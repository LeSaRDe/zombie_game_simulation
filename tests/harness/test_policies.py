"""Mutation tests for policy oracles; these are not a simulator adapter."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from tests.assertions import ContractFailure
from tests.harness.test_invariants import valid_trace
from tests.policy_checks import validate_policy_result, validate_utility_decision
from tests.spec.dsl import agent, world
from tests.spec.policies import cases, witness_bank


def decision():
    return {"id": "d", "time": "0", "observation_id": "o", "intent_id": "i",
            "before_snapshot": "initial", "after_snapshot": "after", "selected_candidate_id": "c0",
            "reason": "Keep the agreed rendezvous while already at full energy.", "candidates": [
        {"id": "c0", "observable_feasible": True, "reason": "Hold the rendezvous.", "score": "1",
         "intent": {"id": "proposal", "actor": "h", "action": "wait", "parameters": {"duration": "1"}},
         "terms": [{"feature": "objective_progress", "value": "1", "weight_path": "/weights/hold", "contribution": "1"}]},
        {"id": "c1", "observable_feasible": True, "reason": "Recovery has little value at full energy.", "score": "0.2",
         "intent": {"id": "rest", "actor": "h", "action": "rest", "parameters": {"duration": "1"}},
         "terms": [{"feature": "recovery", "value": "0.1", "weight_path": "/weights/recovery", "contribution": "0.2"}]}]}


def fixture():
    memory = {"objective": {"kind": "hold_location", "position": ["10", "10"], "until": "10"}, "recent_reports": []}
    context = {"id": "ctx", "world": world(agent("h", inventory={"FOOD": 1})), "actor": "h",
               "model": "HumanDefaultModel", "max_decisions": 8, "horizon": "35", "memory_seed": memory}
    parameters = {"weights": {"hold": "1", "recovery": "2"}}
    trace = valid_trace()
    after = deepcopy(trace["snapshots"]["initial"])
    after.update(time="1", revision="1")
    after["agents"]["h"]["hunger"] = "20.05"
    trace["snapshots"]["after"] = after
    trace["intents"]["i"] = {"id": "i", "actor": "h", "action": "wait", "parameters": {"duration": "1"},
                              "status": "ADMITTED", "decision_id": "d"}
    trace["occurrences"]["i"] = {"actor": "h", "action": "wait", "result": "SUCCEEDED", "start_at": "0",
                                  "planned_end": "1", "resolved_at": "1"}
    trace["observations"]["o"] = {"self_state": {"id": "h"}, "time": "0"}
    response = {"default_models": {"HumanDefaultModel": {"version": "1", "parameters": deepcopy(parameters)}},
                "contexts": {"ctx": {"model": {"id": "HumanDefaultModel", "version": "1", "parameters": parameters},
                                      "memory_seed": memory, "trace": trace, "decisions": [decision()]}}}
    spec = {"kind": "default_bank", "contexts": [context], "actions": ["wait"],
            "review": {"ctx": {"actions": ["wait"], "reason": "Safe rendezvous."}}}
    return response, spec


class PolicyHarnessTests(unittest.TestCase):
    def test_valid_utility_components_and_actual_action(self):
        value, spec = fixture()
        validate_policy_result(value, spec)

    def test_false_utility_components_are_detected(self):
        for field, value in (("score", "9"), ("contribution", "9"), ("value", "2"), ("weight_path", "/weights/missing")):
            with self.subTest(field=field):
                row = decision()
                target = row["candidates"][0] if field == "score" else row["candidates"][0]["terms"][0]
                target[field] = value
                with self.assertRaises(ContractFailure):
                    validate_utility_decision(row, {"weights": {"hold": "1", "recovery": "2"}})

    def test_lower_score_or_masked_choice_is_not_accepted(self):
        for mutate in (lambda d: d.update(selected_candidate_id="c1"),
                       lambda d: d["candidates"][0].update(observable_feasible=False)):
            row = decision()
            mutate(row)
            with self.assertRaises(ContractFailure):
                validate_utility_decision(row, {"weights": {"hold": "1", "recovery": "2"}})

    def test_tied_score_does_not_force_one_candidate(self):
        row = decision()
        row["candidates"][1]["terms"][0].update(value="0.5", contribution="1")
        row["candidates"][1]["score"] = "1"
        for selected in ("c0", "c1"):
            row["selected_candidate_id"] = selected
            validate_utility_decision(row, {"weights": {"hold": "1", "recovery": "2"}})

    def test_score_override_cannot_make_a_focus_choice_pass(self):
        value, spec = fixture()
        value["contexts"]["ctx"]["model"]["parameters"]["weights"]["hold"] = "1000000"
        with self.assertRaises(ContractFailure):
            validate_policy_result(value, spec)

    def test_selection_without_real_effect_is_not_a_witness(self):
        value, spec = fixture()
        value["contexts"]["ctx"]["trace"]["snapshots"]["after"]["agents"]["h"]["stamina"] = "99"
        with self.assertRaisesRegex(ContractFailure, "Wait regenerated"):
            validate_policy_result(value, spec)

    def test_changed_engine_intent_is_detected(self):
        value, spec = fixture()
        value["contexts"]["ctx"]["trace"]["intents"]["i"]["parameters"]["duration"] = "2"
        with self.assertRaisesRegex(ContractFailure, "different intent"):
            validate_policy_result(value, spec)

    def test_rejection_does_not_count_as_a_demonstration(self):
        value, spec = fixture()
        value["contexts"]["ctx"]["trace"]["intents"]["i"]["status"] = "REJECTED"
        with self.assertRaisesRegex(ContractFailure, "lacks real"):
            validate_policy_result(value, spec)

    def test_claimed_coverage_does_not_replace_missing_witnesses(self):
        value, spec = fixture()
        spec["actions"].append("rally")
        value["executable_actions"] = ["wait", "rally"]
        with self.assertRaisesRegex(ContractFailure, "rally"):
            validate_policy_result(value, spec)

    def test_modified_initial_world_is_detected(self):
        value, spec = fixture()
        value["contexts"]["ctx"]["trace"]["snapshots"]["initial"]["agents"]["h"]["life"] = 50
        with self.assertRaisesRegex(ContractFailure, "initial agent state"):
            validate_policy_result(value, spec)

    def test_encoder_rejects_parameter_loss_padding_and_mapping_errors(self):
        value, _ = fixture()
        intent = {"id": "i", "actor": "h", "action": "wait", "parameters": {"duration": "1"}}
        spec = {"kind": "encoder_bank", "contexts": {"one": {"intent": intent, "checks": [
            {"path": "/occurrences/i/result", "op": "eq", "value": "SUCCEEDED"}]}}}
        response = {"contexts": {"one": {"decoded_intents": [deepcopy(intent)], "candidate_mask": [True, False, False],
                      "padding_rejected_indices": [1, 2], "index_to_intent": {"0": "i"},
                      "trace": value["contexts"]["ctx"]["trace"]}}}
        validate_policy_result(response, spec)
        for field, replacement in (("decoded_intents", []), ("candidate_mask", [True, True, False]),
                                   ("padding_rejected_indices", [1]), ("index_to_intent", {"0": "other"})):
            with self.subTest(field=field):
                broken = deepcopy(response)
                broken["contexts"]["one"][field] = replacement
                with self.assertRaises(ContractFailure):
                    validate_policy_result(broken, spec)

    def test_catalog_covers_vocabulary_without_injecting_expected_choices(self):
        manifest = json.loads((Path(__file__).resolve().parents[2] / "ontology/formal_v0.1/manifest.json").read_text())
        inputs, review = witness_bank()
        self.assertEqual({a for r in review.values() for a in r["actions"]}, set(manifest["actions"]))
        for context in inputs:
            self.assertNotIn("actions", context)
            self.assertNotIn("weights", context)
            self.assertNotIn("candidates", context)
            for event in context["background_events"]:
                self.assertTrue(all(i["actor"] != context["actor"] for i in event["intents"]))
        encoder = cases()[1]
        self.assertEqual({f["candidates"][0]["action"] for f in encoder["request"]["setup"]["encoder_bank"]}, set(manifest["actions"]))


if __name__ == "__main__":
    unittest.main()
