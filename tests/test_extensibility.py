from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "validate.py"
spec = importlib.util.spec_from_file_location("uad_validate_extensibility", RUNNER)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


class OperationExtensionAndCompiledPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = mod.load_json(ROOT / "POLICY_CONTRACT.json")
        cls.fixture = ROOT / "examples" / "extensions" / "internal-sandbox-artifact.json"

    def _boundary(self, registry: dict, adapter_id: str = "validator-cli", semantic_details: dict | None = None):
        operation = "internal.sandbox_artifact_publish"
        return mod.evaluate_execution_boundary(
            self.contract,
            [operation],
            [operation],
            ["artifact.txt"],
            ["sandbox:artifact.txt"],
            "test",
            exposure_facts={
                "data_classification": "public",
                "credential_class": "none",
                "tenant_scope": "single_user",
                "public_visibility": "none",
                "estimated_blast_radius": "single_resource",
                "estimated_financial_impact": "none",
            },
            correlation_id="extension-test",
            execution_nonce="extension-test-nonce-0001",
            adapter={
                "id": adapter_id,
                "surface": "test",
                "assertion_source": "human_reviewed",
            },
            semantic_details=semantic_details or {"artifact_kind": "reference_fixture"},
            extension_registry=registry,
        )

    def test_valid_extension_routes_and_compiled_view_is_smaller_than_full_policy(self):
        registry = mod.load_operation_extensions([self.fixture], self.contract)
        route = mod.route_policies(
            self.contract,
            "",
            ["internal.sandbox_artifact_publish"],
            ["src/auth/login.py"],
            "enforcement",
            extension_registry=registry,
        )
        self.assertEqual("PASS", route["routing_status"], route)
        self.assertIn("internal.sandbox_artifact_publish", route["canonical_operations"])
        self.assertIn("deployment", route["policies"])
        self.assertIn("execution", route["policies"])

        compiled = mod.compile_policy_view(
            self.contract,
            operations=["internal.sandbox_artifact_publish"],
            resources=["src/auth/login.py"],
            routing_mode="enforcement",
            extension_registry=registry,
        )
        rendered = mod.render_compiled_policy_view(compiled)
        full_policy = (ROOT / "POLICIES.md").read_text(encoding="utf-8")
        self.assertLess(len(rendered), len(full_policy))
        self.assertIn("## 2. Always-on invariants", rendered)
        self.assertIn("internal.sandbox_artifact_publish", rendered)
        self.assertEqual(registry["combined_digest"], compiled["operation_extension_digest"])

    def test_core_namespace_collision_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "collision.json"
            path.write_text(json.dumps({
                "format": mod.OPERATION_EXTENSION_FORMAT,
                "namespace": "git",
                "operations": [{
                    "id": "git.custom",
                    "policies": ["git"],
                    "effect_floor": "L2",
                    "requires_execution_policy": True,
                    "lifecycle_status": "active",
                    "supported_adapters": ["validator-cli"],
                }],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "collides with a core operation namespace"):
                mod.load_operation_extensions([path], self.contract)

    def test_runtime_rejects_extension_not_supported_by_adapter(self):
        registry = mod.load_operation_extensions([self.fixture], self.contract)
        boundary = self._boundary(registry, adapter_id="unknown-adapter")
        self.assertEqual("FAIL", boundary["status"], boundary)
        self.assertTrue(any("not declared for adapter" in item for item in boundary["errors"]))

    def test_extension_semantics_digest_is_bound_into_action_digest(self):
        registry_a = mod.load_operation_extensions([self.fixture], self.contract)
        with tempfile.TemporaryDirectory() as td:
            changed = json.loads(self.fixture.read_text(encoding="utf-8"))
            changed["operations"][0]["exposure_floor"] = "X1"
            path = Path(td) / "changed.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            registry_b = mod.load_operation_extensions([path], self.contract)

        first = self._boundary(registry_a)
        second = self._boundary(registry_b)
        self.assertEqual("PASS", first["status"], first)
        self.assertEqual("PASS", second["status"], second)
        self.assertNotEqual(first["action_digest"], second["action_digest"])
        self.assertNotEqual(
            first["semantic_details"][mod.OPERATION_EXTENSION_DIGEST_KEY],
            second["semantic_details"][mod.OPERATION_EXTENSION_DIGEST_KEY],
        )

    def test_extension_digest_semantic_key_is_reserved(self):
        registry = mod.load_operation_extensions([self.fixture], self.contract)
        boundary = self._boundary(
            registry,
            semantic_details={
                "artifact_kind": "reference_fixture",
                mod.OPERATION_EXTENSION_DIGEST_KEY: "sha256:" + "0" * 64,
            },
        )
        self.assertEqual("FAIL", boundary["status"], boundary)
        self.assertTrue(any("is reserved" in item for item in boundary["errors"]))

    def test_generated_machine_reference_matches_contract(self):
        policies = (ROOT / "POLICIES.md").read_text(encoding="utf-8")
        expected = mod.render_generated_policy_reference(self.contract)
        start = policies.find(mod.GENERATED_POLICY_START)
        end = policies.find(mod.GENERATED_POLICY_END)
        self.assertGreaterEqual(start, 0)
        self.assertGreaterEqual(end, start)
        end += len(mod.GENERATED_POLICY_END)
        self.assertEqual(expected, policies[start:end])


if __name__ == "__main__":
    unittest.main()
