from __future__ import annotations

import json
import tempfile
import unittest
import warnings
from pathlib import Path

from tests.policy_test_support import ROOT, mod

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

    def test_vendored_project_facts_can_validate_against_consumer_repo_root(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "consumer"
            policy = repo / ".agent-policy"
            policy.mkdir(parents=True)
            (repo / "src").mkdir()
            data = self.base_data()
            path = self.write_project(policy, data)
            result = mod.readiness(path, "development", project_root=repo)
            repo_check = next(x for x in result["verified_checks"] if x["name"] == "repository_root")
            source_check = next(x for x in result["verified_checks"] if x["name"] == "primary_source")
            self.assertEqual("PASS", repo_check["status"], result)
            self.assertEqual("PASS", source_check["status"], result)

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
