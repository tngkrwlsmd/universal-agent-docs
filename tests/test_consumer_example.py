from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from .policy_test_support import ROOT, mod


EXAMPLE = ROOT / "examples" / "consumer-basic"


class ConsumerBasicExampleTests(unittest.TestCase):
    def test_example_paths_and_cli_surface_are_current(self):
        required = [
            EXAMPLE / "README.md",
            EXAMPLE / "before" / "AGENTS.md",
            EXAMPLE / "before" / "Makefile",
            EXAMPLE / "before" / "pyproject.toml",
            EXAMPLE / "before" / "src" / "greeter.py",
            EXAMPLE / "before" / "tests" / "test_greeter.py",
            EXAMPLE / "after" / "AGENTS.md",
            EXAMPLE / "after" / "PROJECT.reviewed.md",
        ]
        self.assertTrue(all(path.is_file() for path in required))
        readme = (EXAMPLE / "README.md").read_text(encoding="utf-8")
        validate_cli = (ROOT / "scripts" / "validate.py").read_text(encoding="utf-8")
        for flag in (
            "--bootstrap-project",
            "--bootstrap-output",
            "--project-root",
            "--readiness",
            "--routing-mode",
            "--route",
            "--operation",
            "--resource",
            "--compiled-policy",
        ):
            self.assertIn(flag, readme)
            self.assertIn(flag, validate_cli)
        self.assertIn("consumer ZIP 설치 != Profile C", readme)
        self.assertIn("bootstrap candidate != canonical PROJECT.md", readme)
        self.assertIn("readiness PASS != build/test command 실행 성공", readme)

    def test_bootstrap_candidate_never_auto_confirms_example_facts(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "consumer-basic"
            shutil.copytree(EXAMPLE / "before", repo)
            candidate = repo / "PROJECT.candidate.md"
            result = mod.bootstrap_project(repo, candidate)
            self.assertEqual("PASS", result["status"], result)
            facts = mod.parse_project_facts(candidate)
            statuses = {
                item["status"]
                for item in facts["facts"].values()
            }
            self.assertNotIn("Confirmed", statuses)
            self.assertEqual("FAIL", mod.readiness(candidate, "development", project_root=repo)["documented"])

    def test_reviewed_after_example_reaches_documented_profile_b_without_execution_claim(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as td:
            repo = Path(td) / "consumer-basic"
            shutil.copytree(EXAMPLE / "after", repo)
            project = repo / "PROJECT.reviewed.md"
            head = mod.git_head(repo)
            self.assertTrue(head)
            project.write_text(
                project.read_text(encoding="utf-8").replace("__REVIEWED_REVISION__", head),
                encoding="utf-8",
            )
            result = mod.readiness(project, "development", project_root=repo)
            self.assertEqual("PASS", result["documented"], result)
            self.assertEqual("PASS", result["evidence_verified"], result)
            self.assertEqual("NOT_RUN", result["execution_verified"], result)

    def test_profile_b_routing_and_compiled_policy_examples_succeed(self):
        contract = mod.load_json(ROOT / "POLICY_CONTRACT.json")
        routed = mod.route_policies(
            contract,
            "modify the greeter and run tests",
            ["code.modify", "test.execute"],
            ["src/greeter.py"],
            "enforcement",
        )
        self.assertEqual("PASS", routed["routing_status"], routed)
        compiled = mod.compile_policy_view(
            contract,
            operations=["code.modify"],
            resources=["src/greeter.py"],
            routing_mode="enforcement",
        )
        self.assertEqual("PASS", compiled["status"], compiled)
        rendered = mod.render_compiled_policy_view(compiled)
        self.assertIn("code.modify", rendered)
        self.assertIn("Applicable primary-owner policy sections", rendered)


if __name__ == "__main__":
    unittest.main()
