"""Exercise typed wire records from all actual action-success fixtures."""
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tests.spec.actions import cases
from zombie_sim.domain_model import DomainCodec, DomainEvent, ScheduledTask, CodecError
from zombie_sim.registry import ACTIONS
from zombie_sim.testing import FrameworkTestAdapter


class EventCodecTests(unittest.TestCase):
    def test_OOP_EVENT_CODEC_all_29_real_action_records_are_lossless(self):
        selected = [case for case in cases() if case["id"] in {f"ACT_{name}_success" for name in ACTIONS}]
        self.assertEqual({case["id"] for case in selected}, {f"ACT_{name}_success" for name in ACTIONS})
        codec = DomainCodec()
        with TemporaryDirectory(prefix="deep-oop-all-actions-") as directory:
            for index, case in enumerate(selected):
                with self.subTest(action=case["id"]):
                    adapter = FrameworkTestAdapter(workdir=Path(directory) / str(index))
                    try:
                        adapter.execute(deepcopy(case["request"]))
                        sim = adapter.simulations[-1]
                        for event in sim.events:
                            self.assertEqual(DomainEvent.from_record(event).to_record(), event)
                        for collection in ("agents", "barriers", "shelters", "stockpiles", "remains", "episodes",
                                           "signals", "reservations", "interventions", "intents", "occurrences"):
                            for record in sim.state.get(collection, {}).values():
                                self.assertEqual(codec.decode_entity(collection, record, sim.state["run_id"]).to_record(), record)
                        for row in sim.queue:
                            task = ScheduledTask.from_record(row)
                            encoded = task.to_record()
                            self.assertEqual(Fraction(str(encoded[0])), row[0])
                            self.assertEqual(encoded[1:], list(row[1:]))
                            self.assertEqual(task.order_key, row[:4])
                    finally:
                        adapter.close()

    def test_OOP_EVENT_CODEC_unknown_kind_and_unreviewed_version_fail(self):
        with self.assertRaises(CodecError):
            DomainEvent.from_record({"id": "unknown", "time": "1/3", "revision": 1, "kind": "invented_rule"})
        with self.assertRaises(CodecError):
            DomainEvent.from_record({"id": "clock", "time": "1/3", "revision": 1,
                                     "kind": "clock_advanced", "payload_version": "999"})
        with self.assertRaises(CodecError):
            ScheduledTask.from_record(["1/3", 2, 0.25, 1, {"kind": "invented_scheduler_effect", "agent": "h"}])

    def test_OOP_EVENT_CODEC_exact_order_and_nested_input_detachment(self):
        row = ["9007199254740993/3", 2, 0.25, 7,
               {"kind": "starvation", "agent": "h", "generation": 3}]
        before = deepcopy(row)
        task = ScheduledTask.from_record(row)
        row[4]["generation"] = 4
        self.assertEqual(task.to_record(), before)
        self.assertEqual(task.order_key, (Fraction(9007199254740993, 3), 2, 0.25, 7))
        encoded = task.to_record()
        encoded[4]["generation"] = 5
        self.assertEqual(task.to_record(), before)

    def test_OOP_EVENT_CODEC_invalid_scheduler_order_fields_are_rejected(self):
        valid = ["1/3", 2, 0.25, 7, {"kind": "starvation", "agent": "h", "generation": 3}]
        for index, bad in ((1, -1), (1, True), (2, float("nan")), (3, -1), (3, True)):
            with self.subTest(index=index, bad=bad):
                value = deepcopy(valid)
                value[index] = bad
                with self.assertRaises(CodecError):
                    ScheduledTask.from_record(value)


if __name__ == "__main__":
    unittest.main()
