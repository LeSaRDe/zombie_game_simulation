"""Declarative codecs for named dataclass fields, with strict schema boundaries."""
from dataclasses import dataclass, field, fields
from functools import lru_cache
from typing import ClassVar
from .values import check_fields, encode


@lru_cache(maxsize=None)
def _schema(cls):
    """Class metadata is stable; record values remain independently owned."""
    return tuple((item.name, cls.aliases.get(item.name, item.name))
                 for item in fields(cls) if not item.name.startswith('_'))


@lru_cache(maxsize=None)
def _wire_names(cls):
    return {wire: name for name, wire in _schema(cls)}


@dataclass(frozen=True, kw_only=True)
class RecordValue:
    _present: frozenset[str] = field(default_factory=frozenset, repr=False)
    aliases: ClassVar[dict[str, str]] = {}
    decoders: ClassVar[dict] = {}

    @classmethod
    def from_record(cls, record, **_):
        wire_names = _wire_names(cls)
        present = check_fields(record, wire_names, cls.__name__)
        values = {}
        for wire, value in record.items():
            name = wire_names[wire]
            decoder = cls.decoders.get(name)
            values[name] = decoder(value) if decoder and value is not None else value
        return cls(**values, _present=present)

    def to_record(self):
        result = {}
        for name, wire in _schema(type(self)):
            if wire in self._present:
                result[wire] = encode(getattr(self, name))
        return result
