"""Immutable value objects and lossless JSON boundary primitives.

Game objects hold named fields. Only explicitly opaque model/extension payloads
use JsonObject; a whole agent or world is never stored inside one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
import math
from typing import Any, Mapping


class CodecError(ValueError):
    """A record cannot be represented without losing or changing its meaning."""


def number(value: Any, name: str, minimum=0, maximum=None, *, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise CodecError(f"{name}: expected a finite number")
    if integer and not isinstance(value, int):
        raise CodecError(f"{name}: expected an integer")
    if value < minimum or (maximum is not None and value > maximum):
        raise CodecError(f"{name}: outside its allowed domain")
    return value


def check_fields(record: Mapping, allowed, name: str) -> frozenset[str]:
    if not isinstance(record, Mapping):
        raise CodecError(f"{name}: expected an object")
    unknown = set(record) - set(allowed)
    if unknown:
        raise CodecError(f"{name}: unsupported fields {sorted(unknown)!r}; register a named codec before importing them")
    return frozenset(record)


@dataclass(frozen=True)
class ExactTime:
    """Exact elapsed seconds, retaining the existing wire spelling on round trip."""

    value: Fraction
    _wire: str | int | float | None = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        raw = self.value
        try:
            if isinstance(raw, bool):
                raise ValueError()
            value = raw if isinstance(raw, Fraction) else Fraction(str(raw))
            if value < 0:
                raise ValueError()
        except (ValueError, TypeError, ZeroDivisionError, OverflowError) as error:
            raise CodecError("time: expected finite nonnegative exact seconds") from error
        object.__setattr__(self, "value", value)

    @classmethod
    def parse(cls, value):
        return value if isinstance(value, cls) else cls(value, value if isinstance(value, (str, int, float)) else None)

    def to_record(self):
        return self._wire if self._wire is not None else str(self.value)

    def __str__(self):
        return str(self.value)

    def __float__(self):
        return float(self.value)

    def plus(self, duration):
        return ExactTime(self.value + ExactTime.parse(duration).value)


def optional_time(value):
    return None if value is None else ExactTime.parse(value)


@dataclass(frozen=True)
class AgentIdentity:
    run_id: str
    agent_id: str

    def __post_init__(self):
        if not isinstance(self.run_id, str) or not self.run_id:
            raise CodecError("Agent identity requires a nonempty run ID")
        if not isinstance(self.agent_id, str) or not self.agent_id:
            raise CodecError("Agent identity requires a nonempty agent ID")


@dataclass(frozen=True)
class Point:
    x: float
    y: float

    def __post_init__(self):
        number(self.x, "x")
        number(self.y, "y")


@dataclass(frozen=True)
class JsonObject:
    """An explicitly opaque, recursively immutable JSON object at an API boundary."""

    entries: tuple[tuple[str, Any], ...] = ()

    @classmethod
    def from_record(cls, value):
        if not isinstance(value, Mapping) or any(not isinstance(k, str) for k in value):
            raise CodecError("JSON object requires string keys")
        return cls(tuple((key, freeze_json(item)) for key, item in value.items()))

    def to_record(self):
        return {key: thaw_json(value) for key, value in self.entries}


@dataclass(frozen=True)
class JsonArray:
    items: tuple[Any, ...]


def freeze_json(value):
    if isinstance(value, (JsonObject, JsonArray)):
        return value
    if isinstance(value, Mapping):
        return JsonObject.from_record(value)
    if isinstance(value, (list, tuple)):
        return JsonArray(tuple(freeze_json(item) for item in value))
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise CodecError(f"Unsupported JSON value: {type(value).__name__}")


def thaw_json(value):
    if isinstance(value, JsonObject):
        return value.to_record()
    if isinstance(value, JsonArray):
        return [thaw_json(item) for item in value.items]
    return value


def encode(value):
    if hasattr(value, "to_record"):
        return value.to_record()
    if isinstance(value, tuple):
        return [encode(item) for item in value]
    return thaw_json(value)
