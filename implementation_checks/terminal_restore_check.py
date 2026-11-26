"""Verify terminal status and retry semantics from actual durable command ACKs."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from zombie_sim.commands import execute_script_command
from zombie_sim.engine import Simulation
from zombie_sim.runtime import restore_revision


class TerminalRestoreChecks(unittest.TestCase):
    def test_terminal_and_partial_advance_restore_and_idempotent_retry(self):
        for backend in ("memory", "sqlite"):
            for target, expected in (("1", ("PAUSED", None)), ("2", ("COMPLETED", "HORIZON"))):
                with self.subTest(backend=backend, target=target), TemporaryDirectory(prefix="zombie-terminal-check-") as directory:
                    path = Path(directory) / "run.sqlite"
                    sim = Simulation({"agents": [{"id": "a", "type": "Human", "x": 10, "y": 10}],
                                      "decision_mode": "scripted", "horizon": 2,
                                      "execution": {"workers": 1}}, history_path=path, backend=backend)
                    try:
                        ack = execute_script_command(sim, "advance", {"to": target}, "advance")
                        self.assertEqual((sim.run_status, sim.termination_reason), expected)
                        revision = sim.revision
                        state, events = deepcopy(sim.state), list(sim.events)
                        raw = sim.history.runtime_at()["attributes"]
                        self.assertEqual(ack["run_status"], "completed" if target == "2" else "paused")
                        self.assertEqual(sim.history.get_metadata("control_state")["status"], ack["run_status"])
                    finally:
                        sim.close()
                    restored = restore_revision(Simulation, path)
                    try:
                        self.assertEqual((restored.run_status, restored.termination_reason), expected)
                        self.assertEqual(restored.state, state)
                        self.assertEqual(list(restored.events), events)
                        self.assertEqual(execute_script_command(restored, "advance", {"to": target}, "advance"), ack)
                        self.assertEqual(restored.revision, revision)
                        self.assertEqual((restored.run_status, restored.termination_reason), expected)
                        self.assertEqual(list(restored.events), events)
                        print(json.dumps({"backend": backend, "target": target,
                            "journal_status": raw["run_status"], "journal_termination_reason": raw["termination_reason"],
                            "durable_ack_status": ack["run_status"], "restored_status": restored.run_status,
                            "restored_termination_reason": restored.termination_reason,
                            "idempotent_retry_without_new_revision": True}), flush=True)
                    finally:
                        restored.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
