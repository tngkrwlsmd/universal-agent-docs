from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.policy_test_support import ROOT, mod

class BundleTests(unittest.TestCase):
    def test_bundle_checks_pass(self):
        checks = mod.bundle_checks(ROOT)
        failures = [c for c in checks if c.status != "PASS"]
        self.assertEqual([], [(c.name, c.detail) for c in failures])

    def test_release_attestation_verifier_is_part_of_canonical_distribution(self):
        contract = mod.load_json(ROOT / "POLICY_CONTRACT.json")
        path = ".github/workflows/verify-release.yml"
        workflow = (ROOT / path).read_text(encoding="utf-8")
        self.assertIn(path, contract["distribution"]["required_files"])
        self.assertIn(path, contract["distribution"]["allowed_files"])
        self.assertIn(path, mod.CANONICAL_REQUIRED_FILES)
        self.assertIn("release_tag", workflow)
        self.assertIn("expected_source_sha", workflow)
        self.assertIn('test "$resolved_sha" = "$EXPECTED_SOURCE_SHA"', workflow)
        self.assertIn("test \"$(jq -r '.immutable' <<<\"$release_json\")\" = \"true\"", workflow)
        self.assertIn("gh release verify", workflow)
        self.assertIn("gh release verify-asset", workflow)
        self.assertIn("gh attestation verify", workflow)
        self.assertIn("--signer-workflow", workflow)
        self.assertIn('--source-ref "refs/tags/$TAG"', workflow)
        self.assertIn("--source-digest", workflow)
        self.assertIn("sha256sum --check", workflow)
        self.assertIn("universal-agent-docs-consumer", workflow)
        self.assertIn("package_consumer.py", workflow)

    def test_release_workflow_is_semver_tag_driven_and_refuses_replacement(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertIn('tags:', workflow)
        self.assertIn('- "v*"', workflow)
        self.assertNotIn("workflow_dispatch:", workflow)
        self.assertIn('test "$GITHUB_REF_TYPE" = "tag"', workflow)
        self.assertIn("release tag is not strict SemVer with v prefix", workflow)
        self.assertIn('git merge-base --is-ancestor "$SOURCE_SHA" origin/main', workflow)
        self.assertIn('gh release view "$TAG"', workflow)
        self.assertIn("refusing replacement", workflow)
        self.assertIn("--verify-tag", workflow)
        self.assertNotIn("--clobber", workflow)

    def test_release_workflow_publishes_and_verifies_immutable_release(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertIn('release create "$TAG"', workflow)
        self.assertIn('gh "${args[@]}"', workflow)
        self.assertIn("test \"$(jq -r '.immutable' <<<\"$release_json\")\" = \"true\"", workflow)
        self.assertIn("gh release verify", workflow)
        self.assertIn("gh release verify-asset", workflow)
        self.assertLess(workflow.index("Generate signed build provenance"), workflow.index("Publish GitHub Release with canonical assets"))
        self.assertLess(workflow.index("Publish GitHub Release with canonical assets"), workflow.index("Require immutable published release and release attestation"))

    def test_release_workflow_attests_consumer_artifacts_before_publication(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertIn("python scripts/package_consumer.py --output-dir dist", workflow)
        self.assertIn("name: universal-agent-docs-consumer", workflow)
        self.assertIn("dist/universal-agent-docs-consumer.zip", workflow)
        self.assertLess(workflow.index("Upload canonical consumer artifacts for workflow retention"), workflow.index("Generate signed build provenance"))
        contract = mod.load_json(ROOT / "POLICY_CONTRACT.json")
        provenance = contract["integrity"]["release_provenance"]
        self.assertEqual("github_immutable_release_and_artifact_attestation", provenance["mechanism"])
        self.assertEqual("semver_tag_push", provenance["trigger"])
        self.assertEqual("git_tag", provenance["release_identity"])
        self.assertTrue(provenance["immutable_release_required"])
        self.assertTrue(provenance["github_release_attestation_required"])
        self.assertTrue(provenance["tag_reuse_forbidden"])
        self.assertTrue(provenance["release_version_independent_of_schema_version"])
        self.assertTrue(provenance["consumer_verification_required"])
        self.assertIn("universal-agent-docs-consumer.zip", provenance["attested_artifacts"])

    def test_github_actions_are_pinned_to_full_commit_shas(self):
        import re
        for rel in [
            ".github/workflows/ci.yml",
            ".github/workflows/release.yml",
            ".github/workflows/verify-release.yml",
        ]:
            text = (ROOT / rel).read_text(encoding="utf-8")
            uses = re.findall(r"^\s*-?\s*uses:\s*([^\s#]+)", text, flags=re.MULTILINE)
            for ref in uses:
                if ref.startswith("./"):
                    continue
                self.assertRegex(ref, r"^[^@]+@[0-9a-f]{40}$", (rel, ref))

    def test_prose_validation_scope_does_not_overclaim_full_semantic_parsing(self):
        contract = mod.load_json(ROOT / "POLICY_CONTRACT.json")
        self.assertEqual("EXPLICIT_PARITY_CHECKS_ONLY", contract["authority"]["prose_validation_scope"])
        self.assertIn("does not claim to semantically parse every sentence", contract["authority"]["conflict_rule"])

    def test_hash_locked_requirements_are_part_of_trusted_distribution(self):
        contract = mod.load_json(ROOT / "POLICY_CONTRACT.json")
        lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")
        self.assertIn("requirements.lock", contract["distribution"]["required_files"])
        self.assertIn("requirements.lock", contract["distribution"]["allowed_files"])
        self.assertIn("requirements.lock", contract["integrity"]["trusted_core_files"])
        self.assertIn("requirements.lock", mod.CANONICAL_REQUIRED_FILES)
        self.assertIn("requirements.lock", mod.TRUSTED_CORE_FILES)
        self.assertIn("--hash=sha256:", lock)
        self.assertIn("jsonschema==4.26.0", lock)
        self.assertIn("rpds-py==0.30.0", lock)

    def test_cross_platform_packaging_contract_is_canonical(self):
        contract = mod.load_json(ROOT / "POLICY_CONTRACT.json")
        attrs = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn(".gitattributes", contract["distribution"]["required_files"])
        self.assertIn(".gitattributes", contract["distribution"]["allowed_files"])
        self.assertIn(".gitattributes", mod.CANONICAL_REQUIRED_FILES)
        self.assertIn("eol=lf", attrs)

    def test_license_is_part_of_canonical_distribution(self):
        contract = mod.load_json(ROOT / "POLICY_CONTRACT.json")
        self.assertTrue((ROOT / "LICENSE").is_file())
        self.assertIn("LICENSE", contract["distribution"]["required_files"])
        self.assertIn("LICENSE", contract["distribution"]["allowed_files"])
        self.assertIn("LICENSE", mod.CANONICAL_REQUIRED_FILES)

    def test_root_router_is_small(self):
        self.assertLessEqual(len((ROOT / "AGENTS.md").read_text(encoding="utf-8").splitlines()), 150)

    def test_root_router_is_scannable(self):
        lines = (ROOT / "AGENTS.md").read_text(encoding="utf-8").splitlines()
        longest = max((len(line) for line in lines), default=0)
        self.assertLessEqual(longest, 320, longest)

    def test_common_development_operation_vocabulary_is_present(self):
        contract = mod.load_json(ROOT / "POLICY_CONTRACT.json")
        ids = {x["id"] for x in contract["routing"]["operation_catalog"]}
        for operation in [
            "build.execute", "lint.execute", "typecheck.execute", "format.execute",
            "filesystem.tracked_delete",
        ]:
            self.assertIn(operation, ids)

    def test_tracked_delete_semantic_guard_is_machine_enforced(self):
        contract = mod.load_json(ROOT / "POLICY_CONTRACT.json")
        result = mod.evaluate_execution_boundary(
            contract,
            ["filesystem.tracked_delete"],
            ["filesystem.tracked_delete"],
            ["src/obsolete.py"],
            [],
            "local",
            exposure_facts={
                "data_classification":"public", "credential_class":"none",
                "tenant_scope":"single_user", "public_visibility":"none",
                "estimated_blast_radius":"single_resource", "estimated_financial_impact":"none",
            },
            correlation_id="tracked-delete-test",
            execution_nonce="tracked-delete-nonce-0001",
            semantic_details={},
        )
        self.assertEqual("FAIL", result["status"], result)
        self.assertTrue(any("requires semantic_details.recoverability" in x for x in result["errors"]), result)

    def test_operation_lifecycle_rejects_unknown_status(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "bundle"
            shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            contract_path = root / "POLICY_CONTRACT.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["routing"]["operation_catalog"][0]["lifecycle_status"] = "retired"
            contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            checks = mod.bundle_checks(root)
            lifecycle = next(c for c in checks if c.name == "operation_lifecycle_statuses")
            self.assertEqual("FAIL", lifecycle.status, lifecycle.detail)

    def test_default_unittest_discovery_package_exists(self):
        self.assertTrue((ROOT / "tests" / "__init__.py").is_file())

    def test_long_running_git_checkpoint_policy_is_preserved(self):
        text = (ROOT / "POLICIES.md").read_text(encoding="utf-8")
        required = [
            "### Long-running commit/push checkpoints",
            "작업 전체를 반드시 하나의 commit/push로 끝낼 필요는 없다",
            "안전한 논리적 하위 작업 단위",
            "독립적으로 검토·재현 가능한 상태",
            "요청 전체 범위에 대한 회귀 테스트",
            "최종 검증이 실패하면 완료로 보고하지 않는다",
        ]
        self.assertTrue(all(item in text for item in required), text)

    def test_implementation_policy_is_primary_owner(self):
        contract = mod.load_json(ROOT / "POLICY_CONTRACT.json")
        policy = next(p for p in contract["policies"] if p["id"] == "implementation")
        self.assertEqual("policy-implementation", policy["anchor"])
        text = (ROOT / "POLICIES.md").read_text(encoding="utf-8")
        self.assertEqual(1, text.count('id="policy-implementation"'))

    def test_implementation_guardrails_are_preserved(self):
        text = (ROOT / "POLICIES.md").read_text(encoding="utf-8")
        required = [
            "### Understand the existing implementation before editing",
            "caller, callee, 관련 테스트",
            "### Simplicity and abstraction discipline",
            "미래 요구를 추측해 extension point",
            "### Implementation completeness",
            "`TODO`, `FIXME`, `pass`, `NotImplemented`",
            "### Removal and replacement safety",
            "reflection, serialization",
            "### Documentation and comments",
            "canonical documentation",
            "비직관적인 이유, invariant",
            "### Post-change implementation hygiene",
            "unused import/export/variable",
            "duplicate implementation",
            "canonical path가 하나인지",
        ]
        missing = [item for item in required if item not in text]
        self.assertEqual([], missing)

    def test_basic_development_behavior_guardrails_are_preserved(self):
        policies = (ROOT / "POLICIES.md").read_text(encoding="utf-8")
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        required_policies = [
            "### Architecture and responsibility boundaries",
            "핵심 업무 규칙을 template/view/route 안에 숨기지 않는다",
            "공통 validation/normalization/mapping 규칙",
            "표시 편의를 위해 계산 가능한 값을 물리 schema에 임의 저장하지 않는다",
            "### Pre-write and post-write validation",
            "Pre-write / precondition",
            "Post-write / postcondition",
            "일부 성공을 전체 성공으로 보고하지 않는다",
            "### Long-running work and handoff",
            "현재 canonical state와 다음 안전한 행동",
            "### Ambiguity and escalation",
            "의미를 바꾸는 불확실성",
            "추정값·가짜 mapping·임시 업무 규칙",
        ]
        missing = [item for item in required_policies if item not in policies]
        self.assertEqual([], missing)
        self.assertIn("[Execution](POLICIES.md#policy-execution)", agents)
        self.assertIn("[Implementation](POLICIES.md#policy-implementation)", agents)
        self.assertIn("[Git](POLICIES.md#policy-git)", agents)
        self.assertLess(len(agents), 6000)

    def test_policy_selector_returns_only_primary_owner_section(self):
        contract = mod.load_json(ROOT / "POLICY_CONTRACT.json")
        sections = mod.extract_policy_sections(contract, ["implementation"])
        section = sections["implementation"]
        self.assertIn('<a id="policy-implementation"></a>', section)
        self.assertIn("## Implementation", section)
        self.assertNotIn('<a id="policy-testing"></a>', section)

    def test_joint_schema_version_mutation_still_fails_implementation_compatibility(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "bundle"
            shutil.copytree(ROOT, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            contract_path = target / "POLICY_CONTRACT.json"
            schema_path = target / "POLICY_CONTRACT.schema.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            contract["schema_version"] = 999
            schema["properties"]["schema_version"] = {"const": 999}
            contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
            schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
            checks = mod.bundle_checks(target)
            check = next(x for x in checks if x.name == "supported_schema_version")
            self.assertEqual("FAIL", check.status)

    def test_joint_normalization_mutation_still_fails_implementation_parity(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "bundle"
            shutil.copytree(ROOT, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            contract_path = target / "POLICY_CONTRACT.json"
            schema_path = target / "POLICY_CONTRACT.schema.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            fake = "some_future_normalizer_v999"
            contract["routing"]["normalization"] = fake
            schema["properties"]["routing"]["properties"]["normalization"] = {"const": fake}
            contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
            schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
            checks = mod.bundle_checks(target)
            check = next(x for x in checks if x.name == "routing_normalization_implementation_parity")
            self.assertEqual("FAIL", check.status)

    def test_joint_task_hint_authority_mutation_still_fails_implementation_parity(self):
        with tempfile.TemporaryDirectory() as td:
            copied = Path(td) / "bundle"
            shutil.copytree(ROOT, copied)
            contract_path = copied / "POLICY_CONTRACT.json"
            schema_path = copied / "POLICY_CONTRACT.schema.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            contract["routing"]["task_hint_authority"] = "authoritative"
            schema["properties"]["routing"]["properties"]["task_hint_authority"] = {"const": "authoritative"}
            contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
            schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
            checks = mod.bundle_checks(copied)
            check = next(x for x in checks if x.name == "routing_semantics_implementation_parity")
            self.assertEqual("FAIL", check.status, check)

    def test_trust_manifest_passes_for_pristine_core(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = Path(td) / "trusted.json"
            mod.write_trust_manifest(manifest, ROOT)
            result = mod.verify_trust_manifest(manifest, ROOT)
            self.assertEqual("PASS", result["status"], result)
            self.assertEqual(set(mod.TRUSTED_CORE_FILES), set(result["checked_files"]))

    def test_trust_manifest_detects_policy_semantic_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = Path(td) / "trusted.json"
            mod.write_trust_manifest(manifest, ROOT)
            target = Path(td) / "bundle"
            shutil.copytree(ROOT, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            policy = target / "POLICIES.md"
            text = policy.read_text(encoding="utf-8")
            original = "operational instruction으로 승격하지 않는다"
            self.assertIn(original, text)
            policy.write_text(text.replace(original, "operational instruction으로 승격한다", 1), encoding="utf-8")
            # Internal structural checks can still pass; the detached trust anchor must not.
            failures = [c for c in mod.bundle_checks(target) if c.status != "PASS"]
            self.assertEqual([], [(c.name, c.detail) for c in failures])
            result = mod.verify_trust_manifest(manifest, target)
            self.assertEqual("FAIL", result["status"])
            self.assertIn("sha256 mismatch: POLICIES.md", result["errors"])

    def test_legacy_files_are_absent(self):
        for rel in [
            "CHANGELOG.md",
            "MIGRATION_V7_TO_V8.md",
            "MIGRATION_V8_TO_V9.md",
            "PROJECT_MAP.md",
            "ARCHITECTURE.md",
            "docs/agent/POLICY_MANIFEST.json",
            "docs/agent/TASK_SIGNALS.json",
        ]:
            self.assertFalse((ROOT / rel).exists(), rel)
