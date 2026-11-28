"""Typed world ownership and explicit transactions independent of storage."""
from .world import WorldAggregate, WorldReadView, WorldDraft, StateChange
from .persistent import PersistentMap
from .runtime_state import RuntimeState, RuntimeSnapshot, install_runtime_fields
from .coordinator import StateCoordinator, UnitOfWork, StalePlan
