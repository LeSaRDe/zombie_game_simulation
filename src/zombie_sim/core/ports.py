"""Narrow orchestration/read contracts; game mutations use TransitionPlan.

These protocols describe coordinator services. Rule handlers do not receive
these ports, a Simulation, a history reader, or an atomic commit capability.
"""
from fractions import Fraction
from typing import Any, Mapping, Protocol

Record = dict[str, Any]


class ObservationContext(Protocol):
    """Dated read projection with local caches and detached compatibility records."""
    state: Mapping
    time: Fraction
    horizon: Fraction
    revision: int
    occurrences: Mapping
    _position_cache: dict

    def _evaluate(self, agent, at): ...
    def _path_position(self, occurrence, time): ...
    def _position_at(self, identity): ...
    def _view_agent(self, identity): ...
    def _nearby(self, position, radius): ...
    def _public(self, agent): ...


class SchedulerContext(Protocol):
    """Execution ordering and committed-rule submission; no direct world writes."""
    world_view: Mapping
    config: Mapping
    time: Fraction
    horizon: Fraction
    revision: int
    queue: list
    decision_mode: str
    run_status: str
    termination_reason: str | None
    history_path: str
    _serial: int
    _decision_due: set
    _runtime_queue_delta: list
    _last_checkpoint: Fraction
    _since_checkpoint: int

    def _random(self, domain, key): ...
    def _schedule(self, time, phase, kind, agent=None, **fields): ...
    def _prepare_completions(self, current): ...
    def _decide(self, identities): ...
    def _dispatch(self, event): ...
    def _scheduled_boundary(self): ...
    def _run_rule(self, kind, payload=None): ...
    def _commit(self, kind, **details): ...
    def _checkpoint_if_due(self): ...
    def checkpoint(self, path=None): ...
    def snapshot(self): ...
    def advance_until(self, until, **options): ...


class DecisionContext(Protocol):
    """Policy inputs/results and isolated-plan admission, never action mutation."""
    world_view: Mapping
    config: Mapping
    time: Fraction
    horizon: Fraction
    revision: int
    workers: int
    queue: list
    occurrences: Mapping
    memories: Mapping
    services: Any
    _pool: Any
    _prepared_boundary: Any
    _prepared_effects: dict
    _runtime_prepared_agents: dict
    _runtime_performance: dict
    parallel_effect_stats: dict

    def _random(self, domain, key): ...
    def observe(self, identity): ...
    def _view_agent(self, identity): ...
    def _nearby(self, position, radius): ...
    def _position_at(self, identity): ...
    def _observation_tasks(self, controllers): ...
    def _run_rule(self, kind, payload=None): ...
