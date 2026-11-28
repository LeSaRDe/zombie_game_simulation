"""Explicit continuation state; adding a service attribute cannot persist it.

The field register is a compatibility contract for legacy runtime-v1 records.
Unknown durable fields are errors, rather than silently lost during migration.
"""
from __future__ import annotations
from dataclasses import dataclass, field, fields
from fractions import Fraction
from types import MappingProxyType
from .runtime_values import CowDict, freeze, materialize


@dataclass
class RuntimeState:
    config: dict = field(default_factory=dict)
    time: Fraction = Fraction(0)
    revision: int = 0
    seed: int = 20261106
    backend: str = 'memory'
    worker_request: object = 1
    workers: int = 1
    decision_mode: str = 'model'
    horizon: Fraction = Fraction(1800)
    history_path: str = ''
    queue: list = field(default_factory=list)
    memories: dict = field(default_factory=dict)
    execution_counters: dict = field(default_factory=lambda: {'policy_calls': 0, 'bernoulli_calls': 0})
    run_status: str = 'PAUSED'
    termination_reason: str | None = None
    _serial: int = 0
    _counter: int = 0
    _identity_counters: dict = field(default_factory=dict)
    _decision_due: set = field(default_factory=set)
    _last_checkpoint: Fraction = Fraction(0)
    _since_checkpoint: int = 0
    _prepared_boundary: Fraction | None = None
    _prepared_effects: dict = field(default_factory=dict)
    parallel_effect_stats: dict = field(default_factory=dict)
    _keyed_random_values: dict = field(default_factory=dict)
    _active_control_command: dict | None = None
    service_bindings: dict | None = None
    rule_bindings: dict | None = None
    _batching: bool = False
    _deferred_events: list = field(default_factory=list)
    _effects_buffer: list = field(default_factory=list)
    _dirty: set = field(default_factory=set)
    # Presence is preserved for optional v1 fields; defaults are not retroactive facts.
    _present: set = field(default_factory=set, repr=False)

    def __setattr__(self, name, value):
        if name not in RUNTIME_FIELDS and name != '_present':
            raise AttributeError(f'Unknown runtime field {name!r}; an explicit continuation codec is required')
        if name in ('config', 'memories'):
            value = CowDict.own(value)
        object.__setattr__(self, name, value)

    @classmethod
    def from_attributes(cls, attributes):
        unknown = set(attributes) - RUNTIME_FIELDS - {'state', 'events', 'decisions', 'random_draws', 'occurrences', 'intents'}
        if unknown:
            raise ValueError(f'Unknown durable runtime attributes: {sorted(unknown)}; an explicit extension codec is required')
        values = {key: (value if key in ('config', 'memories') else materialize(freeze(value)))
                  for key, value in attributes.items() if key in RUNTIME_FIELDS}
        result = cls(**values)
        result._present = set(values)
        for key in ('time', 'horizon', '_last_checkpoint'):
            setattr(result, key, Fraction(str(getattr(result, key))))
        return result

    def attributes(self, *, detach=True):
        result = {key: getattr(self, key) for key in RUNTIME_FIELDS if key in self._present}
        return {key: materialize(freeze(value)) for key, value in result.items()} if detach else result

    def snapshot(self):
        return RuntimeSnapshot(MappingProxyType({key: freeze(getattr(self, key))
                              for key in RUNTIME_FIELDS if key in self._present}))

    def fork(self):
        return self.snapshot().fork()

    def config_token(self):
        return self.config.seal()

    def memory_tokens(self):
        return self.memories.cell_tokens()


RUNTIME_FIELDS = frozenset(f.name for f in fields(RuntimeState) if f.name != '_present')


@dataclass(frozen=True)
class RuntimeSnapshot:
    """Read-only continuation boundary, unpacked only into an isolated workspace."""
    _values: object = field(repr=False, compare=False)

    @classmethod
    def from_attributes(cls, attributes):
        return RuntimeState.from_attributes(attributes).snapshot()

    def to_attributes(self):
        return {key: materialize(value) for key, value in self._values.items()}

    def fork(self):
        result = RuntimeState()
        for key, cell in self._values.items():
            if key in ('config', 'memories'):
                # The new wrapper owns its own mutation cache; only immutable
                # cells are shared with this snapshot and other rule branches.
                object.__setattr__(result, key, CowDict(cell, partitioned=True))
            else:
                setattr(result, key, materialize(cell))
        result._present = set(self._values)
        return result


def install_runtime_fields(owner):
    """Install explicit declared forwarding properties, never an open __getattr__."""
    for name in RUNTIME_FIELDS:
        def get(self, key=name):
            return getattr(self._runtime_state, key)
        def set_(self, value, key=name):
            setattr(self._runtime_state, key, value)
            self._runtime_state._present.add(key)
        setattr(owner, name, property(get, set_))
    return owner
