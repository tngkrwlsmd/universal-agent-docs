from __future__ import annotations

import json
import tempfile
import unittest
import warnings
from pathlib import Path

from tests.policy_test_support import ROOT, mod

class ExecutionBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = mod.load_json(ROOT / "POLICY_CONTRACT.json")

    def evaluate(self, planned, actual, *, action="", resources=(), targets=(), environment="local", exposure="X0", effect=None, exposure_facts=None, correlation_id="test-action-1", execution_nonce="test-action-nonce-0001", adapter=None, semantic_details=None):
        if exposure_facts is None:
            exposure_facts = {
                "data_classification": "public",
                "credential_class": "none",
                "tenant_scope": "single_user",
                "public_visibility": "none",
                "estimated_blast_radius": "single_resource",
                "estimated_financial_impact": "none",
            }
        return mod.evaluate_execution_boundary(
            self.contract,
            planned,
            actual,
            resources,
            targets,
            environment,
            exposure,
            effect,
            action,
            exposure_facts=exposure_facts,
            correlation_id=correlation_id,
            execution_nonce=execution_nonce,
            adapter=adapter or {"id":"test-adapter","surface":"unit-test","assertion_source":"human_reviewed","version":"1"},
            semantic_details=semantic_details or {},
        )

    def test_actual_operation_outside_plan_is_blocked(self):
        r = self.evaluate(
            ["code.modify"],
            ["external.api_write"],
            targets=["internal-admin-api/tenant-123"],
            environment="production",
            exposure="X2",
        )
        self.assertEqual("FAIL", r["status"])
        self.assertIn("external.api_write", r["unplanned_actual_operations"])

    def test_known_action_hint_cannot_be_hidden_behind_generic_command(self):
        r = self.evaluate(
            ["command.execute"],
            ["command.execute"],
            action="rm -rf build",
            environment="local",
            exposure="X0",
        )
        self.assertEqual("FAIL", r["status"])
        self.assertIn("filesystem.delete", r["action_hint_gaps"])

    def test_generic_command_is_forbidden_at_runtime_even_when_hint_is_only_advisory(self):
        r = self.evaluate(
            ["command.execute"],
            ["command.execute"],
            action="restart the production service",
            targets=["production/service-a"],
            environment="production",
            exposure="X2",
        )
        self.assertEqual("FAIL", r["status"], r)
        self.assertIn("service.restart", r["action_hint_gaps"])
        self.assertTrue(any("opaque/forbidden" in x for x in r["errors"]), r)

    def test_hard_terraform_destroy_signature_cannot_be_hidden(self):
        r = self.evaluate(
            ["command.execute"],
            ["command.execute"],
            action="terraform destroy -auto-approve",
            targets=["staging/project-a"],
            environment="staging",
            exposure="X1",
        )
        self.assertEqual("FAIL", r["status"], r)
        self.assertIn("cloud.resource_delete", r["hard_action_hint_gaps"])

    def test_hard_rm_rf_generated_output_is_classified_separately(self):
        self.assertEqual(["filesystem.generated_delete"], mod.infer_hard_action_operations("rm -rf ./build"))
        self.assertEqual(["filesystem.delete"], mod.infer_hard_action_operations("rm -rf ./user-work"))

    def test_hard_kubectl_delete_distinguishes_pod_from_namespace(self):
        self.assertEqual(["cloud.resource_change"], mod.infer_hard_action_operations("kubectl delete pod api-123"))
        self.assertEqual(["cloud.resource_delete"], mod.infer_hard_action_operations("kubectl delete namespace demo"))

    def test_production_deploy_escalates_to_l4_and_x2(self):
        r = self.evaluate(
            ["deploy.execute"],
            ["deploy.execute"],
            action="kubectl apply -f deploy/",
            targets=["production/cluster-a"],
            environment="production",
            exposure="X0",
        )
        self.assertEqual("PASS", r["status"], r)
        self.assertEqual("L4", r["effective_effect"])
        self.assertEqual("X2", r["effective_exposure"])
        self.assertEqual("REQUIRE_EXPLICIT_APPROVAL", r["action_gate"])
        self.assertEqual("BLOCK_APPROVAL_REQUIRED", r["decision"])
        self.assertEqual("NOT_ESTABLISHED", r["approval"])

    def test_local_code_change_can_be_auto(self):
        r = self.evaluate(["code.modify"], ["code.modify"], environment="local", exposure="X0")
        self.assertEqual("PASS", r["status"], r)
        self.assertEqual("L2", r["effective_effect"])
        self.assertEqual("AUTO", r["action_gate"])
        self.assertEqual("ALLOW", r["decision"])

    def test_l2_x3_requires_override(self):
        r = self.evaluate(["code.modify"], ["code.modify"], targets=["local/repo"], environment="local", exposure="X3")
        self.assertEqual("PASS", r["status"], r)
        self.assertEqual("PROHIBITED_WITHOUT_OVERRIDE", r["action_gate"])
        self.assertEqual("BLOCK_OVERRIDE_REQUIRED", r["decision"])

    def test_production_read_stays_l1_but_exposure_is_at_least_x2(self):
        r = self.evaluate(
            ["database.read"], ["database.read"],
            targets=["production/db/customer-123"], environment="production", exposure="X0"
        )
        self.assertEqual("PASS", r["status"], r)
        self.assertEqual("L1", r["effective_effect"])
        self.assertEqual("X2", r["effective_exposure"])
        self.assertEqual("AUTO_WITH_GUARDS", r["action_gate"])

    def test_unknown_environment_is_conservative_x2(self):
        r = self.evaluate(
            ["database.read"], ["database.read"],
            targets=["unknown/db-scope"], environment="unknown", exposure="X0"
        )
        self.assertEqual("PASS", r["status"], r)
        self.assertEqual("X2", r["effective_exposure"])
        self.assertEqual("AUTO_WITH_GUARDS", r["action_gate"])

    def test_l3_requires_concrete_target(self):
        r = self.evaluate(["external.message_send"], ["external.message_send"], environment="external", exposure="X0")
        self.assertEqual("FAIL", r["status"])
        self.assertTrue(any("concrete target" in x for x in r["errors"]), r)

    def test_runtime_effect_can_only_raise_effect(self):
        r = self.evaluate(
            ["code.modify"], ["code.modify"], targets=["local/repo"],
            environment="local", exposure="X0", effect="L3"
        )
        self.assertEqual("L3", r["effective_effect"])
        self.assertEqual("REQUIRE_EXPLICIT_APPROVAL", r["action_gate"])

    def test_raw_exposure_facts_override_underreported_adapter_level(self):
        facts = {
            "data_classification": "restricted",
            "credential_class": "none",
            "tenant_scope": "single_user",
            "public_visibility": "none",
            "estimated_blast_radius": "single_resource",
            "estimated_financial_impact": "none",
        }
        r = self.evaluate(
            ["database.read"], ["database.read"], targets=["staging/db/customer-123"],
            environment="staging", exposure="X0", exposure_facts=facts,
        )
        self.assertEqual("PASS", r["status"], r)
        self.assertEqual("X2", r["derived_exposure"])
        self.assertEqual("X2", r["effective_exposure"])
        self.assertTrue(any("lower than policy-derived" in x for x in r["warnings"]), r)

    def test_privileged_credential_fact_forces_x3(self):
        facts = {
            "data_classification": "public",
            "credential_class": "privileged_credential",
            "tenant_scope": "single_user",
            "public_visibility": "none",
            "estimated_blast_radius": "single_resource",
            "estimated_financial_impact": "none",
        }
        r = self.evaluate(
            ["code.modify"], ["code.modify"], targets=["local/repo"],
            environment="local", exposure="X0", exposure_facts=facts,
        )
        self.assertEqual("X3", r["derived_exposure"], r)
        self.assertEqual("PROHIBITED_WITHOUT_OVERRIDE", r["action_gate"], r)

    def test_missing_exposure_facts_fails_closed(self):
        r = self.evaluate(
            ["code.modify"], ["code.modify"], targets=["local/repo"],
            environment="local", exposure="X0", exposure_facts={},
        )
        self.assertEqual("FAIL", r["status"], r)
        self.assertTrue(any("exposure_facts" in x for x in r["errors"]), r)

    def test_action_digest_binds_target_and_correlation(self):
        first = self.evaluate(
            ["external.message_send"], ["external.message_send"],
            targets=["recipient:user-a@example.invalid"], environment="external",
            correlation_id="message-1",
        )
        changed_target = self.evaluate(
            ["external.message_send"], ["external.message_send"],
            targets=["recipient:user-b@example.invalid"], environment="external",
            correlation_id="message-1",
        )
        changed_correlation = self.evaluate(
            ["external.message_send"], ["external.message_send"],
            targets=["recipient:user-a@example.invalid"], environment="external",
            correlation_id="message-2",
        )
        self.assertNotEqual(first["action_digest"], changed_target["action_digest"])
        self.assertNotEqual(first["action_digest"], changed_correlation["action_digest"])

    def test_action_digest_v3_binds_semantics_adapter_and_nonce(self):
        base = self.evaluate(["external.api_write"], ["external.api_write"], targets=["api/item/1"], environment="external", semantic_details={"intent":"disable"})
        changed_semantics = self.evaluate(["external.api_write"], ["external.api_write"], targets=["api/item/1"], environment="external", semantic_details={"intent":"delete"})
        changed_adapter = self.evaluate(["external.api_write"], ["external.api_write"], targets=["api/item/1"], environment="external", adapter={"id":"other","surface":"unit-test","assertion_source":"human_reviewed","version":"1"}, semantic_details={"intent":"disable"})
        changed_nonce = self.evaluate(["external.api_write"], ["external.api_write"], targets=["api/item/1"], environment="external", execution_nonce="different-nonce-0001", semantic_details={"intent":"disable"})
        self.assertNotEqual(base["action_digest"], changed_semantics["action_digest"])
        self.assertNotEqual(base["action_digest"], changed_adapter["action_digest"])
        self.assertNotEqual(base["action_digest"], changed_nonce["action_digest"])

    def test_material_financial_impact_raises_exposure(self):
        facts = {
            "data_classification":"public", "credential_class":"none", "tenant_scope":"single_user",
            "public_visibility":"none", "estimated_blast_radius":"single_resource",
            "estimated_financial_impact":"material",
        }
        r = self.evaluate(["cloud.resource_change"], ["cloud.resource_change"], targets=["cloud/project/resource"], exposure_facts=facts)
        self.assertEqual("X2", r["effective_exposure"], r)
        self.assertEqual("REQUIRE_EXPLICIT_APPROVAL", r["action_gate"], r)

class RuntimeActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = mod.load_json(ROOT / "POLICY_CONTRACT.json")

    def write_payload(self, root: Path, payload: dict) -> Path:
        path = root / "runtime-action.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def base_payload(self):
        return {
            "schema_version": 3,
            "adapter": {
                "id": "kubernetes-adapter",
                "surface": "kubectl",
                "assertion_source": "tool_adapter",
            },
            "action": {
                "correlation_id": "runtime-action-1",
                "execution_nonce": "runtime-action-nonce-0001",
                "planned_operations": ["cloud.resource_change"],
                "actual_operations": ["cloud.resource_change"],
                "affected_resources": ["deployment/api"],
                "targets": ["staging/cluster-a/namespace-app"],
                "environment": "staging",
                "exposure_facts": {
                    "data_classification": "internal",
                    "credential_class": "none",
                    "tenant_scope": "single_tenant",
                    "public_visibility": "none",
                    "estimated_blast_radius": "bounded_set",
                    "estimated_financial_impact": "bounded"
                },
                "actual_action": "kubectl scale deployment api --replicas=4",
                "semantic_details": {"verb": "scale", "resource_kind": "deployment"},
            },
        }

    def test_runtime_action_schema_and_boundary_pass_but_trust_is_unverified(self):
        with tempfile.TemporaryDirectory() as td:
            result = mod.validate_runtime_action(self.write_payload(Path(td), self.base_payload()), self.contract)
            self.assertEqual("PASS", result["status"], result)
            self.assertEqual("PASS", result["schema_status"])
            self.assertEqual("UNVERIFIED", result["adapter_trust"])
            self.assertEqual("NOT_ESTABLISHED", result["authorization"])

    def test_runtime_action_rejects_unplanned_actual_operation(self):
        payload = self.base_payload()
        payload["action"]["actual_operations"] = ["cloud.resource_delete"]
        payload["action"]["actual_action"] = "terraform destroy -auto-approve"
        with tempfile.TemporaryDirectory() as td:
            result = mod.validate_runtime_action(self.write_payload(Path(td), payload), self.contract)
            self.assertEqual("FAIL", result["status"], result)
            self.assertIn("cloud.resource_delete", result["boundary"]["unplanned_actual_operations"])
