"""Validate actual exported RDF with the existing formal package and literal facts.

Imports are lazy: ordinary test collection does not require the optional RDF
runtime. Selecting a formal case without that runtime fails explicitly.
"""
from pathlib import Path

from tests.assertions import ContractFailure, number

PACKAGE = Path(__file__).resolve().parents[1] / "ontology" / "formal_v0.1"
NAMESPACE = "urn:zombie-game:v0.1:"
ENUM_PROPERTIES = {"biologicalType", "status", "actionStatus", "episodeOutcome", "actionResult"}
KINDS = {"treatment": "CureTransition", "conversion": "ConversionTransition", "death": "DeathTransition"}


def _require(condition, message):
    if not condition:
        raise ContractFailure("Formal export: " + message)


def validate_formal_export(export, spec):
    """Check a capture {turtle, bindings} against a declarative formal_checks item."""
    _require(isinstance(export, dict) and isinstance(export.get("turtle"), str)
             and export["turtle"].strip(), "missing raw Turtle text")
    _require(spec.get("kind") in KINDS, "unknown expected trace kind")
    try:
        from rdflib import Graph, Namespace, URIRef
        from rdflib.namespace import RDF
        from pyshacl import validate
    except ImportError as exc:
        raise ContractFailure("Formal export checks require rdflib and pyshacl; see tests/spec/FORMAL_OPERATIONS.md") from exc
    z = Namespace(NAMESPACE)
    try:
        raw = Graph().parse(data=export["turtle"], format="turtle")
    except Exception as exc:
        raise ContractFailure("Formal export is not valid Turtle") from exc
    _require(len(raw) > 0, "empty RDF graph")
    bindings = export.get("bindings")
    _require(isinstance(bindings, dict) and isinstance(bindings.get("agents"), dict), "missing identity bindings")

    def iri(value, label):
        _require(isinstance(value, str) and ":" in value and not any(c.isspace() for c in value),
                 label + " must bind an absolute IRI")
        return URIRef(value)

    agents = {alias: iri(value, alias) for alias, value in bindings["agents"].items()}
    _require(spec["subject"] in agents, "subject alias has no RDF identity")
    _require(len(set(agents.values())) == len(agents), "distinct aliases share an RDF identity")
    for alias, identity in agents.items():
        _require((identity, RDF.type, z.Agent) in raw, alias + " is not a declared Agent")
    transition = iri(bindings.get("transition"), "transition")
    expected_class = z[KINDS[spec["kind"]]]
    _require(set(raw.subjects(RDF.type, expected_class)) == {transition}, "focused transition is absent or ambiguous")

    # The test owns the validator and trusted schema. Never accept an adapter's
    # boolean, validation report, replacement ontology, or caller-supplied shapes.
    core = Graph().parse(PACKAGE / "ontology.ttl", format="turtle")
    catalog = Graph().parse(PACKAGE / "catalog.ttl", format="turtle")
    shapes = Graph().parse(PACKAGE / "shapes.ttl", format="turtle")
    try:
        conforms, _, report = validate(core + catalog + raw, shacl_graph=shapes,
                                      inference="rdfs", meta_shacl=False, advanced=False,
                                      js=False, do_owl_imports=False)
    except Exception as exc:
        raise ContractFailure("Formal export SHACL execution failed") from exc
    _require(bool(conforms), "SHACL violations:\n" + str(report)[:12000])

    def one(subject, predicate):
        values = list(raw.objects(subject, z[predicate]))
        _require(len(values) == 1, f"{subject} requires one {predicate}; found {len(values)}")
        return values[0]

    def facts(subject, expected):
        for key, value in expected.items():
            actual = one(subject, key)
            if key in ENUM_PROPERTIES:
                _require(actual == z[value], f"{key}: expected {value}, got {actual}")
            else:
                _require(number(str(actual)) == number(value), f"{key}: expected {value}, got {actual}")

    before, after = one(transition, "beforeState"), one(transition, "afterState")
    identity = agents[spec["subject"]]
    _require(one(before, "ofAgent") == one(after, "ofAgent") == identity, "transition changed or misbound identity")
    _require((identity, z.hasState, before) in raw and (identity, z.hasState, after) in raw,
             "before/after states missing from identity history")
    facts(before, spec["before"])
    facts(after, spec["after"])
    if "episode" in spec:
        episode = one(transition, "episode")
        _require(one(episode, "infectedAgent") == identity, "episode belongs to another agent")
        facts(episode, spec["episode"])
        _require(not list(raw.objects(after, z.activeEpisode)), "closed episode remains active")
    if spec["kind"] == "conversion":
        _require(one(before, "activeModel") != one(after, "activeModel"), "conversion reused old model assignment")
        _require(not list(raw.objects(after, z.activeRole)) and not list(raw.objects(after, z.inventory)),
                 "conversion retains human role/inventory")
    elif spec["kind"] == "death":
        for predicate in ("activeModel", "activeRole", "activeAction", "activeEpisode"):
            _require(not list(raw.objects(after, z[predicate])), "death retains " + predicate)
        facts(after, {"death_at": spec["after"]["atTime"], "speed": "0", "sense_r": "0"})
    else:
        _require(spec["actor"] in agents, "treatment actor alias has no identity")
        occurrence = iri(bindings.get("occurrence"), "occurrence")
        _require(one(transition, "triggeredBy") == occurrence, "cure has wrong treatment source")
        _require(one(occurrence, "actionDefinition") == z.action_treat_infection, "wrong action definition")
        facts(occurrence, spec["action"])
        start, end = one(occurrence, "actorStart"), one(occurrence, "actorAfterEnd")
        _require(one(start, "ofAgent") == one(end, "ofAgent") == agents[spec["actor"]], "treatment actor identity mismatch")
        _require(one(occurrence, "targetBeforeEnd") == before and one(occurrence, "targetAfterEnd") == after,
                 "treatment target states differ from cure transition")
        facts(start, spec["actor_start"])
        facts(end, spec["actor_after"])
        for state, expected in [(start, spec["medical_before"]), (end, spec["medical_after"])]:
            inventory = one(state, "inventory")
            stocks = [s for s in raw.objects(inventory, z.stock) if (s, z.resourceType, z.MEDICAL_SUPPLY) in raw]
            _require(len(stocks) == 1, "missing/duplicate medical stock")
            facts(stocks[0], {"quantity": expected, "reserved": 0})

