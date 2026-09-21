from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .policy_test_support import ROOT, mod

class OverrideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = mod.load_json(ROOT / "POLICY_CONTRACT.json")

    def boundary(self):
        return mod.evaluate_execution_boundary(
            self.contract, ["credential.rotate"], ["credential.rotate"], [],
            ["production/service-a/credential-primary"], "production", "X3", None,
            "rotate production credential",
            exposure_facts={
                "data_classification":"restricted", "credential_class":"privileged_credential",
                "tenant_scope":"organization_wide", "public_visibility":"none",
                "estimated_blast_radius":"service", "estimated_financial_impact":"bounded",
            },
            correlation_id="override-action-1", execution_nonce="override-nonce-00001",
            adapter={"id":"credential-adapter","surface":"iam","assertion_source":"tool_adapter","version":"1"},
            semantic_details={"rotation_mode":"replace"},
        )

    def make_override(self, boundary=None, *, issued=None, expires=None):
        boundary = boundary or self.boundary()
        now = datetime.now(timezone.utc)
        return {
            "schema_version": 1,
            "override_id": "override-123",
            "issuer": "org-runtime-approval-workflow",
            "issued_at": (issued or (now - timedelta(minutes=1))).isoformat(),
            "expires_at": (expires or (now + timedelta(minutes=5))).isoformat(),
            "scope": "production credential rotation for service-a",
            "operations": list(boundary["actual_operations"]),
            "targets": list(boundary["targets"]),
            "environment": boundary["environment"],
            "correlation_id": boundary["correlation_id"],
            "execution_nonce": boundary["execution_nonce"],
            "action_digest": boundary["action_digest"],
            "single_use": True,
            "authorization_reference": "approval/123",
        }

    def validate(self, data, boundary=None, *, replay_registry=None, consume=False):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "override.json"
            p.write_text(json.dumps(data), encoding="utf-8")
            return mod.validate_protected_override(
                p, self.contract, boundary or self.boundary(),
                replay_registry=replay_registry, consume=consume,
            )

    def test_valid_object_binds_exact_action_but_never_claims_authorized(self):
        boundary = self.boundary()
        self.assertEqual("PROHIBITED_WITHOUT_OVERRIDE", boundary["action_gate"], boundary)
        result = self.validate(self.make_override(boundary), boundary)
        self.assertEqual("VALID", result["object_validity"], result)
        self.assertEqual("PASS", result["schema_status"])
        self.assertEqual("VALID", result["temporal"])
        self.assertEqual("VALID", result["binding"])
        self.assertEqual("UNVERIFIED", result["authority"])
        self.assertEqual("UNVERIFIED", result["task_approval"])
        self.assertEqual("NOT_ESTABLISHED", result["authorization"])

    def test_override_single_use_registry_rejects_exact_replay(self):
        boundary = self.boundary()
        data = self.make_override(boundary)
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "override-consumption.sqlite"
            first = self.validate(data, boundary, replay_registry=ledger, consume=True)
            self.assertEqual("VALID", first["object_validity"], first)
            self.assertEqual("CONSUMED", first["replay_protection"], first)
            second = self.validate(data, boundary, replay_registry=ledger, consume=True)
            self.assertEqual("INVALID", second["object_validity"], second)
            self.assertEqual("REPLAY_DETECTED", second["replay_protection"], second)
            self.assertTrue(any("already been consumed" in x for x in second["errors"]), second)

    def test_override_digest_mismatch_invalidates_binding(self):
        boundary = self.boundary()
        data = self.make_override(boundary)
        data["action_digest"] = "sha256:" + "0" * 64
        result = self.validate(data, boundary)
        self.assertEqual("INVALID", result["binding"], result)

    def test_expired_override_is_invalid(self):
        now = datetime.now(timezone.utc)
        result = self.validate(self.make_override(issued=now - timedelta(days=2), expires=now - timedelta(days=1)))
        self.assertEqual("INVALID", result["object_validity"], result)
        self.assertIn("override is expired", result["errors"])

    def test_override_ttl_over_contract_limit_is_invalid(self):
        now = datetime.now(timezone.utc)
        result = self.validate(self.make_override(issued=now - timedelta(minutes=1), expires=now + timedelta(minutes=20)))
        self.assertEqual("INVALID", result["object_validity"], result)
        self.assertTrue(any("TTL exceeds maximum" in x for x in result["errors"]), result)

    def test_future_issued_at_is_invalid(self):
        now = datetime.now(timezone.utc)
        result = self.validate(self.make_override(issued=now + timedelta(hours=2), expires=now + timedelta(hours=3)))
        self.assertEqual("INVALID", result["object_validity"], result)
        self.assertIn("issued_at must not be in the future", result["errors"])

    def test_wildcard_target_is_invalid(self):
        data = self.make_override()
        data["targets"] = ["*"]
        result = self.validate(data)
        self.assertEqual("INVALID", result["object_validity"], result)

    def test_unknown_operation_is_invalid(self):
        data = self.make_override()
        data["operations"] = ["do_anything"]
        result = self.validate(data)
        self.assertEqual("INVALID", result["object_validity"], result)

    def test_unexpected_field_is_invalid(self):
        data = self.make_override()
        data["extra"] = "not allowed"
        result = self.validate(data)
        self.assertEqual("INVALID", result["object_validity"], result)

    def test_scope_must_be_string(self):
        data = self.make_override()
        data["scope"] = {}
        result = self.validate(data)
        self.assertEqual("INVALID", result["object_validity"], result)
