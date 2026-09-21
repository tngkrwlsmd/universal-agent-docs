from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "conformance.py"
spec = importlib.util.spec_from_file_location("uad_conformance_runner", RUNNER)
runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)


class LanguageNeutralConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads((ROOT / "POLICY_CONTRACT.json").read_text(encoding="utf-8"))
        cls.schema = json.loads((ROOT / "conformance" / "corpus.schema.json").read_text(encoding="utf-8"))
        cls.result_schema = json.loads((ROOT / "conformance" / "result.schema.json").read_text(encoding="utf-8"))
        cls.coverage = json.loads((ROOT / "conformance" / "coverage.json").read_text(encoding="utf-8"))
        cls.corpora = [
            json.loads((ROOT / "conformance" / name).read_text(encoding="utf-8"))
            for name in ("golden.json", "invalid.json")
        ]
        cls.vectors = [v for corpus in cls.corpora for v in corpus["vectors"]]

    def test_corpora_validate_against_language_neutral_schema(self):
        jsonschema.Draft202012Validator.check_schema(self.schema)
        for corpus in self.corpora:
            jsonschema.validate(corpus, self.schema)
            self.assertEqual("universal-agent-docs-conformance-v2", corpus["format"])
            self.assertEqual(2, corpus["schema_version"])
            self.assertEqual(self.contract["schema_version"], corpus["policy_schema_version"])

    def test_vector_ids_are_globally_unique_and_legacy_ids_are_preserved(self):
        ids = [v["id"] for v in self.vectors]
        self.assertEqual(len(ids), len(set(ids)))
        legacy_ids = {
            "terraform-destroy-is-cloud-delete",
            "git-reset-hard-is-destructive",
            "production-deploy-escalates-l4-x2",
            "terraform-destroy-underreported-as-change",
            "opaque-command-runtime-operation",
            "actual-write-not-covered-by-plan",
        }
        self.assertEqual(set(), legacy_ids - set(ids))

    def test_normative_fields_exist_and_do_not_exact_match_diagnostics(self):
        for vector in self.vectors:
            with self.subTest(vector=vector["id"]):
                self.assertTrue(vector["normative_fields"])
                for pointer in vector["normative_fields"]:
                    runner.json_pointer_get(vector["expected"], pointer)
                    self.assertNotIn(pointer, {"/errors", "/warnings"})
                    self.assertFalse(pointer.startswith("/errors/"))
                    self.assertFalse(pointer.startswith("/warnings/"))

    def test_required_semantic_coverage_is_complete(self):
        covered = {item for v in self.vectors for item in v["covers"]}
        required = set(self.coverage["required_semantics"])
        self.assertEqual(set(), required - covered)

    def test_operation_catalog_has_direct_coverage_or_explicit_exemption(self):
        direct = set()
        for vector in self.vectors:
            data = vector["input"]
            candidates = [data]
            if isinstance(data.get("base"), dict):
                candidates.append(data["base"])
            if isinstance(data.get("boundary"), dict):
                candidates.append(data["boundary"])
            for item in candidates:
                direct.update(item.get("planned_operations", []))
                direct.update(item.get("actual_operations", []))
        catalog = {op["id"] for op in self.contract["routing"]["operation_catalog"]}
        exemptions = set(self.coverage["operation_exemptions"])
        self.assertEqual(set(), catalog - direct - exemptions)
        self.assertEqual(set(), exemptions - catalog)
        self.assertEqual(set(), direct.intersection(exemptions))

    def test_priority_high_risk_operations_have_direct_coverage(self):
        priority = {
            "cloud.resource_change",
            "cloud.resource_delete",
            "database.schema_change",
            "database.destructive_change",
            "credential.rotate",
            "iam.change",
            "external.message_send",
            "service.restart",
            "storage.object_delete",
            "network.configuration_change",
            "artifact.publish",
            "data.export",
            "database.read",
            "git.branch_change",
            "git.commit",
            "git.merge",
            "git.rebase",
        }
        direct = set()
        for vector in self.vectors:
            data = vector["input"]
            candidates = [data]
            if isinstance(data.get("base"), dict):
                candidates.append(data["base"])
            if isinstance(data.get("boundary"), dict):
                candidates.append(data["boundary"])
            for item in candidates:
                direct.update(item.get("planned_operations", []))
                direct.update(item.get("actual_operations", []))
        self.assertEqual(set(), priority - direct)

    def test_reference_runner_passes_entire_corpus(self):
        result = runner.run_suite()
        jsonschema.Draft202012Validator.check_schema(self.result_schema)
        jsonschema.validate(result, self.result_schema)
        self.assertEqual(0, result["summary"]["failed"], [
            (item["id"], item["mismatches"])
            for item in result["results"] if item["status"] == "FAIL"
        ])
        self.assertEqual(len(self.vectors), result["summary"]["total"])

    def test_policy_contract_digest_is_stable_for_key_order(self):
        a = self.contract
        b = {k: a[k] for k in reversed(list(a.keys()))}
        self.assertEqual(
            runner.policy_validate.canonical_policy_contract_digest(a),
            runner.policy_validate.canonical_policy_contract_digest(b),
        )


if __name__ == "__main__":
    unittest.main()
