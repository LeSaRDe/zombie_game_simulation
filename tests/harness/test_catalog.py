from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.audit_suite import audit, fingerprints
from tests.run_acceptance import main
from tests.suite import load_cases, validate_cases, coverage


class CatalogHarnessTests(unittest.TestCase):
    def test_all_named_requirements_have_cases(self):
        mapped = coverage(load_cases())
        self.assertEqual({k: len(v) for k, v in mapped.items()}, {"actions": 29, "invariants": 25, "gui": 16})
        self.assertTrue(all(ids for group in mapped.values() for ids in group.values()))

    def test_catalog_is_deterministic_and_isolated(self):
        first, second = load_cases(), load_cases()
        self.assertEqual(first, second)
        first[0]["request"]["setup"]["test_mutation"] = True
        self.assertNotIn("test_mutation", second[0]["request"]["setup"])

    def test_invalid_catalog_fails(self):
        original = load_cases()[0]
        for mutation in ("checks", "source", "operator", "tier"):
            c = deepcopy(original)
            if mutation in {"checks", "source"}:
                c[mutation] = []
            elif mutation == "operator":
                c["checks"][0]["op"] = "pretend_pass"
            else:
                c["tier"] = "ignore"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_cases([c])
        with self.assertRaises(ValueError):
            validate_cases([original, original])

    def test_current_source_pins(self):
        result = audit()
        self.assertEqual(result["audit_status"], "PASS")
        self.assertEqual(result["framework_conformance"], "NOT_RUN")

    def test_source_drift_is_rejected(self):
        changed = fingerprints()
        changed[next(iter(changed))] = "wrong"
        with patch("tests.audit_suite.fingerprints", return_value=changed), self.assertRaisesRegex(ValueError, "Specification changed"):
            audit()

    def test_no_adapter_report_is_nonpassing(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            with patch.dict("os.environ", {}, clear=True), redirect_stdout(io.StringIO()):
                status = main(["--report", str(report)])
            self.assertEqual(status, 2)
            observed = json.loads(report.read_text())
            self.assertEqual(observed["status"], "NOT_RUN")
            self.assertEqual(observed["executed"], 0)

    def test_harness_double_cannot_report_conformance(self):
        with redirect_stdout(io.StringIO()):
            status = main(["--adapter", "tests.harness.fakes:factory"])
        self.assertEqual(status, 2)

    def test_listing_is_explicitly_not_execution(self):
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(["--list", "--match", "ACT_melee_success"])
        self.assertEqual(status, 0)
        self.assertIn("Framework conformance: NOT RUN", output.getvalue())
