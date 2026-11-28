"""Persistent agents with immutable, biologically applicable state variants."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from typing import Any

from .profiles import ProfileValues, ProfileResolver, EffectiveProfile, PROFILE_FIELDS, HUMAN_PROFILE, ZOMBIE_PROFILE
from .resources import Inventory, ResourceQuantities
from .roles import RoleAssignment, RoleRegistry, SpitterRoleState
from .values import AgentIdentity, CodecError, ExactTime, JsonObject, Point, check_fields, encode, freeze_json, number, optional_time, thaw_json


@dataclass(frozen=True)
class ModelAssignment:
    model_id: str
    version: str | None = None
    requested_version: str | None = None
    parameters: JsonObject | None = None
    _present: frozenset[str] = field(default_factory=frozenset, repr=False)

    @classmethod
    def from_record(cls, record):
        present = check_fields(record, {"model_id", "version", "requested_version", "parameters"}, "model assignment")
        if not isinstance(record.get("model_id"), str) or not record["model_id"]:
            raise CodecError("model_assignment.model_id is required")
        return cls(record["model_id"], record.get("version"), record.get("requested_version"), JsonObject.from_record(record["parameters"]) if record.get("parameters") is not None else None, present)

    def to_record(self):
        result = {"model_id": self.model_id}
        for key in ("version", "requested_version", "parameters"):
            if key in self._present:
                result[key] = encode(getattr(self, key))
        return result


@dataclass(frozen=True)
class TimedEffect:
    kind: str
    start_at: ExactTime
    end_at: ExactTime | None
    value: float | None = None
    source: str | None = None
    strength: float | None = None
    resistance: float | None = None
    radius: float | None = None
    hit_bonus: float | None = None
    effect_id: str | None = None
    recipient: str | None = None
    source_event_id: str | None = None
    _present: frozenset[str] = field(default_factory=frozenset, repr=False)

    @classmethod
    def from_record(cls, record):
        present = check_fields(record, {"kind", "type", "start_at", "end_at", "value", "strength", "source", "resistance", "radius", "hit_bonus", "id", "recipient", "source_event_id"}, "timed effect")
        kind = record.get("kind", record.get("type"))
        if kind not in {"guard", "recon", "prophylaxis", "rally", "rallied", "dash"}:
            raise CodecError(f"Unknown timed effect {kind!r}")
        start = ExactTime.parse(record.get("start_at", 0)); end = optional_time(record.get("end_at"))
        if end is not None and end.value < start.value:
            raise CodecError("Effect ends before it starts")
        for key in ("value", "strength", "resistance", "radius", "hit_bonus"):
            if record.get(key) is not None:
                number(record[key], "effect." + key)
        return cls(kind, start, end, record.get("value"), record.get("source"), record.get("strength"), record.get("resistance"), record.get("radius"), record.get("hit_bonus"), record.get("id"), record.get("recipient"), record.get("source_event_id"), present)

    def to_record(self):
        values = {"kind": self.kind, "type": self.kind, "id": self.effect_id}
        for key in ("start_at", "end_at", "value", "strength", "source", "resistance", "radius", "hit_bonus", "recipient", "source_event_id"):
            values[key] = encode(getattr(self, key))
        return {key: values[key] for key in self._present}

    def applies_at(self, at):
        if at is None:
            return True
        time = ExactTime.parse(at).value
        return self.start_at.value <= time and (self.end_at is None or time < self.end_at.value)

    def magnitude(self, fallback, attribute):
        return next((value for value in (self.value, self.strength, getattr(self, attribute)) if value is not None), fallback)


@dataclass(frozen=True)
class EngineFacts:
    """Persisted integration anchors, independent of projected game properties."""

    evaluated_at: ExactTime | None = None
    generation: int = 0
    hunger_generation: int = 0
    starvation_due_at: ExactTime | None = None
    travelled: float | None = None
    model_memory: Any = None
    memory: Any = None
    initially_infected: bool | None = None


@dataclass(frozen=True)
class AgentProjection:
    """Dated boundary evidence. These values do not drive current-state rules."""

    profile: ProfileValues = field(default_factory=ProfileValues)
    speed: float | None = None
    sense_r: float | None = None
    damage_resistance: float | None = None
    rally_bonus: float | None = None
    infection_resistance_effective: float | None = None
    current_action: str | None = None
    infection_progress: float | None = None
    onset_at: ExactTime | None = None
    incubation_duration: ExactTime | None = None
    conversion_due_at: ExactTime | None = None
    at_time: ExactTime | None = None


COMMON_FIELDS = frozenset({"id", "type", "role", "life", "stamina", "x", "y", "created_at", "infection_episode", "cooldowns", "effects", "active_action", "model_assignment", "profile", "type_profile", "role_profile", "last_state_event_id", "revision", "status", "action_state", "death_at", "death_cause", "_evaluated_at", "_generation", "_hunger_generation", "_starvation_due_at", "_travelled", "model_memory", "memory", "infected", "next_charge_at", "at_time", "current_action", "speed", "sense_r", "damage_resistance", "rally_bonus", "infection_resistance_effective", "infection_progress", "onset_at", "incubation_duration", "conversion_due_at"})
HUMAN_FIELDS = frozenset({"hunger", "inventory", "reserved", "carry_capacity", "starvation_started_at", "next_starvation_damage_at"})
SPITTER_FIELDS = frozenset({"spit_charges", "reserved_charges"})
PROJECTED_FIELDS = frozenset({"speed", "sense_r", "damage_resistance", "rally_bonus", "infection_resistance_effective", "current_action", "infection_progress", "onset_at", "incubation_duration", "conversion_due_at", "at_time"})


@dataclass(frozen=True, kw_only=True)
class AgentState(ABC):
    agent_id: str
    life: int
    stamina: float
    position: Point
    created_at: ExactTime
    role_assignment: RoleAssignment | None = None
    model_assignment: ModelAssignment | None = None
    infection_episode: str | None = None
    active_action: str | None = None
    cooldowns: tuple[tuple[str, ExactTime], ...] = ()
    effects: tuple[tuple[str, TimedEffect], ...] = ()
    type_profile: ProfileValues = field(default_factory=ProfileValues)
    role_profile: ProfileValues = field(default_factory=ProfileValues)
    individual_profile: ProfileValues = field(default_factory=ProfileValues)
    revision: int = 0
    last_state_event_id: str = "initialization"
    death_at: ExactTime | None = None
    death_cause: str | None = None
    engine: EngineFacts = field(default_factory=EngineFacts)
    projection: AgentProjection = field(default_factory=AgentProjection)
    retired_role_state: SpitterRoleState | None = None
    next_charge_at: ExactTime | None = None
    registry: RoleRegistry = field(repr=False, compare=False)
    _present: frozenset[str] = field(default_factory=frozenset, repr=False)
    _effects_as_list: bool = field(default=False, repr=False)

    @property
    @abstractmethod
    def biological_type(self): ...

    @property
    def role(self):
        return self.role_assignment.definition.role_id if self.role_assignment else None

    @property
    def role_state(self):
        return self.role_assignment.state if self.role_assignment else None

    @property
    def alive(self):
        return self.life > 0

    @property
    def status(self):
        return self.classify(self.biological_type, self.life, self.infection_episode)

    @staticmethod
    def classify(biological_type, life, infection_episode=None):
        if life == 0:
            return "DEAD"
        return "ACTIVE" if biological_type == "Zombie" else "INFECTED" if infection_episode else "HEALTHY"

    @property
    def action_status(self):
        return self.classify_action(self.life, self.active_action)

    @staticmethod
    def classify_action(life, active_action=None):
        return "DEAD" if life == 0 else "BUSY" if active_action else "IDLE"

    @property
    def capabilities(self):
        if not self.alive:
            return ()
        base = self.registry.type_capabilities(self.biological_type)
        return tuple(sorted(set(base) | set(self.role_assignment.definition.actions if self.role_assignment else ())))

    def effective_profile(self, at=None, current_action=None):
        return ProfileResolver.resolve(self.biological_type, self.life,
            self.role_assignment.definition if self.role_assignment else None,
            type_profile=self.type_profile, role_profile=self.role_profile,
            individual_profile=self.individual_profile,
            carry_capacity=self.inventory.capacity if isinstance(self, HumanState) else None,
            effects=tuple(effect for _, effect in self.effects), at=at, current_action=current_action)

    def validate(self):
        number(self.life, "life", maximum=100, integer=True)
        number(self.stamina, "stamina", maximum=100)
        number(self.revision, "revision", integer=True)
        if self.role_assignment and self.role_assignment.definition.compatible_type != self.biological_type:
            raise CodecError("Role is incompatible with biological state")
        if self.biological_type == "Zombie" and self.infection_episode is not None:
            raise CodecError("Zombies cannot retain a human infection episode")
        if not self.alive and any((self.role_assignment, self.model_assignment, self.active_action, self.infection_episode, self.effects, self.cooldowns)):
            raise CodecError("Dead state cannot retain active assignments, actions, episodes, effects or cooldowns")
        if self.alive and self.model_assignment is None:
            raise CodecError("A living state requires a model assignment")
        if self.alive and (self.death_at is not None or self.death_cause is not None):
            raise CodecError("Living states cannot have death metadata")
        if self.role_state:
            maximum = self.effective_profile().source.max_spit_charges
            if self.role != "SPITTER" or maximum is None or self.role_state.charges > maximum:
                raise CodecError("Spitter charges do not match the active role profile")

    @classmethod
    def from_record(cls, record, *, roles=None, trusted=False):
        """Decode named fields; trusted skips aggregate checks, never field loss."""
        roles = roles or RoleRegistry.default()
        kind = record.get("type")
        if kind not in {"Human", "Zombie"}:
            raise CodecError(f"Unknown biological type {kind!r}")
        present = check_fields(record, COMMON_FIELDS | HUMAN_FIELDS | SPITTER_FIELDS | PROFILE_FIELDS, "agent")
        if kind == "Zombie" and set(record) & (HUMAN_FIELDS - {"carry_capacity"}):
            raise CodecError("Zombie state contains human-only fields")
        definition = roles.get(record.get("role"))
        role_assignment = RoleAssignment(definition) if definition else None
        raw_effects = record.get("effects", {})
        list_effects = isinstance(raw_effects, (list, tuple))
        effect_items = enumerate(raw_effects) if list_effects else raw_effects.items()
        effects = tuple((str(key), TimedEffect.from_record(value)) for key, value in effect_items)
        charges = None
        if "spit_charges" in record:
            charges = SpitterRoleState(record["spit_charges"], record.get("reserved_charges", 0), optional_time(record.get("next_charge_at")))
            if definition is None and record["life"] > 0:
                raise CodecError("Only active Spitters may have live charge state")
        if role_assignment is not None and charges is not None:
            role_assignment = replace(role_assignment, state=charges)
        engine = EngineFacts(optional_time(record.get("_evaluated_at")), record.get("_generation", 0), record.get("_hunger_generation", 0), optional_time(record.get("_starvation_due_at")), record.get("_travelled"), freeze_json(record.get("model_memory")), freeze_json(record.get("memory")), record.get("infected"))
        projection_values = {key: value for key, value in record.items() if key in PROFILE_FIELDS and key != "carry_capacity"}
        projection = AgentProjection(ProfileValues.from_record(projection_values), **{key: optional_time(record.get(key)) if key in {"onset_at", "incubation_duration", "conversion_due_at", "at_time"} else record.get(key) for key in PROJECTED_FIELDS})
        common = dict(agent_id=str(record["id"]), life=record["life"], stamina=record["stamina"], position=Point(record["x"], record["y"]), created_at=ExactTime.parse(record.get("created_at", 0)), role_assignment=role_assignment,
                      model_assignment=ModelAssignment.from_record(record["model_assignment"]) if record.get("model_assignment") is not None else None,
                      infection_episode=record.get("infection_episode"), active_action=record.get("active_action"), cooldowns=tuple((key, ExactTime.parse(value)) for key, value in record.get("cooldowns", {}).items()), effects=effects,
                      type_profile=ProfileValues.from_record(record.get("type_profile", {})), role_profile=ProfileValues.from_record(record.get("role_profile", {})), individual_profile=ProfileValues.from_record(record.get("profile", {})),
                      revision=record.get("revision", 0), last_state_event_id=record.get("last_state_event_id", "initialization"), death_at=optional_time(record.get("death_at")), death_cause=record.get("death_cause"), engine=engine, projection=projection,
                      retired_role_state=charges if not definition else None, next_charge_at=optional_time(record.get("next_charge_at")), registry=roles, _present=present, _effects_as_list=list_effects)
        if kind == "Human":
            capacity = record.get("carry_capacity", definition.parameters.carry_capacity if definition and definition.parameters.carry_capacity is not None else 10)
            result = HumanState(**common, hunger=record.get("hunger", 20.0), inventory=Inventory(ResourceQuantities.from_record(record.get("inventory", {})), ResourceQuantities.from_record(record.get("reserved", {})), capacity), starvation_started_at=optional_time(record.get("starvation_started_at")), next_starvation_damage_at=optional_time(record.get("next_starvation_damage_at")))
        else:
            result = ZombieState(**common)
        if not trusted:
            result.validate()
            if "status" in record and record["status"] != result.status:
                raise CodecError("Declared status disagrees with biological state")
            if "action_state" in record and record["action_state"] != result.action_status:
                raise CodecError("Declared action_state disagrees with active occurrence")
        return result

    def to_record(self):
        values = {"id": self.agent_id, "type": self.biological_type, "role": self.role, "life": self.life, "stamina": self.stamina, "x": self.position.x, "y": self.position.y, "created_at": self.created_at.to_record(), "infection_episode": self.infection_episode,
                  "cooldowns": {key: time.to_record() for key, time in self.cooldowns}, "effects": [effect.to_record() for _, effect in self.effects] if self._effects_as_list else {key: effect.to_record() for key, effect in self.effects},
                  "active_action": self.active_action, "model_assignment": encode(self.model_assignment), "profile": self.individual_profile.to_record(), "type_profile": self.type_profile.to_record(), "role_profile": self.role_profile.to_record(), "last_state_event_id": self.last_state_event_id, "revision": self.revision,
                  "status": self.status, "action_state": self.action_status, "death_at": encode(self.death_at), "death_cause": self.death_cause, "next_charge_at": encode(self.next_charge_at),
                  "_evaluated_at": encode(self.engine.evaluated_at), "_generation": self.engine.generation, "_hunger_generation": self.engine.hunger_generation, "_starvation_due_at": encode(self.engine.starvation_due_at), "_travelled": self.engine.travelled,
                  "model_memory": thaw_json(self.engine.model_memory), "memory": thaw_json(self.engine.memory), "infected": self.engine.initially_infected}
        values.update(self.projection.profile.to_record())
        values.update({key: encode(getattr(self.projection, key)) for key in PROJECTED_FIELDS})
        charges = self.role_state or self.retired_role_state
        if charges:
            values.update(spit_charges=charges.charges, reserved_charges=charges.reserved_charges)
        if isinstance(self, HumanState):
            values.update(hunger=self.hunger, inventory=self.inventory.quantities.to_record(), reserved=self.inventory.reserved.to_record(), carry_capacity=self.inventory.capacity, starvation_started_at=encode(self.starvation_started_at), next_starvation_damage_at=encode(self.next_starvation_damage_at))
        return {key: values[key] for key in self._present}


@dataclass(frozen=True, kw_only=True)
class HumanState(AgentState):
    hunger: float
    inventory: Inventory
    starvation_started_at: ExactTime | None = None
    next_starvation_damage_at: ExactTime | None = None

    @property
    def biological_type(self):
        return "Human"

    def validate(self):
        super().validate()
        number(self.hunger, "hunger", maximum=100)
        if not self.alive and self.inventory.quantities.total:
            raise CodecError("A dead human's inventory must already have been dropped")


@dataclass(frozen=True, kw_only=True)
class ZombieState(AgentState):
    @property
    def biological_type(self):
        return "Zombie"


@dataclass(frozen=True)
class Agent:
    identity: AgentIdentity
    current_state: AgentState

    def __post_init__(self):
        if self.identity.agent_id != self.current_state.agent_id:
            raise CodecError("Agent identity and state ownership disagree")

    @classmethod
    def from_record(cls, record, run_id, *, roles=None, trusted=False):
        return cls(AgentIdentity(run_id, str(record["id"])), AgentState.from_record(record, roles=roles, trusted=trusted))

    def to_record(self):
        return self.current_state.to_record()

    def with_state(self, state):
        """Return the same persistent identity with a new immutable state value."""
        if not self.current_state.alive and (state.alive or state.biological_type != self.current_state.biological_type or state.position != self.current_state.position):
            raise CodecError("Death is terminal and freezes type and location")
        return Agent(self.identity, state)
