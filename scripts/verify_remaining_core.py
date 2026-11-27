"""Disposable regression checks for I13, I18, I20, I21, I23 and I24."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

from zombie_sim.config import initialize_world, resolve_config
from zombie_sim.domain import make_agent
from zombie_sim.engine import Simulation
from zombie_sim.storage import History, canonical


BASE = {"seed":19,"horizon":3,"population":{"humans":6,"zombies":2,
        "human_roles":{"DOCTOR":2,"ENGINEER":2,"WARRIOR":1},"zombie_roles":{"RUNNER":1}},
        "execution":{"workers":1},"interventions_enabled":True}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def signal_child(phase,directory,backend):
    """Deliver real SIGINT at known vulnerable phases, including worker spawn."""
    from unittest.mock import patch
    from zombie_sim import cli, engine, runtime
    from zombie_sim.interrupts import BoundaryProcessPool
    directory=Path(directory)
    config=deepcopy(BASE)
    config["storage"]={"backend":backend}
    config["execution"]={"workers":2 if phase=="pool" else 1,"parallel_min_agents":2}
    if phase.startswith("resume"):
        cli._headless_run(config,directory,until=".5")
    fired=[]
    def fire():
        if not fired:
            fired.append(phase)
            if phase=="pool":os.killpg(os.getpgrp(),signal.SIGINT)
            else:os.kill(os.getpid(),signal.SIGINT)
            os.kill(os.getpid(),signal.SIGINT)  # repeated requests cannot tear saving
    if phase=="initialize":
        original=engine.initialize_world
        def hook(*args,**kwargs):
            fire();return original(*args,**kwargs)
        target,attribute=engine,"initialize_world"
    elif phase in {"dirty","resume_dirty"}:
        original=Simulation._commit
        def hook(self,*args,**kwargs):
            if self._dirty:fire()
            return original(self,*args,**kwargs)
        target,attribute=Simulation,"_commit"
    elif phase in {"checkpoint","resume_checkpoint"}:
        original=History.save_checkpoint
        def hook(self,*args,**kwargs):
            fire();return original(self,*args,**kwargs)
        target,attribute=History,"save_checkpoint"
    elif phase=="resume":
        original=runtime.restore_revision
        def hook(*args,**kwargs):
            result=original(*args,**kwargs);fire();return result
        target,attribute=runtime,"restore_revision"
    else:
        original=BoundaryProcessPool.submit
        def hook(self,*args,**kwargs):
            result=original(self,*args,**kwargs);fire();return result
        target,attribute=BoundaryProcessPool,"submit"
    with patch.object(target,attribute,hook):
        if phase.startswith("resume"):
            assert cli.main(["resume",str(directory),"--until","1"])==0
        else:
            source=directory.parent/(directory.name+".json")
            source.write_text(canonical(config))
            assert cli.main(["run",str(source),"--output",str(directory),"--until","1"])==0
    assert fired,phase
    manifest=json.loads((directory/"manifest.json").read_text())
    history=History(directory/"run.sqlite",read_only=True)
    try:
        expected=history.state_at()
        assert manifest["revision"]==history.revision
        assert manifest["time"]==str(expected["time"])
    finally:history.close()
    restored=Simulation.restore(directory/"checkpoint.json")
    try:
        assert restored.state==expected
        assert not restored._dirty
        restored.advance_until(3)
        assert restored.run_status=="COMPLETED"
    finally:restored.close()
    assert manifest["status"]=="interrupted"
    assert not list(directory.rglob("*.partial"))
    if Path("/proc").exists():
        children=Path(f"/proc/{os.getpid()}/task/{os.getpid()}/children").read_text().split()
        for child in children:
            command=Path(f"/proc/{child}/cmdline").read_bytes()
            assert b"spawn_main" not in command,command
    print(canonical({"phase":phase,"backend":backend,"status":manifest["status"],
                     "revision":manifest["revision"],"exact_checkpoint_restore":True,"workers_closed":True}))


def main():
    if len(sys.argv)>1 and sys.argv[1]=="--signal-child":
        signal_child(*sys.argv[2:]);return
    from zombie_sim.cli import _headless_run, _resume_headless, _run_lease
    report={"status":"PASS","checks":[]}
    def passed(name,**details):report["checks"].append({"check":name,**details})
    with tempfile.TemporaryDirectory(prefix="zombie-remaining-core-") as temporary:
        root=Path(temporary)
        for backend in ("memory","sqlite"):
            for status in ("terminated","completed","stopped","interrupted"):
                directory=root/f"{backend}-{status}"
                _headless_run(BASE,directory,backend=backend,until=".5" if status!="completed" else 3)
                history=History(directory/"run.sqlite")
                history.finish_command({"command_id":"control","run_id":"check","status":"applied"},
                                       {"status":status,"generation":1,"pacing":0})
                revision=history.revision
                history.close()
                before={p.name:digest(p) for p in directory.iterdir() if p.suffix in (".sqlite",".json")}
                try:result=_resume_headless(directory,None,root)
                except ValueError as error:
                    assert status=="terminated" and "terminated" in str(error)
                else:
                    assert status!="terminated"
                    assert result["status"]=="completed"
                if status in {"terminated","completed"}:
                    assert before=={p.name:digest(p) for p in directory.iterdir() if p.suffix in (".sqlite",".json")}
                    history=History(directory/"run.sqlite",read_only=True)
                    assert history.revision==revision
                    # Terminal replay remains readable and branching is allowed.
                    assert history.state_at()["agents"]
                    history.close()
                    parent=Simulation.restore_revision(directory/"run.sqlite")
                    try:
                        branch=parent.branch(root/f"branch-{backend}-{status}")
                        branch.close()
                    finally:parent.close()
                passed("terminal_continuation",backend=backend,run_status=status,immutable=status in {"terminated","completed"})
        locked=root/"memory-stopped"
        with _run_lease(locked):
            try:_resume_headless(locked,None,root)
            except ValueError as error:assert "active coordinator" in str(error)
            else:raise AssertionError("Concurrent lease admitted")
        passed("active_coordinator_rejected")

        reordered=deepcopy(BASE)
        reordered["population"]["human_roles"]=dict(reversed(list(BASE["population"]["human_roles"].items())))
        a,b=resolve_config(BASE),resolve_config(reordered)
        assert a["fingerprint"]==b["fingerprint"]
        assert initialize_world(a)==initialize_world(b)
        encoded=root/"reordered.toml"
        encoded.write_text('seed=19\nhorizon=3\ninterventions_enabled=true\n[population]\nhumans=6\nzombies=2\n[population.human_roles]\nWARRIOR=1\nENGINEER=2\nDOCTOR=2\n[population.zombie_roles]\nRUNNER=1\n[execution]\nworkers=1\n')
        assert resolve_config(encoded)["fingerprint"]==a["fingerprint"]
        assert initialize_world(encoded)==initialize_world(a)
        legacy=deepcopy(a);legacy.pop("role_assignment_order")
        assert resolve_config(legacy)["role_assignment_order"]=="legacy_insertion_v1"
        assert a["provenance"]["role_assignment_order"]=="canonical_v2"
        passed("role_order_json_toml_identity",version=a["role_assignment_order"])

        if len(sys.argv)>2:
            # The reviewer can supply an immutable pre-fix source snapshot.
            # Produce its actual checkpoint/continuation in a disposable directory.
            source=Path(sys.argv[2]).absolute()
            environment={**os.environ,"PYTHONPATH":str(source/"src"),
                         "ZOMBIE_ONTOLOGY_DIR":str(Path("ontology/formal_v0.1").absolute())}
            legacy_config=root/"legacy-config.json";legacy_config.write_text(canonical(BASE))
            code='''import json,sys
from pathlib import Path
from zombie_sim.engine import Simulation
from zombie_sim.storage import canonical
root=Path(sys.argv[1]);sim=Simulation(json.loads((root/"legacy-config.json").read_text()),workers=1)
sim.advance_until(".5");sim.checkpoint(root/"legacy.json");sim.advance_until(3)
(root/"legacy-expected.json").write_text(canonical({"state":sim.state,"events":list(sim.events),"decisions":list(sim.decisions),"draws":list(sim.random_draws)}));sim.close()
'''
            run=subprocess.run([sys.executable,"-c",code,str(root)],env=environment,text=True,capture_output=True,timeout=60)
            assert run.returncode==0,run.stderr
            before={p.name:digest(p) for p in root.glob("legacy.*") if p.is_file()}
            expected=json.loads((root/"legacy-expected.json").read_text())
            restored=Simulation.restore(root/"legacy.json")
            try:
                assert "role_assignment_order" not in restored.config
                restored.advance_until(3)
                assert json.loads(canonical({"state":restored.state,"events":list(restored.events),"decisions":list(restored.decisions),"draws":list(restored.random_draws)}))==expected
            finally:restored.close()
            after={name:digest(root/name) for name in before}
            assert before==after,{name:(before[name],after[name]) for name in before if before[name]!=after[name]}
            passed("pre_fix_checkpoint_exact_continuation",source=str(source),original_checkpoint_unchanged=True)

        for kind,field,bad in (("Human","human_model","ZombieDefaultModel"),("Zombie","zombie_model","HumanDefaultModel")):
            for route in ("default","agent","state_import"):
                config=deepcopy(BASE)
                if route=="default":config[field]=bad
                else:
                    config["agents"]=[{"id":"a","type":kind,"x":5,"y":5,"model_assignment":{"model_id":bad}}]
                    if route=="state_import":config["state_import"]=True
                path=root/f"bad-{kind}-{route}.sqlite"
                try:Simulation(config,history_path=path)
                except ValueError as error:assert getattr(error,"code",None)=="INCOMPATIBLE_MODEL",str(error)
                else:raise AssertionError("Incompatible model accepted")
                assert not path.exists()
                passed("model_applicability",agent_type=kind,assignment_route=route,rejected_before_history=True)
            assert make_agent("valid",kind,model_assignment={"model_id":"randomLegal"})["model_assignment"]["model_id"]=="randomLegal"
        for backend in ("memory","sqlite"):
            sim=Simulation(BASE,backend=backend)
            try:
                before=sim.serialize()
                try:sim.intervene({"kind":"replace_model","agent":"1","model_id":"ZombieDefaultModel","memory_policy":"reset"})
                except ValueError as error:assert getattr(error,"code",None)=="INCOMPATIBLE_MODEL"
                else:raise AssertionError("Incompatible intervention accepted")
                assert sim.serialize()==before
                sim.intervene({"kind":"replace_model","agent":"1","model_id":"randomLegal","memory_policy":"reset"})
                sim.advance_until(0)
                assert sim.state["agents"]["1"]["model_assignment"]["model_id"]=="randomLegal"
            finally:sim.close()
            conversion={"horizon":2,"incubation_duration":1,"zombie_model":"randomLegal","decision_mode":"scripted",
                        "interventions_enabled":True,"agents":[{"id":"h","type":"Human","x":5,"y":5,"infected":True}]}
            sim=Simulation(conversion,backend=backend,workers=1)
            try:
                sim.memories["h"]={"old_human_memory":True}
                sim.intervene({"kind":"replace_model","agent":"h","model_id":"HumanDefaultModel","memory_policy":"reset"},at="1.5")
                sim.advance_until(1)
                assert sim.state["agents"]["h"]["model_assignment"]["model_id"]=="randomLegal"
                assert "old_human_memory" not in sim.memories.get("h",{})
                sim.advance_until("1.5")
                assert list(sim.state["interventions"].values())[0]["status"]=="REJECTED"
                assert sim.state["agents"]["h"]["model_assignment"]["model_id"]=="randomLegal"
                sim.checkpoint(root/f"converted-{backend}.json")
            finally:sim.close()
            saved=Simulation.restore(root/f"converted-{backend}.json")
            try:assert saved.state["agents"]["h"]["model_assignment"]["model_id"]=="randomLegal"
            finally:saved.close()
            passed("intervention_effective_type_and_conversion_default",backend=backend)

        for backend in ("memory","sqlite"):
            for imported in (False,True):
                config={"human_model":"randomLegal","zombie_model":"randomLegal","horizon":1,"agents":[
                    {"id":"h","type":"Human","x":5,"y":5},
                    {"id":"z","type":"Zombie","x":50,"y":50},
                    {"id":"h-explicit","type":"Human","x":5,"y":8,"model_assignment":{"model_id":"HumanDefaultModel"}},
                    {"id":"z-explicit","type":"Zombie","x":50,"y":53,"model_assignment":{"model_id":"ZombieDefaultModel"}}]}
                if imported:
                    config["state_import"]=True
                    config["agents"].append({"id":"dead","type":"Human","life":0,"x":20,"y":20,"model_assignment":None})
                sim=Simulation(config,backend=backend,workers=1)
                try:
                    models={key:agent["model_assignment"] for key,agent in sim.state["agents"].items()}
                    assert models["h"]["model_id"]==models["z"]["model_id"]=="randomLegal"
                    assert models["h-explicit"]["model_id"]=="HumanDefaultModel"
                    assert models["z-explicit"]["model_id"]=="ZombieDefaultModel"
                    if imported:assert models["dead"] is None
                    sim.advance_until(1)
                    assert all("fallback_reason" not in row.get("diagnostics",{}) for row in sim.decisions)
                    path=root/f"explicit-default-{backend}-{imported}.json"
                    sim.checkpoint(path)
                finally:sim.close()
                saved=Simulation.restore(path)
                try:assert {key:agent["model_assignment"] for key,agent in saved.state["agents"].items()}==models
                finally:saved.close()
                passed("explicit_missing_assignment_uses_scenario_default",backend=backend,state_import=imported,
                       explicit_assignments_preserved=True,dead_assignment_preserved=imported)

        for backend in ("memory","sqlite"):
            from unittest.mock import patch
            closed=[]
            original_close=Simulation.close
            def close_record(self):
                original_close(self);closed.append(self._closed)
            failed=root/f"failed-save-{backend}"
            with patch.object(History,"save_checkpoint",side_effect=OSError("controlled checkpoint failure")),patch.object(Simulation,"close",close_record):
                try:_headless_run(BASE,failed,backend=backend,until=".5")
                except OSError as error:assert "controlled" in str(error)
                else:raise AssertionError("Checkpoint error was hidden")
            assert closed==[True]
            manifest=json.loads((failed/"manifest.json").read_text())
            assert manifest["status"]=="failed" and "controlled" in manifest["error"]
            result=_resume_headless(failed,None,root)
            assert result["status"]=="completed"
            assert "error" not in json.loads((failed/"manifest.json").read_text())
            passed("checkpoint_failure_truthful_and_closed",backend=backend,journal_resume_succeeded=True)
            for phase in ("initialize","dirty","checkpoint","resume","resume_dirty","resume_checkpoint","pool"):
                run=subprocess.run([sys.executable,__file__,"--signal-child",phase,str(root/f"signal-{backend}-{phase}"),backend],
                                   text=True,capture_output=True,timeout=60,start_new_session=True)
                assert run.returncode==0,(phase,backend,run.stdout,run.stderr)
                assert "Traceback" not in run.stderr,run.stderr
                passed("sigint_committed_checkpoint",**json.loads(run.stdout.splitlines()[-1]))
    destination=Path(sys.argv[1] if len(sys.argv)>1 else "artifacts/issues13-18-20-21-23/verification.json")
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(report,indent=2)+"\n")
    print(f"PASS: {len(report['checks'])} checks; {destination}")


if __name__=="__main__":main()
