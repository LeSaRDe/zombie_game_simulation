"""Independent I06 measurement checks against full historical projections.

Only disposable histories are written. The oracle reconstructs full snapshots,
including continuous projections, rather than reproducing the compact sampler.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import time

from zombie_sim.config import initialize_world
from zombie_sim.engine import Simulation
from zombie_sim.metrics import clear_metric_cache, metric_cache_info, sampled_metrics
from zombie_sim.storage import History, canonical, exact_time, _pack
from zombie_sim.visualization import populations, project_state, resources


def digest(history):
    value = hashlib.sha256()
    for row in history.connection.execute("SELECT revision,time_n,time_d,patch,anchor,checksum FROM commits ORDER BY revision"):
        for item in row:
            value.update(item if isinstance(item, bytes) else str(item).encode())
    for row in history.connection.execute("SELECT sequence,revision,payload FROM events ORDER BY sequence"):
        value.update(str(row[:2]).encode()); value.update(row[2])
    return value.hexdigest()


def oracle(history, response):
    cap = int(response["requested_revision"])
    expected_end = history.state_at(response["time"], cap)
    assert int(response["revision"]) == int(expected_end["revision"])
    assert response["cursor"] == {"time": response["time"], "revision": response["revision"]}
    assert response["samples"]
    previous = None
    for sample in response["samples"]:
        state = project_state(history.state_at(sample["time"], cap), sample["time"])
        assert {key: sample[key] for key in populations(state)} == populations(state), (sample, populations(state))
        assert sample["resources"] == resources(state), (sample, resources(state))
        assert int(sample["revision"]) == int(state["revision"])
        assert sample["seconds"] == float(exact_time(sample["time"]))
        cursor = (exact_time(sample["time"]), int(sample["revision"]))
        assert previous is None or previous < cursor
        previous = cursor
    endpoint = response["samples"][-1]
    assert (endpoint["time"], endpoint["revision"]) == (response["time"], response["revision"])
    counts = dict(history.connection.execute("SELECT kind,COUNT(*) FROM events WHERE revision<=? GROUP BY kind", (int(response["revision"]),)))
    assert response["event_counts"] == counts
    return len(response["samples"])


def rejects(operation, text=None):
    try:
        operation()
    except ValueError as error:
        if text:
            assert text.lower() in str(error).lower(), str(error)
        return str(error)
    raise AssertionError("Invalid metric request succeeded")


def actual_engine(root):
    path = root / "engine.sqlite"
    config = {
        "scenario": "issue6_actual_transitions", "seed": 267, "horizon": 3,
        "incubation_duration": 2, "execution": {"workers": 1},
        "placement": {"minimum_separation": 0, "cross_type_separation": 0},
        "agents": [
            {"id": "warrior", "type": "Human", "x": 10, "y": 10},
            {"id": "zombie", "type": "Zombie", "x": 11, "y": 10, "life": 10},
            {"id": "doctor", "type": "Human", "role": "DOCTOR", "x": 30, "y": 30,
             "inventory": {"MEDICAL_SUPPLY": 2}},
            {"id": "patient", "type": "Human", "x": 31, "y": 30, "infected": True},
            {"id": "converter", "type": "Human", "x": 80, "y": 80, "infected": True},
            {"id": "eater", "type": "Human", "x": 50, "y": 50, "hunger": 80,
             "inventory": {"FOOD": 3}},
        ],
    }
    config["profiles"] = {"Human": {"combat_skill": 1}, "DOCTOR": {"medical_skill": 1, "treatment_duration": .5}}
    simulation = Simulation(config, history_path=path, decision_mode="scripted", run_id="issue6-real")
    try:
        simulation.submit_intents([
            {"actor": "warrior", "action": "melee", "target": "zombie"},
            {"actor": "doctor", "action": "treat_infection", "target": "patient"},
            {"actor": "eater", "action": "eat"},
        ])
        for end in ("1/4", "1/2", "3/4", 1, "3/2", 2, "5/2", 3):
            simulation.advance_until(end, return_snapshot=False)
        history = History(path, read_only=True)
        try:
            before = digest(history)
            clear_metric_cache()
            observations = 0
            times = ["0", "1/4", "1/2", "3/4", "1", "3/2", "2", "5/2", "3"]
            for end in times + list(reversed(times)):
                observations += oracle(history, sampled_metrics(history, end=end, interval="1/4"))
            revisions = list(history.connection.execute("SELECT revision,time_n,time_d FROM commits ORDER BY revision"))
            for revision, n, d in revisions:
                observations += oracle(history, sampled_metrics(history, end=str(Fraction(int(n), int(d))), revision=revision, interval="1/4"))
            final = sampled_metrics(history, end=3)["samples"][-1]
            assert [final[name] for name in ("healthy", "infected", "zombies", "dead", "total")] == [4, 0, 1, 1, 6], final
            assert final["resources"]["available_and_reserved"]["FOOD"] == 2
            assert final["resources"]["available_and_reserved"]["MEDICAL_SUPPLY"] == 1
            assert not any(final["resources"]["reserved_subset"].values())
            assert any(sampled_metrics(history, end=0)["samples"][-1]["resources"]["reserved_subset"].values())
            assert digest(history) == before
            return {"commits": len(revisions), "pointwise_samples_checked": observations,
                    "final_populations": {key: final[key] for key in populations(simulation.snapshot())},
                    "final_resources": final["resources"], "audit_unchanged": True}, path
        finally:
            history.close()
    finally:
        simulation.close()


def fixture(path, count=20, origin=0, marker="fixture"):
    state = initialize_world({"scenario": marker, "seed": 619,
                              "population": {"humans": count, "zombies": 0, "infected": 0},
                              "world": {"length": 1000, "width": 1000}})
    state.update(time=str(origin), revision=0, intents={}, occurrences={})
    return History(path, initial=state, anchor_interval=1000)


def grow(history, start, stop, origin=0):
    # Dense irrelevant history demonstrates that cached metric content does not
    # grow with completed occurrences, intents or model memories.
    for index in range(start, stop + 1):
        at = Fraction(origin) + Fraction(index, 2)
        delta = [["set", ["time"], str(at)], ["set", ["revision"], index],
                 ["set", ["intents", f"intent-{index}"], {"observation": "x" * 2048}],
                 ["set", ["occurrences", f"ended-{index}"], {"planned_end": str(at), "details": "y" * 512}],
                 ["set", ["episodes", f"closed-{index}"], {"conversion_due_at": str(at), "outcome": "CURED"}],
                 ["set", ["stockpiles", "research-stock"], {"inventory": {"FOOD": index}, "reserved": {"FOOD": index % 3}}]]
        history.append(at, delta=delta, records=[{"kind": "fixture_change", "time": str(at)}])


def load_previous(path):
    spec = importlib.util.spec_from_file_location("zombie_sim._issue6_previous_visualization", path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def cache_and_growth(root, previous_path):
    import zombie_sim.metrics as implementation
    clear_metric_cache()
    writer = fixture(root / "growth.sqlite")
    try:
        grow(writer, 1, 120)
        history = History(writer.path, read_only=True)
        try:
            before = digest(history)
            previous = load_previous(previous_path)
            original_state_at = history.state_at
            calls = []
            def tracked(*args, **kwargs):
                calls.append((args, kwargs)); return original_state_at(*args, **kwargs)
            history.state_at = tracked
            started = time.perf_counter(); old = previous.sampled_metrics(history, end=60, interval=1); old_seconds = time.perf_counter() - started
            old_calls = len(calls); calls.clear()
            started = time.perf_counter(); current = sampled_metrics(history, end=60, interval=1); cold_seconds = time.perf_counter() - started
            cold_calls = len(calls); calls.clear()
            started = time.perf_counter(); repeated = sampled_metrics(history, end=60, interval=1); warm_seconds = time.perf_counter() - started
            warm_calls = len(calls)
            history.state_at = original_state_at
            assert current == repeated
            assert current["samples"] == old["samples"]
            oracle(history, current)
            assert old_calls > 50 and cold_calls == 0 and warm_calls == 0
            retained_before = sum(len(canonical(entry["state"])) for entry in implementation._cache.values())
            grow(writer, 121, 240)
            updated = sampled_metrics(history, end=120, interval=1)
            oracle(history, updated)
            latest = list(implementation._cache.values())[-1]
            retained_after = len(canonical(latest["state"]))
            assert retained_after <= retained_before * 1.1
            assert metric_cache_info()["occurrences"] == 0
            assert len(updated["samples"]) == 121
            compact = sampled_metrics(history, end="239/2", interval="1/8", limit=15)
            oracle(history, compact)
            assert len(compact["samples"]) <= 17
            assert exact_time(compact["sample_interval"]) >= Fraction(1, 8)
            after_growth = digest(history)
            # Returned objects must not mutate the shared derived-data cache.
            changed = sampled_metrics(history, end=120)
            changed["samples"][0]["healthy"] = -900
            changed["samples"][0]["resources"]["available_and_reserved"]["FOOD"] = -900
            oracle(history, sampled_metrics(history, end=120))
            assert digest(history) == after_growth and before != after_growth
            return {"history_commits": 241, "modeled_seconds": 120, "agents": 20,
                    "old_full_state_reads": old_calls, "cold_full_state_reads": cold_calls,
                    "warm_full_state_reads": warm_calls, "old_seconds": old_seconds,
                    "cold_seconds": cold_seconds, "warm_seconds": warm_seconds,
                    "retained_compact_bytes_before": retained_before, "retained_compact_bytes_after": retained_after,
                    "bounded_samples": len(compact["samples"]), "sample_interval": compact["sample_interval"]}
        finally:
            history.close()
    finally:
        writer.close()


def safety_checks(root, real_path):
    clear_metric_cache(); results = {}
    history = History(real_path, read_only=True)
    try:
        cases = {"negative revision": {"revision": -1}, "future revision": {"revision": history.revision + 1},
                 "negative end": {"end": -1}, "future end": {"end": 4}, "zero interval": {"interval": 0},
                 "negative interval": {"interval": -1}, "zero limit": {"limit": 0}, "fractional limit": {"limit": 1.2}}
        results["invalid_requests"] = {name: rejects(lambda options=options: sampled_metrics(history, **options)) for name, options in cases.items()}
        # A deliberately earlier revision cannot project past its still-active
        # treatment/action/conversion deadline merely because later commits exist.
        active = next(revision for revision, in history.connection.execute("SELECT revision FROM commits ORDER BY revision")
                      if any(agent.get("active_action") for agent in history.state_at(revision=revision)["agents"].values()))
        results["unresolved_deadline"] = rejects(lambda: sampled_metrics(history, end=3, revision=active), "unresolved")
    finally:
        history.close()

    nonzero = fixture(root / "branch-origin.sqlite", count=3, origin=5)
    try:
        grow(nonzero, 1, 8, origin=5)
        oracle(nonzero, sampled_metrics(nonzero, end="25/4", interval="1/2"))
        rejects(lambda: sampled_metrics(nonzero, end=4), "precedes")
        results["nonzero_origin"] = True
    finally:
        nonzero.close()

    sources = []
    try:
        for index in range(12):
            source = fixture(root / f"source-{index}.sqlite", count=index + 1, marker=f"source-{index}")
            sources.append(source)
            assert sampled_metrics(source)["samples"][-1]["healthy"] == index + 1
        assert metric_cache_info()["entries"] <= metric_cache_info()["capacity"] == 8
        for index, source in reversed(list(enumerate(sources))):
            oracle(source, sampled_metrics(source))
            assert sampled_metrics(source)["samples"][-1]["healthy"] == index + 1
        results["cache_eviction_sources"] = 12
    finally:
        for source in sources: source.close()

    path = root / "replacement.sqlite"
    old = fixture(path, count=2); old_result = sampled_metrics(old); old.close()
    path.rename(root / "replacement-old.sqlite")
    replacement = fixture(path, count=7)
    try:
        assert sampled_metrics(replacement)["samples"][-1]["healthy"] == 7
        assert old_result["samples"][-1]["healthy"] == 2
        results["replaced_path_isolated"] = True
    finally: replacement.close()
    for count in (4, 9):
        memory = fixture(":memory:", count=count)
        try: assert sampled_metrics(memory)["samples"][-1]["healthy"] == count
        finally: memory.close()
    results["memory_sources_isolated"] = True

    bad = fixture(root / "corruption.sqlite")
    try:
        grow(bad, 1, 4); clear_metric_cache()
        with bad.connection:
            bad.connection.execute("UPDATE commits SET checksum='bad' WHERE revision=2")
        results["cold_corruption"] = rejects(lambda: sampled_metrics(bad), "checksum")
    finally: bad.close()
    bad = fixture(root / "append-corruption.sqlite")
    try:
        grow(bad, 1, 4); sampled_metrics(bad)
        grow(bad, 5, 8)
        with bad.connection:
            bad.connection.execute("UPDATE commits SET checksum='bad' WHERE revision=6")
        results["appended_corruption"] = rejects(lambda: sampled_metrics(bad), "checksum")
    finally: bad.close()

    source = fixture(root / "cancel.sqlite"); grow(source, 1, 80)
    try:
        clear_metric_cache()
        class Cancelled(Exception): pass
        checked = 0
        def cancel():
            nonlocal checked
            checked += 1
            if checked == 15: raise Cancelled("cancelled for verification")
        before = digest(source)
        try: sampled_metrics(source, check_cancelled=cancel)
        except Cancelled: pass
        else: raise AssertionError("Sampling ignored cancellation")
        assert metric_cache_info()["entries"] == 0
        oracle(source, sampled_metrics(source))
        assert digest(source) == before
        results["cancellation_checks"] = checked
        def read(index):
            current = History(source.path, read_only=True)
            try:
                response = sampled_metrics(current, end=str(Fraction(index, 2)), interval="1/2")
                oracle(current, response)
                return response["cursor"]
            finally: current.close()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results["concurrent_cursors"] = list(pool.map(read, [60, 20, 80, 40, 70, 10, 50, 30]))
    finally: source.close()
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/issue6-metrics.json"))
    parser.add_argument("--previous", type=Path, default=Path(__file__).resolve().parent / "fixtures/issue6_previous_sampler.py")
    options = parser.parse_args(); report = {"passed": False}
    try:
        with tempfile.TemporaryDirectory(prefix="zombie-issue6-metrics-") as directory:
            root = Path(directory)
            report["actual_engine"], path = actual_engine(root)
            report["growth"] = cache_and_growth(root, options.previous)
            report["safety"] = safety_checks(root, path)
            report["cache"] = metric_cache_info()
            clear_metric_cache()
        report["workspace_removed"] = not root.exists()
        report["passed"] = True
    finally:
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": True, "report": str(options.output.resolve())}))


if __name__ == "__main__": main()
