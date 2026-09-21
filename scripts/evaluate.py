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
    "data_classification": "public", "credential_class": "none", "tenant_scope": "single_user",
    "public_visibility": "none", "estimated_blast_radius": "single_resource", "estimated_financial_impact": "none",
}
DEFAULT_CORPORA = (ROOT / "evaluation" / "smoke.json", ROOT / "evaluation" / "regression.json")


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
    actual, expected = result["canonical_operations"], item.get("expected_operations", [])
    actual_set, expected_set = set(actual), set(expected)
    exact = actual == expected
    expected_covered = expected_set.issubset(actual_set)
    unexpected = sorted(actual_set - expected_set)
    missing = sorted(expected_set - actual_set)
    unknown_ok = bool(item.get("expected_unclassified")) and result["task_hint_status"] == "UNCLASSIFIED"
    passed = exact or (not expected and unknown_ok)
    return {
        "id": item["id"], "kind": "routing", "project_type": item["project_type"], "category": item.get("category", "smoke"),
        "status": "PASS" if passed else "MISMATCH", "expected_operations": expected, "actual_operations": actual,
        "exact_match": exact, "expected_operations_covered": expected_covered,
        "unexpected_operations": unexpected, "false_positive": unexpected, "false_negative": missing,
        "unknown_handled_correctly": unknown_ok,
    }


def _boundary(contract: dict, item: dict) -> dict:
    result = policy.evaluate_execution_boundary(
        contract, item.get("planned_operations", []), item.get("actual_operations", []), item.get("resources", []),
        item.get("targets", []), item.get("environment", "local"), exposure_facts=item.get("exposure_facts", DEFAULT_EXPOSURE_FACTS),
        correlation_id=f"evaluation-{item['id']}", execution_nonce=f"evaluation-{item['id']}-nonce-0001",
        adapter={"id": "evaluation-adapter", "surface": "evaluation", "assertion_source": "tool_adapter"},
        semantic_details=item.get("semantic_details", {}),
    )
    expectations = {"status":"expected_status", "effective_effect":"expected_effect", "effective_exposure":"expected_exposure", "action_gate":"expected_gate"}
    field_matches = {field: result.get(field) == item[key] for field, key in expectations.items() if key in item}
    unknown_ok = bool(item.get("expected_unknown_handled")) and result["status"] == "FAIL" and bool(result.get("errors"))
    checks = list(field_matches.values()) + ([unknown_ok] if item.get("expected_unknown_handled") else [])
    return {
        "id": item["id"], "kind": "boundary", "project_type": item["project_type"], "category": item.get("category", "smoke"),
        "status": "PASS" if checks and all(checks) else "MISMATCH", "boundary_status": result["status"],
        "effective_effect": result.get("effective_effect"), "effective_exposure": result.get("effective_exposure"),
        "action_gate": result.get("action_gate"), "field_matches": field_matches, "unknown_handled_correctly": unknown_ok,
        "errors": result.get("errors", []),
    }


def _readiness(item: dict) -> dict:
    project_file = ROOT / item["project_file"]
    result = policy.readiness(project_file, "development", project_root=ROOT)
    passed = result["documented"] == item["expected_documented"]
    return {"id":item["id"], "kind":"readiness", "project_type":item["project_type"], "category":item.get("category","smoke"),
            "status":"PASS" if passed else "MISMATCH", "documented":result["documented"],
            "evidence_verified":result["evidence_verified"], "execution_verified":result["execution_verified"]}


def run_evaluation(corpus_paths: tuple[Path, ...] = DEFAULT_CORPORA) -> dict:
    contract = policy.load_json(ROOT / "POLICY_CONTRACT.json")
    results, seen = [], set()
    for path in corpus_paths:
        corpus = load_corpus(path)
        for item in corpus["scenarios"]:
            if item["id"] in seen:
                raise ValueError(f"duplicate evaluation scenario across corpora: {item['id']}")
            seen.add(item["id"])
            kind = item.get("kind")
            results.append(_routing(contract, item) if kind == "routing" else _boundary(contract, item) if kind == "boundary" else _readiness(item) if kind == "readiness" else (_ for _ in ()).throw(ValueError(f"unsupported evaluation kind: {kind!r}")))
    routing = [r for r in results if r["kind"] == "routing"]
    boundaries = [r for r in results if r["kind"] == "boundary"]
    readiness = [r for r in results if r["kind"] == "readiness"]
    summary = {
        "total_scenarios": len(results), "passed": sum(r["status"] == "PASS" for r in results), "mismatches": sum(r["status"] != "PASS" for r in results),
        "routing_exact_match": sum(r.get("exact_match", False) for r in routing),
        "routing_expected_covered": sum(r.get("expected_operations_covered", False) for r in routing),
        "unexpected_operation_count": sum(len(r.get("unexpected_operations", [])) for r in routing),
        "false_positive": sum(len(r.get("false_positive", [])) for r in routing), "false_negative": sum(len(r.get("false_negative", [])) for r in routing),
        "effect_mismatch": sum(not r.get("field_matches", {}).get("effective_effect", True) for r in boundaries),
        "exposure_mismatch": sum(not r.get("field_matches", {}).get("effective_exposure", True) for r in boundaries),
        "gate_mismatch": sum(not r.get("field_matches", {}).get("action_gate", True) for r in boundaries),
        "readiness_mismatch": sum(r["status"] != "PASS" for r in readiness),
        "unknown_handled_correctly": sum(r.get("unknown_handled_correctly", False) for r in results),
    }
    return {"format":"universal-agent-docs-evaluation-result-v2", "corpora":[str(p.relative_to(ROOT)) for p in corpus_paths], "summary":summary, "results":results}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run non-normative practical policy evaluation scenarios")
    parser.add_argument("--corpus", type=Path, action="append", help="corpus path; repeat to combine. Defaults to smoke + regression")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--fail-on-mismatch", action="store_true")
    args = parser.parse_args()
    paths = tuple(args.corpus) if args.corpus else DEFAULT_CORPORA
    result = run_evaluation(paths)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) if args.as_json else "\n".join(f"{k}: {v}" for k,v in result["summary"].items()))
    return 1 if args.fail_on_mismatch and result["summary"]["mismatches"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
