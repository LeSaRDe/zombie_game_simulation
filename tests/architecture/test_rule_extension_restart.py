"""Explicit custom rules survive every restore route without silent defaults."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from zombie_sim.core import ServiceBindingMismatch
from zombie_sim.engine import Simulation
from zombie_sim.game_rules import GameRuleSet


class ResearchRules(GameRuleSet):
    """Inspectable, stateless extension retaining ontology semantics."""


class RuleRestartTests(unittest.TestCase):
    def test_custom_rules_require_original_binding_and_survive_all_restart_routes(self):
        with TemporaryDirectory(prefix='custom-rule-restart-') as folder:
            root = Path(folder)
            rules = ResearchRules()
            config = {'agents': [{'id':'a', 'type':'Human', 'x':10, 'y':10}],
                      'decision_mode':'scripted', 'horizon':3, 'execution': {'workers':1}}
            with Simulation(config, history_path=root/'source.sqlite', rule_set=rules) as original:
                original.submit_intents([{'actor':'a','action':'wait','parameters':{'duration':2}}])
                original.advance_until(1)
                payload = original.serialize()
                checkpoint = original.checkpoint(root/'checkpoint.json')
                destination = root/'rejected.sqlite'
                with self.assertRaisesRegex(ServiceBindingMismatch, 'original explicit rule_set'):
                    Simulation.from_serialized(payload, history_path=destination)
                self.assertFalse(destination.exists())
                for label, restore in (
                    ('snapshot', lambda: Simulation.from_serialized(payload, rule_set=rules)),
                    ('checkpoint', lambda: Simulation.restore(checkpoint, rule_set=rules)),
                    ('journal', lambda: Simulation.restore_revision(original.history_path, rule_set=rules)),
                ):
                    with self.subTest(route=label), restore() as resumed:
                        self.assertIs(resumed._runtime_rules, rules)
                        self.assertEqual(resumed.state, original.state)
                        resumed.advance_until(3)
                        self.assertEqual(resumed.world_view['agents']['a']['active_action'], None)
                        self.assertEqual(resumed.time, 3)
                with original.branch(root/'child') as child:
                    self.assertIs(child._runtime_rules, rules)
                    self.assertEqual(child.rule_bindings, original.rule_bindings)
                    child.advance_until(3)
                    self.assertEqual(child.world_view['agents']['a']['active_action'], None)


if __name__ == '__main__':
    unittest.main()
