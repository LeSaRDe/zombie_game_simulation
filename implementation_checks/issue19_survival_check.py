"""Independent risk-set oracle using a real cure/conversion/death/movement history."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
import tempfile
import threading

from issue7_cohorts_check import configuration, select_ids, audit
from zombie_sim.application import RunManager, ViewCancelled
from zombie_sim.engine import Simulation
from zombie_sim.runtime import branch
from zombie_sim.storage import canonical, exact_time
from zombie_sim.visualization import project_state


def verify(manager, run_id, history, entries):
    observations = []
    cursors = [(str(exact_time({"n": n, "d": d})), r) for r, n, d in
               history.connection.execute("SELECT revision,time_n,time_d FROM commits ORDER BY revision")]
    start=exact_time(cursors[0][0]);end=exact_time(cursors[-1][0])
    cursors += [(str(start+offset),None) for offset in (exact_time("1/3"),exact_time("5/2")) if start+offset<=end]
    for time, revision in cursors + list(reversed(cursors)):
        raw = project_state(history.state_at(time=time, revision=revision), time)
        entry=entries[raw["run_id"]]
        response = manager.cohort_view(run_id, time=time, revision=revision)
        for item in response["cohorts"]:
            members = select_ids(raw, item["definition"])
            assert sorted(item["members"]) == members
            dead_at_entry={identity for identity in members if entry["agents"][identity]["life"]==0}
            eligible_identities=[identity for identity in members if identity not in dead_at_entry]
            eligible_humans = [identity for identity in eligible_identities if entry["agents"][identity]["type"] == "Human"]
            deaths = {identity for identity in members if raw["agents"][identity]["life"] == 0}
            human_events = sum(identity in deaths or raw["agents"][identity]["type"] == "Zombie"
                               for identity in eligible_humans)
            human = item["human_survival"]; identity = item["identity_survival"]
            assert human["events"] == human_events
            assert human["eligible"] == human["denominator"] == len(eligible_humans)
            assert human["censored"] == len(eligible_humans) - human_events
            assert human["excluded_non_human"] == len(eligible_identities) - len(eligible_humans)
            assert human["excluded_unknown_entry"] == human["missing_at_cursor"] == 0
            assert human["excluded_dead_at_entry"]==identity["excluded_dead_at_entry"]==len(dead_at_entry)
            assert identity["events"] == len(deaths-dead_at_entry)
            assert identity["eligible"] == identity["denominator"] == len(eligible_identities)
            assert identity["censored"] == len(eligible_identities) - len(deaths-dead_at_entry)
            assert human["entry_time"] == identity["entry_time"] == str(entry["time"])
            assert human["entry_revision"] == identity["entry_revision"] == str(entry["revision"])
            assert human["entry_run_id"] == identity["entry_run_id"] == entry["run_id"]
            assert item["survival_measurement_version"] == "zombie-sim/cohort-survival-v3"
        observations.append({"time": time, "revision": response["cursor"]["revision"], "cohorts": len(response["cohorts"]),
                             "entry_run_id":entry["run_id"],"entry_time":str(entry["time"]),"entry_revision":str(entry["revision"])})
    return observations


def definitions(manager, run_id, *, entry_time="0", conversion_time="3"):
    for mode in ("fixed", "dynamic"):
        for kind in ("Human", "Zombie", None):
            manager.save_cohort(run_id, {"name": f"{mode} {kind or 'mixed'}", "mode": mode,
                "predicate": {"type": kind} if kind else {}, "include_dead": True,
                "reference_time": entry_time, "reference_revision": "0"})
    if conversion_time is not None:
        manager.save_cohort(run_id, {"name": "Zombies after conversion", "mode": "fixed",
            "predicate": {"type": "Zombie"}, "include_dead": True, "reference_time": conversion_time})


def register(manager,sim,directory):
    with manager.connection:
        manager.connection.execute("INSERT INTO runs(id,directory,config,status,frontier) VALUES(?,?,?,?,?)",
            (sim.state["run_id"],str(directory),canonical(sim.config),"terminated",
             canonical({"revision":str(sim.revision),"time":str(sim.time),"pacing":0})))


def main():
    report = {"passed": False}
    with tempfile.TemporaryDirectory(prefix="zombie-i19-") as tmp:
        root = Path(tmp); directory = root / "runs" / "lifecycle"; directory.mkdir(parents=True)
        config = configuration()
        sim = Simulation(config, history_path=directory / "run.sqlite", decision_mode="scripted", run_id="lifecycle")
        entries={"lifecycle":deepcopy(sim.state)}
        manager = RunManager(root)
        try:
            sim.submit_intents([
                {"actor": "warrior", "action": "melee", "target": "target"},
                {"actor": "doctor", "action": "treat_infection", "target": "patient"},
                {"actor": "biter", "action": "bite", "target": "victim"},
                {"actor": "killer", "action": "claw", "target": "doomed"},
                {"actor": "walker", "action": "move", "parameters": {"duration": 2,
                 "path": [{"x": 60, "y": 60, "offset": 0}, {"x": 64, "y": 60, "offset": 2}]}},
            ])
            sim.advance_until(4, return_snapshot=False)
            register(manager,sim,directory)
            definitions(manager, "lifecycle")
            before = audit(directory / "run.sqlite", manager, "lifecycle")
            report["parent_cursors"] = verify(manager, "lifecycle", sim.history, entries)
            assert audit(directory / "run.sqlite", manager, "lifecycle") == before
            zombie_only = next(x for x in manager.cohort_view("lifecycle")["cohorts"] if x["definition"]["name"] == "fixed Zombie")
            assert zombie_only["human_survival"]["eligible"] == zombie_only["human_survival"]["events"] == 0
            assert zombie_only["identity_survival"]["events"] == 1
            report["zombie_only"] = zombie_only["human_survival"]
            child = branch(sim, root / "runs" / "child", run_id="child")
            try:
                entries["child"]=deepcopy(child.state)
                register(manager,child,root/"runs"/"child")
                definitions(manager, "child")
                child_before=audit(root/"runs"/"child"/"run.sqlite",manager,"child")
                report["branch_after_conversion_cursors"] = verify(manager, "child", child.history, entries)
                mixed=next(item for item in manager.cohort_view("child")["cohorts"] if item["definition"]["name"]=="fixed mixed")
                assert mixed["human_survival"]["events"]==mixed["identity_survival"]["events"]==0
                assert mixed["identity_survival"]["excluded_dead_at_entry"]==2
                nested=branch(child,root/"runs"/"nested",run_id="nested")
                try:
                    entries["nested"]=deepcopy(nested.state)
                    register(manager,nested,root/"runs"/"nested")
                    definitions(manager,"nested")
                    nested_before=audit(root/"runs"/"nested"/"run.sqlite",manager,"nested")
                    report["nested_branch_cursors"]=verify(manager,"nested",nested.history,entries)
                    assert {row["entry_run_id"] for row in report["nested_branch_cursors"]}=={"lifecycle","child","nested"}
                    assert audit(root/"runs"/"nested"/"run.sqlite",manager,"nested")==nested_before
                finally:nested.close()
                assert audit(root/"runs"/"child"/"run.sqlite",manager,"child")==child_before
            finally: child.close()
            source=Simulation.restore_revision(directory/"run.sqlite",revision=sim.history.state_at(time="1/2")["revision"])
            try:
                early=branch(source,root/"runs"/"early",run_id="early")
                try:
                    entries["early"]=deepcopy(early.state)
                    early.advance_until(4,return_snapshot=False)
                    register(manager,early,root/"runs"/"early")
                    definitions(manager,"early")
                    early_before=audit(root/"runs"/"early"/"run.sqlite",manager,"early")
                    report["branch_before_conversion_cursors"]=verify(manager,"early",early.history,entries)
                    mixed=next(item for item in manager.cohort_view("early")["cohorts"] if item["definition"]["name"]=="fixed mixed")
                    assert mixed["human_survival"]["events"]>0
                    assert mixed["human_survival"]["entry_time"]=="1/2"
                    assert audit(root/"runs"/"early"/"run.sqlite",manager,"early")==early_before
                finally:early.close()
            finally:source.close()

            for backend in ("memory","sqlite"):
                imported_id="imported-"+backend;imported_dir=root/"runs"/imported_id;imported_dir.mkdir()
                imported=Simulation({"time":10,"horizon":12,"state_import":True,"agents":[
                    {"id":"dead-human","type":"Human","life":0,"x":10,"y":10},
                    {"id":"dead-zombie","type":"Zombie","life":0,"x":20,"y":20},
                    {"id":"living-human","type":"Human","x":30,"y":30},
                    {"id":"living-zombie","type":"Zombie","x":80,"y":80}]},
                    history_path=imported_dir/"run.sqlite",backend=backend,workers=1,decision_mode="scripted",run_id=imported_id)
                try:
                    entries[imported_id]=deepcopy(imported.state);imported.advance_until(12,return_snapshot=False)
                    register(manager,imported,imported_dir)
                    definitions(manager,imported_id,entry_time="10",conversion_time=None)
                    imported_before=audit(imported_dir/"run.sqlite",manager,imported_id)
                    report[imported_id+"_cursors"]=verify(manager,imported_id,imported.history,entries)
                    mixed=next(item for item in manager.cohort_view(imported_id)["cohorts"] if item["definition"]["name"]=="fixed mixed")
                    assert mixed["human_survival"]["eligible"]==1 and mixed["identity_survival"]["eligible"]==2
                    assert mixed["human_survival"]["events"]==mixed["identity_survival"]["events"]==0
                    assert mixed["human_survival"]["excluded_dead_at_entry"]==mixed["identity_survival"]["excluded_dead_at_entry"]==2
                    assert audit(imported_dir/"run.sqlite",manager,imported_id)==imported_before
                finally:imported.close()
            from zombie_sim.cohort_survival import survival_counts
            unknown=survival_counts([{"id":"unknown","type":"Human","life":100}],entries["lifecycle"],missing=2)
            for label in ("human_survival","identity_survival"):
                assert unknown[label]["eligible"]==unknown[label]["events"]==unknown[label]["censored"]==0
                assert unknown[label]["excluded_unknown_entry"]==1 and unknown[label]["missing_at_cursor"]==2
            report["unknown_and_missing"]=unknown
            cancelled = threading.Event(); cancelled.set()
            try: manager.cohort_view("lifecycle", cancel_event=cancelled)
            except ViewCancelled: pass
            else: raise AssertionError("Cohort load ignored cancellation")
            assert audit(directory / "run.sqlite", manager, "lifecycle") == before
            report.update(passed=True, histories_unchanged=True,
                          checks=["Human-only, Zombie-only, mixed fixed/dynamic risk sets", "Post-conversion membership uses historical entry types",
                                  "Conversion ends Human interval; death ends identity interval; surviving eligible members censored",
                                  "Every causal revision, fractional replay and reverse order", "Actual child entry before/after conversion; nested prefixes select source-run entry",
                                  "Dead-at-entry branch/import identities excluded; both import backends", "Unknown entry and missing cursor members explicitly excluded", "Cancellation"],
                          measurement_version="zombie-sim/cohort-survival-v3")
        finally:
            manager.close(); sim.close()
    Path("artifacts/issue19-survival.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: len(v) if k.endswith("cursors") else v for k, v in report.items()}, indent=2))


if __name__ == "__main__": main()
