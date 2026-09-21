from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark.py"
spec = importlib.util.spec_from_file_location("uad_benchmark", SCRIPT)
benchmark = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = benchmark
spec.loader.exec_module(benchmark)


class PolicyCostBenchmarkTests(unittest.TestCase):
    def test_static_metrics_are_deterministic_and_complete(self):
        first = benchmark.collect_static_metrics()
        second = benchmark.collect_static_metrics()
        self.assertEqual(first, second)
        for key in (
            "full_policy_bundle_bytes", "agents", "compiled_policy", "compiled_policy_cases", "operation_count",
            "schema_count", "conformance_vector_count", "consumer_artifact_bytes",
        ):
            self.assertIn(key, first)
        self.assertGreater(first["consumer_artifact_bytes"], 0)
        self.assertEqual(6, len(first["compiled_policy_cases"]))
        self.assertLess(first["compiled_policy"]["characters"], (ROOT / "POLICIES.md").stat().st_size)


if __name__ == "__main__":
    unittest.main()
