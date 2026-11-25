"""Managed-process recovery and historical branching using isolated new runs."""
from pathlib import Path
import json
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from zombie_sim.application import RunManager


def wait(manager, identity, desired):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        row = next(item for item in manager.list_runs() if item["id"] == identity)
        if row["status"] == desired:
            return row
        if row["status"] == "failed":
            raise AssertionError(row)
        time.sleep(.025)
    raise AssertionError((identity, desired, row))


def main():
    with tempfile.TemporaryDirectory(prefix="zombie-managed-recovery-") as root:
        manager = RunManager(root)
        try:
            config = {"seed": 71, "horizon": 12, "population": {"humans": 2, "zombies": 1, "infected": 1}, "incubation_duration": 5}
            identity = manager.create(config, "create-parent")["run_id"]
            wait(manager, identity, "paused")
            step = manager.command(identity, "step", {"command_id": "step-once", "generation": 0})
            assert step["status"] == "applied", step
            assert manager.command(identity, "step", {"command_id": "step-once", "generation": 0}) == step
            assert manager.command(identity, "advance", {"time": "3"})["status"] == "applied"
            parent = manager.snapshot(identity)
            with manager.connection:
                manager.connection.execute("UPDATE commands SET status='pending',response=NULL WHERE id='step-once'")
            assert manager.command_result("step-once") == step
            assert manager.snapshot(identity)["revision"] == parent["revision"]
            branch = manager.branch(identity, {"command_id": "historical-child", "revision": "0", "seed": 72})
            child = branch["run_id"]
            wait(manager, child, "paused")
            assert manager.snapshot(child)["time"] == "0"
            assert manager.snapshot(identity)["revision"] == parent["revision"]
            assert manager.command(identity, "continue")["status"] == "applied"
            wait(manager, identity, "running")
            process = manager.processes[identity]
            process.terminate(); process.join(timeout=5)
            durable = manager.snapshot(identity)
            assert manager.command(identity, "pause")["status"] == "applied"
            wait(manager, identity, "paused")
            recovered = manager.snapshot(identity)
            assert recovered["revision"] == durable["revision"], (durable["revision"], recovered["revision"])
            assert recovered["state"] == durable["state"]
            assert manager.command(identity, "stop")["status"] == "applied"
            assert manager.command(identity, "resume")["status"] == "applied"
            assert manager.command(identity, "pause")["status"] == "applied"
            assert manager.command(identity, "stop")["status"] == "applied"
            assert manager.command(child, "stop")["status"] == "applied"
            print(json.dumps({"status": "passed", "historical_branch_revision": 0,
                              "durable_recovered_revision": durable["revision"],
                              "lost_ack_reconciliation": "passed", "stop_resume": "passed"}, indent=2))
        finally:
            manager.close()


if __name__ == "__main__":
    main()
