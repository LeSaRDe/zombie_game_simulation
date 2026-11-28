"""Ontology-based, event-driven zombie simulation."""
__version__ = "0.1.0"


def __getattr__(name):
    modules = {
        "Simulation": "engine", "SimulationFramework": "framework", "Experiment": "framework",
        "ScenarioBuilder": "modeling", "ObjectDecisionModel": "modeling", "ModelRegistry": "modeling",
        "ExactTime": "entities", "HistoryCursor": "entities", "AgentIdentity": "entities",
        "WorldView": "entities", "AgentView": "entities", "ObservationView": "entities",
        "ActionIntent": "entities", "Decision": "entities",
        "MeasurementRegistry": "measurements", "PopulationMeasurement": "measurements",
        "TrainingPipeline": "training_pipeline", "EvaluationPipeline": "training_pipeline",
        "ConfigurationService": "config", "WorkspaceServices": "services",
        "SimulationServiceFactory": "core.composition",
    }
    if name in modules:
        from importlib import import_module
        value = getattr(import_module("." + modules[name], __name__), name)
        globals()[name] = value
        return value
    raise AttributeError(name)
