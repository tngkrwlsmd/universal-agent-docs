#!/usr/bin/env python3
"""Profile C reference adapter that performs a real write only inside a caller-provided sandbox."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import validate as policy_validate  # noqa: E402

EXTENSION_PATH = ROOT / "examples" / "extensions" / "internal-sandbox-artifact.json"
ADAPTER = {
    "id": "reference-sandbox-artifact-adapter",
    "surface": "local-sandbox-artifact-publish",
    "assertion_source": "tool_adapter",
    "version": "1",
}
ACTUAL_OPERATION = "internal.sandbox_artifact_publish"


def exposure_facts() -> dict:
    return {
        "data_classification": "public",
        "credential_class": "none",
        "tenant_scope": "single_user",
        "public_visibility": "none",
        "estimated_blast_radius": "single_resource",
        "estimated_financial_impact": "none",
    }


def evaluate_publish(
    contract: dict,
    extension_registry: dict,
    planned_operations: list[str],
    source: Path,
    destination: Path,
    *,
    environment: str = "test",
    correlation_id: str = "reference-sandbox-publish",
    execution_nonce: str = "reference-sandbox-publish-nonce-0001",
) -> dict:
    """Map the fixed adapter surface to an independently observed actual operation."""
    return policy_validate.evaluate_execution_boundary(
        contract,
        planned_operations,
        [ACTUAL_OPERATION],
        [str(source)],
        [f"sandbox:{destination}"],
        environment,
        exposure_facts=exposure_facts(),
        correlation_id=correlation_id,
        execution_nonce=execution_nonce,
        adapter=ADAPTER,
        semantic_details={"artifact_kind": "reference_fixture"},
        extension_registry=extension_registry,
    )


def build_approval(boundary: dict, now: datetime, *, expires_delta: timedelta = timedelta(minutes=10)) -> dict:
    return {
        "schema_version": 2,
        "approval": {
            "approval_id": "reference-sandbox-approval",
            "issuer": "reference-higher-authority",
            "decision": "APPROVE",
            "scope": "publish one fixture into the local sandbox",
            "issued_at": (now - timedelta(minutes=1)).isoformat(),
            "expires_at": (now + expires_delta).isoformat(),
            "operations": list(boundary["actual_operations"]),
            "targets": list(boundary["targets"]),
            "environment": boundary["environment"],
            "correlation_id": boundary["correlation_id"],
            "execution_nonce": boundary["execution_nonce"],
            "single_use": True,
            "action_digest": boundary["action_digest"],
            "authorization_reference": "reference:local-sandbox",
        },
    }


def execute_publish(
    source: Path,
    destination: Path,
    boundary: dict,
    approval_path: Path | None,
    ledger: Path,
    *,
    contract: dict,
    reference_time: datetime,
    higher_authority_authenticated: bool,
    transport_authenticated: bool,
) -> dict:
    """Final dispatcher: copy only after exact approval binding and atomic consumption."""
    audit = {
        "decision": "BLOCKED",
        "executed": False,
        "target": str(destination),
        "action_digest": boundary.get("action_digest"),
    }
    if boundary.get("status") != "PASS":
        audit["reason"] = "POLICY_BOUNDARY_FAILED"
        return audit
    if boundary.get("action_gate") != "REQUIRE_EXPLICIT_APPROVAL":
        audit["reason"] = "REFERENCE_ADAPTER_EXPECTS_EXPLICIT_APPROVAL_GATE"
        return audit
    if approval_path is None:
        audit["reason"] = "APPROVAL_REQUIRED"
        return audit
    if not higher_authority_authenticated or not transport_authenticated:
        audit["reason"] = "HIGHER_AUTHORITY_OR_TRANSPORT_UNVERIFIED"
        return audit

    approval = policy_validate.validate_approval_assertion(
        approval_path,
        contract,
        boundary,
        replay_registry=ledger,
        consume=True,
        reference_time=reference_time,
    )
    audit["approval"] = {
        "object_validity": approval["object_validity"],
        "binding": approval["binding"],
        "replay_protection": approval["replay_protection"],
        "validator_authorization": approval["authorization"],
    }
    if not (
        approval["object_validity"] == "VALID"
        and approval["binding"] == "VALID"
        and approval["replay_protection"] == "CONSUMED"
    ):
        audit["reason"] = "APPROVAL_NOT_CONSUMABLE"
        return audit

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    audit.update({
        "decision": "EXECUTED",
        "executed": True,
        "reason": "APPROVAL_BOUND_AND_CONSUMED",
        "output_sha256": digest,
    })
    return audit


def run_demo() -> dict:
    contract = policy_validate.load_json(ROOT / "POLICY_CONTRACT.json")
    extensions = policy_validate.load_operation_extensions([EXTENSION_PATH], contract)
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as td:
        sandbox = Path(td)
        source = sandbox / "source.txt"
        destination = sandbox / "published" / "artifact.txt"
        approval_path = sandbox / "approval.json"
        ledger = sandbox / "approval.sqlite3"
        source.write_text("reference artifact\n", encoding="utf-8")

        boundary = evaluate_publish(
            contract, extensions, [ACTUAL_OPERATION], source, destination
        )
        approval_path.write_text(
            json.dumps(build_approval(boundary, now), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        first = execute_publish(
            source, destination, boundary, approval_path, ledger,
            contract=contract,
            reference_time=now,
            higher_authority_authenticated=True,
            transport_authenticated=True,
        )
        replay = execute_publish(
            source, destination, boundary, approval_path, ledger,
            contract=contract,
            reference_time=now,
            higher_authority_authenticated=True,
            transport_authenticated=True,
        )
        return {
            "boundary_status": boundary["status"],
            "action_gate": boundary["action_gate"],
            "extension_digest": boundary["semantic_details"].get(
                policy_validate.OPERATION_EXTENSION_DIGEST_KEY
            ),
            "first": first,
            "replay": replay,
            "destination_exists": destination.is_file(),
        }


def main() -> int:
    result = run_demo()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if (
        result["boundary_status"] == "PASS"
        and result["action_gate"] == "REQUIRE_EXPLICIT_APPROVAL"
        and result["first"]["executed"] is True
        and result["replay"]["executed"] is False
        and result["destination_exists"] is True
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
