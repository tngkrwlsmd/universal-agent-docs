from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "examples" / "runtime-adapter" / "github_issue_adapter.py"
spec = importlib.util.spec_from_file_location("uad_github_issue_adapter", ADAPTER_PATH)
adapter = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = adapter
spec.loader.exec_module(adapter)


class GitHubIssueReferenceAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = adapter.policy_validate.load_json(ROOT / "POLICY_CONTRACT.json")
        cls.now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        cls.request = adapter.GitHubIssueRequest("example/project", "Issue title", "Issue body")
        cls.correlation_id = "github-adapter-test"
        cls.nonce = "github-adapter-test-nonce-0001"

    def _boundary(self, request=None, planned=None, exposure_facts=None):
        return adapter.evaluate_issue_create(
            self.contract,
            planned or [adapter.ACTUAL_OPERATION],
            request or self.request,
            correlation_id=self.correlation_id,
            execution_nonce=self.nonce,
            exposure_facts=exposure_facts,
        )

    def _write_approval(self, root: Path, boundary: dict, *, expires_delta=timedelta(minutes=10)) -> Path:
        path = root / "approval.json"
        path.write_text(
            json.dumps(adapter.build_approval(boundary, self.now, expires_delta=expires_delta)),
            encoding="utf-8",
        )
        return path

    def test_demo_executes_once_and_blocks_replay(self):
        result = adapter.run_demo()
        self.assertEqual("PASS", result["boundary_status"], result)
        self.assertEqual("REQUIRE_EXPLICIT_APPROVAL", result["action_gate"])
        self.assertTrue(result["first"]["executed"])
        self.assertFalse(result["replay"]["executed"])
        self.assertEqual("REPLAY_DETECTED", result["replay"]["approval"]["replay_protection"])
        self.assertEqual(1, result["transport_calls"])

    def test_plan_actual_mismatch_is_blocked(self):
        boundary = self._boundary(planned=["git.push"])
        self.assertEqual("FAIL", boundary["status"], boundary)
        self.assertIn(adapter.ACTUAL_OPERATION, boundary["unplanned_actual_operations"])

    def test_missing_raw_exposure_fact_fails_closed(self):
        facts = adapter.github_exposure_facts()
        facts.pop("tenant_scope")
        boundary = self._boundary(exposure_facts=facts)
        self.assertEqual("FAIL", boundary["status"], boundary)
        self.assertTrue(any("tenant_scope" in error for error in boundary["errors"]))

    def test_target_substitution_after_approval_is_blocked_before_transport(self):
        original = self._boundary()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            approval = self._write_approval(root, original)
            transport = adapter.RecordingGitHubTransport()
            changed = adapter.GitHubIssueRequest("other/project", self.request.title, self.request.body)
            result = adapter.dispatch_issue_create(
                changed, [adapter.ACTUAL_OPERATION], approval, root / "ledger.sqlite3", transport,
                contract=self.contract, reference_time=self.now,
                correlation_id=self.correlation_id, execution_nonce=self.nonce,
                higher_authority_authenticated=True, transport_authenticated=True,
            )
            self.assertFalse(result["executed"], result)
            self.assertEqual("APPROVAL_NOT_CONSUMABLE", result["reason"])
            self.assertEqual(0, len(transport.calls))

    def test_semantic_mutation_after_approval_is_blocked(self):
        original = self._boundary()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            approval = self._write_approval(root, original)
            transport = adapter.RecordingGitHubTransport()
            changed = adapter.GitHubIssueRequest(self.request.repository, "Changed title", self.request.body)
            result = adapter.dispatch_issue_create(
                changed, [adapter.ACTUAL_OPERATION], approval, root / "ledger.sqlite3", transport,
                contract=self.contract, reference_time=self.now,
                correlation_id=self.correlation_id, execution_nonce=self.nonce,
                higher_authority_authenticated=True, transport_authenticated=True,
            )
            self.assertFalse(result["executed"], result)
            self.assertEqual("APPROVAL_NOT_CONSUMABLE", result["reason"])
            self.assertEqual(0, len(transport.calls))

    def test_expired_approval_and_unverified_trust_are_blocked(self):
        boundary = self._boundary()
        for case in ("expired", "trust"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                approval = self._write_approval(
                    root, boundary,
                    expires_delta=timedelta(seconds=-1) if case == "expired" else timedelta(minutes=10),
                )
                transport = adapter.RecordingGitHubTransport()
                result = adapter.dispatch_issue_create(
                    self.request, [adapter.ACTUAL_OPERATION], approval, root / "ledger.sqlite3", transport,
                    contract=self.contract, reference_time=self.now,
                    correlation_id=self.correlation_id, execution_nonce=self.nonce,
                    higher_authority_authenticated=case != "trust", transport_authenticated=True,
                )
                self.assertFalse(result["executed"], result)
                self.assertEqual(0, len(transport.calls))

    def test_invalid_or_opaque_runtime_operation_remains_fail_closed(self):
        for actual in ("command.execute", "vendor.unknown"):
            with self.subTest(actual=actual):
                result = adapter.policy_validate.evaluate_execution_boundary(
                    self.contract,
                    [actual],
                    [actual],
                    [],
                    ["github:example/project/issues"],
                    "external",
                    exposure_facts=adapter.github_exposure_facts(),
                    correlation_id="opaque-github-test",
                    execution_nonce="opaque-github-test-nonce-0001",
                    adapter=adapter.ADAPTER,
                )
                self.assertEqual("FAIL", result["status"], result)
                self.assertEqual("BLOCK_POLICY_ERROR", result["decision"])


if __name__ == "__main__":
    unittest.main()
