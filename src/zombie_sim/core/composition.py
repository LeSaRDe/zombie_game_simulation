"""Replaceable orchestration and read projections with explicit extension ports."""
from __future__ import annotations

import hashlib
import importlib
import inspect
from types import MappingProxyType
from typing import Any, Mapping
from .migration import LEGACY_BEHAVIOR_BINDINGS, MUTATION_SERVICES, unsupported_extension

_DEFAULT_SERVICES = {
    "transactions": ("transactions", "TransactionService"),
    "randomness": ("randomness", "RandomService"),
    "continuous": ("continuous", "ContinuousStateService"),
    "observations": ("observations", "ObservationService"),
    "scheduler": ("scheduler", "SchedulerService"),
    "decisions": ("decisions", "DecisionService"),
    "lifecycle": ("lifecycle", "LifecycleService"),
    "interventions": ("interventions", "InterventionService"),
    "actions": ("actions", "ActionService"),
    "runtime": ("runtime_service", "RuntimeService"),
    "parallel": ("parallel_service", "ParallelExecutor"),
}


class ServiceBindingMismatch(ValueError):
    """Exact continuation requires the original explicitly supplied behavior."""


class SimulationServiceFactory:
    """Bind named services to classes accepting one explicit context argument.

    Subclass a built-in service and override its behavior, then supply that class
    in ``overrides``. Custom wiring requires one coordinator worker and an
    identical explicit factory for restoration. Neither service instances nor
    Python callables are persisted in the runtime journal. Factories are immutable
    and carry only declared class bindings; behavior parameters belong in the
    recorded scenario available through the context, not factory instance fields.
    """

    def __init__(self, overrides: Mapping[str, type] | None = None):
        bindings = dict(overrides or {})
        unknown = bindings.keys() - _DEFAULT_SERVICES.keys()
        if unknown:
            raise ValueError(f"Unknown simulation services: {sorted(unknown)}")
        legacy = bindings.keys() & LEGACY_BEHAVIOR_BINDINGS
        if legacy:
            unsupported_extension(sorted(legacy)[0])
        if any(not inspect.isclass(value) for value in bindings.values()):
            raise TypeError("Service bindings must be classes accepting a context")
        self.overrides = MappingProxyType(bindings)
        # Validate reproducible identities at composition time, before any writes.
        self._manifest = self._describe()

    def __setattr__(self, name, value):
        if name not in {"overrides", "_manifest"}:
            raise TypeError("Service factories cannot carry unrecorded instance state; put behavior parameters in the recorded scenario")
        if name in self.__dict__:
            raise AttributeError("Service factory bindings are immutable; use with_overrides() to create a new factory")
        object.__setattr__(self, name, value)

    def _validate_state(self) -> None:
        # Also reject a subclass which populated its __dict__ directly rather
        # than using normal assignment. Arbitrary instance settings cannot be
        # inferred reliably from class/version/source identities.
        if set(vars(self)) != {"overrides", "_manifest"}:
            raise TypeError("Service factories cannot carry unrecorded instance state; put behavior parameters in the recorded scenario")

    @property
    def is_custom(self) -> bool:
        return bool(self.overrides) or type(self) is not SimulationServiceFactory

    def with_overrides(self, **overrides: type) -> "SimulationServiceFactory":
        return type(self)({**self.overrides, **overrides})

    def _describe(self) -> dict[str, Any]:
        bindings = {}
        implementations = dict(self.overrides)
        if type(self) is not SimulationServiceFactory:
            implementations["$factory"] = type(self)
        for name, service in sorted(implementations.items()):
            try:
                source = inspect.getsource(service)
                filename = inspect.getsourcefile(service)
                if filename is None:
                    raise OSError("No implementation source file")
                # Pin the full implementation file, including helpers used by the
                # class. User-supplied version labels never replace this digest.
                with open(filename, "rb") as stream:
                    file_digest = hashlib.sha256(stream.read()).hexdigest()
            except (OSError, TypeError) as exc:
                raise ValueError(f"Custom service {name!r} needs inspectable source for exact restart") from exc
            bindings[name] = {
                "module": service.__module__, "class": service.__qualname__,
                "version": str(getattr(service, "service_version", "1")),
                "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                "file_sha256": file_digest,
                "inherited_implementations": [],
            }
            for base in service.__mro__[1:]:
                if base is object:
                    continue
                filename = inspect.getsourcefile(base)
                if filename is None:
                    raise ValueError(f"Custom service {name!r} has an uninspectable base implementation")
                with open(filename, "rb") as stream:
                    digest = hashlib.sha256(stream.read()).hexdigest()
                bindings[name]["inherited_implementations"].append({
                    "module": base.__module__, "class": base.__qualname__,
                    "file_sha256": digest,
                })
        return {"schema": "zombie-sim/service-bindings-v1", "services": bindings}

    def manifest(self) -> dict[str, Any]:
        from copy import deepcopy
        self._validate_state()
        return deepcopy(self._manifest)

    def validate_workers(self, workers: int) -> None:
        self._validate_state()
        if self.is_custom and workers != 1:
            raise ValueError("Custom service bindings require workers=1; detached workers cannot silently use default behavior")

    def validate_restart(self, recorded: dict | None) -> None:
        legacy = set((recorded or {}).get('services', {})) & LEGACY_BEHAVIOR_BINDINGS
        if legacy:
            unsupported_extension(sorted(legacy)[0])
        actual = self.manifest() if self.is_custom else None
        if recorded != actual:
            raise ServiceBindingMismatch("Runtime service bindings differ; provide the original explicit service_factory to restore or branch")

    def create(self, name: str, context: Any):
        if name not in _DEFAULT_SERVICES:
            raise KeyError(name)
        if name in MUTATION_SERVICES:
            unsupported_extension(name)
        implementation = self.overrides.get(name)
        if implementation is None:
            module, classname = _DEFAULT_SERVICES[name]
            implementation = getattr(importlib.import_module(f"{__package__}.{module}"), classname)
        return implementation(context)


class SimulationServices:
    """One lazy instance of each behavior per authoritative coordinator/view."""

    def __init__(self, context: Any, factory: SimulationServiceFactory | None = None):
        self.context = context
        self.factory = factory or SimulationServiceFactory()
        self._instances: dict[str, Any] = {}

    def _get(self, name):
        if name in {'observations', 'continuous'}:
            return getattr(self.context._projection, name)
        if name in MUTATION_SERVICES:
            unsupported_extension(name)
        if name not in self._instances:
            self._instances[name] = self.factory.create(name, None if name == 'randomness' else self.context)
        return self._instances[name]

    @property
    def transactions(self): return self._get("transactions")
    @property
    def randomness(self): return self._get("randomness")
    @property
    def continuous(self): return self._get("continuous")
    @property
    def observations(self): return self._get("observations")
    @property
    def scheduler(self): return self._get("scheduler")
    @property
    def decisions(self): return self._get("decisions")
    @property
    def lifecycle(self): return self._get("lifecycle")
    @property
    def interventions(self): return self._get("interventions")
    @property
    def actions(self): return self._get("actions")
    @property
    def runtime(self): return self._get("runtime")
    @property
    def parallel(self): return self._get("parallel")
