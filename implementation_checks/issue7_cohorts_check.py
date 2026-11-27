"""I07 cohort measurements checked against independent full-history projections.

Uses a disposable real engine with cure, exposure, conversion, death and motion.
Only analysis definitions are added to its separate manager journal. No user
workspace, existing history, ontology or supplied acceptance fixture is changed.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import threading

from zombie_sim.application import RunManager, ViewCancelled
from zombie_sim.engine import Simulation
from zombie_sim.storage import History, canonical, exact_time
from zombie_sim.visualization import project_state


def configuration():
    return {
        "scenario": "issue7_real_transitions", "seed": 267, "horizon": 4,
        "incubation_duration": 2, "execution": {"workers": 1},
        "placement": {"minimum_separation": 0, "cross_type_separation": 0},
        "profiles": {"Human": {"combat_skill": 1, "infection_resistance": 0},
                     "WARRIOR": {"combat_skill": 1},
                     "DOCTOR": {"medical_skill": 1, "treatment_duration": .5},
                     "Zombie": {"attack_skill": 1, "virulence": 1}},
        "agents": [
            {"id": "warrior", "type": "Human", "role": "WARRIOR", "x": 10, "y": 10},
            {"id": "target", "type": "Zombie", "x": 11, "y": 10, "life": 10},
            {"id": "doctor", "type": "Human", "role": "DOCTOR", "x": 30, "y": 30,
             "inventory": {"MEDICAL_SUPPLY": 2}},
            {"id": "patient", "type": "Human", "x": 31, "y": 30, "infected": True},
            {"id": "converter", "type": "Human", "x": 80, "y": 80, "infected": True},
            {"id": "biter", "type": "Zombie", "x": 50, "y": 50},
            {"id": "victim", "type": "Human", "x": 51, "y": 50},
            {"id": "walker", "type": "Human", "x": 60, "y": 60, "stamina": 50},
            {"id": "doomed", "type": "Human", "x": 15, "y": 15, "life": 10},
            {"id": "killer", "type": "Zombie", "x": 16, "y": 15},
        ],
    }


def audit(path, manager, run_id):
    digest = hashlib.sha256()
    sizes = {}
    with sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True) as database:
        for table in ("commits", "runtime_commits", "events", "control_commands", "metadata"):
            digest.update(table.encode()); sizes[table] = 0
            for row in database.execute(f"SELECT * FROM {table} ORDER BY rowid"):
                sizes[table] += 1
                for value in row:
                    encoded = value if isinstance(value, bytes) else repr(value).encode()
                    digest.update(len(encoded).to_bytes(8, "big")); digest.update(encoded)
    with manager.lock:
        row = dict(manager.connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())
        commands = manager.connection.execute("SELECT COUNT(*) FROM commands WHERE run_id=?", (run_id,)).fetchone()[0]
    return {"ledger_sha256": digest.hexdigest(), "rows": sizes, "run": row, "commands": commands}


def known_status(agent):
    if agent["life"] == 0:
        return "DEAD"
    if agent["type"] == "Zombie":
        return "ACTIVE"
    return "INFECTED" if agent.get("infection_episode") else "HEALTHY"


def select_ids(state, definition):
    """Independent predicate oracle; does not call cohort implementation helpers."""
    if definition["mode"] == "fixed":
        return sorted(definition["members"])
    expected = []
    predicate = definition.get("predicate", {})
    for identity, agent in state["agents"].items():
        status = known_status(agent)
        if not definition.get("include_dead", True) and status == "DEAD":
            continue
        model = agent.get("model_assignment")
        if isinstance(model, dict):
            model = model.get("model_id")
        values = {"type": agent["type"], "role": agent.get("role"),
                  "status": status, "model_assignment": model}
        if any(value != "" and values[key] != value for key, value in predicate.items() if key != "region"):
            continue
        if "region" in predicate:
            left, bottom, right, top = predicate["region"]
            if not left <= agent["x"] <= right or not bottom <= agent["y"] <= top:
                continue
        expected.append(str(identity))
    return sorted(expected)


def verify_summary(state, item):
    expected = select_ids(state, item["definition"])
    assert sorted(item["members"]) == expected
    assert sorted(item["member_ids"]) == expected
    assert item["denominator"] == len(expected)
    agents = [state["agents"][identity] for identity in expected if identity in state["agents"]]
    assert item["present"] == len(agents)
    counts = {"healthy": 0, "infected": 0, "zombies": 0, "dead": 0}
    for agent in agents:
        key = {"HEALTHY": "healthy", "INFECTED": "infected", "ACTIVE": "zombies", "DEAD": "dead"}[known_status(agent)]
        counts[key] += 1
    counts["total"] = len(agents)
    assert item["populations"] == counts
    for field in ("life", "stamina"):
        assert item[f"mean_{field}_denominator"] == len(agents)
        if agents:
            expected_mean = sum(agent[field] for agent in agents) / len(agents)
            assert math.isclose(item[f"mean_{field}"], expected_mean, rel_tol=1e-12, abs_tol=1e-12)
        else:
            assert item[f"mean_{field}"] is None
    totals = {}; reserved = {}
    for agent in agents:
        for key, quantity in agent.get("inventory", {}).items(): totals[key] = totals.get(key, 0) + quantity
        for key, quantity in agent.get("reserved", {}).items(): reserved[key] = reserved.get(key, 0) + quantity
    assert item["resources"] == {"available_and_reserved": totals, "reserved_subset": reserved}
    return {"id": item["definition"]["id"], "members": expected, "counts": counts}


def rejects(operation):
    try:
        operation()
    except ValueError as error:
        return str(error)
    raise AssertionError("Malformed cohort request was accepted")


def run_check(output):
    report = {"passed": False}
    with tempfile.TemporaryDirectory(prefix="zombie-issue7-cohorts-") as temporary:
        root = Path(temporary); run_id = "issue7-real"
        directory = root / "runs" / run_id; directory.mkdir(parents=True)
        path = directory / "run.sqlite"
        simulation = Simulation(configuration(), history_path=path, decision_mode="scripted", run_id=run_id)
        manager = RunManager(root)
        try:
            simulation.submit_intents([
                {"actor": "warrior", "action": "melee", "target": "target"},
                {"actor": "doctor", "action": "treat_infection", "target": "patient"},
                {"actor": "biter", "action": "bite", "target": "victim"},
                {"actor": "killer", "action": "claw", "target": "doomed"},
                {"actor": "walker", "action": "move", "parameters": {"duration": 2,
                 "path": [{"x": 60, "y": 60, "offset": 0}, {"x": 64, "y": 60, "offset": 2}]}},
            ])
            for time in ("1/2", "1", "3/2", "2", "3", "4"):
                simulation.advance_until(time, return_snapshot=False)
            with manager.connection:
                manager.connection.execute("INSERT INTO runs(id,directory,config,status,frontier) VALUES(?,?,?,?,?)",
                    (run_id, str(directory), canonical(simulation.config), "terminated",
                     canonical({"revision": str(simulation.revision), "time": str(simulation.time), "pacing": 0})))
            before = audit(path, manager, run_id)
            runtime_before = canonical(simulation.serialize())
            history = History(path, read_only=True)
            try:
                assert manager.cohort_view(run_id)["cohorts"] == []
                initial = project_state(history.state_at(revision=0))
                human_model = initial["agents"]["warrior"]["model_assignment"]["model_id"]
                definitions = {}
                specs = [
                    ("fixed humans", "fixed", {"type": "Human"}, True),
                    ("dynamic humans", "dynamic", {"type": "Human"}, True),
                    ("living humans", "dynamic", {"type": "Human"}, False),
                    ("fixed initially living", "fixed", {"type": "Human"}, False),
                    ("initially infected", "fixed", {"status": "INFECTED"}, True),
                    ("currently infected", "dynamic", {"status": "INFECTED"}, True),
                    ("doctor", "dynamic", {"role": "DOCTOR"}, True),
                    ("no active role", "dynamic", {"role": None}, True),
                    ("human controller", "dynamic", {"model_assignment": human_model}, True),
                    ("human active is empty", "dynamic", {"type": "Human", "status": "ACTIVE"}, True),
                    ("nonexistent model is empty", "dynamic", {"model_assignment": "no-such-model"}, True),
                    ("corner", "dynamic", {"region": [0, 0, 20, 20]}, True),
                    ("all identities", "dynamic", {}, True),
                    ("dead identities", "dynamic", {"status": "DEAD"}, True),
                ]
                for name, mode, predicate, include_dead in specs:
                    original = {"name": name, "mode": mode, "predicate": predicate,
                                "include_dead": include_dead, "reference_revision": "0", "reference_time": "0"}
                    copy = deepcopy(original)
                    saved = manager.save_cohort(run_id, original)
                    assert original == copy, "Creation mutated caller-owned input"
                    assert saved["reference_time"] == "0" and str(saved["reference_revision"]) == "0"
                    if mode == "fixed":
                        assert sorted(saved["members"]) == select_ids(initial, dict(saved, mode="dynamic"))
                    definitions[name] = saved
                fractional = manager.snapshot(run_id, time="1/3")
                stored = history.state_at("1/3")
                assert exact_time(stored["time"]) < exact_time("1/3"), "Fractional case must project between commits"
                assert fractional["state"]["agents"]["walker"]["x"] != stored["agents"]["walker"]["x"]
                region = {"region": [60.5, 59, 60.8, 61]}
                projected_definition = manager.save_cohort(run_id, {
                    "name": "fractional region", "mode": "fixed", "predicate": region,
                    "include_dead": True, "reference_time": "1/3", "reference_revision": fractional["revision"]})
                assert projected_definition["members"] == ["walker"]
                assert projected_definition["reference_time"] == "1/3"
                definitions["fractional region"] = projected_definition
                legacy = {"id": "legacy", "name": "Legacy retained", "mode": "fixed", "predicate": {},
                          "reference_revision": "0", "members": ["patient", "converter"], "include_dead": False}
                legacy_bytes = canonical(legacy)
                minimal_legacy = {"id": "legacy-minimal", "mode": "dynamic", "reference_revision": "0"}
                minimal_bytes = canonical(minimal_legacy)
                with manager.connection:
                    manager.connection.execute("INSERT INTO views VALUES(?,?,?)", (run_id, "legacy", legacy_bytes))
                    manager.connection.execute("INSERT INTO views VALUES(?,?,?)", (run_id, "legacy-minimal", minimal_bytes))
                definitions["legacy"] = legacy
                definitions["legacy-minimal"] = minimal_legacy
                observations = []; count = 0
                rows = list(history.connection.execute("SELECT revision,time_n,time_d FROM commits ORDER BY revision"))
                requests = [(str(exact_time({"n": n, "d": d})), revision) for revision, n, d in rows]
                requests += [(time, None) for time in ("1/3", "2/3", "7/4", "5/2", "4", "0")]
                for time, revision in requests + list(reversed(requests)):
                    result = manager.cohort_view(run_id, time=time, revision=revision)
                    state = project_state(history.state_at(time=time, revision=revision), time)
                    assert result["run_id"] == run_id
                    assert result["cursor"] == {"time": str(exact_time(time)), "revision": str(state["revision"])}
                    assert len(result["cohorts"]) == len(definitions)
                    for item in result["cohorts"]:
                        verified = verify_summary(state, item); count += 1
                        assert "reference_time" in item["definition"]
                        if item["definition"]["id"] == "legacy":
                            assert item["definition"]["reference_time"] == "0"
                        if item["definition"]["id"] == "legacy-minimal":
                            assert item["definition"]["name"] == "Unnamed cohort"
                            assert item["definition"]["predicate"] == {}
                            assert item["definition"]["include_dead"] is True
                    observations.append({"time": time, "revision": str(state["revision"]), "cohorts": len(result["cohorts"])})
                final = {item["definition"]["name"]: item for item in manager.cohort_view(run_id)["cohorts"]}
                assert final["fixed humans"]["denominator"] == 7
                assert final["fixed humans"]["populations"] == {"healthy": 4, "infected": 0, "zombies": 2, "dead": 1, "total": 7}
                assert final["fixed initially living"]["members"] == final["fixed humans"]["members"]
                assert final["dynamic humans"]["denominator"] == 5
                assert final["living humans"]["denominator"] == 4
                assert final["currently infected"]["denominator"] == 0
                assert sorted(final["initially infected"]["members"]) == ["converter", "patient"]
                assert sum(item["denominator"] for item in final.values()) > len(simulation.state["agents"]), "Overlapping cohorts are not a partition"
                assert manager.connection.execute("SELECT definition FROM views WHERE id='legacy'").fetchone()[0] == legacy_bytes
                assert manager.connection.execute("SELECT definition FROM views WHERE id='legacy-minimal'").fetchone()[0] == minimal_bytes
                assert isinstance(manager.cohorts(run_id), list), "Existing manager callers retain list results"
                definitions_before = list(manager.connection.execute("SELECT id,definition FROM views ORDER BY id"))
                base = {"name": "invalid", "mode": "dynamic", "predicate": {}, "reference_revision": "0"}
                invalid = {
                    "blank name": dict(base, name="  "), "nonstring name": dict(base, name=23),
                    "mode": dict(base, mode="other"), "mode list": dict(base, mode=[]),
                    "mode object": dict(base, mode={}), "predicate shape": dict(base, predicate=[]),
                    "unknown predicate": dict(base, predicate={"hunger": 50}),
                    "type filter shape": dict(base, predicate={"type": []}),
                    "status filter value": dict(base, predicate={"status": "LIVE"}),
                    "role filter shape": dict(base, predicate={"role": True}),
                    "model filter shape": dict(base, predicate={"model_assignment": {}}),
                    "include_dead type": dict(base, include_dead="false"),
                    "region order": dict(base, predicate={"region": [2, 0, 1, 1]}),
                    "region nonfinite": dict(base, predicate={"region": [0, 0, float("inf"), 1]}),
                    "region missing bound": dict(base, predicate={"region": [0, 0, 1]}),
                    "negative revision": dict(base, reference_revision=-1),
                    "fractional revision": dict(base, reference_revision=1.5),
                    "boolean revision": dict(base, reference_revision=True),
                    "future revision": dict(base, reference_revision=simulation.revision + 1),
                    "negative reference time": dict(base, reference_time="-1"),
                    "future reference time": dict(base, reference_time="5"),
                    "unknown explicit member": dict(base, mode="fixed", members=["missing"]),
                    "duplicate explicit member": dict(base, mode="fixed", members=["patient", "patient"]),
                }
                failures = {label: rejects(lambda definition=definition: manager.save_cohort(run_id, definition)) for label, definition in invalid.items()}
                assert list(manager.connection.execute("SELECT id,definition FROM views ORDER BY id")) == definitions_before
                cancelled = threading.Event(); cancelled.set()
                try:
                    manager.cohort_view(run_id, time="1/3", cancel_event=cancelled)
                except ViewCancelled:
                    pass
                else:
                    raise AssertionError("Already-cancelled cohort read completed")
                with ThreadPoolExecutor(max_workers=4) as pool:
                    concurrent = list(pool.map(lambda time: manager.cohort_view(run_id, time=time), ["0", "1/3", "3/2", "4"]))
                for result in concurrent:
                    state = project_state(history.state_at(time=result["cursor"]["time"], revision=int(result["cursor"]["revision"])), result["cursor"]["time"])
                    for item in result["cohorts"]: verify_summary(state, item)
                response = manager.cohort_view(run_id, time="4")
                selected = next(item for item in response["cohorts"] if item["definition"]["name"] == "fixed humans")
                first_id = selected["definition"]["id"]
                first_members = list(selected["members"])
                assert first_members
                selected["members"].clear()
                fresh = next(item for item in manager.cohort_view(run_id, time="4")["cohorts"] if item["definition"]["id"] == first_id)
                assert fresh["members"] == first_members
                assert audit(path, manager, run_id) == before
                assert canonical(simulation.serialize()) == runtime_before
                assert simulation.execution_counters == {"policy_calls": 0, "bernoulli_calls": 4}
                outcomes = sorted(episode["outcome"] for episode in simulation.state["episodes"].values())
                assert outcomes == ["CONVERTED", "CONVERTED", "CURED"]
                report.update(passed=True, engine={"agents": 10, "commits": len(rows), "modeled_seconds": 4,
                    "episode_outcomes": outcomes, "deaths": 2, "execution_counters": simulation.execution_counters},
                    definitions=len(definitions), summary_comparisons=count, cursors=observations,
                    fractional_projection={"time": "1/3", "revision": fractional["revision"], "members": projected_definition["members"]},
                    invalid_definitions=failures, legacy_definition_preserved=True, source_audit_unchanged=True,
                    runtime_rng_policy_state_unchanged=True, cancellation=True, concurrent_readers=4,
                    source_audit=before)
            finally:
                history.close()
        finally:
            manager.close(); simulation.close()
        assert not manager.processes
        assert manager.head_diagnostics()["active_connections"] == 0
    report["workspace_removed"] = not root.exists()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "summary_comparisons": report["summary_comparisons"], "report": str(output)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/issue7-cohorts.json"))
    run_check(parser.parse_args().output)
