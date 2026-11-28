"""Extension migration is explicit; read customizations have no writer access."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from zombie_sim.engine import Simulation
from zombie_sim.core import SimulationServiceFactory
from zombie_sim.core.actions import ActionService
from zombie_sim.core.migration import LegacyExtensionError
from zombie_sim.core.observations import ObservationService
from zombie_sim.core.randomness import RandomService


class CountingObservations(ObservationService):
    def observe(self, identity):
        self.calls = getattr(self, 'calls', 0) + 1
        return super().observe(identity)


class LegacyActionOverride(ActionService):
    pass


class LegacyNearbyOverride(Simulation):
    def _nearby(self, position, radius):
        return super()._nearby(position, radius)


class ExtensionMigrationTests(unittest.TestCase):
    def test_read_only_observation_override_uses_projection_and_preserves_ledger(self):
        factory = SimulationServiceFactory({'observations': CountingObservations})
        with Simulation({'preset': 'small', 'horizon': 2}, workers=1, service_factory=factory) as sim:
            before = sim.state
            observation = sim.observe(next(iter(sim.state['agents'])))
            service = sim.services.observations
            self.assertEqual(service.calls, 1)
            for forbidden in ('history', 'store', 'state_coordinator', '_run_rule', '_commit'):
                self.assertFalse(hasattr(service.context, forbidden), forbidden)
            observation['self_state']['life'] = 0
            self.assertEqual(sim.state, before)
            payload = sim.serialize()
            with Simulation.from_serialized(payload, workers=1, service_factory=factory) as resumed:
                self.assertIsInstance(resumed.services.observations, CountingObservations)
                self.assertEqual(resumed.state, before)

    def test_legacy_mutation_binding_fails_before_a_run_can_be_created(self):
        with self.assertRaisesRegex(LegacyExtensionError, 'actions.*GameRuleSet/ActionHandler'):
            SimulationServiceFactory({'actions': LegacyActionOverride})
        with self.assertRaisesRegex(LegacyExtensionError, 'actions.*GameRuleSet/ActionHandler'):
            SimulationServiceFactory().validate_restart({'services': {'actions': {'class': 'Legacy'}}})
        with self.assertRaisesRegex(LegacyExtensionError, 'ActionService'):
            ActionService(object())

    def test_legacy_simulation_private_override_fails_before_opening_ledger(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'never-created.sqlite'
            with self.assertRaisesRegex(LegacyExtensionError, '_nearby.*ReadProjection'):
                LegacyNearbyOverride({'preset': 'small'}, history_path=path, workers=1)
            self.assertFalse(path.exists())

    def test_random_primitive_has_no_context_and_controlled_input_is_detached(self):
        primitive = RandomService()
        self.assertFalse(hasattr(primitive, 'context'))
        self.assertEqual(primitive.value(42, 'policy', 'a:1/3'), primitive.value(42, 'policy', 'a:1/3'))
        previous = {('a', 'hit'): 0.25}
        actual = primitive.controlled_values([{'intent': 'b', 'channel': 'infection', 'value': '1/2'}], previous)
        self.assertEqual(previous, {('a', 'hit'): 0.25})
        self.assertEqual(actual[('b', 'infection')], .5)


if __name__ == '__main__':
    unittest.main()
