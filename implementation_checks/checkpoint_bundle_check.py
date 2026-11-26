"""Verify portable checkpoint bundles using real busy-state continuations.

The copied JSON intentionally retains its original absolute history_path. A
portable bundle consists of the JSON, adjacent history sidecar, and referenced
model pins; its adjacent files must remain authoritative after the source moves
or publishes a newer rolling checkpoint.
"""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from zombie_sim.artifact_pins import ArtifactMismatch
from zombie_sim.engine import Simulation


@contextmanager
def bounded_sidecar_reads():
    """Reject whole-ledger reads while permitting JSON, source, and model pins."""
    original_open, original_read_bytes = Path.open, Path.read_bytes
    sizes = []

    class Reader:
        def __init__(self, stream): self.stream = stream
        def __enter__(self): self.stream.__enter__(); return self
        def __exit__(self, *args): return self.stream.__exit__(*args)
        def __getattr__(self, name): return getattr(self.stream, name)
        def read(self, size=-1):
            assert 0 < size <= 4 * 1024**2, f"Unbounded sidecar read: {size}"
            sizes.append(size)
            return self.stream.read(size)
        def readinto(self, buffer):
            assert 0 < len(buffer) <= 4 * 1024**2, f"Unbounded sidecar buffer: {len(buffer)}"
            sizes.append(len(buffer))
            return self.stream.readinto(buffer)

    def open_file(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        mode = args[0] if args else kwargs.get("mode", "r")
        return Reader(stream) if path.name.endswith(".history.sqlite") and mode == "rb" else stream

    def read_bytes(path):
        assert not path.name.endswith(".history.sqlite"), "Sidecars must not use Path.read_bytes"
        return original_read_bytes(path)

    with patch.object(Path, "open", open_file), patch.object(Path, "read_bytes", read_bytes):
        yield sizes


def copy_bundle(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    shutil.copy2(source.with_suffix(".history.sqlite"), destination.with_suffix(".history.sqlite"))
    shutil.copytree(source.with_suffix(".models"), destination.with_suffix(".models"))
    payload = json.loads(destination.read_text())["document"]["payload"]
    assert payload["artifact_pins"]["models"], "Fixture must exercise actual model pins"
    for record in payload["artifact_pins"]["models"]:
        assert hashlib.sha256((destination.parent / record["path"]).read_bytes()).hexdigest() == record["sha256"]


class CheckpointBundleChecks(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(TemporaryDirectory(prefix="zombie-bundle-check-")))
        source = self.root / "source"
        source.mkdir()
        self.sim = Simulation({"agents": [{"id": "a", "type": "Human", "x": 10, "y": 10}],
                               "decision_mode": "scripted", "horizon": 5,
                               "execution": {"workers": 1}}, history_path=source / "run.sqlite")
        self.stack.callback(self.sim.close)
        self.sim.submit_intents({"actor": "a", "action": "move", "parameters": {"duration": 2,
            "path": [{"x": 10, "y": 10, "offset": 0}, {"x": 14, "y": 10, "offset": 2}]}})
        self.sim.advance_until(1, return_snapshot=False)
        self.original = Path(self.sim.checkpoint(source / "rolling.json"))
        self.copied = self.root / "portable" / self.original.name
        copy_bundle(self.original, self.copied)
        self.saved_state = deepcopy(self.sim.state)
        self.saved_events = list(self.sim.events)

    def restore(self, path=None):
        clone = Simulation.restore(path or self.copied)
        self.stack.callback(clone.close)
        self.assertEqual(clone.state, self.saved_state)
        self.assertEqual(list(clone.events), self.saved_events)
        return clone

    def test_copied_bundle_survives_original_rolling_replacement(self):
        self.sim.advance_until(2, return_snapshot=False)
        self.sim.checkpoint(self.original)
        clone = self.restore()
        clone.advance_until(2, return_snapshot=False)
        self.assertEqual(clone.state, self.sim.state)
        self.assertEqual(list(clone.events), list(self.sim.events))
        self.assertEqual(clone.memories, self.sim.memories)
        self.assertEqual(sorted(clone.queue), sorted(self.sim.queue))

    def test_corrupt_adjacent_history_never_falls_back_to_valid_original(self):
        adjacent = self.copied.with_suffix(".history.sqlite")
        adjacent.write_bytes(b"corrupt local history")
        with self.assertRaisesRegex(ValueError, "history sidecar checksum mismatch"):
            self.restore()

    def test_missing_adjacent_history_can_use_original_path(self):
        self.copied.with_suffix(".history.sqlite").rename(self.root / "detached.history.sqlite")
        self.restore()

    def test_adjacent_directory_never_falls_back_to_valid_original(self):
        adjacent = self.copied.with_suffix(".history.sqlite")
        adjacent.rename(self.root / "detached.history.sqlite")
        adjacent.mkdir()
        with self.assertRaises(IsADirectoryError):
            self.restore()

    def test_broken_adjacent_symlink_never_falls_back_to_valid_original(self):
        adjacent = self.copied.with_suffix(".history.sqlite")
        adjacent.rename(self.root / "detached.history.sqlite")
        adjacent.symlink_to("missing-history.sqlite")
        with self.assertRaises(FileNotFoundError):
            self.restore()

    def test_bundle_and_model_pins_survive_source_directory_move(self):
        self.sim.close()
        self.original.parent.rename(self.root / "moved-source")
        self.restore()

    def test_missing_adjacent_model_pin_never_uses_original(self):
        payload = json.loads(self.copied.read_text())["document"]["payload"]
        pin = self.copied.parent / payload["artifact_pins"]["models"][0]["path"]
        pin.rename(pin.with_suffix(".detached"))
        with self.assertRaises(ArtifactMismatch) as error:
            self.restore()
        self.assertEqual(error.exception.component, "model_artifact_checksum")

    def test_corrupt_adjacent_model_pin_never_uses_original(self):
        payload = json.loads(self.copied.read_text())["document"]["payload"]
        pin = self.copied.parent / payload["artifact_pins"]["models"][0]["path"]
        pin.write_text("{}")
        with self.assertRaises(ArtifactMismatch) as error:
            self.restore()
        self.assertEqual(error.exception.component, "model_artifact_checksum")

    def test_checkpoint_hashes_sidecar_with_bounded_reads(self):
        with bounded_sidecar_reads() as sizes:
            checkpoint = Path(self.sim.checkpoint(self.original.parent / "streamed.json"))
        self.assertTrue(sizes, "Checkpoint must hash its actual sidecar")
        payload = json.loads(checkpoint.read_text())["document"]["payload"]
        expected = hashlib.sha256(checkpoint.with_suffix(".history.sqlite").read_bytes()).hexdigest()
        self.assertEqual(payload["history_sha256"], expected)
        self.restore(checkpoint)

    def test_restore_hashes_sidecar_with_bounded_reads(self):
        with bounded_sidecar_reads() as sizes:
            self.restore()
        self.assertTrue(sizes, "Restore must validate its actual sidecar")

    def test_streamed_hash_equals_standard_hash_across_chunk_boundaries(self):
        from zombie_sim.runtime import _file_digest
        path = self.root / "hash-input.history.sqlite"
        for content in (b"", b"x", bytes(range(256)) * (16 * 1024 + 1)):
            with self.subTest(length=len(content)):
                path.write_bytes(content)
                with bounded_sidecar_reads() as sizes:
                    observed = _file_digest(path)
                self.assertTrue(sizes)
                self.assertEqual(observed, hashlib.sha256(content).hexdigest())
                if len(content) > 4 * 1024**2:
                    self.assertGreater(len(sizes), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
