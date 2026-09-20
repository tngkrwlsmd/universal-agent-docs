from __future__ import annotations

import importlib.util
import json
import shutil
import stat
import sys
import tempfile
import unittest
import warnings
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("uad_validate", ROOT / "scripts" / "validate.py")
mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


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
        self.assertIn("expected_source_sha", workflow)
        self.assertIn('test "$source_sha" = "$EXPECTED_SOURCE_SHA"', workflow)
        self.assertIn('test "$workflow_path" = ".github/workflows/release.yml"', workflow)
        self.assertIn('test "$source_branch" = "main"', workflow)
        self.assertIn("gh attestation verify", workflow)
        self.assertIn("--signer-workflow", workflow)
        self.assertIn("--source-ref refs/heads/main", workflow)
        self.assertIn("--source-digest", workflow)
        self.assertIn("sha256sum --check", workflow)

    def test_release_workflow_requires_main_source(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertIn('test "$GITHUB_REF" = "refs/heads/main"', workflow)

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
        self.assertIn("업무 의미·권한·파괴 범위를 바꾸는 불확실성", agents)
        self.assertIn("precondition과 postcondition/business invariant", agents)

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


class RoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = mod.load_json(ROOT / "POLICY_CONTRACT.json")

    def route(self, task="", operations=(), resources=()):
        return mod.route_policies(self.contract, task, operations, resources)

    def assertExactPolicies(self, task, expected, operations=(), resources=()):
        result = self.route(task, operations, resources)
        self.assertEqual(set(expected), set(result["policies"]), (task, result))
        return result

    def test_common_development_commands_have_specific_operations(self):
        cases = [
            ("npm run build", "build.execute"),
            ("ruff check .", "lint.execute"),
            ("mypy src", "typecheck.execute"),
            ("ruff format .", "format.execute"),
        ]
        for text, operation in cases:
            with self.subTest(text=text):
                routed = self.route(text)
                self.assertIn(operation, routed["canonical_operations"], routed)

    def test_tracked_delete_requires_specific_operation(self):
        routed = self.route("delete clean git tracked file")
        self.assertIn("filesystem.tracked_delete", routed["canonical_operations"], routed)

    def test_korean_bug_and_unit_test(self):
        r = self.assertExactPolicies("버그를 고치고 단위 테스트도 추가해줘", ["implementation", "testing"])
        self.assertIn("code.modify", r["canonical_operations"])
        self.assertIn("test.design", r["canonical_operations"])

    def test_korean_refactor(self):
        self.assertExactPolicies("이 함수 리팩터링해줘", ["implementation", "testing"])

    def test_plain_function_edit_routes_implementation(self):
        r = self.assertExactPolicies("이 함수 수정해줘", ["implementation", "testing"])
        self.assertEqual(["code.modify"], r["canonical_operations"])

    def test_english_rename_routes_implementation(self):
        self.assertExactPolicies("rename this function", ["implementation", "testing"])

    def test_login_does_not_false_match_log_observability(self):
        r = self.assertExactPolicies("로그인 화면 문구 바꿔줘", ["implementation", "testing", "security"])
        self.assertNotIn("observability", r["policies"])
        self.assertIn("auth.change", r["canonical_operations"])

    def test_log_analysis_routes_observability(self):
        self.assertExactPolicies("로그 분석해줘", ["observability", "execution"])

    def test_english_auth_bug_and_tests(self):
        self.assertExactPolicies("fix the auth bug and add unit tests", ["security", "implementation", "testing"])

    def test_english_refactor_and_run_tests(self):
        self.assertExactPolicies("refactor this function and run tests", ["implementation", "testing", "execution"])

    def test_korean_production_deploy_inflection(self):
        self.assertExactPolicies("프로덕션에 배포해줘", ["execution", "deployment"])

    def test_korean_database_migration_inflection(self):
        self.assertExactPolicies("데이터베이스 마이그레이션해줘", ["data_safety", "execution"])

    def test_test_colloquial(self):
        r = self.assertExactPolicies("테스트 돌려줘", ["testing", "execution"])
        self.assertIn("test.execute", r["canonical_operations"])

    def test_exact_canonical_operation_is_preferred(self):
        r = self.assertExactPolicies("문제 해결해줘", ["testing", "execution"], operations=["test.execute"])
        self.assertEqual(["test.execute"], r["canonical_operations"])
        self.assertEqual([], r["unresolved_operations"])

    def test_legacy_operation_alias_is_normalized(self):
        r = self.route("", operations=["run tests"])
        self.assertIn("test.execute", r["canonical_operations"])
        self.assertEqual([], r["unresolved_operations"])

    def test_unknown_planned_operation_is_not_silently_ignored(self):
        r = self.route("문제 해결", operations=["do mysterious thing"])
        self.assertEqual(["do mysterious thing"], r["unresolved_operations"])
        self.assertTrue(r["warnings"])

    def test_rm_rf_routes_execution_and_file_handling_conservatively(self):
        r = self.assertExactPolicies("", ["execution", "file_handling"], operations=["rm -rf build"])
        self.assertIn("filesystem.delete", r["canonical_operations"])

    def test_generated_delete_has_separate_l2_operation(self):
        r = self.assertExactPolicies("", ["execution", "file_handling"], operations=["filesystem.generated_delete"])
        self.assertIn("filesystem.generated_delete", r["canonical_operations"])

    def test_git_reset_hard_routes_git_and_execution(self):
        r = self.assertExactPolicies("", ["git", "execution"], operations=["git reset --hard HEAD~1"])
        self.assertIn("git.destructive_change", r["canonical_operations"])

    def test_drop_table_routes_data_safety_and_execution(self):
        r = self.assertExactPolicies("DROP TABLE users 실행", ["data_safety", "execution"])
        self.assertIn("database.destructive_change", r["canonical_operations"])

    def test_iam_change_routes_security_and_execution(self):
        r = self.assertExactPolicies("AWS IAM role 바꿔줘", ["security", "execution"])
        self.assertIn("iam.change", r["canonical_operations"])

    def test_external_message_routes_execution(self):
        r = self.assertExactPolicies("Slack에 메시지 보내줘", ["execution"])
        self.assertIn("external.message_send", r["canonical_operations"])

    def test_resource_adds_security_policy(self):
        self.assertExactPolicies(
            "이 파일 수정",
            ["implementation", "testing", "security"],
            resources=["src/auth/login.py"],
        )

    def test_resource_adds_dependency_policy(self):
        self.assertExactPolicies("업데이트", ["dependencies"], resources=["package.json"])

    def test_resource_adds_deployment_policy(self):
        self.assertExactPolicies("설정 변경", ["deployment"], resources=[".github/workflows/deploy.yml"])

    def test_scenario_toctou_routes_real_policies(self):
        r = self.assertExactPolicies(
            "TOCTOU 테스트 해줘",
            ["testing", "implementation", "execution"],
        )
        self.assertIn("test.scenario.toctou", r["canonical_operations"])

    def test_scenario_replay_idempotency_routes_real_policies(self):
        r = self.assertExactPolicies(
            "멱등성 테스트 해줘",
            ["testing", "implementation", "data_safety", "execution"],
        )
        self.assertIn("test.scenario.replay_idempotency", r["canonical_operations"])

    def test_scenario_transaction_rollback_canonical_operation(self):
        r = self.assertExactPolicies(
            "",
            ["testing", "data_safety", "execution"],
            operations=["test.scenario.transaction_rollback"],
        )
        self.assertEqual([], r["unresolved_operations"])

    def test_scenario_concurrency_routes_real_policies(self):
        r = self.assertExactPolicies(
            "동시성 테스트 해줘",
            ["testing", "implementation", "data_safety", "execution"],
        )
        self.assertIn("test.scenario.concurrency", r["canonical_operations"])

    def test_scenario_security_routes_real_policies(self):
        r = self.assertExactPolicies(
            "보안 테스트 해줘",
            ["testing", "security", "execution"],
        )
        self.assertIn("test.scenario.security", r["canonical_operations"])

    def test_scenario_file_canonical_operation(self):
        r = self.assertExactPolicies(
            "",
            ["testing", "file_handling", "security", "execution"],
            operations=["test.scenario.file"],
        )
        self.assertEqual([], r["unresolved_operations"])

    def test_scenario_external_system_routes_real_policies(self):
        r = self.assertExactPolicies(
            "외부 시스템 테스트 해줘",
            ["testing", "execution"],
        )
        self.assertIn("test.scenario.external_system", r["canonical_operations"])


    def test_common_development_fallback_corpus(self):
        cases = [
            ("API 엔드포인트 만들어줘", {"implementation", "testing"}, "code.modify"),
            ("React 컴포넌트 추가해줘", {"implementation", "testing"}, "code.modify"),
            ("fix null pointer exception", {"implementation", "testing"}, "code.modify"),
            ("update README", {"implementation"}, "documentation.modify"),
            ("rename variable x to y", {"implementation", "testing"}, "code.modify"),
            ("run npm test", {"testing", "execution"}, "test.execute"),
            ("change CORS policy", {"security", "implementation", "testing"}, "security.configuration_change"),
            ("add index to users table", {"data_safety", "execution"}, "database.schema_change"),
            ("publish docker image", {"deployment", "execution"}, "artifact.publish"),
            ("send a Slack message", {"execution"}, "external.message_send"),
        ]
        for task, policies, operation in cases:
            with self.subTest(task=task):
                result = self.route(task)
                self.assertEqual(policies, set(result["policies"]), result)
                self.assertIn(operation, result["canonical_operations"], result)

    def test_unclassified_task_is_visible(self):
        r = self.route("do something mysterious")
        self.assertEqual("UNCLASSIFIED", r["task_hint_status"])
        self.assertEqual("WARN", r["routing_status"])
        self.assertTrue(any("did not resolve" in w for w in r["warnings"]))

    def test_generic_programming_words_do_not_route_to_git_or_release(self):
        cases = [
            "commit transaction after validation",
            "push item into array",
            "release memory after request",
            "create a new branch in this if statement",
            "merge these two arrays",
        ]
        for task in cases:
            with self.subTest(task=task):
                r = self.route(task)
                self.assertFalse(any(x.startswith("git.") for x in r["canonical_operations"]), r)
                self.assertNotIn("release.publish", r["canonical_operations"], r)

    def test_high_risk_natural_language_hints_are_detected(self):
        cases = [
            ("운영 서버에 올려줘", "deploy.execute"),
            ("사용자 테이블의 모든 행을 비워줘", "database.destructive_change"),
            ("npm publish 실행해줘", "package.publish"),
            ("kubectl apply 해줘", "deploy.execute"),
            ("delete all customer records in production", "database.destructive_change"),
        ]
        for task, expected in cases:
            with self.subTest(task=task):
                r = self.route(task)
                self.assertIn(expected, r["canonical_operations"], r)


    def test_reviewed_routing_gaps_are_now_classified(self):
        cases = [
            ("프로덕션 DB에서 고객 데이터 조회해줘", "database.read", {"data_safety", "execution"}),
            ("운영 DB에서 사용자 10명만 조회해줘", "database.read", {"data_safety", "execution"}),
            ("권한을 읽기 전용으로 바꿔줘", "permission.change", {"security", "execution"}),
            ("이 브랜치 원격에 올려줘", "git.push", {"git", "execution"}),
            ("users 테이블에서 모든 행 삭제해줘", "database.destructive_change", {"data_safety", "execution"}),
            ("README 고쳐줘", "documentation.modify", {"implementation"}),
        ]
        for task, operation, policies in cases:
            with self.subTest(task=task):
                r = self.route(task)
                self.assertIn(operation, r["canonical_operations"], r)
                self.assertTrue(policies <= set(r["policies"]), r)

    def test_enforcement_requires_resolved_plan_even_when_task_is_unclassified(self):
        r = mod.route_policies(self.contract, "do something mysterious", routing_mode="enforcement")
        self.assertEqual("FAIL", r["routing_status"])
        self.assertTrue(any("requires at least one resolved planned" in x for x in r["errors"]), r)
        self.assertTrue(any("did not resolve" in x for x in r["warnings"]), r)

    def test_enforcement_mode_fails_closed_for_unknown_planned_operation(self):
        r = mod.route_policies(self.contract, "", ["do mysterious thing"], routing_mode="enforcement")
        self.assertEqual("FAIL", r["routing_status"])
        self.assertEqual(["do mysterious thing"], r["unresolved_operations"])

    def test_enforcement_unclassified_task_is_advisory_when_canonical_plan_exists(self):
        r = mod.route_policies(
            self.contract,
            "invoke the internal admin endpoint to frobnicate tenant state",
            ["code.modify"],
            routing_mode="enforcement",
        )
        self.assertEqual("UNCLASSIFIED", r["task_hint_status"])
        self.assertEqual("WARN", r["routing_status"])
        self.assertEqual([], r["errors"], r)
        self.assertTrue(any("did not resolve" in x for x in r["warnings"]), r)

    def test_enforcement_surfaces_task_plan_underdeclaration_as_anomaly(self):
        r = mod.route_policies(
            self.contract,
            "invoke the internal admin endpoint to purge tenant records",
            ["code.modify"],
            routing_mode="enforcement",
        )
        self.assertIn("database.destructive_change", r["canonical_operations"])
        self.assertIn("database.destructive_change", r["task_plan_gaps"])
        self.assertEqual("WARN", r["routing_status"])
        self.assertEqual([], r["errors"], r)

    def test_v6_runtime_taxonomy_covers_common_operational_actions(self):
        cases = [
            ("terraform destroy -auto-approve", "cloud.resource_delete"),
            ("kubectl delete pod api-123", "cloud.resource_change"),
            ("restart the production service", "service.restart"),
            ("export all customer data to csv", "data.export"),
            ("change firewall rules", "network.configuration_change"),
            ("create a new cloud admin role", "iam.change"),
            ("프로덕션 S3 버킷 파일 전부 삭제해", "storage.object_delete"),
            ("read secret from secret manager", "secret.read"),
        ]
        for task, expected in cases:
            with self.subTest(task=task):
                r = self.route(task)
                self.assertIn(expected, r["canonical_operations"], r)

    def test_broader_dependency_resource_fallbacks(self):
        for resource in ["pom.xml", "services/api/build.gradle.kts", "Directory.Packages.props", "Package.swift", "pubspec.yaml", "uv.lock"]:
            with self.subTest(resource=resource):
                r = self.route(resources=[resource])
                self.assertIn("dependencies", r["policies"], r)

    def test_broader_deployment_resource_fallbacks(self):
        for resource in [".gitlab-ci.yml", "Jenkinsfile", ".circleci/config.yml", "Pulumi.prod.yaml", "serverless.yml"]:
            with self.subTest(resource=resource):
                r = self.route(resources=[resource])
                self.assertIn("deployment", r["policies"], r)

    def test_effect_floor_is_exposed_for_canonical_operations(self):
        r = self.route(operations=["database.destructive_change", "git.push"])
        self.assertEqual("L4", r["effect_floors"]["database.destructive_change"])
        self.assertEqual("L3", r["effect_floors"]["git.push"])

    def test_execution_required_operations_always_route_execution(self):
        for operation in self.contract["routing"]["operation_catalog"]:
            if operation["requires_execution_policy"]:
                with self.subTest(operation=operation["id"]):
                    r = self.route(operations=[operation["id"]])
                    self.assertIn("execution", r["policies"], r)

    def test_alias_file_has_exact_canonical_operation_coverage(self):
        aliases = mod.load_routing_aliases(self.contract)
        canonical = {item["id"] for item in self.contract["routing"]["operation_catalog"]}
        self.assertEqual(canonical, set(aliases["operations"]))

    def test_all_scenario_ids_are_in_contract(self):
        expected = {
            "test.scenario.toctou",
            "test.scenario.replay_idempotency",
            "test.scenario.transaction_rollback",
            "test.scenario.concurrency",
            "test.scenario.security",
            "test.scenario.file",
            "test.scenario.external_system",
        }
        actual = {item["id"] for item in self.contract["routing"]["operation_catalog"]}
        self.assertTrue(expected <= actual)


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


class ReadinessTests(unittest.TestCase):
    def write_project(self, root: Path, data: dict):
        content = (
            "# PROJECT.md\n\n"
            + mod.PROJECT_START
            + "\n```json\n"
            + json.dumps(data, ensure_ascii=False, indent=2)
            + "\n```\n"
            + mod.PROJECT_END
            + "\n"
        )
        path = root / "PROJECT.md"
        path.write_text(content, encoding="utf-8")
        return path

    def base_data(self):
        return {
            "profile": "project",
            "facts": {
                "repository_root": {"value": ".", "status": "Confirmed", "evidence": "path:."},
                "primary_source": {"value": "src", "status": "Confirmed", "evidence": "path:src"},
                "build_command": {"value": "python -m build", "status": "Confirmed", "evidence": "manual:checked project tooling"},
                "test_command": {"value": "python -m unittest", "status": "Confirmed", "evidence": "manual:checked project tooling"},
                "runtime": {"value": "Python", "status": "Confirmed", "evidence": "manual:checked runtime"},
                "deploy_command": {"value": "", "status": "Unknown", "evidence": ""},
                "deploy_target": {"value": "", "status": "Unknown", "evidence": ""},
            },
            "components": [{"name": "core", "path": "src", "responsibility": "core"}],
            "review": {"reviewed_revision": "manual-revision", "reviewed_at": "2026-09-19"},
        }

    def test_readiness_can_use_project_file_with_independent_project_root(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            project_root = base / "consumer"
            policy_root = project_root / ".agent-policy"
            policy_root.mkdir(parents=True)
            (project_root / "src").mkdir()
            data = self.base_data()
            path = self.write_project(project_root, data)
            result = mod.readiness(path, "development", project_root)
            primary = next(x for x in result["verified_checks"] if x["name"] == "primary_source")
            self.assertEqual("PASS", primary["status"], result)

    def test_resolve_readiness_context_accepts_explicit_consumer_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = root / "PROJECT.md"
            project.write_text("# placeholder\n", encoding="utf-8")
            resolved_file, resolved_root = mod.resolve_readiness_context(project, root)
            self.assertEqual(project.resolve(), resolved_file)
            self.assertEqual(root.resolve(), resolved_root)

    def test_readiness_context_rejects_project_file_outside_root(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "repo"
            root.mkdir()
            outside = base / "PROJECT.md"
            outside.write_text("# placeholder\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                mod.resolve_readiness_context(outside, root)

    def test_confirmed_fake_path_does_not_verify(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = self.base_data()
            data["facts"]["primary_source"] = {"value": "definitely-missing", "status": "Confirmed", "evidence": "path:definitely-missing"}
            path = self.write_project(root, data)
            r = mod.readiness(path, "development")
            self.assertEqual("PASS", r["documented"])
            self.assertEqual("FAIL", r["verified"])

    def test_documented_can_be_partial_verified(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "src").mkdir()
            data = self.base_data()
            path = self.write_project(root, data)
            r = mod.readiness(path, "development")
            self.assertEqual("PASS", r["documented"])
            self.assertEqual("PARTIAL", r["verified"])


    def test_primary_source_evidence_must_identify_same_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "src").mkdir()
            (root / "other").mkdir()
            data = self.base_data()
            data["facts"]["primary_source"] = {"value": "src", "status": "Confirmed", "evidence": "path:other"}
            path = self.write_project(root, data)
            r = mod.readiness(path, "development")
            check = next(x for x in r["verified_checks"] if x["name"] == "primary_source")
            self.assertEqual("FAIL", check["status"])

    def test_command_fact_rejects_unrelated_path_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "src").mkdir()
            (root / "pyproject.toml").write_text("[build-system]\n", encoding="utf-8")
            data = self.base_data()
            data["facts"]["build_command"] = {
                "value": "totally nonexistent build command", "status": "Confirmed", "evidence": "path:pyproject.toml"
            }
            path = self.write_project(root, data)
            r = mod.readiness(path, "development")
            check = next(x for x in r["verified_checks"] if x["name"] == "build_command")
            self.assertEqual("FAIL", check["status"])

    def test_command_source_must_match_documented_command(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "src").mkdir()
            (root / "Makefile").write_text("build:\n\tpython -m build\n", encoding="utf-8")
            data = self.base_data()
            data["facts"]["build_command"] = {
                "value": "python -m build", "status": "Confirmed", "evidence": "command-source:Makefile::python -m build"
            }
            path = self.write_project(root, data)
            r = mod.readiness(path, "development")
            check = next(x for x in r["verified_checks"] if x["name"] == "build_command")
            self.assertEqual("PASS", check["status"])

    def test_command_source_literal_cannot_verify_different_value(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "src").mkdir()
            (root / "Makefile").write_text("build:\n\tpython -m build\n", encoding="utf-8")
            data = self.base_data()
            data["facts"]["build_command"] = {
                "value": "evil-build --publish", "status": "Confirmed", "evidence": "command-source:Makefile::python -m build"
            }
            path = self.write_project(root, data)
            r = mod.readiness(path, "development")
            check = next(x for x in r["verified_checks"] if x["name"] == "build_command")
            self.assertEqual("FAIL", check["status"])

    def test_malformed_fact_object_returns_structured_fail_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = self.base_data()
            data["facts"]["repository_root"] = "not-an-object"
            path = self.write_project(root, data)
            result = mod.readiness(path, "development")
            self.assertEqual("FAIL", result["documented"])
            self.assertEqual("FAIL", result["verified"])
            self.assertTrue(any("facts.repository_root must be an object" in x for x in result["errors"]), result)

    def test_malformed_component_returns_structured_fail_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = self.base_data()
            data["components"] = ["not-an-object"]
            path = self.write_project(root, data)
            result = mod.readiness(path, "development")
            self.assertEqual("FAIL", result["documented"])
            self.assertTrue(any("components[0] must be an object" in x for x in result["errors"]), result)

    def test_stale_reviewed_at_emits_nonblocking_warning(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "src").mkdir()
            data = self.base_data()
            data["review"]["reviewed_at"] = "2020-01-01"
            path = self.write_project(root, data)
            result = mod.readiness(path, "development")
            self.assertEqual("PASS", result["documented"])
            self.assertTrue(any("last reviewed" in x for x in result["warnings"]), result)

    def test_future_reviewed_at_fails_verification(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "src").mkdir()
            data = self.base_data()
            data["review"]["reviewed_at"] = "2999-01-01"
            path = self.write_project(root, data)
            result = mod.readiness(path, "development")
            check = next(x for x in result["verified_checks"] if x["name"] == "reviewed_at")
            self.assertEqual("FAIL", check["status"])

    def test_template_is_not_ready(self):
        r = mod.readiness(ROOT / "PROJECT.md", "development")
        self.assertEqual("FAIL", r["documented"])

    def test_readiness_distinguishes_evidence_from_command_execution(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "src").mkdir()
            data = self.base_data()
            path = self.write_project(root, data)
            result = mod.readiness(path, "development")
            self.assertEqual(result["verified"], result["evidence_verified"])
            self.assertEqual("NOT_RUN", result["execution_verified"])

    def test_component_specific_facts_are_supported_and_verified(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "src").mkdir()
            (root / "services" / "api").mkdir(parents=True)
            (root / "services" / "api" / "Makefile").write_text("test:\n\tpython -m pytest\n", encoding="utf-8")
            data = self.base_data()
            data["components"].append({
                "name": "api",
                "path": "services/api",
                "responsibility": "api",
                "facts": {
                    "test_command": {
                        "value": "python -m pytest",
                        "status": "Confirmed",
                        "evidence": "command-source:services/api/Makefile::python -m pytest",
                    }
                },
            })
            path = self.write_project(root, data)
            result = mod.readiness(path, "development")
            check = next(x for x in result["verified_checks"] if x["name"] == "components[1].test_command")
            self.assertEqual("PASS", check["status"], result)


    def test_comment_only_command_source_does_not_verify(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "Makefile").write_text("# obsolete example: python -m unittest\n", encoding="utf-8")
            status, detail = mod.verify_fact_evidence(
                root, "test_command", "python -m unittest", "command-source:Makefile::python -m unittest"
            )
            self.assertEqual("FAIL", status, detail)
            self.assertIn("not active", detail)

    def test_reviewed_paths_allow_unrelated_head_changes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess = __import__("subprocess")
            subprocess.run(["git", "init"], cwd=root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            (root / "facts.txt").write_text("stable\n", encoding="utf-8")
            subprocess.run(["git", "add", "facts.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "facts"], cwd=root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            reviewed = mod.git_head(root)
            self.assertIsNotNone(reviewed)
            (root / "unrelated.txt").write_text("later\n", encoding="utf-8")
            subprocess.run(["git", "add", "unrelated.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "unrelated"], cwd=root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            unchanged, detail = mod.git_reviewed_paths_unchanged(root, reviewed, ["facts.txt"])
            self.assertIs(True, unchanged, detail)
            (root / "facts.txt").write_text("changed\n", encoding="utf-8")
            subprocess.run(["git", "add", "facts.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "facts changed"], cwd=root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            unchanged, detail = mod.git_reviewed_paths_unchanged(root, reviewed, ["facts.txt"])
            self.assertIs(False, unchanged, detail)


class BootstrapTests(unittest.TestCase):
    def test_bootstrap_generates_only_inferred_or_unknown_facts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "src").mkdir()
            (root / "package.json").write_text(json.dumps({
                "scripts": {"build": "npm run compile", "test": "node --test"},
                "engines": {"node": ">=22"},
            }), encoding="utf-8")
            output = root / "PROJECT.inferred.md"
            result = mod.bootstrap_project(root, output)
            self.assertEqual("PASS", result["status"], result)
            data = mod.parse_project_facts(output)
            statuses = {fact["status"] for fact in data["facts"].values()}
            self.assertTrue(statuses <= {"Inferred", "Unknown", "N/A"}, statuses)
            self.assertNotIn("Confirmed", statuses)
            readiness = mod.readiness(output, "development")
            self.assertEqual("FAIL", readiness["documented"], readiness)

    def test_bootstrap_refuses_to_overwrite_existing_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "PROJECT.inferred.md"
            output.write_text("do not overwrite", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                mod.bootstrap_project(root, output)
            self.assertEqual("do not overwrite", output.read_text(encoding="utf-8"))


class DistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = mod.load_json(ROOT / "POLICY_CONTRACT.json")
        cls.required = cls.contract["distribution"]["required_files"]
        cls.canonical_root = cls.contract["distribution"]["canonical_root"]

    def write_valid_zip(self, path: Path, mutate=None, extras=None):
        with zipfile.ZipFile(path, "w") as zf:
            for rel in self.required:
                data = (ROOT / rel).read_bytes()
                if mutate is not None:
                    data = mutate(rel, data)
                zf.writestr(f"{self.canonical_root}/{rel}", data)
            for name, data in extras or []:
                zf.writestr(name, data)

    def test_complete_zip_passes(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "universal-agent-docs.zip"
            self.write_valid_zip(z)
            result = mod.validate_distribution(z, self.contract)
            self.assertEqual("PASS", result["status"], result)

    def test_partial_zip_fails_missing_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "partial.zip"
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr("universal-agent-docs/AGENTS.md", "ok")
            result = mod.validate_distribution(z, self.contract)
            self.assertEqual("FAIL", result["status"])
            self.assertTrue(result["missing"])

    def test_zip_with_pyc_fails(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "bad.zip"
            self.write_valid_zip(z, extras=[("universal-agent-docs/scripts/__pycache__/x.pyc", b"x")])
            result = mod.validate_distribution(z, self.contract)
            self.assertEqual("FAIL", result["status"])
            self.assertTrue(result["forbidden"])

    def test_zip_with_unexpected_file_fails(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "bad.zip"
            self.write_valid_zip(z, extras=[("universal-agent-docs/EXTRA.txt", b"x")])
            result = mod.validate_distribution(z, self.contract)
            self.assertEqual("FAIL", result["status"])
            self.assertIn("EXTRA.txt", result["unexpected"])

    def test_zip_traversal_entry_fails(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "bad.zip"
            self.write_valid_zip(z, extras=[("../outside.txt", b"x")])
            result = mod.validate_distribution(z, self.contract)
            self.assertEqual("FAIL", result["status"])
            self.assertTrue(result["unsafe_entries"])

    def test_zip_absolute_entry_fails(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "bad.zip"
            self.write_valid_zip(z, extras=[("/outside.txt", b"x")])
            result = mod.validate_distribution(z, self.contract)
            self.assertEqual("FAIL", result["status"])
            self.assertTrue(result["unsafe_entries"])

    def test_zip_duplicate_entry_fails(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "bad.zip"
            self.write_valid_zip(z)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(z, "a") as zf:
                    zf.writestr("universal-agent-docs/AGENTS.md", "duplicate")
            result = mod.validate_distribution(z, self.contract)
            self.assertEqual("FAIL", result["status"])
            self.assertTrue(result["duplicate_entries"])

    def test_zip_symlink_entry_fails(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "bad.zip"
            self.write_valid_zip(z)
            info = zipfile.ZipInfo("universal-agent-docs/link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(z, "a") as zf:
                zf.writestr(info, "AGENTS.md")
            result = mod.validate_distribution(z, self.contract)
            self.assertEqual("FAIL", result["status"])
            self.assertTrue(result["symlinks"])


    def test_zip_casefold_name_collision_fails(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "bad.zip"
            self.write_valid_zip(z, extras=[(f"{self.canonical_root}/readme.md", b"x")])
            result = mod.validate_distribution(z, self.contract)
            self.assertEqual("FAIL", result["status"])
            self.assertTrue(result["name_collisions"])

    def test_zip_unicode_normalization_collision_fails(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "bad.zip"
            self.write_valid_zip(z, extras=[
                (f"{self.canonical_root}/caf\u00e9.txt", b"x"),
                (f"{self.canonical_root}/cafe\u0301.txt", b"x"),
            ])
            result = mod.validate_distribution(z, self.contract)
            self.assertEqual("FAIL", result["status"])
            self.assertTrue(result["name_collisions"])

    def test_zip_file_size_limit_fails_before_extraction(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "bad.zip"
            limit = self.contract["distribution"]["max_file_uncompressed_bytes"]
            def mutate(rel, data):
                return b"x" * (limit + 1) if rel == "AGENTS.md" else data
            self.write_valid_zip(z, mutate=mutate)
            result = mod.validate_distribution(z, self.contract)
            self.assertEqual("FAIL", result["status"])
            self.assertTrue(result["resource_limit_violations"])

    def test_zip_compression_ratio_limit_fails(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "bad.zip"
            with zipfile.ZipFile(z, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for rel in self.required:
                    data = (ROOT / rel).read_bytes()
                    if rel == "AGENTS.md":
                        data = b"A" * 300000
                    zf.writestr(f"{self.canonical_root}/{rel}", data)
            result = mod.validate_distribution(z, self.contract)
            self.assertEqual("FAIL", result["status"])
            self.assertTrue(any("compression ratio" in x for x in result["resource_limit_violations"]), result)

    def test_semantically_broken_bundle_fails_even_with_complete_manifest(self):
        def mutate(rel, data):
            if rel == "POLICY_CONTRACT.json":
                obj = json.loads(data.decode("utf-8"))
                obj["project_name"] = "wrong-name"
                return json.dumps(obj).encode("utf-8")
            return data

        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "bad.zip"
            self.write_valid_zip(z, mutate=mutate)
            result = mod.validate_distribution(z, self.contract)
            self.assertEqual("FAIL", result["status"])
            self.assertTrue(result["bundle_failures"])

    def test_trusted_manifest_detects_semantic_policy_mutation_in_distribution(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = Path(td) / "trusted.json"
            mod.write_trust_manifest(manifest, ROOT)

            def mutate(rel, data):
                if rel == "POLICIES.md":
                    text = data.decode("utf-8")
                    text = text.replace(
                        "operational instruction으로 승격하지 않는다",
                        "operational instruction으로 승격한다",
                        1,
                    )
                    return text.encode("utf-8")
                return data

            z = Path(td) / "tampered.zip"
            self.write_valid_zip(z, mutate=mutate)
            result = mod.validate_distribution(z, self.contract, manifest)
            self.assertEqual("FAIL", result["status"])
            self.assertIn("sha256 mismatch: POLICIES.md", result["integrity_failures"])

    def test_full_release_manifest_verifies_archive_and_all_distribution_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            z = root / "universal-agent-docs.zip"
            manifest = root / "universal-agent-docs.release.json"
            self.write_valid_zip(z)
            data = mod.write_release_manifest(manifest, z, ROOT)
            self.assertIn("PROJECT.md", data["files"])
            self.assertIn("tests/test_policy.py", data["files"])
            result = mod.validate_distribution(z, self.contract, release_manifest=manifest)
            self.assertEqual("PASS", result["status"], result)

    def test_full_release_manifest_detects_non_core_release_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            z = root / "universal-agent-docs.zip"
            manifest = root / "universal-agent-docs.release.json"
            self.write_valid_zip(z)
            mod.write_release_manifest(manifest, z, ROOT)

            def mutate(rel, data):
                if rel == "README.md":
                    return data + b"\n"
                return data

            self.write_valid_zip(z, mutate=mutate)
            result = mod.validate_distribution(z, self.contract, release_manifest=manifest)
            self.assertEqual("FAIL", result["status"], result)
            self.assertTrue(result["release_integrity_failures"], result)
            self.assertTrue(any("artifact SHA-256 mismatch" in x or "README.md" in x for x in result["release_integrity_failures"]), result)

    def test_complete_directory_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / self.canonical_root
            root.mkdir()
            for rel in self.required:
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / rel, target)
            result = mod.validate_distribution(root, self.contract)
            self.assertEqual("PASS", result["status"], result)


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


if __name__ == "__main__":
    unittest.main()
