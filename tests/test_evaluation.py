from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "evaluate.py"
spec = importlib.util.spec_from_file_location("uad_evaluation", RUNNER)
evaluation = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = evaluation
spec.loader.exec_module(evaluation)


class PracticalEvaluationTests(unittest.TestCase):
    def test_corpus_covers_requested_project_families(self):
        corpus = evaluation.load_corpus(ROOT / "evaluation" / "scenarios.json")
        project_types = {item["project_type"] for item in corpus["scenarios"]}
        for required in {
            "python", "node-typescript", "go", "jvm", "monorepo", "docker",
            "github-actions", "terraform-iac", "database-migration",
        }:
            self.assertIn(required, project_types)

    def test_runner_reports_quality_separately_from_conformance(self):
        result = evaluation.run_evaluation()
        self.assertEqual("universal-agent-docs-evaluation-result-v1", result["format"])
        summary = result["summary"]
        for key in (
            "total_scenarios", "routing_exact_match", "routing_acceptable_match",
            "false_positive", "false_negative", "gate_mismatch", "unknown_handled_correctly",
        ):
            self.assertIn(key, summary)
        self.assertEqual(summary["total_scenarios"], len(result["results"]))

    def test_unknown_and_missing_project_facts_are_fail_closed(self):
        result = evaluation.run_evaluation()
        by_id = {item["id"]: item for item in result["results"]}
        self.assertTrue(by_id["unknown-operation-fail-closed"]["unknown_handled_correctly"])
        self.assertEqual("FAIL", by_id["missing-project-facts"]["documented"])


if __name__ == "__main__":
    unittest.main()
