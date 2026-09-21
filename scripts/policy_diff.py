#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

# Central registry of contract roots whose changes alter machine-enforceable behavior.
# A nested change under one of these roots is conservatively classified as enforcement
# breaking unless a more specific classifier (for example operation lifecycle) owns it.
ENFORCEMENT_SEMANTIC_ROOTS = (
    "execution_boundary",
    "risk_model",
    "protected_override",
)
ROUTING_ENFORCEMENT_FIELDS = (
    "enforcement_requires_resolved_plan",
    "modes",
)
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


def _walk_changes(before: Any, after: Any, prefix: str) -> list[tuple[str, Any, Any]]:
    """Return deterministic leaf-oriented changes below a semantic root."""
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        changes: list[tuple[str, Any, Any]] = []
        for key in sorted(set(before) | set(after)):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in before:
                changes.append((path, None, after[key]))
            elif key not in after:
                changes.append((path, before[key], None))
            else:
                changes.extend(_walk_changes(before[key], after[key], path))
        return changes
    # Arrays are semantic units here: ordering and membership can affect gates/binding.
    return [(prefix, before, after)]


def _schema_type_set(value: Any) -> set[str] | None:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return set(value)
    return None


def _schema_change(changes: list[dict], classification: str, path: str, before: Any, after: Any, action: str) -> None:
    _add(changes, classification, f"schema:{path}", before, after, action)


def _compare_schema_node(before: Any, after: Any, path: str, changes: list[dict]) -> None:
    if before == after:
        return
    if not isinstance(before, dict) or not isinstance(after, dict):
        _schema_change(changes, "behavioral", path, before, after, "Schema structure changed in a way that requires manual compatibility review.")
        return

    handled: set[str] = set()

    # Required properties: additions reject previously valid payloads; removals widen.
    old_required = set(before.get("required", [])) if isinstance(before.get("required", []), list) else set()
    new_required = set(after.get("required", [])) if isinstance(after.get("required", []), list) else set()
    if old_required != new_required:
        handled.add("required")
        added = sorted(new_required - old_required)
        removed = sorted(old_required - new_required)
        if added:
            _schema_change(changes, "breaking_schema", f"{path}.required", sorted(old_required), sorted(new_required), "New required fields must be supplied before upgrading.")
        if removed:
            _schema_change(changes, "backward_compatible", f"{path}.required", sorted(old_required), sorted(new_required), "Previously required fields became optional; existing payloads remain valid with respect to this requirement.")

    # Type sets: narrowing is breaking, widening is backward-compatible, replacement is breaking.
    if before.get("type") != after.get("type") and ("type" in before or "type" in after):
        handled.add("type")
        old_types, new_types = _schema_type_set(before.get("type")), _schema_type_set(after.get("type"))
        if "type" not in before and "type" in after:
            classification = "breaking_schema"
            action = "A type restriction was added; previously valid payload types may be rejected."
        elif "type" in before and "type" not in after:
            classification = "backward_compatible"
            action = "The type restriction was removed; existing payload types remain valid."
        elif old_types is not None and new_types is not None:
            if old_types <= new_types:
                classification = "backward_compatible"
                action = "Accepted JSON types were widened; existing payload types remain accepted."
            else:
                classification = "breaking_schema"
                action = "Accepted JSON types were narrowed or replaced; existing payloads may be rejected."
        else:
            classification = "behavioral"
            action = "Type constraint changed in a form that requires manual compatibility review."
        _schema_change(changes, classification, f"{path}.type", before.get("type"), after.get("type"), action)

    # Enum: subset is narrowing/breaking, superset is widening/backward-compatible.
    if before.get("enum") != after.get("enum") and ("enum" in before or "enum" in after):
        handled.add("enum")
        old_enum, new_enum = before.get("enum"), after.get("enum")
        if "enum" not in before and isinstance(new_enum, list):
            classification, action = "breaking_schema", "An enum restriction was added; previously valid values outside the enum will fail."
        elif isinstance(old_enum, list) and "enum" not in after:
            classification, action = "backward_compatible", "The enum restriction was removed; existing enum payloads remain valid."
        elif isinstance(old_enum, list) and isinstance(new_enum, list):
            old_set, new_set = set(map(json.dumps, old_enum)), set(map(json.dumps, new_enum))
            if old_set <= new_set:
                classification, action = "backward_compatible", "Enum values were added; existing enum payloads remain accepted."
            elif new_set < old_set:
                classification, action = "breaking_schema", "Enum values were removed; existing payloads using removed values will fail."
            else:
                classification, action = "behavioral", "Enum values changed in both directions; review affected producers and consumers manually."
        else:
            classification, action = "behavioral", "Enum constraint changed structurally; review compatibility manually."
        _schema_change(changes, classification, f"{path}.enum", old_enum, new_enum, action)

    # Const replacement always rejects the old constant; removing const widens.
    if before.get("const") != after.get("const") and ("const" in before or "const" in after):
        handled.add("const")
        if "const" in before and "const" not in after:
            classification, action = "backward_compatible", "Const restriction was removed; existing payload remains valid."
        else:
            classification, action = "breaking_schema", "Const restriction was added or changed; previously valid payloads may be rejected."
        _schema_change(changes, classification, f"{path}.const", before.get("const"), after.get("const"), action)

    # additionalProperties false is a tightening. true/schema changes are conservatively reviewed.
    if before.get("additionalProperties", True) != after.get("additionalProperties", True):
        handled.add("additionalProperties")
        old_ap, new_ap = before.get("additionalProperties", True), after.get("additionalProperties", True)
        if new_ap is False and old_ap is not False:
            classification, action = "breaking_schema", "Unknown properties became forbidden; existing payloads may be rejected."
        elif old_ap is False and new_ap is True:
            classification, action = "backward_compatible", "Unknown properties became allowed; existing payloads remain valid."
        else:
            classification, action = "behavioral", "additionalProperties schema changed; review compatibility manually."
        _schema_change(changes, classification, f"{path}.additionalProperties", old_ap, new_ap, action)

    # Numeric/string/array bounds. Higher minimums and lower maximums tighten.
    for keyword, direction in (
        ("minimum", "min"), ("exclusiveMinimum", "min"),
        ("maximum", "max"), ("exclusiveMaximum", "max"),
        ("minLength", "min"), ("maxLength", "max"),
        ("minItems", "min"), ("maxItems", "max"),
    ):
        if before.get(keyword) == after.get(keyword) or (keyword not in before and keyword not in after):
            continue
        handled.add(keyword)
        old, new = before.get(keyword), after.get(keyword)
        if old is None and new is not None:
            classification, action = "breaking_schema", f"{keyword} restriction was added; previously valid payloads may be rejected."
        elif old is not None and new is None:
            classification, action = "backward_compatible", f"{keyword} restriction was removed; existing payloads remain valid."
        elif isinstance(old, (int, float)) and isinstance(new, (int, float)):
            tightened = new > old if direction == "min" else new < old
            classification = "breaking_schema" if tightened else "backward_compatible"
            action = f"{keyword} was {'tightened' if tightened else 'relaxed'}."
        else:
            classification, action = "behavioral", f"{keyword} changed in a form requiring manual review."
        _schema_change(changes, classification, f"{path}.{keyword}", old, new, action)

    if before.get("pattern") != after.get("pattern") and ("pattern" in before or "pattern" in after):
        handled.add("pattern")
        old, new = before.get("pattern"), after.get("pattern")
        if old is None and new is not None:
            classification, action = "breaking_schema", "A pattern restriction was added; previously valid strings may be rejected."
        elif old is not None and new is None:
            classification, action = "backward_compatible", "A pattern restriction was removed; existing payloads remain valid."
        else:
            classification, action = "behavioral", "Pattern changed; automatic widening/narrowing proof is not attempted."
        _schema_change(changes, classification, f"{path}.pattern", old, new, action)

    # Property additions/removals and recursive known-property changes.
    old_props = before.get("properties", {}) if isinstance(before.get("properties", {}), dict) else {}
    new_props = after.get("properties", {}) if isinstance(after.get("properties", {}), dict) else {}
    if old_props != new_props:
        handled.add("properties")
        for name in sorted(set(new_props) - set(old_props)):
            classification = "breaking_schema" if name in new_required else "backward_compatible"
            action = "New property is required." if classification == "breaking_schema" else "Optional property was added; existing payloads remain valid."
            _schema_change(changes, classification, f"{path}.properties.{name}", None, new_props[name], action)
        for name in sorted(set(old_props) - set(new_props)):
            # If unknown properties are forbidden after the change, payloads using the removed property fail.
            classification = "breaking_schema" if after.get("additionalProperties", True) is False else "behavioral"
            action = "Removed property is no longer accepted under additionalProperties=false." if classification == "breaking_schema" else "Property was removed while unknown-property behavior may still accept it; review semantics manually."
            _schema_change(changes, classification, f"{path}.properties.{name}", old_props[name], None, action)
        for name in sorted(set(old_props) & set(new_props)):
            _compare_schema_node(old_props[name], new_props[name], f"{path}.properties.{name}", changes)

    # Composite schemas are intentionally conservative: proving arbitrary oneOf/anyOf/allOf
    # compatibility is out of scope for this deterministic helper.
    for keyword in ("oneOf", "anyOf", "allOf", "not", "if", "then", "else"):
        if before.get(keyword) != after.get(keyword) and (keyword in before or keyword in after):
            handled.add(keyword)
            _schema_change(changes, "behavioral", f"{path}.{keyword}", before.get(keyword), after.get(keyword), "Composite/conditional schema changed; manual compatibility review is required.")

    # Recurse into definitions/items and report any remaining changed keywords as behavioral.
    for keyword in ("$defs", "definitions"):
        old_defs = before.get(keyword, {}) if isinstance(before.get(keyword, {}), dict) else {}
        new_defs = after.get(keyword, {}) if isinstance(after.get(keyword, {}), dict) else {}
        if old_defs != new_defs:
            handled.add(keyword)
            for name in sorted(set(old_defs) | set(new_defs)):
                if name not in old_defs or name not in new_defs:
                    _schema_change(changes, "behavioral", f"{path}.{keyword}.{name}", old_defs.get(name), new_defs.get(name), "Schema definition was added or removed; review references manually.")
                else:
                    _compare_schema_node(old_defs[name], new_defs[name], f"{path}.{keyword}.{name}", changes)
    if before.get("items") != after.get("items") and ("items" in before or "items" in after):
        handled.add("items")
        if isinstance(before.get("items"), dict) and isinstance(after.get("items"), dict):
            _compare_schema_node(before["items"], after["items"], f"{path}.items", changes)
        else:
            _schema_change(changes, "behavioral", f"{path}.items", before.get("items"), after.get("items"), "Array item schema changed structurally; manual compatibility review is required.")

    ignored_annotation_keywords = {"title", "description", "$comment", "examples", "default"}
    for key in sorted(set(before) | set(after)):
        if key in handled or key in ignored_annotation_keywords:
            continue
        if before.get(key) != after.get(key):
            _schema_change(changes, "behavioral", f"{path}.{key}", before.get(key), after.get(key), "Schema keyword changed without a proven compatibility rule; review manually.")


def compare_schema_requirements(before_schema: dict, after_schema: dict) -> list[dict]:
    """Compatibility alias retained for callers; now performs broader conservative analysis."""
    changes: list[dict] = []
    _compare_schema_node(before_schema, after_schema, "$", changes)
    # Avoid duplicate identical records from overlapping recursive observations.
    unique: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()
    for change in changes:
        key = (
            change["classification"], change["path"],
            json.dumps(change["before"], sort_keys=True, ensure_ascii=False, default=str),
            json.dumps(change["after"], sort_keys=True, ensure_ascii=False, default=str),
        )
        if key not in seen:
            seen.add(key)
            unique.append(change)
    return unique


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

    # Enforcement roots are classified recursively so newly added nested security fields
    # cannot silently become no_semantic_change merely because this tool predates them.
    for root in ENFORCEMENT_SEMANTIC_ROOTS:
        for path, old, new in _walk_changes(before.get(root), after.get(root), root):
            _add(changes, "breaking_enforcement", path, old, new, "Machine-enforceable semantics changed; update runtime expectations and regression evidence before upgrading.")

    old_routing, new_routing = before.get("routing", {}), after.get("routing", {})
    for field in ROUTING_ENFORCEMENT_FIELDS:
        if old_routing.get(field) != new_routing.get(field):
            for path, old, new in _walk_changes(old_routing.get(field), new_routing.get(field), f"routing.{field}"):
                _add(changes, "breaking_enforcement", path, old, new, "Routing enforcement behavior changed; re-evaluate planning and fail-closed expectations.")

    old_schema_version, new_schema_version = before.get("schema_version"), after.get("schema_version")
    if old_schema_version != new_schema_version:
        classification = "breaking_schema" if isinstance(old_schema_version, int) and isinstance(new_schema_version, int) and new_schema_version > old_schema_version else "behavioral"
        _add(changes, classification, "schema_version", old_schema_version, new_schema_version, "Confirm the consumer supports the target schema version and review migration notes.")

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

    # Deduplicate paths already covered by more specific operation/lifecycle handling.
    priority = {
        "removed_operation": 0, "breaking_schema": 1, "breaking_enforcement": 2,
        "deprecated_operation": 3, "behavioral": 4, "additive": 5, "backward_compatible": 6,
    }
    dedup: dict[tuple[str, str, str], dict] = {}
    for change in changes:
        key = (
            change["path"],
            json.dumps(change["before"], sort_keys=True, ensure_ascii=False, default=str),
            json.dumps(change["after"], sort_keys=True, ensure_ascii=False, default=str),
        )
        existing = dedup.get(key)
        if existing is None or priority[change["classification"]] < priority[existing["classification"]]:
            dedup[key] = change
    changes = sorted(dedup.values(), key=lambda x: (priority[x["classification"]], x["path"]))

    counts = {key: 0 for key in priority}
    for change in changes:
        counts[change["classification"]] += 1
    return {
        "format": "universal-agent-docs-policy-diff-v1",
        "from_schema_version": old_schema_version,
        "to_schema_version": new_schema_version,
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
