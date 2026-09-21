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
    def test_corpora_cover_requested_project_families_and_regression_categories(self):
        corpora = [evaluation.load_corpus(path) for path in evaluation.DEFAULT_CORPORA]
        scenarios = [item for corpus in corpora for item in corpus["scenarios"]]
        project_types = {item["project_type"] for item in scenarios}
        for required in {"python", "node-typescript", "go", "jvm", "monorepo", "docker", "github-actions", "terraform-iac", "database-migration"}:
            self.assertIn(required, project_types)
        categories = {item.get("category") for item in scenarios}
        for required in {"paraphrase", "multilingual", "typo", "negation", "read-only-vs-write", "multi-intent-negation", "untrusted-data", "unknown"}:
            self.assertIn(required, categories)

    def test_runner_reports_quality_dimensions_separately_from_conformance(self):
        result = evaluation.run_evaluation()
        self.assertEqual("universal-agent-docs-evaluation-result-v2", result["format"])
        summary = result["summary"]
        for key in (
            "total_scenarios", "routing_exact_match", "routing_expected_covered",
            "unexpected_operation_count", "false_positive", "false_negative", "effect_mismatch",
            "exposure_mismatch", "gate_mismatch", "readiness_mismatch", "unknown_handled_correctly",
        ):
            self.assertIn(key, summary)
        self.assertEqual(summary["total_scenarios"], len(result["results"]))
        self.assertGreaterEqual(summary["total_scenarios"], 30)

    def test_regression_corpus_has_no_current_mismatch(self):
        result = evaluation.run_evaluation()
        self.assertEqual(0, result["summary"]["mismatches"], result)
        self.assertEqual(0, result["summary"]["false_positive"], result)
        self.assertEqual(0, result["summary"]["false_negative"], result)


if __name__ == "__main__":
    unittest.main()
