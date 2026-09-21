from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "policy_diff.py"
spec = importlib.util.spec_from_file_location("uad_policy_diff", SCRIPT)
policy_diff = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = policy_diff
spec.loader.exec_module(policy_diff)


class PolicyDiffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads((ROOT / "POLICY_CONTRACT.json").read_text(encoding="utf-8"))

    def test_additive_operation_is_not_automatically_breaking(self):
        after = copy.deepcopy(self.contract)
        after["routing"]["operation_catalog"].append({
            "id": "example.new_operation", "policies": ["implementation"],
            "effect_floor": "L1", "requires_execution_policy": False, "lifecycle_status": "active",
        })
        result = policy_diff.compare_contracts(self.contract, after)
        self.assertEqual(1, result["summary"]["additive"])
        self.assertFalse(result["requires_consumer_migration"])

    def test_effect_floor_change_is_breaking_enforcement(self):
        after = copy.deepcopy(self.contract)
        operation = next(x for x in after["routing"]["operation_catalog"] if x["id"] == "code.modify")
        operation["effect_floor"] = "L3"
        result = policy_diff.compare_contracts(self.contract, after)
        self.assertEqual(1, result["summary"]["breaking_enforcement"])
        self.assertTrue(result["requires_consumer_migration"])

    def test_schema_bump_and_removed_operation_are_reported(self):
        after = copy.deepcopy(self.contract)
        after["schema_version"] += 1
        after["routing"]["operation_catalog"] = [x for x in after["routing"]["operation_catalog"] if x["id"] != "code.modify"]
        result = policy_diff.compare_contracts(self.contract, after)
        self.assertEqual(1, result["summary"]["breaking_schema"])
        self.assertEqual(1, result["summary"]["removed_operation"])

    def test_schema_required_field_addition_is_breaking_schema(self):
        before_schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": []}
        after_schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
        result = policy_diff.compare_contracts(
            self.contract, self.contract, before_schema=before_schema, after_schema=after_schema
        )
        self.assertEqual(1, result["summary"]["breaking_schema"])
        self.assertEqual("breaking", result["compatibility"])



if __name__ == "__main__":
    unittest.main()
