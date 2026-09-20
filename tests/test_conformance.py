from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "conformance" / "reference_runner.py"
SPEC = importlib.util.spec_from_file_location("uad_conformance_runner", RUNNER)
runner = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


class LanguageNeutralConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads((ROOT / "POLICY_CONTRACT.json").read_text(encoding="utf-8"))
        cls.suite = json.loads((ROOT / "conformance" / "suite.json").read_text(encoding="utf-8"))
        cls.schema = json.loads((ROOT / "conformance" / "schema.json").read_text(encoding="utf-8"))
        cls.result_schema = json.loads((ROOT / "conformance" / "result.schema.json").read_text(encoding="utf-8"))

    def test_suite_schema_and_stable_unique_ids(self):
        jsonschema.validate(self.suite, self.schema)
        ids = [case["id"] for case in self.suite["cases"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(2, self.suite["conformance_version"])
        self.assertEqual(self.contract["schema_version"], self.suite["contract_schema_version"])

    def test_reference_runner_passes_entire_suite(self):
        result = runner.run_suite()
        jsonschema.validate(result, self.result_schema)
        self.assertEqual(result["summary"]["total"], result["summary"]["passed"], result)
        self.assertEqual(0, result["summary"]["failed"], result)

    def test_legacy_vector_ids_are_preserved(self):
        legacy = set()
        for name in ["golden.json", "invalid.json"]:
            doc = json.loads((ROOT / "conformance" / name).read_text(encoding="utf-8"))
            legacy.update(vector["id"] for vector in doc["vectors"])
        current = {case["id"] for case in self.suite["cases"]}
        self.assertEqual(set(), legacy - current)

    def test_normative_expectations_do_not_match_diagnostic_text(self):
        for case in self.suite["cases"]:
            with self.subTest(case=case["id"]):
                self.assertNotIn("errors", case["normative_fields"])
                self.assertNotIn("warnings", case["normative_fields"])
                self.assertNotIn("expected_error_contains", case["expected"])

    def test_required_semantic_categories_are_covered(self):
        categories = {case["category"] for case in self.suite["cases"]}
        required = {
            "routing", "operation_lifecycle", "execution_boundary",
            "execution_boundary_invalid", "exposure", "target_requirements",
            "action_signature", "plan_binding", "action_digest",
            "approval", "approval_replay", "override", "override_replay",
            "readiness", "distribution", "integrity",
        }
        self.assertEqual(set(), required - categories)

    def test_operation_catalog_has_explicit_coverage_or_exemption(self):
        catalog = {item["id"] for item in self.contract["routing"]["operation_catalog"]}
        covered = {
            op
            for case in self.suite["cases"]
            for key in ("planned_operations", "actual_operations")
            for op in case["input"].get(key, [])
            if op in catalog
        }
        exemptions = set(self.suite["operation_coverage_exemptions"])
        self.assertEqual(set(), covered & exemptions)
        self.assertEqual(catalog, covered | exemptions)
        deprecated = {
            item["id"] for item in self.contract["routing"]["operation_catalog"]
            if item.get("lifecycle_status") == "deprecated"
        }
        self.assertEqual(set(), deprecated - covered, "deprecated operations require dedicated conformance coverage")

    def test_coverage_exemptions_have_rationales(self):
        for operation, reason in self.suite["operation_coverage_exemptions"].items():
            with self.subTest(operation=operation):
                self.assertTrue(reason.strip())
                self.assertGreaterEqual(len(reason.strip()), 20)

    def test_result_protocol_contains_only_normative_observations(self):
        result = runner.run_suite()
        cases = {case["id"]: case for case in self.suite["cases"]}
        for item in result["results"]:
            with self.subTest(case=item["id"]):
                self.assertEqual(
                    set(cases[item["id"]]["normative_fields"]),
                    set(item["observed"]),
                )


if __name__ == "__main__":
    unittest.main()
