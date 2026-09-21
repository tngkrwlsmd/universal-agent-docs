from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .contract import AGENTS_PATH, POLICIES_PATH
from .readiness import extract_policy_sections
from .routing import operation_catalog, route_policies


def extract_always_on_invariants(path: Path = AGENTS_PATH) -> str:
    text = path.read_text(encoding="utf-8")
    start_token = "## 2. Always-on invariants"
    end_token = "\n## 3. "
    start = text.find(start_token)
    if start < 0:
        raise ValueError("AGENTS.md is missing the always-on invariants section")
    end = text.find(end_token, start)
    if end < 0:
        end = len(text)
    return text[start:end].strip()


def compile_policy_view(
    contract: dict,
    task_text: str = "",
    operations: Iterable[str] = (),
    resources: Iterable[str] = (),
    routing_mode: str = "advisory",
    extension_registry: dict | None = None,
) -> dict:
    """Compile task-specific context without creating a new policy Source of Truth."""
    routing = route_policies(
        contract,
        task_text,
        operations,
        resources,
        routing_mode,
        extension_registry=extension_registry,
    )
    catalog = operation_catalog(contract, extension_registry)
    operation_contracts = []
    for operation_id in routing["canonical_operations"]:
        operation = catalog[operation_id]
        operation_contracts.append({
            key: operation[key]
            for key in (
                "id", "policies", "effect_floor", "requires_execution_policy",
                "lifecycle_status", "extension_namespace", "supported_adapters",
                "exposure_floor", "production_effect",
            )
            if key in operation
        })
    policy_sections = extract_policy_sections(contract, routing["policies"], POLICIES_PATH)
    extension_used = any("extension_namespace" in item for item in operation_contracts)
    return {
        "status": routing["routing_status"],
        "sources": {
            "always_on_invariants": "AGENTS.md#2-always-on-invariants",
            "machine_contract": "POLICY_CONTRACT.json",
            "human_policy": "POLICIES.md",
        },
        "always_on_invariants": extract_always_on_invariants(),
        "routing": routing,
        "operations": operation_contracts,
        "policy_sections": policy_sections,
        "operation_extension_digest": (
            extension_registry.get("combined_digest")
            if extension_registry and extension_used else None
        ),
        "operation_extension_sources": (
            extension_registry.get("sources", [])
            if extension_registry and extension_used else []
        ),
    }


def render_compiled_policy_view(view: dict) -> str:
    lines = [
        "# Compiled policy view",
        "",
        "Sources: AGENTS.md (always-on invariants), POLICY_CONTRACT.json (machine semantics), "
        "POLICIES.md (selected human primary-owner sections).",
        "",
        view["always_on_invariants"],
        "",
        "## Contract-derived operation summary",
    ]
    if not view["operations"]:
        lines.append("- No canonical operation resolved.")
    for operation in view["operations"]:
        suffix = ""
        if operation.get("extension_namespace"):
            suffix = (
                f"; extension={operation['extension_namespace']}; "
                f"supported_adapters={','.join(operation.get('supported_adapters', []))}"
            )
        lines.append(
            f"- `{operation['id']}`: effect_floor={operation['effect_floor']}; "
            f"policies={','.join(operation.get('policies', []))}; "
            f"requires_execution_policy={str(operation.get('requires_execution_policy', False)).lower()}"
            f"{suffix}"
        )
    if view.get("operation_extension_digest"):
        lines.extend([
            "",
            f"Operation extension digest: `{view['operation_extension_digest']}`",
        ])
    warnings = view["routing"].get("warnings", [])
    errors = view["routing"].get("errors", [])
    if warnings or errors:
        lines.extend(["", "## Routing diagnostics"])
        lines.extend(f"- warning: {item}" for item in warnings)
        lines.extend(f"- error: {item}" for item in errors)
    if view["policy_sections"]:
        lines.extend(["", "## Applicable primary-owner policy sections", ""])
        lines.append("\n\n".join(view["policy_sections"].values()))
    return "\n".join(lines).rstrip() + "\n"
