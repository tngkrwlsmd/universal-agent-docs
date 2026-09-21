from __future__ import annotations

import json
import unittest
import warnings

from .policy_test_support import ROOT, mod

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
