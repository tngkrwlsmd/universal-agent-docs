from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CanonicalSourceSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads((ROOT / "POLICY_CONTRACT.json").read_text(encoding="utf-8"))
        cls.allowed = set(cls.contract["distribution"]["allowed_files"])

    def test_all_source_tests_are_in_canonical_distribution_manifest(self):
        discovered = {
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "tests").glob("test_*.py")
        }
        self.assertFalse(discovered - self.allowed, sorted(discovered - self.allowed))

    def test_source_only_tooling_and_examples_are_in_manifest(self):
        expected = {
            "evaluation/README.md",
            "evaluation/scenarios.json",
            "scripts/evaluate.py",
            "scripts/policy_diff.py",
            "scripts/benchmark.py",
            "examples/runtime-adapter/github_issue_adapter.py",
        }
        self.assertFalse(expected - self.allowed, sorted(expected - self.allowed))


if __name__ == "__main__":
    unittest.main()
