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

    def _changed(self, path, value):
        after = copy.deepcopy(self.contract)
        node = after
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
        return policy_diff.compare_contracts(self.contract, after)

    def assertBreakingPath(self, result, suffix):
        self.assertTrue(result["requires_consumer_migration"], result)
        self.assertEqual("breaking", result["compatibility"], result)
        self.assertTrue(any(c["classification"] == "breaking_enforcement" and c["path"].endswith(suffix) for c in result["changes"]), result)

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
        self.assertGreaterEqual(result["summary"]["breaking_enforcement"], 1)
        self.assertTrue(result["requires_consumer_migration"])

    def test_security_sensitive_execution_and_override_semantics_are_never_silent(self):
        cases = [
            (("execution_boundary", "approval_max_ttl_seconds"), 1200, "approval_max_ttl_seconds"),
            (("execution_boundary", "approval_replay_protection", "single_use_required"), False, "single_use_required"),
            (("execution_boundary", "approval_replay_protection", "execution_nonce_required"), False, "execution_nonce_required"),
            (("execution_boundary", "approval_replay_protection", "authorization_requires_atomic_consumption"), False, "authorization_requires_atomic_consumption"),
            (("protected_override", "max_ttl_seconds"), 600, "max_ttl_seconds"),
            (("protected_override", "exact_action_binding_required"), False, "exact_action_binding_required"),
            (("protected_override", "task_approval_required"), False, "task_approval_required"),
            (("protected_override", "issuer_must_be_higher_authority"), False, "issuer_must_be_higher_authority"),
            (("execution_boundary", "target_required_effect_levels"), ["L4"], "target_required_effect_levels"),
            (("execution_boundary", "runtime_forbidden_operations"), [], "runtime_forbidden_operations"),
            (("execution_boundary", "action_digest_binds"), self.contract["execution_boundary"]["action_digest_binds"][:-1], "action_digest_binds"),
            (("execution_boundary", "trusted_assertion_sources"), ["tool_adapter"], "trusted_assertion_sources"),
        ]
        for path, value, suffix in cases:
            with self.subTest(path=path):
                self.assertBreakingPath(self._changed(path, value), suffix)

    def test_exposure_derivation_and_decision_matrix_changes_are_breaking(self):
        after = copy.deepcopy(self.contract)
        after["execution_boundary"]["exposure_derivation"]["fact_floors"]["credential_class"]["user_secret"] = "X2"
        result = policy_diff.compare_contracts(self.contract, after)
        self.assertBreakingPath(result, "credential_class.user_secret")

        after = copy.deepcopy(self.contract)
        after["risk_model"]["decision_matrix"]["L2"]["X1"] = "REQUIRE_EXPLICIT_APPROVAL"
        result = policy_diff.compare_contracts(self.contract, after)
        self.assertBreakingPath(result, "risk_model.decision_matrix.L2.X1")

    def test_schema_bump_and_removed_operation_are_reported(self):
        after = copy.deepcopy(self.contract)
        after["schema_version"] += 1
        after["routing"]["operation_catalog"] = [x for x in after["routing"]["operation_catalog"] if x["id"] != "code.modify"]
        result = policy_diff.compare_contracts(self.contract, after)
        self.assertEqual(1, result["summary"]["breaking_schema"])
        self.assertEqual(1, result["summary"]["removed_operation"])

    def _schema_result(self, before_schema, after_schema):
        return policy_diff.compare_contracts(
            self.contract, self.contract, before_schema=before_schema, after_schema=after_schema
        )

    def test_schema_required_field_addition_and_removal(self):
        base = {"type": "object", "properties": {"a": {"type": "string"}}, "required": []}
        added = copy.deepcopy(base); added["required"] = ["a"]
        result = self._schema_result(base, added)
        self.assertGreaterEqual(result["summary"]["breaking_schema"], 1)
        removed = self._schema_result(added, base)
        self.assertGreaterEqual(removed["summary"]["backward_compatible"], 1)

    def test_schema_enum_type_const_and_additional_properties(self):
        cases = [
            ({"enum": ["a", "b"]}, {"enum": ["a"]}, "breaking_schema"),
            ({"enum": ["a"]}, {"enum": ["a", "b"]}, "backward_compatible"),
            ({"type": "string"}, {"type": "integer"}, "breaking_schema"),
            ({"const": 1}, {"const": 2}, "breaking_schema"),
            ({"type": "object", "additionalProperties": True}, {"type": "object", "additionalProperties": False}, "breaking_schema"),
        ]
        for before, after, expected in cases:
            with self.subTest(before=before, after=after):
                result = self._schema_result(before, after)
                self.assertGreaterEqual(result["summary"][expected], 1, result)

    def test_schema_bounds_and_patterns_are_conservative(self):
        self.assertGreaterEqual(self._schema_result({"type": "number", "minimum": 0}, {"type": "number", "minimum": 1})["summary"]["breaking_schema"], 1)
        self.assertGreaterEqual(self._schema_result({"type": "string"}, {"type": "string", "pattern": "^[a-z]+$"})["summary"]["breaking_schema"], 1)
        changed_pattern = self._schema_result({"type": "string", "pattern": "^a"}, {"type": "string", "pattern": "a$"})
        self.assertGreaterEqual(changed_pattern["summary"]["behavioral"], 1)

    def test_composite_schema_change_requires_manual_review(self):
        before = {"oneOf": [{"type": "string"}, {"type": "integer"}]}
        after = {"oneOf": [{"type": "string"}, {"type": "number"}]}
        result = self._schema_result(before, after)
        self.assertGreaterEqual(result["summary"]["behavioral"], 1)
        self.assertEqual("compatible_change", result["compatibility"])


    def test_schema_type_constraint_add_remove_widen_narrow_and_replace(self):
        cases = [
            ({}, {"type": "string"}, "breaking_schema", True),
            ({"type": "string"}, {}, "backward_compatible", False),
            ({"type": "string"}, {"type": ["string", "null"]}, "backward_compatible", False),
            ({"type": ["string", "null"]}, {"type": "string"}, "breaking_schema", True),
            ({"type": "string"}, {"type": "integer"}, "breaking_schema", True),
        ]
        for before_schema, after_schema, classification, migration in cases:
            with self.subTest(before=before_schema, after=after_schema):
                result = policy_diff.compare_contracts(
                    self.contract, self.contract, before_schema=before_schema, after_schema=after_schema
                )
                self.assertGreater(result["summary"][classification], 0, result)
                self.assertEqual(migration, result["requires_consumer_migration"], result)
                self.assertEqual("breaking" if migration else "compatible_change", result["compatibility"], result)

    def test_schema_enum_constraint_add_remove_widen_narrow_and_mixed(self):
        cases = [
            ({"type": "string"}, {"type": "string", "enum": ["a", "b"]}, "breaking_schema", True),
            ({"enum": ["a", "b"]}, {}, "backward_compatible", False),
            ({"enum": ["a"]}, {"enum": ["a", "b"]}, "backward_compatible", False),
            ({"enum": ["a", "b"]}, {"enum": ["a"]}, "breaking_schema", True),
            ({"enum": ["a", "b"]}, {"enum": ["b", "c"]}, "behavioral", False),
        ]
        for before_schema, after_schema, classification, migration in cases:
            with self.subTest(before=before_schema, after=after_schema):
                result = policy_diff.compare_contracts(
                    self.contract, self.contract, before_schema=before_schema, after_schema=after_schema
                )
                self.assertGreater(result["summary"][classification], 0, result)
                self.assertEqual(migration, result["requires_consumer_migration"], result)
                self.assertEqual("breaking" if migration else "compatible_change", result["compatibility"], result)

    def test_schema_other_constraint_regressions(self):
        cases = [
            ({"additionalProperties": True}, {"additionalProperties": False}, "breaking_schema"),
            ({"type": "string"}, {"type": "string", "pattern": "^a"}, "breaking_schema"),
            ({"type": "string", "pattern": "^a"}, {"type": "string", "pattern": "^b"}, "behavioral"),
            ({"type": "object", "required": []}, {"type": "object", "required": ["a"]}, "breaking_schema"),
            ({"type": "object", "required": ["a"]}, {"type": "object", "required": []}, "backward_compatible"),
            ({}, {"const": "a"}, "breaking_schema"),
            ({"const": "a"}, {"const": "b"}, "breaking_schema"),
        ]
        for before_schema, after_schema, classification in cases:
            with self.subTest(before=before_schema, after=after_schema):
                result = policy_diff.compare_contracts(
                    self.contract, self.contract, before_schema=before_schema, after_schema=after_schema
                )
                self.assertGreater(result["summary"][classification], 0, result)


if __name__ == "__main__":
    unittest.main()
