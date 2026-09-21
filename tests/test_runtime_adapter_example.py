from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "runtime-adapter" / "mock_runtime.py"
spec = importlib.util.spec_from_file_location("uad_mock_runtime_example", EXAMPLE)
example = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = example
spec.loader.exec_module(example)


class RuntimeAdapterExampleTests(unittest.TestCase):
    def test_mock_profile_c_flow_consumes_once_and_blocks_replay(self):
        result = example.run_demo()
        self.assertEqual("PASS", result["boundary"]["status"])
        self.assertEqual("L3", result["boundary"]["effective_effect"])
        self.assertEqual("X2", result["boundary"]["effective_exposure"])
        self.assertEqual("REQUIRE_EXPLICIT_APPROVAL", result["boundary"]["action_gate"])
        self.assertEqual("VALID", result["first_consumption"]["object_validity"])
        self.assertEqual("VALID", result["first_consumption"]["binding"])
        self.assertEqual("CONSUMED", result["first_consumption"]["replay_protection"])
        self.assertEqual("UNVERIFIED", result["first_consumption"]["validator_authority"])
        self.assertEqual("NOT_ESTABLISHED", result["first_consumption"]["validator_authorization"])
        self.assertEqual("INVALID", result["replay_attempt"]["object_validity"])
        self.assertEqual("REPLAY_DETECTED", result["replay_attempt"]["replay_protection"])
        self.assertEqual(1, result["mock_execution_count"])


if __name__ == "__main__":
    unittest.main()
