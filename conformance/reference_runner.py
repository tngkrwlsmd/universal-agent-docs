#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import shutil
import stat
import sys
import tempfile
import warnings
import zipfile
from datetime import datetime
from pathlib import Path

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from validation.approval import validate_approval_assertion  # noqa: E402
from validation.contract import PROJECT_END, PROJECT_START, load_json  # noqa: E402
from validation.distribution import validate_distribution  # noqa: E402
from validation.integrity import (  # noqa: E402
    verify_release_manifest,
    verify_trust_manifest,
    write_release_manifest,
    write_trust_manifest,
)
from validation.override import validate_protected_override  # noqa: E402
from validation.readiness import readiness  # noqa: E402
from validation.routing import operation_catalog, route_policies  # noqa: E402
from validation.runtime import compute_action_digest, evaluate_execution_boundary  # noqa: E402


SUITE = ROOT / "conformance" / "suite.json"
SUITE_SCHEMA = ROOT / "conformance" / "schema.json"
RESULT_SCHEMA = ROOT / "conformance" / "result.schema.json"
CONTRACT = ROOT / "POLICY_CONTRACT.json"

ADAPTER = {
    "id": "conformance-reference",
    "surface": "language-neutral-conformance",
    "assertion_source": "human_reviewed",
    "version": "2",
}
X0 = {
    "data_classification": "public",
    "credential_class": "none",
    "tenant_scope": "single_user",
    "public_visibility": "none",
    "estimated_blast_radius": "single_resource",
    "estimated_financial_impact": "none",
}
X3 = {
    "data_classification": "regulated",
    "credential_class": "privileged_credential",
    "tenant_scope": "organization_wide",
    "public_visibility": "none",
    "estimated_blast_radius": "organization",
    "estimated_financial_impact": "material",
}


def _reference_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _boundary(contract: dict, vector_id: str, data: dict) -> dict:
    return evaluate_execution_boundary(
        contract,
        data.get("planned_operations", []),
        data.get("actual_operations", []),
        data.get("affected_resources", []),
        data.get("targets", []),
        data.get("environment", ""),
        data.get("declared_exposure"),
        data.get("runtime_effect"),
        data.get("actual_action", ""),
        exposure_facts=data.get("exposure_facts"),
        correlation_id=data.get("correlation_id", f"conformance-{vector_id}"),
        execution_nonce=data.get("execution_nonce", f"nonce-{vector_id}-00000001"),
        adapter=ADAPTER,
        semantic_details=data.get("semantic_details", {}),
    )


def _digest_payload(contract: dict, semantic_details: dict, exposure_facts: dict, nonce: str) -> dict:
    return {
        "policy_schema_version": contract["schema_version"],
        "policy_contract_digest": __import__(
            "validation.contract", fromlist=["canonical_policy_contract_digest"]
        ).canonical_policy_contract_digest(contract),
        "adapter": ADAPTER,
        "correlation_id": "conformance-digest",
        "execution_nonce": nonce,
        "planned_operations": ["filesystem.tracked_delete"],
        "actual_operations": ["filesystem.tracked_delete"],
        "affected_resources": ["src/old.py"],
        "targets": [],
        "environment": "local",
        "exposure_facts": exposure_facts,
        "declared_exposure": None,
        "runtime_effect": None,
        "actual_action": "remove tracked file",
        "semantic_details": semantic_details,
    }


def _approval_boundary(contract: dict) -> dict:
    return _boundary(contract, "approval", {
        "planned_operations": ["database.write"],
        "actual_operations": ["database.write"],
        "actual_action": "update test user",
        "affected_resources": ["users"],
        "targets": ["db/test/users"],
        "environment": "test",
        "exposure_facts": X0,
        "correlation_id": "approval-action",
        "execution_nonce": "approval-nonce-000001",
    })


def _approval_payload(boundary: dict) -> dict:
    return {
        "schema_version": 2,
        "approval": {
            "approval_id": "approval-1",
            "issuer": "conformance-authority",
            "decision": "APPROVE",
            "scope": "exact conformance action",
            "issued_at": "2030-01-01T00:00:00Z",
            "expires_at": "2030-01-01T00:20:00Z",
            "operations": list(boundary["actual_operations"]),
            "targets": list(boundary["targets"]),
            "environment": boundary["environment"],
            "correlation_id": boundary["correlation_id"],
            "execution_nonce": boundary["execution_nonce"],
            "single_use": True,
            "action_digest": boundary["action_digest"],
            "authorization_reference": "conformance://approval/1",
        },
    }


def _override_boundary(contract: dict) -> dict:
    return _boundary(contract, "override", {
        "planned_operations": ["build.execute"],
        "actual_operations": ["build.execute"],
        "actual_action": "build with privileged material",
        "affected_resources": ["src"],
        "targets": ["workspace/build"],
        "environment": "local",
        "exposure_facts": X3,
        "correlation_id": "override-action",
        "execution_nonce": "override-nonce-000001",
    })


def _override_payload(boundary: dict) -> dict:
    return {
        "schema_version": 1,
        "override_id": "override-1",
        "issuer": "conformance-higher-authority",
        "issued_at": "2030-01-01T00:00:00Z",
        "expires_at": "2030-01-01T00:12:00Z",
        "scope": "exact prohibited conformance action",
        "operations": list(boundary["actual_operations"]),
        "targets": list(boundary["targets"]),
        "environment": boundary["environment"],
        "correlation_id": boundary["correlation_id"],
        "execution_nonce": boundary["execution_nonce"],
        "action_digest": boundary["action_digest"],
        "single_use": True,
        "authorization_reference": "conformance://override/1",
    }


def _write_project(root: Path, data: dict) -> Path:
    content = (
        "# PROJECT.md\n\n"
        + PROJECT_START
        + "\n```json\n"
        + json.dumps(data, ensure_ascii=False, indent=2)
        + "\n```\n"
        + PROJECT_END
        + "\n"
    )
    path = root / "PROJECT.md"
    path.write_text(content, encoding="utf-8")
    return path


def _project_data() -> dict:
    return {
        "profile": "project",
        "facts": {
            "repository_root": {"value": ".", "status": "Confirmed", "evidence": "path:."},
            "primary_source": {"value": "src", "status": "Confirmed", "evidence": "path:src"},
            "build_command": {"value": "python -m build", "status": "Confirmed", "evidence": "manual:checked project tooling"},
            "test_command": {"value": "python -m unittest", "status": "Confirmed", "evidence": "manual:checked project tooling"},
            "runtime": {"value": "Python", "status": "Confirmed", "evidence": "manual:checked runtime"},
            "deploy_command": {"value": "", "status": "Unknown", "evidence": ""},
            "deploy_target": {"value": "", "status": "Unknown", "evidence": ""},
        },
        "components": [{"name": "core", "path": "src", "responsibility": "core"}],
        "review": {"reviewed_revision": "manual-revision", "reviewed_at": "2026-09-19"},
    }


def _write_valid_zip(path: Path, contract: dict, mutation: str) -> None:
    required = contract["distribution"]["required_files"]
    canonical_root = contract["distribution"]["canonical_root"]
    limit = contract["distribution"]["max_file_uncompressed_bytes"]
    with zipfile.ZipFile(path, "w") as zf:
        for rel in required:
            data = (ROOT / rel).read_bytes()
            if mutation == "file_size_limit" and rel == "AGENTS.md":
                data = b"x" * (limit + 1)
            zf.writestr(f"{canonical_root}/{rel}", data)
        if mutation == "path_traversal":
            zf.writestr("../outside.txt", b"x")
        elif mutation == "casefold_collision":
            zf.writestr(f"{canonical_root}/readme.md", b"x")
        elif mutation == "unicode_collision":
            zf.writestr(f"{canonical_root}/caf\u00e9.txt", b"x")
            zf.writestr(f"{canonical_root}/cafe\u0301.txt", b"x")
        elif mutation == "symlink":
            info = zipfile.ZipInfo(f"{canonical_root}/link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "AGENTS.md")
    if mutation == "duplicate":
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(path, "a") as zf:
                zf.writestr(f"{canonical_root}/AGENTS.md", "duplicate")


def evaluate_case(case: dict, contract: dict) -> dict:
    kind = case["kind"]
    data = case["input"]

    if kind == "execution_boundary":
        return _boundary(contract, case["id"], data)

    if kind == "routing":
        return route_policies(
            contract,
            data.get("task_text", ""),
            data.get("planned_operations", []),
            data.get("resources", []),
            data.get("routing_mode", "advisory"),
        )

    if kind == "lifecycle":
        item = operation_catalog(contract).get(data["operation"])
        return {"known": item is not None, "lifecycle_status": item.get("lifecycle_status") if item else None}

    if kind == "digest_relation":
        left_facts = dict(X0)
        right_facts = dict(reversed(list(X0.items())))
        left_semantics = {"recoverability": "git_tracked_clean", "recovery_revision": "abc123"}
        right_semantics = dict(reversed(list(left_semantics.items())))
        if data["variant"] == "semantic_details":
            right_semantics["recovery_revision"] = "def456"
        left = compute_action_digest(**_digest_payload(contract, left_semantics, left_facts, "digest-nonce-000001"))
        right = compute_action_digest(**_digest_payload(contract, right_semantics, right_facts, "digest-nonce-000001"))
        return {"relation": "equal" if left == right else "not_equal"}

    if kind == "approval":
        boundary = _approval_boundary(contract)
        payload = _approval_payload(boundary)
        mutation = data["mutation"]
        if mutation == "expired":
            payload["approval"]["issued_at"] = "2029-12-31T23:00:00Z"
            payload["approval"]["expires_at"] = "2029-12-31T23:20:00Z"
        elif mutation == "target":
            payload["approval"]["targets"] = ["db/test/other"]
        elif mutation == "environment":
            payload["approval"]["environment"] = "staging"
        elif mutation == "correlation_id":
            payload["approval"]["correlation_id"] = "other-action"
        elif mutation == "execution_nonce":
            payload["approval"]["execution_nonce"] = "other-approval-nonce-0001"
        reference_time = _reference_time(data["reference_time"])
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assertion = root / "approval.json"
            assertion.write_text(json.dumps(payload), encoding="utf-8")
            if mutation == "replay":
                ledger = root / "ledger.sqlite"
                first = validate_approval_assertion(assertion, contract, boundary, replay_registry=ledger, consume=True, reference_time=reference_time)
                second = validate_approval_assertion(assertion, contract, boundary, replay_registry=ledger, consume=True, reference_time=reference_time)
                return {
                    "first_replay_protection": first["replay_protection"],
                    "second_replay_protection": second["replay_protection"],
                    "second_object_validity": second["object_validity"],
                }
            return validate_approval_assertion(assertion, contract, boundary, reference_time=reference_time)

    if kind == "override":
        boundary = _override_boundary(contract)
        payload = _override_payload(boundary)
        mutation = data["mutation"]
        if mutation == "action_digest":
            payload["action_digest"] = "sha256:" + "0" * 64
        reference_time = _reference_time(data["reference_time"])
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assertion = root / "override.json"
            assertion.write_text(json.dumps(payload), encoding="utf-8")
            if mutation == "replay":
                ledger = root / "ledger.sqlite"
                first = validate_protected_override(assertion, contract, boundary, replay_registry=ledger, consume=True, reference_time=reference_time)
                second = validate_protected_override(assertion, contract, boundary, replay_registry=ledger, consume=True, reference_time=reference_time)
                return {
                    "first_replay_protection": first["replay_protection"],
                    "second_replay_protection": second["replay_protection"],
                    "second_object_validity": second["object_validity"],
                }
            return validate_protected_override(assertion, contract, boundary, reference_time=reference_time)

    if kind == "readiness":
        scenario = data["scenario"]
        if scenario == "template":
            return readiness(ROOT / "PROJECT.md", "development")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = _project_data()
            if scenario == "valid_source_manual_commands":
                (root / "src").mkdir()
            elif scenario == "missing_primary_source":
                project["facts"]["primary_source"] = {
                    "value": "definitely-missing",
                    "status": "Confirmed",
                    "evidence": "path:definitely-missing",
                }
            path = _write_project(root, project)
            return readiness(path, "development")

    if kind == "distribution":
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "bundle.zip"
            _write_valid_zip(archive, contract, data["mutation"])
            result = validate_distribution(archive, contract)
            finding = next(
                (field for field in [
                    "unsafe_entries", "duplicate_entries", "name_collisions",
                    "symlinks", "resource_limit_violations"
                ] if result.get(field)),
                "",
            )
            return {"status": result["status"], "finding": finding}

    if kind == "integrity":
        scenario = data["scenario"]
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            if scenario.startswith("trust_"):
                bundle = temp / "bundle"
                for rel in contract["integrity"]["trusted_core_files"]:
                    target = bundle / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(ROOT / rel, target)
                manifest = temp / "trust.json"
                write_trust_manifest(manifest, bundle)
                if scenario == "trust_tamper":
                    (bundle / "AGENTS.md").write_text("tampered", encoding="utf-8")
                return verify_trust_manifest(manifest, bundle)
            archive = temp / "universal-agent-docs.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                for rel in contract["distribution"]["required_files"]:
                    zf.writestr(f"{contract['distribution']['canonical_root']}/{rel}", (ROOT / rel).read_bytes())
            manifest = temp / "release.json"
            write_release_manifest(manifest, archive, ROOT)
            with zipfile.ZipFile(archive, "a") as zf:
                zf.writestr("tamper-marker.txt", "tampered")
            return verify_release_manifest(manifest, archive, contract)

    raise ValueError(f"unsupported conformance kind: {kind}")


def _get_path(obj: dict, dotted: str):
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def run_suite(suite_path: Path = SUITE) -> dict:
    suite = load_json(suite_path)
    contract = load_json(CONTRACT)
    if jsonschema is not None:
        jsonschema.validate(suite, load_json(SUITE_SCHEMA))
    if suite["contract_schema_version"] != contract["schema_version"]:
        raise ValueError("suite contract_schema_version does not match POLICY_CONTRACT.json")

    results = []
    passed = 0
    for case in suite["cases"]:
        observed_full = evaluate_case(case, contract)
        observed = {field: _get_path(observed_full, field) for field in case["normative_fields"]}
        mismatches = [
            field for field in case["normative_fields"]
            if observed[field] != _get_path(case["expected"], field)
        ]
        status = "PASS" if not mismatches else "FAIL"
        passed += status == "PASS"
        results.append({
            "id": case["id"],
            "status": status,
            "observed": observed,
            "mismatches": mismatches,
        })

    result = {
        "conformance_version": suite["conformance_version"],
        "implementation": {"name": "python-reference-validator", "version": str(contract["schema_version"])},
        "summary": {"total": len(results), "passed": passed, "failed": len(results) - passed},
        "results": results,
    }
    if jsonschema is not None:
        jsonschema.validate(result, load_json(RESULT_SCHEMA))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the language-neutral universal-agent-docs conformance suite")
    parser.add_argument("--suite", type=Path, default=SUITE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true", help="print only the summary; exit non-zero on mismatch")
    args = parser.parse_args()

    result = run_suite(args.suite.resolve())
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.check:
        print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
