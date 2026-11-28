"""Authoritative typed world and isolated copy-on-read rule drafts.

The draft dictionaries are local arithmetic/codec workspaces. They never alias
committed entities; a finished plan contains immutable typed replacements.
"""
from __future__ import annotations
from collections.abc import Mapping, MutableMapping
from copy import deepcopy
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from ..domain_model import Agent, RoleRegistry
from ..domain_model.values import JsonObject, AgentIdentity
from .persistent import PersistentMap
from .spatial import SpatialIndex

COLLECTIONS = ('agents', 'barriers', 'shelters', 'stockpiles', 'remains',
               'episodes', 'signals', 'reservations', 'interventions',
               'intents', 'occurrences')


def _decode(collection, record, run_id, roles):
    from ..domain_model import DomainCodec
    return DomainCodec(roles=roles).decode_entity(collection, record, run_id)


def _encode(entity):
    return entity.to_record()


@dataclass(frozen=True)
class StateChange:
    collection: str
    identity: str
    value: object | None
    reinserted: bool = False


@dataclass(frozen=True)
class WorldAggregate:
    """One immutable committed revision; only UnitOfWork publishes a successor."""

    metadata: JsonObject
    collections: Mapping[str, PersistentMap]
    roles: RoleRegistry = field(repr=False, compare=False)
    reservations_by_holder: PersistentMap = field(default_factory=PersistentMap, repr=False, compare=False)
    spatial_index: SpatialIndex = field(default_factory=SpatialIndex, repr=False, compare=False)

    def metadata_value(self, name, default=None):
        # Scalar cursor reads never thaw the potentially large provenance payload.
        return next((value for key,value in self.metadata.entries if key==name),default)

    @classmethod
    def from_record(cls, record, *, roles=None):
        roles = roles or RoleRegistry.default()
        run_id = record.get('run_id', 'detached-world')
        collections = {name: PersistentMap.from_items(
            (str(key), _decode(name, value, run_id, roles))
            for key, value in record.get(name, {}).items()) for name in COLLECTIONS}
        index=PersistentMap()
        for identity,reservation in collections['reservations'].items():
            key=(reservation.collection,reservation.holder)
            index=index.set(key,(*index.get(key,()),identity))
        return cls(JsonObject.from_record({k: v for k, v in record.items() if k not in COLLECTIONS}),
                   MappingProxyType(collections), roles,index,
                   SpatialIndex.build(collections['agents'], collections['occurrences']))

    @property
    def revision(self):
        return int(self.metadata_value('revision',0))

    @property
    def run_id(self):
        return self.metadata_value('run_id','detached-world')

    def agent(self, identity):
        return self.collections['agents'][str(identity)]

    def to_record(self):
        return {**self.metadata.to_record(), **{name: {key: _encode(value) for key, value in entries.items()}
                for name, entries in self.collections.items()}}

    def read_view(self):
        return WorldReadView(self)

    def with_changes(self, changes, *, time, revision, metadata=None):
        collections = dict(self.collections)
        index=self.reservations_by_holder
        for change in changes:
            table = collections[change.collection]
            if change.collection=='reservations':
                previous=table.get(change.identity)
                if previous is not None:
                    key=(previous.collection,previous.holder)
                    members=tuple(identity for identity in index.get(key,()) if identity!=change.identity)
                    index=index.set(key,members) if members else index.remove(key)
                if change.value is not None:
                    key=(change.value.collection,change.value.holder)
                    index=index.set(key,(*index.get(key,()),change.identity))
            if change.reinserted:table=table.remove(change.identity)
            collections[change.collection] = (table.remove(change.identity) if change.value is None
                                               else table.set(change.identity, change.value))
        values = self.metadata.to_record()
        values.update(metadata or {})
        values.update(time=str(time), revision=int(revision))
        if values.get('run_id',self.run_id)!=self.run_id:
            # Branching changes the scope of current identities, never old views.
            run_id=values['run_id']
            collections['agents']=PersistentMap.from_items(
                (identity,replace(agent,identity=AgentIdentity(run_id,identity)))
                for identity,agent in collections['agents'].items())
        spatial = self.spatial_index
        for change in changes:
            if change.collection == 'agents':
                spatial = (spatial.with_typed_agent(change.value, collections['occurrences']) if change.value is not None
                           else spatial.with_agent(change.identity, None))
        return WorldAggregate(JsonObject.from_record(values), MappingProxyType(collections), self.roles,index,spatial)


class _RecordCollection(Mapping):
    def __init__(self, entries):
        self.entries = entries

    def __len__(self): return len(self.entries)
    def __iter__(self): return iter(self.entries)
    def __getitem__(self, key): return _encode(self.entries[str(key)])
    def values(self): return (_encode(value) for value in self.entries.values())
    def items(self): return ((key, _encode(value)) for key, value in self.entries.items())
    def __deepcopy__(self, memo): return dict(self.items())


class WorldReadView(Mapping):
    """Dated typed ownership plus detached compatibility records on demand."""
    def __init__(self, world):
        self.world = world
        self._metadata = world.metadata.to_record()

    @property
    def revision(self): return self.world.revision
    def agent(self, identity): return self.world.agent(identity)
    def __len__(self): return len(self._metadata) + len(self.world.collections)
    def __iter__(self): return iter((*self._metadata, *self.world.collections))
    def __getitem__(self, key):
        return (_RecordCollection(self.world.collections[key]) if key in self.world.collections
                else deepcopy(self._metadata[key]))
    def __deepcopy__(self, memo): return self.world.to_record()
    def to_record(self): return self.world.to_record()


class _DraftCollection(MutableMapping):
    def __init__(self, source):
        self.source = source
        self.drafts = {}
        self.baselines = {}
        self.removed = set()
        self.reinserted = set()

    def __getitem__(self, key):
        key = str(key)
        if key in self.removed: raise KeyError(key)
        if key not in self.drafts:
            self.baselines[key] = _encode(self.source[key])
            self.drafts[key] = deepcopy(self.baselines[key])
        return self.drafts[key]

    def __contains__(self, key):
        key = str(key)
        return key not in self.removed and (key in self.drafts or key in self.source)

    def __setitem__(self, key, value):
        key = str(key)
        if key in self.removed and key in self.source:self.reinserted.add(key)
        self.removed.discard(key)
        # Insertions join this transaction-local workspace. Rule code may retain
        # the record and finish its evidence after inserting it; committed source
        # records are still decoded into detached drafts on the first read.
        self.drafts[key] = value

    def __delitem__(self, key):
        key = str(key)
        if key not in self: raise KeyError(key)
        self.removed.add(key)
        self.drafts.pop(key, None)

    def __iter__(self):
        yield from (key for key in self.source if key not in self.removed and key not in self.reinserted)
        yield from (key for key in self.drafts if (key not in self.source or key in self.reinserted) and key not in self.removed)

    def __len__(self):
        return len(self.source) - sum(key in self.source for key in self.removed) + sum(key not in self.source for key in self.drafts)

    def __deepcopy__(self, memo): return {key: deepcopy(self[key], memo) for key in self}


class WorldDraft(MutableMapping):
    """Transaction-local overlay; reads see preceding staged rule changes."""
    def __init__(self, view):
        self.base = view.world
        self.metadata = self.base.metadata.to_record()
        self.tables = {name: _DraftCollection(table) for name, table in self.base.collections.items()}

    def __getitem__(self, key): return self.tables[key] if key in self.tables else self.metadata[key]
    def __setitem__(self, key, value):
        if key in COLLECTIONS:
            table = _DraftCollection(PersistentMap())
            for identity, record in value.items(): table[identity] = record
            # Replacing a collection also replaces its observable iteration
            # order, including keys already present in the committed world.
            table.reinserted = set(table.drafts) & set(self.base.collections[key])
            self.tables[key] = table
        else: self.metadata[key] = deepcopy(value)
    def __delitem__(self, key): del self.metadata[key]
    def __iter__(self): return iter((*self.metadata, *self.tables))
    def __len__(self): return len(self.metadata) + len(self.tables)
    def __deepcopy__(self, memo): return {key: deepcopy(self[key], memo) for key in self}

    def fork(self):
        """Copy only materialized drafts; immutable committed branches are shared."""
        child=object.__new__(WorldDraft)
        child.base=self.base
        child.metadata=deepcopy(self.metadata)
        child.tables={}
        for name,table in self.tables.items():
            duplicate=_DraftCollection(table.source)
            duplicate.drafts=deepcopy(table.drafts)
            # Baselines are private detached records, never exposed or mutated.
            duplicate.baselines=dict(table.baselines)
            duplicate.removed=set(table.removed)
            duplicate.reinserted=set(table.reinserted)
            child.tables[name]=duplicate
        return child

    def metadata_changes(self):
        before=self.base.metadata.to_record()
        if set(before)-set(self.metadata):
            raise ValueError('World metadata deletion requires an explicit schema migration')
        return {key:deepcopy(value) for key,value in self.metadata.items()
                if key not in {'time','revision'} and (key not in before or value!=before[key])}

    def changed_keys(self):
        result=set()
        for collection,table in self.tables.items():
            for key in table.removed:
                if key in table.source:result.add((collection,key))
            for key,record in table.drafts.items():
                if key not in table.source or key in table.reinserted:
                    result.add((collection,key))
                else:
                    if key not in table.baselines:
                        table.baselines[key] = _encode(table.source[key])
                    if record != table.baselines[key]:
                        result.add((collection,key))
            # Whole-collection replacement may remove otherwise untouched keys.
            if table.source is not self.base.collections[collection]:
                result.update((collection,key) for key in self.base.collections[collection] if key not in table)
        return result

    def changes(self, dirty=()):
        changes = []
        candidates=set(dirty)|self.changed_keys()
        by_collection={}
        for collection,key in candidates:
            by_collection.setdefault(collection,set()).add(key)
        ordered=[]
        for collection,table in self.tables.items():
            keys=by_collection.get(collection)
            if not keys:continue
            existing=sorted(key for key in keys if key in table.source and key not in table.reinserted)
            additions=[key for key in table.drafts if key in keys and key not in table.removed and (key not in table.source or key in table.reinserted)]
            missing=sorted(key for key in keys if key not in table and key not in existing)
            ordered.extend((collection,key) for key in (*existing,*missing,*additions))
        for collection, key in ordered:
            table = self.tables[collection]
            value = (_decode(collection, table[key], self.metadata['run_id'], self.base.roles)
                     if key in table else None)
            changes.append(StateChange(collection, key, value,key in table.reinserted))
        return tuple(changes)
