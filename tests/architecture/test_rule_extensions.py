"""Actual Simulation rule composition and exact restart provenance contracts."""
from copy import deepcopy
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from zombie_sim.core.composition import ServiceBindingMismatch
from zombie_sim.engine import Simulation
from zombie_sim.game_rules import GameRuleSet, ActionHandlerRegistry
from zombie_sim.game_rules.handlers import WaitHandler
from zombie_sim.runtime import _digest


# These witnesses observe actual calls without introducing unrecorded instance
# state into the extension. Rule behavior itself remains deterministic/stateless.
CALLS = []


class RecordedWait(WaitHandler):
    def validate_admission(self, *args, **kwargs):
        CALLS.append("wait-admission")
        return super().validate_admission(*args, **kwargs)


class RecordedRules(GameRuleSet):
    def plan(self, request, *args, **kwargs):
        CALLS.append(request.kind)
        return super().plan(request, *args, **kwargs)


class OtherRules(GameRuleSet):
    pass


def custom_rules():
    defaults = ActionHandlerRegistry()
    return RecordedRules(ActionHandlerRegistry({key: RecordedWait() if key == "wait" else defaults[key]
                                               for key in defaults}))


class RuleExtensionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix="deep-oop-rule-extension-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        CALLS.clear()

    def simulation(self, **options):
        sim = Simulation({"agents": [{"id": "h", "type": "Human", "x": 10, "y": 10}],
                          "decision_mode": "scripted", "workers": 1, "horizon": 10},
                         history_path=self.root / "source.sqlite", **options)
        self.addCleanup(sim.close)
        return sim

    def admit(self, sim, identity):
        CALLS.clear()
        sim.submit_intents([{"id": identity, "actor": "h", "action": "wait",
                             "parameters": {"duration": "1"}}])
        self.assertIn("admit", CALLS)
        self.assertIn("wait-admission", CALLS)
        self.assertIsNotNone(sim.snapshot()["agents"]["h"]["active_action"])

    def test_OOP_RULE_EXTENSION_real_simulation_checkpoint_journal_and_branch(self):
        original = self.simulation(rule_set=custom_rules())
        self.admit(original, "before")
        original.advance_until(1)
        checkpoint = original.checkpoint(self.root / "checkpoint.json")
        source_state = original.snapshot()
        manifest = original.serialize()["attributes"]["rule_bindings"]
        self.assertEqual(manifest["schema"], "zombie-sim/rule-bindings-v1")
        self.assertEqual(manifest["rules"][0]["file_sha256"], hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        restored = Simulation.restore(checkpoint, history_path=self.root / "restored.sqlite", rule_set=custom_rules())
        self.addCleanup(restored.close)
        self.assertEqual(restored.snapshot(), source_state)
        self.admit(restored, "restored")
        restored.advance_until(2)
        journal = Simulation.restore_revision(original.history_path, output_history_path=self.root / "journal.sqlite",
                                               rule_set=custom_rules())
        self.addCleanup(journal.close)
        self.assertEqual(journal.snapshot(), source_state)
        self.admit(journal, "journal")
        branch = original.branch(self.root / "branch.sqlite")
        self.addCleanup(branch.close)
        self.assertNotEqual(branch.state_coordinator.current_world.run_id, original.state_coordinator.current_world.run_id)
        self.admit(branch, "branch")
        self.assertEqual(original.snapshot(), source_state)

    def test_OOP_RULE_EXTENSION_missing_wrong_or_changed_source_rejected_before_writes(self):
        original = self.simulation(rule_set=custom_rules())
        checkpoint = original.checkpoint(self.root / "checkpoint.json")
        for name, options in (("missing", {}), ("wrong", {"rule_set": OtherRules()})):
            destination = self.root / (name + ".sqlite")
            with self.subTest(binding=name), self.assertRaises(ServiceBindingMismatch):
                Simulation.restore(checkpoint, history_path=destination, **options)
            self.assertFalse(destination.exists())
        payload = deepcopy(original.serialize())
        payload["attributes"]["rule_bindings"]["rules"][0]["file_sha256"] = "0" * 64
        payload["attributes_sha256"] = _digest(payload["attributes"])
        destination = self.root / "changed-source.sqlite"
        with self.assertRaises(ServiceBindingMismatch):
            Simulation.from_serialized(payload, history_path=destination, rule_set=custom_rules())
        self.assertFalse(destination.exists())

    def test_OOP_RULE_EXTENSION_stateful_rule_or_handler_rejected_before_writes(self):
        for name, rule in (("rule", custom_rules()), ("handler", custom_rules())):
            if name == "rule":
                rule.unrecorded_parameter = 4
            else:
                rule.handlers["wait"].unrecorded_parameter = 4
            with self.subTest(binding=name), self.assertRaisesRegex(ValueError, "unrecorded instance state"):
                self.simulation(rule_set=rule)
            self.assertFalse((self.root / "source.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
