"""Real I/O failures and process death cannot split a rolling checkpoint pair."""
import errno
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from zombie_sim.engine import Simulation
from zombie_sim.persistence import PersistenceBundleFactory
from zombie_sim.core import runtime_service


CONFIG = {'agents': [{'id': 'a', 'type': 'Human', 'x': 10, 'y': 10}],
          'decision_mode': 'scripted', 'horizon': 10, 'checkpoint_interval': 1000,
          'execution': {'workers': 1}}


class CheckpointPublicationTests(unittest.TestCase):
    def test_successful_portable_pair_can_be_renamed_without_pending_generation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with Simulation(CONFIG, history_path=root / 'live.sqlite') as sim:
                sim.advance_until(1, return_snapshot=False)
                original = Path(sim.checkpoint(root / 'original.json'))
                renamed = root / 'renamed.json'
                shutil.copy2(original, renamed)
                shutil.copy2(original.with_suffix('.history.sqlite'), renamed.with_suffix('.history.sqlite'))
                with Simulation.restore(renamed) as restored:
                    self.assertEqual(restored.state, sim.state)
                    self.assertEqual(list(restored.events), list(sim.events))

    def test_failures_before_envelope_preserve_previous_pair_and_markers(self):
        for point in ('pins', 'envelope_fsync'):
            with self.subTest(point=point), TemporaryDirectory() as directory:
                root = Path(directory)
                with Simulation(CONFIG, history_path=root / 'live.sqlite') as sim:
                    sim.advance_until(1, return_snapshot=False)
                    checkpoint = Path(sim.checkpoint(root / 'rolling.json'))
                    sidecar = checkpoint.with_suffix('.history.sqlite')
                    old = {path: path.read_bytes() for path in (checkpoint, sidecar)}
                    old_state, old_events = sim.state, list(sim.events)
                    sim.advance_until(2, return_snapshot=False)
                    markers = (sim._last_checkpoint, sim._since_checkpoint)
                    failure = OSError(errno.ENOSPC, 'Injected publication capacity failure')
                    fsync = os.fsync

                    def fail_pins(*args):
                        self.assertEqual(len(list(root.glob('*.generation.history.sqlite'))), 1)
                        raise failure

                    def fail_envelope_fsync(descriptor):
                        partial = checkpoint.with_suffix('.json.partial')
                        if partial.exists() and os.fstat(descriptor).st_ino == partial.stat().st_ino:
                            self.assertEqual(len(list(root.glob('*.generation.history.sqlite'))), 1)
                            raise failure
                        return fsync(descriptor)

                    injection = patch('zombie_sim.artifact_pins.write_pins', fail_pins) if point == 'pins' else patch('os.fsync', fail_envelope_fsync)
                    with injection, self.assertRaises(OSError) as raised:
                        sim.checkpoint(checkpoint)
                    self.assertIs(raised.exception, failure)
                    self.assertEqual((sim._last_checkpoint, sim._since_checkpoint), markers)
                    self.assertEqual(list(root.glob('*.generation.history.sqlite')), [])
                    for path, content in old.items():
                        self.assertEqual(path.read_bytes(), content)
                    with Simulation.restore(checkpoint) as restored:
                        self.assertEqual(restored.state, old_state)
                        self.assertEqual(list(restored.events), old_events)
                    sim.checkpoint(checkpoint)
                    with Simulation.restore(checkpoint) as restored:
                        self.assertEqual(restored.state, sim.state)
                        self.assertEqual(list(restored.events), list(sim.events))

    def crash_after_envelope(self, root, previous):
        script = r'''
import json,sys
from pathlib import Path
from zombie_sim.engine import Simulation
from zombie_sim import faults
root=Path(sys.argv[1]);previous=sys.argv[2]=='True'
config=json.loads(sys.argv[3])
with Simulation(config,history_path=root/'live.sqlite') as sim:
    sim.submit_intents({'actor':'a','action':'move','parameters':{'duration':3,'path':[{'x':10,'y':10,'offset':0},{'x':16,'y':10,'offset':3}]}})
    sim.advance_until(1,return_snapshot=False)
    if previous:sim.checkpoint(root/'rolling.json')
    sim.advance_until(2,return_snapshot=False)
    (root/'expected.json').write_text(json.dumps({'state':sim.state,'events':list(sim.events)}))
    with Simulation.from_serialized(sim.serialize()) as future:
        future.advance_until(3,return_snapshot=False)
        (root/'continued.json').write_text(json.dumps({'state':future.state,'events':list(future.events)}))
    faults.arm('after_checkpoint_envelope_before_sidecar_promotion',crash=True)
    sim.checkpoint(root/'rolling.json')
'''
        process = subprocess.run([sys.executable, '-c', script, str(root), str(previous), json.dumps(CONFIG)],
                                 capture_output=True, text=True, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        self.assertEqual(process.returncode, 86, process.stdout + process.stderr)
        checkpoint = root / 'rolling.json'
        payload = json.loads(checkpoint.read_text())['document']['payload']
        generation = root / payload['history_publication']['generation']
        self.assertTrue(generation.is_file())
        self.assertEqual(checkpoint.with_suffix('.history.sqlite').exists(), previous)
        return checkpoint, generation

    def test_process_death_after_first_envelope_restores_pending_generation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint, _ = self.crash_after_envelope(root, False)
            with Simulation.restore(checkpoint) as restored:
                expected = json.loads((root / 'expected.json').read_text())
                self.assertEqual(restored.state, expected['state'])
                self.assertEqual(list(restored.events), expected['events'])
                restored.advance_until(3, return_snapshot=False)
                continued = json.loads((root / 'continued.json').read_text())
                self.assertEqual(restored.state, continued['state'])
                self.assertEqual(list(restored.events), continued['events'])

    def test_process_death_after_rolling_envelope_recovers_and_cleans_only_owned_generation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint, generation = self.crash_after_envelope(root, True)
            unrelated = root / 'user-owned.history.sqlite'
            unrelated.write_bytes(b'User history must survive')
            with Simulation.restore(checkpoint) as restored:
                expected = json.loads((root / 'expected.json').read_text())
                self.assertEqual(restored.state, expected['state'])
                self.assertEqual(list(restored.events), expected['events'])
                named = Path(restored.checkpoint(root / 'named.json'))
                named_bytes = named.read_bytes(), named.with_suffix('.history.sqlite').read_bytes()
                for _ in range(10):
                    restored.checkpoint(checkpoint)
                    self.assertEqual(list(root.glob('rolling*.generation.history.sqlite')), [])
                self.assertFalse(generation.exists())
                self.assertEqual(unrelated.read_bytes(), b'User history must survive')
                self.assertEqual((named.read_bytes(), named.with_suffix('.history.sqlite').read_bytes()), named_bytes)

    def test_pending_generation_does_not_mask_arbitrary_canonical_corruption(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint, generation = self.crash_after_envelope(root, True)
            checkpoint.with_suffix('.history.sqlite').write_bytes(b'Corrupt canonical history')
            self.assertTrue(generation.is_file())
            with self.assertRaisesRegex(ValueError, 'history sidecar checksum mismatch'):
                Simulation.restore(checkpoint)

    def test_concurrent_promotion_during_hash_or_prefix_copy_rechecks_canonical(self):
        for point in ('hash', 'copy'):
            with self.subTest(point=point), TemporaryDirectory() as directory:
                root = Path(directory)
                checkpoint, generation = self.crash_after_envelope(root, True)
                canonical = checkpoint.with_suffix('.history.sqlite')
                digest = runtime_service._file_digest
                promoted = []

                def promoting_digest(path):
                    if Path(path) == generation and not promoted:
                        os.replace(generation, canonical)
                        promoted.append(point)
                    return digest(path)

                class PromotingFactory(PersistenceBundleFactory):
                    def export_prefix(self, source, destination, revision, state):
                        if Path(source) == generation and not promoted:
                            os.replace(generation, canonical)
                            promoted.append(point)
                        return super().export_prefix(source, destination, revision, state)

                if point == 'hash':
                    with patch.object(runtime_service, '_file_digest', promoting_digest):
                        restored = Simulation.restore(checkpoint)
                else:
                    restored = Simulation.restore(checkpoint, persistence_factory=PromotingFactory())
                with restored:
                    expected = json.loads((root / 'expected.json').read_text())
                    self.assertEqual(restored.state, expected['state'])
                    self.assertEqual(list(restored.events), expected['events'])
                self.assertEqual(promoted, [point])


if __name__ == '__main__':
    unittest.main()
