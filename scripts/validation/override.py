from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

try:
    import jsonschema
except ImportError:  # pragma: no cover - exercised by CLI environments without deps
    jsonschema = None

from .approval import _parse_timestamp
from .contract import PROTECTED_OVERRIDE_MAX_TTL_SECONDS, Check, ROOT, load_json
from .risk import _concrete_targets
from .routing import operation_catalog

def _override_replay_state(registry: Path, override_id: str, execution_nonce: str, action_digest: str, *, consume: bool) -> tuple[str, str | None]:
    """Check/atomically consume a single-use protected override in a local SQLite registry.

    This mirrors approval replay protection as a reference implementation. Production
    runtimes may use another atomic store, but first-use/second-use semantics must match.
    """
    registry.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(registry), timeout=10, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS override_consumption (override_id TEXT PRIMARY KEY, execution_nonce TEXT UNIQUE NOT NULL, action_digest TEXT NOT NULL, consumed_at TEXT NOT NULL)")
        row = conn.execute("SELECT execution_nonce, action_digest FROM override_consumption WHERE override_id=? OR execution_nonce=?", (override_id, execution_nonce)).fetchone()
        if row is not None:
            return "REPLAY_DETECTED", "override_id or execution_nonce has already been consumed"
        if not consume:
            return "UNUSED", None
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT 1 FROM override_consumption WHERE override_id=? OR execution_nonce=?", (override_id, execution_nonce)).fetchone()
            if row is not None:
                conn.execute("ROLLBACK")
                return "REPLAY_DETECTED", "override_id or execution_nonce has already been consumed"
            conn.execute(
                "INSERT INTO override_consumption(override_id, execution_nonce, action_digest, consumed_at) VALUES (?,?,?,?)",
                (override_id, execution_nonce, action_digest, datetime.now(timezone.utc).isoformat()),
            )
            conn.execute("COMMIT")
            return "CONSUMED", None
        except sqlite3.IntegrityError:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass
            return "REPLAY_DETECTED", "override_id or execution_nonce has already been consumed"
    finally:
        conn.close()
def validate_protected_override(
    path: Path,
    contract: dict,
    boundary: dict | None = None,
    root: Path = ROOT,
    replay_registry: Path | None = None,
    consume: bool = False,
) -> dict:
    """Validate a protected override and bind it to the exact prohibited action.

    This proves schema/time/action binding only. Issuer authority and the separately
    required task-level approval remain higher-authority runtime responsibilities.
    """
    rules = contract["protected_override"]
    warnings = [
        "issuer authority must be verified by a higher-authority runtime/organization workflow",
        "task-level approval for the exact action and target must be verified separately",
    ]
    if replay_registry is None:
        warnings.append("single-use override replay status is unverified without an atomic override consumption registry")
    errors: list[str] = []
    schema_name = rules.get("schema", "PROTECTED_OVERRIDE.schema.json")
    try:
        data = load_json(path)
    except Exception as exc:
        return {"object_validity":"INVALID","schema_status":"FAIL","temporal":"NOT_CHECKED","binding":"NOT_CHECKED","authority":"UNVERIFIED","task_approval":"UNVERIFIED","authorization":"NOT_ESTABLISHED","errors":[str(exc)],"warnings":warnings}
    try:
        schema = load_json(root / schema_name)
    except Exception as exc:
        return {"object_validity":"INVALID","schema_status":"FAIL","temporal":"NOT_CHECKED","binding":"NOT_CHECKED","authority":"UNVERIFIED","task_approval":"UNVERIFIED","authorization":"NOT_ESTABLISHED","errors":[f"protected override schema: {exc}"],"warnings":warnings}
    if jsonschema is None:
        return {"object_validity":"INVALID","schema_status":"FAIL","temporal":"NOT_CHECKED","binding":"NOT_CHECKED","authority":"UNVERIFIED","task_approval":"UNVERIFIED","authorization":"NOT_ESTABLISHED","errors":["install dependencies: pip install -r requirements.txt"],"warnings":warnings}
    try:
        jsonschema.validate(data, schema)
    except Exception as exc:
        return {"object_validity":"INVALID","schema_status":"FAIL","temporal":"NOT_CHECKED","binding":"NOT_CHECKED","authority":"UNVERIFIED","task_approval":"UNVERIFIED","authorization":"NOT_ESTABLISHED","errors":[str(exc)],"warnings":warnings}

    catalog = operation_catalog(contract)
    unknown_ops = sorted(set(data["operations"]) - set(catalog))
    if unknown_ops:
        errors.append("override operations must use canonical operation IDs; unknown: " + ", ".join(unknown_ops))
    concrete_targets, target_errors = _concrete_targets(data["targets"])
    errors.extend(target_errors)
    if len(concrete_targets) != len(data["targets"]):
        errors.append("override targets must be unique concrete targets")

    temporal_errors: list[str] = []
    issued = _parse_timestamp(data.get("issued_at"), "issued_at", temporal_errors)
    expires = _parse_timestamp(data.get("expires_at"), "expires_at", temporal_errors)
    now = datetime.now(timezone.utc)
    if issued is not None and expires is not None:
        if issued >= expires:
            temporal_errors.append("issued_at must be earlier than expires_at")
        if issued > now:
            temporal_errors.append("issued_at must not be in the future")
        if expires <= now:
            temporal_errors.append("override is expired")
        max_ttl = int(rules.get("max_ttl_seconds", PROTECTED_OVERRIDE_MAX_TTL_SECONDS))
        if (expires - issued).total_seconds() > max_ttl:
            temporal_errors.append(f"override TTL exceeds maximum of {max_ttl} seconds")
    errors.extend(temporal_errors)
    temporal = "VALID" if issued is not None and expires is not None and not temporal_errors else "INVALID"

    binding = "NOT_CHECKED"
    binding_errors: list[str] = []
    if boundary is not None:
        binding = "VALID"
        if boundary.get("status") != "PASS":
            binding_errors.append("cannot bind override to an invalid execution boundary")
        if data["action_digest"] != boundary.get("action_digest"):
            binding_errors.append("override action_digest does not match the imminent action")
        if data["correlation_id"] != boundary.get("correlation_id"):
            binding_errors.append("override correlation_id does not match the imminent action")
        if data["execution_nonce"] != boundary.get("execution_nonce"):
            binding_errors.append("override execution_nonce does not match the imminent action")
        if set(data["operations"]) != set(boundary.get("actual_operations", [])):
            binding_errors.append("override operations do not exactly match runtime actual_operations")
        if set(data["targets"]) != set(boundary.get("targets", [])):
            binding_errors.append("override targets do not exactly match runtime targets")
        if data["environment"] != boundary.get("environment"):
            binding_errors.append("override environment does not match the imminent action")
        if boundary.get("action_gate") != rules.get("binding_required_for_gate", "PROHIBITED_WITHOUT_OVERRIDE"):
            warnings.append(f"protected override object was supplied for action_gate={boundary.get('action_gate')!r}")
        if binding_errors:
            binding = "INVALID"
            errors.extend(binding_errors)

    replay_protection = "UNVERIFIED"
    if consume and replay_registry is None:
        errors.append("consume=True requires replay_registry for atomic single-use override enforcement")
        replay_protection = "INVALID"
    elif replay_registry is not None and not errors:
        replay_protection, replay_error = _override_replay_state(
            replay_registry, data["override_id"], data["execution_nonce"], data["action_digest"], consume=consume
        )
        if replay_error:
            errors.append(replay_error)
            if binding == "VALID":
                binding = "INVALID"

    return {
        "object_validity":"VALID" if not errors else "INVALID",
        "schema_status":"PASS",
        "temporal":temporal,
        "binding":binding,
        "override_id":data.get("override_id"),
        "correlation_id":data.get("correlation_id"),
        "execution_nonce":data.get("execution_nonce"),
        "action_digest":data.get("action_digest"),
        "replay_protection":replay_protection,
        "authority":"UNVERIFIED",
        "task_approval":"UNVERIFIED",
        "authorization":"NOT_ESTABLISHED",
        "errors":errors,
        "warnings":warnings,
    }
