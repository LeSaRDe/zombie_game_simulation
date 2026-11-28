"""Applicable spatial/environment state and resource ownership."""
from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from fractions import Fraction
from .records import RecordValue
from .resources import ResourceQuantities, RESOURCES
from .values import CodecError, ExactTime, JsonObject, Point, check_fields, encode, number, optional_time


@dataclass(frozen=True)
class Rectangle:
    xmin: float
    ymin: float
    xmax: float
    ymax: float
    _wire_coordinates: tuple | None = field(default=None, repr=False, compare=False)
    _wire_object: bool = field(default=False, repr=False, compare=False)

    def __post_init__(self):
        for name in ("xmin", "ymin", "xmax", "ymax"):
            number(getattr(self, name), name)
        if self.xmin >= self.xmax or self.ymin >= self.ymax:
            raise CodecError("Rectangle must have positive width and height")

    @classmethod
    def from_record(cls, record):
        if isinstance(record, dict):
            check_fields(record, {"xmin", "ymin", "xmax", "ymax"}, "rectangle")
            raw = tuple(record[key] for key in ("xmin", "ymin", "xmax", "ymax"))
        elif isinstance(record, (list, tuple)) and len(record) == 4:
            raw = tuple(record)
        else:
            raise CodecError("Rectangle requires four coordinates")
        try:
            coordinates = tuple(float(Fraction(value)) if isinstance(value, str) else value for value in raw)
        except (ValueError, ZeroDivisionError) as error:
            raise CodecError("Rectangle coordinates must be finite numbers") from error
        return cls(*coordinates, _wire_coordinates=raw, _wire_object=isinstance(record, dict))

    def to_record(self):
        coordinates = self._wire_coordinates or (self.xmin, self.ymin, self.xmax, self.ymax)
        return dict(zip(("xmin", "ymin", "xmax", "ymax"), coordinates)) if self._wire_object else list(coordinates)

    def contains(self, point: Point):
        return self.xmin <= point.x <= self.xmax and self.ymin <= point.y <= self.ymax


@dataclass(frozen=True, kw_only=True)
class WorldBounds(RecordValue):
    length: float
    width: float
    boundary_policy: str = "CLOSED"
    coordinate_system: str | None = None

    def __post_init__(self):
        number(self.length, "length"); number(self.width, "width")
        if self.length <= 0 or self.width <= 0 or self.boundary_policy != "CLOSED":
            raise CodecError("World requires positive dimensions and CLOSED boundaries")


@dataclass(frozen=True, kw_only=True)
class SpatialEntity(RecordValue, ABC):
    id: str


@dataclass(frozen=True, kw_only=True)
class Barrier(SpatialEntity, ABC):
    footprint: Rectangle
    type: str
    created_at: ExactTime | None = None
    decoders = {"footprint": Rectangle.from_record, "created_at": ExactTime.parse}

    @classmethod
    def from_record(cls, record, **kwargs):
        if cls is Barrier:
            implementation = {"Obstacle": PermanentObstacle, "Gate": Gate, "Barricade": Barricade}.get(record.get("type"))
            if implementation is None:
                raise CodecError(f"Unknown barrier type {record.get('type')!r}")
            return implementation.from_record(record, **kwargs)
        return super().from_record(record, **kwargs)

    @property
    def blocks_movement(self):
        raise NotImplementedError


@dataclass(frozen=True, kw_only=True)
class PermanentObstacle(Barrier):
    blocks_vision: bool = True
    destructible: bool = False

    @property
    def blocks_movement(self):
        return True


@dataclass(frozen=True, kw_only=True)
class Gate(Barrier):
    mode: str
    integrity: int
    max_integrity: int
    shelter_id: str | None = None

    def __post_init__(self):
        number(self.integrity, "gate.integrity", maximum=self.max_integrity, integer=True)
        number(self.max_integrity, "gate.max_integrity", minimum=1, integer=True)
        if self.mode not in {"OPEN", "CLOSED", "BREACHED"} or (self.mode == "BREACHED") != (self.integrity == 0):
            raise CodecError("Gate mode and integrity disagree")

    @property
    def blocks_movement(self):
        return self.mode == "CLOSED"


@dataclass(frozen=True, kw_only=True)
class Barricade(Barrier):
    integrity: int
    max_integrity: int
    creator_id: str | None = None
    destroyed_at: ExactTime | None = None
    decoders = {**Barrier.decoders, "destroyed_at": ExactTime.parse}

    def __post_init__(self):
        number(self.integrity, "barricade.integrity", maximum=self.max_integrity, integer=True)
        number(self.max_integrity, "barricade.max_integrity", minimum=1, integer=True)

    @property
    def blocks_movement(self):
        return self.integrity > 0


@dataclass(frozen=True, kw_only=True)
class Shelter(SpatialEntity):
    interior: Rectangle
    walls: tuple[str, ...]
    gates: tuple[str, ...]
    decoders = {"interior": Rectangle.from_record, "walls": tuple, "gates": tuple}


@dataclass(frozen=True, kw_only=True)
class Stockpile(SpatialEntity):
    x: float
    y: float
    inventory: ResourceQuantities
    reserved: ResourceQuantities = field(default_factory=lambda: ResourceQuantities(_present=frozenset()))
    created_at: ExactTime | None = None
    available: ResourceQuantities | None = None
    decoders = {"inventory": ResourceQuantities.from_record, "reserved": ResourceQuantities.from_record, "created_at": ExactTime.parse, "available": ResourceQuantities.from_record}

    def __post_init__(self):
        Point(self.x, self.y)
        if any(self.reserved.quantity(key) > self.inventory.quantity(key) for key in RESOURCES):
            raise CodecError("Stockpile reservations exceed stock")


@dataclass(frozen=True, kw_only=True)
class Remains(SpatialEntity):
    source_agent_id: str
    x: float
    y: float
    biomass: int
    reserved_biomass: int = 0
    created_at: ExactTime | None = None
    decoders = {"created_at": ExactTime.parse}

    def __post_init__(self):
        Point(self.x, self.y)
        number(self.biomass, "biomass", integer=True)
        number(self.reserved_biomass, "reserved_biomass", maximum=self.biomass, integer=True)


@dataclass(frozen=True, kw_only=True)
class InfectionEpisode(RecordValue):
    id: str
    agent_id: str
    source_kind: str
    source_event_id: str
    onset_at: ExactTime
    incubation_duration: ExactTime
    conversion_due_at: ExactTime
    onset_revision: int = 0
    source_agent_id: str | None = None
    episode_id: str | None = None
    ended_at: ExactTime | None = None
    end_revision: int | None = None
    outcome: str | None = None
    decoders = {key: ExactTime.parse for key in ("onset_at", "incubation_duration", "conversion_due_at", "ended_at")}

    def __post_init__(self):
        if self.incubation_duration.value <= 0 or self.conversion_due_at.value != self.onset_at.value + self.incubation_duration.value:
            raise CodecError("Infection episode deadline must equal onset plus positive duration")
        if self.outcome not in {None, "ONGOING", "CURED", "CONVERTED", "HOST_DIED"}:
            raise CodecError("Unknown infection episode outcome")

    def progress(self, at):
        return max(0, min(1, (ExactTime.parse(at).value - self.onset_at.value) / self.incubation_duration.value))


@dataclass(frozen=True, kw_only=True)
class SignalPayload(RecordValue):
    entity_id: str | None = None
    position: JsonObject | tuple | None = None
    resource: str | None = None
    resource_type: str | None = None
    quantity: int | None = None
    observed_at: ExactTime | None = None
    type: str | None = None
    decoders = {"position": lambda value: JsonObject.from_record(value) if isinstance(value, dict) else tuple(value), "observed_at": ExactTime.parse}


@dataclass(frozen=True, kw_only=True)
class Signal(SpatialEntity):
    sender_id: str
    sender_type_at_emission: str
    position_at_emission: tuple[float, float]
    radius: float
    kind: str
    payload: SignalPayload
    emitted_at: ExactTime
    expires_at: ExactTime
    recipients: tuple[str, ...] = ()
    source: str | None = None
    decoders = {"position_at_emission": tuple, "payload": SignalPayload.from_record, "emitted_at": ExactTime.parse, "expires_at": ExactTime.parse, "recipients": tuple}


@dataclass(frozen=True, kw_only=True)
class Reservation(RecordValue):
    id: str
    occurrence_id: str
    actor: str
    collection: str
    holder: str
    kind: str
    resource: str | None
    quantity: int

    def __post_init__(self):
        number(self.quantity, "reservation.quantity", minimum=1, integer=True)


@dataclass(frozen=True, kw_only=True)
class InterventionChange(RecordValue):
    kind: str
    agent: str | None = None
    role: str | None = None
    model_id: str | None = None
    model_version: str | None = None
    memory_policy: str | None = None
    resource: str | None = None
    resource_type: str | None = None
    quantity: int | None = None
    stockpile: str | None = None
    x: float | None = None
    y: float | None = None
    drop_order: tuple[str, ...] | None = None
    decoders = {"drop_order": tuple}


@dataclass(frozen=True, kw_only=True)
class Intervention(RecordValue):
    id: str
    at: ExactTime
    change: InterventionChange
    status: str
    reason: str | None = None
    effective_time: ExactTime | None = None
    effective_revision: int | None = None
    decoders = {"at": ExactTime.parse, "change": InterventionChange.from_record, "effective_time": ExactTime.parse}
