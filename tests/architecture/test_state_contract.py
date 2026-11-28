"""Typed state ownership contracts independent of the Simulation facade."""
from copy import deepcopy
import json
import unittest

from zombie_sim.domain import make_agent
from zombie_sim.domain_model import HumanState
from zombie_sim.state_management import WorldAggregate, RuntimeSnapshot


class StateOwnershipTests(unittest.TestCase):
    def test_OOP_CONTINUATION_encoding_untouched_memory_preserves_cell_tokens(self):
        from zombie_sim.runtime import _encode, _decode
        from zombie_sim.state_management.runtime_state import RuntimeState
        source = {"tuple": (1, True, 1.0), "nested": [(1, 2), (False, 3.0)],
                  "set": {"one", "two"}, "list": [1, True, 1.0]}
        runtime = RuntimeState.from_attributes({"time": "0", "memories": source})
        tokens = runtime.memory_tokens()
        encoded = {key: _encode(value) for key, value in runtime.memories.items()}
        fork = runtime.snapshot().fork()
        fork_encoded = {key: _encode(value) for key, value in fork.memories.items()}
        after = fork.memory_tokens()
        self.assertEqual(encoded, fork_encoded)
        for key in source:
            self.assertIs(after[key], tokens[key],
                          "Reading or encoding unchanged model memory must not mark its cell changed")
            decoded = _decode(fork_encoded[key])
            self.assertEqual(type(decoded), type(source[key]))
            self.assertEqual(decoded, source[key])
        for key in ("tuple", "list"):
            self.assertEqual([type(value) for value in _decode(fork_encoded[key])], [int, bool, float])

    def test_OOP_CONTINUATION_cow_config_serializes_all_nested_values(self):
        from zombie_sim.config_io import ConfigurationCodec
        from zombie_sim.storage import canonical
        source = {"profiles": {"Human": {"base_speed": 2}},
                  "agents": [{"id": "h", "type": "Human", "inventory": {"FOOD": 2}}], "seed": 3917}
        runtime = RuntimeSnapshot.from_attributes({"time": "0", "config": source}).fork()
        self.assertEqual(json.loads(canonical(runtime.config)), source)
        self.assertEqual(json.loads(ConfigurationCodec().dumps(runtime.config)), source)
        with self.assertRaises(TypeError):
            json.dumps(runtime.config)
        runtime.config["agents"][0]["inventory"]["FOOD"] = 3
        changed = deepcopy(source)
        changed["agents"][0]["inventory"]["FOOD"] = 3
        self.assertEqual(json.loads(canonical(runtime.config)), changed)
        self.assertEqual(json.loads(ConfigurationCodec().dumps(runtime.config)), changed)

    def test_OOP_STATE_OWNERSHIP_unread_private_memory_is_not_recopied_per_fork(self):
        class CountedMemory:
            copies = 0

            def __deepcopy__(self, memo):
                type(self).copies += 1
                value = type(self)()
                memo[id(self)] = value
                return value

        snapshot = RuntimeSnapshot.from_attributes({"time": "0", "memories": {"h": CountedMemory()}, "queue": []})
        copies_after_detachment = CountedMemory.copies
        # The initial input may be detached once. Merely creating independent
        # planning boundaries must not repeatedly copy untouched private cells.
        workspaces = [snapshot.fork() for _ in range(8)]
        self.assertEqual(len(workspaces), 8)
        self.assertEqual(CountedMemory.copies, copies_after_detachment,
                         "Fork cost must not copy every agent's unread model memory")

    def test_OOP_STATE_OWNERSHIP_world_decoding_detaches_input(self):
        source = {"run_id": "contract-run", "time": "0", "revision": 0,
                  "agents": {"h": make_agent("h", "Human", x=10, y=10, life=87)}}
        world = WorldAggregate.from_record(source)
        self.assertIsInstance(world.agent("h").current_state, HumanState)
        source["agents"]["h"]["life"] = 0
        source["agents"]["h"]["inventory"]["FOOD"] = 12345
        self.assertEqual(world.agent("h").to_record()["life"], 87)
        self.assertEqual(world.agent("h").to_record()["inventory"]["FOOD"], 0)

    def test_OOP_STATE_OWNERSHIP_read_view_never_returns_live_mutable_records(self):
        world = WorldAggregate.from_record({"run_id": "contract-run", "time": "0", "revision": 0,
                  "agents": {"h": make_agent("h", "Human", x=10, y=10, life=87)}})
        view = world.read_view()
        original = deepcopy(world.to_record())
        record = view["agents"]["h"]
        record["life"] = 0
        record["inventory"]["FOOD"] = 10000
        self.assertEqual(world.to_record(), original)
        self.assertEqual(view["agents"]["h"]["life"], 87)
        with self.assertRaises(TypeError):
            view["agents"]["h"] = record

    def test_OOP_CONTINUATION_unknown_durable_runtime_field_is_not_discarded(self):
        with self.assertRaisesRegex(ValueError, "unreviewed_extension|Unknown durable"):
            RuntimeSnapshot.from_attributes({"time": "1/3", "unreviewed_extension": {"state": 9}})

    def test_OOP_RULE_BOUNDARY_runtime_fork_cannot_change_snapshot(self):
        incoming = {"time": "1/3", "config": {"profiles": {"Human": {"base_speed": 2}}},
                    "memories": {"h": {"private": [1, 2]}}, "queue": []}
        snapshot = RuntimeSnapshot.from_attributes(incoming)
        saved = snapshot.to_attributes()
        incoming["config"]["profiles"]["Human"]["base_speed"] = 100
        incoming["memories"]["h"]["private"].append(3)
        self.assertEqual(snapshot.to_attributes(), saved)
        workspace = snapshot.fork()
        workspace.config["profiles"]["Human"]["base_speed"] = 200
        workspace.memories["h"]["private"].append(4)
        workspace.queue.append({"unexpected": True})
        self.assertEqual(snapshot.to_attributes(), saved,
                         "A transaction-local fork must not mutate another task's committed config or private memory")
        exposed = snapshot.to_attributes()
        exposed["memories"]["h"]["private"].append(5)
        self.assertEqual(snapshot.to_attributes(), saved)


if __name__ == "__main__":
    unittest.main()
