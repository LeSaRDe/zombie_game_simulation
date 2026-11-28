"""Domain objects must own actual simulation transitions, not unused wrappers."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from zombie_sim.engine import Simulation
from zombie_sim.domain_model import Agent, HumanState, ZombieState
from zombie_sim.testing import fixture_config


class DomainIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix="deep-oop-domain-integration-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def simulation(self, agents, **options):
        config = fixture_config({"length": "100", "width": "100", "agents": agents}, {
            "decision_mode": "scripted", "workers": 1, "seed": 3917, **options})
        sim = Simulation(config, history_path=self.root / (str(len(list(self.root.iterdir()))) + ".sqlite"))
        self.addCleanup(sim.close)
        return sim

    def test_OOP_STATE_OWNERSHIP_spatial_index_survives_admission_and_cancellation(self):
        sim = self.simulation([{"id": "h", "type": "Human", "x": 49, "y": 10,
                               "infection": {"onset_at": "0", "incubation_duration": "1/4"}}])
        original = sim.state_coordinator.current_world
        self.assertNotIn("h", original.spatial_index.candidates((53, 10), 0))
        sim.submit_intents([{"id": "walk", "actor": "h", "action": "move", "parameters": {
            "duration": "2", "path": [{"x": 49, "y": 10, "offset": "0"},
                                       {"x": 53, "y": 10, "offset": "2"}]}}])
        admitted = sim.state_coordinator.current_world
        self.assertIn("h", admitted.spatial_index.candidates((53, 10), 0))
        self.assertNotIn("h", original.spatial_index.candidates((53, 10), 0))
        sim.advance_until("1/4")
        cancelled = sim.state_coordinator.current_world
        self.assertIsInstance(cancelled.agent("h").current_state, ZombieState)
        self.assertIsNone(cancelled.agent("h").to_record()["active_action"])
        self.assertAlmostEqual(sim.snapshot()["agents"]["h"]["x"], 49.5)
        self.assertNotIn("h", cancelled.spatial_index.candidates((53, 10), 0))
        self.assertIn("h", admitted.spatial_index.candidates((53, 10), 0))
        self.assertNotIn("h", original.spatial_index.candidates((53, 10), 0))

    def test_OOP_IDENTITY_real_conversion_replaces_state_not_identity(self):
        sim = self.simulation([{"id": "h", "type": "Human", "role": "DOCTOR", "x": 10, "y": 10,
                                "life": 64, "stamina": 32,
                                "infection": {"onset_at": "0", "incubation_duration": "3"},
                                "inventory": {"FOOD": 2, "MEDICAL_SUPPLY": 1, "MATERIAL": 0}}])
        before = sim.state_coordinator.current_world.agent("h")
        self.assertIsInstance(before, Agent)
        self.assertIsInstance(before.current_state, HumanState)
        before_record = before.to_record()
        sim.submit_intents([{"id": "rest", "actor": "h", "action": "rest", "parameters": {"duration": 5}}])
        sim.advance_until(3)
        after = sim.state_coordinator.current_world.agent("h")
        self.assertEqual(after.identity, before.identity)
        self.assertIsInstance(after.current_state, ZombieState)
        self.assertEqual(before.to_record(), before_record, "An issued old state must not mutate on conversion")
        observed = after.to_record()
        self.assertEqual((observed["id"], observed["type"], observed["role"], observed["life"]), ("h", "Zombie", None, 64))
        self.assertEqual(observed["stamina"], 44)
        self.assertNotIn("inventory", observed)
        self.assertNotIn("hunger", observed)
        self.assertEqual(sum(s["inventory"]["FOOD"] for s in sim.snapshot()["stockpiles"].values()), 2)
        self.assertEqual(sum(s["inventory"]["MEDICAL_SUPPLY"] for s in sim.snapshot()["stockpiles"].values()), 1)

    def test_OOP_STATE_OWNERSHIP_simulation_state_is_detached(self):
        sim = self.simulation([{"id": "h", "type": "Human", "x": 10, "y": 10, "life": 87}])
        public = sim.state
        # A read-only mapping or a mutable detached DTO is valid; mutation must
        # never reach the authoritative world or its historical initial state.
        try:
            public["agents"]["h"]["life"] = 0
        except (TypeError, AttributeError):
            pass
        self.assertEqual(sim.snapshot()["agents"]["h"]["life"], 87)
        self.assertEqual(sim.state_coordinator.current_world.agent("h").to_record()["life"], 87)
        self.assertEqual(sim.history.state_at(revision=0)["agents"]["h"]["life"], 87)

    def test_OOP_STATE_OWNERSHIP_snapshot_and_typed_record_are_detached(self):
        sim = self.simulation([{"id": "h", "type": "Human", "x": 10, "y": 10, "life": 87}])
        agent = sim.state_coordinator.current_world.agent("h")
        canonical = deepcopy(agent.to_record())
        output = agent.to_record()
        output["inventory"]["FOOD"] = 12345
        output["life"] = 0
        snapshot = sim.snapshot()
        snapshot["agents"]["h"]["life"] = 1
        self.assertEqual(agent.to_record(), canonical)
        self.assertEqual(sim.snapshot()["agents"]["h"]["life"], 87)

    def test_OOP_ROLES_retirement_uses_real_lifecycle_and_preserves_identity(self):
        sim = self.simulation([{"id": "e", "type": "Human", "role": "ENGINEER", "x": 10, "y": 10,
                               "life": 70, "stamina": 30,
                               "inventory": {"FOOD": 10, "MEDICAL_SUPPLY": 0, "MATERIAL": 6}}],
                              interventions_enabled=True)
        original = sim.state_coordinator.current_world.agent("e")
        sim.intervene({"kind": "replace_role", "agent": "e", "role": None,
                       "drop_order": ["MATERIAL", "FOOD", "MEDICAL_SUPPLY"]}, at="1", id="retire")
        sim.advance_until(1)
        retired = sim.state_coordinator.current_world.agent("e")
        self.assertEqual(retired.identity, original.identity)
        self.assertEqual(original.to_record()["role"], "ENGINEER")
        self.assertIsNone(retired.to_record()["role"])
        self.assertEqual(retired.to_record()["life"], 70)
        self.assertEqual(retired.to_record()["stamina"], 30)
        self.assertEqual(retired.to_record()["inventory"], {"FOOD": 10, "MEDICAL_SUPPLY": 0, "MATERIAL": 0})
        self.assertEqual(sum(s["inventory"]["MATERIAL"] for s in sim.snapshot()["stockpiles"].values()), 6)

    def test_OOP_STATE_TYPES_death_retains_human_variant_and_identity(self):
        sim = self.simulation([{"id": "h", "type": "Human", "x": 10, "y": 10, "life": 1,
                               "hunger": 100, "infection": {"onset_at": "0", "incubation_duration": "10"}}])
        before = sim.state_coordinator.current_world.agent("h")
        sim.advance_until(10)
        after = sim.state_coordinator.current_world.agent("h")
        self.assertEqual(after.identity, before.identity)
        self.assertIsInstance(after.current_state, HumanState)
        self.assertEqual(after.to_record()["life"], 0)
        self.assertEqual(after.to_record()["status"], "DEAD")
        self.assertEqual(len(sim.snapshot()["remains"]), 1)
        sim.advance_until(20)
        self.assertEqual(len(sim.snapshot()["remains"]), 1)
        self.assertEqual(sim.state_coordinator.current_world.agent("h").to_record()["life"], 0)


if __name__ == "__main__":
    unittest.main()
