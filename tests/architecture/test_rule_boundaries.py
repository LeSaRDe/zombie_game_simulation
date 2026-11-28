"""Rules execute from typed inputs without a Simulation or persistence handle."""
from copy import deepcopy
from fractions import Fraction
import unittest
from unittest.mock import patch

from zombie_sim.config import resolve_config, initialize_world
from zombie_sim.game_rules import GameRuleSet, RuleRequest, TransitionPlan, ActionHandler, ActionHandlerRegistry
from zombie_sim.game_rules.handlers import WaitHandler
from zombie_sim.state_management import WorldAggregate, RuntimeSnapshot
from zombie_sim.registry import ACTIONS


def inputs():
    config = resolve_config({"agents": [{"id": "h", "type": "Human", "x": 10, "y": 10,
                                       "life": 87, "stamina": 80}],
                             "decision_mode": "scripted", "horizon": 10, "seed": 3917})
    raw = initialize_world(config)
    raw.update(run_id="rule-contract", time="0", revision=0)
    agent = raw["agents"]["h"]
    agent.update(_evaluated_at="0", _generation=0)
    agent.pop("infected", None)
    agent.pop("model_memory", None)
    world = WorldAggregate.from_record(raw)
    runtime = RuntimeSnapshot.from_attributes({"config": config, "time": Fraction(0), "revision": 0,
        "seed": 3917, "horizon": Fraction(10), "queue": [], "memories": {},
        "_identity_counters": {}, "_counter": 0, "_serial": 0, "_decision_due": set(),
        "_prepared_boundary": None, "_batching": False, "_deferred_events": [], "_effects_buffer": [],
        "_dirty": set(), "_last_checkpoint": Fraction(0), "_since_checkpoint": 0,
        "decision_mode": "scripted", "run_status": "PAUSED", "termination_reason": None})
    return config, world, runtime


class RuleBoundaryTests(unittest.TestCase):
    def test_OOP_RULE_BOUNDARY_transition_plan_detaches_every_nested_projection(self):
        _, _, runtime = inputs()
        metadata = {"lineage": {"ancestors": ["parent"]}}
        result = [{"id": "intent", "details": {"costs": [2]}}]
        queue_delta = (["set", ["queue", "1"], {"nested": ["event"]}],)
        diagnostics = {"read": {"ids": ["h"]}}
        plan = TransitionPlan(0, "0", (), (), runtime, metadata, result, queue_delta,
                              diagnostics=diagnostics)
        original = deepcopy((metadata, result, queue_delta, diagnostics))
        metadata["lineage"]["ancestors"].append("input-alias")
        result[0]["details"]["costs"].append(99)
        queue_delta[0][2]["nested"].append("input-alias")
        diagnostics["read"]["ids"].append("input-alias")
        exposed_metadata, exposed_result = plan.metadata, plan.result
        exposed_queue, exposed_diagnostics = plan.queue_delta, plan.diagnostics
        exposed_metadata["lineage"]["ancestors"].append("output-alias")
        exposed_result[0]["details"]["costs"].append(99)
        exposed_queue[0][2]["nested"].append("output-alias")
        exposed_diagnostics["read"]["ids"].append("output-alias")
        self.assertEqual((plan.metadata, plan.result, plan.queue_delta, plan.diagnostics), original)

    def test_OOP_ACTIVITY_handler_registry_covers_exact_frozen_catalog(self):
        handlers = ActionHandlerRegistry()
        self.assertEqual(set(handlers), set(ACTIONS))
        self.assertEqual(len(handlers), 29)
        for name in handlers:
            self.assertIsInstance(handlers[name], ActionHandler)
            self.assertEqual(handlers[name].action, name)
            for operation in ("validate_admission", "declare_access", "admit", "resolve", "cancel"):
                self.assertTrue(callable(getattr(handlers[name], operation)))
        omitted = {name: handlers[name] for name in handlers if name != "wait"}
        with self.assertRaises(ValueError):
            ActionHandlerRegistry(omitted)

    def test_OOP_RULE_BOUNDARY_real_admission_produces_typed_plan_without_io(self):
        config, world, runtime = inputs()
        rules = GameRuleSet()
        original_world, original_runtime, original_config = world.to_record(), runtime.to_attributes(), deepcopy(config)
        request = RuleRequest("admit", {"intents": [{"id": "wait-1", "actor": "h", "action": "wait",
                                                    "parameters": {"duration": "1"}}]})
        with patch("sqlite3.connect", side_effect=AssertionError("A rule opened a database")), \
             patch("builtins.open", side_effect=AssertionError("A rule opened a file")):
            plan = rules.plan(request, world.read_view(), runtime, config=config)
        self.assertIsInstance(plan, TransitionPlan)
        self.assertEqual(plan.expected_revision, 0)
        self.assertEqual(plan.time, "0")
        changed = {(change.collection, change.identity): change.value for change in plan.changes}
        self.assertIn(("agents", "h"), changed)
        self.assertEqual(changed["agents", "h"].to_record()["life"], 87)
        self.assertIsNotNone(changed["agents", "h"].to_record()["active_action"])
        self.assertTrue(any(event.to_record()["kind"] == "action_started" for event in plan.events))
        self.assertTrue(any(change.collection == "occurrences" for change in plan.changes))
        self.assertEqual(world.to_record(), original_world)
        self.assertEqual(runtime.to_attributes(), original_runtime)
        self.assertEqual(config, original_config)
        self.assertEqual(world.revision, 0, "Planning is not publication")

    def test_OOP_RULE_BOUNDARY_injected_handler_is_used_by_actual_admission(self):
        class CountWait(WaitHandler):
            def __init__(self):
                super().__init__()
                self.calls = 0

            def validate_admission(self, *args, **kwargs):
                self.calls += 1
                return super().validate_admission(*args, **kwargs)

        defaults = ActionHandlerRegistry()
        handler = CountWait()
        registry = ActionHandlerRegistry({name: handler if name == "wait" else defaults[name] for name in defaults})
        config, world, runtime = inputs()
        plan = GameRuleSet(registry).plan(RuleRequest("admit", {"intents": [{"id": "wait-1", "actor": "h",
            "action": "wait", "parameters": {"duration": "1"}}]}), world.read_view(), runtime, config=config)
        self.assertGreater(handler.calls, 0, "An unused class wrapper does not satisfy the extension contract")
        self.assertTrue(any(event.to_record()["kind"] == "action_started" for event in plan.events))
        self.assertEqual(world.revision, 0)

    def test_OOP_RULE_BOUNDARY_unknown_request_does_not_change_inputs(self):
        config, world, runtime = inputs()
        before = world.to_record(), runtime.to_attributes()
        with self.assertRaises(ValueError):
            GameRuleSet().plan(RuleRequest("invented_transition", {}), world.read_view(), runtime, config=config)
        self.assertEqual((world.to_record(), runtime.to_attributes()), before)


if __name__ == "__main__":
    unittest.main()
