"""Test the checker using existing reviewed RDF examples and deliberate defects.

These fixtures test the oracle only. Product conformance cases must export their
own executed simulation trace, and cannot return the fixture files as results.
"""
import unittest
from decimal import Decimal

from rdflib import Graph, Literal, Namespace

from tests.assertions import ContractFailure
from tests.formal_checks import PACKAGE, validate_formal_export
from tests.spec.formal import expectations

EX = Namespace("urn:zombie-game:example:")
ZG = Namespace("urn:zombie-game:v0.1:")


def sample(kind):
    filename = "valid_conversion_preserves_identity" if kind == "conversion" else "valid_" + kind
    agents = {"patient": str(EX.patient), "doctor": str(EX.doctor)} if kind == "treatment" else {"h": str(EX.person)}
    value = {"turtle": (PACKAGE / "examples" / (filename + ".ttl")).read_text(),
             "bindings": {"agents": agents, "transition": str(EX.cure if kind == "treatment" else EX[kind])}}
    if kind == "treatment":
        value["bindings"]["occurrence"] = str(EX.treatment)
    # The reviewed examples deliberately cover partial semantics. Their hunger
    # is a static 20 illustration, whereas actual run exports must include the
    # elapsed clock. Adjust only these copied facts, never the package files.
    hunger = ({"doctor_start": "25", "doctor_admitted": "25", "patient_start": "25",
               "doctor_pre_end": "25.2", "doctor_post_end": "25.2",
               "patient_pre_end": "25.2", "patient_post_end": "25.2"} if kind == "treatment" else
              {"human_before": "35"} if kind == "conversion" else {"before": "20.5", "after": "20.5"})
    graph = Graph().parse(data=value["turtle"], format="turtle")
    for state, quantity in hunger.items():
        graph.set((EX[state], ZG.hunger, Literal(Decimal(quantity))))
    value["turtle"] = graph.serialize(format="turtle")
    return value


class FormalHarnessTests(unittest.TestCase):
    def test_positive_examples_with_execution_clock_are_accepted(self):
        for kind in ("treatment", "conversion", "death"):
            with self.subTest(kind=kind):
                validate_formal_export(sample(kind), expectations(kind))

    def test_unchanged_static_example_is_not_an_actual_run_export(self):
        value = sample("conversion")
        value["turtle"] = (PACKAGE / "examples" / "valid_conversion_preserves_identity.ttl").read_text()
        with self.assertRaisesRegex(ContractFailure, "hunger: expected 35"):
            validate_formal_export(value, expectations("conversion"))

    def test_boolean_without_raw_turtle_is_not_evidence(self):
        with self.assertRaisesRegex(ContractFailure, "missing raw Turtle"):
            validate_formal_export({"conforms": True}, expectations("conversion"))

    def test_invalid_turtle_fails_explicitly(self):
        value = sample("death")
        value["turtle"] = "This is not Turtle."
        with self.assertRaisesRegex(ContractFailure, "not valid Turtle"):
            validate_formal_export(value, expectations("death"))

    def test_forged_transition_binding_fails(self):
        value = sample("conversion")
        value["bindings"]["transition"] = str(EX.missing)
        with self.assertRaisesRegex(ContractFailure, "absent or ambiguous"):
            validate_formal_export(value, expectations("conversion"))

    def test_shape_violation_is_checked_by_real_pyshacl(self):
        value = sample("conversion")
        value["turtle"] = (PACKAGE / "examples" / "conversion_heals.ttl").read_text()
        with self.assertRaisesRegex(ContractFailure, "SHACL violations"):
            validate_formal_export(value, expectations("conversion"))

    def test_shacl_valid_but_wrong_life_still_fails_literal_oracle(self):
        value = sample("conversion")
        graph = Graph().parse(data=value["turtle"], format="turtle")
        for state in (EX.human_before, EX.zombie_after):
            graph.set((state, ZG.life, Literal(63)))
        value["turtle"] = graph.serialize(format="turtle")
        # This mutation preserves formal conversion invariants. The literal
        # expected run fact (64) must independently reject it after SHACL passes.
        with self.assertRaisesRegex(ContractFailure, "life: expected 64"):
            validate_formal_export(value, expectations("conversion"))

    def test_identity_binding_cannot_substitute_another_agent(self):
        value = sample("treatment")
        value["bindings"]["agents"]["patient"] = str(EX.doctor)
        with self.assertRaisesRegex(ContractFailure, "share an RDF identity"):
            validate_formal_export(value, expectations("treatment"))

