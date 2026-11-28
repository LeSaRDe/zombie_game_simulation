"""Cancellation releases private readers without changing history or other viewers."""
from __future__ import annotations

import hashlib
from pathlib import Path
import queue
import sqlite3
import sys
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from zombie_sim import application, storage
from zombie_sim.application import RunManager, ViewCancelled
from zombie_sim.engine import Simulation
from zombie_sim.storage import canonical


class ReaderChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix="zombie-issue2-reader-")
        self.root = Path(self.temporary.name)
        self.identity = "reader-fixture"
        directory = self.root / "runs" / self.identity
        directory.mkdir(parents=True)
        self.path = directory / "run.sqlite"
        config = {"agents": [{"id": "human", "type": "Human", "x": 10, "y": 10}],
                  "decision_mode": "scripted", "horizon": 20, "execution": {"workers": 1}}
        simulation = Simulation(config, history_path=self.path, run_id=self.identity)
        try:
            for target in range(1, 7):
                simulation.advance_until(target)
            self.revision = simulation.revision
            frontier = {"revision": str(self.revision), "time": str(simulation.time), "pacing": 0}
        finally:
            simulation.close()
        self.manager = RunManager(self.root)
        with self.manager.catalog:
            self.manager.catalog.insert_run(self.identity,directory,config,"terminated",frontier=frontier)
        self.digest = self.ledger_digest()

    def ledger_digest(self):
        digest = hashlib.sha256()
        with sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True) as database:
            for table in ("commits", "runtime_commits", "events", "control_commands", "metadata"):
                digest.update(table.encode())
                for row in database.execute(f"SELECT * FROM {table} ORDER BY rowid"):
                    for value in row:
                        encoded = value if isinstance(value, bytes) else repr(value).encode()
                        digest.update(len(encoded).to_bytes(8, "big")); digest.update(encoded)
        return digest.hexdigest()

    def tearDown(self):
        self.assertEqual(self.ledger_digest(), self.digest, "A cancelled viewer changed durable research data")
        self.assertTrue(all(reader.users == 0 for reader in self.manager._head_readers.values()))
        self.manager.close()
        self.assertEqual(self.manager.head_diagnostics()["active_connections"], 0)
        self.temporary.cleanup()

    def start_reader(self, cancelled=None):
        results = queue.Queue()
        def read():
            try:
                results.put(self.manager.snapshot(self.identity, cancel_event=cancelled))
            except BaseException as error:
                results.put(error)
        thread = threading.Thread(target=read, daemon=True)
        thread.start()
        return thread, results

    def finish(self, worker):
        thread, results = worker
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive(), "Cancelled reader did not leave its queue")
        return results.get_nowait()

    def test_already_cancelled_request_does_no_read_work(self):
        cancelled = threading.Event(); cancelled.set()
        with self.assertRaises(ViewCancelled):
            self.manager.snapshot(self.identity, cancel_event=cancelled)
        self.assertEqual(self.manager.head_diagnostics()["opened"], 0)
        self.assertEqual(self.manager.snapshot_diagnostics()["builds"], 0)

    def test_waiting_metadata_reader_can_cancel(self):
        self.manager.read_head(self.identity)
        reader = self.manager._head_readers[self.identity]
        cancelled = threading.Event()
        with reader.lock:
            worker = self.start_reader(cancelled)
            cancelled.set()
            self.assertIsInstance(self.finish(worker), ViewCancelled)
        self.assertEqual(self.manager.snapshot_diagnostics()["builds"], 0)
        self.assertEqual(self.manager.read_head(self.identity)["revision"], str(self.revision))

    def test_waiting_projection_closes_private_connection(self):
        self.manager.read_head(self.identity)
        cancelled = threading.Event()
        opened = threading.Event()
        private_connections = []
        original = self.manager.history
        def history(identity):
            result = original(identity)
            private_connections.append(result.connection)
            opened.set()
            return result
        lock = self.manager._snapshot_build_locks[hash(self.identity) % len(self.manager._snapshot_build_locks)]
        with patch.object(self.manager, "history", history), lock:
            worker = self.start_reader(cancelled)
            self.assertTrue(opened.wait(timeout=3))
            cancelled.set()
            self.assertIsInstance(self.finish(worker), ViewCancelled)
        self.assertTrue(private_connections)
        for connection in private_connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")
        self.assertEqual(self.manager.snapshot_diagnostics()["builds"], 0)

    def test_patch_chain_stops_before_later_patches_and_projection(self):
        cancelled = threading.Event()
        calls = []
        original = storage.apply_patch
        def apply(state, delta):
            calls.append(1)
            result = original(state, delta)
            cancelled.set()
            return result
        with patch.object(storage, "apply_patch", apply), patch.object(application, "project_state") as projection:
            with self.assertRaises(ViewCancelled):
                self.manager.snapshot(self.identity, cancel_event=cancelled)
            self.assertEqual(len(calls), 1)
            projection.assert_not_called()
        self.assertEqual(self.manager.snapshot_diagnostics()["builds"], 0)

    def test_cancelled_atomic_projection_does_not_cancel_independent_viewer(self):
        entered = threading.Event(); release = threading.Event(); cancelled = threading.Event()
        original = application.project_state
        def project(*args, **kwargs):
            entered.set()
            if not release.wait(timeout=5):
                raise TimeoutError("Test did not release atomic projection")
            return original(*args, **kwargs)
        with patch.object(application, "project_state", project):
            obsolete = self.start_reader(cancelled)
            self.assertTrue(entered.wait(timeout=3))
            independent = self.start_reader()
            cancelled.set(); release.set()
            self.assertIsInstance(self.finish(obsolete), ViewCancelled)
            actual = self.finish(independent)
        self.assertIsInstance(actual, dict)
        self.assertEqual(actual["revision"], str(self.revision))
        self.assertEqual(self.manager.snapshot_diagnostics()["builds"], 1)
        # A later cancellation also leaves the completed shared cache intact.
        with self.assertRaises(ViewCancelled):
            self.manager.snapshot(self.identity, cancel_event=cancelled)
        cached = self.manager.snapshot(self.identity)
        self.assertEqual(cached["state"], actual["state"])
        self.assertEqual(self.manager.snapshot_diagnostics()["builds"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
