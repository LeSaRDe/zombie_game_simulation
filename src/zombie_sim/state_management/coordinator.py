"""Commit ownership: validated typed plans become visible after durability."""
from __future__ import annotations
from dataclasses import dataclass
from ..persistence.contracts import CommitBundle, CommitOutcomeUnknown
from .world import WorldAggregate
from .validation import validate_transition


class StalePlan(ValueError):
    pass


class StateCoordinator:
    def __init__(self, world: WorldAggregate, persistence):
        self._world = world
        self.persistence = persistence

    @property
    def current_world(self):
        return self._world

    def view(self):
        return self._world.read_view()

    def begin(self, plan):
        return UnitOfWork(self, plan)


class UnitOfWork:
    def __init__(self, coordinator, plan):
        self.coordinator = coordinator
        self.plan = plan
        if plan.expected_revision != coordinator.current_world.revision:
            raise StalePlan('Transition plan read an obsolete committed revision')
        self.next_world = coordinator.current_world.with_changes(
            plan.changes, time=plan.time, revision=plan.expected_revision + 1,
            metadata=plan.metadata)
        validate_transition(coordinator.current_world,self.next_world,plan.changes)

    def commit(self, runtime_delta, command_result=None):
        plan = self.plan
        if self.coordinator.current_world.revision != plan.expected_revision:
            raise StalePlan('Committed world changed while the transaction was staged')
        patch = [['set', ['time'], str(plan.time)], ['set', ['revision'], plan.expected_revision + 1]]
        for key, value in plan.metadata.items():
            patch.append(['set', [key], value])
        for change in plan.changes:
            if change.reinserted:patch.append(['remove',[change.collection,change.identity]])
            patch.append(['remove', [change.collection, change.identity]] if change.value is None else
                         ['set', [change.collection, change.identity], change.value.to_record()])
        records = tuple(event.to_record() for event in plan.events)
        bundle = CommitBundle(patch, runtime_delta, records, command_result)
        transaction_id = f'{self.next_world.run_id}:revision:{plan.expected_revision + 1}'
        try:
            result = self.coordinator.persistence.atomic.commit(bundle, plan.expected_revision, transaction_id)
        except CommitOutcomeUnknown:
            result = self.coordinator.persistence.atomic.resolve_transaction(transaction_id)
            if result is None:
                raise
        # The durable result is authoritative. No speculative typed world was
        # ever returned by StateCoordinator.view() before this assignment.
        self.coordinator._world = self.next_world
        return result
