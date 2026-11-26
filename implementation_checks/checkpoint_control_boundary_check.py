"""Exercise control arrival inside the final durable clock commit.

The hook inserts a real pending manager command after SQLite commits and before
the engine publishes its boundary. Checkpoint observation delegates to the real
writer: a regression creates actual checkpoint files rather than simulated ones.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("src"))
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.source.resolve()))
    from zombie_sim import faults
    from zombie_sim.application import _journal
    from zombie_sim.engine import Simulation
    from zombie_sim.storage import canonical

    results = []
    with TemporaryDirectory(prefix="zombie-checkpoint-control-") as temporary:
        root = Path(temporary)
        for operation in ("pause", "terminate", None):
            name = operation or "no_callback"
            directory = root / name
            directory.mkdir()
            journal = _journal(directory / "manager.sqlite")
            sim = Simulation({
                "agents": [{"id": "human", "type": "Human", "x": 10, "y": 10}],
                "decision_mode": "scripted", "horizon": 10,
                "checkpoint_interval": 1, "checkpoint_transactions": 100000,
                "execution": {"workers": 1},
            }, history_path=directory / "run.sqlite", run_id="control-boundary")
            checkpoint_calls = []
            arrivals = []
            expected_revision = sim.revision + 1
            original_hit, original_checkpoint = faults.hit, Simulation.checkpoint

            def arrival(point, **context):
                if (operation and point == "after_history_commit_before_publish"
                        and context.get("revision") == expected_revision and not arrivals):
                    # This is the real post-COMMIT boundary, before _commit returns.
                    durable = sim.history.connection.execute(
                        "SELECT revision,time_n,time_d FROM commits ORDER BY revision DESC LIMIT 1"
                    ).fetchone()
                    kinds = [row[0] for row in sim.history.connection.execute(
                        "SELECT kind FROM events WHERE revision=?", (durable[0],)
                    )]
                    arrivals.append({"hook": point, "revision": durable[0],
                                     "time": f"{durable[1]}/{durable[2]}", "event_kinds": kinds})
                    with journal:
                        journal.execute("INSERT INTO commands VALUES(?,?,?,?,?,?,?)", (
                            name, "control-boundary", operation,
                            canonical({"command_id": name, "operation": operation}),
                            "pending", None, 1,
                        ))
                return original_hit(point, **context)

            def controls_waiting():
                return journal.execute(
                    "SELECT 1 FROM commands WHERE run_id=? AND status='pending' "
                    "AND operation NOT IN ('create','branch') LIMIT 1",
                    ("control-boundary",),
                ).fetchone() is not None

            def record_checkpoint(instance, path=None):
                checkpoint_calls.append({"time": str(instance.time), "revision": instance.revision})
                return original_checkpoint(instance, path)

            try:
                with patch.object(faults, "hit", arrival), patch.object(Simulation, "checkpoint", record_checkpoint):
                    boundary = sim.advance_until(
                        1, return_snapshot=False,
                        should_yield=controls_waiting if operation else None,
                    )
                checkpoints = sim.history.connection.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
                actual = {
                    "operation": name, "arrivals": arrivals, "boundary": boundary,
                    "durable_revision": sim.history.revision,
                    "checkpoint_calls": checkpoint_calls, "registered_checkpoints": checkpoints,
                    "checkpoint_file_exists": (directory / "run.checkpoint.json").exists(),
                    "state_sha256": hashlib.sha256(canonical(sim.snapshot()).encode()).hexdigest(),
                    "events_sha256": hashlib.sha256(canonical(list(sim.events)).encode()).hexdigest(),
                }
                expected_count = 0 if operation else 1
                checks = {
                    "returned_committed_boundary": boundary["time"] == "1" and boundary["revision"] == expected_revision == sim.history.revision,
                    "returned_paused": boundary["status"] == "PAUSED",
                    "command_arrived_during_final_commit": (
                        len(arrivals) == 1 and arrivals[0]["event_kinds"] == ["clock_advanced"]
                        and arrivals[0]["revision"] == expected_revision and arrivals[0]["time"] == "1/1"
                    ) if operation else not arrivals,
                    "no_uncommitted_changes": not sim._dirty,
                    "checkpoint_not_started_for_pending_control": len(checkpoint_calls) == expected_count,
                    "actual_checkpoint_artifacts_match": checkpoints == expected_count and actual["checkpoint_file_exists"] == bool(expected_count),
                }
                results.append({"actual": actual, "checks": checks, "passed": all(checks.values())})
            finally:
                sim.close()
                journal.close()
    report = {
        "source": str(args.source.resolve()),
        "engine_sha256": hashlib.sha256((args.source / "zombie_sim/engine.py").read_bytes()).hexdigest(),
        "passed": all(item["passed"] for item in results), "cases": results,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    for result in results:
        print(("PASS" if result["passed"] else "FAIL"), result["actual"]["operation"],
              "checkpoints", len(result["actual"]["checkpoint_calls"]))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
