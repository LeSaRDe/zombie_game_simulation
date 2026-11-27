"""An early GUI handoff preserves durable creation receipts and retry identity."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from zombie_sim import application
from zombie_sim.server import create_app


def held_initialization(root, identity):
    """Real spawned coordinator held before world creation in this test only."""
    directory = Path(root) / "runs" / identity
    (directory / "fixture-init-entered").touch()
    deadline = time.monotonic() + 20
    while not (directory / "fixture-init-release").exists():
        if time.monotonic() > deadline:
            raise TimeoutError("Test did not release initialization")
        time.sleep(.01)
    # Spawn imports application freshly, so this is the original worker.
    application._run_worker(root, identity)


class CreationChecks(unittest.TestCase):
    def test_accepted_handoff_is_separate_from_initial_boundary_receipt(self):
        with TemporaryDirectory(prefix="zombie-issue2-create-") as temporary:
            app = create_app(temporary)
            manager = app.state.manager
            create = next(route.endpoint for route in app.routes
                          if getattr(route, "path", "") == "/api/runs" and "POST" in getattr(route, "methods", set()))
            receipt = next(route.endpoint for route in app.routes
                           if getattr(route, "path", "") == "/api/commands/{command_id}")
            config = {"preset": "small", "seed": 92, "horizon": 20,
                      "execution": {"workers": 1}}
            request = {"config": config, "command_id": "initial-create", "wait_for_initialization": False}
            identity = None
            try:
                with patch.object(application, "_run_worker", held_initialization):
                    started = time.monotonic()
                    response = create(request)
                elapsed = time.monotonic() - started
                self.assertLess(elapsed, 2, "GUI handoff waited for initialization")
                self.assertEqual(response.status_code, 202)
                accepted = json.loads(response.body)
                identity = accepted["run_id"]
                self.assertEqual(accepted["status"], "accepted")
                self.assertEqual(accepted["run_status"], "initializing")
                self.assertNotIn("revision", accepted)
                self.assertNotIn("time", accepted)
                directory = Path(manager._row(identity)["directory"])
                deadline = time.monotonic() + 5
                while not (directory / "fixture-init-entered").exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue((directory / "fixture-init-entered").exists())
                self.assertFalse((directory / "run.sqlite").exists(), "Fixture already initialized")
                raw = manager.command_result("initial-create")
                self.assertEqual(raw["status"], "applied")
                self.assertNotIn("revision", raw)
                stored = manager.connection.execute("SELECT request FROM commands WHERE id='initial-create'").fetchone()[0]
                self.assertNotIn("wait_for_initialization", json.loads(stored))

                repeated = json.loads(create(request).body)
                self.assertEqual(repeated["run_id"], identity)
                self.assertEqual(len(manager.list_runs()), 1)
                self.assertEqual(manager.command_result("initial-create"), raw)
                with self.assertRaisesRegex(ValueError, "different request content"):
                    create({**request, "config": {**config, "seed": 93}})
                with self.assertRaisesRegex(ValueError, "must be a boolean"):
                    create({**request, "wait_for_initialization": "false"})

                (directory / "fixture-init-release").touch()
                deadline = time.monotonic() + 10
                while manager._row(identity)["status"] == "initializing" and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(manager._row(identity)["status"], "paused")
                advanced = manager.command(identity, "advance", {"command_id": "advance-before-receipt", "time": "1"})
                self.assertEqual(advanced["status"], "applied")
                self.assertGreater(int(advanced["revision"]), 0)

                # Changing only the transport wait mode preserves the identity
                # and pins the final receipt to creation, not the newer world.
                finalized = create({"config": config, "command_id": "initial-create"})
                self.assertEqual(finalized["run_id"], identity)
                self.assertEqual(finalized["status"], "applied")
                self.assertEqual(finalized["revision"], "0")
                self.assertEqual(finalized["time"], "0")
                self.assertEqual(receipt("initial-create"), finalized)
                accepted_again = json.loads(create(request).body)
                self.assertEqual(accepted_again["run_id"], identity)
                self.assertEqual(accepted_again["generation"], manager._row(identity)["generation"])
                self.assertEqual(accepted_again["run_status"], "paused")
                self.assertNotIn("revision", accepted_again)
                self.assertEqual(receipt("initial-create"), finalized)
                self.assertEqual(len(manager.list_runs()), 1)
                print(json.dumps({"accepted_handoff_seconds": elapsed,
                                  "initializing_handoff": True, "single_run_identity": True,
                                  "durable_initial_revision": finalized["revision"],
                                  "later_revision": advanced["revision"],
                                  "transport_retry_preserved_receipt": True}), flush=True)
            finally:
                if identity is not None:
                    (Path(manager._row(identity)["directory"]) / "fixture-init-release").touch()
                app.state.exports.close()
                manager.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
