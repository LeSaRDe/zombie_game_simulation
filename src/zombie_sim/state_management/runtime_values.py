"""Immutable continuation cells and branch-local copy-on-write containers.

Private model memory is intentionally opaque: exact restart codecs are decided
at the persistence boundary, not by this ownership layer. Opaque objects are
copied when imported or accessed by a writable branch; untouched cells are
shared by snapshots without inspecting or serializing their contents.
"""
from __future__ import annotations

from collections.abc import ItemsView, KeysView, Mapping, MutableMapping, ValuesView
from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
import math
from pathlib import Path, PosixPath, PurePath, PurePosixPath, PureWindowsPath, WindowsPath
from types import MappingProxyType


@dataclass(frozen=True)
class MappingCell:
    entries: object


@dataclass(frozen=True)
class SequenceCell:
    entries: tuple
    kind: type


@dataclass(frozen=True)
class OpaqueCell:
    _owned: object


IMMUTABLE_SCALARS = frozenset((type(None), str, bool, int, float, Fraction,
                              PurePath, Path, PurePosixPath, PureWindowsPath, PosixPath, WindowsPath))


class _NonStructuralValue(Exception):
    """A model value needs deepcopy graph semantics, not tree normalization."""


def immutable_key(value):
    if type(value) in IMMUTABLE_SCALARS:
        return True
    return type(value) in (tuple, frozenset) and all(immutable_key(item) for item in value)


def _same_key(left, right):
    """Compare retained representation, including numeric types and path case."""
    if left is right:
        return True
    if type(left) is not type(right):
        return False
    if type(left) is float:
        return _same_float(left, right)
    if isinstance(left, PurePath):
        # Windows paths compare case-insensitively, but model memory must keep
        # the spelling that was actually assigned, including after reinsertion.
        return str(left) == str(right)
    if type(left) is tuple:
        return len(left) == len(right) and all(_same_key(a, b) for a, b in zip(left, right))
    if type(left) is frozenset:
        return len(left) == len(right) and all(any(_same_key(a, b) for b in right) for a in left)
    return left == right


def _same_float(left, right):
    # Retain the previous nonfinite comparison behavior, including NaN != NaN.
    # Finite signed zero must remain distinct at the serialization boundary.
    return (left.hex() == right.hex() if math.isfinite(left) and math.isfinite(right)
            else left == right)


def same_cell(left, right):
    if left is right:
        return True
    if type(left) is float and type(right) is float:
        return _same_float(left, right)
    if isinstance(left, SequenceCell) and isinstance(right, SequenceCell):
        if left.kind in (set, frozenset) and left.kind is right.kind:
            return len(left.entries) == len(right.entries) and all(
                any(same_cell(a, b) for b in right.entries) for a in left.entries)
        return left.kind is right.kind and len(left.entries) == len(right.entries) and all(
            same_cell(a, b) for a, b in zip(left.entries, right.entries))
    if isinstance(left, MappingCell) and isinstance(right, MappingCell):
        return len(left.entries) == len(right.entries) and all(
            _same_key(a, b) for a, b in zip(left.entries, right.entries)) and all(
            same_cell(value, right.entries[key]) for key, value in left.entries.items())
    return type(left) is type(right) and type(left) in IMMUTABLE_SCALARS and _same_key(left, right)


def _freeze_tree(value, seen):
    """Freeze exact built-in trees; never erase a custom type or graph alias."""
    if type(value) in IMMUTABLE_SCALARS:
        return value
    from ..domain_model import ScheduledTask
    if type(value) is ScheduledTask:
        return value
    if type(value) in (tuple, frozenset) and immutable_key(value):
        return SequenceCell(tuple(_freeze_tree(item, seen) for item in value), type(value))
    if id(value) in seen:
        raise _NonStructuralValue()
    seen.add(id(value))
    if type(value) is dict or type(value) is CowDict:
        if any(not immutable_key(key) for key in value):
            raise _NonStructuralValue()
        cell = MappingCell(MappingProxyType({key: _freeze_tree(item, seen) for key, item in value.items()}))
    elif type(value) in (list, tuple, set, frozenset, CowList):
        kind = list if type(value) is CowList else type(value)
        cell = SequenceCell(tuple(_freeze_tree(item, seen) for item in value), kind)
    else:
        raise _NonStructuralValue()
    if type(value) in (CowDict, CowList) and same_cell(cell, value._base):
        return value._base
    return cell


def freeze(value):
    if type(value) in (CowDict, CowList):
        return value.seal()
    try:
        return _freeze_tree(value, set())
    except _NonStructuralValue:
        return OpaqueCell(deepcopy(value))


def materialize(cell):
    """Detached legacy values, preserving list/tuple/set distinctions exactly."""
    if isinstance(cell, MappingCell):
        return {deepcopy(key): materialize(value) for key, value in cell.entries.items()}
    if isinstance(cell, SequenceCell):
        return cell.kind(materialize(value) for value in cell.entries)
    if isinstance(cell, OpaqueCell):
        return deepcopy(cell._owned)
    return cell


def writable(cell):
    if isinstance(cell, MappingCell):
        return CowDict(cell)
    if isinstance(cell, SequenceCell) and cell.kind is list:
        return CowList(cell)
    if isinstance(cell, SequenceCell):
        return cell.kind(writable(value) for value in cell.entries)
    if isinstance(cell, OpaqueCell):
        return deepcopy(cell._owned)
    return cell


class CowDict(MutableMapping):
    """A mutable branch over an immutable mapping cell.

    Cached children belong only to this branch. Sealing recursively freezes
    accessed children, reusing every unchanged cell and retaining no aliases to
    caller-owned mutable values. It deliberately is not a dict subclass: Python
    JSON encoders can bypass overridden dict methods and silently lose values.
    Export and plugin boundaries materialize ordinary dictionaries explicitly.
    """

    def __init__(self, cell, *, partitioned=False):
        self._base = cell
        self._partitioned = partitioned
        self._cache = {}
        self._deleted = set()
        self._added = {}

    @classmethod
    def own(cls, value):
        if not isinstance(value, Mapping):
            raise TypeError('Declared runtime config/memories must be mappings')
        if any(not immutable_key(key) for key in value):
            raise TypeError('Declared runtime owner keys must be immutable')
        # Only the declared outer owner map is normalized. Each private memory
        # remains its own deepcopy/COW isolation unit, including richer graphs.
        cell = value.seal() if type(value) is cls and value._partitioned else MappingCell(
            MappingProxyType({key: freeze(item) for key, item in value.items()}))
        return cls(cell, partitioned=True)

    def __getitem__(self, key):
        if key in self._deleted:
            raise KeyError(key)
        if key in self._cache:
            return self._cache[key]
        cell = self._base.entries[key]
        value = writable(cell)
        if isinstance(cell, (MappingCell, SequenceCell, OpaqueCell)):
            self._cache[key] = value
        return value

    def __setitem__(self, key, value):
        if self._partitioned and not immutable_key(key):
            raise TypeError('Declared runtime owner keys must be immutable')
        if key not in self:
            self._added[key] = None
        self._deleted.discard(key)
        # Owner-map assignment detaches an incoming model value. Within an
        # already isolated value, normal Python assignment preserves aliases;
        # sealing then copies any richer graph as one opaque ownership unit.
        self._cache[key] = writable(freeze(value)) if self._partitioned else value

    def __delitem__(self, key):
        if key not in self:
            raise KeyError(key)
        self._cache.pop(key, None)
        self._deleted.add(key)
        self._added.pop(key, None)

    def __iter__(self):
        yield from (key for key in self._base.entries if key not in self._deleted and key not in self._added)
        yield from self._added

    def __reversed__(self):
        return reversed(tuple(self))

    def __len__(self):
        return sum(1 for _ in self)

    def __contains__(self, key):
        return key not in self._deleted and (key in self._cache or key in self._base.entries)

    def get(self, key, default=None):
        return self[key] if key in self else default

    def keys(self):
        return KeysView(self)

    def items(self):
        return ItemsView(self)

    def values(self):
        return ValuesView(self)

    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
        return self[key]

    def pop(self, key, *default):
        if len(default) > 1:
            raise TypeError(f'pop expected at most 2 arguments, got {len(default) + 1}')
        if key not in self:
            if default:
                return default[0]
            raise KeyError(key)
        value = self[key]
        del self[key]
        return value

    def popitem(self):
        if not self:
            raise KeyError('popitem(): dictionary is empty')
        key = next(reversed(list(self)))
        return key, self.pop(key)

    def update(self, other=(), **kwargs):
        for key, value in (other.items() if hasattr(other, 'items') else other):
            self[key] = value
        for key, value in kwargs.items():
            self[key] = value

    def clear(self):
        self._cache.clear()
        self._deleted = set(self._base.entries)
        self._added.clear()

    def copy(self):
        return {key: self[key] for key in self}

    def to_dict(self):
        return materialize(self.seal())

    def __deepcopy__(self, memo):
        result = {}
        memo[id(self)] = result
        for key, value in self.items():
            result[deepcopy(key, memo)] = deepcopy(value, memo)
        return result

    def __eq__(self, other):
        return isinstance(other, Mapping) and len(self) == len(other) and all(key in other and self[key] == other[key] for key in self)

    def __ne__(self, other):
        return not self == other

    def __repr__(self):
        return repr(self.copy())

    def __or__(self, other):
        result = self.copy(); result.update(other); return result

    def __ror__(self, other):
        result = dict(other); result.update(self); return result

    def __ior__(self, other):
        self.update(other); return self

    def seal(self):
        if not self._partitioned:
            try:
                cell = _freeze_tree(self, set())
            except _NonStructuralValue:
                return OpaqueCell(deepcopy(self))
            self._base = cell
            self._deleted.clear()
            self._added.clear()
            return cell
        changes = {}
        for key, value in self._cache.items():
            cell = freeze(value)
            if key not in self._base.entries or not same_cell(cell, self._base.entries[key]):
                changes[key] = cell
        if self._deleted or self._added or changes:
            entries = {key: changes[key] if key in changes else self._base.entries[key] for key in self}
            self._base = MappingCell(MappingProxyType(entries))
            self._deleted.clear()
            self._added.clear()
        return self._base

    def cell_tokens(self):
        """Stable identities for journal change detection without memory reads."""
        return self.seal().entries


class CowList(list):
    """A concrete list branch; nested children retain their shared cells."""

    def __init__(self, cell):
        super().__init__(writable(value) for value in cell.entries)
        self._base = cell

    def seal(self):
        try:
            cell = _freeze_tree(self, set())
        except _NonStructuralValue:
            return OpaqueCell(deepcopy(self))
        self._base = cell
        return cell

    def __deepcopy__(self, memo):
        result = []
        memo[id(self)] = result
        result.extend(deepcopy(value, memo) for value in self)
        return result
