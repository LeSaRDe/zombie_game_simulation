"""Mutation checks for test oracles, using synthetic records (not a simulator)."""
from copy import deepcopy
import unittest

from tests.assertions import ContractFailure
from tests.harness.test_invariants import valid_snapshot, valid_trace
from tests.research_checks import baseline_geometry, validate_baseline, validate_trials, validate_performance


def baseline_record():
    result = valid_snapshot()
    result.update(world={"length": "1000", "width": "1000"}, agents={})
    human_roles = [None]*400 + ["DOCTOR"]*80 + ["WARRIOR"]*120 + ["SCOUT"]*80 + ["ENGINEER"]*120
    zombie_roles = [None]*120 + ["TYRANT"]*20 + ["RUNNER"]*30 + ["SPITTER"]*20 + ["SCREAMER"]*10
    for i, role in enumerate(human_roles + zombie_roles):
        key = f"agent_{i}"
        a = deepcopy(valid_snapshot()["agents"]["h"])
        a.update(id=key, role=role, inventory={"FOOD": 0, "MEDICAL_SUPPLY": int(role == "DOCTOR"),
                                            "MATERIAL": int(role == "ENGINEER")})
        if i < 800:
            a.update(x=str((i % 32)*3), y=str((i // 32)*3), model_assignment={"model_id": "HumanDefaultModel"})
        else:
            j = i-800
            a.update(type="Zombie", status="ACTIVE", x=str(850+(j % 20)*3), y=str((j // 20)*3),
                     model_assignment={"model_id": "ZombieDefaultModel"})
            for field in ("hunger", "inventory", "reserved", "carry_capacity"):
                del a[field]
            if role == "SPITTER":
                a["spit_charges"] = 3
        if i < 20:
            ep_id = f"episode_{i}"
            a.update(status="INFECTED", infection_episode=ep_id)
            result["episodes"][ep_id] = {"agent": key, "onset_at": "0", "incubation_duration": "300",
                                          "conversion_due_at": "300", "outcome": "ONGOING"}
        result["agents"][key] = a
    rectangles, stockpiles = baseline_geometry()
    for i, (kind, *rect) in enumerate(rectangles):
        b = {"kind": kind, "rect": list(map(str, rect))}
        if kind == "Gate":
            b.update(mode="CLOSED", integrity=200, max_integrity=200)
        result["barriers"][f"barrier_{i}"] = b
    for i, ((x, y), stock) in enumerate(stockpiles.items()):
        result["stockpiles"][f"stock_{i}"] = {"x": str(x), "y": str(y), "stock": stock, "reserved": {}}
    return result


class ResearchOracleTests(unittest.TestCase):
    @staticmethod
    def performance_record():
        return {"population": 1000, "measured_frames": 1500, "frame_times_ms": [20]*1500,
                "input_latencies_ms": [40]*20, "receipt_ack_latencies_ms": [80]*5,
                "fps": 50, "input_latency_p95_ms": 40, "receipt_ack_p95_ms": 80}

    def test_performance_recomputed_from_samples(self):
        validate_performance(self.performance_record(), {"population": 1000, "duration_seconds": "30"})

    def test_performance_rejects_fabricated_summary_or_short_sample(self):
        for field, value in (("fps", 100), ("input_latency_p95_ms", 1), ("input_latencies_ms", []),
                             ("frame_times_ms", [20]*30)):
            record = self.performance_record()
            record[field] = value
            with self.subTest(field=field), self.assertRaises(ContractFailure):
                validate_performance(record, {"population": 1000, "duration_seconds": "30"})

    def test_valid_synthetic_baseline(self):
        validate_baseline(baseline_record())

    def test_exact_two_metre_separation_is_legal(self):
        snapshot = baseline_record()
        snapshot["agents"]["agent_0"].update(x="1", y="0")
        validate_baseline(snapshot)

    def test_baseline_mutations(self):
        original = baseline_record()
        changes = [lambda s: s["agents"]["agent_0"].update(x="2", y="0"),
                   lambda s: s["agents"]["agent_800"].update(x="94", y="0"),
                   lambda s: s["agents"]["agent_400"]["inventory"].update(MEDICAL_SUPPLY=0),
                   lambda s: s["agents"]["agent_0"].update(role="DOCTOR"),
                   lambda s: s["barriers"].pop("barrier_0"),
                   lambda s: s["stockpiles"]["stock_0"]["stock"].update(FOOD=61),
                   lambda s: s["agents"]["agent_0"]["model_assignment"].update(model_id="Other"),
                   lambda s: s["episodes"]["episode_0"].update(outcome="CURED")]
        for i, mutate in enumerate(changes):
            with self.subTest(mutation=i):
                snapshot = deepcopy(original)
                mutate(snapshot)
                with self.assertRaises(ContractFailure):
                    validate_baseline(snapshot)

    @staticmethod
    def trials(successes=72):
        records = []
        for seed in range(100):
            outcome = seed < successes
            trace = valid_trace()
            trace["snapshots"]["end"] = trace["snapshots"].pop("initial")
            trace["snapshots"]["end"]["agents"]["h"]["life"] = 86 if outcome else 100
            trace["random_draws"] = [{"channel": "hit", "probability": "0.72", "value": "0" if outcome else "0.99", "outcome": outcome}]
            records.append({"seed": seed, "trace": trace})
        return records

    def test_raw_trials_with_expected_frequency(self):
        validate_trials(self.trials(), {"seeds": list(range(100)), "kind": "hit", "probability": "0.72"})

    def test_all_successes_fail_frequency_check(self):
        with self.assertRaises(ContractFailure):
            validate_trials(self.trials(100), {"seeds": list(range(100)), "kind": "hit", "probability": "0.72"})

    def test_trial_seed_and_effect_corruption(self):
        for corrupt in ("seed", "life"):
            records = self.trials()
            if corrupt == "seed":
                records[0]["seed"] = 1
            else:
                records[0]["trace"]["snapshots"]["end"]["agents"]["h"]["life"] = 99
            with self.subTest(corrupt=corrupt), self.assertRaises(ContractFailure):
                validate_trials(records, {"seeds": list(range(100)), "kind": "hit", "probability": "0.72"})
