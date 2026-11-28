"""Inject real checkpoint copy/write failures and verify narrow recovery hygiene."""
from copy import deepcopy
import errno
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from zombie_sim.engine import Simulation
from zombie_sim import runtime
from zombie_sim.core import runtime_service
from zombie_sim.persistence import checkpoint as persistence_checkpoint


class CheckpointFailureChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix="zombie-checkpoint-failure-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sim = Simulation({"agents": [{"id": "a", "type": "Human", "x": 10, "y": 10}],
                               "decision_mode": "scripted", "horizon": 5,
                               "execution": {"workers": 1}}, history_path=self.root / "run.sqlite")
        self.addCleanup(self.sim.close)
        self.sim.advance_until(1, return_snapshot=False)
        self.checkpoint = Path(self.sim.checkpoint(self.root / "rolling.json"))
        self.sidecar = self.checkpoint.with_suffix(".history.sqlite")
        self.previous_files = {p: p.read_bytes() for p in (self.checkpoint, self.sidecar)}
        self.sim.advance_until(2, return_snapshot=False)
        self.markers = (self.sim._last_checkpoint, self.sim._since_checkpoint)
        self.state, self.events = deepcopy(self.sim.state), list(self.sim.events)
        self.journal = list(self.sim.history.connection.iterdump())
        # Other generations, including their companions, must never be cleaned.
        self.unrelated = [self.sidecar.with_name(self.sidecar.name + ".another.partial" + suffix)
                          for suffix in ("", "-wal", "-shm", "-journal")]
        for path in self.unrelated: path.write_bytes(b"another generation")

    def assert_preserved(self, error, failure, *, before_publication=True):
        self.assertIs(error.exception, failure, "Cleanup must preserve the original exception")
        self.assertEqual((self.sim._last_checkpoint, self.sim._since_checkpoint), self.markers)
        self.assertEqual(self.sim.state, self.state)
        self.assertEqual(list(self.sim.events), self.events)
        self.assertEqual(list(self.sim.history.connection.iterdump()), self.journal)
        if before_publication:
            for path, content in self.previous_files.items(): self.assertEqual(path.read_bytes(), content)
        for path in self.unrelated: self.assertEqual(path.read_bytes(), b"another generation")
        self.assertEqual(set(self.root.glob(self.sidecar.name + ".*.partial*")), set(self.unrelated))

    def retry(self):
        self.assertEqual(Path(self.sim.checkpoint(self.checkpoint)), self.checkpoint)
        self.assertEqual((self.sim._last_checkpoint, self.sim._since_checkpoint), (self.sim.time, 0))
        restored = Simulation.restore(self.checkpoint)
        try:
            self.assertEqual(restored.state, self.state)
            self.assertEqual(list(restored.events), self.events)
        finally: restored.close()

    def test_sqlite_copy_write_failure_preserves_previous_checkpoint_and_retries(self):
        failure = sqlite3.OperationalError("injected SQLite disk I/O error after actual backup write")
        connect = sqlite3.connect
        wrote = []

        class FailingCopy(sqlite3.Connection):
            def execute(connection, sql, parameters=()):
                result = super().execute(sql, parameters)
                if sql.startswith("DELETE FROM participants"):
                    wrote.append(True)
                    raise failure
                return result

        def connect_copy(database, *args, **kwargs):
            if str(database).endswith(".partial"): kwargs["factory"] = FailingCopy
            return connect(database, *args, **kwargs)

        with patch.object(persistence_checkpoint.sqlite3, "connect", connect_copy):
            with self.assertRaises(sqlite3.OperationalError) as error: self.sim.checkpoint(self.checkpoint)
        self.assertTrue(wrote, "Fault must occur after the real SQLite backup and write")
        self.assert_preserved(error, failure)
        self.retry()

    def test_copy_failure_cleans_only_owned_database_and_companion_paths(self):
        failure = OSError(errno.EIO, "injected copy finalization failure with SQLite companions")
        copy_history = persistence_checkpoint.copy_history_prefix
        owned = []

        def interrupted_copy(source, destination, revision, state):
            copy_history(source, destination, revision, state)
            # Fault fixture explicitly leaves all possible SQLite companion
            # names to verify cleanup ownership; the database itself is real.
            for suffix in ("", "-wal", "-shm", "-journal"):
                path = Path(str(destination) + suffix)
                if suffix: path.write_bytes(b"injected interrupted-copy companion")
                owned.append(path)
            raise failure

        with patch.object(persistence_checkpoint, "copy_history_prefix", interrupted_copy):
            with self.assertRaises(OSError) as error: self.sim.checkpoint(self.checkpoint)
        self.assert_preserved(error, failure)
        self.assertTrue(all(not path.exists() for path in owned))
        self.retry()

    def test_sidecar_fsync_failure_preserves_previous_checkpoint_and_retries(self):
        failure = OSError(errno.ENOSPC, "injected sidecar fsync failure")
        fsync = os.fsync
        writes = []

        def failing_fsync(descriptor):
            identity = os.fstat(descriptor)
            for path in self.root.glob(self.sidecar.name + ".*.partial"):
                if path in self.unrelated: continue
                candidate = path.stat()
                if (identity.st_dev, identity.st_ino) == (candidate.st_dev, candidate.st_ino):
                    writes.append(path)
                    raise failure
            return fsync(descriptor)

        with patch.object(runtime_service.os, "fsync", failing_fsync):
            with self.assertRaises(OSError) as error: self.sim.checkpoint(self.checkpoint)
        self.assertTrue(writes)
        self.assert_preserved(error, failure)
        self.retry()

    def test_registration_failure_restores_markers_without_removing_published_sidecar(self):
        failure = OSError(errno.EIO, "injected registration failure after actual envelope publication")
        copy_history = persistence_checkpoint.copy_history_prefix
        temporary_paths = []

        def record_temporary(source, destination, revision, state):
            temporary_paths.append(destination)
            return copy_history(source, destination, revision, state)

        def fail_registration(point, **context):
            self.assertEqual(point, "after_checkpoint_rename_before_register")
            self.assertNotEqual(self.checkpoint.read_bytes(), self.previous_files[self.checkpoint])
            # Publication ended our ownership of the old temporary path. A new
            # file at that name belongs to someone else and must survive cleanup.
            for suffix in ("", "-wal", "-shm", "-journal"):
                path = Path(str(temporary_paths[0]) + suffix)
                path.write_bytes(b"another generation")
                self.unrelated.append(path)
            raise failure

        with patch.object(persistence_checkpoint, "copy_history_prefix", record_temporary), patch("zombie_sim.faults.hit", fail_registration):
            with self.assertRaises(OSError) as error: self.sim.checkpoint(self.checkpoint)
        self.assert_preserved(error, failure, before_publication=False)
        self.assertTrue(self.sidecar.is_file())
        self.retry()

    def test_serialization_failure_restores_markers_before_any_temporary_creation(self):
        failure = TypeError("injected unsupported checkpoint value")
        with patch.object(self.sim.services.runtime, "serialize", side_effect=failure):
            with self.assertRaises(TypeError) as error: self.sim.checkpoint(self.checkpoint)
        self.assert_preserved(error, failure)
        self.retry()

    def test_temporary_name_collision_never_deletes_another_generation(self):
        with patch.object(runtime_service.uuid, "uuid4", return_value=SimpleNamespace(hex="another")):
            with self.assertRaises(FileExistsError) as error: self.sim.checkpoint(self.checkpoint)
        self.assert_preserved(error, error.exception)
        self.retry()

    def test_exclusive_empty_reservation_does_not_change_database_bytes(self):
        absent, reserved = self.root / "absent.sqlite", self.root / "reserved.sqlite"
        reserved.touch(exist_ok=False)
        for target in (absent, reserved):
            runtime._copy_history(self.sim.history_path, target, self.sim.revision, self.sim.state)
        self.assertEqual(absent.read_bytes(), reserved.read_bytes())


if __name__ == "__main__": unittest.main(verbosity=2)
