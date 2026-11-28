"""Catalog imported from the original RDF/XML; no hand-maintained action registry."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET

NS = "urn:zombie-game:v0.1:"
ROOT = Path(__file__).resolve().parents[2]
_SOURCE_ONTOLOGY = ROOT / "ontology/formal_v0.1"
ONTOLOGY_DIR = Path(os.environ.get("ZOMBIE_ONTOLOGY_DIR", _SOURCE_ONTOLOGY if _SOURCE_ONTOLOGY.is_dir() else Path(__file__).parent / "spec/formal_v0.1"))
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
XSD = "http://www.w3.org/2001/XMLSchema#"


def _local(value):
    return value.removeprefix(NS).removeprefix("urn:zombie-game:baseline:")


def _xml_catalog(directory=None):
    directory = ONTOLOGY_DIR if directory is None else Path(directory)
    graph = {}
    for node in ET.parse(directory / "ontology.owl").getroot():
        subject = node.attrib.get("{" + RDF + "}about")
        if not subject:
            continue
        props = graph.setdefault(_local(subject), {})
        for prop in node:
            key = prop.tag.split("}", 1)[-1]
            resource = prop.attrib.get("{" + RDF + "}resource")
            if resource:
                value = _local(resource)
            elif len(prop):
                continue
            else:
                value = prop.text or ""
                datatype = prop.attrib.get("{" + RDF + "}datatype", "")
                if datatype.endswith("integer"):
                    value = int(value)
                elif datatype.endswith(("decimal", "double", "float")):
                    value = float(value)
                elif datatype.endswith("boolean"):
                    value = value in ("true", "1")
            props.setdefault(key, []).append(value)
    return graph

def _named_turtle(path):
    """Read the simple named-node Turtle used by baseline.ttl, fail on other syntax.

    This importer intentionally accepts only the published baseline's grammar; full
    RDF parsing/validation is available through rdflib in the export command.
    """
    text = Path(path).read_text()
    text = re.sub(r"@prefix[^\n]+", "", text)
    token_re = re.compile(r'"(?:[^"\\]|\\.)*"|[A-Za-z_][\w-]*:[\w-]+|[+-]?\d+\.\d+|[+-]?\d+|true\b|false\b|a\b|[;,.]')
    tokens = token_re.findall(text)
    remainder = token_re.sub("", text)
    if remainder.strip():
        raise ValueError("Unsupported syntax in authoritative baseline Turtle")
    graph, i = {}, 0
    while i < len(tokens):
        subject = tokens[i].split(":", 1)[-1]; i += 1
        props = graph.setdefault(subject, {})
        while True:
            predicate = tokens[i].split(":", 1)[-1]; i += 1
            while True:
                raw = tokens[i]; i += 1
                if raw.startswith('"'):
                    value = json.loads(raw)
                elif raw in ("true", "false"):
                    value = raw == "true"
                elif ":" in raw:
                    value = raw.split(":", 1)[-1]
                else:
                    value = float(raw) if "." in raw else int(raw)
                props.setdefault(predicate, []).append(value)
                if tokens[i] != ",":
                    break
                i += 1
            sep = tokens[i]; i += 1
            if sep == ".":
                break
            if sep != ";":
                raise ValueError("Unsupported baseline Turtle separator")
    return graph

class OntologyCatalog:
    """One validated formal catalog, with explicit source and provenance roots.

    The ontology remains authoritative. Construction imports RDF/XML and verifies
    every executable action/role against the manifest and canonical Turtle.
    """

    def __init__(self, directory=None, *, project_root=None):
        self.directory = Path(ONTOLOGY_DIR if directory is None else directory)
        self.project_root = Path(ROOT if project_root is None else project_root)
        self.graph = _xml_catalog(self.directory)
        self.manifest = json.loads((self.directory / "manifest.json").read_text())
        self.roles = {}
        for _name, _props in self.graph.items():
            if any(t in ("HumanRoleDefinition", "ZombieRoleDefinition") for t in _props.get("type", [])):
                self.roles[_name] = {k: v[0] for k, v in _props.items() if k not in ("type", "grants", "label")}
                self.roles[_name]["type"] = self.roles[_name].pop("compatibleType")
                self.roles[_name]["actions"] = sorted(v.removeprefix("cap_") for v in _props.get("grants", []))
        self.type_actions = {kind: sorted(x.removeprefix("cap_") for x in self.graph[kind].get("grants", [])) for kind in ("Human", "Zombie")}
        self.actions = {}
        for _name, _props in self.graph.items():
            if "ActionDefinition" in _props.get("type", []):
                _action = _name.removeprefix("action_")
                _entry = {k: v[0] for k, v in _props.items() if k not in ("type", "label", "mayCause")}
                _entry["duration"] = _entry["duration_min"]
                _entry["cost"] = _entry["stamina_cost"]
                _entry["types"] = [t for t, actions in self.type_actions.items() if _action in actions]
                _entry["roles"] = [r for r, values in self.roles.items() if _action in values["actions"]]
                _entry["type"] = _entry["types"][0] if len(_entry["types"]) == 1 else None
                _entry["role"] = _entry["roles"][0] if len(_entry["roles"]) == 1 else None
                self.actions[_action] = _entry
        if set(self.actions) != set(self.manifest["actions"]) or set(self.roles) != set(self.manifest["roles"]):
            raise RuntimeError("Ontology registry mismatch: imported actions/roles differ from manifest")


        _CATALOG_GRAPH = _named_turtle(self.directory / "catalog.ttl")
        for _subject in ["action_" + name for name in self.actions] + list(self.roles):
            for _predicate, _values in _CATALOG_GRAPH[_subject].items():
                _xml_values = self.graph[_subject].get("type" if _predicate == "a" else _predicate, [])
                if sorted(map(str, _values)) != sorted(map(str, _xml_values)):
                    raise RuntimeError(f"Catalog Turtle/RDF-XML disagreement at {_subject}.{_predicate}; review ontology provenance")

    def source_hashes(self):
        paths = {name: self.directory / name for name in ("ontology.ttl", "ontology.owl", "catalog.ttl", "baseline.ttl", "shapes.ttl", "manifest.json")}
        paths.update({"ontology_markdown": self.directory.parent / "zombie_game_ontology_v0.1.md", "requirements": self.project_root / "prompts/zombie_game_plans.md", "implementation_plan": self.project_root / "prompts/task_2_implementation_plan.md", "action_matrix": self.project_root / "prompts/task_2_action_and_validation_matrix.md"})
        return {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in paths.items() if path.is_file()}

    def provenance(self):
        hashes = self.source_hashes()
        return {"ontology_version": self.manifest["ontology_version"], "source_hashes": hashes,
                "registry_actions": sorted(self.actions), "registry_roles": sorted(self.roles),
                "ontology_source_matches_manifest": hashes.get("ontology_markdown") == self.manifest["source_sha256"],
                "plan_source_matches_manifest": hashes.get("requirements") == self.manifest["source_plan_sha256"],
                "plan_provenance_note": "Formal package is preserved. Current requirements hash is recorded independently; the historical formal validation is not claimed as current."}

    def baseline_graph(self):
        return _named_turtle(self.directory / "baseline.ttl")


DEFAULT_CATALOG = OntologyCatalog()
# Public compatibility names refer to the validated catalog's owned records.
_GRAPH = DEFAULT_CATALOG.graph
MANIFEST = DEFAULT_CATALOG.manifest
ROLES = DEFAULT_CATALOG.roles
TYPE_ACTIONS = DEFAULT_CATALOG.type_actions
ACTIONS = DEFAULT_CATALOG.actions


def source_hashes():
    return DEFAULT_CATALOG.source_hashes()


def provenance():
    return DEFAULT_CATALOG.provenance()


def baseline_graph():
    return DEFAULT_CATALOG.baseline_graph()
