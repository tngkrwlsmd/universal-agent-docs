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
        cls.capability_fixture = (
            ROOT / "examples" / "capabilities" / "reference-sandbox-artifact-adapter.json"
        )

    def _registries(self):
        extensions = mod.load_operation_extensions([self.fixture], self.contract)
        capabilities = mod.load_adapter_capabilities([self.capability_fixture])
        return extensions, capabilities

    def _boundary(
        self,
        registry: dict,
        capabilities: dict,
        adapter_id: str = "reference-sandbox-artifact-adapter",
        semantic_details: dict | None = None,
    ):
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
            adapter_capabilities=capabilities,
        )

    def test_valid_extension_requires_bilateral_adapter_capability(self):
        registry, capabilities = self._registries()
        boundary = self._boundary(registry, capabilities)
        self.assertEqual("PASS", boundary["status"], boundary)
        self.assertEqual("UNVERIFIED", boundary["extension_integrity"])
        self.assertEqual("UNVERIFIED", boundary["adapter_capability_integrity"])
        self.assertEqual("NOT_ESTABLISHED", boundary["extension_authority"])
        self.assertEqual("NOT_ESTABLISHED", boundary["adapter_capability_authority"])

    def test_extension_allowlist_without_capability_is_rejected(self):
        registry, _ = self._registries()
        boundary = self._boundary(registry, {"adapters": {}, "integrity": "UNVERIFIED"})
        self.assertEqual("FAIL", boundary["status"], boundary)
        self.assertTrue(any("requires an explicit capability declaration" in item for item in boundary["errors"]))

    def test_capability_missing_operation_is_rejected(self):
        registry, capabilities = self._registries()
        changed = json.loads(json.dumps(capabilities))
        changed["adapters"]["reference-sandbox-artifact-adapter"]["supported_operations"] = [
            "internal.other_operation"
        ]
        boundary = self._boundary(registry, changed)
        self.assertEqual("FAIL", boundary["status"], boundary)
        self.assertTrue(any("capability does not declare" in item for item in boundary["errors"]))

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

    def test_extension_and_capability_digest_match_integrity_not_authority(self):
        extensions = mod.load_operation_extensions([self.fixture], self.contract)
        capabilities = mod.load_adapter_capabilities([self.capability_fixture])
        extensions = mod.load_operation_extensions(
            [self.fixture], self.contract, expected_digests=[extensions["combined_digest"]]
        )
        capabilities = mod.load_adapter_capabilities(
            [self.capability_fixture], expected_digests=[capabilities["combined_digest"]]
        )
        self.assertEqual("MATCHED", extensions["integrity"])
        self.assertEqual("MATCHED", capabilities["integrity"])
        self.assertEqual("NOT_ESTABLISHED", extensions["authority"])
        self.assertEqual("NOT_ESTABLISHED", capabilities["authority"])

    def test_production_extension_requires_matched_integrity(self):
        extension = {
            "format": mod.OPERATION_EXTENSION_FORMAT,
            "namespace": "acme",
            "operations": [{
                "id": "acme.release_rollout",
                "policies": ["deployment", "execution"],
                "effect_floor": "L3",
                "requires_execution_policy": True,
                "lifecycle_status": "active",
                "supported_adapters": ["acme-adapter"],
                "production_effect": "L4",
                "allowed_environments": ["production"],
            }],
        }
        capability = {
            "format": mod.ADAPTER_CAPABILITIES_FORMAT,
            "adapter_id": "acme-adapter",
            "supported_operations": ["acme.release_rollout"],
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ext_path, cap_path = root / "ext.json", root / "cap.json"
            ext_path.write_text(json.dumps(extension), encoding="utf-8")
            cap_path.write_text(json.dumps(capability), encoding="utf-8")
            extensions = mod.load_operation_extensions([ext_path], self.contract)
            capabilities = mod.load_adapter_capabilities([cap_path])
            kwargs = dict(
                contract=self.contract,
                planned_operations=["acme.release_rollout"],
                actual_operations=["acme.release_rollout"],
                resources=[],
                targets=["service/prod"],
                environment="production",
                exposure_facts={
                    "data_classification": "public",
                    "credential_class": "none",
                    "tenant_scope": "single_user",
                    "public_visibility": "none",
                    "estimated_blast_radius": "single_resource",
                    "estimated_financial_impact": "none",
                },
                correlation_id="production-extension",
                execution_nonce="production-extension-nonce-0001",
                adapter={"id": "acme-adapter", "surface": "test", "assertion_source": "human_reviewed"},
                extension_registry=extensions,
                adapter_capabilities=capabilities,
            )
            untrusted = mod.evaluate_execution_boundary(**kwargs)
            self.assertEqual("FAIL", untrusted["status"], untrusted)

            trusted_extensions = mod.load_operation_extensions(
                [ext_path], self.contract, expected_digests=[extensions["combined_digest"]]
            )
            trusted_capabilities = mod.load_adapter_capabilities(
                [cap_path], expected_digests=[capabilities["combined_digest"]]
            )
            kwargs["extension_registry"] = trusted_extensions
            kwargs["adapter_capabilities"] = trusted_capabilities
            trusted = mod.evaluate_execution_boundary(**kwargs)
            self.assertEqual("PASS", trusted["status"], trusted)
            self.assertEqual("L4", trusted["effective_effect"])
            self.assertEqual("MATCHED", trusted["extension_integrity"])
            self.assertEqual("MATCHED", trusted["adapter_capability_integrity"])

    def test_extension_semantics_and_capability_are_bound_into_action_digest(self):
        registry, capabilities = self._registries()
        first = self._boundary(registry, capabilities)
        changed = json.loads(json.dumps(capabilities))
        changed["combined_digest"] = "sha256:" + "1" * 64
        second = self._boundary(registry, changed)
        self.assertEqual("PASS", first["status"], first)
        self.assertEqual("PASS", second["status"], second)
        self.assertNotEqual(first["action_digest"], second["action_digest"])
        self.assertIn(mod.OPERATION_EXTENSION_DIGEST_KEY, first["semantic_details"])
        self.assertIn(mod.ADAPTER_CAPABILITY_DIGEST_KEY, first["semantic_details"])

    def test_reserved_digest_semantic_keys_are_rejected(self):
        registry, capabilities = self._registries()
        for key in (mod.OPERATION_EXTENSION_DIGEST_KEY, mod.ADAPTER_CAPABILITY_DIGEST_KEY):
            with self.subTest(key=key):
                boundary = self._boundary(
                    registry,
                    capabilities,
                    semantic_details={"artifact_kind": "reference_fixture", key: "sha256:" + "0" * 64},
                )
                self.assertEqual("FAIL", boundary["status"], boundary)
                self.assertTrue(any("is reserved" in item for item in boundary["errors"]))

    def test_compiled_policy_semantics_are_path_independent(self):
        source = json.loads(self.fixture.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as first_td, tempfile.TemporaryDirectory() as second_td:
            first = Path(first_td) / "ext.json"
            second = Path(second_td) / "ext.json"
            first.write_text(json.dumps(source), encoding="utf-8")
            second.write_text(json.dumps(source), encoding="utf-8")
            first_registry = mod.load_operation_extensions([first], self.contract)
            second_registry = mod.load_operation_extensions([second], self.contract)
            first_view = mod.compile_policy_view(
                self.contract,
                operations=["internal.sandbox_artifact_publish"],
                resources=["src/auth/login.py"],
                routing_mode="enforcement",
                extension_registry=first_registry,
            )
            second_view = mod.compile_policy_view(
                self.contract,
                operations=["internal.sandbox_artifact_publish"],
                resources=["src/auth/login.py"],
                routing_mode="enforcement",
                extension_registry=second_registry,
            )
        self.assertEqual(first_view, second_view)

    def test_compiled_policy_has_concrete_context_budgets(self):
        full_chars = len((ROOT / "POLICIES.md").read_text(encoding="utf-8"))
        cases = [
            ("simple-code", ["code.modify"], ["src/simple.py"], 0.32),
            ("auth-code", ["code.modify"], ["src/auth/login.py"], 0.40),
            # Git policy intentionally includes execution/history safety; still require >50% reduction.
            ("git-commit", ["git.commit"], [".git/COMMIT_EDITMSG"], 0.50),
        ]
        for name, operations, resources, max_ratio in cases:
            with self.subTest(name=name):
                view = mod.compile_policy_view(
                    self.contract,
                    operations=operations,
                    resources=resources,
                    routing_mode="enforcement",
                )
                rendered = mod.render_compiled_policy_view(view)
                ratio = len(rendered) / full_chars
                self.assertLessEqual(ratio, max_ratio, (name, len(rendered), full_chars, ratio))
                self.assertIn("## 2. Always-on invariants", rendered)

    def test_consumer_distribution_declares_public_extension_surface(self):
        required = set(self.contract["distribution"]["required_files"])
        for path in (
            "OPERATION_EXTENSION.schema.json",
            "ADAPTER_CAPABILITIES.schema.json",
            "docs/extensions.md",
            "docs/generated-policy-reference.md",
        ):
            self.assertIn(path, required)
        cli = (ROOT / "scripts" / "validate.py").read_text(encoding="utf-8")
        for flag in (
            "--compiled-policy",
            "--operation-extension",
            "--adapter-capabilities",
            "--trusted-extension-digest",
            "--trusted-capability-digest",
        ):
            self.assertIn(flag, cli)

    def test_generated_machine_reference_is_separate_and_current(self):
        expected = mod.render_generated_policy_reference(self.contract)
        actual = (ROOT / mod.GENERATED_POLICY_PATH).read_text(encoding="utf-8")
        self.assertEqual(expected, actual)
        policies = (ROOT / "POLICIES.md").read_text(encoding="utf-8")
        self.assertNotIn("<!-- generated-policy-reference:start -->", policies)
        self.assertIn("docs/generated-policy-reference.md", policies)


if __name__ == "__main__":
    unittest.main()
