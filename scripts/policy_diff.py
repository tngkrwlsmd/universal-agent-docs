#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SEMANTIC_OPERATION_FIELDS = (
    "effect_floor", "requires_execution_policy", "policies", "production_effect",
    "exposure_floor", "allowed_environments", "required_semantic_details",
    "semantic_detail_allowed_values",
)


def _catalog(contract: dict) -> dict[str, dict]:
    return {item["id"]: item for item in contract.get("routing", {}).get("operation_catalog", [])}


def _add(changes: list[dict], classification: str, path: str, before: Any, after: Any, consumer_action: str) -> None:
    changes.append({
        "classification": classification,
        "path": path,
        "before": before,
        "after": after,
        "consumer_action": consumer_action,
    })


def _required_paths(schema: object, prefix: str = "$") -> dict[str, set[str]]:
    """Collect JSON Schema required-property sets for deterministic compatibility hints."""
    found: dict[str, set[str]] = {}
    if isinstance(schema, dict):
        required = schema.get("required")
        if isinstance(required, list) and all(isinstance(item, str) for item in required):
            found[prefix] = set(required)
        for key, value in schema.items():
            if isinstance(value, (dict, list)):
                found.update(_required_paths(value, f"{prefix}.{key}"))
    elif isinstance(schema, list):
        for index, value in enumerate(schema):
            if isinstance(value, (dict, list)):
                found.update(_required_paths(value, f"{prefix}[{index}]"))
    return found


def compare_schema_requirements(before_schema: dict, after_schema: dict) -> list[dict]:
    changes: list[dict] = []
    old, new = _required_paths(before_schema), _required_paths(after_schema)
    for path in sorted(set(old) | set(new)):
        added = sorted(new.get(path, set()) - old.get(path, set()))
        removed = sorted(old.get(path, set()) - new.get(path, set()))
        if added:
            _add(changes, "breaking_schema", f"schema.required:{path}", sorted(old.get(path, set())), sorted(new.get(path, set())), "New required schema fields must be supplied before upgrading.")
        if removed:
            _add(changes, "backward_compatible", f"schema.required:{path}", sorted(old.get(path, set())), sorted(new.get(path, set())), "Previously required fields became optional; existing payloads remain valid with respect to this requirement.")
    if before_schema != after_schema and not changes:
        _add(changes, "behavioral", "schema", "changed", "changed", "Schema changed outside required-field sets; review the JSON Schema diff manually.")
    return changes


def compare_contracts(before: dict, after: dict, *, before_schema: dict | None = None, after_schema: dict | None = None) -> dict:
    changes: list[dict] = []
    old_ops, new_ops = _catalog(before), _catalog(after)

    for op in sorted(set(new_ops) - set(old_ops)):
        _add(changes, "additive", f"routing.operation_catalog.{op}", None, new_ops[op], "Adapters may opt in to the new canonical operation.")
    for op in sorted(set(old_ops) - set(new_ops)):
        _add(changes, "removed_operation", f"routing.operation_catalog.{op}", old_ops[op], None, "Consumers using this operation must migrate before upgrading.")
    for op in sorted(set(old_ops) & set(new_ops)):
        old, new = old_ops[op], new_ops[op]
        if old.get("lifecycle_status") != new.get("lifecycle_status") and new.get("lifecycle_status") == "deprecated":
            _add(changes, "deprecated_operation", f"routing.operation_catalog.{op}.lifecycle_status", old.get("lifecycle_status"), "deprecated", f"Migrate to {new.get('replacement_operation')!r} before removal.")
        for field in SEMANTIC_OPERATION_FIELDS:
            if old.get(field) != new.get(field):
                _add(changes, "breaking_enforcement", f"routing.operation_catalog.{op}.{field}", old.get(field), new.get(field), "Re-evaluate plans, adapters, approvals and expected gates for this operation.")

    old_exec = before.get("execution_boundary", {})
    new_exec = after.get("execution_boundary", {})
    for field in (
        "required_inputs", "environment_exposure_floors", "production_effect_escalation_operations",
        "runtime_forbidden_operations", "context_effect_escalation_rules", "operation_semantic_requirements",
        "approval_binding_required_for_gate", "action_digest_binds",
    ):
        if old_exec.get(field) != new_exec.get(field):
            _add(changes, "breaking_enforcement", f"execution_boundary.{field}", old_exec.get(field), new_exec.get(field), "Update runtime adapters and regression expectations before upgrading.")

    old_risk, new_risk = before.get("risk_model", {}), after.get("risk_model", {})
    if old_risk.get("decision_matrix") != new_risk.get("decision_matrix"):
        _add(changes, "breaking_enforcement", "risk_model.decision_matrix", old_risk.get("decision_matrix"), new_risk.get("decision_matrix"), "Re-check approval/override gates for existing actions.")

    old_schema, new_schema = before.get("schema_version"), after.get("schema_version")
    if old_schema != new_schema:
        classification = "breaking_schema" if isinstance(old_schema, int) and isinstance(new_schema, int) and new_schema > old_schema else "behavioral"
        _add(changes, classification, "schema_version", old_schema, new_schema, "Confirm the consumer supports the target schema version and review migration notes.")

    # Non-enforcement contract metadata is reported as behavioral, not silently ignored.
    for field in ("authority", "integrity", "operation_lifecycle", "consumer_distribution"):
        if before.get(field) != after.get(field):
            _add(changes, "behavioral", field, before.get(field), after.get(field), "Review the changed contract metadata and trust/distribution assumptions.")

    old_distribution = before.get("distribution", {})
    new_distribution = after.get("distribution", {})
    for field in ("required_files", "allowed_files"):
        old_values = set(old_distribution.get(field, []))
        new_values = set(new_distribution.get(field, []))
        added = sorted(new_values - old_values)
        removed = sorted(old_values - new_values)
        if added:
            _add(changes, "additive", f"distribution.{field}.added", [], added, "Consume the new versioned artifact; no existing operation semantics changed.")
        if removed:
            _add(changes, "behavioral", f"distribution.{field}.removed", removed, [], "Review packaging expectations before upgrading.")

    if before_schema is not None or after_schema is not None:
        if before_schema is None or after_schema is None:
            raise ValueError("before_schema and after_schema must be supplied together")
        changes.extend(compare_schema_requirements(before_schema, after_schema))

    order = {
        "removed_operation": 0, "breaking_schema": 1, "breaking_enforcement": 2,
        "deprecated_operation": 3, "behavioral": 4, "additive": 5, "backward_compatible": 6,
    }
    changes.sort(key=lambda x: (order[x["classification"]], x["path"]))
    counts = {key: 0 for key in order}
    for change in changes:
        counts[change["classification"]] += 1
    return {
        "format": "universal-agent-docs-policy-diff-v1",
        "from_schema_version": old_schema,
        "to_schema_version": new_schema,
        "summary": counts,
        "requires_consumer_migration": any(counts[k] for k in ("removed_operation", "breaking_schema", "breaking_enforcement")),
        "compatibility": "breaking" if any(counts[k] for k in ("removed_operation", "breaking_schema", "breaking_enforcement")) else ("compatible_change" if changes else "no_semantic_change"),
        "changes": changes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two policy contracts by semantic compatibility categories")
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--before-schema", type=Path, help="optional JSON Schema paired with before contract")
    parser.add_argument("--after-schema", type=Path, help="optional JSON Schema paired with after contract")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    before = json.loads(args.before.read_text(encoding="utf-8"))
    after = json.loads(args.after.read_text(encoding="utf-8"))
    before_schema = json.loads(args.before_schema.read_text(encoding="utf-8")) if args.before_schema else None
    after_schema = json.loads(args.after_schema.read_text(encoding="utf-8")) if args.after_schema else None
    result = compare_contracts(before, after, before_schema=before_schema, after_schema=after_schema)
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(f"schema: {result['from_schema_version']} -> {result['to_schema_version']}")
        for key, value in result["summary"].items():
            print(f"{key}: {value}")
        for change in result["changes"]:
            print(f"[{change['classification']}] {change['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
