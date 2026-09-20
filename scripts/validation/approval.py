from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

try:
    import jsonschema
except ImportError:  # pragma: no cover - exercised by CLI environments without deps
    jsonschema = None

from .contract import APPROVAL_MAX_TTL_SECONDS, Check, ROOT, load_json
from .risk import _concrete_targets
from .routing import operation_catalog

def _parse_timestamp(value, field: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} must be a non-empty ISO-8601 string")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        errors.append(f"{field} must be ISO-8601")
        return None
    if parsed.tzinfo is None:
        errors.append(f"{field} must include timezone")
        return None
    return parsed.astimezone(timezone.utc)
def _approval_replay_state(registry: Path, approval_id: str, execution_nonce: str, action_digest: str, *, consume: bool) -> tuple[str, str | None]:
    """Check/atomically consume a single-use approval in a local SQLite registry.

    A production runtime may use another atomic store; this local implementation exists
    so the reference validator can prove first-use/second-use behavior.
    """
    registry.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(registry), timeout=10, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS approval_consumption (approval_id TEXT PRIMARY KEY, execution_nonce TEXT UNIQUE NOT NULL, action_digest TEXT NOT NULL, consumed_at TEXT NOT NULL)")
        row = conn.execute("SELECT execution_nonce, action_digest FROM approval_consumption WHERE approval_id=? OR execution_nonce=?", (approval_id, execution_nonce)).fetchone()
        if row is not None:
            return "REPLAY_DETECTED", "approval_id or execution_nonce has already been consumed"
        if not consume:
            return "UNUSED", None
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT 1 FROM approval_consumption WHERE approval_id=? OR execution_nonce=?", (approval_id, execution_nonce)).fetchone()
            if row is not None:
                conn.execute("ROLLBACK")
                return "REPLAY_DETECTED", "approval_id or execution_nonce has already been consumed"
            conn.execute(
                "INSERT INTO approval_consumption(approval_id, execution_nonce, action_digest, consumed_at) VALUES (?,?,?,?)",
                (approval_id, execution_nonce, action_digest, datetime.now(timezone.utc).isoformat()),
            )
            conn.execute("COMMIT")
            return "CONSUMED", None
        except sqlite3.IntegrityError:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass
            return "REPLAY_DETECTED", "approval_id or execution_nonce has already been consumed"
    finally:
        conn.close()
def validate_approval_assertion(
    path: Path,
    contract: dict,
    boundary: dict | None = None,
    root: Path = ROOT,
    replay_registry: Path | None = None,
    consume: bool = False,
    reference_time: datetime | None = None,
) -> dict:
    """Validate an explicit-approval object and, when supplied, bind it to one action.

    Local validation can prove schema/temporal/action binding. It deliberately cannot
    authenticate issuer identity or authority; that remains the responsibility of the
    higher-authority runtime/organization workflow.
    """
    cfg = contract.get("execution_boundary", {})
    schema_name = cfg.get("approval_assertion_schema", "APPROVAL_ASSERTION.schema.json")
    warnings = [
        "approval issuer identity/authority must be authenticated by a higher-authority runtime or organization workflow"
    ]
    if replay_registry is None:
        warnings.append("single-use replay status is unverified without an atomic approval consumption registry")
    errors: list[str] = []
    try:
        payload = load_json(path)
    except Exception as exc:
        return {
            "object_validity": "INVALID", "schema_status": "FAIL", "temporal": "NOT_CHECKED",
            "binding": "NOT_CHECKED", "authority": "UNVERIFIED", "authorization": "NOT_ESTABLISHED",
            "errors": [str(exc)], "warnings": warnings,
        }
    try:
        schema = load_json(root / schema_name)
    except Exception as exc:
        return {
            "object_validity": "INVALID", "schema_status": "FAIL", "temporal": "NOT_CHECKED",
            "binding": "NOT_CHECKED", "authority": "UNVERIFIED", "authorization": "NOT_ESTABLISHED",
            "errors": [f"approval assertion schema: {exc}"], "warnings": warnings,
        }
    if jsonschema is None:
        return {
            "object_validity": "INVALID", "schema_status": "FAIL", "temporal": "NOT_CHECKED",
            "binding": "NOT_CHECKED", "authority": "UNVERIFIED", "authorization": "NOT_ESTABLISHED",
            "errors": ["install dependencies: pip install -r requirements.txt"], "warnings": warnings,
        }
    try:
        jsonschema.validate(payload, schema)
    except Exception as exc:
        return {
            "object_validity": "INVALID", "schema_status": "FAIL", "temporal": "NOT_CHECKED",
            "binding": "NOT_CHECKED", "authority": "UNVERIFIED", "authorization": "NOT_ESTABLISHED",
            "errors": [str(exc)], "warnings": warnings,
        }

    approval = payload["approval"]
    catalog = operation_catalog(contract)
    unknown_ops = sorted(set(approval["operations"]) - set(catalog))
    if unknown_ops:
        errors.append("approval operations must use canonical operation IDs; unknown: " + ", ".join(unknown_ops))
    concrete_targets, target_errors = _concrete_targets(approval["targets"])
    errors.extend(target_errors)
    if len(concrete_targets) != len(approval["targets"]):
        errors.append("approval targets must be unique concrete targets")

    issued_errors: list[str] = []
    issued = _parse_timestamp(approval.get("issued_at"), "issued_at", issued_errors)
    expires = _parse_timestamp(approval.get("expires_at"), "expires_at", issued_errors)
    now = reference_time or datetime.now(timezone.utc)
    if issued is not None and expires is not None:
        if issued >= expires:
            issued_errors.append("issued_at must be earlier than expires_at")
        if issued > now:
            issued_errors.append("issued_at must not be in the future")
        if expires <= now:
            issued_errors.append("approval is expired")
        max_ttl = int(cfg.get("approval_max_ttl_seconds", APPROVAL_MAX_TTL_SECONDS))
        if (expires - issued).total_seconds() > max_ttl:
            issued_errors.append(f"approval TTL exceeds maximum of {max_ttl} seconds")
    errors.extend(issued_errors)
    temporal = "VALID" if issued is not None and expires is not None and not issued_errors else "INVALID"

    binding = "NOT_CHECKED"
    binding_errors: list[str] = []
    if boundary is not None:
        binding = "VALID"
        if boundary.get("status") != "PASS":
            binding_errors.append("cannot bind approval to an invalid execution boundary")
        expected_digest = boundary.get("action_digest")
        if not expected_digest:
            binding_errors.append("execution boundary did not produce an action_digest")
        elif approval["action_digest"] != expected_digest:
            binding_errors.append("approval action_digest does not match the imminent action")
        if approval["correlation_id"] != boundary.get("correlation_id"):
            binding_errors.append("approval correlation_id does not match the imminent action")
        if approval["execution_nonce"] != boundary.get("execution_nonce"):
            binding_errors.append("approval execution_nonce does not match the imminent action")
        if set(approval["operations"]) != set(boundary.get("actual_operations", [])):
            binding_errors.append("approval operations do not exactly match runtime actual_operations")
        if set(approval["targets"]) != set(boundary.get("targets", [])):
            binding_errors.append("approval targets do not exactly match runtime targets")
        if approval["environment"] != boundary.get("environment"):
            binding_errors.append("approval environment does not match the imminent action")
        if boundary.get("action_gate") != cfg.get("approval_binding_required_for_gate", "REQUIRE_EXPLICIT_APPROVAL"):
            warnings.append(f"approval object was supplied for action_gate={boundary.get('action_gate')!r}")
        if binding_errors:
            binding = "INVALID"
            errors.extend(binding_errors)

    replay_protection = "UNVERIFIED"
    if consume and replay_registry is None:
        errors.append("consume=True requires replay_registry for atomic single-use enforcement")
        replay_protection = "INVALID"
    elif replay_registry is not None and not errors:
        replay_protection, replay_error = _approval_replay_state(
            replay_registry, approval["approval_id"], approval["execution_nonce"], approval["action_digest"], consume=consume
        )
        if replay_error:
            errors.append(replay_error)
            if binding == "VALID":
                binding = "INVALID"

    object_validity = "VALID" if not errors else "INVALID"
    return {
        "object_validity": object_validity,
        "schema_status": "PASS",
        "temporal": temporal,
        "binding": binding,
        "approval_id": approval.get("approval_id"),
        "correlation_id": approval.get("correlation_id"),
        "action_digest": approval.get("action_digest"),
        "execution_nonce": approval.get("execution_nonce"),
        "replay_protection": replay_protection,
        "authority": "UNVERIFIED",
        "authorization": "NOT_ESTABLISHED",
        "errors": errors,
        "warnings": warnings,
    }
