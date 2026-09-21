#!/usr/bin/env python3
"""Production-shaped Profile C reference adapter for a GitHub issue-create surface.

The adapter intentionally uses a deterministic in-memory transport by default.  The
security-relevant part is the boundary: independently observe the imminent request,
recompute policy state immediately before dispatch, validate exact approval binding,
atomically consume replay state, and only then invoke the transport.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import validate as policy_validate  # noqa: E402

ACTUAL_OPERATION = "external.api_write"
ADAPTER = {
    "id": "reference-github-issue-adapter",
    "surface": "github.issue.create",
    "assertion_source": "tool_adapter",
    "version": "1",
}


@dataclass(frozen=True)
class GitHubIssueRequest:
    repository: str
    title: str
    body: str = ""


class GitHubIssueTransport(Protocol):
    def create_issue(self, request: GitHubIssueRequest) -> dict: ...


class RecordingGitHubTransport:
    """Deterministic test double; no network call is performed."""

    def __init__(self) -> None:
        self.calls: list[GitHubIssueRequest] = []

    def create_issue(self, request: GitHubIssueRequest) -> dict:
        self.calls.append(request)
        return {
            "number": len(self.calls),
            "repository": request.repository,
            "url": f"https://github.invalid/{request.repository}/issues/{len(self.calls)}",
        }


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def demo_exposure_facts() -> dict:
    """Low-risk fixture used only by the local demo/tests; not a production default."""
    return {
        "data_classification": "public",
        "credential_class": "none",
        "tenant_scope": "single_user",
        "public_visibility": "none",
        "estimated_blast_radius": "single_resource",
        "estimated_financial_impact": "none",
    }


def unknown_exposure_facts() -> dict:
    """Conservative explicit unknown facts for callers that genuinely lack context."""
    return {
        "data_classification": "unknown",
        "credential_class": "unknown",
        "tenant_scope": "unknown",
        "public_visibility": "unknown",
        "estimated_blast_radius": "unknown",
        "estimated_financial_impact": "unknown",
    }


def _target(request: GitHubIssueRequest) -> str:
    repo = request.repository.strip().strip("/")
    if not repo or repo.count("/") != 1:
        raise ValueError("repository must be a concrete owner/name target")
    return f"github:{repo}/issues"


def evaluate_issue_create(
    contract: dict,
    planned_operations: list[str],
    request: GitHubIssueRequest,
    *,
    correlation_id: str,
    execution_nonce: str,
    exposure_facts: dict | None = None,
) -> dict:
    """Independently map the fixed adapter surface to canonical runtime semantics."""
    target = _target(request)
    if exposure_facts is None:
        raise ValueError("exposure_facts must be explicitly supplied by the execution surface")
    facts = exposure_facts
    return policy_validate.evaluate_execution_boundary(
        contract,
        planned_operations,
        [ACTUAL_OPERATION],
        [],
        [target],
        "external",
        exposure_facts=facts,
        correlation_id=correlation_id,
        execution_nonce=execution_nonce,
        actual_action="github.issue.create",
        adapter=ADAPTER,
        semantic_details={
            "github_action": "issue.create",
            "repository": request.repository,
            "title_digest": _sha256_text(request.title),
            "body_digest": _sha256_text(request.body),
        },
    )


def build_approval(
    boundary: dict,
    now: datetime,
    *,
    approval_id: str = "reference-github-approval",
    expires_delta: timedelta = timedelta(minutes=10),
) -> dict:
    return {
        "schema_version": 2,
        "approval": {
            "approval_id": approval_id,
            "issuer": "reference-higher-authority",
            "decision": "APPROVE",
            "scope": "create one issue in the bound GitHub repository",
            "issued_at": (now - timedelta(minutes=1)).isoformat(),
            "expires_at": (now + expires_delta).isoformat(),
            "operations": list(boundary["actual_operations"]),
            "targets": list(boundary["targets"]),
            "environment": boundary["environment"],
            "correlation_id": boundary["correlation_id"],
            "execution_nonce": boundary["execution_nonce"],
            "single_use": True,
            "action_digest": boundary["action_digest"],
            "authorization_reference": "reference:github-issue-workflow",
        },
    }


def dispatch_issue_create(
    request: GitHubIssueRequest,
    planned_operations: list[str],
    approval_path: Path | None,
    ledger: Path,
    transport: GitHubIssueTransport,
    *,
    contract: dict,
    reference_time: datetime,
    correlation_id: str,
    execution_nonce: str,
    higher_authority_authenticated: bool,
    transport_authenticated: bool,
    exposure_facts: dict | None = None,
) -> dict:
    """Final dispatcher with execution-time re-observation and exact binding.

    The caller does not pass a previously evaluated boundary.  The dispatcher derives
    it again from the imminent request, so target/title/body mutation after approval
    changes the action digest and invalidates the old approval.
    """
    try:
        boundary = evaluate_issue_create(
            contract,
            planned_operations,
            request,
            correlation_id=correlation_id,
            execution_nonce=execution_nonce,
            exposure_facts=exposure_facts,
        )
    except Exception as exc:
        return {"decision": "BLOCKED", "executed": False, "reason": "OBSERVATION_FAILED", "error": str(exc)}

    audit = {
        "decision": "BLOCKED",
        "executed": False,
        "target": boundary.get("targets", [None])[0],
        "action_digest": boundary.get("action_digest"),
        "boundary_status": boundary.get("status"),
        "boundary_errors": boundary.get("errors", []),
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

    response = transport.create_issue(request)
    audit.update({
        "decision": "EXECUTED",
        "executed": True,
        "reason": "APPROVAL_BOUND_AND_CONSUMED",
        "response": response,
    })
    return audit


def run_demo() -> dict:
    contract = policy_validate.load_json(ROOT / "POLICY_CONTRACT.json")
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    request = GitHubIssueRequest("example/project", "Reference adapter smoke test", "No network is used.")
    correlation_id = "reference-github-issue"
    execution_nonce = "reference-github-issue-nonce-0001"
    boundary = evaluate_issue_create(
        contract,
        [ACTUAL_OPERATION],
        request,
        correlation_id=correlation_id,
        execution_nonce=execution_nonce,
        exposure_facts=demo_exposure_facts(),
    )
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        approval_path = root / "approval.json"
        ledger = root / "approval.sqlite3"
        approval_path.write_text(json.dumps(build_approval(boundary, now), indent=2), encoding="utf-8")
        transport = RecordingGitHubTransport()
        first = dispatch_issue_create(
            request, [ACTUAL_OPERATION], approval_path, ledger, transport,
            contract=contract, reference_time=now, correlation_id=correlation_id,
            execution_nonce=execution_nonce, higher_authority_authenticated=True,
            transport_authenticated=True, exposure_facts=demo_exposure_facts(),
        )
        replay = dispatch_issue_create(
            request, [ACTUAL_OPERATION], approval_path, ledger, transport,
            contract=contract, reference_time=now, correlation_id=correlation_id,
            execution_nonce=execution_nonce, higher_authority_authenticated=True,
            transport_authenticated=True, exposure_facts=demo_exposure_facts(),
        )
        return {
            "boundary_status": boundary["status"],
            "action_gate": boundary["action_gate"],
            "first": first,
            "replay": replay,
            "transport_calls": len(transport.calls),
        }


def main() -> int:
    result = run_demo()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if (
        result["boundary_status"] == "PASS"
        and result["action_gate"] == "REQUIRE_EXPLICIT_APPROVAL"
        and result["first"]["executed"] is True
        and result["replay"]["executed"] is False
        and result["transport_calls"] == 1
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
