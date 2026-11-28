"""Small immutable ordered map used by dated world snapshots.

Two radix trees share unchanged branches: one indexes keys, one preserves their
insertion order. A commit copies O(log n) nodes per changed entity, never the
whole accumulated occurrence history. Values must themselves be immutable.
"""
from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib


@dataclass(frozen=True, slots=True)
class _Node:
    children: tuple = ()
    entries: tuple = ()


def _lookup(node, digits, key, depth=0):
    if depth == len(digits):
        return next((entry for entry in node.entries if entry[0] == key), None)
    child = next((n for d, n in node.children if d == digits[depth]), None)
    return None if child is None else _lookup(child, digits, key, depth + 1)


def _replace(node, digits, key, entry, depth=0):
    if depth == len(digits):
        entries = tuple(e for e in node.entries if e[0] != key)
        return _Node(node.children, entries + (() if entry is None else (entry,)))
    digit = digits[depth]
    children = dict(node.children)
    child = _replace(children.get(digit, _Node()), digits, key, entry, depth + 1)
    if child.children or child.entries:
        children[digit] = child
    else:
        children.pop(digit, None)
    return _Node(tuple(sorted(children.items())), node.entries)


def _walk(node):
    yield from node.entries
    for _, child in node.children:
        yield from _walk(child)


def _digits(key):
    # Four bytes suffice for indexing; leaf equality handles hash collisions.
    digest = hashlib.blake2s(str(key).encode(), digest_size=4).digest()
    return tuple(n for byte in digest for n in (byte >> 4, byte & 15))


def _order_digits(index):
    return tuple((index >> shift) & 15 for shift in range(60, -1, -4))


@dataclass(frozen=True)
class PersistentMap(Mapping):
    _keys: _Node = _Node()
    _order: _Node = _Node()
    _size: int = 0
    _next: int = 0

    def __len__(self):
        return self._size

    def __iter__(self):
        return (entry[0] for entry in _walk(self._order))

    def __getitem__(self, key):
        entry = _lookup(self._keys, _digits(key), key)
        if entry is None:
            raise KeyError(key)
        return entry[2]

    def items(self):
        return ((entry[0], entry[2]) for entry in _walk(self._order))

    def values(self):
        return (entry[2] for entry in _walk(self._order))

    def set(self, key, value):
        previous = _lookup(self._keys, _digits(key), key)
        order = previous[1] if previous is not None else self._next
        entry = (key, order, value)
        return PersistentMap(_replace(self._keys, _digits(key), key, entry),
                             _replace(self._order, _order_digits(order), key, entry),
                             self._size + int(previous is None),
                             self._next + int(previous is None))

    def remove(self, key):
        previous = _lookup(self._keys, _digits(key), key)
        if previous is None:
            return self
        return PersistentMap(_replace(self._keys, _digits(key), key, None),
                             _replace(self._order, _order_digits(previous[1]), key, None),
                             self._size - 1, self._next)

    @classmethod
    def from_items(cls, items):
        result = cls()
        for key, value in items:
            result = result.set(key, value)
        return result
