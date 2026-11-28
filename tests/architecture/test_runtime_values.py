"""Live private-memory ownership, including non-JSON Python value graphs."""
from collections import defaultdict, namedtuple
from copy import deepcopy
from fractions import Fraction
from pathlib import PosixPath, PureWindowsPath
from types import MappingProxyType
import unittest

from zombie_sim.engine import Simulation
from zombie_sim.domain_model import ScheduledTask
from zombie_sim import policies
from zombie_sim.runtime import _encode
from zombie_sim.state_management import RuntimeState, RuntimeSnapshot
from zombie_sim.state_management.runtime_values import CowDict


PrivatePair = namedtuple('PrivatePair', 'history opaque')


class OpaqueMarker:
    pass


class TaggedInt(int):
    pass


class TaggedString(str):
    pass


class TaggedTask(ScheduledTask):
    pass


class TaggedFraction(Fraction):
    # Fraction's inherited copy protocol intentionally omits subclass state;
    # this live-memory subtype supplies the same deepcopy contract as legacy.
    def __deepcopy__(self, memo):
        result = type(self)(self.numerator, self.denominator); memo[id(self)] = result
        result.__dict__.update(deepcopy(self.__dict__, memo))
        return result


class TaggedPath(PosixPath):
    def __deepcopy__(self, memo):
        result = type(self)(str(self)); memo[id(self)] = result
        result.__dict__.update(deepcopy(self.__dict__, memo))
        return result


class MutableKey:
    def __init__(self, value): self.value = value; self.tags = []
    def __hash__(self): return hash(self.value)
    def __eq__(self, other): return isinstance(other, MutableKey) and self.value == other.value


class CountedPrivateMemory:
    copies = []
    def __init__(self, identifier): self.identifier = identifier; self.values = []
    def __deepcopy__(self, memo):
        type(self).copies.append(self.identifier)
        result = type(self)(self.identifier); memo[id(self)] = result
        result.values = deepcopy(self.values, memo)
        return result


class LegacyRichMemoryModel:
    """Plain legacy policy, deliberately without an exact restart codec."""
    model_id = 'architecture/legacy-rich-memory'
    version = '1.0.0'
    applicable_types = ('Human', 'Zombie')

    def __init__(self, parameters=None): self.parameters = parameters or {'kind': 'pair'}

    def manifest(self):
        return {'model_id': self.model_id, 'model_version': self.version,
                'applicable_types': list(self.applicable_types), 'parameters': self.parameters,
                'restartable': False, 'deterministic': True, 'dependencies': []}

    def decide(self, observation, memory, rng):
        kind = self.parameters['kind']
        if not memory:
            memory = PrivatePair([], OpaqueMarker()) if kind == 'pair' else defaultdict(list, opaque=OpaqueMarker())
        if kind == 'pair':
            assert type(memory) is PrivatePair
            memory.history.append(observation['time'])
            count = len(memory.history)
        else:
            assert type(memory) is defaultdict and memory.default_factory is list
            memory['history'].append(observation['time'])
            count = len(memory['history'])
        return {'action': 'wait', 'parameters': {'duration': 1}}, memory, {'calls': count}


class RuntimeValueGraphTests(unittest.TestCase):
    def snapshot(self, value):
        return RuntimeSnapshot.from_attributes({'memories': {'h': value}})

    def test_case_preserving_paths_survive_values_and_reinserted_memory_keys(self):
        original = PureWindowsPath('C:/Original')
        replacement = PureWindowsPath('C:/ORIGINAL')
        before = self.snapshot({'path': original})
        branch = before.fork()
        branch.memories['h']['path'] = replacement
        after = branch.snapshot()
        self.assertEqual(str(after.to_attributes()['memories']['h']['path']), str(replacement))
        self.assertEqual(str(before.to_attributes()['memories']['h']['path']), str(original))
        self.assertEqual(str(after.fork().memories['h']['path']), str(replacement))
        for old_key, new_key in ((original, replacement), ((original,), (replacement,)),
                                 (frozenset((original,)), frozenset((replacement,)))):
            with self.subTest(key=old_key):
                branch = self.snapshot({old_key: 'value'}).fork()
                del branch.memories['h'][old_key]
                branch.memories['h'][new_key] = 'value'
                retained = next(iter(branch.snapshot().to_attributes()['memories']['h']))
                path = retained if isinstance(retained, PureWindowsPath) else next(iter(retained))
                self.assertEqual(str(path), str(replacement))

    def test_custom_container_and_scalar_types_keep_mutable_attributes_isolated(self):
        values = [TaggedInt(7), TaggedString('seven'), TaggedFraction(1, 3), TaggedPath('/tmp/seven'),
                  TaggedTask.from_record(['1/3', 2, 0.5, 1, {'kind': 'decision', 'agent': 'h'}])]
        for value in values: value.tags = ['original']
        values += [PrivatePair([1], OpaqueMarker()), defaultdict(list, seen=[1])]
        for value in values:
            with self.subTest(kind=type(value).__name__):
                snapshot = self.snapshot(value)
                branch = snapshot.fork(); actual = branch.memories['h']
                self.assertIs(type(actual), type(value))
                if hasattr(actual, 'tags'):
                    actual.tags.append('changed')
                    self.assertEqual(value.tags, ['original'])
                    self.assertEqual(snapshot.to_attributes()['memories']['h'].tags, ['original'])
                elif isinstance(actual, PrivatePair):
                    actual.history.append(2)
                    self.assertEqual(snapshot.to_attributes()['memories']['h'].history, [1])
                else:
                    actual['new'].append(2)
                    self.assertIs(actual.default_factory, list)
                    self.assertNotIn('new', snapshot.to_attributes()['memories']['h'])

    def test_aliased_and_cyclic_graphs_survive_each_memory_boundary(self):
        shared = [1]
        source = {'a': shared, 'b': shared}
        snapshot = self.snapshot(source); branch = snapshot.fork().memories['h']
        self.assertIs(branch['a'], branch['b'])
        branch['a'].append(2)
        old = snapshot.to_attributes()['memories']['h']
        self.assertIs(old['a'], old['b']); self.assertEqual(old['a'], [1]); self.assertEqual(shared, [1])
        # Ownership supports deepcopy graphs. This does not claim that the
        # legacy journal has a cycle-preserving restart codec.
        cycle = []; cycle.append(cycle)
        snapshot = self.snapshot(cycle); branch = snapshot.fork().memories['h']
        self.assertIs(branch[0], branch)
        branch.append(9)
        old = snapshot.to_attributes()['memories']['h']
        self.assertIs(old[0], old); self.assertEqual(len(old), 1)

    def test_unsafe_keys_do_not_expose_snapshot_owned_objects(self):
        key = MutableKey('key')
        snapshot = self.snapshot({key: [1]})
        branch = snapshot.fork().memories['h']; branch_key = next(iter(branch))
        branch_key.tags.append('changed')
        self.assertEqual(next(iter(snapshot.to_attributes()['memories']['h'])).tags, [])
        self.assertEqual(key.tags, [])
        state = self.snapshot({}).fork()
        external = MutableKey('new'); state.memories['h'][external] = [2]
        published = state.snapshot(); external.tags.append('outside')
        self.assertEqual(next(iter(published.to_attributes()['memories']['h'])).tags, [])

    def test_aliases_created_inside_writable_branch_remain_graphs(self):
        state = self.snapshot({}).fork(); memory = state.memories['h']; shared = []
        memory['a'] = shared; memory['b'] = shared
        shared.append(1); snapshot = state.snapshot(); shared.append(2)
        captured = snapshot.to_attributes()['memories']['h']
        self.assertIs(captured['a'], captured['b']); self.assertEqual(captured['a'], [1])
        state = self.snapshot({'items': []}).fork(); items = state.memories['h']['items']; items.append(items)
        captured = state.snapshot().to_attributes()['memories']['h']['items']
        self.assertIs(captured[0], captured)

    def test_delete_reinsert_and_clear_match_dictionary_order(self):
        for initial in ({'a': 1, 'b': 2, 'c': 3}, {}):
            state = self.snapshot(initial).fork(); actual = state.memories['h']; expected = dict(initial)
            for mapping in (actual, expected):
                mapping['a'] = mapping.get('a', 0) + 1
                mapping.pop('a'); mapping['a'] = 9
            self.assertEqual(list(actual), list(expected))
            self.assertEqual(list(reversed(actual)), list(reversed(expected)))
            self.assertEqual(list(state.snapshot().to_attributes()['memories']['h']), list(expected))
            for mapping in (actual, expected): mapping.clear(); mapping.update(c=3, b=2, a=1)
            self.assertEqual(list(actual), list(expected))
            self.assertEqual(list(state.snapshot().to_attributes()['memories']['h']), list(expected))
            self.assertEqual(actual.popitem(), expected.popitem())

    def test_only_accessed_opaque_agent_memory_is_copied(self):
        state = RuntimeState.from_attributes({'memories': {str(i): CountedPrivateMemory(i) for i in range(1000)}})
        snapshot = state.snapshot(); CountedPrivateMemory.copies = []
        branch = snapshot.fork(); branch.memories['7'].values.append('private')
        self.assertEqual(CountedPrivateMemory.copies, [7])
        branch.snapshot()
        self.assertEqual(set(CountedPrivateMemory.copies), {7})

    def test_exact_builtin_tree_tokens_and_mapping_owner_inputs(self):
        state = RuntimeState.from_attributes({'config': MappingProxyType({'profiles': {'Human': {'base_speed': 2}}}),
            'memories': defaultdict(dict, h={'list': [(1, 2)], 'tuple': (1, 2), 'set': {1, 2}})})
        before = state.memory_tokens()
        for _ in range(4):
            _encode(state.memories['h']); state = state.snapshot().fork()
            self.assertIs(state.memory_tokens()['h'], before['h'])
        self.assertIsInstance(state.memories, CowDict)
        self.assertEqual(state.config.to_dict()['profiles']['Human']['base_speed'], 2)

    def test_delete_reinsert_preserves_equal_but_differently_typed_keys(self):
        for before, after in ((1, 1.0), ((1,), (1.0,)), (frozenset((1,)), frozenset((1.0,)))):
            with self.subTest(key=before):
                state = self.snapshot({before: 'value'}).fork(); memory = state.memories['h']
                del memory[before]; memory[after] = 'value'
                captured = next(iter(state.snapshot().to_attributes()['memories']['h']))
                if type(after) in (tuple, frozenset):
                    self.assertIs(type(next(iter(captured))), float)
                else:
                    self.assertIs(type(captured), float)

    def test_signed_zero_memories_preserve_forks_journals_and_restore(self):
        import json
        import tempfile
        from pathlib import Path

        for before, after in ((0.0, -0.0), (-0.0, 0.0)):
            with self.subTest(before=before), tempfile.TemporaryDirectory() as directory:
                config = {"agents": [{"id": "h", "type": "Human", "x": 10, "y": 10}],
                          "decision_mode": "scripted"}
                with Simulation(config, workers=1, history_path=Path(directory)/"history.sqlite") as sim:
                    sim.memories["h"] = {"value": before, "nested": [{"value": before}]}
                    sim.advance_until("1/3", return_snapshot=False)
                    previous = sim._runtime_state.snapshot()
                    sim.memories["h"]["value"] = after
                    sim.memories["h"]["nested"][0]["value"] = after
                    sim.advance_until("2/3", return_snapshot=False)
                    for memory in (sim._runtime_state.snapshot().fork().memories["h"],
                                   sim.serialize()["attributes"]["memories"]["h"],
                                   sim.history.runtime_at()["memories"]["h"]):
                        self.assertEqual(json.dumps(memory["value"]), json.dumps(after))
                        self.assertEqual(json.dumps(memory["nested"][0]["value"]), json.dumps(after))
                    self.assertEqual(json.dumps(previous.fork().memories["h"]["value"]), json.dumps(before))
                    with Simulation.restore_revision(sim.history_path,
                            output_history_path=Path(directory)/"restored.sqlite", workers=1) as restored:
                        self.assertEqual(json.dumps(restored.memories["h"]["value"]), json.dumps(after))

    def test_signed_zero_reinserted_keys_and_nonfinite_cell_equality(self):
        import json
        from zombie_sim.state_management.runtime_values import same_cell

        for wrap in (lambda value: value, lambda value: (value,), lambda value: frozenset((value,))):
            for before, after in ((0.0, -0.0), (-0.0, 0.0)):
                with self.subTest(key_type=type(wrap(before)), before=before):
                    state = self.snapshot({wrap(before): "value"}).fork()
                    memory = state.memories["h"]
                    # Ordinary equal-key assignment preserves the original key.
                    memory[wrap(after)] = "value"
                    original = next(iter(state.snapshot().to_attributes()["memories"]["h"]))
                    if type(original) is not float:
                        original = next(iter(original))
                    self.assertEqual(json.dumps(original), json.dumps(before))
                    del memory[wrap(before)]
                    memory[wrap(after)] = "value"
                    captured = next(iter(state.snapshot().to_attributes()["memories"]["h"]))
                    if type(captured) is not float:
                        captured = next(iter(captured))
                    self.assertEqual(json.dumps(captured), json.dumps(after))
        self.assertFalse(same_cell(float("nan"), float("nan")))
        value = float("nan")
        self.assertTrue(same_cell(value, value))

    def test_real_legacy_policy_preserves_nonrestartable_live_memory(self):
        previous = policies._REGISTRY.get(LegacyRichMemoryModel.model_id)
        policies.register_model(LegacyRichMemoryModel.model_id, LegacyRichMemoryModel, replace=True)
        self.addCleanup(lambda: policies._REGISTRY.pop(LegacyRichMemoryModel.model_id, None) if previous is None else
                        policies._REGISTRY.__setitem__(LegacyRichMemoryModel.model_id, previous))
        for kind in ('pair', 'defaultdict'):
            with self.subTest(kind=kind), Simulation({'agents': [{'id': 'h', 'type': 'Human', 'x': 10, 'y': 10,
                    'model_assignment': {'model_id': LegacyRichMemoryModel.model_id, 'parameters': {'kind': kind}}}],
                    'horizon': 4}, workers=1) as sim:
                sim.advance_until('1/3'); before = sim._runtime_state.snapshot()
                sim.advance_until(3)
                memory = sim.memories['h']; historical = before.to_attributes()['memories']['h']
                history = memory.history if kind == 'pair' else memory['history']
                prior = historical.history if kind == 'pair' else historical['history']
                self.assertEqual(len(prior), 1); self.assertGreaterEqual(len(history), 4)
                self.assertTrue(all('fallback_reason' not in event.get('diagnostics', {}) for event in sim.decisions))
                self.assertEqual(sim.serialize()['restart_capability'], 'STATE_REPLAY_ONLY')


if __name__ == '__main__':
    unittest.main()
