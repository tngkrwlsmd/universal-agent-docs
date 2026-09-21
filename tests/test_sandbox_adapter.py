from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "examples" / "runtime-adapter" / "sandbox_artifact_adapter.py"
spec = importlib.util.spec_from_file_location("uad_sandbox_artifact_adapter", ADAPTER_PATH)
adapter = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = adapter
spec.loader.exec_module(adapter)


class SandboxArtifactReferenceAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = adapter.policy_validate.load_json(ROOT / "POLICY_CONTRACT.json")
        cls.extensions = adapter.policy_validate.load_operation_extensions(
            [adapter.EXTENSION_PATH], cls.contract
        )
        cls.capabilities = adapter.policy_validate.load_adapter_capabilities(
            [adapter.CAPABILITIES_PATH]
        )
        cls.now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    def test_demo_executes_once_and_blocks_replay(self):
        result = adapter.run_demo()
        self.assertEqual("PASS", result["boundary_status"], result)
        self.assertEqual("REQUIRE_EXPLICIT_APPROVAL", result["action_gate"])
        self.assertTrue(result["first"]["executed"])
        self.assertFalse(result["replay"]["executed"])
        self.assertEqual(
            "REPLAY_DETECTED",
            result["replay"]["approval"]["replay_protection"],
        )

    def test_plan_actual_mismatch_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            boundary = adapter.evaluate_publish(
                self.contract,
                self.extensions,
                self.capabilities,
                ["documentation.modify"],
                root / "source.txt",
                root / "published.txt",
            )
            self.assertEqual("FAIL", boundary["status"], boundary)
            self.assertIn(adapter.ACTUAL_OPERATION, boundary["unplanned_actual_operations"])

    def test_missing_approval_never_reaches_dispatch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.txt"
            destination = root / "published.txt"
            source.write_text("artifact", encoding="utf-8")
            boundary = adapter.evaluate_publish(
                self.contract, self.extensions, self.capabilities,
                [adapter.ACTUAL_OPERATION], source, destination
            )
            result = adapter.execute_publish(
                source,
                destination,
                boundary,
                None,
                root / "ledger.sqlite3",
                contract=self.contract,
                extension_registry=self.extensions,
                reference_time=self.now,
                higher_authority_authenticated=True,
                transport_authenticated=True,
            )
            self.assertFalse(result["executed"])
            self.assertEqual("APPROVAL_REQUIRED", result["reason"])
            self.assertFalse(destination.exists())

    def _approval_result_for_changed_boundary(self, mutate: str):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.txt"
            destination = root / "published.txt"
            source.write_text("artifact", encoding="utf-8")
            original = adapter.evaluate_publish(
                self.contract,
                self.extensions,
                self.capabilities,
                [adapter.ACTUAL_OPERATION],
                source,
                destination,
                correlation_id="binding-test",
                execution_nonce="binding-test-nonce-0001",
            )
            assertion = adapter.build_approval(original, self.now)
            if mutate == "target":
                changed = adapter.evaluate_publish(
                    self.contract,
                    self.extensions,
                    self.capabilities,
                    [adapter.ACTUAL_OPERATION],
                    source,
                    root / "other.txt",
                    correlation_id="binding-test",
                    execution_nonce="binding-test-nonce-0001",
                )
            elif mutate == "environment":
                changed = adapter.evaluate_publish(
                    self.contract,
                    self.extensions,
                    self.capabilities,
                    [adapter.ACTUAL_OPERATION],
                    source,
                    destination,
                    environment="local",
                    correlation_id="binding-test",
                    execution_nonce="binding-test-nonce-0001",
                )
            elif mutate == "digest":
                changed = original
                assertion["approval"]["action_digest"] = "sha256:" + "0" * 64
            else:
                raise AssertionError(mutate)
            path = root / "approval.json"
            path.write_text(json.dumps(assertion), encoding="utf-8")
            return adapter.policy_validate.validate_approval_assertion(
                path,
                self.contract,
                changed,
                reference_time=self.now,
            )

    def test_target_environment_and_digest_changes_break_exact_binding(self):
        for mutation in ("target", "environment", "digest"):
            with self.subTest(mutation=mutation):
                result = self._approval_result_for_changed_boundary(mutation)
                self.assertEqual("INVALID", result["object_validity"], result)
                self.assertEqual("INVALID", result["binding"], result)

    def test_expired_approval_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.txt"
            destination = root / "published.txt"
            source.write_text("artifact", encoding="utf-8")
            boundary = adapter.evaluate_publish(
                self.contract, self.extensions, self.capabilities,
                [adapter.ACTUAL_OPERATION], source, destination
            )
            assertion = adapter.build_approval(
                boundary, self.now, expires_delta=timedelta(seconds=-30)
            )
            path = root / "approval.json"
            path.write_text(json.dumps(assertion), encoding="utf-8")
            result = adapter.policy_validate.validate_approval_assertion(
                path, self.contract, boundary, reference_time=self.now
            )
            self.assertEqual("INVALID", result["object_validity"], result)
            self.assertEqual("INVALID", result["temporal"], result)

    def test_opaque_runtime_operation_remains_forbidden(self):
        result = adapter.policy_validate.evaluate_execution_boundary(
            self.contract,
            ["command.execute"],
            ["command.execute"],
            [],
            ["sandbox"],
            "local",
            exposure_facts=adapter.exposure_facts(),
            correlation_id="opaque-test",
            execution_nonce="opaque-test-nonce-0001",
            adapter=adapter.ADAPTER,
        )
        self.assertEqual("FAIL", result["status"], result)
        self.assertEqual("BLOCK_POLICY_ERROR", result["decision"])


if __name__ == "__main__":
    unittest.main()
