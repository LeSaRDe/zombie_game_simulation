"""Definitions, proposals, admitted occurrences and scheduled work are distinct."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from .agents import AgentState
from .environment import Barrier, Rectangle, Remains, Reservation, SignalPayload, Stockpile
from .records import RecordValue
from .values import CodecError, ExactTime, JsonObject, encode, freeze_json, number, thaw_json


@dataclass(frozen=True, kw_only=True)
class PathPoint(RecordValue):
    x: float
    y: float
    offset: ExactTime
    decoders = {"offset": ExactTime.parse}


@dataclass(frozen=True)
class Trajectory:
    points: tuple[PathPoint, ...]

    @classmethod
    def from_record(cls, record):
        return cls(tuple(PathPoint.from_record(point) for point in record))

    def to_record(self):
        return [point.to_record() for point in self.points]


@dataclass(frozen=True, kw_only=True)
class ActionParameters(RecordValue):
    duration: ExactTime | None = None
    path: Trajectory | None = None
    target: str | int | None = None
    center: JsonObject | tuple | None = None
    length: float | None = None
    orientation: str | None = None
    footprint: Rectangle | None = None
    resource: str | None = None
    resource_type: str | None = None
    quantity: int | None = None
    kind: str | None = None
    payload: SignalPayload | None = None
    decoders = {"duration": ExactTime.parse, "path": Trajectory.from_record, "center": lambda value: JsonObject.from_record(value) if isinstance(value, dict) else tuple(value), "footprint": Rectangle.from_record, "payload": SignalPayload.from_record}


@dataclass(frozen=True)
class ActionDefinition:
    action_id: str
    duration_min: ExactTime
    duration_max: ExactTime
    stamina_cost: float
    cooldown: ExactTime
    target_kind: str
    reach: float | None
    types: tuple[str, ...]
    roles: tuple[str, ...]
    version: str = "0.1.0"

    @classmethod
    def from_catalog(cls, action_id, catalog):
        definition = catalog.actions[action_id] if hasattr(catalog, "actions") else catalog
        version = catalog.manifest["ontology_version"] if hasattr(catalog, "manifest") else "0.1.0"
        return cls(action_id, ExactTime.parse(definition["duration_min"]), ExactTime.parse(definition["duration_max"]), definition["stamina_cost"], ExactTime.parse(definition["cooldown"]), definition["target_kind"], definition.get("reach"), tuple(definition["types"]), tuple(definition["roles"]), version)


@dataclass(frozen=True, kw_only=True)
class IntentOutcome(RecordValue):
    id: str
    actor: str
    status: str
    occurrence_id: str | None = None
    reason: str | None = None


@dataclass(frozen=True, kw_only=True)
class ActionIntent(RecordValue):
    id: str
    actor: str
    action: str | None = None
    target: str | int | None = None
    parameters: ActionParameters | None = None
    proposed_at: ExactTime | None = None
    outcome: IntentOutcome | None = None
    resolved_parameters: ActionParameters | None = None
    decision_id: str | None = None
    audit_reason: str | None = None
    name: str | None = None
    agent_id: str | None = None
    observation_id: str | None = None
    fallback_for: str | None = None
    decoders = {"parameters": ActionParameters.from_record, "resolved_parameters": ActionParameters.from_record, "proposed_at": ExactTime.parse, "outcome": IntentOutcome.from_record}

    @classmethod
    def from_record(cls, record, **kwargs):
        if record.get("outcome", {}).get("status") == "REJECTED":
            # Rejected proposals may be deliberately malformed. Keep the exact
            # submitted JSON as audit evidence, never as executable parameters.
            return RejectedActionIntent.from_record(record)
        return super().from_record(record, **kwargs)


@dataclass(frozen=True)
class RejectedActionIntent:
    id: str
    actor: str
    outcome: IntentOutcome
    proposed_at: ExactTime
    audit_reason: str | None
    submitted_evidence: JsonObject

    @classmethod
    def from_record(cls, record):
        return cls(record["id"], record["actor"], IntentOutcome.from_record(record["outcome"]), ExactTime.parse(record["proposed_at"]), record.get("audit_reason"), JsonObject.from_record({key: value for key, value in record.items() if key not in {"id", "actor", "outcome", "proposed_at", "audit_reason"}}))

    def to_record(self):
        result = self.submitted_evidence.to_record()
        result.update(id=self.id, actor=self.actor, outcome=self.outcome.to_record(), proposed_at=self.proposed_at.to_record())
        if self.audit_reason is not None:
            result["audit_reason"] = self.audit_reason
        return result


def environment_evidence(record):
    if "footprint" in record:
        return Barrier.from_record(record)
    if "biomass" in record:
        return Remains.from_record(record)
    return Stockpile.from_record(record)


@dataclass(frozen=True, kw_only=True)
class ActionOccurrence(RecordValue):
    id: str
    intent_id: str
    actor: str
    action: str
    target: str | None
    target_collection: str
    parameters: ActionParameters
    start_at: ExactTime
    planned_end: ExactTime
    duration: ExactTime
    cost: float
    cooldown: ExactTime
    result: str
    reservations: tuple[str, ...]
    admission_priority: float
    actor_start: AgentState | None = None
    actor_after_start: AgentState | None = None
    target_start: AgentState | None = None
    actor_before_end: AgentState | None = None
    actor_after_end: AgentState | None = None
    target_before_end: AgentState | None = None
    target_after_end: AgentState | None = None
    environment_start: Barrier | Stockpile | Remains | None = None
    resolved_at: ExactTime | None = None
    audit_reason: str | None = None
    hit: bool | None = None
    damage: int | None = None
    conflict_winner: str | None = None
    stockpile_id: str | None = None
    healing: int | None = None
    episode_id: str | None = None
    cure: bool | None = None
    integrity_damage: int | None = None
    integrity_restored: int | None = None
    barrier_id: str | None = None
    released_reservations: tuple[Reservation, ...] = ()
    spent_resources: tuple[Reservation, ...] = ()
    decoders = {"parameters": ActionParameters.from_record, "start_at": ExactTime.parse, "planned_end": ExactTime.parse, "duration": ExactTime.parse, "cooldown": ExactTime.parse, "resolved_at": ExactTime.parse, "reservations": tuple, "environment_start": environment_evidence,
                "released_reservations": lambda raw: tuple(Reservation.from_record(item) for item in raw), "spent_resources": lambda raw: tuple(Reservation.from_record(item) for item in raw),
                **{key: lambda record: AgentState.from_record(record, trusted=True) for key in ("actor_start", "actor_after_start", "target_start", "actor_before_end", "actor_after_end", "target_before_end", "target_after_end")}}

    def validate(self):
        if self.duration.value <= 0 or self.planned_end.value != self.start_at.value + self.duration.value:
            raise CodecError("Occurrence requires a positive, consistent action interval")
        if self.result == "IN_PROGRESS" and self.resolved_at is not None:
            raise CodecError("Pending occurrence cannot have a resolution time")
        if self.result != "IN_PROGRESS" and self.resolved_at is None:
            raise CodecError("Resolved occurrence requires a resolution time")
        if self.result not in {"IN_PROGRESS", "SUCCEEDED", "MISSED", "FAILED_PRECONDITION", "CANCELLED_BY_DEATH", "CANCELLED_BY_CONVERSION", "CANCELLED_BY_CONFLICT", "CANCELLED_BY_INTERVENTION", "PARTIAL_BLOCKED"}:
            raise CodecError("Unknown admitted action result")


@dataclass(frozen=True, kw_only=True)
class ScheduledPayload(RecordValue):
    kind: str
    agent: str | None = None
    occurrence: str | None = None
    generation: int | None = None
    episode: str | None = None
    effect: str | None = None
    intervention: str | None = None
    signal: str | None = None

    def __post_init__(self):
        if self.kind not in {"complete", "decision", "starvation", "conversion", "recharge", "expire", "intervention", "blocked", "signal_expire"}:
            raise CodecError(f"Unknown scheduled task kind {self.kind!r}")


@dataclass(frozen=True)
class ScheduledTask:
    due_at: ExactTime
    phase: int
    priority: float
    serial: int
    payload: ScheduledPayload

    def __post_init__(self):
        number(self.phase, "scheduled phase", integer=True)
        number(self.serial, "scheduled serial", integer=True)
        number(self.priority, "scheduled priority", maximum=1)

    @classmethod
    def from_record(cls, record):
        if isinstance(record, cls):
            return record
        if not isinstance(record, (tuple, list)) or len(record) != 5:
            raise CodecError("Scheduled task requires time, phase, priority, serial and payload")
        return cls(ExactTime.parse(record[0]), record[1], record[2], record[3], ScheduledPayload.from_record(record[4]))

    def to_record(self):
        return [self.due_at.to_record(), self.phase, self.priority, self.serial, self.payload.to_record()]

    @property
    def order_key(self):
        return (self.due_at.value, self.phase, self.priority, self.serial)

    def as_legacy_tuple(self):
        """Detached compatibility row; heap ordering still uses exact values."""
        return (*self.order_key, self.payload.to_record())

    def __getitem__(self, index):
        return self.as_legacy_tuple()[index]

    def __iter__(self):
        return iter(self.as_legacy_tuple())

    def __len__(self):
        return 5

    def __lt__(self, other):
        key = other.order_key if isinstance(other, ScheduledTask) else tuple(other[:4])
        return self.order_key < key
