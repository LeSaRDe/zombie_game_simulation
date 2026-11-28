"""Shared immutable profiles preserve complete field and numeric wire values."""
from dataclasses import FrozenInstanceError, dataclass, fields, replace
import json
import unittest

from zombie_sim.domain import make_agent
from zombie_sim.domain_model import Agent, CodecError
from zombie_sim.domain_model.profiles import ProfileValues, _intern_profile_values


class MutableFloat(float):
    pass


@dataclass(frozen=True)
class ExtendedProfile(ProfileValues):
    marker: str = "extension"


class ProfileInterningTests(unittest.TestCase):
    def test_equal_records_share_only_immutable_named_values(self):
        first = ProfileValues.from_record({"base_speed": 2.0, "rest_rate": 4})
        second = ProfileValues.from_record({"rest_rate": 4, "base_speed": 2.0})
        self.assertIs(first, second)
        self.assertTrue(all(getattr(first, field.name) is None or
                            type(getattr(first, field.name)) in (int, float)
                            for field in fields(first)))
        with self.assertRaises(FrozenInstanceError):
            first.base_speed = 3
        exported = first.to_record()
        exported["base_speed"] = 7
        self.assertEqual(second.base_speed, 2.0)
        changed = replace(first, base_speed=3)
        self.assertEqual(changed.base_speed, 3)
        self.assertEqual(second.base_speed, 2.0)
        self.assertIsInstance(first._record_items, tuple)
        self.assertIsInstance(first._cache_key, tuple)

    def test_numeric_types_signed_zero_presence_and_rejections(self):
        pairs = (({"base_speed": 3}, {"base_speed": 3.0}),
                 ({"base_damage_resistance": -0.0}, {"base_damage_resistance": 0.0}),
                 ({}, {"base_damage_resistance": 0}))
        for left, right in pairs:
            with self.subTest(left=left, right=right):
                first, second = ProfileValues.from_record(left), ProfileValues.from_record(right)
                self.assertIsNot(first, second)
                self.assertEqual(json.dumps(first.to_record(), sort_keys=True),
                                 json.dumps(left, sort_keys=True))
                self.assertEqual(json.dumps(second.to_record(), sort_keys=True),
                                 json.dumps(right, sort_keys=True))
        for record in ({"base_speed": None}, {"base_speed": True},
                       {"base_speed": float("nan")}, {"base_speed": float("inf")},
                       {"new_field": 1}):
            with self.subTest(record=record), self.assertRaises(CodecError):
                ProfileValues.from_record(record)

    def test_agent_field_presence_and_other_state_remain_separate(self):
        record = make_agent("h")
        first = Agent.from_record(record, "run")
        second = Agent.from_record({**record, "id": "other"}, "run")
        self.assertIs(first.current_state.type_profile, second.current_state.individual_profile)
        self.assertIs(first.current_state.individual_profile, first.current_state.projection.profile)
        without_profile = {key: value for key, value in record.items() if key != "profile"}
        third = Agent.from_record(without_profile, "run")
        self.assertNotIn("profile", third.to_record())
        self.assertIn("profile", first.to_record())
        self.assertIsNot(first.current_state, second.current_state)

    def test_effective_profile_caches_preserve_signed_zero_in_both_orders(self):
        from zombie_sim.domain import profile, _typed_profile_values
        from zombie_sim.domain_model.profiles import ProfileResolver, _resolve_sources

        for order in ((-0.0, 0.0), (0.0, -0.0)):
            for boundary in ("typed", "compatibility"):
                with self.subTest(order=order, boundary=boundary):
                    _resolve_sources.cache_clear()
                    _typed_profile_values.cache_clear()
                    for value in order:
                        if boundary == "typed":
                            actual = ProfileResolver.resolve("Human", 100, individual_profile=
                                ProfileValues.from_record({"base_damage_resistance": value})).to_record()
                        else:
                            actual = profile(make_agent("h", "Human", profile={"base_damage_resistance": value}))
                        self.assertEqual(json.dumps(actual["base_damage_resistance"]), json.dumps(value))

    def test_custom_scalar_and_profile_subtypes_bypass_cache(self):
        value = MutableFloat(2)
        value.tags = []
        first = ProfileValues.from_record({"base_speed": value})
        second = ProfileValues.from_record({"base_speed": value})
        self.assertIsNot(first, second)
        self.assertIs(first.base_speed, value)
        first = ExtendedProfile.from_record({"base_speed": 2})
        second = ExtendedProfile.from_record({"base_speed": 2})
        self.assertIs(type(first), ExtendedProfile)
        self.assertIsNot(first, second)

    def test_bounded_cache_eviction_preserves_historical_values(self):
        _intern_profile_values.cache_clear()
        previous = ProfileValues.from_record({"base_speed": 1})
        for value in range(2, 2052):
            ProfileValues.from_record({"base_speed": value})
        info = _intern_profile_values.cache_info()
        self.assertEqual(info.maxsize, 2048)
        self.assertEqual(info.currsize, 2048)
        self.assertEqual(previous.to_record(), {"base_speed": 1})
        self.assertIsNot(ProfileValues.from_record({"base_speed": 1}), previous)


if __name__ == "__main__":
    unittest.main()
