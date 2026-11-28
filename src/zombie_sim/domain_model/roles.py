"""Role inheritance models capability specialization independently of identity."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache
from typing import ClassVar
from .profiles import ProfileValues
from .values import CodecError, ExactTime, number


@dataclass(frozen=True)
class RoleDefinition(ABC):
    parameters: ProfileValues
    actions: tuple[str, ...]
    version: str = "baseline_v0.1"
    role_id: ClassVar[str]

    @property
    @abstractmethod
    def compatible_type(self) -> str: ...

    def grants(self, action: str) -> bool:
        return action in self.actions


@dataclass(frozen=True)
class HumanRoleDefinition(RoleDefinition):
    @property
    def compatible_type(self):
        return "Human"


@dataclass(frozen=True)
class ZombieRoleDefinition(RoleDefinition):
    @property
    def compatible_type(self):
        return "Zombie"


@dataclass(frozen=True)
class DoctorRole(HumanRoleDefinition):
    role_id = "DOCTOR"


@dataclass(frozen=True)
class WarriorRole(HumanRoleDefinition):
    role_id = "WARRIOR"


@dataclass(frozen=True)
class ScoutRole(HumanRoleDefinition):
    role_id = "SCOUT"


@dataclass(frozen=True)
class EngineerRole(HumanRoleDefinition):
    role_id = "ENGINEER"


@dataclass(frozen=True)
class TyrantRole(ZombieRoleDefinition):
    role_id = "TYRANT"


@dataclass(frozen=True)
class RunnerRole(ZombieRoleDefinition):
    role_id = "RUNNER"


@dataclass(frozen=True)
class SpitterRole(ZombieRoleDefinition):
    role_id = "SPITTER"


@dataclass(frozen=True)
class ScreamerRole(ZombieRoleDefinition):
    role_id = "SCREAMER"


ROLE_CLASSES = (DoctorRole, WarriorRole, ScoutRole, EngineerRole, TyrantRole, RunnerRole, SpitterRole, ScreamerRole)


@dataclass(frozen=True)
class RoleRegistry:
    definitions: tuple[RoleDefinition, ...]
    human_actions: tuple[str, ...]
    zombie_actions: tuple[str, ...]

    def __post_init__(self):
        identifiers = [item.role_id for item in self.definitions]
        if len(identifiers) != len(set(identifiers)):
            raise CodecError("Role registry contains duplicate identifiers")

    @classmethod
    def from_catalog(cls, catalog):
        definitions = []
        for implementation in ROLE_CLASSES:
            source = catalog.roles[implementation.role_id]
            parameters = {key: value for key, value in source.items() if key not in {"type", "actions", "registry_version", "label"}}
            role = implementation(ProfileValues.from_record(parameters), tuple(source["actions"]), source.get("registry_version", "baseline_v0.1"))
            if role.compatible_type != source["type"]:
                raise CodecError(f"{role.role_id}: incompatible catalog role type")
            definitions.append(role)
        if set(catalog.roles) != {item.role_id for item in definitions}:
            raise CodecError("Register an explicit role implementation for each catalog role")
        return cls(tuple(definitions), tuple(catalog.type_actions["Human"]), tuple(catalog.type_actions["Zombie"]))

    @classmethod
    @lru_cache(maxsize=1)
    def default(cls):
        # Importing at the composition boundary keeps domain objects independent
        # of filesystem/catalog loading once their registry has been created.
        from ..registry import DEFAULT_CATALOG
        return cls.from_catalog(DEFAULT_CATALOG)

    def get(self, role_id):
        if role_id is None:
            return None
        for definition in self.definitions:
            if definition.role_id == role_id:
                return definition
        raise CodecError(f"Unknown role {role_id!r}")

    def type_capabilities(self, biological_type):
        if biological_type == "Human":
            return self.human_actions
        if biological_type == "Zombie":
            return self.zombie_actions
        raise CodecError(f"Unknown biological type {biological_type!r}")


@dataclass(frozen=True)
class RoleAssignment:
    definition: RoleDefinition
    assigned_at: ExactTime | None = None
    retired_at: ExactTime | None = None
    state: SpitterRoleState | None = None


@dataclass(frozen=True)
class SpitterRoleState:
    charges: int
    reserved_charges: int = 0
    next_charge_at: ExactTime | None = None

    def __post_init__(self):
        number(self.charges, "spit_charges", integer=True)
        number(self.reserved_charges, "reserved_charges", maximum=self.charges, integer=True)
