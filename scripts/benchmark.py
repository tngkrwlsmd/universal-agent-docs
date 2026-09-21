#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATE = ROOT / "scripts" / "validate.py"
spec = importlib.util.spec_from_file_location("uad_validate_benchmark", VALIDATE)
policy = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = policy
spec.loader.exec_module(policy)


def _text_metrics(text: str) -> dict:
    return {
        "utf8_bytes": len(text.encode("utf-8")),
        "characters": len(text),
        "word_like_units": len(re.findall(r"[\w가-힣]+", text, flags=re.UNICODE)),
    }


def _consumer_artifact_size() -> int:
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "package_consumer.py"), "--output-dir", td],
            cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return (Path(td) / "universal-agent-docs-consumer.zip").stat().st_size


def collect_static_metrics() -> dict:
    contract = policy.load_json(ROOT / "POLICY_CONTRACT.json")
    required = contract["distribution"]["required_files"]
    bundle_bytes = sum((ROOT / rel).stat().st_size for rel in required)
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    compiled_cases = {}
    for name, operations, resources in (
        ("code_modify", ["code.modify"], ["src/simple.py"]),
        ("code_modify_auth", ["code.modify"], ["src/auth/login.py"]),
        ("test_execute", ["test.execute"], ["tests/test_app.py"]),
        ("git_commit", ["git.commit"], [".git/COMMIT_EDITMSG"]),
        ("database_schema_change", ["database.schema_change"], ["db/migrations/001.sql"]),
        ("external_api_write", ["external.api_write"], ["src/integration.py"]),
    ):
        rendered = policy.render_compiled_policy_view(policy.compile_policy_view(
            contract, operations=operations, resources=resources, routing_mode="enforcement"
        ))
        compiled_cases[name] = _text_metrics(rendered)
    compiled = policy.render_compiled_policy_view(policy.compile_policy_view(
        contract, operations=["code.modify"], resources=["src/auth/login.py"], routing_mode="enforcement"
    ))
    conformance_vectors = 0
    for name in ("golden.json", "invalid.json"):
        data = json.loads((ROOT / "conformance" / name).read_text(encoding="utf-8"))
        conformance_vectors += len(data.get("vectors", []))
    schema_count = sum(1 for rel in required if rel.endswith(".schema.json"))
    return {
        "format": "universal-agent-docs-policy-cost-v1",
        "policy_schema_version": contract["schema_version"],
        "full_policy_bundle_bytes": bundle_bytes,
        "agents": _text_metrics(agents),
        "compiled_policy": _text_metrics(compiled),
        "compiled_policy_cases": compiled_cases,
        "operation_count": len(contract["routing"]["operation_catalog"]),
        "schema_count": schema_count,
        "conformance_vector_count": conformance_vectors,
        "consumer_artifact_bytes": _consumer_artifact_size(),
    }


def collect_timing_metrics(repeat: int = 3) -> dict:
    contract = policy.load_json(ROOT / "POLICY_CONTRACT.json")
    validation_times = []
    compile_times = []
    for _ in range(repeat):
        start = time.perf_counter()
        policy.bundle_checks(ROOT)
        validation_times.append((time.perf_counter() - start) * 1000)
        start = time.perf_counter()
        policy.compile_policy_view(contract, operations=["code.modify"], resources=["src/auth/login.py"], routing_mode="enforcement")
        compile_times.append((time.perf_counter() - start) * 1000)
    return {
        "repeat": repeat,
        "validator_bundle_checks_ms_median": sorted(validation_times)[len(validation_times) // 2],
        "compiled_policy_ms_median": sorted(compile_times)[len(compile_times) // 2],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure reproducible policy size baselines and optional local timings")
    parser.add_argument("--static-only", action="store_true", help="omit environment-sensitive timing measurements")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    result = collect_static_metrics()
    if not args.static_only:
        result["timing"] = collect_timing_metrics(max(1, args.repeat))
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
