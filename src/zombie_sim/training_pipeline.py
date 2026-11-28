"""Object-owned training/evaluation orchestration around pinned ML kernels.

The legacy learning module is deliberately byte-preserved: historical learned
model checkpoints pin that file. New orchestration and extension seams live here.
Optional ML libraries are imported only when the backend actually executes.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Protocol, Any


class LearningBackend(Protocol):
    def train(self, config, output, settings) -> dict[str, Any]: ...
    def evaluate(self, config, artifact, seeds, **options) -> dict[str, Any]: ...


class RecurrentPPOBackend:
    def train(self, config, output, settings):
        from .learning import train
        return train(config, output, settings)

    def evaluate(self, config, artifact, seeds, **options):
        from .learning import evaluate
        return evaluate(config, artifact, seeds=seeds, **options)


class TrainingPipeline:
    """Own a validated scenario, split settings, destination and trainer strategy."""

    def __init__(self, config, output, settings=None, *, backend=None, configuration=None):
        from .config import ConfigurationService
        from .learning import TrainingConfig
        self.configuration = configuration if configuration is not None else ConfigurationService()
        self.config = self.configuration.resolve(config)
        self.output = Path(output)
        self.settings = deepcopy(settings) if settings is not None else TrainingConfig()
        self.settings.__post_init__()
        self.backend = backend if backend is not None else RecurrentPPOBackend()

    def run(self):
        # Each invocation receives detached inputs; backend mutation cannot change
        # a later experiment or silently contaminate the declared data split.
        settings = deepcopy(self.settings)
        settings.__post_init__()
        return self.backend.train(deepcopy(self.config), self.output, settings)


class EvaluationPipeline:
    """Own an explicit evaluation cohort and injectable evaluator strategy."""

    def __init__(self, config, artifact=None, seeds=range(2000, 2030), *,
                 backend=None, configuration=None, **evaluation_options):
        from .config import ConfigurationService
        self.configuration = configuration if configuration is not None else ConfigurationService()
        self.config = self.configuration.resolve(config)
        self.artifact = Path(artifact) if artifact is not None else None
        self.seeds = tuple(seeds)
        if not self.seeds or any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
                                 for seed in self.seeds) or len(set(self.seeds)) != len(self.seeds):
            raise ValueError("Evaluation seeds must be distinct nonnegative integers")
        self.options = deepcopy(evaluation_options)
        self.backend = backend if backend is not None else RecurrentPPOBackend()

    def run(self):
        return self.backend.evaluate(deepcopy(self.config), self.artifact,
                                     self.seeds, **deepcopy(self.options))
