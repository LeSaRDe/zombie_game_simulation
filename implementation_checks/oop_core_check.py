"""Independent OOP checks: exact old/new traces, old bundles, and real injection.

The pre-refactor package is an audit artifact, not an implementation dependency.
Run from the repository root with its runtime Python and PYTHONPATH=src.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "artifacts/oop-refactor/baseline-package"


def scenario(mode):
    agents = [{"id": f"h{i}", "type": "Human", "x": 10+i*2, "y": 10,
               "life": 90, "stamina": 60} for i in range(6)]
    agents += [{"id": f"z{i}", "type": "Zombie", "x": 11+i*3, "y": 12} for i in range(2)]
    return {"agents": agents, "seed": 3917, "horizon": 7, "decision_mode": mode,
            "placement": {"minimum_separation": 0, "cross_type_separation": 0},
            "execution": {"parallel_min_agents": 1, "completion_order": "seeded_shuffle"},
            "checkpoint_interval": 1000}


def semantic_trace(sim):
    payload = sim.serialize()
    attrs = payload["attributes"]
    attrs.pop("history_path", None)
    return {"state": sim.snapshot(), "events": list(sim.events),
            "decisions": list(sim.decisions), "random_draws": list(sim.random_draws),
            "runtime_attributes": attrs}


def probe(options):
    # Both packages use the real canonical ontology and requirement provenance.
    import zombie_sim.registry as registry
    registry.ROOT = ROOT
    from zombie_sim.engine import Simulation
    if options.get("checkpoint_input"):
        sim = Simulation.restore(options["checkpoint_input"], backend=options["backend"], workers=options["workers"])
    else:
        sim = Simulation(scenario(options["mode"]), backend=options["backend"],
                         workers=options["workers"], run_id="oop-differential")
        if options["mode"] == "scripted":
            sim.submit_intents([
                {"actor": "h0", "action": "move", "parameters": {"duration": 2,
                 "path": [{"x": 10, "y": 10, "offset": 0}, {"x": 14, "y": 10, "offset": 2}]}},
                {"actor": "h1", "action": "rest", "parameters": {"duration": 2}},
                {"actor": "z0", "action": "claw", "target": "h0"},
            ])
        sim.advance_until("1/3", return_snapshot=False)
        if options.get("checkpoint_output"):
            sim.checkpoint(options["checkpoint_output"])
    try:
        sim.advance_until(5, return_snapshot=False)
        trace = semantic_trace(sim)
        Path(options["output"]).write_text(json.dumps(trace, sort_keys=True))
        diagnostics = sim.execution_diagnostics()
        print(json.dumps({"revision": sim.revision, "records": len(sim.events),
                          "worker_processes": len(diagnostics["performance"].get("worker_cpu_seconds", {}))}))
    finally:
        sim.close()


def run_probe(package, options):
    env = dict(os.environ, PYTHONPATH=str(package), PYTHONDONTWRITEBYTECODE="1",
               ZOMBIE_ONTOLOGY_DIR=str(ROOT / "ontology/formal_v0.1"))
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--probe", json.dumps(options)],
                            cwd=ROOT, env=env, text=True, capture_output=True, check=True)
    return json.loads(result.stdout.strip().splitlines()[-1])


def injection_checks(directory):
    from zombie_sim import Simulation
    from zombie_sim.core import SimulationServiceFactory, ServiceBindingMismatch
    from zombie_sim.core.observations import ObservationService
    from zombie_sim.core.scheduler import SchedulerService
    from zombie_sim.core.runtime_service import RuntimeService
    from zombie_sim.runtime import _digest

    class CountObservations(ObservationService):
        def observe(self, aid):
            self.calls = getattr(self, "calls", 0) + 1
            return super().observe(aid)

    class CountScheduler(SchedulerService):
        def advance_until(self, *args, **kwargs):
            self.calls = getattr(self, "calls", 0) + 1
            return super().advance_until(*args, **kwargs)

    class CountRuntime(RuntimeService):
        def serialize(self, sim):
            self.calls = getattr(self, "calls", 0) + 1
            return super().serialize(sim)

    class CustomFactory(SimulationServiceFactory):
        def create(self, name, context):
            if name == "observations":
                return CountObservations(context)
            return super().create(name, context)

    class ParameterizedFactory(SimulationServiceFactory):
        def __init__(self, factor):
            super().__init__()
            self.factor = factor

    factory = SimulationServiceFactory({"observations": CountObservations,
                                        "scheduler": CountScheduler, "runtime": CountRuntime})
    with Simulation(scenario("model"), workers=1, service_factory=factory) as sim:
        sim.advance_until("1/3")
        assert sim.services.scheduler.calls == 1
        assert sim.services.observations.calls >= 8
        payload = sim.serialize()
        assert sim.services.runtime.calls == 1
        assert "service_bindings" in payload["attributes"]
        assert not any(name.startswith("_runtime_") for name in payload["attributes"])
        assert factory.manifest()["services"]["observations"]["inherited_implementations"]
        for options in ({}, {"service_factory": SimulationServiceFactory({"observations": CountObservations})}):
            try:
                Simulation.from_serialized(payload, workers=1, **options)
            except ServiceBindingMismatch:
                pass
            else:
                raise AssertionError("Custom runtime was restored with different behavior")
        with Simulation.from_serialized(payload, workers=1, service_factory=factory) as restored:
            assert type(restored.services.observations) is CountObservations
            sim.advance_until(2); restored.advance_until(2)
            assert sim.snapshot() == restored.snapshot()
            assert list(sim.events) == list(restored.events)
        with Simulation.restore_revision(sim.history_path, workers=1, service_factory=factory) as restored:
            assert type(restored.services.scheduler) is CountScheduler
        bundle = sim.checkpoint(directory / "custom.json")
        with Simulation.restore(bundle, workers=1, service_factory=factory) as restored:
            assert type(restored.services.runtime) is CountRuntime
        with sim.branch(directory / "custom-child") as child:
            assert child.services.factory.manifest() == factory.manifest()
        tampered = deepcopy(payload)
        tampered["attributes"]["service_bindings"]["services"]["observations"]["file_sha256"] = "0"*64
        tampered["attributes_sha256"] = _digest(tampered["attributes"])
        try:
            Simulation.from_serialized(tampered, workers=1, service_factory=factory)
        except ServiceBindingMismatch:
            pass
        else:
            raise AssertionError("Altered behavior provenance was accepted")
    try:
        Simulation(scenario("model"), workers=2, service_factory=factory)
    except ValueError as exc:
        assert "workers=1" in str(exc)
    else:
        raise AssertionError("Custom worker behavior silently fell back to defaults")
    custom_factory = CustomFactory()
    assert custom_factory.is_custom
    assert "$factory" in custom_factory.manifest()["services"]
    with Simulation(scenario("model"), workers=1, service_factory=custom_factory) as sim:
        sim.observe("h0")
        assert sim.services.observations.calls == 1
        payload = sim.serialize()
        try:
            Simulation.from_serialized(payload, workers=1)
        except ServiceBindingMismatch:
            pass
        else:
            raise AssertionError("A custom composition factory silently became the default")
        with Simulation.from_serialized(payload, workers=1, service_factory=custom_factory) as restored:
            assert type(restored.services.observations) is CountObservations
    for factor in (1, 2):
        try:
            ParameterizedFactory(factor)
        except TypeError as exc:
            assert "unrecorded instance state" in str(exc)
        else:
            raise AssertionError("A parameterized factory was accepted without durable parameters")
    # Approved deep-OOP migration: mutable Simulation subclass hooks are
    # explicit errors; read-only observation subclasses above remain supported.
    from zombie_sim.core.migration import LegacyExtensionError
    class ObserveHook(Simulation):
        def _nearby(self, position, radius):
            return super()._nearby(position, radius)
    try:
        ObserveHook(scenario("scripted"), workers=1)
    except LegacyExtensionError as exc:
        assert "_nearby" in str(exc) and "ReadProjection" in str(exc)
    else:
        raise AssertionError("Legacy mutable coordinator hook silently bypassed the read port")
    assert Simulation._public({"id": "a", "_private": 1}) == {"id": "a"}
    return {"injected_decisions_observations_scheduler_runtime": True,
            "normal_reconstruction_restore_and_journal_and_checkpoint": True,
            "branch_inherits_factory": True, "missing_changed_and_tampered_bindings_rejected": True,
            "custom_worker_fallback_rejected": True, "custom_factory_subclasses_pinned": True,
            "unrecorded_factory_parameters_rejected": True, "legacy_subclass_hooks_require_migration": True}


def main():
    assert BASELINE.is_dir(), "Retain the pre-refactor audit package for differential validation"
    report = {"same_default_semantics": [], "old_checkpoint_continuation": [], "pins_preserved": {}}
    for name in ("policies.py", "learning.py"):
        before = (BASELINE / "zombie_sim" / name).read_bytes()
        after = (ROOT / "src/zombie_sim" / name).read_bytes()
        assert before == after, f"Existing model source pin changed: {name}"
        report["pins_preserved"][name] = hashlib.sha256(after).hexdigest()
    with TemporaryDirectory(prefix="oop-core-check-") as temp:
        directory = Path(temp)
        for mode in ("scripted", "model"):
            for backend in ("memory", "sqlite"):
                for workers in (1, 2):
                    label = f"{mode}-{backend}-{workers}"
                    checkpoint = directory / (label+".json")
                    common = {"mode": mode, "backend": backend, "workers": workers,
                              "checkpoint_output": str(checkpoint)}
                    before = directory / (label+"-before.json")
                    old = run_probe(BASELINE, {**common, "output": str(before)})
                    # A different checkpoint filename avoids replacing the source bundle.
                    after = directory / (label+"-after.json")
                    new = run_probe(ROOT / "src", {**common,
                         "checkpoint_output": str(directory / (label+"-new.json")), "output": str(after)})
                    expected = json.loads(before.read_text())
                    actual = json.loads(after.read_text())
                    assert expected == actual, f"Default semantic/runtime trace changed: {label}"
                    if mode == "model" and workers == 2:
                        assert old["worker_processes"] and new["worker_processes"], "Detached worker path was not exercised"
                    report["same_default_semantics"].append({"case": label, **new,
                          "trace_sha256": hashlib.sha256(before.read_bytes()).hexdigest()})
                    restored = directory / (label+"-restored.json")
                    run_probe(ROOT / "src", {"checkpoint_input": str(checkpoint),
                              "backend": backend, "workers": workers, "output": str(restored)})
                    assert expected == json.loads(restored.read_text()), f"Old bundle continuation changed: {label}"
                    report["old_checkpoint_continuation"].append(label)
        report["injection"] = injection_checks(directory)
    target = ROOT / "artifacts/oop-refactor/core-verification.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--probe":
        probe(json.loads(sys.argv[2]))
    else:
        main()
