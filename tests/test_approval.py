from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.policy_test_support import ROOT, mod

class ApprovalAssertionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = mod.load_json(ROOT / "POLICY_CONTRACT.json")

    def boundary(self):
        return mod.evaluate_execution_boundary(
            self.contract,
            ["external.message_send"],
            ["external.message_send"],
            [],
            ["recipient:user@example.invalid"],
            "external",
            "X0",
            None,
            "send approved notification",
            exposure_facts={
                "data_classification": "public",
                "credential_class": "none",
                "tenant_scope": "single_user",
                "public_visibility": "public_destination",
                "estimated_blast_radius": "single_resource",
                "estimated_financial_impact": "none",
            },
            correlation_id="approval-action-1",
            execution_nonce="approval-nonce-000001",
            adapter={"id":"message-adapter","surface":"external-message","assertion_source":"tool_adapter","version":"2"},
            semantic_details={"message_type":"notification"},
        )

    def approval(self, boundary):
        now = datetime.now(timezone.utc)
        return {
            "schema_version": 2,
            "approval": {
                "approval_id": "approval-123",
                "issuer": "org-approval-workflow",
                "decision": "APPROVE",
                "scope": "send one notification to one recipient",
                "issued_at": (now - timedelta(minutes=1)).isoformat(),
                "expires_at": (now + timedelta(minutes=10)).isoformat(),
                "operations": list(boundary["actual_operations"]),
                "targets": list(boundary["targets"]),
                "environment": boundary["environment"],
                "correlation_id": boundary["correlation_id"],
                "execution_nonce": boundary["execution_nonce"],
                "single_use": True,
                "action_digest": boundary["action_digest"],
                "authorization_reference": "approval-workflow/123",
            },
        }

    def validate(self, payload, boundary):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "approval.json"
            p.write_text(json.dumps(payload), encoding="utf-8")
            return mod.validate_approval_assertion(p, self.contract, boundary)

    def test_valid_approval_binds_exact_action_but_does_not_self_authenticate(self):
        boundary = self.boundary()
        self.assertEqual("REQUIRE_EXPLICIT_APPROVAL", boundary["action_gate"], boundary)
        result = self.validate(self.approval(boundary), boundary)
        self.assertEqual("VALID", result["object_validity"], result)
        self.assertEqual("VALID", result["binding"])
        self.assertEqual("UNVERIFIED", result["authority"])
        self.assertEqual("NOT_ESTABLISHED", result["authorization"])

    def test_digest_mismatch_blocks_confused_deputy_reuse(self):
        boundary = self.boundary()
        payload = self.approval(boundary)
        payload["approval"]["action_digest"] = "sha256:" + "0" * 64
        result = self.validate(payload, boundary)
        self.assertEqual("INVALID", result["binding"], result)
        self.assertTrue(any("action_digest" in x for x in result["errors"]), result)

    def test_target_or_correlation_mismatch_invalidates_binding(self):
        boundary = self.boundary()
        for field, value in [
            ("targets", ["recipient:other@example.invalid"]),
            ("correlation_id", "other-action"),
        ]:
            with self.subTest(field=field):
                payload = self.approval(boundary)
                payload["approval"][field] = value
                result = self.validate(payload, boundary)
                self.assertEqual("INVALID", result["binding"], result)

    def test_expired_approval_is_invalid(self):
        boundary = self.boundary()
        payload = self.approval(boundary)
        now = datetime.now(timezone.utc)
        payload["approval"]["issued_at"] = (now - timedelta(hours=2)).isoformat()
        payload["approval"]["expires_at"] = (now - timedelta(hours=1)).isoformat()
        result = self.validate(payload, boundary)
        self.assertEqual("INVALID", result["object_validity"], result)
        self.assertEqual("INVALID", result["temporal"])

    def test_approval_ttl_over_contract_limit_is_invalid(self):
        boundary = self.boundary()
        payload = self.approval(boundary)
        now = datetime.now(timezone.utc)
        payload["approval"]["issued_at"] = (now - timedelta(minutes=1)).isoformat()
        payload["approval"]["expires_at"] = (now + timedelta(hours=1)).isoformat()
        result = self.validate(payload, boundary)
        self.assertEqual("INVALID", result["object_validity"], result)
        self.assertTrue(any("TTL exceeds maximum" in x for x in result["errors"]), result)

    def test_wildcard_approval_target_is_rejected(self):
        boundary = self.boundary()
        payload = self.approval(boundary)
        payload["approval"]["targets"] = ["*"]
        result = self.validate(payload, boundary)
        self.assertEqual("INVALID", result["object_validity"], result)
        self.assertTrue(any("target" in x for x in result["errors"]), result)

    def test_single_use_registry_rejects_exact_replay(self):
        boundary = self.boundary()
        payload = self.approval(boundary)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assertion = root / "approval.json"
            ledger = root / "approval-ledger.sqlite"
            assertion.write_text(json.dumps(payload), encoding="utf-8")
            first = mod.validate_approval_assertion(assertion, self.contract, boundary, replay_registry=ledger, consume=True)
            second = mod.validate_approval_assertion(assertion, self.contract, boundary, replay_registry=ledger, consume=True)
        self.assertEqual("VALID", first["object_validity"], first)
        self.assertEqual("CONSUMED", first["replay_protection"], first)
        self.assertEqual("INVALID", second["object_validity"], second)
        self.assertEqual("REPLAY_DETECTED", second["replay_protection"], second)
