"""Typed, detached views over the framework's stable JSON record format.

Identity, biological state, role and model assignment are separate concepts.
These objects never hold a live coordinator or expose a mutable state record.
Use ``to_record()`` at process, history and HTTP boundaries.
"""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
import math
from types import MappingProxyType
from typing import Any


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("Record keys must be strings")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise TypeError("Records accept only finite JSON values (and tuple sequences)")


def _record(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _record(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_record(item) for item in value]
    return deepcopy(value)


@dataclass(frozen=True, order=True)
class ExactTime:
    """Nonnegative rational seconds; display rounding is a separate concern."""

    value: Fraction

    def __post_init__(self) -> None:
        if isinstance(self.value, bool):
            raise ValueError("A Boolean is not a simulation time")
        value = self.value.value if isinstance(self.value, ExactTime) else Fraction(str(self.value))
        if value < 0:
            raise ValueError("Simulation time must be nonnegative")
        object.__setattr__(self, "value", value)

    @classmethod
    def parse(cls, value: Any) -> ExactTime:
        return value if isinstance(value, cls) else cls(value)

    def __str__(self) -> str:
        return str(self.value)

    def __float__(self) -> float:
        """Approximate plotting coordinate, never an authoritative cursor."""
        return float(self.value)

    def plus(self, duration: Any) -> ExactTime:
        return ExactTime(self.value + ExactTime.parse(duration).value)


@dataclass(frozen=True)
class HistoryCursor:
    run_id: str
    time: ExactTime
    revision: int

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id:
            raise ValueError("A history cursor requires a run identity")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 0:
            raise ValueError("A history revision must be a nonnegative integer")
        object.__setattr__(self, "time", ExactTime.parse(self.time))

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> HistoryCursor:
        revision = record["revision"]
        if isinstance(revision, bool) or not str(revision).isdigit():
            raise ValueError("A history revision must be a nonnegative integer")
        return cls(str(record["run_id"]), ExactTime.parse(record["time"]), int(revision))

    def to_record(self) -> dict[str, str]:
        return {"run_id": self.run_id, "time": str(self.time), "revision": str(self.revision)}


@dataclass(frozen=True)
class AgentIdentity:
    run_id: str
    agent_id: str


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True, init=False)
class FrozenRecord(Mapping[str, Any]):
    """Read-only nested record with explicit, detached serialization."""

    _data: Mapping[str, Any]

    def __init__(self, record: Mapping[str, Any]):
        if not isinstance(record, Mapping):
            raise TypeError("A record must be a mapping")
        object.__setattr__(self, "_data", _freeze(record))

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def to_record(self) -> dict[str, Any]:
        return _record(self._data)


@dataclass(frozen=True, init=False)
class AgentView(FrozenRecord):
    _run_id: str

    def __init__(self, record: Mapping[str, Any], run_id: str = ""):
        super().__init__(record)
        object.__setattr__(self, "_run_id", run_id)

    @property
    def agent_id(self) -> str:
        return str(self["id"])

    @property
    def identity(self) -> AgentIdentity | None:
        """Run-scoped identity for researcher views; local observations omit it."""
        return AgentIdentity(self._run_id, self.agent_id) if self._run_id else None

    @property
    def biological_type(self) -> str:
        return self["type"]

    @property
    def role(self) -> str | None:
        return self.get("role")

    @property
    def alive(self) -> bool:
        return self["life"] > 0

    @property
    def position(self) -> Point:
        return Point(float(self["x"]), float(self["y"]))

    @property
    def model_assignment(self) -> Mapping[str, Any] | str | None:
        return self.get("model_assignment")


class WorldView(FrozenRecord):
    """A researcher snapshot; never pass this object to a decision model."""

    @property
    def cursor(self) -> HistoryCursor:
        return HistoryCursor.from_record(self)

    @property
    def agents(self) -> Mapping[str, AgentView]:
        return MappingProxyType({str(key): AgentView(agent, self.get("run_id", ""))
                                 for key, agent in self.get("agents", {}).items()})

    def agent(self, identity: str | int) -> AgentView:
        return AgentView(self["agents"][str(identity)], self.get("run_id", ""))


class ObservationView(FrozenRecord):
    """Only the engine-supplied local observation, with no global lookup port."""

    @property
    def time(self) -> ExactTime:
        return ExactTime.parse(self["time"])

    @property
    def self_state(self) -> AgentView:
        return AgentView(self["self_state"])

    @property
    def visible_agents(self) -> Mapping[str, AgentView]:
        return MappingProxyType({str(key): AgentView(agent)
                                 for key, agent in self.get("local_agents", {}).items()})

    @property
    def environment(self) -> Mapping[str, Any]:
        return self.get("local_environment", MappingProxyType({}))


@dataclass(frozen=True)
class ActionIntent:
    action: str
    target: str | int | None = None
    parameters: Mapping[str, Any] | None = None
    actor: str | int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action, str) or not self.action:
            raise ValueError("An intent requires an action name")
        if self.parameters is not None and not isinstance(self.parameters, Mapping):
            raise TypeError("Action parameters must be a mapping")
        object.__setattr__(self, "parameters", _freeze(self.parameters or {}))

    def to_record(self) -> dict[str, Any]:
        value = {"action": self.action, "parameters": _record(self.parameters)}
        if self.target is not None:
            value["target"] = self.target
        if self.actor is not None:
            value["actor"] = self.actor
        return value


@dataclass(frozen=True)
class Decision:
    intent: ActionIntent
    memory: Any = None
    diagnostics: Mapping[str, Any] | None = None

    def to_result(self) -> tuple[dict[str, Any], Any, dict[str, Any]]:
        return self.intent.to_record(), deepcopy(self.memory), _record(self.diagnostics or {})
