"""Recorded causal facts with typed payloads, separate from future scheduler work."""
from __future__ import annotations

from dataclasses import dataclass, field
from .activities import ActionIntent
from .agents import AgentState, ModelAssignment, TimedEffect
from .environment import InterventionChange
from .records import RecordValue
from .resources import ResourceQuantities
from .values import CodecError, ExactTime, JsonObject, check_fields, encode, freeze_json, thaw_json


@dataclass(frozen=True, kw_only=True)
class ActionEventPayload(RecordValue):
    actor: str | None = None
    target: str | None = None
    action: str | None = None
    occurrence: str | None = None
    intent_id: str | None = None
    arbitration_priority: float | None = None
    outcome: str | None = None
    reason: str | None = None
    audit_reason: str | None = None
    result: str | None = None


@dataclass(frozen=True, kw_only=True)
class LifecycleEventPayload(RecordValue):
    actor: str | None = None
    target: str | None = None
    agent_id: str | None = None
    agent: str | None = None
    source: str | None = None
    episode_id: str | None = None
    episode: str | None = None
    action_id: str | None = None
    before_state: AgentState | None = None
    after_state: AgentState | None = None
    retired_model: ModelAssignment | None = None
    retired_memory: object = None
    remains: str | None = None
    decoders = {"before_state": lambda raw: AgentState.from_record(raw, trusted=True), "after_state": lambda raw: AgentState.from_record(raw, trusted=True), "retired_model": ModelAssignment.from_record, "retired_memory": freeze_json}


@dataclass(frozen=True, kw_only=True)
class DamageEventPayload(RecordValue):
    actor: str | None
    target: str
    target_type: str
    source: str | None
    raw_damage: int
    mitigated_damage: int
    actual_damage: int


@dataclass(frozen=True, kw_only=True)
class ResourceEventPayload(RecordValue):
    agent: str
    stockpile: str
    quantities: ResourceQuantities
    decoders = {"quantities": ResourceQuantities.from_record}


@dataclass(frozen=True, kw_only=True)
class SignalEventPayload(RecordValue):
    agent: str | None = None
    signal: str | None = None
    recipients: tuple[str, ...] | None = None
    effect: TimedEffect | str | None = None
    decoders = {"recipients": tuple, "effect": lambda raw: TimedEffect.from_record(raw) if isinstance(raw, dict) else raw}


@dataclass(frozen=True, kw_only=True)
class BiologicalEventPayload(RecordValue):
    agent: str | None = None
    episode: str | None = None


@dataclass(frozen=True, kw_only=True)
class DecisionEventPayload(RecordValue):
    actor: str
    # The original model-boundary observation and diagnostics are evidence, not
    # mutable current-world state. Their pinned format remains intact.
    observation: JsonObject
    intent: JsonObject
    diagnostics: JsonObject
    fallback_reason: str | None = None
    decoders = {"observation": JsonObject.from_record, "intent": JsonObject.from_record, "diagnostics": JsonObject.from_record}


@dataclass(frozen=True, kw_only=True)
class RandomEventPayload(RecordValue):
    occurrence: str
    channel: str
    probability: float
    value: float
    outcome: bool


@dataclass(frozen=True, kw_only=True)
class BatchEventPayload(RecordValue):
    agents: tuple[str, ...] | None = None
    intents: tuple[str, ...] | None = None
    decoders = {"agents": tuple, "intents": tuple}


@dataclass(frozen=True, kw_only=True)
class SchedulerEventPayload(RecordValue):
    scheduled_kind: str | None = None


@dataclass(frozen=True, kw_only=True)
class InterventionEventPayload(RecordValue):
    intervention: str
    status: str | None = None
    change: InterventionChange | None = None
    decoders = {"change": InterventionChange.from_record}


@dataclass(frozen=True, kw_only=True)
class CounterfactualParent(RecordValue):
    run_id: str
    history_path: str
    time: ExactTime
    revision: int
    state_sha256: str
    seed: int
    counterfactual_seed: int
    pending_priorities: str
    decoders = {"time": ExactTime.parse}


@dataclass(frozen=True, kw_only=True)
class BranchEventPayload(RecordValue):
    parent: CounterfactualParent
    decoders = {"parent": CounterfactualParent.from_record}


EVENT_PAYLOADS = {
    **{kind: ActionEventPayload for kind in ("action_started", "intent_rejected", "action_cancelled", "action_completed", "action_result", "movement_blocked")},
    **{kind: LifecycleEventPayload for kind in ("conversion", "death", "infection", "cure")},
    "damage": DamageEventPayload, "inventory_drop": ResourceEventPayload,
    **{kind: SignalEventPayload for kind in ("effect_applied", "effect_expired", "signal_emitted", "signal_expired")},
    "starvation": BiologicalEventPayload, "recharge": BiologicalEventPayload,
    "decision": DecisionEventPayload, "random_draw": RandomEventPayload,
    "decision_batch": BatchEventPayload, "admission_batch": BatchEventPayload,
    "scheduler_advanced": SchedulerEventPayload, "clock_advanced": SchedulerEventPayload,
    "intervention_scheduled": InterventionEventPayload, "intervention": InterventionEventPayload,
    "branch_created": BranchEventPayload,
}


@dataclass(frozen=True)
class DomainEvent:
    id: str
    time: ExactTime
    revision: int
    kind: str
    payload: RecordValue
    causes: tuple[str, ...] = ()
    run_id: str | None = None
    _present: frozenset[str] = field(default_factory=frozenset, repr=False)

    @classmethod
    def from_record(cls, record):
        kind = record.get("kind")
        implementation = EVENT_PAYLOADS.get(kind)
        if implementation is None:
            raise CodecError(f"Unknown domain event kind {kind!r}; register its typed payload")
        envelope = {"id", "time", "revision", "kind", "causes", "run_id"}
        payload = implementation.from_record({key: value for key, value in record.items() if key not in envelope})
        return cls(record["id"], ExactTime.parse(record["time"]), record["revision"], kind, payload, tuple(record.get("causes", ())), record.get("run_id"), frozenset(record) & envelope)

    def to_record(self):
        result = self.payload.to_record()
        envelope = {"id": self.id, "time": self.time.to_record(), "revision": self.revision, "kind": self.kind, "causes": list(self.causes), "run_id": self.run_id}
        result.update({key: value for key, value in envelope.items() if key in self._present})
        return result
