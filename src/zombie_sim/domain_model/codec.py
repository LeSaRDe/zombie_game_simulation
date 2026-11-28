"""Versioned translation between typed values and the stable v1 world records."""
from .agents import Agent
from .activities import ActionIntent, ActionOccurrence
from .environment import Barrier, Shelter, Stockpile, Remains, InfectionEpisode, Signal, Reservation, Intervention, WorldBounds
from .roles import RoleRegistry
from .values import CodecError
from .events import DomainEvent


class DomainCodec:
    version = "domain-records-v1"

    def __init__(self, roles=None):
        self.roles = roles or RoleRegistry.default()

    def decode_entity(self, collection, record, run_id, *, trusted=False):
        if collection == "agents":
            return Agent.from_record(record, run_id, roles=self.roles, trusted=trusted)
        implementation = {"barriers": Barrier, "shelters": Shelter, "stockpiles": Stockpile, "remains": Remains,
                          "episodes": InfectionEpisode, "signals": Signal, "reservations": Reservation,
                          "interventions": Intervention, "intents": ActionIntent, "occurrences": ActionOccurrence,
                          "world": WorldBounds}.get(collection)
        if implementation is None:
            raise CodecError(f"Unknown world collection {collection!r}")
        return implementation.from_record(record)

    @staticmethod
    def encode_entity(entity):
        return entity.to_record()

    @staticmethod
    def decode_event(record):
        return DomainEvent.from_record(record)
