"""Committed identity, isolated overlays and pre-storage consistency contracts."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from zombie_sim.domain import make_agent
from zombie_sim import faults
from zombie_sim.domain_model import DomainCodec
from zombie_sim.game_rules import TransitionPlan
from zombie_sim.persistence import PersistenceBundleFactory
from zombie_sim.state_management import StateCoordinator, WorldAggregate, WorldDraft, StateChange
from zombie_sim.state_management.validation import InvalidTransition


def initial_world():
    return WorldAggregate.from_record({
        'run_id': 'parent', 'revision': 0, 'time': '0',
        'lineage': {'name': 'original'},
        'agents': {key: make_agent(key, 'Human', x=index * 3 + 10, y=10)
                   for index, key in enumerate(('a', 'b', 'c'))},
        'stockpiles': {'stock': {'id': 'stock', 'x': 20, 'y': 20,
                                'inventory': {'FOOD': 3}, 'reserved': {'FOOD': 0}}},
    })


def plan(changes=(), metadata=None):
    return TransitionPlan(0, '1/3', tuple(changes), (), None, metadata=metadata or {})


class StateIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix='typed-state-contract-')
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(faults.clear)

    def test_branch_rebinds_current_agent_identity_without_changing_parent(self):
        parent = initial_world()
        child = parent.with_changes((), time='1/3', revision=1, metadata={'run_id': 'child'})
        self.assertEqual(parent.agent('a').identity.run_id, 'parent')
        self.assertEqual(child.agent('a').identity.run_id, 'child')
        self.assertIs(parent.agent('a').current_state, child.agent('a').current_state)

    def test_unmarked_nested_edit_becomes_typed_change_and_parent_stays_immutable(self):
        parent = initial_world()
        draft = WorldDraft(parent.read_view())
        draft['agents']['a']['inventory']['FOOD'] = 2
        self.assertEqual(draft.changed_keys(), {('agents', 'a')})
        changes = draft.changes()
        child = parent.with_changes(changes, time='1/3', revision=1)
        self.assertEqual(child.agent('a').to_record()['inventory']['FOOD'], 2)
        self.assertEqual(parent.agent('a').to_record()['inventory']['FOOD'], 0)

    def test_new_local_record_remains_live_until_plan_is_frozen(self):
        draft = WorldDraft(initial_world().read_view())
        record = {'id': 'new', 'x': 25, 'y': 25, 'inventory': {'FOOD': 1}}
        draft['stockpiles']['new'] = record
        record['inventory']['FOOD'] = 2
        replacement = next(change for change in draft.changes() if change.identity == 'new')
        record['inventory']['FOOD'] = 3
        self.assertEqual(replacement.value.to_record()['inventory']['FOOD'], 2)

    def test_delete_and_reinsert_preserves_the_new_iteration_order(self):
        parent = initial_world()
        draft = WorldDraft(parent.read_view())
        record = draft['agents']['a']
        del draft['agents']['a']
        draft['agents']['a'] = record
        self.assertEqual(list(draft['agents']), ['b', 'c', 'a'])
        child = parent.with_changes(draft.changes(), time='1/3', revision=1)
        self.assertEqual(list(child.collections['agents']), ['b', 'c', 'a'])
        self.assertEqual(list(parent.collections['agents']), ['a', 'b', 'c'])

    def test_whole_collection_replacement_preserves_requested_order(self):
        parent = initial_world()
        draft = WorldDraft(parent.read_view())
        draft['agents'] = {key: parent.agent(key).to_record() for key in ('c', 'a', 'b')}
        child = parent.with_changes(draft.changes(), time='1/3', revision=1)
        self.assertEqual(list(child.collections['agents']), ['c', 'a', 'b'])

    def test_fork_shares_immutable_base_and_isolates_only_materialized_overlays(self):
        draft = WorldDraft(initial_world().read_view())
        draft['agents']['a']['inventory']['FOOD'] = 2
        fork = draft.fork()
        self.assertIs(fork.base, draft.base)
        self.assertEqual(set(fork.tables['agents'].drafts), {'a'})
        fork['agents']['a']['inventory']['FOOD'] = 1
        fork['lineage']['name'] = 'fork'
        self.assertEqual(draft['agents']['a']['inventory']['FOOD'], 2)
        self.assertEqual(draft['lineage']['name'], 'original')
        self.assertEqual(fork.metadata_changes(), {'lineage': {'name': 'fork'}})
        self.assertEqual(draft.metadata_changes(), {})

    def assert_invalid_before_storage(self, world, changes, expected):
        atomic = Mock()
        coordinator = StateCoordinator(world, SimpleNamespace(atomic=atomic))
        with self.assertRaisesRegex(InvalidTransition, expected):
            coordinator.begin(plan(changes))
        atomic.commit.assert_not_called()
        self.assertIs(coordinator.current_world, world)

    def test_dangling_active_action_is_rejected_before_persistence(self):
        world = initial_world()
        record = world.agent('a').to_record()
        record['active_action'] = 'missing'
        agent = DomainCodec().decode_entity('agents', record, world.run_id)
        self.assert_invalid_before_storage(world, [StateChange('agents', 'a', agent)], 'Missing occurrences')

    def test_entity_key_mismatch_is_rejected_before_persistence(self):
        world = initial_world()
        self.assert_invalid_before_storage(world, [StateChange('agents', 'a', world.agent('b'))], 'identity disagree')

    def test_reserved_stock_without_owning_reservation_is_rejected_before_persistence(self):
        world = initial_world()
        record = world.collections['stockpiles']['stock'].to_record()
        record['reserved']['FOOD'] = 1
        stock = DomainCodec().decode_entity('stockpiles', record, world.run_id)
        self.assert_invalid_before_storage(world, [StateChange('stockpiles', 'stock', stock)], 'owned reservations')

    def test_changed_reservation_indexes_only_its_affected_holders(self):
        world = initial_world()
        codec = DomainCodec()
        reservation = codec.decode_entity('reservations', {'id': 'r', 'occurrence_id': 'action',
            'actor': 'a', 'collection': 'stockpiles', 'holder': 'stock', 'kind': 'inventory',
            'resource': 'FOOD', 'quantity': 1}, world.run_id)
        changed = world.with_changes([StateChange('reservations', 'r', reservation)], time='1/3', revision=1)
        self.assertEqual(changed.reservations_by_holder[('stockpiles', 'stock')], ('r',))
        self.assertEqual(len(world.reservations_by_holder), 0)
        removed = changed.with_changes([StateChange('reservations', 'r', None)], time='2/3', revision=2)
        self.assertEqual(len(removed.reservations_by_holder), 0)
        self.assert_invalid_before_storage(world, [StateChange('reservations', 'r', reservation)], 'Missing occurrences')

    def persistence_case(self, backend):
        world = initial_world()
        bundle = PersistenceBundleFactory().create(world.to_record(), Path(self.temporary.name) / (backend+'.sqlite'), backend)
        self.addCleanup(bundle.close)
        bundle.history.initialize_runtime({'queue': {}, 'memories': {}}, revision=0)
        draft = WorldDraft(world.read_view())
        draft['agents']['a']['life'] -= 1
        return world, bundle, StateCoordinator(world, bundle), plan(draft.changes())

    def test_before_commit_fault_keeps_typed_world_runtime_and_receipt_unpublished(self):
        for backend in ('memory', 'sqlite'):
            with self.subTest(backend=backend):
                world, bundle, coordinator, proposed = self.persistence_case(backend)
                faults.arm('before_history_commit', error='ENOSPC')
                with self.assertRaises(OSError):
                    coordinator.begin(proposed).commit([['set', ['memories', 'a'], {'count': 1}]],
                        {'command_id': 'advance', 'status': 'applied'})
                self.assertIs(coordinator.current_world, world)
                self.assertEqual(bundle.history.state_at(), world.to_record())
                self.assertEqual(bundle.history.runtime_at(), {'queue': {}, 'memories': {}})
                self.assertIsNone(bundle.history.command_result('advance'))
                self.assertEqual(bundle.history.revision, 0)

    def test_after_commit_fault_reconciles_receipt_before_typed_world_publication(self):
        for backend in ('memory', 'sqlite'):
            with self.subTest(backend=backend):
                world, bundle, coordinator, proposed = self.persistence_case(backend)
                faults.arm('after_history_commit_before_publish', error='EIO')
                result = coordinator.begin(proposed).commit([['set', ['memories', 'a'], {'count': 1}]],
                    {'command_id': 'advance', 'status': 'applied'})
                self.assertEqual(result.revision, 1)
                self.assertEqual(coordinator.current_world.to_record(), bundle.history.state_at())
                self.assertEqual(bundle.store.read_view(), bundle.history.state_at())
                self.assertEqual(bundle.history.runtime_at()['memories'], {'a': {'count': 1}})
                self.assertEqual(result.command_result['command_id'], 'advance')
                self.assertEqual(bundle.atomic.resolve_transaction(result.transaction_id), result)
                self.assertEqual(world.revision, 0)

    def test_receipt_read_failure_reconciles_without_repeating_the_durable_commit(self):
        for backend in ('memory', 'sqlite'):
            with self.subTest(backend=backend):
                world, bundle, coordinator, proposed = self.persistence_case(backend)
                lookup = bundle.history.transaction_result
                reads = []
                def unavailable_once(transaction_id):
                    reads.append(transaction_id)
                    if len(reads) == 1:
                        raise OSError('receipt read interrupted after durable commit')
                    return lookup(transaction_id)
                with patch.object(bundle.history, 'transaction_result', unavailable_once):
                    result = coordinator.begin(proposed).commit(None, {'command_id': 'advance', 'status': 'applied'})
                self.assertEqual(len(reads), 2)
                self.assertEqual(result.revision, 1)
                self.assertEqual(bundle.history.revision, 1)
                self.assertEqual(coordinator.current_world.to_record(), bundle.history.state_at())


if __name__ == '__main__':
    unittest.main()
