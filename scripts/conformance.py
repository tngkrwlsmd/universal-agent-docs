#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
import stat
import sys
import tempfile
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import validate as policy_validate  # noqa: E402

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None

CORPUS_FORMAT = "universal-agent-docs-conformance-v2"
RESULT_FORMAT = "universal-agent-docs-conformance-result-v1"
SUITE_SCHEMA_VERSION = 2
DEFAULT_CORPORA = [ROOT / "conformance" / "golden.json", ROOT / "conformance" / "invalid.json"]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def json_pointer_get(value: Any, pointer: str) -> Any:
    if pointer == "":
        return value
    if not pointer.startswith("/"):
        raise ValueError(f"invalid JSON pointer: {pointer}")
    current = value
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(token)]
        else:
            current = current[token]
    return current


def compare_normative(actual: dict, expected: dict, pointers: list[str]) -> list[str]:
    mismatches: list[str] = []
    for pointer in pointers:
        try:
            actual_value = json_pointer_get(actual, pointer)
        except Exception as exc:
            mismatches.append(f"{pointer}: actual field missing ({exc})")
            continue
        try:
            expected_value = json_pointer_get(expected, pointer)
        except Exception as exc:
            mismatches.append(f"{pointer}: expected field missing ({exc})")
            continue
        if actual_value != expected_value:
            mismatches.append(
                f"{pointer}: expected={expected_value!r}, actual={actual_value!r}"
            )
    return mismatches


def _reference_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _boundary_input(data: dict) -> dict:
    vector_id = data.get("vector_id", "case")
    return {
        "planned_operations": list(data.get("planned_operations", [])),
        "actual_operations": list(data.get("actual_operations", [])),
        "affected_resources": list(data.get("affected_resources", [])),
        "targets": list(data.get("targets", [])),
        "environment": data.get("environment", "local"),
        "declared_exposure": data.get("declared_exposure"),
        "runtime_effect": data.get("runtime_effect"),
        "actual_action": data.get("actual_action", ""),
        "exposure_facts": copy.deepcopy(data.get("exposure_facts")),
        "correlation_id": data.get("correlation_id", f"conformance-{vector_id}"),
        "execution_nonce": data.get("execution_nonce", f"nonce-{vector_id}-00000001"),
        "adapter": copy.deepcopy(data.get("adapter", {
            "id": "conformance-reference",
            "surface": "language-neutral-suite",
            "assertion_source": "human_reviewed",
            "version": "2",
        })),
        "semantic_details": copy.deepcopy(data.get("semantic_details", {})),
    }


def evaluate_boundary(contract: dict, data: dict) -> dict:
    kwargs = _boundary_input(data)
    return policy_validate.evaluate_execution_boundary(
        contract,
        kwargs["planned_operations"],
        kwargs["actual_operations"],
        kwargs["affected_resources"],
        kwargs["targets"],
        kwargs["environment"],
        kwargs["declared_exposure"],
        kwargs["runtime_effect"],
        kwargs["actual_action"],
        exposure_facts=kwargs["exposure_facts"],
        correlation_id=kwargs["correlation_id"],
        execution_nonce=kwargs["execution_nonce"],
        adapter=kwargs["adapter"],
        semantic_details=kwargs["semantic_details"],
    )


def run_routing(contract: dict, vector: dict) -> dict:
    data = vector["input"]
    return policy_validate.route_policies(
        contract,
        data.get("task_text", ""),
        data.get("planned_operations", []),
        data.get("affected_resources", []),
        data.get("routing_mode", "advisory"),
    )


def run_execution_boundary(contract: dict, vector: dict) -> dict:
    data = copy.deepcopy(vector["input"])
    data["vector_id"] = vector["id"]
    return evaluate_boundary(contract, data)


def run_digest_relation(contract: dict, vector: dict) -> dict:
    data = copy.deepcopy(vector["input"])
    data["vector_id"] = vector["id"]
    first = evaluate_boundary(contract, data["base"])
    relation = data.get("relation", "stable")
    second_input = copy.deepcopy(data["base"])
    for key, value in data.get("mutations", {}).items():
        second_input[key] = value
    second_input["vector_id"] = vector["id"] + "-second"
    second = evaluate_boundary(contract, second_input)
    same = first.get("action_digest") == second.get("action_digest")
    return {
        "first_status": first.get("status"),
        "second_status": second.get("status"),
        "first_digest": first.get("action_digest"),
        "second_digest": second.get("action_digest"),
        "digest_equal": same,
        "relation": relation,
    }


def run_catalog_invariant(contract: dict, vector: dict) -> dict:
    invariant = vector["input"]["invariant"]
    catalog = policy_validate.operation_catalog(contract)
    if invariant == "deprecated_entries_have_replacement":
        deprecated = [op for op in catalog.values() if op.get("lifecycle_status") == "deprecated"]
        invalid = [
            op["id"] for op in deprecated
            if not isinstance(op.get("replacement"), str) or not op.get("replacement")
        ]
        return {
            "status": "PASS" if not invalid else "FAIL",
            "deprecated_count": len(deprecated),
            "invalid_operations": invalid,
        }
    if invariant == "all_catalog_ids_have_effect_floor":
        invalid = [
            op["id"] for op in catalog.values()
            if op.get("effect_floor") not in {"L1", "L2", "L3", "L4"}
        ]
        return {"status": "PASS" if not invalid else "FAIL", "invalid_operations": invalid}
    raise ValueError(f"unsupported catalog invariant: {invariant}")


def _substitute(value: Any, boundary: dict) -> Any:
    replacements = {
        "$ACTION_DIGEST": boundary.get("action_digest"),
        "$CORRELATION_ID": boundary.get("correlation_id"),
        "$EXECUTION_NONCE": boundary.get("execution_nonce"),
        "$ACTUAL_OPERATIONS": boundary.get("actual_operations"),
        "$TARGETS": boundary.get("targets"),
        "$ENVIRONMENT": boundary.get("environment"),
    }
    if isinstance(value, str) and value in replacements:
        return copy.deepcopy(replacements[value])
    if isinstance(value, list):
        return [_substitute(x, boundary) for x in value]
    if isinstance(value, dict):
        return {k: _substitute(v, boundary) for k, v in value.items()}
    return value


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run_assertion(contract: dict, vector: dict, *, protected: bool) -> dict:
    data = copy.deepcopy(vector["input"])
    boundary_input = data["boundary"]
    boundary_input["vector_id"] = vector["id"]
    boundary = evaluate_boundary(contract, boundary_input)
    assertion = _substitute(data["assertion"], boundary)
    reference_time = _reference_time(data.get("reference_time"))
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        assertion_path = root / ("override.json" if protected else "approval.json")
        _write_json(assertion_path, assertion)
        registry = root / "replay.sqlite3"
        func = (
            policy_validate.validate_protected_override
            if protected else policy_validate.validate_approval_assertion
        )
        kwargs = {
            "path": assertion_path,
            "contract": contract,
            "boundary": boundary,
            "root": ROOT,
            "reference_time": reference_time,
        }
        if data.get("replay"):
            kwargs.update({"replay_registry": registry, "consume": True})
            first = func(**kwargs)
            second = func(**kwargs)
            return {
                "boundary_status": boundary.get("status"),
                "boundary_gate": boundary.get("action_gate"),
                "first": first,
                "second": second,
            }
        if data.get("use_registry"):
            kwargs.update({"replay_registry": registry, "consume": bool(data.get("consume"))})
        result = func(**kwargs)
        result["boundary_status"] = boundary.get("status")
        result["boundary_gate"] = boundary.get("action_gate")
        return result


def run_approval(contract: dict, vector: dict) -> dict:
    return _run_assertion(contract, vector, protected=False)


def run_protected_override(contract: dict, vector: dict) -> dict:
    return _run_assertion(contract, vector, protected=True)


def _project_markdown(project: dict) -> str:
    payload = json.dumps(project, ensure_ascii=False, indent=2)
    return (
        "# PROJECT.md conformance fixture\n\n"
        + policy_validate.PROJECT_START + "\n```json\n" + payload
        + "\n```\n" + policy_validate.PROJECT_END + "\n"
    )


def run_readiness(contract: dict, vector: dict) -> dict:
    data = copy.deepcopy(vector["input"])
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for rel, content in data.get("files", {}).items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(content), encoding="utf-8")
        project_path = root / "PROJECT.md"
        project_path.write_text(_project_markdown(data["project"]), encoding="utf-8")
        return policy_validate.readiness(
            project_path,
            data.get("mode", "development"),
            project_root=root,
            reference_time=_reference_time(data.get("reference_time")),
        )


def _zip_entry(zf: zipfile.ZipFile, entry: dict) -> None:
    name = entry["name"]
    entry_type = entry.get("type", "file")
    data = entry.get("data", "")
    if isinstance(data, str):
        raw = data.encode("utf-8")
    else:
        raw = bytes(data)
    if "repeat_byte" in entry:
        raw = str(entry["repeat_byte"]).encode("utf-8")[:1] * int(entry.get("size", 0))
    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    if entry_type == "symlink":
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
    else:
        info.external_attr = (stat.S_IFREG | 0o644) << 16
    info.compress_type = zipfile.ZIP_STORED
    zf.writestr(info, raw)


def run_distribution(contract: dict, vector: dict) -> dict:
    data = vector["input"]
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "fixture.zip"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
            for entry in data["entries"]:
                _zip_entry(zf, entry)
        result = policy_validate.validate_distribution(path, contract)
        return {
            "status": result["status"],
            "has_unsafe_entries": bool(result["unsafe_entries"]),
            "has_duplicate_entries": bool(result["duplicate_entries"]),
            "has_name_collisions": bool(result["name_collisions"]),
            "has_symlinks": bool(result["symlinks"]),
            "has_resource_limit_violations": bool(result["resource_limit_violations"]),
            "has_outside_root": bool(result["outside_root"]),
        }


def _load_packager():
    spec = importlib.util.spec_from_file_location("uad_conformance_package", SCRIPT_DIR / "package.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_integrity(contract: dict, vector: dict) -> dict:
    data = vector["input"]
    scenario = data["scenario"]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        if scenario.startswith("trust_"):
            manifest = policy_validate.build_trust_manifest(ROOT)
            if scenario == "trust_manifest_tamper":
                rel = manifest["files"].keys().__iter__().__next__()
                manifest["files"][rel] = "0" * 64
            path = root / "trust.json"
            _write_json(path, manifest)
            result = policy_validate.verify_trust_manifest(path, ROOT)
            return {"status": result["status"], "error_count": len(result["errors"])}

        packager = _load_packager()
        packaged = packager.package(root)
        artifact = Path(packaged["zip"])
        manifest_path = Path(packaged["release_manifest"])
        if scenario == "release_manifest_valid":
            result = policy_validate.verify_release_manifest(manifest_path, artifact, contract)
        elif scenario == "release_manifest_artifact_hash_tamper":
            manifest = load_json(manifest_path)
            manifest["artifact"]["sha256"] = "0" * 64
            bad = root / "bad.release.json"
            _write_json(bad, manifest)
            result = policy_validate.verify_release_manifest(bad, artifact, contract)
        else:
            raise ValueError(f"unsupported integrity scenario: {scenario}")
        return {"status": result["status"], "error_count": len(result["errors"])}


RUNNERS = {
    "routing": run_routing,
    "execution_boundary": run_execution_boundary,
    "digest_relation": run_digest_relation,
    "catalog_invariant": run_catalog_invariant,
    "approval": run_approval,
    "protected_override": run_protected_override,
    "readiness": run_readiness,
    "distribution": run_distribution,
    "integrity": run_integrity,
}


def load_corpora(paths: list[Path]) -> list[dict]:
    corpora = [load_json(path) for path in paths]
    if jsonschema is not None:
        schema = load_json(ROOT / "conformance" / "corpus.schema.json")
        for corpus in corpora:
            jsonschema.validate(corpus, schema)
    return corpora


def run_suite(paths: list[Path] | None = None) -> dict:
    paths = paths or DEFAULT_CORPORA
    corpora = load_corpora(paths)
    contract = policy_validate.load_json(ROOT / "POLICY_CONTRACT.json")
    vectors = [vector for corpus in corpora for vector in corpus["vectors"]]
    seen: set[str] = set()
    results = []
    for vector in vectors:
        if vector["id"] in seen:
            raise ValueError(f"duplicate conformance vector id: {vector['id']}")
        seen.add(vector["id"])
        actual = RUNNERS[vector["kind"]](contract, vector)
        mismatches = compare_normative(actual, vector["expected"], vector["normative_fields"])
        results.append({
            "id": vector["id"],
            "status": "PASS" if not mismatches else "FAIL",
            "actual": actual,
            "mismatches": mismatches,
        })

    failed = sum(1 for item in results if item["status"] == "FAIL")
    result = {
        "format": RESULT_FORMAT,
        "suite_schema_version": SUITE_SCHEMA_VERSION,
        "policy_schema_version": contract["schema_version"],
        "implementation": {
            "name": "universal-agent-docs-python-reference",
            "version": str(contract["schema_version"]),
            "language": "python",
        },
        "summary": {
            "total": len(results),
            "passed": len(results) - failed,
            "failed": failed,
        },
        "results": results,
    }
    if jsonschema is not None:
        jsonschema.validate(result, load_json(ROOT / "conformance" / "result.schema.json"))
    return result


def coverage_summary(paths: list[Path] | None = None) -> dict:
    corpora = load_corpora(paths or DEFAULT_CORPORA)
    vectors = [v for c in corpora for v in c["vectors"]]
    return {
        "total": len(vectors),
        "categories": dict(sorted(Counter(v["category"] for v in vectors).items())),
        "kinds": dict(sorted(Counter(v["kind"] for v in vectors).items())),
        "covers": sorted({item for v in vectors for item in v["covers"]}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the language-neutral universal-agent-docs conformance corpus")
    parser.add_argument("--corpus", action="append", type=Path, default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--jsonl", action="store_true", help="emit one result object per vector instead of the aggregate result")
    parser.add_argument("--coverage", action="store_true", help="print corpus coverage metadata and exit")
    args = parser.parse_args()
    paths = [p.resolve() for p in args.corpus] or DEFAULT_CORPORA
    if args.coverage:
        print(json.dumps(coverage_summary(paths), ensure_ascii=False, indent=2))
        return 0
    result = run_suite(paths)
    if args.jsonl:
        for item in result["results"]:
            print(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
    else:
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
    return 0 if result["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
