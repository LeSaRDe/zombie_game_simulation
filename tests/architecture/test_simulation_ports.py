"""The actual runner must use an injected non-SQL persistence combination."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from zombie_sim.engine import Simulation
from zombie_sim.domain_model import ZombieState
from zombie_sim.metrics import MetricsService
from zombie_sim.timeline import TimelineService
from zombie_sim.persistence import PersistenceBundleFactory


class InMemoryOnlyFactory(PersistenceBundleFactory):
    def __init__(self):
        self.created = []

    def create(self, initial, path, backend="memory"):
        self.created.append((initial["run_id"], str(path), backend))
        return super().create(initial, path, "contract-memory")


class SimulationPortTests(unittest.TestCase):
    def test_OOP_BACKEND_actual_simulation_conversion_and_analysis_use_injected_ports(self):
        factory = InMemoryOnlyFactory()
        with TemporaryDirectory(prefix="deep-oop-simulation-ports-") as directory:
            path = Path(directory) / "not-a-sqlite-database.sqlite"
            with patch("sqlite3.connect", side_effect=AssertionError("Simulation or research bypassed its persistence factory")):
                with Simulation({"agents": [{"id": "h", "type": "Human", "role": "DOCTOR", "x": 10, "y": 10,
                                             "life": 64, "stamina": 32, "infected": True,
                                             "inventory": {"FOOD": 2, "MEDICAL_SUPPLY": 1, "MATERIAL": 0}}],
                                 "decision_mode": "scripted", "horizon": 10, "incubation_duration": 3}, workers=1,
                                history_path=path, persistence_factory=factory, run_id="port-contract") as sim:
                    before = sim.state_coordinator.current_world.agent("h")
                    sim.submit_intents([{"id": "rest", "actor": "h", "action": "rest", "parameters": {"duration": 5}}])
                    sim.advance_until(3)
                    after = sim.state_coordinator.current_world.agent("h")
                    self.assertEqual(before.identity, after.identity)
                    self.assertIsInstance(after.current_state, ZombieState)
                    self.assertEqual(after.to_record()["life"], 64)
                    self.assertEqual(after.to_record()["stamina"], 44)
                    self.assertEqual(len(factory.created), 1)
                    self.assertFalse(path.exists(), "Independent in-memory store unexpectedly created a SQLite database")
                    metrics = MetricsService()
                    try:
                        samples = metrics.metrics_at_times(sim.history, ["0", "3"], sim.revision)
                    finally:
                        metrics.close()
                    self.assertEqual((samples[0]["infected"], samples[0]["zombies"]), (1, 0))
                    self.assertEqual((samples[1]["infected"], samples[1]["zombies"]), (0, 1))
                    timeline = TimelineService().page(sim.history, "port-contract", sim.revision, agent="h")
                    self.assertTrue(any(record["kind"] == "conversion" for record in timeline["records"]))
                    retained = sim.snapshot()
                    with self.assertRaisesRegex(ValueError, "nondurable|portable"):
                        sim.checkpoint(Path(directory) / "unsupported.json")
                    self.assertEqual(sim.snapshot(), retained)
                    self.assertFalse((Path(directory) / "unsupported.json").exists())


if __name__ == "__main__":
    unittest.main()
