"""Object-oriented modeling API over the stable, hash-pinned policy contract."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
from random import Random
from typing import Any

from .entities import AgentView, Decision, FrozenRecord, ObservationView
from .interfaces import DecisionModel


class ObjectDecisionModel(ABC):
    """Subclass ``choose`` to implement a policy using typed local observations.

    One instance may serve many identities. Per-agent memory belongs in the
    returned Decision, never in instance attributes. The engine supplies RNGs.
    """

    model_id = "custom/model"
    version = "1.0.0"
    applicable_types = ("Human", "Zombie")

    def __init__(self, parameters: Mapping[str, Any] | None = None):
        self.parameters = FrozenRecord(parameters or {})

    def initial_memory(self, agent: AgentView) -> Any:
        return {}

    def initialize_memory(self, agent: dict[str, Any]) -> Any:
        return self._pack_memory(self.initial_memory(AgentView(agent)))

    def _pack_memory(self, memory: Any) -> dict[str, Any]:
        encoded = self.encode_memory(memory)
        # Even a custom codec must produce finite JSON at the engine boundary.
        encoded = json.loads(json.dumps(encoded, allow_nan=False))
        return {"$object_model_memory": "v1", "model_id": self.model_id, "value": encoded}

    @abstractmethod
    def choose(self, observation: ObservationView, memory: Any, rng: Random) -> Decision:
        """Choose an ontology action using only this local observation."""

    def decide(self, observation: dict[str, Any], memory: Any, rng: Random):
        view = ObservationView(observation)
        if view.self_state.biological_type not in self.applicable_types:
            raise ValueError("Decision model is incompatible with the current biological type")
        if isinstance(memory, dict) and "$object_model_memory" in memory:
            if memory["$object_model_memory"] != "v1" or memory.get("model_id") != self.model_id:
                raise ValueError("Incompatible object-model memory envelope")
            local_memory = self.decode_memory(deepcopy(memory["value"]))
        elif memory is None or memory == {}:
            # The stable engine signals an identity's first decision with {}.
            # The envelope distinguishes that signal from an initialized empty
            # memory on subsequent decisions, including after exact restart.
            local_memory = self.initial_memory(view.self_state)
        else:
            local_memory = self.decode_memory(deepcopy(memory))
        decision = self.choose(view, local_memory, rng)
        if not isinstance(decision, Decision):
            raise TypeError("ObjectDecisionModel.choose must return a Decision")
        intent, _, diagnostics = decision.to_result()
        return intent, self._pack_memory(decision.memory), diagnostics

    def decide_batch(self, observations, memories, rngs):
        return [self.decide(observation, memory, rng)
                for observation, memory, rng in zip(observations, memories, rngs, strict=True)]

    def encode_memory(self, memory: Any) -> Any:
        """Default codec accepts only finite JSON data; override for other types."""
        return json.loads(json.dumps(memory, allow_nan=False))

    def decode_memory(self, payload: Any) -> Any:
        return self.encode_memory(payload)

    def manifest(self) -> dict[str, Any]:
        from .policies import OBSERVATION_VERSION
        parameters = self.parameters.to_record()
        encoded = json.dumps(parameters, sort_keys=True, separators=(",", ":"), allow_nan=False)
        # Include inherited behavior in a new plugin's declared dependencies.
        # Existing built-in/learned implementations and their pins are untouched.
        dependencies = [{"module": "zombie_sim." + name,
                         "sha256": hashlib.sha256(Path(__file__).with_name(name + ".py").read_bytes()).hexdigest()}
                        for name in ("modeling", "entities")]
        # artifact_pins hashes the concrete class's file. Also pin intermediate
        # plugin bases: a subclass file alone does not capture inherited rules.
        inherited = {}
        for base in type(self).__mro__[1:]:
            if base in (ObjectDecisionModel, ABC, object):
                continue
            source = inspect.getsourcefile(base)
            if source is None:
                raise ValueError(f"Model base {base.__qualname__} requires inspectable source for exact restart")
            inherited[base.__module__] = hashlib.sha256(Path(source).read_bytes()).hexdigest()
        dependencies.extend({"module": module, "sha256": digest} for module, digest in sorted(inherited.items()))
        return {"model_id": self.model_id, "model_version": self.version,
                "applicable_types": list(self.applicable_types),
                "observation_version": OBSERVATION_VERSION, "action_vocabulary": "ontology_v0.1",
                "encoder_version": "typed-observation-v1", "parameters": parameters,
                "parameter_checksum": hashlib.sha256(encoded.encode()).hexdigest(),
                "dependencies": dependencies, "deterministic": True, "restartable": True}


class ModelRegistry:
    """Registration/catalog port shared with the existing policy factories.

    Registrations are process-local, just like the legacy API. Install a plugin
    during startup in each worker process; a closure is not a portable plugin.
    """

    def __init__(self):
        from .model_catalog import DEFAULT_MODEL_CATALOG
        self.catalog = DEFAULT_MODEL_CATALOG

    def register(self, name: str, factory, *, label: str | None = None,
                 description: str = "", metadata: dict | None = None, replace: bool = False) -> None:
        if metadata is None and label is not None:
            required = ("model_id", "version", "applicable_types")
            if not all(hasattr(factory, key) for key in required):
                raise ValueError("A labelled model factory requires declared identity, version and applicable types")
            metadata = {"model_id": factory.model_id, "version": factory.version,
                        "applicable_types": list(factory.applicable_types), "label": label,
                        "description": description}
        self.catalog.register(name, factory, metadata=metadata, replace=replace)

    def create(self, name: str, parameters: dict | None = None) -> DecisionModel:
        model = self.catalog.create(name, parameters)
        if not isinstance(model, DecisionModel):
            raise TypeError(f"Model {name!r} does not implement the decision-model contract")
        return model

    def names(self) -> tuple[str, ...]:
        return self.catalog.names()

    def describe(self) -> dict[str, Any]:
        return self.catalog.describe()


class ScenarioBuilder:
    """Build ordinary scenario records; all validation stays in one service."""

    def __init__(self, source: Mapping[str, Any] | None = None):
        self._source = deepcopy(dict(source or {"preset": "small"}))

    def set(self, **settings: Any) -> ScenarioBuilder:
        self._source.update(deepcopy(settings))
        return self

    def world(self, length: float, width: float) -> ScenarioBuilder:
        self._source["world"] = {"length": length, "width": width}
        return self

    def agents(self, records) -> ScenarioBuilder:
        """Set explicit ordinary agents; spacing and geometry are still checked."""
        self._source["agents"] = deepcopy(records)
        return self

    def decision_models(self, *, human: str | None = None, zombie: str | None = None) -> ScenarioBuilder:
        if human is not None:
            self._source["human_model"] = human
        if zombie is not None:
            self._source["zombie_model"] = zombie
        return self

    def build(self, *, configuration=None) -> dict[str, Any]:
        if configuration is None:
            from .config import ConfigurationService
            configuration = ConfigurationService()
        return configuration.resolve(deepcopy(self._source))

    def draft(self) -> dict[str, Any]:
        return deepcopy(self._source)
