"""Typed profile parameters; derived values are computed, never independently set."""
from __future__ import annotations

from dataclasses import dataclass, fields, replace
from functools import cached_property, lru_cache
from .values import CodecError, check_fields, number


@dataclass(frozen=True, eq=False)
class ProfileValues:
    base_speed: float | None = None
    base_sense_r: float | None = None
    movement_cost: float | None = None
    rest_rate: float | None = None
    base_damage_resistance: float | None = None
    max_life: int | None = None
    max_stamina: float | None = None
    hunger_rate: float | None = None
    combat_skill: float | None = None
    melee_damage: int | None = None
    medical_skill: float | None = None
    infection_resistance: float | None = None
    carry_capacity: int | None = None
    attack_skill: float | None = None
    virulence: float | None = None
    claw_damage: int | None = None
    bite_damage: int | None = None
    feed_healing: int | None = None
    feed_energy: float | None = None
    treatment_duration: float | None = None
    treatment_cost: int | None = None
    prophylaxis_resistance: float | None = None
    prophylaxis_duration: float | None = None
    strike_damage: int | None = None
    guard_resistance: float | None = None
    guard_duration: float | None = None
    recon_radius: float | None = None
    recon_duration: float | None = None
    mark_radius: float | None = None
    build_integrity: int | None = None
    build_material_cost: int | None = None
    repair_amount: int | None = None
    repair_material_cost: int | None = None
    rally_radius: float | None = None
    rally_duration: float | None = None
    rally_hit_bonus: float | None = None
    demolish_damage: int | None = None
    dash_multiplier: float | None = None
    dash_duration: float | None = None
    spit_range: float | None = None
    spit_damage: int | None = None
    spit_potency: float | None = None
    max_spit_charges: int | None = None
    recharge_interval: float | None = None
    call_radius: float | None = None
    call_ttl: float | None = None

    def __post_init__(self):
        probabilities = {"combat_skill", "medical_skill", "infection_resistance", "attack_skill", "virulence", "spit_potency", "prophylaxis_resistance", "rally_hit_bonus"}
        integers = {"max_life", "melee_damage", "carry_capacity", "claw_damage", "bite_damage", "feed_healing", "treatment_cost", "strike_damage", "build_integrity", "build_material_cost", "repair_amount", "repair_material_cost", "demolish_damage", "spit_damage", "max_spit_charges"}
        positive = {"base_speed", "treatment_duration", "treatment_cost", "prophylaxis_duration", "guard_duration", "recon_duration", "build_integrity", "build_material_cost", "repair_material_cost", "rally_duration", "dash_duration", "max_spit_charges", "recharge_interval", "call_ttl"}
        for key, value in self.to_record().items():
            number(value, "profile." + key, maximum=1 if key in probabilities else .8 if key in {"base_damage_resistance", "guard_resistance"} else None, integer=key in integers)
            if key in positive and value <= 0:
                raise CodecError(f"profile.{key}: must be positive")
            if key == "dash_multiplier" and value < 1:
                raise CodecError("profile.dash_multiplier: must be at least one")
            if key in {"max_life", "max_stamina"} and value != 100:
                raise CodecError(f"profile.{key}: ontology fixes the cap at 100")

    @classmethod
    def from_record(cls, record):
        check_fields(record, PROFILE_FIELDS, "profile")
        if any(value is None for value in record.values()):
            raise CodecError("Profile parameters cannot be null")
        # Only exact immutable JSON numeric fields are shared. Custom numeric
        # or class subtypes retain their pre-existing construction semantics.
        if cls is ProfileValues and all(type(key) is str and type(value) in (int, float)
                                        for key, value in record.items()):
            key = tuple(sorted((name, type(value), value.hex() if type(value) is float else value)
                               for name, value in record.items()))
            return _intern_profile_values(key)
        return cls(**record)

    def to_record(self):
        return dict(self._record_items)

    @cached_property
    def _record_items(self):
        # Derived immutable cache, never an alternative mutable profile source.
        return tuple((name, getattr(self, name)) for name in PROFILE_FIELD_ORDER if getattr(self, name) is not None)

    def overlay(self, other: ProfileValues) -> ProfileValues:
        return replace(self, **other.to_record())

    @cached_property
    def _cache_key(self):
        # Numeric types and signed zero have distinct legacy JSON spellings.
        return tuple((type(value), value.hex() if type(value) is float else value)
                     for value in (getattr(self, name) for name in PROFILE_FIELD_ORDER))

    @cached_property
    def _cached_hash(self):
        return hash(self._cache_key)

    def __hash__(self):
        return self._cached_hash

    def __eq__(self, other):
        return isinstance(other, ProfileValues) and self._cache_key == other._cache_key


PROFILE_FIELD_ORDER = tuple(item.name for item in fields(ProfileValues))
PROFILE_FIELDS = frozenset(PROFILE_FIELD_ORDER)


@lru_cache(maxsize=2048)
def _intern_profile_values(key):
    """Bounded sharing of validated immutable values, preserving wire types.

    Sparse names distinguish absent fields. Float hex tokens distinguish -0.0
    from 0.0 as well as retaining their exact binary values. Returned records
    remain fresh dictionaries; mutable/subclass values bypass this cache.
    """
    return ProfileValues(**{name: float.fromhex(value) if kind is float else value
                            for name, kind, value in key})

HUMAN_PROFILE = ProfileValues(base_speed=2.0, base_sense_r=40.0, movement_cost=.10, rest_rate=4.0, base_damage_resistance=0.0, max_life=100, max_stamina=100.0, hunger_rate=.05, combat_skill=.35, melee_damage=16, medical_skill=.20, infection_resistance=.20, carry_capacity=10)
ZOMBIE_PROFILE = ProfileValues(base_speed=1.6, base_sense_r=35.0, movement_cost=.08, rest_rate=3.0, base_damage_resistance=0.0, max_life=100, max_stamina=100.0, attack_skill=.40, virulence=.45, claw_damage=14, bite_damage=6, feed_healing=8, feed_energy=12.0)


@dataclass(frozen=True)
class EffectiveProfile:
    source: ProfileValues
    speed: float
    sense_r: float
    damage_resistance: float
    rally_bonus: float = 0.0
    infection_resistance_effective: float | None = None

    def to_record(self):
        result = self.source.to_record()
        result.update(speed=self.speed, sense_r=self.sense_r, damage_resistance=self.damage_resistance, rally_bonus=self.rally_bonus)
        if self.infection_resistance_effective is not None:
            result["infection_resistance_effective"] = self.infection_resistance_effective
        return result


@lru_cache(maxsize=4096)
def _resolve_sources(biological_type, role_definition, type_profile, role_profile, individual_profile, carry_capacity):
    values = HUMAN_PROFILE if biological_type == "Human" else ZOMBIE_PROFILE
    if type_profile is not None:
        values = values.overlay(type_profile)
    if role_definition is not None:
        values = values.overlay(role_definition.parameters)
    if role_profile is not None:
        values = values.overlay(role_profile)
    if individual_profile is not None:
        values = values.overlay(individual_profile)
    if biological_type == "Human" and carry_capacity is not None:
        values = replace(values, carry_capacity=carry_capacity)
    return values


class ProfileResolver:
    """Apply type, role, individual and timed modifiers in semantic order."""

    @staticmethod
    def resolve(biological_type, life, role_definition=None, *, type_profile=None,
                role_profile=None, individual_profile=None, carry_capacity=None,
                effects=(), at=None, current_action=None):
        values = _resolve_sources(biological_type, role_definition, type_profile, role_profile, individual_profile, carry_capacity)
        speed, sense, resistance = values.base_speed, values.base_sense_r, values.base_damage_resistance
        infection = values.infection_resistance if biological_type == "Human" else None
        rally = 0.0
        role_id = role_definition.role_id if role_definition else None
        for effect in effects:
            if not effect.applies_at(at):
                continue
            if effect.kind == "guard" and role_id == "WARRIOR":
                resistance = max(resistance, float(effect.magnitude(.6, "resistance")))
            elif effect.kind == "recon" and role_id == "SCOUT":
                sense = max(sense, float(effect.magnitude(85, "radius")))
            elif effect.kind == "prophylaxis" and biological_type == "Human":
                infection = max(infection, float(effect.magnitude(.8, "resistance")))
            elif effect.kind in {"rally", "rallied"} and biological_type == "Zombie":
                rally = max(rally, float(effect.magnitude(.1, "hit_bonus")))
        if role_id == "RUNNER" and current_action == "dash":
            speed *= values.dash_multiplier
        if life == 0:
            speed = sense = 0.0
        return EffectiveProfile(values, speed, sense, resistance, rally, infection)
