#!/usr/bin/env python3
"""Profile C integration sketch with no external side effects."""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import validate as policy_validate  # noqa: E402


def build_approval(boundary: dict, now: datetime) -> dict:
    return {
        "schema_version": 2,
        "approval": {
            "approval_id": "mock-approval-001",
            "issuer": "mock-higher-authority",
            "decision": "APPROVE",
            "scope": "send one mock notification",
            "issued_at": (now - timedelta(minutes=1)).isoformat(),
            "expires_at": (now + timedelta(minutes=10)).isoformat(),
            "operations": list(boundary["actual_operations"]),
            "targets": list(boundary["targets"]),
            "environment": boundary["environment"],
            "correlation_id": boundary["correlation_id"],
            "execution_nonce": boundary["execution_nonce"],
            "single_use": True,
            "action_digest": boundary["action_digest"],
            "authorization_reference": "mock-authority/demo-approval",
        },
    }


def run_demo() -> dict:
    contract = policy_validate.load_json(ROOT / "POLICY_CONTRACT.json")
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    boundary = policy_validate.evaluate_execution_boundary(
        contract,
        ["external.message_send"],
        ["external.message_send"],
        [],
        ["recipient:user@example.invalid"],
        "external",
        "X0",
        None,
        "send mock notification",
        exposure_facts={
            "data_classification": "public",
            "credential_class": "none",
            "tenant_scope": "single_user",
            "public_visibility": "public_destination",
            "estimated_blast_radius": "single_resource",
            "estimated_financial_impact": "none",
        },
        correlation_id="mock-profile-c-action-001",
        execution_nonce="mock-execution-nonce-000001",
        adapter={
            "id": "mock-message-adapter",
            "surface": "mock-external-message",
            "assertion_source": "tool_adapter",
            "version": "1",
        },
        semantic_details={"message_type": "notification"},
    )
    if boundary["status"] != "PASS":
        raise RuntimeError(f"unexpected boundary failure: {boundary}")

    # Explicit stand-ins for controls outside the reference validator.
    issuer_authenticated = True
    transport_authenticated = True
    executions: list[str] = []

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        assertion = root / "approval.json"
        ledger = root / "approval-ledger.sqlite"
        assertion.write_text(
            json.dumps(build_approval(boundary, now), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        first = policy_validate.validate_approval_assertion(
            assertion,
            contract,
            boundary,
            replay_registry=ledger,
            consume=True,
            reference_time=now,
        )
        if (
            issuer_authenticated
            and transport_authenticated
            and first["object_validity"] == "VALID"
            and first["binding"] == "VALID"
            and first["replay_protection"] == "CONSUMED"
        ):
            executions.append("mock execution")

        replay = policy_validate.validate_approval_assertion(
            assertion,
            contract,
            boundary,
            replay_registry=ledger,
            consume=True,
            reference_time=now,
        )
        if (
            issuer_authenticated
            and transport_authenticated
            and replay["object_validity"] == "VALID"
            and replay["binding"] == "VALID"
            and replay["replay_protection"] == "CONSUMED"
        ):
            executions.append("unexpected replay execution")

    return {
        "boundary": {
            "status": boundary["status"],
            "effective_effect": boundary["effective_effect"],
            "effective_exposure": boundary["effective_exposure"],
            "action_gate": boundary["action_gate"],
            "action_digest": boundary["action_digest"],
        },
        "first_consumption": {
            "object_validity": first["object_validity"],
            "binding": first["binding"],
            "replay_protection": first["replay_protection"],
            "validator_authority": first["authority"],
            "validator_authorization": first["authorization"],
        },
        "replay_attempt": {
            "object_validity": replay["object_validity"],
            "binding": replay["binding"],
            "replay_protection": replay["replay_protection"],
        },
        "mock_execution_count": len(executions),
    }


def main() -> int:
    result = run_demo()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    ok = (
        result["boundary"]["action_gate"] == "REQUIRE_EXPLICIT_APPROVAL"
        and result["first_consumption"]["replay_protection"] == "CONSUMED"
        and result["replay_attempt"]["replay_protection"] == "REPLAY_DETECTED"
        and result["mock_execution_count"] == 1
        and result["first_consumption"]["validator_authorization"] == "NOT_ESTABLISHED"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
