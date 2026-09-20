from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate.py"
spec = importlib.util.spec_from_file_location("policy_validate_conformance", VALIDATOR)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


class AdapterConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = mod.load_json(ROOT / "POLICY_CONTRACT.json")

    def evaluate(self, vector):
        return mod.evaluate_execution_boundary(
            self.contract,
            vector["planned_operations"],
            vector["actual_operations"],
            vector.get("affected_resources", []),
            vector.get("targets", []),
            vector["environment"],
            None,
            vector.get("runtime_effect"),
            vector.get("actual_action", ""),
            exposure_facts=vector["exposure_facts"],
            correlation_id=f"conformance-{vector['id']}",
            execution_nonce=f"nonce-{vector['id']}-00000001",
            adapter={
                "id": "conformance-adapter",
                "surface": "adapter-conformance-kit",
                "assertion_source": "human_reviewed",
                "version": "1",
            },
            semantic_details=vector.get("semantic_details", {}),
        )

    def test_golden_vectors(self):
        doc = json.loads((ROOT / "conformance" / "golden.json").read_text(encoding="utf-8"))
        self.assertEqual(1, doc["schema_version"])
        for vector in doc["vectors"]:
            with self.subTest(vector=vector["id"]):
                result = self.evaluate(vector)
                for key, expected in vector["expected"].items():
                    self.assertEqual(expected, result.get(key), result)

    def test_invalid_vectors_fail_closed(self):
        doc = json.loads((ROOT / "conformance" / "invalid.json").read_text(encoding="utf-8"))
        self.assertEqual(1, doc["schema_version"])
        for vector in doc["vectors"]:
            with self.subTest(vector=vector["id"]):
                result = self.evaluate(vector)
                self.assertEqual("FAIL", result["status"], result)
                joined = "\n".join(result["errors"])
                self.assertIn(vector["expected_error_contains"], joined, result)

    def test_policy_contract_digest_is_stable_for_key_order(self):
        a = self.contract
        b = {k: a[k] for k in reversed(list(a.keys()))}
        self.assertEqual(mod.canonical_policy_contract_digest(a), mod.canonical_policy_contract_digest(b))


if __name__ == "__main__":
    unittest.main()
