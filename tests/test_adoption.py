from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.policy_test_support import ROOT, consumer_mod, mod

class AdoptionProfileTests(unittest.TestCase):
    def test_readme_exposes_first_use_decision_acquisition_and_stop_boundary(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        guide = (ROOT / "docs" / "adoption-profiles.md").read_text(encoding="utf-8")
        self.assertLess(readme.index("## 5분 Quick Start"), readme.index("## 문서 지도"))
        for label in ["A — Guidance", "B — Validated", "C — Enforced Runtime"]:
            self.assertIn(label, readme)
        self.assertIn("GitHub Releases", readme)
        self.assertIn("최신 immutable SemVer Release", readme)
        self.assertIn("동일한 full `.agent-policy/` bundle", readme)
        self.assertIn("primary owner는 [Adoption profiles]", readme)
        self.assertIn("consumer installation, PROJECT bootstrap/readiness", guide)
        self.assertIn("Profile A/B consumer example", guide)
        self.assertNotIn("## Protected override", readme)
        self.assertNotIn("## Distribution validation", readme)
        self.assertNotIn("## Runtime integration", readme)
        self.assertLess(len(readme), 12000)
        self.assertNotIn("v0.1.0", readme)
        self.assertNotIn("20d726f845a0e929103a6de57cb1c82eaeffedca", readme)
        self.assertNotIn("blob/main/examples/", readme)
        self.assertNotIn("blob/main/examples/", guide)
        self.assertNotIn("/tmp/uad-consumer", guide)
        self.assertIn("uad-consumer-stage", guide)
        self.assertIn("canonical source Release artifact", guide)

    def test_distribution_docs_explain_source_template_and_file_roles(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        guide = (ROOT / "docs" / "adoption-profiles.md").read_text(encoding="utf-8")
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("templates/PROJECT.md", readme)
        self.assertIn("templates/PROJECT.md", guide)
        self.assertIn("templates/PROJECT.md", agents)
        self.assertIn("distribution.required_files", guide)
        self.assertIn("distribution.allowed_files", guide)
        self.assertIn("consumer packager는 `required_files`", guide)
        self.assertIn("canonical source packager는 `allowed_files`", guide)

    def test_user_facing_commands_do_not_depend_on_known_posix_only_examples(self):
        docs = [
            ROOT / "README.md",
            ROOT / "docs" / "adoption-profiles.md",
            ROOT / "docs" / "extensions.md",
            ROOT / "conformance" / "README.md",
            ROOT / "examples" / "consumer-basic" / "README.md",
            ROOT / "examples" / "runtime-adapter" / "README.md",
        ]
        for path in docs:
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("/tmp/", content, path)
            self.assertNotIn("cp -R", content, path)
            self.assertNotIn("rm -rf", content, path)

    def test_adoption_profiles_are_documentation_not_machine_enforcement_state(self):
        contract = mod.load_json(ROOT / "POLICY_CONTRACT.json")
        self.assertNotIn("adoption_profile", contract)
        self.assertNotIn("adoption_profiles", contract)
        self.assertNotIn("active_profile", contract)
        guide = (ROOT / "docs" / "adoption-profiles.md").read_text(encoding="utf-8")
        self.assertIn("문서 분류", guide)
        self.assertIn("설치 artifact의 파일 subset을 뜻하지 않는다", guide)
        self.assertIn("실행을 intercept하지 않는다", guide)
        self.assertIn("Profile C의 runtime enforcement와 동일하지 않다", guide)
        self.assertNotIn("\\n\\n", guide)

    def test_consumer_bundle_is_one_full_artifact_for_all_profiles(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "dist"
            result = consumer_mod.package_consumer(out)
            self.assertEqual("PASS", result["status"], result)
            self.assertTrue(str(result["zip"]).endswith("universal-agent-docs-consumer.zip"))
            contract = mod.load_json(ROOT / "POLICY_CONTRACT.json")
            root = contract["consumer_distribution"]["canonical_root"]
            policy_root = contract["consumer_distribution"]["policy_root"]
            expected_vendored = {
                f"{root}/{policy_root}/{rel}"
                for rel in contract["distribution"]["required_files"]
            }
            with zipfile.ZipFile(result["zip"]) as zf:
                names = set(zf.namelist())
                self.assertIn(f"{root}/AGENTS.md", names)
                self.assertTrue(expected_vendored <= names)
                self.assertFalse(any(name.startswith(f"{root}/{policy_root}/examples/") for name in names))
                router = zf.read(f"{root}/AGENTS.md").decode("utf-8")
                self.assertIn(f"{policy_root}/PROJECT.md", router)

    def test_empty_repo_consumer_install_template_bootstrap_and_readiness_flow(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            out = base / "dist"
            packaged = consumer_mod.package_consumer(out)
            stage = base / "stage"
            repo = base / "consumer"
            repo.mkdir()
            with zipfile.ZipFile(packaged["zip"]) as zf:
                zf.extractall(stage)

            contract = mod.load_json(ROOT / "POLICY_CONTRACT.json")
            cfg = contract["consumer_distribution"]
            staged_root = stage / cfg["canonical_root"]
            shutil.copytree(staged_root / cfg["policy_root"], repo / cfg["policy_root"])
            shutil.copy2(staged_root / cfg["root_agents_path"], repo / cfg["root_agents_path"])

            canonical_project = repo / ".agent-policy" / "PROJECT.md"
            self.assertTrue((repo / "AGENTS.md").is_file())
            self.assertTrue((repo / ".agent-policy" / "POLICIES.md").is_file())
            template = mod.parse_project_facts(canonical_project)
            self.assertEqual("template", template["profile"])

            template_readiness = mod.readiness(
                canonical_project, "development", project_root=repo
            )
            self.assertEqual("FAIL", template_readiness["documented"], template_readiness)

            (repo / "src").mkdir()
            (repo / "package.json").write_text(
                json.dumps({
                    "scripts": {"build": "npm run build:impl", "test": "node --test"},
                    "engines": {"node": ">=22"},
                }),
                encoding="utf-8",
            )
            candidate = repo / "PROJECT.candidate.md"
            boot = mod.bootstrap_project(repo, candidate)
            self.assertEqual("PASS", boot["status"], boot)
            self.assertNotEqual(canonical_project.resolve(), candidate.resolve())
            facts = mod.parse_project_facts(candidate)
            statuses = {item["status"] for item in facts["facts"].values()}
            self.assertNotIn("Confirmed", statuses)

            candidate_readiness = mod.readiness(candidate, "development", project_root=repo)
            self.assertEqual("FAIL", candidate_readiness["documented"], candidate_readiness)
            self.assertEqual("NOT_RUN", candidate_readiness["execution_verified"])

    def test_existing_root_agents_is_a_manual_no_overwrite_collision(self):
        contract = mod.load_json(ROOT / "POLICY_CONTRACT.json")
        cfg = contract["consumer_distribution"]
        self.assertFalse(cfg["overwrite_existing_root_agents"])
        self.assertTrue(cfg["extraction_requires_collision_check"])
        guide = (ROOT / "docs" / "adoption-profiles.md").read_text(encoding="utf-8")
        self.assertIn("자동 overwrite하거나 단순 append하지 않는다", guide)
        self.assertIn("read and apply `.agent-policy/AGENTS.md`", guide)
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            existing = repo / cfg["root_agents_path"]
            existing.write_text("# Existing project instructions\n", encoding="utf-8")
            self.assertTrue(existing.exists())
            self.assertFalse(cfg["overwrite_existing_root_agents"])
            self.assertEqual("# Existing project instructions\n", existing.read_text(encoding="utf-8"))

    def test_default_project_path_and_custom_project_file_are_both_explicit(self):
        validate_cli = (ROOT / "scripts" / "validate.py").read_text(encoding="utf-8")
        guide = (ROOT / "docs" / "adoption-profiles.md").read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--project-file"', validate_cli)
        self.assertIn("canonical project facts 문서는 `.agent-policy/PROJECT.md`", guide)
        self.assertIn("--project-file ./docs/PROJECT.md", guide)
