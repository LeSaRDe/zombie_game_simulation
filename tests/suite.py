"""Load and validate specification cases without loading a product adapter."""
import importlib
import json
from pathlib import Path
import re

from tests.assertions import OPERATORS

ROOT = Path(__file__).resolve().parents[1]
CASE_MODULES = ("actions", "lifecycle_geometry", "systems", "generated", "research", "policies", "formal")
TIERS = {"core", "integration", "browser", "statistical", "performance", "training"}


def load_cases():
    result = []
    for name in CASE_MODULES:
        module = importlib.import_module(f"tests.spec.{name}")
        result.extend(module.cases())
    validate_cases(result)
    return result


def validate_cases(cases):
    identifiers = set()
    for case in cases:
        id = case["id"]
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+", id) or id in identifiers:
            raise ValueError(f"Invalid or duplicate case ID: {id}")
        identifiers.add(id)
        if not case.get("checks") or not case.get("source") or not case.get("requirements"):
            raise ValueError(f"{id}: checks, source and requirements are mandatory")
        if case["tier"] not in TIERS:
            raise ValueError(f"{id}: unsupported tier {case['tier']}")
        request = case["request"]
        if request["kind"] not in {"simulation", "validation", "workflow", "browser"}:
            raise ValueError(f"{id}: unknown request kind")
        if not isinstance(request["steps"], list):
            raise ValueError(f"{id}: steps must be a list")
        for key in ("snapshot_paths", "baseline_paths"):
            for pointer in case.get(key, []):
                if not isinstance(pointer, str) or not pointer.startswith("/"):
                    raise ValueError(f"{id}: invalid {key} pointer")
        for key in ("trial_checks", "performance_checks", "policy_checks", "formal_checks"):
            for item in case.get(key, []):
                if not isinstance(item.get("path"), str) or not item["path"].startswith("/"):
                    raise ValueError(f"{id}: invalid {key} pointer")
        for assertion in case["checks"]:
            if assertion.get("op") not in OPERATORS:
                raise ValueError(f"{id}: unsupported assertion {assertion}")
            path = assertion.get("path")
            if not isinstance(path, str) or (path and not path.startswith("/")):
                raise ValueError(f"{id}: invalid assertion pointer")
            if assertion["op"] in {"same", "different"} and "other_path" not in assertion:
                raise ValueError(f"{id}: comparison missing other_path")
        json.dumps(case, allow_nan=False)


def coverage(cases):
    actions = json.loads((ROOT / "ontology/formal_v0.1/manifest.json").read_text())["actions"]
    groups = {"actions": actions, "invariants": [f"V{i:02}" for i in range(1, 26)],
              "gui": [f"G{i:02}" for i in range(1, 17)]}
    return {group: {item: [c["id"] for c in cases
                          if item in c["actions" if group == "actions" else "requirements"]]
                    for item in items} for group, items in groups.items()}
