"""Independent checks for I11's metadata and preserved model assignments."""
from __future__ import annotations

import argparse
import ast
import builtins
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import random
import sys
import tempfile
from unittest.mock import patch

from zombie_sim import Simulation
from zombie_sim import policies
from zombie_sim import model_catalog as catalog_module
from zombie_sim.config import DEFAULTS, ConfigError, baseline_config, initialize_world, resolve_config
from zombie_sim.config_io import dumps, loads
from zombie_sim.domain import make_agent
from zombie_sim.server import create_app


def check(output: Path, before: Path | None):
    report = {"passed": False, "checks": {}}
    registry, declarations = dict(policies._REGISTRY), deepcopy(catalog_module._MODEL_METADATA)
    try:
        original_defaults = deepcopy(DEFAULTS)
        catalog = catalog_module.model_catalog()
        assert len(catalog["choices"]) == 3
        assert len(catalog["registered_names"]) == 8
        choices = {entry["model_id"]: entry for entry in catalog["choices"]}
        checked_aliases = []
        for choice in catalog["choices"]:
            for alias in choice["aliases"]:
                model = policies.create_model(alias)
                manifest = model.manifest()
                assert manifest["model_id"] == choice["model_id"]
                assert manifest["model_version"] == choice["version"]
                assert sorted(manifest["applicable_types"]) == choice["applicable_types"]
                checked_aliases.append(alias)
        assert choices["defaultHuman/v1"]["aliases"] == ["HumanDefaultModel", "defaultHuman", "defaultHuman/v1"]
        assert choices["defaultZombie/v1"]["aliases"] == ["ZombieDefaultModel", "defaultZombie", "defaultZombie/v1"]
        assert catalog["defaults"] == {"Human": "HumanDefaultModel", "Zombie": "ZombieDefaultModel"}
        report["checks"]["catalog_matches_installed_manifests"] = checked_aliases

        # Poison factories to make an accidental instantiation fail immediately.
        factory_calls = []
        def never_construct(parameters=None):
            factory_calls.append(parameters)
            raise AssertionError("A metadata request instantiated a model")
        descriptor = {"model_id": "guidePlugin/v2", "label": "Guide plugin", "version": "2.3.0",
                      "applicable_types": ["Human"], "description": "Declared without loading its weights."}
        catalog_module.register_model("guidePlugin/v2", never_construct, metadata=descriptor)
        catalog_module.register_model("guidePlugin", never_construct, metadata=descriptor)
        descriptor["version"] = "MUTATED"
        descriptor["applicable_types"].append("Zombie")
        catalog_module.register_model("legacyPlugin", never_construct)
        plugin_catalog = catalog_module.model_catalog()
        plugin_choice = next(c for c in plugin_catalog["choices"] if c["model_id"] == "guidePlugin/v2")
        assert plugin_choice["version"] == "2.3.0" and plugin_choice["applicable_types"] == ["Human"]
        assert plugin_choice["aliases"] == ["guidePlugin", "guidePlugin/v2"]
        assert "legacyPlugin" in plugin_catalog["registered_names"]
        assert not any("legacyPlugin" in c["aliases"] for c in plugin_catalog["choices"])
        plugin_choice["aliases"].append("fakeAlias")
        plugin_choice["applicable_types"].append("Zombie")
        assert "fakeAlias" not in json.dumps(catalog_module.model_catalog())

        # Replacing an alias must not keep the old implementation's label/version.
        catalog_module.register_model("guidePlugin", lambda p: None, replace=True)
        after_replace = catalog_module.model_catalog()
        assert next(c for c in after_replace["choices"] if c["model_id"] == "guidePlugin/v2")["aliases"] == ["guidePlugin/v2"]
        # Conflicting declarations do not become duplicate or mislabeled choices.
        conflict = {"model_id": "guidePlugin/v2", "label": "Different implementation", "version": "4.0",
                    "applicable_types": ["Zombie"]}
        catalog_module.register_model("conflictingPlugin", lambda p: None, metadata=conflict)
        assert not any(c["model_id"] == "guidePlugin/v2" for c in catalog_module.model_catalog()["choices"])
        assert "guidePlugin/v2" in catalog_module.model_catalog()["registered_names"]

        policies.register_model("HumanDefaultModel", never_construct, replace=True)
        legacy_replacement = catalog_module.model_catalog()
        assert not any("HumanDefaultModel" in c["aliases"] for c in legacy_replacement["choices"])
        policies._REGISTRY["HumanDefaultModel"] = registry["HumanDefaultModel"]

        invalid = [{}, {"model_id": "x", "label": "X", "version": "1", "applicable_types": []},
                   {"model_id": "x", "label": "X", "version": "1", "applicable_types": ["Human", "Human"]},
                   {"model_id": "x", "label": "X", "version": "1", "applicable_types": ["Animal"]},
                   {"model_id": "x", "label": "X", "version": "1", "applicable_types": ["Human"], "description": 5}]
        for value in invalid:
            before_registry, before_metadata = dict(policies._REGISTRY), deepcopy(catalog_module._MODEL_METADATA)
            try:
                catalog_module.register_model("HumanDefaultModel", never_construct, replace=True, metadata=value)
            except ValueError:
                pass
            else:
                raise AssertionError("Invalid metadata accepted")
            assert policies._REGISTRY == before_registry and catalog_module._MODEL_METADATA == before_metadata
        report["checks"]["plugin_metadata"] = {"legacy_advanced_only": True, "declarations_and_catalog_detached": True,
                                              "replacement_drops_stale_metadata": True, "conflicts_advanced_only": True,
                                              "legacy_api_replacement_invalidates_metadata": True, "invalid_replacement_rollbacks": len(invalid)}

        with tempfile.TemporaryDirectory(prefix="zombie-issue11-models-") as temporary:
            temp = Path(temporary)
            app = create_app(temp / "workspace")
            endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/api/config")
            original_import = builtins.__import__
            def block_heavy(name, *args, **kwargs):
                if name in {"torch", "numpy", "learning", "zombie_sim.learning"}:
                    raise AssertionError(f"Metadata imported {name}")
                return original_import(name, *args, **kwargs)
            try:
                with patch.object(policies, "create_model", never_construct), patch("builtins.__import__", block_heavy):
                    metadata = endpoint()
                assert metadata["models"] == catalog_module.model_catalog()
                assert {"human_model", "zombie_model"} <= {field["path"] for field in metadata["fields"]}
                assert "human_model" not in metadata["presets"]["small"]
                assert "zombie_model" not in metadata["presets"]["baseline"]
                assert factory_calls == []
                report["checks"]["metadata_no_model_or_dependency_load"] = True
            finally:
                app.state.exports.close()
                app.state.manager.close()

            # Restore the normal registry before initialization checks.
            policies._REGISTRY.clear(); policies._REGISTRY.update(registry)
            catalog_module._MODEL_METADATA.clear(); catalog_module._MODEL_METADATA.update(declarations)
            actual_worlds = {}
            for name, config in (("small", DEFAULTS), ("baseline", baseline_config())):
                resolved_before = resolve_config(config)
                world = initialize_world(config)
                for agent in world["agents"].values():
                    assignment = agent["model_assignment"]
                    expected = catalog["defaults"][agent["type"]]
                    choice = next(c for c in catalog["choices"] if expected in c["aliases"])
                    assert assignment == {"model_id": expected, "version": choice["version"]}
                assert resolve_config(config) == resolved_before
                actual_worlds[name] = len(world["agents"])
            assert actual_worlds == {"small": 20, "baseline": 1000}
            assert DEFAULTS == original_defaults
            report["checks"]["untouched_preset_assignments"] = actual_worlds

            round_trips = 0
            for field, aliases in (("human_model", choices["defaultHuman/v1"]["aliases"]),
                                   ("zombie_model", choices["defaultZombie/v1"]["aliases"])):
                for alias in aliases:
                    raw = {field: alias, "seed": 123, "horizon": 4}
                    expected = resolve_config(raw)
                    for format in ("json", "toml"):
                        parsed = loads(dumps(raw, format), format)
                        assert parsed == raw and resolve_config(parsed)["fingerprint"] == expected["fingerprint"]
                        round_trips += 1
            explicit = {"seed": 7, "human_model": "randomLegal/v1", "zombie_model": "randomLegal/v1", "agents": [
                {"id": "h", "type": "Human", "x": 10, "y": 10,
                 "model_assignment": {"model_id": "defaultHuman", "version": "1", "parameters": {"weights": {"survival": 9}}}},
                {"id": "z", "type": "Zombie", "x": 80, "y": 80,
                 "model_assignment": {"model_id": "defaultZombie/v1", "version": "1.1.0", "parameters": {"memory_ttl": 35}}}]}
            for format in ("json", "toml"):
                assert loads(dumps(explicit, format), format) == explicit
            world = initialize_world(explicit)
            assert world["agents"]["h"]["model_assignment"] == {
                "model_id": "defaultHuman", "version": "1.1.0", "requested_version": "1", "parameters": {"weights": {"survival": 9}}}
            assert world["agents"]["z"]["model_assignment"] == {
                "model_id": "defaultZombie/v1", "version": "1.1.0", "parameters": {"memory_ttl": 35}}
            report["checks"]["alias_and_explicit_agent_preservation"] = {"alias_round_trips": round_trips, "explicit_agent_round_trips": 2}

            errors = []
            for field in ("human_model", "zombie_model"):
                for identifier in ("", "unknownPolicy/v1", f"ppo:{temp / 'missing-artifact'}"):
                    try:
                        resolve_config({field: identifier})
                    except ConfigError as error:
                        assert error.code == "MODEL_UNAVAILABLE" and str(error).startswith(field + ":")
                        errors.append(str(error))
                    else:
                        raise AssertionError("Unavailable model accepted")
            artifact = temp / "artifact"; artifact.mkdir(); (artifact / "manifest.json").write_text("{}")
            def missing_torch(name, *args, **kwargs):
                if name == "torch":
                    raise ModuleNotFoundError("No module named 'torch'", name="torch")
                return original_import(name, *args, **kwargs)
            with patch("builtins.__import__", missing_torch):
                try:
                    resolve_config({"human_model": f"ppo:{artifact}"})
                except ConfigError as error:
                    assert error.code == "MODEL_UNAVAILABLE" and "required dependencies" in str(error) and "torch" in str(error)
                    errors.append(str(error))
                else:
                    raise AssertionError("Missing dependency accepted")
            report["checks"]["unavailable_selection_feedback"] = errors

            # Exercise a real alternative policy on both biological types.
            alternative = {"seed": 123, "horizon": 3, "human_model": "randomLegal/v1", "zombie_model": "randomLegal/v1", "execution": {"workers": 1}}
            with Simulation(alternative, history_path=str(temp / "alternative.sqlite")) as simulation:
                assert all(agent["model_assignment"]["model_id"] == "randomLegal/v1" for agent in simulation.snapshot()["agents"].values())
                simulation.advance_until(2, return_snapshot=False)
                assert str(simulation.time) == "2"
                report["checks"]["actual_alternative_simulation"] = {"agents": 20, "time": str(simulation.time), "revision": simulation.revision}

            if before:
                # Compare actual candidate decisions with the pre-I11 implementation.
                old_file = before / "src/zombie_sim/policies.py"
                spec = importlib.util.spec_from_file_location("zombie_sim._before_issue11_policies", old_file)
                old = importlib.util.module_from_spec(spec); sys.modules[spec.name] = old; spec.loader.exec_module(old)
                old_ast, new_ast = ast.parse(old_file.read_text()), ast.parse(Path(policies.__file__).read_text())
                old_items = {node.name: ast.dump(node, include_attributes=False) for node in old_ast.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
                new_items = {node.name: ast.dump(node, include_attributes=False) for node in new_ast.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
                unchanged = list(old_items)
                assert old_file.read_bytes() == Path(policies.__file__).read_bytes()
                assert all(old_items[name] == new_items[name] for name in unchanged)
                decisions = 0
                for kind in ("Human", "Zombie"):
                    actor = make_agent("a", kind, x=20, y=20)
                    other = make_agent("b", "Zombie" if kind == "Human" else "Human", x=21, y=20)
                    observation = {"time": "0", "world": {"length": 100, "width": 100}, "self_state": actor,
                                   "local_agents": {"b": other}, "local_environment": {"barriers": {}, "stockpiles": {}, "remains": {}}, "received_signals": []}
                    for name in (catalog["defaults"][kind], "randomLegal/v1"):
                        for seed in (0, 1, 12, 321):
                            assert old.choose(deepcopy(observation), None, random.Random(seed), name) == policies.choose(deepcopy(observation), None, random.Random(seed), name)
                            decisions += 1
                checkpoint = temp / "before-issue11.json"
                with patch.object(policies, "create_model", old.create_model):
                    with Simulation({"seed": 123, "horizon": 4, "execution": {"workers": 1}}, history_path=str(temp / "before-issue11.sqlite")) as historical:
                        historical.advance_until(1, return_snapshot=False)
                        historical.checkpoint(checkpoint)
                        old_revision = historical.revision
                frozen_files = {path: path.read_bytes() for path in temp.glob("before-issue11*") if path.is_file()}
                frozen_files.update({path: path.read_bytes() for path in checkpoint.with_suffix(".models").iterdir()})
                with Simulation.restore(checkpoint) as restored:
                    assert str(restored.time) == "1" and restored.revision == old_revision
                    restored.advance_until(2, return_snapshot=False)
                    assert str(restored.time) == "2"
                assert all(path.read_bytes() == data for path, data in frozen_files.items())
                report["checks"]["prior_behavior_preserved"] = {"policies_source_byte_identical": True,
                    "unchanged_function_and_class_asts": len(unchanged), "identical_seeded_decisions": decisions,
                    "pre_issue11_checkpoint_restored_and_advanced": True, "historical_files_unchanged": len(frozen_files)}
        report["temporary_workspace_removed"] = not temp.exists()
        report["passed"] = True
    finally:
        policies._REGISTRY.clear(); policies._REGISTRY.update(registry)
        catalog_module._MODEL_METADATA.clear(); catalog_module._MODEL_METADATA.update(declarations)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "report": str(output)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/issue11-models.json"))
    parser.add_argument("--before", type=Path)
    args = parser.parse_args()
    check(args.output, args.before)
