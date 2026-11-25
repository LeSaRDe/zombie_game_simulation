"""Crash/restart checks against new implementation-owned temporary runs."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from zombie_sim.engine import Simulation
from zombie_sim.runtime import restore_revision
from zombie_sim.storage import History


CONFIG = {"seed": 73, "horizon": 8, "population": {"humans": 2, "zombies": 1, "infected": 1},
          "incubation_duration": 5, "interventions_enabled": True, "checkpoint_interval": 30}


def perform(sim, operation):
    if operation == "step":
        sim.step(return_snapshot=False)
    else:
        sim.advance_until("0" if operation == "step_timestamp" else "3", return_snapshot=False)


def child(path, backend, operation, boundary):
    sim = Simulation(CONFIG, history_path=path, backend=backend, run_id="recovery-verification")
    active = {"id": "crash-command", "operation": operation, "request": {},
              "target": "0" if operation == "step_timestamp" else "3",
              "desired_control": {"generation": 1, "status": "paused", "pacing": 1}}
    sim.history.begin_command(active)
    sim._active_control_command = active
    original = sim.store.commit_delta
    def crash(*args, **kwargs):
        if boundary == "after":
            original(*args, **kwargs)
        os._exit(86)
    sim.store.commit_delta = crash
    perform(sim, operation)
    raise AssertionError("Fault was not reached")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        child(*sys.argv[2:])
        return
    results = []
    with tempfile.TemporaryDirectory(prefix="zombie-runtime-crash-") as root:
        for backend in ("memory", "sqlite"):
            for operation in ("step", "step_timestamp", "advance"):
                for boundary in ("before", "after"):
                    path = Path(root) / f"{backend}-{operation}-{boundary}.sqlite"
                    process = subprocess.run([sys.executable, str(Path(__file__).absolute()), "--child", str(path), backend, operation, boundary], check=False)
                    assert process.returncode == 86, process.returncode
                    resumed = restore_revision(Simulation, path, output_history_path=path)
                    active = resumed.history.get_metadata("active_control_command")
                    result = resumed.history.command_result("crash-command")
                    if active:
                        resumed._active_control_command = active
                        perform(resumed, operation)
                    else:
                        assert result and result["status"] == "applied"
                    result = resumed.history.command_result("crash-command")
                    assert result and result["status"] == "applied", (backend, operation, boundary, result)
                    assert resumed.history.get_metadata("active_control_command") is None
                    reference = Simulation(CONFIG, run_id="recovery-verification")
                    perform(reference, operation)
                    assert resumed.snapshot() == reference.snapshot(), (backend, operation, boundary, "boundary state")
                    assert resumed.events == reference.events, (backend, operation, boundary, "boundary events")
                    resumed.advance_until(6, return_snapshot=False)
                    reference.advance_until(6, return_snapshot=False)
                    assert resumed.snapshot() == reference.snapshot(), (backend, operation, boundary, "continued state")
                    assert resumed.events == reference.events, (backend, operation, boundary, "continued events")
                    assert resumed.memories == reference.memories
                    assert sorted(resumed.queue) == sorted(reference.queue)
                    results.append({"backend": backend, "operation": operation, "crash": boundary, "status": "passed"})
                    resumed.close(); reference.close()
    print(json.dumps({"status": "passed", "cases": results}, indent=2))


if __name__ == "__main__":
    main()
