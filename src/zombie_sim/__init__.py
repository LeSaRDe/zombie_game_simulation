"""Ontology-based, event-driven zombie simulation."""
__version__ = "0.1.0"


def __getattr__(name):
    if name == "Simulation":
        from .engine import Simulation
        return Simulation
    raise AttributeError(name)
