"""Restore must use the caller's complete adapter bundle, including copying."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from zombie_sim.engine import Simulation
from zombie_sim.persistence import PersistenceBundleFactory


class RecordingFactory:
    """Independent structural factory, with no inheritance from SQLite adapters."""

    def __init__(self):
        self.adapter = PersistenceBundleFactory()
        self.copies = []
        self.restores = []

    def create(self, initial, path, backend='memory'):
        return self.adapter.create(initial, path, backend)

    def restore(self, path, backend='memory', initial=None):
        self.restores.append(str(path))
        return self.adapter.restore(path, backend, initial)

    def open_history(self, path, *, read_only=True):
        return self.adapter.open_history(path, read_only=read_only)

    def export_prefix(self, source, destination, revision, state):
        self.copies.append((str(source), str(destination), revision, state['revision']))
        return self.adapter.export_prefix(source, destination, revision, state)


class RestoreFactoryTests(unittest.TestCase):
    def test_prefix_adapter_failure_is_authoritative_and_does_not_touch_source(self):
        class RefusingFactory(RecordingFactory):
            def export_prefix(self, source, destination, revision, state):
                raise OSError('The selected backend declined prefix export')

        with TemporaryDirectory() as directory:
            root = Path(directory)
            with Simulation({'agents': [{'id': 'a', 'type': 'Human', 'x': 10, 'y': 10}],
                             'decision_mode': 'scripted', 'horizon': 5},
                            history_path=root / 'source.sqlite') as original:
                original.advance_until(1, return_snapshot=False)
                state, events = original.state, list(original.events)
                destination = root / 'refused.sqlite'
                factory = RefusingFactory()
                with self.assertRaisesRegex(OSError, 'backend declined'):
                    Simulation.from_serialized(original.serialize(), history_path=destination,
                                               persistence_factory=factory)
                self.assertEqual(factory.restores, [])
                self.assertFalse(destination.exists())
                self.assertEqual(original.state, state)
                self.assertEqual(list(original.events), events)

    def test_checkpoint_journal_and_branch_delegate_prefix_copy_to_factory(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            factory = RecordingFactory()
            with Simulation({'agents': [{'id': 'a', 'type': 'Human', 'x': 10, 'y': 10}],
                             'decision_mode': 'scripted', 'horizon': 5},
                            history_path=root / 'source.sqlite', persistence_factory=factory) as original:
                original.advance_until(1, return_snapshot=False)
                checkpoint = original.checkpoint(root / 'saved.json')
                for restore in (
                    lambda: Simulation.restore(checkpoint, persistence_factory=factory),
                    lambda: Simulation.restore_revision(original.history_path, persistence_factory=factory),
                ):
                    with restore() as clone:
                        self.assertEqual(clone.state, original.state)
                        self.assertEqual(list(clone.events), list(original.events))
                with original.branch(root / 'child') as child:
                    self.assertEqual(child.world_view['lineage']['revision'], original.revision)
            self.assertEqual(len(factory.copies), 3)
            self.assertEqual(len(factory.restores), 3)
            self.assertTrue(all(revision == state_revision for _, _, revision, state_revision in factory.copies))


if __name__ == '__main__':
    unittest.main()
