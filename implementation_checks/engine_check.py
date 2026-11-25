"""Implementation verification derived from ontology §§6,9,14–16.

This command deliberately does not import or discover the separately supplied
acceptance suite. It checks real simulator traces and store/worker comparisons.
"""
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
import json
import tempfile

from zombie_sim.engine import Simulation
from zombie_sim.config import resolve_config


def scene(agents,**options):
    return {"agents":agents,"world":{"length":40.,"width":40.},"horizon":30.,
            "placement":{"minimum_separation":0.,"cross_type_separation":0.},
            "decision_mode":"scripted",**options}


def person(id,**fields):
    return {"id":id,"type":"Human","x":5.,"y":5.,**fields}


def normalized(snapshot):
    snapshot=deepcopy(snapshot)
    snapshot.pop("run_id",None)
    return snapshot


def main():
    report={}
    # Exact incubation precedence and preservation, independently selected values.
    config=scene([person("medic",role="DOCTOR",stamina=91.,inventory={"MEDICAL_SUPPLY":2}),
                  person("patient",x=6.,life=43,stamina=61.,infected=True)],incubation_duration=4.)
    with Simulation(config) as sim:
        result=sim.submit_intents([{"actor":"medic","action":"treat_infection","target":"patient"}])[0]
        sim.advance_until(4)
        state=sim.snapshot();patient=state["agents"]["patient"]
        assert patient["type"]=="Zombie" and patient["life"]==43 and patient["stamina"]==61
        assert sim.occurrences[result["occurrence_id"]]["result"]=="FAILED_PRECONDITION"
        assert state["agents"]["medic"]["inventory"]["MEDICAL_SUPPLY"]==2
        assert not state["reservations"]
    config["incubation_duration"]=4.0001
    with Simulation(config) as sim:
        sim.submit_intents([{"actor":"medic","action":"treat_infection","target":"patient"}])
        sim.advance_until(4)
        assert sim.snapshot()["agents"]["patient"]["status"]=="HEALTHY"
    report["cure_deadline_and_preservation"]="PASS"
    # Idle clocks are continuous and do not depend on policy decisions.
    with Simulation(scene([person("hungry",hunger=99.5,life=2)],horizon=40.)) as sim:
        sim.advance_until(10)
        assert sim.snapshot()["agents"]["hungry"]["hunger"]==100
        sim.advance_until(20)
        assert sim.snapshot()["agents"]["hungry"]["life"]==1
        sim.advance_until(30)
        assert sim.snapshot()["agents"]["hungry"]["life"]==0
        assert len(sim.state["remains"])==1 and sim.termination_reason=="NO_LIVING_AGENTS"
    report["idle_starvation_and_terminal_death"]="PASS"
    # Stopping at the horizon finishes every due action, even through atomic steps.
    with Simulation(scene([person("one",stamina=20.),person("two",x=7.,stamina=30.)],horizon=2.)) as sim:
        sim.submit_intents([{"actor":aid,"action":"rest","parameters":{"duration":2}} for aid in ("one","two")])
        while sim.run_status!="COMPLETED":sim.step(return_snapshot=False)
        assert all(o["result"]=="SUCCEEDED" for o in sim.occurrences.values())
        assert [sim.snapshot()["agents"][a]["stamina"] for a in ("one","two")]==[28.,38.]
    report["horizon_atomic_steps"]="PASS"
    # All workers start from the same observations; publication order is fixed.
    base=resolve_config("configs/small.toml");base["horizon"]=12.
    traces=[]
    for backend,workers in (("memory",1),("sqlite",1),("memory",2)):
        with Simulation(base,backend=backend,workers=workers) as sim:
            sim.advance_until(12,return_snapshot=False)
            traces.append((normalized(sim.snapshot()),deepcopy(sim.events),deepcopy(sim.random_draws)))
    assert traces[0]==traces[1]==traces[2]
    report["memory_sqlite_two_worker_equivalence"]="PASS"
    # Persist a busy action, then continue with a fresh interpreter-owned store.
    with tempfile.TemporaryDirectory() as directory:
        with Simulation(scene([person("walker",stamina=63.)])) as original:
            original.submit_intents([{"actor":"walker","action":"move","parameters":{"duration":2,
                "path":[{"x":5.,"y":5.,"offset":0},{"x":9.,"y":5.,"offset":2}]}}])
            original.advance_until(Fraction(1,3));path=original.checkpoint(Path(directory)/"busy.json")
            with Simulation.restore(path,backend="sqlite") as resumed:
                original.advance_until(2);resumed.advance_until(2)
                assert original.snapshot()==resumed.snapshot()
                assert original.events==resumed.events and original.queue==resumed.queue
    report["exact_busy_restart"]="PASS"
    output=Path("artifacts/implementation");output.mkdir(parents=True,exist_ok=True)
    (output/"engine_checks.json").write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=="__main__":main()
