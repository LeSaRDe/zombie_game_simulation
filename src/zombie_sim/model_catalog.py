"""Declarative configuration choices, separate from hash-pinned policy code.

Import register_model from this module to add optional friendly choice metadata.
The original policies.register_model API and all runtime policy code stay intact.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Callable

from . import policies

class ModelCatalog:
    """Own model factories and declarative choice metadata.

    A new catalog snapshots the installed factories into its own mapping. The
    explicit DEFAULT_MODEL_CATALOG shares the legacy process registry so existing
    configuration, worker startup and checkpoint lookup paths retain their API.
    Isolated catalogs are useful for inspecting/prototyping extensions; register
    in the default catalog to make a plugin available to ordinary simulations.
    """

    def __init__(self, factories=None):
        self.factories = dict(policies._REGISTRY) if factories is None else factories
        self.metadata: dict[str, tuple[Callable, dict]] = {}
        for _names,_factory,_label,_description in (
                (("defaultHuman/v1","defaultHuman","HumanDefaultModel"), policies.HumanDefaultModel,
                 "Default human utility policy", "Chooses observable actions using versioned survival, resource and cooperation preferences."),
                (("defaultZombie/v1","defaultZombie","ZombieDefaultModel"), policies.ZombieDefaultModel,
                 "Default zombie utility policy", "Chooses observable actions using versioned pursuit, recovery and cooperation preferences."),
                (("randomLegal/v1","randomLegal"), policies.RandomLegalModel,
                 "Random observable candidates", "Samples uniformly from observable candidate actions; the engine may still reject an action.")):
            for _name in _names:
                if self.factories.get(_name) is not _factory:
                    continue
                self.metadata[_name] = (_factory, {
                    "model_id": _factory.model_id, "label": _label, "version": _factory.version,
                    "applicable_types": list(_factory.applicable_types), "description": _description})

    def register(self, name: str, factory: Callable, *, replace: bool = False,
                       metadata: dict | None = None) -> None:
        """Register a factory and optional lightweight configuration-choice metadata.

        Metadata is declarative: registration and catalog reads never instantiate a
        policy. Existing two-argument plugins remain available by their registry name
        through the advanced editor. Replacing an alias drops its previous metadata
        unless the caller explicitly supplies a new declaration.
        """
        if not name or not callable(factory):
            raise ValueError("A model requires a nonempty name and callable factory")
        declaration = None
        if metadata is not None:
            if not isinstance(metadata, dict):
                raise ValueError("Model choice metadata must be an object")
            declaration = {}
            for key in ("model_id", "label", "version"):
                value = metadata.get(key)
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"Model choice metadata requires a nonempty {key}")
                declaration[key] = value
            types = metadata.get("applicable_types")
            if (not isinstance(types, (list, tuple)) or not types
                    or any(value not in ("Human", "Zombie") for value in types)
                    or len(set(types)) != len(types)):
                raise ValueError("Model choice metadata requires distinct Human/Zombie applicable_types")
            declaration["applicable_types"] = sorted(types)
            description = metadata.get("description", "")
            if not isinstance(description, str):
                raise ValueError("Model choice metadata description must be text")
            declaration["description"] = description
        if self.factories is policies._REGISTRY:
            policies.register_model(name, factory, replace=replace)
        else:
            if name in self.factories and not replace:
                raise ValueError(f"Model already registered: {name}")
            self.factories[name] = factory
        self.metadata.pop(name, None)
        if declaration is not None:
            self.metadata[name] = (factory, declaration)

    def describe(self) -> dict:
        """Return detached choice descriptions without invoking model factories.

        Aliases are grouped only when their canonical metadata and actual factory
        agree. Conflicting declarations remain usable by registry name, but are not
        advertised as one policy with a potentially incorrect version/type label.
        """
        groups: dict[str, list[str]] = {}
        for name, (factory, metadata) in self.metadata.items():
            if self.factories.get(name) is factory:
                groups.setdefault(metadata["model_id"], []).append(name)
        choices = []
        for canonical_id, names in sorted(groups.items()):
            names.sort()
            first = names[0]
            if any(self.metadata[name][1] != self.metadata[first][1]
                   or self.metadata[name][0] is not self.metadata[first][0] for name in names[1:]):
                continue
            choices.append({**deepcopy(self.metadata[first][1]), "aliases": names})
        return {"schema_version": "zombie-sim/model-catalog-v1",
                "defaults": {"Human": "HumanDefaultModel", "Zombie": "ZombieDefaultModel"},
                "choices": choices, "registered_names": list(self.names())}

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self.factories))

    def create(self, name: str, parameters: dict | None = None):
        if self.factories is policies._REGISTRY or name.startswith("ppo:"):
            return policies.create_model(name, parameters)
        if name not in self.factories:
            raise ValueError(f"Unknown decision model {name!r}; registered: {', '.join(self.names())}")
        return self.factories[name](parameters)


DEFAULT_MODEL_CATALOG = ModelCatalog(policies._REGISTRY)
# Kept as the same mutable object for existing metadata inspection/test clients.
_MODEL_METADATA = DEFAULT_MODEL_CATALOG.metadata


def register_model(name: str, factory: Callable, *, replace: bool = False,
                   metadata: dict | None = None) -> None:
    return DEFAULT_MODEL_CATALOG.register(name, factory, replace=replace, metadata=metadata)


def model_catalog() -> dict:
    return DEFAULT_MODEL_CATALOG.describe()
