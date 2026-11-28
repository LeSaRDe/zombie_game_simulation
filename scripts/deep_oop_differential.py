"""Preserve legacy bundles and compare real engines in isolated processes.

Capture is append-only: an existing corpus is never replaced. The probe uses the
selected package's actual Simulation; expected results come from the archived
accepted engine, independent of the refactored implementation.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = ROOT / "artifacts/deep-oop-refactor/baseline-package"
DEFAULT_CORPUS = ROOT / "artifacts/deep-oop-refactor/legacy-corpus-v4"
RUNTIME_CAPTURE = "all_attributes_except_documented_physical_fields-v1"
# state is compared in full as world; the other fields identify physical
# execution placement. Every other present serialized field is compared,
# including counters, prepared work, config and optional extension bindings.
RUNTIME_EXCLUDED = frozenset({"state", "history_path", "backend", "workers", "worker_request"})
PROVENANCE_ONLY_PATHS = ("/world/source_provenance/plan_source_matches_manifest",
                         "/world/source_provenance/source_hashes/manifest.json")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def compatibility_projection(captures):
    """Validate the approved plan-pin refresh separately from game equality.

    Only two exact provenance fields differ after the approved nonsemantic
    manifest refresh. Raw captures retain both; all ontology/source bytes and
    every gameplay/runtime field remain part of the ordinary comparison.
    """
    manifests = {}
    for path in (ROOT / "artifacts/deep-oop-refactor/before/ontology/formal_v0.1/manifest.json",
                 ROOT / "ontology/formal_v0.1/manifest.json"):
        manifests[digest(path)] = json.loads(path.read_text())
    projected = deepcopy(captures)
    for capture in projected:
        provenance = capture["world"]["source_provenance"]
        fingerprint = provenance["source_hashes"]["manifest.json"]
        if fingerprint not in manifests:
            raise AssertionError("Capture's ontology manifest is neither the preserved original nor the reviewed current file")
        expected = provenance["source_hashes"].get("requirements") == manifests[fingerprint]["source_plan_sha256"]
        if provenance["plan_source_matches_manifest"] != expected:
            raise AssertionError("Capture misreports its actual plan provenance")
        del provenance["plan_source_matches_manifest"]
        del provenance["source_hashes"]["manifest.json"]
    return projected


def scenarios():
    base = {"seed": 3917, "horizon": 12, "decision_mode": "scripted",
            "placement": {"minimum_separation": 0, "cross_type_separation": 0},
            "execution": {"parallel_min_agents": 1, "completion_order": "seeded_shuffle"},
            "checkpoint_interval": 1000}
    return {
        "movement": {"config": {**base, "agents": [
            {"id": "h", "type": "Human", "x": 10, "y": 10, "life": 87, "stamina": 80},
            {"id": "z", "type": "Zombie", "x": 12, "y": 12}]},
            "intents": [{"id": "move", "actor": "h", "action": "move", "parameters": {"duration": 2,
                "path": [{"x": 10, "y": 10, "offset": 0}, {"x": 14, "y": 10, "offset": 2}]}}]},
        "conversion": {"config": {**base, "incubation_duration": 3, "agents": [
            {"id": "h", "type": "Human", "role": "DOCTOR", "x": 10, "y": 10,
             "life": 64, "stamina": 32, "infected": True,
             "inventory": {"FOOD": 2, "MEDICAL_SUPPLY": 1, "MATERIAL": 0}},
            {"id": "other", "type": "Human", "x": 30, "y": 30}]},
            "intents": [{"id": "rest", "actor": "h", "action": "rest", "parameters": {"duration": 5}}]},
        "roles": {"config": {**base, "interventions_enabled": True, "agents": [
            {"id": "e", "type": "Human", "role": "ENGINEER", "x": 10, "y": 10,
             "life": 70, "stamina": 30, "inventory": {"FOOD": 10, "MATERIAL": 6, "MEDICAL_SUPPLY": 0}},
            {"id": "s", "type": "Zombie", "role": "SPITTER", "x": 40, "y": 40}]},
            "intervention": {"kind": "replace_role", "agent": "e", "role": None,
                             "drop_order": ["MATERIAL", "FOOD", "MEDICAL_SUPPLY"]}},
        "model": {"config": {**base, "decision_mode": "model", "agents": [
            *[{"id": f"h{i}", "type": "Human", "x": 10+i*2, "y": 10, "life": 90, "stamina": 60} for i in range(6)],
            *[{"id": f"z{i}", "type": "Zombie", "x": 11+i*3, "y": 12} for i in range(2)]]}},
        "typed_model": {"workers": [1], "config": {**base, "decision_mode": "model",
            "human_model": "deep-oop/counter-memory", "zombie_model": "deep-oop/counter-memory",
            "agents": [{"id": "h", "type": "Human", "x": 10, "y": 10},
                       {"id": "z", "type": "Zombie", "x": 50, "y": 50}]}},
    }


def canonical_capture(sim):
    payload = sim.serialize()
    # Do not use a whitelist: losing an optional or newly added continuation
    # field must be visible, including truthful execution diagnostic counters.
    attrs = payload.get("attributes")
    if attrs is None:
        from zombie_sim.execution import LegacyRuntimeProjection
        attrs = LegacyRuntimeProjection.from_snapshot(payload)
    return {"world": sim.snapshot(), "events": list(sim.events),
            "decisions": list(sim.decisions), "random_draws": list(sim.random_draws),
            "observations": {aid: sim.observe(aid) for aid, a in sim.snapshot()["agents"].items() if a["life"] > 0},
            "runtime": {key: deepcopy(value) for key, value in attrs.items() if key not in RUNTIME_EXCLUDED}}


def differing_paths(left, right, path=""):
    """Exact diagnostic paths, never a normalization or comparison tolerance."""
    if type(left) is not type(right):
        return [{"path": path, "expected_type": type(left).__name__, "observed_type": type(right).__name__}]
    if isinstance(left, dict):
        result = []
        for key in sorted(left.keys() | right.keys()):
            location = path + "/" + str(key).replace("~", "~0").replace("/", "~1")
            if key not in left or key not in right:
                result.append({"path": location, "missing_from": "expected" if key not in left else "observed"})
            else:
                result.extend(differing_paths(left[key], right[key], location))
        return result
    if isinstance(left, list):
        result = [] if len(left) == len(right) else [{"path": path, "expected_length": len(left), "observed_length": len(right)}]
        for index, (expected, observed) in enumerate(zip(left, right)):
            result.extend(differing_paths(expected, observed, path + "/" + str(index)))
        return result
    equal = left.hex() == right.hex() if type(left) is float else left == right
    return [] if equal else [{"path": path, "expected": left, "observed": right}]


def probe(options):
    sys.path.insert(1, str(ROOT))
    from tests.architecture.model_fixtures import CounterMemoryModel
    from zombie_sim.policies import register_model
    register_model(CounterMemoryModel.model_id, CounterMemoryModel)
    import zombie_sim.registry as registry
    registry.ROOT = ROOT
    registry.DEFAULT_CATALOG.project_root = ROOT
    from zombie_sim.engine import Simulation
    from zombie_sim.storage import canonical
    output = Path(options["output"])
    output.mkdir(parents=True, exist_ok=False)
    backend, workers = options["backend"], options["workers"]
    if options.get("checkpoint"):
        sim = Simulation.restore(options["checkpoint"], history_path=output / "continued.sqlite",
                                 backend=backend, workers=workers)
    elif options.get("journal"):
        sim = Simulation.restore_revision(options["journal"], output_history_path=output / "continued.sqlite",
                                          backend=backend, workers=workers)
    else:
        spec = scenarios()[options["scenario"]]
        sim = Simulation(spec["config"], history_path=output / "run.sqlite", backend=backend,
                         workers=workers, run_id="deep-oop-compatibility")
        if spec.get("intents"):
            sim.submit_intents(spec["intents"])
        if spec.get("intervention"):
            sim.intervene(spec["intervention"], at=1, id="retire")
        sim.advance_until("1/3", return_snapshot=False)
        sim.checkpoint(output / "legacy.json")
        # Preserve a journal-only recovery fixture with the pending action and
        # exact clock, independently of the later continuing live database.
        from shutil import copyfile
        copyfile(output / "legacy.history.sqlite", output / "journal-prefix.sqlite")
    try:
        captures = []
        for boundary in ("1/3", "1", "2", "3", "5"):
            sim.advance_until(boundary, return_snapshot=False)
            captures.append(canonical_capture(sim))
        save(output / "trace.json", json.loads(canonical(captures)))
        save(output / "runtime-raw.json", sim.serialize())
        diagnostics = sim.execution_diagnostics()
        save(output / "diagnostics.json", diagnostics)
    finally:
        sim.close()


def run_probe(package, options):
    environment = dict(os.environ, PYTHONPATH=str(Path(package).resolve()), PYTHONDONTWRITEBYTECODE="1",
                       ZOMBIE_ONTOLOGY_DIR=str(ROOT / "ontology/formal_v0.1"))
    completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--probe", json.dumps(options)],
                               cwd=ROOT, env=environment, capture_output=True, text=True)
    if completed.returncode:
        raise RuntimeError(f"Probe failed: {options}\n{completed.stdout}\n{completed.stderr}")


def assert_reference_witness(scenario, location):
    """Require the named phenomenon, not only equality of two quiet traces."""
    trace = json.loads((location / "trace.json").read_text())
    last = trace[-1]
    if scenario == "conversion":
        human = trace[0]["world"]["agents"]["h"]
        zombie = last["world"]["agents"]["h"]
        assert human["type"] == "Human" and zombie["type"] == "Zombie"
        assert zombie["life"] == 64 and zombie["stamina"] == 44
        assert zombie["role"] is None and "inventory" not in zombie
        assert any(event["kind"] == "conversion" and event["time"] == "3" for event in last["events"])
        assert sum(stock["inventory"]["FOOD"] for stock in last["world"]["stockpiles"].values()) == 2
    elif scenario == "roles":
        assert trace[0]["world"]["agents"]["e"]["role"] == "ENGINEER"
        assert last["world"]["agents"]["e"]["role"] is None
        assert sum(stock["inventory"]["MATERIAL"] for stock in last["world"]["stockpiles"].values()) == 6
    elif scenario == "movement":
        assert last["world"]["agents"]["h"]["x"] == 14
        assert last["world"]["occurrences"]["action-1"]["result"] == "SUCCEEDED"
    elif scenario == "model":
        assert last["decisions"] and last["events"]
    elif scenario == "typed_model":
        for memory in last["runtime"]["memories"].values():
            assert memory["value"]["counter"] > 40


def assert_parallel_witness(scenario, workers, location):
    if scenario != "model" or workers == 1:
        return
    diagnostics = json.loads((location / "diagnostics.json").read_text())
    performance = diagnostics["performance"]
    assert diagnostics["workers"] > 1, "Requested parallel comparison silently executed serially"
    assert performance.get("parallel_batches", 0) > 0 and performance.get("parallel_decisions", 0) > 0
    assert performance.get("worker_cpu_seconds"), "No real detached worker process executed the model"
    assert sum(performance["worker_cpu_seconds"].values()) > 0


def capture(args):
    corpus = args.corpus.resolve()
    corpus.mkdir(parents=True, exist_ok=False)
    entries = []
    for scenario in args.scenarios or ("movement", "conversion", "roles", "model"):
        for backend in ("memory", "sqlite"):
            for workers in scenarios()[scenario].get("workers", args.workers):
                label = f"{scenario}-{backend}-{workers}"
                location = corpus / label
                run_probe(args.baseline, {"scenario": scenario, "backend": backend, "workers": workers, "output": str(location)})
                assert_reference_witness(scenario, location)
                assert_parallel_witness(scenario, workers, location)
                # Legacy checkpoint saving changes checkpoint scheduling markers
                # only in its envelope. The journal retains its own truthful
                # marker values; capture that continuation separately rather
                # than normalizing away these execution-state differences.
                run_probe(args.baseline, {"journal": str(location / "journal-prefix.sqlite"),
                          "backend": backend, "workers": workers, "output": str(location / "journal-reference")})
                entry = {"id": label, "scenario": scenario, "backend": backend, "workers": workers,
                         "files": {str(p.relative_to(corpus)): digest(p) for p in location.rglob("*") if p.is_file()}}
                entries.append(entry)
                save(corpus / "manifest.json", {"schema": "deep-oop-legacy-corpus-v1", "entries": entries,
                     "runtime_capture": RUNTIME_CAPTURE, "runtime_excluded": sorted(RUNTIME_EXCLUDED),
                     "baseline": str(args.baseline.resolve()), "complete": False})
                print(f"CAPTURED {label}", flush=True)
    save(corpus / "manifest.json", {"schema": "deep-oop-legacy-corpus-v1", "entries": entries,
         "runtime_capture": RUNTIME_CAPTURE, "runtime_excluded": sorted(RUNTIME_EXCLUDED),
         "baseline": str(args.baseline.resolve()), "complete": True})


def compare(args):
    manifest = json.loads((args.corpus / "manifest.json").read_text())
    if not manifest["complete"]:
        raise ValueError("Incomplete reference corpus is not a passing baseline")
    if manifest.get("runtime_capture") != RUNTIME_CAPTURE or manifest.get("runtime_excluded") != sorted(RUNTIME_EXCLUDED):
        raise ValueError("This corpus used a selected runtime projection; regenerate append-only all-attribute reference evidence")
    args.output.mkdir(parents=True, exist_ok=False)
    checks = []
    for entry in manifest["entries"]:
        for relative, expected_hash in entry["files"].items():
            if digest(args.corpus / relative) != expected_hash:
                raise AssertionError(f"Immutable legacy fixture changed: {relative}")
        for mode in ("fresh", "checkpoint", "journal"):
            expected_path = args.corpus / entry["id"] / ("journal-reference/trace.json" if mode == "journal" else "trace.json")
            expected = json.loads(expected_path.read_text())
            options = {"scenario": entry["scenario"], "backend": entry["backend"], "workers": entry["workers"],
                       "output": str((args.output / f'{entry["id"]}-{mode}').resolve())}
            if mode == "checkpoint":
                options["checkpoint"] = str((args.corpus / entry["id"] / "legacy.json").resolve())
            elif mode == "journal":
                options["journal"] = str((args.corpus / entry["id"] / "journal-prefix.sqlite").resolve())
            run_probe(args.active, options)
            assert_parallel_witness(entry["scenario"], entry["workers"], Path(options["output"]))
            observed = json.loads((Path(options["output"]) / "trace.json").read_text())
            differences = differing_paths(compatibility_projection(expected), compatibility_projection(observed))
            if differences:
                save(args.report or args.output / "report.json", {"schema": "deep-oop-differential-v2", "checks": checks,
                     "status": "FAIL", "failed": {"id": entry["id"], "mode": mode}, "differences": differences,
                     "runtime_capture": RUNTIME_CAPTURE, "runtime_excluded": sorted(RUNTIME_EXCLUDED)})
                raise AssertionError(f'Canonical continuation differs: {entry["id"]}/{mode}; retained raw captures for diagnosis')
            checks.append({"id": entry["id"], "mode": mode, "status": "PASS"})
            print(f'PASS {entry["id"]}/{mode}', flush=True)
    for entry in manifest["entries"]:
        for relative, expected_hash in entry["files"].items():
            if digest(args.corpus / relative) != expected_hash:
                raise AssertionError(f"Comparison modified original evidence: {relative}")
    save(args.report or args.output / "report.json", {"schema": "deep-oop-differential-v2", "checks": checks,
         "status": "PASS", "preserved_prefixes": True, "runtime_capture": RUNTIME_CAPTURE,
         "runtime_excluded": sorted(RUNTIME_EXCLUDED),
         "separately_validated_provenance_paths": list(PROVENANCE_ONLY_PATHS)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe")
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--active", type=Path, default=ROOT / "src")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/deep-oop-refactor/differential")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 2, 4])
    parser.add_argument("--scenarios", nargs="+", choices=sorted(scenarios()))
    args = parser.parse_args()
    if args.probe:
        probe(json.loads(args.probe))
    elif args.capture:
        capture(args)
    else:
        compare(args)


if __name__ == "__main__":
    main()
