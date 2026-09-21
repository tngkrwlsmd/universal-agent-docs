#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATE = ROOT / "scripts" / "validate.py"
spec = importlib.util.spec_from_file_location("uad_validate_evaluation", VALIDATE)
policy = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = policy
spec.loader.exec_module(policy)

DEFAULT_EXPOSURE_FACTS = {
    "data_classification": "public",
    "credential_class": "none",
    "tenant_scope": "single_user",
    "public_visibility": "none",
    "estimated_blast_radius": "single_resource",
    "estimated_financial_impact": "none",
}


def load_corpus(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != "universal-agent-docs-evaluation-v1":
        raise ValueError("unsupported evaluation corpus format")
    if not isinstance(data.get("scenarios"), list):
        raise ValueError("evaluation scenarios must be an array")
    ids = [item.get("id") for item in data["scenarios"]]
    if any(not isinstance(item, str) or not item for item in ids) or len(ids) != len(set(ids)):
        raise ValueError("evaluation scenario ids must be unique non-empty strings")
    return data


def _routing(contract: dict, item: dict) -> dict:
    result = policy.route_policies(contract, item["task"], routing_mode="advisory")
    actual = result["canonical_operations"]
    expected = item.get("expected_operations", [])
    exact = actual == expected
    acceptable = set(expected).issubset(actual)
    false_positive = sorted(set(actual) - set(expected))
    false_negative = sorted(set(expected) - set(actual))
    unknown_ok = bool(item.get("expected_unclassified")) and result["task_hint_status"] == "UNCLASSIFIED"
    passed = exact or (not expected and unknown_ok)
    return {
        "id": item["id"], "kind": "routing", "project_type": item["project_type"],
        "status": "PASS" if passed else "MISMATCH", "expected_operations": expected,
        "actual_operations": actual, "exact_match": exact, "acceptable_match": acceptable,
        "false_positive": false_positive, "false_negative": false_negative,
        "unknown_handled_correctly": unknown_ok,
    }


def _boundary(contract: dict, item: dict) -> dict:
    result = policy.evaluate_execution_boundary(
        contract,
        item.get("planned_operations", []),
        item.get("actual_operations", []),
        item.get("resources", []),
        item.get("targets", []),
        item.get("environment", "local"),
        exposure_facts=item.get("exposure_facts", DEFAULT_EXPOSURE_FACTS),
        correlation_id=f"evaluation-{item['id']}",
        execution_nonce=f"evaluation-{item['id']}-nonce-0001",
        adapter={"id": "evaluation-adapter", "surface": "evaluation", "assertion_source": "tool_adapter"},
        semantic_details=item.get("semantic_details", {}),
    )
    checks = []
    for field, key in (
        ("status", "expected_status"),
        ("effective_effect", "expected_effect"),
        ("effective_exposure", "expected_exposure"),
        ("action_gate", "expected_gate"),
    ):
        if key in item:
            checks.append(result.get(field) == item[key])
    unknown_ok = bool(item.get("expected_unknown_handled")) and result["status"] == "FAIL" and bool(result.get("errors"))
    if item.get("expected_unknown_handled"):
        checks.append(unknown_ok)
    passed = all(checks) if checks else False
    return {
        "id": item["id"], "kind": "boundary", "project_type": item["project_type"],
        "status": "PASS" if passed else "MISMATCH", "boundary_status": result["status"],
        "effective_effect": result.get("effective_effect"), "effective_exposure": result.get("effective_exposure"),
        "action_gate": result.get("action_gate"), "unknown_handled_correctly": unknown_ok,
        "errors": result.get("errors", []),
    }


def _readiness(item: dict) -> dict:
    project_file = ROOT / item["project_file"]
    result = policy.readiness(project_file, "development", project_root=ROOT)
    passed = result["documented"] == item["expected_documented"]
    return {
        "id": item["id"], "kind": "readiness", "project_type": item["project_type"],
        "status": "PASS" if passed else "MISMATCH", "documented": result["documented"],
        "evidence_verified": result["evidence_verified"], "execution_verified": result["execution_verified"],
    }


def run_evaluation(corpus_path: Path = ROOT / "evaluation" / "scenarios.json") -> dict:
    corpus = load_corpus(corpus_path)
    contract = policy.load_json(ROOT / "POLICY_CONTRACT.json")
    results = []
    for item in corpus["scenarios"]:
        kind = item.get("kind")
        if kind == "routing":
            results.append(_routing(contract, item))
        elif kind == "boundary":
            results.append(_boundary(contract, item))
        elif kind == "readiness":
            results.append(_readiness(item))
        else:
            raise ValueError(f"unsupported evaluation kind: {kind!r}")

    routing = [r for r in results if r["kind"] == "routing"]
    boundaries = [r for r in results if r["kind"] == "boundary"]
    summary = {
        "total_scenarios": len(results),
        "passed": sum(r["status"] == "PASS" for r in results),
        "mismatches": sum(r["status"] != "PASS" for r in results),
        "routing_exact_match": sum(r.get("exact_match", False) for r in routing),
        "routing_acceptable_match": sum(r.get("acceptable_match", False) for r in routing),
        "false_positive": sum(len(r.get("false_positive", [])) for r in routing),
        "false_negative": sum(len(r.get("false_negative", [])) for r in routing),
        "gate_mismatch": sum(r["status"] != "PASS" for r in boundaries if r.get("action_gate") is not None),
        "unknown_handled_correctly": sum(r.get("unknown_handled_correctly", False) for r in results),
    }
    return {
        "format": "universal-agent-docs-evaluation-result-v1",
        "corpus": str(corpus_path.relative_to(ROOT)),
        "summary": summary,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run non-normative practical policy evaluation scenarios")
    parser.add_argument("--corpus", type=Path, default=ROOT / "evaluation" / "scenarios.json")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--fail-on-mismatch", action="store_true", help="return non-zero when any evaluation scenario mismatches")
    args = parser.parse_args()
    result = run_evaluation(args.corpus)
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        for key, value in result["summary"].items():
            print(f"{key}: {value}")
    return 1 if args.fail_on_mismatch and result["summary"]["mismatches"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
