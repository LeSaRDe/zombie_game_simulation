"""Composable researcher measurements; no access to mutable coordinator state."""
from __future__ import annotations

from copy import deepcopy
import json

from .entities import WorldView
from .interfaces import Measurement


class PopulationMeasurement:
    name = "population"
    version = "1"

    def measure(self, world: WorldView):
        counts = {"living_humans": 0, "living_zombies": 0, "dead": 0}
        for agent in world.agents.values():
            if not agent.alive:
                counts["dead"] += 1
            elif agent.biological_type == "Human":
                counts["living_humans"] += 1
            elif agent.biological_type == "Zombie":
                counts["living_zombies"] += 1
        return counts


class MeasurementRegistry:
    """Instance-owned measurement strategies with named, versioned results."""

    def __init__(self, measurements=None):
        self._measurements: dict[str, Measurement] = {}
        for measurement in (PopulationMeasurement(),) if measurements is None else measurements:
            self.register(measurement)

    def register(self, measurement: Measurement, *, replace=False):
        if not isinstance(measurement.name, str) or not measurement.name:
            raise ValueError("A measurement requires a name")
        if not isinstance(measurement.version, str) or not measurement.version:
            raise ValueError("A measurement requires a version")
        if measurement.name in self._measurements and not replace:
            raise ValueError(f"Measurement {measurement.name!r} is already registered")
        if not callable(measurement.measure):
            raise TypeError("A measurement must implement measure(world)")
        self._measurements[measurement.name] = measurement

    def measure(self, world: WorldView, names=None):
        selected = tuple(self._measurements) if names is None else tuple(names)
        result = {}
        for name in selected:
            strategy = self._measurements[name]
            values = deepcopy(dict(strategy.measure(world)))
            json.dumps(values, allow_nan=False)
            result[name] = {"version": strategy.version, "values": values}
        return {"cursor": world.cursor.to_record(), "measurements": result}

    def names(self):
        return tuple(self._measurements)
