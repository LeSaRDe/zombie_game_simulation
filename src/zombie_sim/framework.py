"""Public composition root and explicitly owned simulation sessions."""
from __future__ import annotations

from .entities import ExactTime, ObservationView, WorldView
from .interfaces import SimulationPort
from .measurements import MeasurementRegistry
from .modeling import ModelRegistry, ScenarioBuilder


class Experiment:
    """Own one coordinator's lifetime; expose detached typed research views.

    Use a context manager so stores and worker pools close even on exceptions.
    ``simulation`` is the explicit escape hatch for the established engine API.
    """

    def __init__(self, simulation: SimulationPort, *, measurements=None):
        self.simulation = simulation
        self.measurements = measurements if measurements is not None else MeasurementRegistry()
        self._closed = False

    def _require_open(self):
        if self._closed:
            raise RuntimeError("This experiment is closed")

    def snapshot(self) -> WorldView:
        self._require_open()
        return WorldView(self.simulation.snapshot())

    def observe(self, agent_id) -> ObservationView:
        self._require_open()
        return ObservationView(self.simulation.observe(agent_id))

    def advance(self, until) -> WorldView:
        self._require_open()
        self.simulation.advance_until(str(ExactTime.parse(until)), return_snapshot=False)
        return self.snapshot()

    def submit(self, *intents):
        """Submit ActionIntent objects or existing intent records unchanged."""
        self._require_open()
        return self.simulation.submit_intents([
            intent.to_record() if hasattr(intent, "to_record") else intent for intent in intents])

    def measure(self, names=None):
        return self.measurements.measure(self.snapshot(), names)

    def checkpoint(self, path=None):
        self._require_open()
        return self.simulation.checkpoint(path)

    def close(self):
        if not self._closed:
            self.simulation.close()
            self._closed = True

    def __enter__(self):
        self._require_open()
        return self

    def __exit__(self, *_):
        self.close()


class SimulationFramework:
    """Configure collaborators once, then create independent experiments.

    This object owns configuration, registry and measurement strategies. Each
    returned Experiment owns its own simulation and must be closed by its caller.
    It does not start a web service or import optional GUI/learning packages.
    """

    def __init__(self, *, configuration=None, simulation_factory=None,
                 models=None, measurements=None, service_factory=None):
        from .config import ConfigurationService
        from .engine import Simulation
        self.configuration = configuration if configuration is not None else ConfigurationService()
        self.simulation_factory = simulation_factory if simulation_factory is not None else Simulation
        self.models = models if models is not None else ModelRegistry()
        self.measurements = measurements if measurements is not None else MeasurementRegistry()
        self.service_factory = service_factory

    def scenario(self, source=None) -> ScenarioBuilder:
        return ScenarioBuilder(source)

    def create(self, scenario=None, **options) -> Experiment:
        if isinstance(scenario, ScenarioBuilder):
            scenario = scenario.draft()
        config = self.configuration.resolve(scenario)
        if self.service_factory is not None:
            options.setdefault("service_factory", self.service_factory)
        simulation = self.simulation_factory(config, **options)
        return Experiment(simulation, measurements=self.measurements)

    def restore(self, checkpoint, **options) -> Experiment:
        """Restore via the selected factory's explicit restart contract."""
        restore = getattr(self.simulation_factory, "restore", None)
        if restore is None:
            raise TypeError("The simulation factory does not expose restore(checkpoint, **options)")
        if self.service_factory is not None:
            options.setdefault("service_factory", self.service_factory)
        return Experiment(restore(checkpoint, **options), measurements=self.measurements)
