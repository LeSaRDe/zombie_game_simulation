"""Independent I09 comparison checks using disposable recorded histories.

Expected counts come from complete historical states, never the production
sampler. Controlled query fixtures exercise origins and long intervals; separate
public-engine histories exercise cure, conversion, death and equal-time commits.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from unittest.mock import patch

from zombie_sim.application import RunManager, ViewCancelled
from zombie_sim.config import initialize_world
from zombie_sim.engine import Simulation
from zombie_sim.storage import History, canonical
from issue7_cohorts_check import configuration


def counts(state):
    result = dict(healthy=0, infected=0, zombies=0, dead=0, total=0)
    for agent in state.get("agents", {}).values():
        result["total"] += 1
        if agent["life"] == 0:
            result["dead"] += 1
        elif agent["type"] == "Zombie":
            result["zombies"] += 1
        elif agent.get("infection_episode") is not None:
            result["infected"] += 1
        else:
            result["healthy"] += 1
    return result


def audit(manager):
    digest = hashlib.sha256()
    # Include continuation/RNG, semantic, control and analysis-definition data.
    for row in sorted(manager.catalog.run_rows(), key=lambda row: row["id"]):
        path = Path(row["directory"]) / "run.sqlite"
        digest.update(row["id"].encode())
        if not path.exists():
            continue
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
            for table, in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
                digest.update(table.encode())
                for record in db.execute('SELECT * FROM "' + table.replace('"', '""') + '" ORDER BY rowid'):
                    for value in record:
                        data = value if isinstance(value, bytes) else repr(value).encode()
                        digest.update(len(data).to_bytes(8, "big")); digest.update(data)
    # Inspect actual stored bytes independently of production query projections.
    with sqlite3.connect((manager.root / "manager.sqlite").as_uri() + "?mode=ro", uri=True) as catalog:
        for table in ("runs", "commands", "views"):
            for record in catalog.execute(f"SELECT * FROM {table} ORDER BY rowid"):
                digest.update(repr(tuple(record)).encode())
    return digest.hexdigest()


def register(manager, identity, path, config, status="terminated"):
    history = History(path, read_only=True)
    try:
        revision, n, d = history.connection.execute(
            "SELECT revision,time_n,time_d FROM commits ORDER BY revision DESC LIMIT 1").fetchone()
    finally:
        history.close()
    with manager.catalog:
        manager.catalog.insert_run(identity,path.parent,config,status,
            frontier={"time": str(Fraction(int(n), int(d))), "revision": str(revision)})


def source(manager, identity, revision=None):
    history = manager.history(identity)
    try:
        if revision is None:
            revision = history.connection.execute("SELECT MAX(revision) FROM commits").fetchone()[0]
        n, d = history.connection.execute("SELECT time_n,time_d FROM commits WHERE revision=?", (revision,)).fetchone()
        return {"run_id": identity, "time": str(Fraction(int(n), int(d))), "revision": str(revision)}
    finally:
        history.close()


def fixture(manager, root, identity, population, origin, changes):
    path = root / "histories" / identity / "run.sqlite"; path.parent.mkdir(parents=True)
    config = {"scenario": identity, "seed": 619, "horizon": 25000,
              "profiles": {"Human": {"hunger_rate": 0}},
              "population": {"humans": population, "zombies": 0, "infected": 0},
              "world": {"length": 1000, "width": 1000}}
    state = initialize_world(config)
    state.update(time=str(origin), revision=0, intents={}, occurrences={})
    history = History(path, initial=state)
    try:
        for time in changes:
            revision = history.revision + 1
            history.append(time, delta=[["set", ["time"], str(time)], ["set", ["revision"], revision]])
    finally:
        history.close()
    register(manager, identity, path, config)
    return path


def engine(manager, root, identity, smaller=False):
    config = configuration(); config["scenario"] = identity
    if smaller:
        config["seed"] = 268; config["agents"] = config["agents"][:4]
    path = root / "histories" / identity / "run.sqlite"; path.parent.mkdir(parents=True)
    simulation = Simulation(config, history_path=path, decision_mode="scripted", run_id=identity)
    try:
        intents = [{"actor": "warrior", "action": "melee", "target": "target"},
                   {"actor": "doctor", "action": "treat_infection", "target": "patient"}]
        if not smaller:
            intents += [{"actor": "biter", "action": "bite", "target": "victim"},
                        {"actor": "killer", "action": "claw", "target": "doomed"}]
        simulation.submit_intents(intents)
        for time in ("1/2", "1", "3/2", "2", "3", "4"):
            simulation.advance_until(time, return_snapshot=False)
        register(manager, identity, path, simulation.config)
        return path
    finally:
        simulation.close()


def oracle(manager, response, requested, report):
    assert response["status"] in {"ready", "no_overlap"}
    assert not response["errors"]
    assert [item["run_id"] for item in response["sources"]] == [item["run_id"] for item in requested]
    for actual, expected in zip(response["sources"], requested):
        assert Fraction(actual["time"]) == Fraction(expected["time"])
        assert actual["revision"] == expected["revision"]
    origins = []
    for request in requested:
        history = manager.history(request["run_id"])
        try:
            n, d = history.connection.execute("SELECT time_n,time_d FROM commits ORDER BY revision LIMIT 1").fetchone()
            origins.append(Fraction(int(n), int(d)))
        finally:
            history.close()
    start, end = max(origins), min(Fraction(item["time"]) for item in requested)
    interval = response["common_interval"]
    assert Fraction(interval["start"]) == start and Fraction(interval["end"]) == end
    if start > end:
        assert response["status"] == "no_overlap" and response["runs"] == [] and response["sample_times"] == []
        report["no_overlap_checks"] += 1
        return
    assert response["status"] == "ready" and response["sample_limit"] == 2000
    times = [Fraction(value) for value in response["sample_times"]]
    assert times and times[0] == start and times[-1] == end and len(times) <= 2000
    assert all(left < right for left, right in zip(times, times[1:]))
    spacing = Fraction(response["sample_interval"])
    assert spacing >= 1
    if start == end:
        assert len(times) == 1
    else:
        assert all(right-left == spacing for left, right in zip(times[:-2], times[1:-1]))
        if len(times) > 1:
            assert 0 < times[-1]-times[-2] <= spacing
    assert [item["run_id"] for item in response["runs"]] == [item["run_id"] for item in requested]
    for item, request, origin in zip(response["runs"], requested, origins):
        assert Fraction(item["origin"]) == origin
        assert Fraction(item["requested_cursor"]["time"]) == Fraction(request["time"])
        assert item["requested_cursor"]["revision"] == request["revision"]
        assert [sample["time"] for sample in item["samples"]] == response["sample_times"]
        history = manager.history(item["run_id"])
        try:
            for time, sample in zip(times, item["samples"]):
                state = history.state_at(str(time), int(request["revision"]))
                expected = counts(state)
                assert {key: sample[key] for key in expected} == expected, (request, sample, expected)
                assert sample["revision"] == str(state["revision"])
                assert sample["seconds"] == float(time)
                report["population_samples_checked"] += 1
            assert item["cursor"] == {"time": str(end), "revision": item["samples"][-1]["revision"]}
        finally:
            history.close()
    report["ready_queries"] += 1


def check(output):
    report = {"passed": False, "ready_queries": 0, "no_overlap_checks": 0, "population_samples_checked": 0}
    with tempfile.TemporaryDirectory(prefix="zombie-issue9-oracle-") as temporary:
        root = Path(temporary); manager = RunManager(root)
        try:
            paths = {"real-a": engine(manager, root, "real-a"), "real-b": engine(manager, root, "real-b", True)}
            paths["branch-a"] = fixture(manager, root, "branch-a", 3, "5/4", ["9/4", "13/4", "4"])
            paths["branch-b"] = fixture(manager, root, "branch-b", 7, "1/3", ["4/3", "7/3", "3"])
            paths["later"] = fixture(manager, root, "later", 2, "5", ["6"])
            # Long query fixture uses a healthy human with a declared zero hunger
            # rate, so future projections cross no unresolved starvation clock.
            for identity, origin in (("long-a", "0"), ("long-b", "1/3")):
                path = fixture(manager, root, identity, 1, origin, ["20000"])
                paths[identity] = path
            damaged = fixture(manager, root, "damaged", 2, "0", ["1", "2"])
            with sqlite3.connect(damaged) as database:
                database.execute("UPDATE commits SET checksum=? WHERE revision=1", ("0" * 64,))
            paths["damaged"] = damaged
            from zombie_sim.metrics import clear_comparison_cache
            clear_comparison_cache()
            before = audit(manager)
            original_history = manager.history; private = []
            def tracked(identity):
                history = original_history(identity); private.append(history); return history
            manager.history = tracked
            def query(requested):
                saved = deepcopy(requested)
                with patch.object(History, "state_at", side_effect=AssertionError("Comparison reconstructed a full world")):
                    response = manager.comparison(requested)
                assert saved == requested
                oracle(manager, response, requested, report)
                return response

            # Exercise every real causal boundary, including equal-time changes.
            a = manager.history("real-a")
            try:
                revisions = [row[0] for row in a.connection.execute("SELECT revision FROM commits ORDER BY revision")]
            finally: a.close()
            for revision in revisions + list(reversed(revisions)):
                query([source(manager, "real-a", revision), source(manager, "real-b")])
            report["real_engine_revisions"] = len(revisions)
            pair = [source(manager, "real-a"), source(manager, "real-b")]
            first = query(pair); assert first == query(pair)
            for order in (("real-a", "branch-a"), ("branch-b", "real-a"), ("real-b", "branch-a", "branch-b"),
                          ("branch-b", "real-b", "branch-a", "real-a"), ("real-a", "real-b")):
                query([source(manager, identity) for identity in order])
            query([source(manager, "real-a", 0), source(manager, "real-b", 0)])
            query([source(manager, "real-a"), source(manager, "later")])
            query([source(manager, "branch-a", 0), source(manager, "real-a")])
            long_result = query([source(manager, "long-a"), source(manager, "long-b")])
            report["bounded_long_interval"] = {"samples_per_run": len(long_result["sample_times"]),
                "spacing": long_result["sample_interval"], "interval": long_result["common_interval"]}
            # A caller cannot poison a cached dataset by mutating its response.
            first["runs"][0]["samples"][0]["healthy"] = -999
            query(pair)
            with ThreadPoolExecutor(max_workers=4) as pool:
                responses = list(pool.map(lambda _: manager.comparison(pair), range(8)))
            for response in responses: oracle(manager, response, pair, report)
            report["concurrent_queries"] = len(responses)

            invalid = [[], pair[:1], pair*3, [pair[0], pair[0]],
                       [dict(pair[0], revision="1.5"), pair[1]],
                       [dict(pair[0], revision="-1"), pair[1]],
                       [dict(pair[0], time="NaN"), pair[1]],
                       [dict(pair[0], time="1/0"), pair[1]]]
            for request in invalid:
                try: manager.comparison(request)
                except ValueError: pass
                else: raise AssertionError(f"Malformed request accepted: {request}")
            report["invalid_request_checks"] = len(invalid)
            for request in ([dict(pair[0], run_id="missing"), pair[1]],
                            [dict(pair[0], revision="999999"), pair[1]],
                            [dict(pair[0], time="100"), pair[1]]):
                result = manager.comparison(request)
                assert result["status"] == "failed" and not result["runs"] and not result["sample_times"]
                assert result["errors"] and result["errors"][0]["run_id"] == request[0]["run_id"]
            # The first run can finish successfully before the second run's
            # checksum failure. None of that partial comparison may publish.
            result = manager.comparison([pair[0], source(manager, "damaged")])
            assert result["status"] == "failed" and result["runs"] == [] and result["sample_times"] == []
            assert result["errors"][0]["run_id"] == "damaged" and "checksum" in result["errors"][0]["message"].lower()
            report["corrupt_second_source_rejected_without_partial_output"] = True
            report["failed_batches_are_atomic"] = True
            cancel = threading.Event(); cancel.set()
            try: manager.comparison(pair, cancel_event=cancel)
            except ViewCancelled: report["pre_cancelled"] = True
            else: raise AssertionError("Pre-cancelled batch succeeded")
            from zombie_sim.metrics import comparison_cache_info
            cache = comparison_cache_info()
            assert cache["entries"] <= cache["capacity"] <= 8
            assert cache["samples"] <= cache["capacity"] * 2000
            report["bounded_cache"] = cache
            assert audit(manager) == before
            for reader in private:
                try: reader.connection.execute("SELECT 1")
                except sqlite3.ProgrammingError: continue
                raise AssertionError("Private comparison/oracle reader remained open")
            report["private_readers_closed"] = len(private)
            report["source_audit_unchanged"] = True
            report["source_audit"] = before
            report["full_world_reconstruction_calls"] = 0
            report["passed"] = True
        finally:
            manager.close()
    report["workspace_removed"] = not root.exists()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/issue9-comparison.json"))
    check(parser.parse_args().output)
