from copy import deepcopy
import unittest
from tests.assertions import ContractFailure
from tests.invariants import validate_snapshot, validate_trace


def valid_snapshot():
    return {"time": "0", "revision": "0", "world": {"length": "100", "width": "100"},
            "agents": {"h": {"id": "h", "type": "Human", "role": None, "status": "HEALTHY", "life": 100,
                             "x": "10", "y": "10", "stamina": "100", "hunger": "20",
                             "inventory": {"FOOD": 1}, "reserved": {}, "carry_capacity": 10,
                             "active_action": None, "infection_episode": None, "effects": {}, "cooldowns": {}}},
            "barriers": {}, "stockpiles": {}, "remains": {}, "episodes": {}, "reservations": {}, "signals": {}}


def valid_trace():
    return {"snapshots": {"initial": valid_snapshot()}, "intents": {}, "occurrences": {},
            "observations": {}, "events": [], "random_draws": []}


class InvariantHarnessTests(unittest.TestCase):
    def test_valid_record(self):
        validate_trace(valid_trace())

    def test_mutations_of_state_are_detected(self):
        mutations = {"life": 101, "stamina": "-1", "hunger": "NaN", "status": "ACTIVE",
                     "role": "TYRANT", "x": "101", "inventory": {"FOOD": 11},
                     "reserved": {"FOOD": 2}, "carry_capacity": True, "life_boolean": True}
        for field, value in mutations.items():
            with self.subTest(field=field):
                snap = valid_snapshot()
                snap["agents"]["h"]["life" if field == "life_boolean" else field] = value
                with self.assertRaises(ContractFailure):
                    validate_snapshot(snap)

    def test_wall_contact_is_forbidden(self):
        snap = valid_snapshot()
        snap["barriers"]["wall"] = {"kind": "Obstacle", "rect": ["10", "9", "11", "11"]}
        with self.assertRaises(ContractFailure):
            validate_snapshot(snap)

    def test_gate_integrity_disagreement(self):
        snap = valid_snapshot()
        snap["barriers"]["g"] = {"kind": "Gate", "rect": ["40", "40", "42", "46"],
                                  "integrity": 10, "max_integrity": 200, "mode": "BREACHED"}
        with self.assertRaises(ContractFailure):
            validate_snapshot(snap)

    def test_causal_cycle_and_missing_predecessor(self):
        for causes in (["e"], ["missing"]):
            trace = valid_trace()
            trace["events"] = [{"id": "e", "causes": causes}]
            with self.assertRaises(ContractFailure):
                validate_trace(trace)

    def test_recorded_draw_law(self):
        trace = valid_trace()
        trace["random_draws"] = [{"intent": "a", "channel": "hit", "probability": "0.5",
                                  "value": "0.5", "outcome": True}]
        with self.assertRaises(ContractFailure):
            validate_trace(trace)
        trace["random_draws"][0]["outcome"] = False
        validate_trace(trace)

    def test_missing_snapshot_fields_are_not_skipped(self):
        snap = valid_snapshot()
        del snap["agents"]["h"]["life"]
        with self.assertRaises(ContractFailure):
            validate_snapshot(snap)

    def test_resurrection_is_detected(self):
        trace = valid_trace()
        dead = deepcopy(trace["snapshots"]["initial"])
        dead["agents"]["h"].update(life=0, status="DEAD", inventory={}, reserved={})
        dead["time"] = "1"
        dead["revision"] = "1"
        alive = valid_snapshot()
        alive.update(time="2", revision="2")
        trace["snapshots"].update(dead=dead, resurrected=alive)
        with self.assertRaises(ContractFailure):
            validate_trace(trace)
