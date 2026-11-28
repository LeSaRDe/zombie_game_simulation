"""A failed scheduled commit restores the runner, not just its durable world."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from zombie_sim import faults
from zombie_sim.engine import Simulation


class SchedulerAtomicityTests(unittest.TestCase):
    def make_simulation(self, directory, backend, boundary):
        simulation = Simulation({
            'agents': [{'id': 'a', 'type': 'Human', 'x': 10, 'y': 10}],
            'decision_mode': 'model' if boundary == 'decision' else 'scripted',
            'horizon': 4, 'execution': {'workers': 1},
        }, history_path=Path(directory) / 'run.sqlite', backend=backend)
        self.addCleanup(simulation.close)
        if boundary == 'completion':
            simulation.submit_intents([{'actor': 'a', 'action': 'wait',
                                        'parameters': {'duration': 1}}])
        return simulation

    def test_failed_storage_restores_all_runner_fields_and_unpublished_evidence(self):
        self.addCleanup(faults.clear)
        for backend in ('memory', 'sqlite'):
            for boundary in ('completion', 'decision', 'clock'):
                with self.subTest(backend=backend, boundary=boundary), TemporaryDirectory() as directory:
                    sim = self.make_simulation(directory, backend, boundary)
                    before = sim._runtime_state.attributes()
                    world = sim.state_coordinator.current_world
                    journal = sim.history.runtime_at()
                    events = list(sim.events)
                    faults.arm('before_history_commit', error='ENOSPC')
                    try:
                        with self.assertRaises(OSError):
                            sim.advance_until(1, max_events=None if boundary == 'clock' else 1)
                    finally:
                        faults.clear()
                    after = sim._runtime_state.attributes()
                    for field in ('run_status', 'termination_reason'):
                        before.pop(field, None)
                        after.pop(field, None)
                    self.assertEqual(after, before)
                    self.assertIs(sim.state_coordinator.current_world, world)
                    self.assertEqual(sim.history.runtime_at(), journal)
                    self.assertEqual(list(sim.events), events)
                    self.assertEqual(sim._runtime_queue_delta, [])
                    self.assertEqual(getattr(sim, '_runtime_prepared_agents', {}), {})
                    self.assertEqual((sim.run_status, sim.termination_reason), ('FAILED', 'STORAGE_ERROR'))
                    # Recovery from the committed journal consumes the pending
                    # work exactly once and leaves the failed runner untouched.
                    with Simulation.restore_revision(sim.history_path) as recovered:
                        recovered.advance_until(1, max_events=None if boundary == 'clock' else 1)
                        self.assertEqual(recovered.revision, world.revision + 1)
                        self.assertEqual(recovered.history.revision, recovered.revision)
                    self.assertEqual(sim.revision, world.revision)
                    sim.close()

    def test_uncertain_but_durable_scheduled_commit_keeps_published_runtime(self):
        self.addCleanup(faults.clear)
        for backend in ('memory', 'sqlite'):
            with self.subTest(backend=backend), TemporaryDirectory() as directory:
                sim = self.make_simulation(directory, backend, 'completion')
                previous = sim.revision
                faults.arm('after_history_commit_before_publish', error='EIO')
                try:
                    sim.advance_until(1, max_events=1)
                finally:
                    faults.clear()
                self.assertEqual(sim.revision, previous + 1)
                self.assertEqual(sim.time, 1)
                self.assertIsNone(sim.state['agents']['a']['active_action'])
                self.assertEqual(sim.history.revision, sim.revision)
                sim.close()


if __name__ == '__main__':
    unittest.main()
