#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import posixpath
import re
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

try:
    import jsonschema
except ImportError:  # pragma: no cover - exercised by CLI environments without deps
    jsonschema = None

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "POLICY_CONTRACT.json"
SCHEMA_PATH = ROOT / "POLICY_CONTRACT.schema.json"
ALIASES_PATH = ROOT / "ROUTING_ALIASES.json"
ALIASES_SCHEMA_PATH = ROOT / "ROUTING_ALIASES.schema.json"
RUNTIME_ACTION_SCHEMA_PATH = ROOT / "RUNTIME_ACTION.schema.json"
APPROVAL_ASSERTION_SCHEMA_PATH = ROOT / "APPROVAL_ASSERTION.schema.json"
PROTECTED_OVERRIDE_SCHEMA_PATH = ROOT / "PROTECTED_OVERRIDE.schema.json"
PROJECT_PATH = ROOT / "PROJECT.md"
POLICIES_PATH = ROOT / "POLICIES.md"
AGENTS_PATH = ROOT / "AGENTS.md"
PROJECT_START = "<!-- project-facts:start -->"
PROJECT_END = "<!-- project-facts:end -->"
CANONICAL_ROOT = "universal-agent-docs"
SUPPORTED_SCHEMA_VERSIONS = {10}
ROUTING_NORMALIZATION_ID = "nfkc_casefold_token_boundary_v3"
ROUTING_INPUTS = ["task_text", "planned_operations", "affected_resources"]
TASK_HINT_AUTHORITY = "advisory_only"
ENFORCEMENT_REQUIRES_RESOLVED_PLAN = True
EXECUTION_BOUNDARY_INPUTS = [
    "planned_operations", "actual_operations", "affected_resources", "targets", "environment",
    "exposure_facts", "correlation_id", "execution_nonce"
]
KNOWN_ENVIRONMENTS = ["local", "test", "staging", "production", "public", "external", "unknown"]
ENVIRONMENT_EXPOSURE_FLOORS = {
    "local": "X0", "test": "X0", "staging": "X1", "production": "X2",
    "public": "X0", "external": "X0", "unknown": "X2",
}
EXPOSURE_DERIVATION = {
    "algorithm": "max_floor_v1",
    "declared_exposure_authority": "advisory_raise_only",
    "required_fact_keys": [
        "data_classification", "credential_class", "tenant_scope", "public_visibility", "estimated_blast_radius",
        "estimated_financial_impact"
    ],
    "fact_floors": {
        "data_classification": {
            "public": "X0", "internal": "X1", "confidential": "X2", "restricted": "X2",
            "regulated": "X3", "unknown": "X2",
        },
        "credential_class": {
            "none": "X0", "user_secret": "X1", "service_credential": "X2",
            "privileged_credential": "X3", "break_glass": "X3", "unknown": "X2",
        },
        "tenant_scope": {
            "single_user": "X0", "single_tenant": "X1", "multi_tenant": "X2",
            "organization_wide": "X3", "global": "X3", "unknown": "X2",
        },
        "public_visibility": {
            "none": "X0", "public_source": "X0", "public_destination": "X2",
            "bidirectional": "X2", "unknown": "X2",
        },
        "estimated_blast_radius": {
            "single_resource": "X0", "bounded_set": "X1", "service": "X2",
            "organization": "X3", "global": "X3", "unknown": "X2",
        },
        "estimated_financial_impact": {
            "none": "X0", "negligible": "X0", "bounded": "X1",
            "material": "X2", "critical": "X3", "unknown": "X2",
        },
    },
}
PRODUCTION_EFFECT_ESCALATION_OPERATIONS = [
    "database.write", "database.schema_change", "database.destructive_change",
    "deploy.execute", "rollback.execute", "permission.change", "credential.rotate", "iam.change",
    "service.restart", "cloud.resource_change", "cloud.resource_delete", "storage.object_delete",
    "network.configuration_change",
]
CONTEXT_EFFECT_ESCALATION_RULES = [
    {
        "id": "public_distribution_publish",
        "operations": ["artifact.publish", "package.publish"],
        "match_any": [
            {"source": "environment", "values": ["public"]},
            {"source": "exposure_facts.public_visibility", "values": ["public_destination", "bidirectional"]},
        ],
        "effect": "L4",
    }
]
APPROVAL_MAX_TTL_SECONDS = 1800
PROTECTED_OVERRIDE_MAX_TTL_SECONDS = 900
TARGET_REQUIRED_EFFECT_LEVELS = ["L3", "L4"]
TARGET_REQUIRED_EXPOSURE_LEVELS = ["X2", "X3"]
TRUST_MANIFEST_FORMAT = "universal-agent-docs-trust-manifest-v2"
RELEASE_MANIFEST_FORMAT = "universal-agent-docs-release-manifest-v2"
ACTION_DIGEST_FORMAT = "universal-agent-docs-action-digest-v3"
TRUSTED_CORE_FILES = [
    "AGENTS.md", "POLICIES.md", "POLICY_CONTRACT.json", "POLICY_CONTRACT.schema.json",
    "ROUTING_ALIASES.json", "ROUTING_ALIASES.schema.json", "RUNTIME_ACTION.schema.json",
    "APPROVAL_ASSERTION.schema.json", "PROTECTED_OVERRIDE.schema.json", "scripts/validate.py", "scripts/package.py", "requirements.txt", "requirements.lock",
]
REVIEW_FRESHNESS_DAYS = 90
PROJECT_FACT_KEYS = (
    "repository_root", "primary_source", "build_command", "test_command", "runtime",
    "deploy_command", "deploy_target",
)
PROJECT_FACT_STATUSES = {"Confirmed", "Inferred", "Unknown", "N/A"}
CANONICAL_REQUIRED_FILES = [
    "AGENTS.md",
    "POLICIES.md",
    "PROJECT.md",
    "POLICY_CONTRACT.json",
    "POLICY_CONTRACT.schema.json",
    "ROUTING_ALIASES.json",
    "ROUTING_ALIASES.schema.json",
    "RUNTIME_ACTION.schema.json",
    "APPROVAL_ASSERTION.schema.json",
    "PROTECTED_OVERRIDE.schema.json",
    "README.md",
    "LICENSE",
    "requirements.txt",
    "requirements.lock",
    "scripts/validate.py",
    "scripts/package.py",
    "tests/__init__.py",
    "tests/test_policy.py",
    "tests/test_fuzz.py",
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
    "conformance/README.md",
    "conformance/golden.json",
    "conformance/invalid.json",
    "tests/test_conformance.py",
]


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def canonical_policy_contract_digest(contract: dict) -> str:
    """Return a stable semantic SHA-256 for the machine policy contract.

    The project intentionally has no date/version suffix in its artifact name. Approval
    binding instead pins the exact canonical JSON semantics of POLICY_CONTRACT.json.
    """
    encoded = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"[^\w가-힣]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def has_hangul(value: str) -> bool:
    return bool(re.search(r"[가-힣]", value))


KOREAN_PARTICLES = (
    "은", "는", "이", "가", "을", "를", "에", "에서", "에게", "께", "도",
    "와", "과", "로", "으로", "의", "만", "부터", "까지", "랑", "이랑", "하고",
)


def _korean_literal_token_matches(source: str, target: str) -> bool:
    if source == target:
        return True
    return any(source == target + particle for particle in KOREAN_PARTICLES)


def phrase_matches(normalized: str, phrase: str) -> bool:
    """Match token boundaries; Korean particles are allowed but substrings are not.

    This prevents a hint such as '로그' from matching '로그인', while still letting
    '테스트' match '테스트도' or '프로덕션' match '프로덕션에'.
    """
    p = normalize_text(phrase)
    if not p:
        return False
    if has_hangul(p):
        source_tokens = normalized.split()
        phrase_tokens = p.split()
        width = len(phrase_tokens)
        for i in range(len(source_tokens) - width + 1):
            window = source_tokens[i : i + width]
            if all(_korean_literal_token_matches(src, dst) for src, dst in zip(window, phrase_tokens)):
                return True
        return False
    pattern = r"(?<!\w)" + re.escape(p).replace(r"\ ", r"\s+") + r"(?!\w)"
    return bool(re.search(pattern, normalized, flags=re.UNICODE))


def stem_matches(normalized: str, stem: str) -> bool:
    s = normalize_text(stem)
    if not s:
        return False
    if has_hangul(s):
        # Korean task suffixes/particles often attach to the final token. Prefix
        # matching is allowed only for explicitly declared stems. Multi-token stems
        # require exact preceding tokens and prefix-match only the final token.
        source_tokens = normalized.split()
        stem_tokens = s.split()
        if not stem_tokens:
            return False
        width = len(stem_tokens)
        for i in range(len(source_tokens) - width + 1):
            window = source_tokens[i : i + width]
            leading_ok = all(_korean_literal_token_matches(src, dst) for src, dst in zip(window[:-1], stem_tokens[:-1]))
            if leading_ok and window[-1].startswith(stem_tokens[-1]):
                return True
        return False
    pattern = r"(?<![a-z0-9_])" + re.escape(s) + r"[a-z0-9_-]*(?![a-z0-9_])"
    return bool(re.search(pattern, normalized))


def operation_catalog(contract: dict) -> dict[str, dict]:
    return {item["id"]: item for item in contract["routing"]["operation_catalog"]}


def load_routing_aliases(contract: dict, root: Path = ROOT) -> dict:
    source = contract.get("routing", {}).get("alias_source", "ROUTING_ALIASES.json")
    return load_json(root / source)


def infer_operations(contract: dict, text: str, aliases_doc: dict | None = None) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    if aliases_doc is None:
        aliases_doc = load_routing_aliases(contract)
    alias_operations = aliases_doc.get("operations", {}) if isinstance(aliases_doc, dict) else {}
    matched: list[str] = []
    for operation in contract["routing"]["operation_catalog"]:
        aliases = alias_operations.get(operation["id"], {})
        phrase_hit = any(phrase_matches(normalized, x) for x in aliases.get("phrases", []))
        stem_hit = any(stem_matches(normalized, x) for x in aliases.get("stems", []))
        pattern_hit = False
        for pattern in aliases.get("patterns", []):
            try:
                if re.search(pattern, normalized, flags=re.UNICODE):
                    pattern_hit = True
                    break
            except re.error:
                continue
        if phrase_hit or stem_hit or pattern_hit:
            matched.append(operation["id"])
    return matched


def route_policies(
    contract: dict,
    task_text: str = "",
    operations: Iterable[str] = (),
    resources: Iterable[str] = (),
    routing_mode: str = "advisory",
    aliases_doc: dict | None = None,
) -> dict:
    """Route through canonical IDs; natural-language aliases are advisory hints only.

    Enforcement requires at least one resolved planned canonical operation. Task-text
    classification and task/plan disagreement stay visible as anomaly signals, but do
    not outrank a canonical plan. The execution boundary remains fail-closed by comparing
    trusted runtime actual operations against that plan.
    """
    catalog = operation_catalog(contract)
    modes = contract.get("routing", {}).get("modes", {})
    if routing_mode not in modes:
        raise ValueError(f"unknown routing mode: {routing_mode}")
    mode_rules = modes[routing_mode]
    if aliases_doc is None:
        aliases_doc = load_routing_aliases(contract)
    operations = list(operations)
    resources = list(resources)
    canonical_operations: list[str] = []
    planned_canonical_operations: list[str] = []
    operation_sources: list[str] = []
    unresolved_operations: list[str] = []
    policies: list[str] = []
    matched_resources: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []

    def add_operation(operation_id: str, source: str) -> None:
        if operation_id not in canonical_operations:
            canonical_operations.append(operation_id)
            operation_sources.append(f"{source} -> {operation_id}")

    def add_planned_operation(operation_id: str, source: str) -> None:
        if operation_id not in planned_canonical_operations:
            planned_canonical_operations.append(operation_id)
        add_operation(operation_id, source)

    def add_policy(policy_id: str) -> None:
        if policy_id not in policies:
            policies.append(policy_id)

    task_matches = infer_operations(contract, task_text, aliases_doc)
    for operation_id in task_matches:
        add_operation(operation_id, "task_hint")

    for raw in operations:
        candidate = str(raw).strip()
        if not candidate:
            continue
        if candidate in catalog:
            add_planned_operation(candidate, f"planned:{candidate}")
            continue
        inferred = infer_operations(contract, candidate, aliases_doc)
        if inferred:
            for operation_id in inferred:
                add_planned_operation(operation_id, f"planned_alias:{candidate}")
        else:
            unresolved_operations.append(candidate)

    for operation_id in canonical_operations:
        operation = catalog[operation_id]
        for policy_id in operation["policies"]:
            add_policy(policy_id)
        if operation.get("requires_execution_policy"):
            add_policy("execution")

    normalized_resources: list[str] = []
    for raw in resources:
        resource = str(raw).replace("\\", "/")
        while resource.startswith("./"):
            resource = resource[2:]
        if resource:
            normalized_resources.append(resource)

    for policy in contract["policies"]:
        for resource in normalized_resources:
            if any(fnmatch.fnmatch(resource, pattern) for pattern in policy.get("resource_globs", [])):
                add_policy(policy["id"])
                item = f"{resource} -> {policy['id']}"
                if item not in matched_resources:
                    matched_resources.append(item)

    if unresolved_operations:
        message = ("unresolved planned operation(s): " + ", ".join(unresolved_operations)
                   + "; use canonical operation IDs or extend ROUTING_ALIASES.json")
        (errors if mode_rules["unresolved_operation_behavior"] == "FAIL" else warnings).append(message)
    if operations and not planned_canonical_operations:
        message = "planned operations were supplied but none resolved to a canonical operation"
        (errors if mode_rules["unresolved_operation_behavior"] == "FAIL" else warnings).append(message)
    if (routing_mode == "enforcement" and contract.get("routing", {}).get("enforcement_requires_resolved_plan", ENFORCEMENT_REQUIRES_RESOLVED_PLAN)
            and not planned_canonical_operations):
        errors.append("enforcement routing requires at least one resolved planned canonical operation")

    normalized_task = normalize_text(task_text)
    task_hint_status = "EMPTY" if not normalized_task else ("CLASSIFIED" if task_matches else "UNCLASSIFIED")
    if normalized_task and not task_matches:
        message = ("task text did not resolve to a canonical operation; supply planned canonical operation IDs "
                   "and ensure the task is independently classifiable before autonomous execution, or extend ROUTING_ALIASES.json")
        (errors if mode_rules["unclassified_task_behavior"] == "FAIL" else warnings).append(message)

    task_plan_gaps = sorted(set(task_matches) - set(planned_canonical_operations)) if operations else []
    if task_plan_gaps:
        message = ("task-derived canonical operation(s) are absent from planned operations: "
                   + ", ".join(task_plan_gaps) + "; the plan may under-declare effects")
        behavior = mode_rules.get("task_plan_mismatch_behavior", mode_rules["unclassified_task_behavior"])
        (errors if behavior == "FAIL" else warnings).append(message)

    risk_floors = {op_id: catalog[op_id]["effect_floor"] for op_id in canonical_operations}
    routing_status = "FAIL" if errors else ("WARN" if warnings else "PASS")
    return {
        "routing_mode": routing_mode,
        "normalized_task": normalized_task,
        "task_hint_status": task_hint_status,
        "routing_status": routing_status,
        "canonical_operations": canonical_operations,
        "planned_canonical_operations": planned_canonical_operations,
        "task_plan_gaps": task_plan_gaps,
        "operation_sources": operation_sources,
        "unresolved_operations": unresolved_operations,
        "effect_floors": risk_floors,
        "policies": policies,
        "matched_resources": matched_resources,
        "warnings": warnings,
        "errors": errors,
    }


_EFFECT_RANK = {"L1": 1, "L2": 2, "L3": 3, "L4": 4}
_EXPOSURE_RANK = {"X0": 0, "X1": 1, "X2": 2, "X3": 3}


def _max_level(values: Iterable[str], ranks: dict[str, int]) -> str | None:
    valid = [value for value in values if value in ranks]
    return max(valid, key=ranks.__getitem__) if valid else None


def _concrete_targets(targets: Iterable[str]) -> tuple[list[str], list[str]]:
    normalized: list[str] = []
    errors: list[str] = []
    for raw in targets:
        value = str(raw).strip()
        if not value:
            errors.append("target must be a non-empty string")
            continue
        if value.casefold() in {"all", "any", "*", "everything"} or any(ch in value for ch in "*?[]"):
            errors.append(f"target must be concrete and non-wildcard: {value!r}")
            continue
        if value not in normalized:
            normalized.append(value)
    return normalized, errors


HARD_ACTION_SIGNATURES = (
    (re.compile(r"\bgit\s+reset\s+--hard\b", re.I), "git.destructive_change"),
    (re.compile(r"\bgit\s+push\b[^\n]*(?:--force(?:-with-lease)?|-f)(?:\s|$)", re.I), "git.destructive_change"),
    (re.compile(r"\bterraform\s+destroy\b", re.I), "cloud.resource_delete"),
    (re.compile(r"\baws\s+s3\s+rm\b[^\n]*\s--recursive\b", re.I), "storage.object_delete"),
    (re.compile(r"\b(?:drop\s+(?:table|database)|truncate\s+table)\b", re.I), "database.destructive_change"),
)
_RM_RF_SIGNATURE = re.compile(r"(?<!\w)rm\s+(?:-[a-z]*r[a-z]*f[a-z]*|-[a-z]*f[a-z]*r[a-z]*)\s+([^;&|\n]+)", re.I)
_GENERATED_DELETE_TARGET = re.compile(r"^(?:\./)?(?:build|dist|coverage|out|target|\.cache)(?:/)?$", re.I)
_KUBECTL_DELETE_SIGNATURE = re.compile(r"\bkubectl\s+delete\s+([a-z0-9.-]+)\b", re.I)


def infer_hard_action_operations(text: str) -> list[str]:
    """Return only high-confidence command signatures suitable for fail-closed checks.

    Recursive local deletion is L2 only for a small allowlist of conventional generated
    output directories. Other recursive deletion is treated as general filesystem.delete.
    Kubernetes pod deletion is treated as a bounded resource change; deleting any other
    resource kind is classified as cloud.resource_delete.
    """
    operations = [operation for pattern, operation in HARD_ACTION_SIGNATURES if pattern.search(text)]

    rm_match = _RM_RF_SIGNATURE.search(text)
    if rm_match:
        raw_target = rm_match.group(1).strip().strip("'\"")
        operation = "filesystem.generated_delete" if _GENERATED_DELETE_TARGET.fullmatch(raw_target) else "filesystem.delete"
        operations.append(operation)

    kubectl_match = _KUBECTL_DELETE_SIGNATURE.search(text)
    if kubectl_match:
        kind = kubectl_match.group(1).casefold()
        operations.append("cloud.resource_change" if kind in {"pod", "pods"} else "cloud.resource_delete")

    return list(dict.fromkeys(operations))


def derive_exposure_floor(
    contract: dict,
    environment: str,
    exposure_facts: dict | None,
    declared_exposure: str | None = None,
) -> dict:
    """Derive Exposure from raw runtime facts; adapter labels may only raise the result.

    The runtime reports facts. The policy engine owns the classification. Unknown fact
    values fail closed at the schema/function boundary rather than being silently mapped.
    Explicit ``unknown`` enum values are allowed and intentionally map to a conservative
    floor.
    """
    cfg = contract.get("execution_boundary", {})
    derivation = cfg.get("exposure_derivation", EXPOSURE_DERIVATION)
    required_keys = derivation.get("required_fact_keys", [])
    fact_floors = derivation.get("fact_floors", {})
    errors: list[str] = []
    warnings: list[str] = []
    contributions: list[dict] = []

    env = str(environment).strip().casefold()
    env_floors = cfg.get("environment_exposure_floors", ENVIRONMENT_EXPOSURE_FLOORS)
    if env in env_floors:
        contributions.append({"source": "environment", "value": env, "floor": env_floors[env]})

    if not isinstance(exposure_facts, dict):
        errors.append("exposure_facts must be an object containing raw exposure dimensions")
        exposure_facts = {}

    missing = [key for key in required_keys if key not in exposure_facts]
    if missing:
        errors.append("exposure_facts missing required key(s): " + ", ".join(missing))

    unexpected = sorted(set(exposure_facts) - set(required_keys))
    if unexpected:
        errors.append("exposure_facts contains unsupported key(s): " + ", ".join(unexpected))

    normalized_facts: dict[str, str] = {}
    for key in required_keys:
        if key not in exposure_facts:
            continue
        value = str(exposure_facts[key]).strip()
        mapping = fact_floors.get(key, {})
        if value not in mapping:
            errors.append(f"exposure_facts.{key} must be one of {sorted(mapping)}; got {value!r}")
            continue
        normalized_facts[key] = value
        contributions.append({"source": key, "value": value, "floor": mapping[value]})

    derived = _max_level((x["floor"] for x in contributions), _EXPOSURE_RANK)
    effective = derived
    if declared_exposure is not None:
        if declared_exposure not in _EXPOSURE_RANK:
            errors.append(f"declared_exposure must be one of {sorted(_EXPOSURE_RANK)}; got {declared_exposure!r}")
        elif effective is None or _EXPOSURE_RANK[declared_exposure] > _EXPOSURE_RANK[effective]:
            effective = declared_exposure
            warnings.append(f"adapter-declared Exposure raised the derived floor to {declared_exposure}; it cannot lower policy-derived Exposure")
        elif _EXPOSURE_RANK[declared_exposure] < _EXPOSURE_RANK[effective]:
            warnings.append(f"adapter-declared Exposure {declared_exposure} was lower than policy-derived {effective} and was ignored")

    return {
        "status": "FAIL" if errors else "PASS",
        "facts": normalized_facts,
        "contributions": contributions,
        "derived_exposure": derived,
        "effective_exposure": effective,
        "declared_exposure": declared_exposure,
        "errors": errors,
        "warnings": warnings,
    }


def canonical_action_digest_payload(
    *,
    policy_schema_version: int,
    policy_contract_digest: str,
    adapter: dict | None,
    correlation_id: str,
    execution_nonce: str,
    planned_operations: Iterable[str],
    actual_operations: Iterable[str],
    affected_resources: Iterable[str],
    targets: Iterable[str],
    environment: str,
    exposure_facts: dict,
    declared_exposure: str | None,
    runtime_effect: str | None,
    actual_action: str,
    semantic_details: dict | None,
) -> dict:
    """Return the exact security-relevant payload bound by approval/override.

    Digest v3 deliberately binds policy identity, adapter identity, semantic parameters,
    and a single-use execution nonce so changing any execution-relevant meaning changes
    the digest.
    """
    normalized_adapter = {} if adapter is None else {k: adapter[k] for k in sorted(adapter)}
    normalized_semantics = {} if semantic_details is None else {k: semantic_details[k] for k in sorted(semantic_details)}
    return {
        "format": ACTION_DIGEST_FORMAT,
        "policy_schema_version": policy_schema_version,
        "policy_contract_digest": policy_contract_digest,
        "adapter": normalized_adapter,
        "correlation_id": str(correlation_id),
        "execution_nonce": str(execution_nonce),
        "planned_operations": sorted(set(str(x) for x in planned_operations)),
        "actual_operations": sorted(set(str(x) for x in actual_operations)),
        "affected_resources": sorted(set(str(x) for x in affected_resources)),
        "targets": sorted(set(str(x) for x in targets)),
        "environment": str(environment).strip().casefold(),
        "exposure_facts": {k: exposure_facts[k] for k in sorted(exposure_facts)},
        "declared_exposure": declared_exposure,
        "runtime_effect": runtime_effect,
        "actual_action": actual_action,
        "semantic_details": normalized_semantics,
    }


def compute_action_digest(**kwargs) -> str:
    payload = canonical_action_digest_payload(**kwargs)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def evaluate_execution_boundary(
    contract: dict,
    planned_operations: Iterable[str],
    actual_operations: Iterable[str],
    resources: Iterable[str],
    targets: Iterable[str],
    environment: str,
    declared_exposure: str | None = None,
    runtime_effect: str | None = None,
    actual_action: str = "",
    aliases_doc: dict | None = None,
    *,
    exposure_facts: dict | None = None,
    correlation_id: str = "",
    execution_nonce: str = "",
    adapter: dict | None = None,
    semantic_details: dict | None = None,
) -> dict:
    """Evaluate the policy gate for an imminent action.

    Runtime/tool adapters assert action facts and canonical operations. They do not own
    Exposure classification: the validator derives a conservative floor from raw facts
    and environment. Adapter-declared Exposure is optional and may only raise that floor.
    The function computes the minimum gate but deliberately does not authenticate an
    approval issuer or protected-override authority.
    """
    catalog = operation_catalog(contract)
    cfg = contract.get("execution_boundary", {})
    errors: list[str] = []
    warnings: list[str] = []

    planned = [str(x).strip() for x in planned_operations if str(x).strip()]
    actual = [str(x).strip() for x in actual_operations if str(x).strip()]
    resource_list = [str(x) for x in resources]
    target_list = [str(x) for x in targets]
    correlation = str(correlation_id).strip()
    if not correlation:
        errors.append("correlation_id must be a non-empty string at the execution boundary")
    nonce = str(execution_nonce).strip()
    if len(nonce) < 16:
        errors.append("execution_nonce must be a caller/runtime-issued single-use string of at least 16 characters")

    unknown_planned = sorted(set(planned) - set(catalog))
    unknown_actual = sorted(set(actual) - set(catalog))
    if unknown_planned:
        errors.append("planned_operations must be canonical at execution boundary; unknown: " + ", ".join(unknown_planned))
    if unknown_actual:
        errors.append("actual_operations must be canonical runtime assertions; unknown: " + ", ".join(unknown_actual))
    if not actual:
        errors.append("actual_operations must contain at least one canonical operation")
    forbidden_runtime_ops = set(cfg.get("runtime_forbidden_operations", ["command.execute"]))
    forbidden_seen = sorted(set(actual).intersection(forbidden_runtime_ops))
    if forbidden_seen:
        errors.append(
            "runtime actual_operations contains opaque/forbidden operation(s): "
            + ", ".join(forbidden_seen)
            + "; assert semantically specific canonical operation IDs instead"
        )

    unplanned_actual = sorted(set(actual) - set(planned)) if planned else sorted(set(actual))
    if unplanned_actual and cfg.get("actual_operations_must_be_covered_by_plan", True):
        errors.append("actual operation(s) are not covered by the plan: " + ", ".join(unplanned_actual))

    action_hints: list[str] = []
    action_hint_gaps: list[str] = []
    hard_action_hints: list[str] = []
    hard_action_hint_gaps: list[str] = []
    if actual_action.strip():
        if aliases_doc is None:
            aliases_doc = load_routing_aliases(contract)
        action_hints = infer_operations(contract, actual_action, aliases_doc)
        action_hint_gaps = sorted(set(action_hints) - set(actual))
        if action_hint_gaps:
            message = (
                "action text advisory hint implies operation(s) missing from runtime actual_operations: "
                + ", ".join(action_hint_gaps)
            )
            behavior = cfg.get("known_action_hint_mismatch_behavior", "WARN")
            (errors if behavior == "FAIL" else warnings).append(message)
        hard_action_hints = infer_hard_action_operations(actual_action)
        hard_action_hint_gaps = sorted(set(hard_action_hints) - set(actual))
        if hard_action_hint_gaps:
            message = (
                "high-confidence action signature implies operation(s) missing from runtime actual_operations: "
                + ", ".join(hard_action_hint_gaps)
            )
            behavior = cfg.get("hard_action_signature_mismatch_behavior", "FAIL")
            (errors if behavior == "FAIL" else warnings).append(message)

    env = str(environment).strip().casefold()
    known_envs = cfg.get("known_environments", KNOWN_ENVIRONMENTS)
    if env not in known_envs:
        errors.append(f"environment must be one of {known_envs}; got {environment!r}")

    if runtime_effect is not None and runtime_effect not in _EFFECT_RANK:
        errors.append(f"runtime_effect must be one of {sorted(_EFFECT_RANK)}; got {runtime_effect!r}")

    concrete_targets, target_errors = _concrete_targets(target_list)
    errors.extend(target_errors)

    valid_actual = [op for op in actual if op in catalog]
    route = route_policies(contract, "", valid_actual, resource_list, "enforcement", aliases_doc)
    if route["routing_status"] == "FAIL":
        errors.extend(route["errors"])

    floor_values = [catalog[op]["effect_floor"] for op in valid_actual]
    effective_effect = _max_level(floor_values, _EFFECT_RANK)
    escalations: list[str] = []
    production_ops = set(cfg.get("production_effect_escalation_operations", PRODUCTION_EFFECT_ESCALATION_OPERATIONS))
    if env == "production" and production_ops.intersection(valid_actual):
        if effective_effect is None or _EFFECT_RANK[effective_effect] < _EFFECT_RANK["L4"]:
            effective_effect = "L4"
        escalations.append("production environment escalated state-changing operation to L4")
    if runtime_effect in _EFFECT_RANK:
        if effective_effect is None or _EFFECT_RANK[runtime_effect] > _EFFECT_RANK[effective_effect]:
            effective_effect = runtime_effect
            escalations.append(f"runtime_effect raised effective Effect to {runtime_effect}")

    exposure_result = derive_exposure_floor(contract, env, exposure_facts, declared_exposure)
    errors.extend(exposure_result["errors"])
    warnings.extend(exposure_result["warnings"])
    effective_exposure = exposure_result["effective_exposure"]
    for item in exposure_result["contributions"]:
        if effective_exposure == item["floor"] and item["source"] != "environment":
            escalations.append(f"Exposure floor {item['floor']} derived from {item['source']}={item['value']}")

    # Machine-enforced context-sensitive Effect rules. A canonical operation may have
    # a lower general floor but become L4 when its runtime destination is public.
    context_rules = cfg.get("context_effect_escalation_rules", CONTEXT_EFFECT_ESCALATION_RULES)
    normalized_facts_for_rules = exposure_result.get("facts", {})
    for rule in context_rules:
        if not set(rule.get("operations", [])).intersection(valid_actual):
            continue
        matched = False
        for matcher in rule.get("match_any", []):
            source = matcher.get("source")
            values = set(matcher.get("values", []))
            if source == "environment":
                value = env
            elif isinstance(source, str) and source.startswith("exposure_facts."):
                value = normalized_facts_for_rules.get(source.split(".", 1)[1])
            else:
                errors.append(f"unsupported context effect matcher source: {source!r}")
                continue
            if value in values:
                matched = True
                break
        effect = rule.get("effect")
        if matched:
            if effect not in _EFFECT_RANK:
                errors.append(f"context effect rule {rule.get('id')!r} has invalid effect {effect!r}")
            else:
                if effective_effect is None or _EFFECT_RANK[effect] > _EFFECT_RANK[effective_effect]:
                    effective_effect = effect
                escalations.append(f"context rule {rule.get('id')} escalated Effect to {effect}")

    target_required = set(cfg.get("target_required_effect_levels", TARGET_REQUIRED_EFFECT_LEVELS))
    target_exposure_required = set(cfg.get("target_required_exposure_levels", TARGET_REQUIRED_EXPOSURE_LEVELS))
    if effective_effect in target_required and not concrete_targets:
        errors.append(f"at least one concrete target is required for effective Effect {effective_effect}")
    if effective_exposure in target_exposure_required and not concrete_targets:
        errors.append(f"at least one concrete target is required for effective Exposure {effective_exposure}")

    gate = None
    decision = "BLOCK_POLICY_ERROR"
    if not errors and effective_effect and effective_exposure:
        gate = contract["risk_model"]["decision_matrix"][effective_effect][effective_exposure]
        decision = {
            "AUTO": "ALLOW",
            "AUTO_WITH_GUARDS": "ALLOW_WITH_GUARDS",
            "REQUIRE_EXPLICIT_APPROVAL": "BLOCK_APPROVAL_REQUIRED",
            "PROHIBITED_WITHOUT_OVERRIDE": "BLOCK_OVERRIDE_REQUIRED",
        }[gate]

    normalized_exposure_facts = exposure_result["facts"]
    action_digest = None
    if correlation and not exposure_result["errors"]:
        action_digest = compute_action_digest(
            policy_schema_version=contract.get("schema_version"),
            policy_contract_digest=canonical_policy_contract_digest(contract),
            adapter=adapter,
            correlation_id=correlation,
            execution_nonce=nonce,
            planned_operations=planned,
            actual_operations=actual,
            affected_resources=resource_list,
            targets=concrete_targets,
            environment=env,
            exposure_facts=normalized_exposure_facts,
            declared_exposure=declared_exposure,
            runtime_effect=runtime_effect,
            actual_action=actual_action,
            semantic_details=semantic_details,
        )

    return {
        "status": "FAIL" if errors else "PASS",
        "decision": decision,
        "correlation_id": correlation,
        "execution_nonce": nonce,
        "action_digest": action_digest,
        "policy_contract_digest": canonical_policy_contract_digest(contract),
        "planned_operations": planned,
        "actual_operations": actual,
        "unplanned_actual_operations": unplanned_actual,
        "actual_action": actual_action,
        "adapter": adapter or {},
        "semantic_details": semantic_details or {},
        "action_hints": action_hints,
        "action_hint_gaps": action_hint_gaps,
        "hard_action_hints": hard_action_hints,
        "hard_action_hint_gaps": hard_action_hint_gaps,
        "policies": route["policies"],
        "resources": resource_list,
        "targets": concrete_targets,
        "environment": env,
        "exposure_facts": normalized_exposure_facts,
        "exposure_contributions": exposure_result["contributions"],
        "declared_exposure": declared_exposure,
        "derived_exposure": exposure_result["derived_exposure"],
        "runtime_effect": runtime_effect,
        "effective_effect": effective_effect,
        "effective_exposure": effective_exposure,
        "action_gate": gate,
        "escalations": list(dict.fromkeys(escalations)),
        "approval": "NOT_ESTABLISHED",
        "protected_override_authorization": "NOT_ESTABLISHED",
        "errors": errors,
        "warnings": warnings,
    }


def validate_runtime_action(path: Path, contract: dict, root: Path = ROOT) -> dict:
    """Validate a structured runtime-adapter assertion and evaluate its action boundary.

    Schema validity does not authenticate the adapter. The higher-authority runtime must
    authenticate producer identity/transport before treating facts as trustworthy.
    """
    cfg = contract.get("execution_boundary", {})
    schema_name = cfg.get("runtime_action_schema", "RUNTIME_ACTION.schema.json")
    try:
        payload = load_json(path)
    except Exception as exc:
        return {"status": "FAIL", "schema_status": "FAIL", "adapter_trust": "UNVERIFIED", "errors": [str(exc)]}
    try:
        schema = load_json(root / schema_name)
    except Exception as exc:
        return {"status": "FAIL", "schema_status": "FAIL", "adapter_trust": "UNVERIFIED", "errors": [f"runtime action schema: {exc}"]}
    if jsonschema is None:
        return {"status": "FAIL", "schema_status": "FAIL", "adapter_trust": "UNVERIFIED", "errors": ["install dependencies: pip install -r requirements.txt"]}
    try:
        jsonschema.validate(payload, schema)
    except Exception as exc:
        return {"status": "FAIL", "schema_status": "FAIL", "adapter_trust": "UNVERIFIED", "errors": [str(exc)]}

    adapter = payload["adapter"]
    action = payload["action"]
    source = adapter["assertion_source"]
    trusted_sources = cfg.get("trusted_assertion_sources", [])
    errors: list[str] = []
    if source not in trusted_sources:
        errors.append(f"assertion_source is not allowed by contract: {source}")
    boundary = evaluate_execution_boundary(
        contract,
        action["planned_operations"],
        action["actual_operations"],
        action.get("affected_resources", []),
        action.get("targets", []),
        action["environment"],
        action.get("declared_exposure"),
        action.get("runtime_effect"),
        action.get("actual_action", ""),
        exposure_facts=action["exposure_facts"],
        correlation_id=action["correlation_id"],
        execution_nonce=action["execution_nonce"],
        adapter=adapter,
        semantic_details=action.get("semantic_details", {}),
    )
    errors.extend(boundary["errors"])
    return {
        "status": "FAIL" if errors else "PASS",
        "schema_status": "PASS",
        "adapter": adapter,
        "adapter_trust": "UNVERIFIED",
        "assertion_source_claim": source,
        "authorization": "NOT_ESTABLISHED",
        "boundary": boundary,
        "errors": errors,
        "warnings": [
            "schema validity does not authenticate the adapter; verify producer identity and transport in the higher-authority runtime"
        ] + boundary.get("warnings", []),
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_trust_manifest(root: Path = ROOT) -> dict:
    contract = load_json(root / "POLICY_CONTRACT.json")
    cfg = contract.get("integrity", {})
    files = cfg.get("trusted_core_files", TRUSTED_CORE_FILES)
    missing = [rel for rel in files if not (root / rel).is_file()]
    if missing:
        raise ValueError("cannot build trust manifest; missing core file(s): " + ", ".join(missing))
    return {
        "format": TRUST_MANIFEST_FORMAT,
        "project_name": CANONICAL_ROOT,
        "schema_version": contract.get("schema_version"),
        "policy_contract_sha256": sha256_file(root / "POLICY_CONTRACT.json"),
        "algorithm": "sha256",
        "files": {rel: sha256_file(root / rel) for rel in files},
    }


def write_trust_manifest(path: Path, root: Path = ROOT) -> dict:
    manifest = build_trust_manifest(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def verify_trust_manifest(path: Path, root: Path = ROOT) -> dict:
    errors: list[str] = []
    try:
        manifest = load_json(path)
    except Exception as exc:
        return {"status": "FAIL", "errors": [f"trust manifest parse error: {exc}"], "checked_files": []}
    if not isinstance(manifest, dict):
        return {"status": "FAIL", "errors": ["trust manifest must be a JSON object"], "checked_files": []}

    if manifest.get("format") != TRUST_MANIFEST_FORMAT:
        errors.append(f"unsupported trust manifest format: {manifest.get('format')!r}")
    if manifest.get("project_name") != CANONICAL_ROOT:
        errors.append(f"trust manifest project_name mismatch: {manifest.get('project_name')!r}")
    if manifest.get("algorithm") != "sha256":
        errors.append(f"unsupported trust manifest algorithm: {manifest.get('algorithm')!r}")

    try:
        contract = load_json(root / "POLICY_CONTRACT.json")
    except Exception as exc:
        errors.append(f"cannot read bundle contract: {exc}")
        contract = {}
    expected_contract_hash = sha256_file(root / "POLICY_CONTRACT.json") if (root / "POLICY_CONTRACT.json").is_file() else None
    if manifest.get("policy_contract_sha256") != expected_contract_hash:
        errors.append("trust manifest policy_contract_sha256 does not match POLICY_CONTRACT.json")
    if manifest.get("schema_version") != contract.get("schema_version"):
        errors.append(
            f"schema_version mismatch: manifest={manifest.get('schema_version')!r}, bundle={contract.get('schema_version')!r}"
        )

    expected_files = contract.get("integrity", {}).get("trusted_core_files", TRUSTED_CORE_FILES)
    declared = manifest.get("files")
    if not isinstance(declared, dict):
        errors.append("trust manifest files must be an object")
        declared = {}
    if set(declared) != set(expected_files):
        errors.append(
            "trust manifest file set mismatch: "
            f"missing={sorted(set(expected_files)-set(declared))}, extra={sorted(set(declared)-set(expected_files))}"
        )

    checked_files: list[str] = []
    for rel in expected_files:
        expected = declared.get(rel)
        target = root / rel
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            errors.append(f"invalid sha256 for {rel}")
            continue
        if not target.is_file():
            errors.append(f"missing trusted core file: {rel}")
            continue
        actual = sha256_file(target)
        checked_files.append(rel)
        if actual != expected:
            errors.append(f"sha256 mismatch: {rel}")

    return {"status": "FAIL" if errors else "PASS", "errors": errors, "checked_files": checked_files}


def build_release_manifest(artifact_path: Path, root: Path = ROOT) -> dict:
    """Build a full-release integrity manifest covering every distributed file and ZIP bytes.

    This is intentionally distinct from the trusted-core manifest. It proves release
    completeness/integrity when obtained through a trusted channel, but it does not by
    itself authenticate the publisher.
    """
    contract = load_json(root / "POLICY_CONTRACT.json")
    files = list(contract.get("distribution", {}).get("required_files", []))
    missing = [rel for rel in files if not (root / rel).is_file()]
    if missing:
        raise ValueError("cannot build release manifest; missing distribution file(s): " + ", ".join(missing))
    if not (artifact_path.is_file() and zipfile.is_zipfile(artifact_path)):
        raise ValueError("release manifest requires the canonical ZIP artifact")
    return {
        "format": RELEASE_MANIFEST_FORMAT,
        "project_name": CANONICAL_ROOT,
        "schema_version": contract.get("schema_version"),
        "policy_contract_sha256": sha256_file(root / "POLICY_CONTRACT.json"),
        "algorithm": "sha256",
        "artifact": {
            "name": artifact_path.name,
            "sha256": sha256_file(artifact_path),
        },
        "files": {rel: sha256_file(root / rel) for rel in files},
    }


def write_release_manifest(path: Path, artifact_path: Path, root: Path = ROOT) -> dict:
    manifest = build_release_manifest(artifact_path, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def verify_release_manifest(path: Path, artifact_path: Path, contract: dict | None = None) -> dict:
    errors: list[str] = []
    warnings = [
        "release manifest integrity is not publisher authentication; obtain it through a trusted channel or verify an external signature"
    ]
    try:
        manifest = load_json(path)
    except Exception as exc:
        return {"status": "FAIL", "errors": [f"release manifest parse error: {exc}"], "warnings": warnings, "checked_files": []}
    if not isinstance(manifest, dict):
        return {"status": "FAIL", "errors": ["release manifest must be a JSON object"], "warnings": warnings, "checked_files": []}
    if contract is None:
        try:
            contract = load_json(CONTRACT_PATH)
        except Exception as exc:
            return {"status": "FAIL", "errors": [f"cannot load contract: {exc}"], "warnings": warnings, "checked_files": []}

    if manifest.get("format") != RELEASE_MANIFEST_FORMAT:
        errors.append(f"unsupported release manifest format: {manifest.get('format')!r}")
    if manifest.get("project_name") != contract.get("project_name"):
        errors.append(f"release manifest project_name mismatch: {manifest.get('project_name')!r}")
    if manifest.get("schema_version") != contract.get("schema_version"):
        errors.append("release manifest schema_version does not match contract")
    if manifest.get("algorithm") != "sha256":
        errors.append(f"unsupported release manifest algorithm: {manifest.get('algorithm')!r}")

    artifact = manifest.get("artifact") if isinstance(manifest.get("artifact"), dict) else {}
    expected_artifact_hash = artifact.get("sha256")
    if not isinstance(expected_artifact_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_artifact_hash):
        errors.append("release manifest artifact.sha256 must be a lowercase SHA-256 hex digest")
    elif not artifact_path.is_file():
        errors.append(f"release artifact does not exist: {artifact_path}")
    elif sha256_file(artifact_path) != expected_artifact_hash:
        errors.append("release artifact SHA-256 mismatch")
    if artifact.get("name") != artifact_path.name:
        errors.append(f"release artifact name mismatch: manifest={artifact.get('name')!r}, actual={artifact_path.name!r}")

    expected_files = list(contract.get("distribution", {}).get("required_files", []))
    declared = manifest.get("files")
    if not isinstance(declared, dict):
        errors.append("release manifest files must be an object")
        declared = {}
    if set(declared) != set(expected_files):
        errors.append(
            "release manifest file set mismatch: "
            f"missing={sorted(set(expected_files)-set(declared))}, extra={sorted(set(declared)-set(expected_files))}"
        )
    declared_contract_hash = declared.get("POLICY_CONTRACT.json")
    if manifest.get("policy_contract_sha256") != declared_contract_hash:
        errors.append("release manifest policy_contract_sha256 does not match the declared POLICY_CONTRACT.json digest")

    checked: list[str] = []
    if artifact_path.is_file() and zipfile.is_zipfile(artifact_path):
        root_prefix = str(contract.get("distribution", {}).get("canonical_root", CANONICAL_ROOT)).rstrip("/") + "/"
        with zipfile.ZipFile(artifact_path) as zf:
            infos: dict[str, list[zipfile.ZipInfo]] = {}
            for info in zf.infolist():
                if info.is_dir() or not info.filename.startswith(root_prefix):
                    continue
                rel = info.filename[len(root_prefix):]
                infos.setdefault(rel, []).append(info)
            for rel in expected_files:
                expected = declared.get(rel)
                if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
                    errors.append(f"invalid SHA-256 for release file {rel}")
                    continue
                matches = infos.get(rel, [])
                if len(matches) != 1:
                    errors.append(f"release file {rel} must appear exactly once in ZIP; found {len(matches)}")
                    continue
                actual = hashlib.sha256(zf.read(matches[0])).hexdigest()
                checked.append(rel)
                if actual != expected:
                    errors.append(f"release file SHA-256 mismatch: {rel}")
    else:
        errors.append("release manifest verification requires a ZIP artifact")

    return {"status": "FAIL" if errors else "PASS", "errors": errors, "warnings": warnings, "checked_files": checked}


def extract_policy_sections(
    contract: dict,
    policy_ids: Iterable[str],
    path: Path = POLICIES_PATH,
) -> dict[str, str]:
    """Return complete primary-owner Markdown sections for requested policy IDs."""
    catalog = {item["id"]: item for item in contract.get("policies", [])}
    requested = list(dict.fromkeys(str(x).strip() for x in policy_ids if str(x).strip()))
    unknown = [x for x in requested if x not in catalog]
    if unknown:
        raise ValueError("unknown policy id(s): " + ", ".join(unknown))
    text = path.read_text(encoding="utf-8")
    sections: dict[str, str] = {}
    for policy_id in requested:
        anchor = catalog[policy_id]["anchor"]
        token = f'<a id="{anchor}"></a>'
        start = text.find(token)
        if start < 0:
            raise ValueError(f"missing policy anchor: {anchor}")
        next_match = re.search(r'\n<a id="policy-[a-z0-9-]+"></a>', text[start + len(token):])
        end = len(text) if next_match is None else start + len(token) + next_match.start()
        sections[policy_id] = text[start:end].strip()
    return sections


def validate_project_facts_shape(data: object) -> list[str]:
    """Validate PROJECT.md's machine block defensively without assuming nested types."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["project facts root must be a JSON object"]

    profile = data.get("profile")
    if not isinstance(profile, str) or not profile.strip():
        errors.append("profile must be a non-empty string")

    facts = data.get("facts")
    if not isinstance(facts, dict):
        errors.append("facts must be an object")
    else:
        for key in PROJECT_FACT_KEYS:
            if key not in facts:
                errors.append(f"facts.{key} is required")
        for key, item in facts.items():
            if not isinstance(item, dict):
                errors.append(f"facts.{key} must be an object")
                continue
            for field in ("value", "status", "evidence"):
                if field not in item:
                    errors.append(f"facts.{key}.{field} is required")
            value = item.get("value")
            status = item.get("status")
            evidence = item.get("evidence")
            if value is not None and not isinstance(value, str):
                errors.append(f"facts.{key}.value must be a string")
            if status not in PROJECT_FACT_STATUSES:
                errors.append(f"facts.{key}.status must be one of {sorted(PROJECT_FACT_STATUSES)}")
            if evidence is not None and not isinstance(evidence, str):
                errors.append(f"facts.{key}.evidence must be a string")

    components = data.get("components")
    if not isinstance(components, list):
        errors.append("components must be an array")
    else:
        for idx, component in enumerate(components):
            if not isinstance(component, dict):
                errors.append(f"components[{idx}] must be an object")
                continue
            for field in ("name", "path", "responsibility"):
                value = component.get(field)
                if not isinstance(value, str):
                    errors.append(f"components[{idx}].{field} must be a string")
            component_facts = component.get("facts")
            if component_facts is not None:
                if not isinstance(component_facts, dict):
                    errors.append(f"components[{idx}].facts must be an object")
                else:
                    allowed_component_facts = {"build_command", "test_command", "runtime", "deploy_command", "deploy_target"}
                    for key, item in component_facts.items():
                        if key not in allowed_component_facts:
                            errors.append(f"components[{idx}].facts.{key} is not supported")
                            continue
                        if not isinstance(item, dict):
                            errors.append(f"components[{idx}].facts.{key} must be an object")
                            continue
                        for field in ("value", "status", "evidence"):
                            if field not in item:
                                errors.append(f"components[{idx}].facts.{key}.{field} is required")
                        if item.get("value") is not None and not isinstance(item.get("value"), str):
                            errors.append(f"components[{idx}].facts.{key}.value must be a string")
                        if item.get("status") not in PROJECT_FACT_STATUSES:
                            errors.append(f"components[{idx}].facts.{key}.status must be one of {sorted(PROJECT_FACT_STATUSES)}")
                        if item.get("evidence") is not None and not isinstance(item.get("evidence"), str):
                            errors.append(f"components[{idx}].facts.{key}.evidence must be a string")

    review = data.get("review")
    if not isinstance(review, dict):
        errors.append("review must be an object")
    else:
        for field in ("reviewed_revision", "reviewed_at"):
            value = review.get(field)
            if not isinstance(value, str):
                errors.append(f"review.{field} must be a string")
        reviewed_paths = review.get("reviewed_paths", [])
        if not isinstance(reviewed_paths, list) or any(not isinstance(x, str) or not x.strip() for x in reviewed_paths):
            errors.append("review.reviewed_paths must be an array of non-empty strings when provided")
    return errors


def _reviewed_at_timestamp(value: str) -> tuple[datetime | None, str | None]:
    raw = value.strip()
    if not raw:
        return None, "reviewed_at is missing"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        try:
            parsed = datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
            return parsed, None
        except ValueError:
            return None, "reviewed_at must be a valid ISO-8601 date or timezone-aware datetime"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None, "reviewed_at must be a valid ISO-8601 date or timezone-aware datetime"
    if parsed.tzinfo is None:
        return None, "reviewed_at datetime must include timezone"
    return parsed.astimezone(timezone.utc), None


def _readiness_structure_failure(mode: str, errors: list[str]) -> dict:
    detail = "; ".join(errors)
    check = asdict(Check("project_facts_structure", "FAIL", detail))
    return {
        "mode": mode,
        "documented": "FAIL",
        "evidence_verified": "FAIL",
        "execution_verified": "NOT_RUN",
        "verified": "FAIL",
        "documented_checks": [check],
        "verified_checks": [check],
        "warnings": [],
        "errors": errors,
    }


def parse_project_facts(path: Path = PROJECT_PATH) -> dict:
    text = path.read_text(encoding="utf-8")
    if PROJECT_START not in text or PROJECT_END not in text:
        raise ValueError("PROJECT.md project-facts markers are missing")
    body = text.split(PROJECT_START, 1)[1].split(PROJECT_END, 1)[0]
    match = re.search(r"```json\s*(.*?)\s*```", body, flags=re.DOTALL)
    if not match:
        raise ValueError("PROJECT.md project-facts JSON block is missing")
    return json.loads(match.group(1))


def path_from_value(project_root: Path, value: str) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else (project_root / p)


def git_head(project_root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
        return out.stdout.strip()
    except Exception:
        return None


def _command_literal_is_active(target: Path, content: str, literal: str) -> tuple[bool, str]:
    """Best-effort source-aware command check.

    It deliberately does not claim that a command will execute successfully. The goal
    is narrower: avoid treating a comment-only occurrence as command-source evidence.
    """
    wanted = _normalized_value(literal)
    name = target.name.casefold()
    if name == "package.json":
        try:
            doc = json.loads(content)
        except Exception as exc:
            return False, f"package.json parse failed: {exc}"
        scripts = doc.get("scripts") if isinstance(doc, dict) else None
        if not isinstance(scripts, dict):
            return False, "package.json has no scripts object"
        values = [value for value in scripts.values() if isinstance(value, str)]
        if any(wanted == _normalized_value(value) for value in values):
            return True, "matched package.json scripts value"
        return False, "literal was not an exact package.json scripts value"

    lines = content.splitlines()
    active_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", "//", ";", "<!--")):
            continue
        active_lines.append(line)
    for line in active_lines:
        if wanted in _normalized_value(line):
            if name in {"makefile", "gnumakefile"} or name.endswith(".mk"):
                return True, "matched non-comment Makefile line"
            return True, "matched non-comment source line"
    return False, "literal appears only in comments or is absent"


def git_reviewed_paths_unchanged(project_root: Path, reviewed_revision: str, paths: Iterable[str]) -> tuple[bool | None, str]:
    path_list = [str(x).strip() for x in paths if str(x).strip()]
    if not path_list:
        return None, "no reviewed_paths configured"
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_root), "diff", "--quiet", reviewed_revision, "HEAD", "--", *path_list],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        return None, f"git diff failed: {exc}"
    if proc.returncode == 0:
        return True, "reviewed paths are unchanged since documented revision"
    if proc.returncode == 1:
        return False, "reviewed paths changed since documented revision"
    return None, proc.stderr.strip() or f"git diff returned {proc.returncode}"


def _read_text_evidence(project_root: Path, payload: str, kind: str) -> tuple[str, str, str | None]:
    if "::" not in payload:
        return "FAIL", f"{kind} evidence must be {kind}:<path>::<literal>", None
    file_part, literal = payload.split("::", 1)
    target = path_from_value(project_root, file_part.strip())
    if not target.is_file():
        return "FAIL", f"missing evidence file: {target}", None
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "MANUAL", f"binary/non-UTF8 evidence file: {target}", None
    if kind == "command-source":
        active, active_detail = _command_literal_is_active(target, content, literal)
        if not active:
            return "FAIL", f"command literal is not active in {target}: {literal!r}; {active_detail}", None
        return "PASS", f"command literal verified in active source {target}: {active_detail}", literal
    if literal not in content:
        return "FAIL", f"literal not found in {target}: {literal!r}", None
    return "PASS", f"literal found in {target}", literal


def verify_evidence(project_root: Path, evidence: str) -> tuple[str, str]:
    """Verify a standalone evidence reference without claiming semantic linkage to a fact."""
    evidence = (evidence or "").strip()
    if not evidence:
        return "FAIL", "evidence is empty"
    if evidence.startswith("manual:"):
        return "MANUAL", evidence[7:].strip() or "manual verification required"
    if evidence.startswith("path:"):
        target = path_from_value(project_root, evidence[5:].strip())
        return ("PASS", str(target)) if target.exists() else ("FAIL", f"missing path: {target}")
    for kind in ("contains", "command-source", "value-source"):
        prefix = kind + ":"
        if evidence.startswith(prefix):
            status, detail, _ = _read_text_evidence(project_root, evidence[len(prefix):], kind)
            return status, detail
    if evidence == "git:HEAD":
        return "MANUAL", "use reviewed_revision comparison instead of evidence=git:HEAD"
    return "MANUAL", "untyped evidence is not auto-verified; use path:, command-source:, value-source:, contains:, or manual:"


def _same_resolved_path(a: Path, b: Path) -> bool:
    try:
        return a.resolve(strict=False) == b.resolve(strict=False)
    except OSError:
        return False


def _normalized_value(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).strip()).casefold()


def verify_fact_evidence(project_root: Path, key: str, value: str, evidence: str) -> tuple[str, str]:
    """Verify evidence using fact-specific evidence types and semantic linkage."""
    evidence = (evidence or "").strip()
    if evidence.startswith("manual:"):
        return "MANUAL", evidence[7:].strip() or "manual verification required"

    if key in {"repository_root", "primary_source"}:
        if not evidence.startswith("path:"):
            return "FAIL", f"{key} requires path:<path> evidence for automatic verification"
        value_path = path_from_value(project_root, value)
        evidence_path = path_from_value(project_root, evidence[5:].strip())
        if not evidence_path.exists():
            return "FAIL", f"missing evidence path: {evidence_path}"
        if not value_path.exists():
            return "FAIL", f"fact path does not exist: {value_path}"
        if not _same_resolved_path(value_path, evidence_path):
            return "FAIL", f"evidence path does not identify fact value: value={value_path}, evidence={evidence_path}"
        return "PASS", str(value_path.resolve(strict=False))

    if key in {"build_command", "test_command", "deploy_command"}:
        prefix = "command-source:"
        if not evidence.startswith(prefix):
            return "FAIL", f"{key} requires command-source:<path>::<literal> or manual: evidence"
        status, detail, literal = _read_text_evidence(project_root, evidence[len(prefix):], "command-source")
        if status != "PASS":
            return status, detail
        if _normalized_value(literal or "") != _normalized_value(value):
            return "FAIL", f"command-source literal does not equal documented {key} value"
        return "PASS", detail

    if key in {"runtime", "deploy_target"}:
        prefix = "value-source:"
        if not evidence.startswith(prefix):
            return "FAIL", f"{key} requires value-source:<path>::<literal> or manual: evidence"
        status, detail, literal = _read_text_evidence(project_root, evidence[len(prefix):], "value-source")
        if status != "PASS":
            return status, detail
        if _normalized_value(literal or "") != _normalized_value(value):
            return "FAIL", f"value-source literal does not equal documented {key} value"
        return "PASS", detail

    return verify_evidence(project_root, evidence)


def readiness(project_path: Path = PROJECT_PATH, mode: str = "development") -> dict:
    try:
        facts_doc = parse_project_facts(project_path)
    except Exception as exc:
        return _readiness_structure_failure(mode, [f"PROJECT.md parse error: {exc}"])

    shape_errors = validate_project_facts_shape(facts_doc)
    if shape_errors:
        return _readiness_structure_failure(mode, shape_errors)

    project_root = project_path.parent
    facts = facts_doc["facts"]
    required = ["repository_root", "primary_source", "build_command", "test_command", "runtime"]
    if mode == "deployment":
        required += ["deploy_command", "deploy_target"]

    documented: list[Check] = []
    verified: list[Check] = []
    warnings: list[str] = []

    if facts_doc.get("profile") == "template":
        documented.append(Check("profile", "FAIL", "profile is still template"))
    else:
        documented.append(Check("profile", "PASS", str(facts_doc.get("profile"))))

    for key in required:
        item = facts[key]
        value = item["value"].strip()
        status = item["status"]
        evidence = item["evidence"].strip()
        if status == "N/A":
            ok = bool(evidence)
            documented.append(Check(key, "PASS" if ok else "FAIL", "N/A" if ok else "N/A requires reason/evidence"))
            verified.append(Check(key, "MANUAL", "N/A rationale is a human claim"))
            continue
        doc_ok = status == "Confirmed" and bool(value) and bool(evidence)
        documented.append(Check(key, "PASS" if doc_ok else "FAIL", f"status={status!r}, value={value!r}, evidence={evidence!r}"))
        if not doc_ok:
            verified.append(Check(key, "FAIL", "not documented as Confirmed with value and evidence"))
            continue
        result_status, detail = verify_fact_evidence(project_root, key, value, evidence)
        verified.append(Check(key, result_status, detail))

    components = facts_doc["components"]
    if components:
        documented.append(Check("components", "PASS", f"{len(components)} component(s)"))
        component_failures = []
        for idx, component in enumerate(components):
            component_path = component["path"].strip()
            if not component_path or not path_from_value(project_root, component_path).exists():
                component_failures.append(component_path or "<missing path>")
            for key, item in component.get("facts", {}).items():
                value = item["value"].strip()
                status = item["status"]
                evidence = item["evidence"].strip()
                check_name = f"components[{idx}].{key}"
                if status == "N/A":
                    documented.append(Check(check_name, "PASS" if evidence else "FAIL", "N/A" if evidence else "N/A requires reason/evidence"))
                    verified.append(Check(check_name, "MANUAL", "N/A rationale is a human claim"))
                    continue
                doc_ok = status == "Confirmed" and bool(value) and bool(evidence)
                documented.append(Check(check_name, "PASS" if doc_ok else "FAIL", f"status={status!r}, value={value!r}, evidence={evidence!r}"))
                if doc_ok:
                    result_status, detail = verify_fact_evidence(project_root, key, value, evidence)
                    verified.append(Check(check_name, result_status, detail))
                else:
                    verified.append(Check(check_name, "FAIL", "not documented as Confirmed with value and evidence"))
        verified.append(Check("components", "PASS" if not component_failures else "FAIL", ", ".join(component_failures) if component_failures else "all component paths exist"))
    else:
        documented.append(Check("components", "FAIL", "at least one component is required"))
        verified.append(Check("components", "FAIL", "no components to verify"))

    review = facts_doc["review"]
    reviewed = review["reviewed_revision"].strip()
    reviewed_paths = [str(x).strip() for x in review.get("reviewed_paths", []) if str(x).strip()]
    if reviewed_paths:
        documented.append(Check("reviewed_paths", "PASS", ", ".join(reviewed_paths)))
    if reviewed:
        documented.append(Check("reviewed_revision", "PASS", reviewed))
        head = git_head(project_root)
        if head is None:
            verified.append(Check("reviewed_revision", "MANUAL", "project root is not a Git repository or Git is unavailable"))
        elif reviewed == head:
            verified.append(Check("reviewed_revision", "PASS", f"documented revision equals HEAD={head}"))
        elif reviewed_paths:
            unchanged, detail = git_reviewed_paths_unchanged(project_root, reviewed, reviewed_paths)
            if unchanged is True:
                verified.append(Check("reviewed_revision", "PASS", f"documented={reviewed}, HEAD={head}; {detail}"))
            elif unchanged is False:
                verified.append(Check("reviewed_revision", "FAIL", f"documented={reviewed}, HEAD={head}; {detail}"))
            else:
                verified.append(Check("reviewed_revision", "MANUAL", f"documented={reviewed}, HEAD={head}; {detail}"))
        else:
            verified.append(Check("reviewed_revision", "FAIL", f"documented={reviewed}, HEAD={head}; configure reviewed_paths to permit unrelated HEAD changes"))
    else:
        documented.append(Check("reviewed_revision", "FAIL", "missing"))
        verified.append(Check("reviewed_revision", "FAIL", "missing"))

    reviewed_at_raw = review["reviewed_at"].strip()
    reviewed_at, reviewed_at_error = _reviewed_at_timestamp(reviewed_at_raw)
    if reviewed_at_error:
        documented.append(Check("reviewed_at", "FAIL", reviewed_at_error))
        verified.append(Check("reviewed_at", "FAIL", reviewed_at_error))
    else:
        assert reviewed_at is not None
        documented.append(Check("reviewed_at", "PASS", reviewed_at_raw))
        today = datetime.now(timezone.utc).date()
        if reviewed_at.date() > today:
            verified.append(Check("reviewed_at", "FAIL", f"reviewed_at is in the future: {reviewed_at_raw}"))
        else:
            age_days = (today - reviewed_at.date()).days
            verified.append(Check("reviewed_at", "PASS", f"review age={age_days} day(s)"))
            if age_days > REVIEW_FRESHNESS_DAYS:
                warnings.append(
                    f"project facts were last reviewed {age_days} days ago; refresh evidence if project topology or commands may have changed"
                )

    documented_pass = all(x.status == "PASS" for x in documented)
    if not documented_pass:
        verified_state = "FAIL"
    elif any(x.status == "FAIL" for x in verified):
        verified_state = "FAIL"
    elif any(x.status == "MANUAL" for x in verified):
        verified_state = "PARTIAL"
    else:
        verified_state = "PASS"

    return {
        "mode": mode,
        "documented": "PASS" if documented_pass else "FAIL",
        "evidence_verified": verified_state,
        "execution_verified": "NOT_RUN",
        "verified": verified_state,
        "documented_checks": [asdict(x) for x in documented],
        "verified_checks": [asdict(x) for x in verified],
        "warnings": warnings,
        "errors": [],
    }


def extract_internal_links(markdown: str) -> list[str]:
    links = []
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", markdown):
        target = target.strip()
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        links.append(target)
    return links


def validate_internal_links(root: Path) -> list[Check]:
    checks: list[Check] = []
    for md in sorted(root.rglob("*.md")):
        text = md.read_text(encoding="utf-8")
        for target in extract_internal_links(text):
            path_part, _, anchor = target.partition("#")
            dest = (md.parent / path_part).resolve() if path_part else md.resolve()
            if not dest.exists():
                checks.append(Check(f"link:{md.relative_to(root)}", "FAIL", f"missing {target}"))
                continue
            if anchor and dest.suffix.lower() == ".md":
                content = dest.read_text(encoding="utf-8")
                if f'id="{anchor}"' not in content and f"id='{anchor}'" not in content:
                    if anchor.startswith("policy-"):
                        checks.append(Check(f"anchor:{md.relative_to(root)}", "FAIL", f"missing #{anchor} in {dest.relative_to(root)}"))
    if not checks:
        checks.append(Check("internal_links", "PASS", "all checked relative links resolve"))
    return checks


def _candidate_fact(value: str = "", status: str = "Unknown", evidence: str = "") -> dict:
    return {"value": value, "status": status, "evidence": evidence}


def _makefile_recipe(path: Path, target: str) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    in_target = False
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            if in_target and not line.startswith("\t"):
                break
            continue
        if not line.startswith((" ", "\t")) and re.match(rf"^{re.escape(target)}\s*:", line):
            in_target = True
            continue
        if in_target:
            if line.startswith("\t"):
                command = line.strip()
                if command and not command.startswith("#"):
                    return command
            elif not line.startswith(" "):
                break
    return None


def bootstrap_project(repo_root: Path, output: Path | None = None, force: bool = False) -> dict:
    """Generate a conservative PROJECT candidate from observable repository evidence.

    Nothing is promoted to Confirmed. Automatically detected facts remain Inferred so
    readiness cannot become documented-PASS merely because bootstrap ran.
    """
    repo_root = repo_root.resolve()
    if not repo_root.is_dir():
        raise ValueError(f"repository root is not a directory: {repo_root}")
    output = output.resolve() if output is not None else repo_root / "PROJECT.inferred.md"
    if output.exists() and not force:
        raise FileExistsError(f"refusing to overwrite existing bootstrap output: {output}; use --bootstrap-force")

    detected_paths: list[str] = []
    facts = {
        "repository_root": _candidate_fact(".", "Inferred", "path:."),
        "primary_source": _candidate_fact(),
        "build_command": _candidate_fact(),
        "test_command": _candidate_fact(),
        "runtime": _candidate_fact(),
        "deploy_command": _candidate_fact(),
        "deploy_target": _candidate_fact(),
    }

    source_candidates = ["src", "app", "lib", "services", "packages", "apps", "backend", "frontend"]
    for rel in source_candidates:
        if (repo_root / rel).is_dir():
            facts["primary_source"] = _candidate_fact(rel, "Inferred", f"path:{rel}")
            detected_paths.append(rel)
            break

    package_json = repo_root / "package.json"
    if package_json.is_file():
        detected_paths.append("package.json")
        try:
            package = load_json(package_json)
        except Exception:
            package = {}
        scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
        if isinstance(scripts, dict):
            build = scripts.get("build")
            test = scripts.get("test")
            if isinstance(build, str) and build.strip():
                facts["build_command"] = _candidate_fact(build.strip(), "Inferred", f"command-source:package.json::{build.strip()}")
            if isinstance(test, str) and test.strip():
                facts["test_command"] = _candidate_fact(test.strip(), "Inferred", f"command-source:package.json::{test.strip()}")
        engines = package.get("engines", {}) if isinstance(package, dict) else {}
        node = engines.get("node") if isinstance(engines, dict) else None
        if isinstance(node, str) and node.strip():
            facts["runtime"] = _candidate_fact(node.strip(), "Inferred", f"value-source:package.json::{node.strip()}")

    makefile = repo_root / "Makefile"
    if makefile.is_file():
        detected_paths.append("Makefile")
        if facts["build_command"]["status"] == "Unknown":
            cmd = _makefile_recipe(makefile, "build")
            if cmd:
                facts["build_command"] = _candidate_fact(cmd, "Inferred", f"command-source:Makefile::{cmd}")
        if facts["test_command"]["status"] == "Unknown":
            cmd = _makefile_recipe(makefile, "test")
            if cmd:
                facts["test_command"] = _candidate_fact(cmd, "Inferred", f"command-source:Makefile::{cmd}")
        deploy = _makefile_recipe(makefile, "deploy")
        if deploy:
            facts["deploy_command"] = _candidate_fact(deploy, "Inferred", f"command-source:Makefile::{deploy}")

    runtime_sources = [
        (".python-version", lambda text: next((x.strip() for x in text.splitlines() if x.strip()), "")),
        (".tool-versions", lambda text: next((x.strip() for x in text.splitlines() if x.strip()), "")),
    ]
    if facts["runtime"]["status"] == "Unknown":
        for rel, extractor in runtime_sources:
            path = repo_root / rel
            if path.is_file():
                detected_paths.append(rel)
                try:
                    literal = extractor(path.read_text(encoding="utf-8"))
                except Exception:
                    literal = ""
                if literal:
                    facts["runtime"] = _candidate_fact(literal, "Inferred", f"value-source:{rel}::{literal}")
                    break
    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file():
        detected_paths.append("pyproject.toml")
        if facts["runtime"]["status"] == "Unknown":
            try:
                pytext = pyproject.read_text(encoding="utf-8")
            except Exception:
                pytext = ""
            m = re.search(r"^requires-python\s*=\s*['\"]([^'\"]+)['\"]", pytext, flags=re.MULTILINE)
            if m:
                literal = m.group(1).strip()
                facts["runtime"] = _candidate_fact(literal, "Inferred", f"value-source:pyproject.toml::{literal}")

    components: list[dict] = []
    for parent in ["services", "packages", "apps"]:
        base = repo_root / parent
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if child.is_dir() and not child.name.startswith("."):
                rel = str(child.relative_to(repo_root)).replace("\\", "/")
                components.append({
                    "name": child.name,
                    "path": rel,
                    "responsibility": "Inferred component candidate; confirm responsibility and boundaries",
                })
                detected_paths.append(rel)
    if not components and facts["primary_source"]["status"] == "Inferred":
        rel = facts["primary_source"]["value"]
        components.append({
            "name": Path(rel).name or "source",
            "path": rel,
            "responsibility": "Inferred primary source component; confirm responsibility and boundaries",
        })

    reviewed_revision = git_head(repo_root) or ""
    reviewed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    data = {
        "profile": "inferred-bootstrap-candidate",
        "facts": facts,
        "components": components,
        "review": {
            "reviewed_revision": reviewed_revision,
            "reviewed_at": reviewed_at,
            "reviewed_paths": sorted(set(detected_paths)),
        },
    }
    block = json.dumps(data, ensure_ascii=False, indent=2)
    markdown = (
        "# PROJECT.md — inferred bootstrap candidate\n\n"
        "> 이 파일은 repository 관찰로 생성한 **후보**다. 자동 탐색 결과는 `Confirmed`로 승격하지 않는다. "
        "실제 evidence를 검토한 뒤 필요한 fact만 `Confirmed` 또는 근거 있는 `N/A`로 변경한다.\n\n"
        + PROJECT_START + "\n```json\n" + block + "\n```\n" + PROJECT_END
        + "\n\n## Bootstrap notes\n\n"
          "- 생성기는 기존 `PROJECT.md`를 덮어쓰지 않는다.\n"
          "- `Inferred` 상태는 documented readiness를 통과시키지 않는다.\n"
          "- 잘못 추론된 command/runtime/component는 삭제하거나 실제 Source of Truth에 맞게 수정한다.\n"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    return {
        "status": "PASS",
        "repository_root": str(repo_root),
        "output": str(output),
        "profile": data["profile"],
        "inferred_facts": sorted(k for k, v in facts.items() if v["status"] == "Inferred"),
        "unknown_facts": sorted(k for k, v in facts.items() if v["status"] == "Unknown"),
        "components": [x["path"] for x in components],
        "note": "No fact was auto-promoted to Confirmed.",
    }


def parse_policy_matrix(markdown: str) -> dict:
    matrix = {}
    row_re = re.compile(r"^\|\s*(L[1-4])\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*$", re.MULTILINE)
    for m in row_re.finditer(markdown):
        matrix[m.group(1)] = {f"X{i}": m.group(i + 2).strip() for i in range(4)}
    return matrix


def compile_python_sources(root: Path) -> list[Check]:
    checks: list[Check] = []
    failures: list[str] = []
    for source in sorted(root.rglob("*.py")):
        try:
            compile(source.read_text(encoding="utf-8"), str(source), "exec")
        except Exception as exc:
            failures.append(f"{source.relative_to(root)}: {exc}")
    checks.append(Check("python_compile", "PASS" if not failures else "FAIL", "; ".join(failures) if failures else "all Python sources compile"))
    return checks


def bundle_checks(root: Path = ROOT) -> list[Check]:
    checks: list[Check] = []
    missing = []
    for rel in CANONICAL_REQUIRED_FILES:
        ok = (root / rel).is_file()
        checks.append(Check(f"file:{rel}", "PASS" if ok else "FAIL", ""))
        if not ok:
            missing.append(rel)

    contract = None
    schema = None
    aliases_doc = None
    aliases_schema = None
    runtime_action_schema = None
    approval_assertion_schema = None
    protected_override_schema = None
    try:
        contract = load_json(root / "POLICY_CONTRACT.json")
    except Exception as exc:
        checks.append(Check("contract_json", "FAIL", str(exc)))
    try:
        schema = load_json(root / "POLICY_CONTRACT.schema.json")
    except Exception as exc:
        checks.append(Check("schema_json", "FAIL", str(exc)))
    try:
        aliases_doc = load_json(root / "ROUTING_ALIASES.json")
    except Exception as exc:
        checks.append(Check("routing_aliases_json", "FAIL", str(exc)))
    try:
        aliases_schema = load_json(root / "ROUTING_ALIASES.schema.json")
    except Exception as exc:
        checks.append(Check("routing_aliases_schema_json", "FAIL", str(exc)))
    try:
        runtime_action_schema = load_json(root / "RUNTIME_ACTION.schema.json")
    except Exception as exc:
        checks.append(Check("runtime_action_schema_json", "FAIL", str(exc)))
    try:
        approval_assertion_schema = load_json(root / "APPROVAL_ASSERTION.schema.json")
    except Exception as exc:
        checks.append(Check("approval_assertion_schema_json", "FAIL", str(exc)))
    try:
        protected_override_schema = load_json(root / "PROTECTED_OVERRIDE.schema.json")
    except Exception as exc:
        checks.append(Check("protected_override_schema_json", "FAIL", str(exc)))

    if contract is not None and schema is not None:
        if jsonschema is None:
            checks.append(Check("json_schema", "FAIL", "install dependencies: pip install -r requirements.txt"))
        else:
            try:
                jsonschema.Draft202012Validator.check_schema(schema)
                jsonschema.validate(contract, schema)
                checks.append(Check("json_schema", "PASS", "schema and contract validate"))
            except Exception as exc:
                checks.append(Check("json_schema", "FAIL", str(exc)))
            if aliases_doc is not None and aliases_schema is not None:
                try:
                    jsonschema.Draft202012Validator.check_schema(aliases_schema)
                    jsonschema.validate(aliases_doc, aliases_schema)
                    checks.append(Check("routing_aliases_schema", "PASS", "schema and aliases validate"))
                except Exception as exc:
                    checks.append(Check("routing_aliases_schema", "FAIL", str(exc)))
            if runtime_action_schema is not None:
                try:
                    jsonschema.Draft202012Validator.check_schema(runtime_action_schema)
                    checks.append(Check("runtime_action_schema", "PASS", "runtime action schema validates"))
                except Exception as exc:
                    checks.append(Check("runtime_action_schema", "FAIL", str(exc)))
            if approval_assertion_schema is not None:
                try:
                    jsonschema.Draft202012Validator.check_schema(approval_assertion_schema)
                    checks.append(Check("approval_assertion_schema", "PASS", "approval assertion schema validates"))
                except Exception as exc:
                    checks.append(Check("approval_assertion_schema", "FAIL", str(exc)))
            if protected_override_schema is not None:
                try:
                    jsonschema.Draft202012Validator.check_schema(protected_override_schema)
                    checks.append(Check("protected_override_schema", "PASS", "protected override schema validates"))
                except Exception as exc:
                    checks.append(Check("protected_override_schema", "FAIL", str(exc)))

        schema_version = contract.get("schema_version")
        checks.append(Check(
            "supported_schema_version",
            "PASS" if schema_version in SUPPORTED_SCHEMA_VERSIONS else "FAIL",
            f"declared={schema_version!r}, supported={sorted(SUPPORTED_SCHEMA_VERSIONS)}",
        ))
        routing = contract.get("routing") if isinstance(contract.get("routing"), dict) else {}
        normalization = routing.get("normalization")
        checks.append(Check(
            "routing_normalization_implementation_parity",
            "PASS" if normalization == ROUTING_NORMALIZATION_ID else "FAIL",
            f"declared={normalization!r}, implemented={ROUTING_NORMALIZATION_ID!r}",
        ))
        routing_inputs = routing.get("inputs")
        checks.append(Check(
            "routing_inputs_implementation_parity",
            "PASS" if routing_inputs == ROUTING_INPUTS else "FAIL",
            f"declared={routing_inputs!r}, implemented={ROUTING_INPUTS!r}",
        ))
        alias_source = routing.get("alias_source")
        checks.append(Check(
            "routing_alias_source",
            "PASS" if alias_source == "ROUTING_ALIASES.json" else "FAIL",
            f"declared={alias_source!r}",
        ))
        enforcement_mode = routing.get("modes", {}).get("enforcement", {}) if isinstance(routing.get("modes"), dict) else {}
        routing_semantics_ok = (
            routing.get("task_hint_authority") == TASK_HINT_AUTHORITY
            and routing.get("enforcement_requires_resolved_plan") is ENFORCEMENT_REQUIRES_RESOLVED_PLAN
            and enforcement_mode.get("unresolved_operation_behavior") == "FAIL"
            and enforcement_mode.get("unclassified_task_behavior") == "WARN"
            and enforcement_mode.get("task_plan_mismatch_behavior") == "WARN"
        )
        checks.append(Check(
            "routing_semantics_implementation_parity",
            "PASS" if routing_semantics_ok else "FAIL",
            json.dumps({
                "task_hint_authority": routing.get("task_hint_authority"),
                "enforcement_requires_resolved_plan": routing.get("enforcement_requires_resolved_plan"),
                "enforcement": enforcement_mode,
            }, ensure_ascii=False),
        ))
        execution_boundary = contract.get("execution_boundary") if isinstance(contract.get("execution_boundary"), dict) else {}
        checks.append(Check(
            "execution_boundary_inputs_implementation_parity",
            "PASS" if execution_boundary.get("required_inputs") == EXECUTION_BOUNDARY_INPUTS else "FAIL",
            f"declared={execution_boundary.get('required_inputs')!r}, implemented={EXECUTION_BOUNDARY_INPUTS!r}",
        ))
        checks.append(Check(
            "execution_boundary_environments_implementation_parity",
            "PASS" if execution_boundary.get("known_environments") == KNOWN_ENVIRONMENTS else "FAIL",
            f"declared={execution_boundary.get('known_environments')!r}, implemented={KNOWN_ENVIRONMENTS!r}",
        ))
        checks.append(Check(
            "execution_boundary_exposure_floors_implementation_parity",
            "PASS" if execution_boundary.get("environment_exposure_floors") == ENVIRONMENT_EXPOSURE_FLOORS else "FAIL",
            f"declared={execution_boundary.get('environment_exposure_floors')!r}",
        ))
        checks.append(Check(
            "execution_boundary_production_effect_rules_implementation_parity",
            "PASS" if execution_boundary.get("production_effect_escalation_operations") == PRODUCTION_EFFECT_ESCALATION_OPERATIONS else "FAIL",
            f"declared={execution_boundary.get('production_effect_escalation_operations')!r}",
        ))
        checks.append(Check(
            "execution_boundary_target_rules_implementation_parity",
            "PASS" if (execution_boundary.get("target_required_effect_levels") == TARGET_REQUIRED_EFFECT_LEVELS
                       and execution_boundary.get("target_required_exposure_levels") == TARGET_REQUIRED_EXPOSURE_LEVELS) else "FAIL",
            f"effect={execution_boundary.get('target_required_effect_levels')!r}, exposure={execution_boundary.get('target_required_exposure_levels')!r}",
        ))
        runtime_contract_ok = (
            execution_boundary.get("runtime_action_schema") == "RUNTIME_ACTION.schema.json"
            and execution_boundary.get("approval_assertion_schema") == "APPROVAL_ASSERTION.schema.json"
            and execution_boundary.get("structured_adapter_assertion_required") is True
            and execution_boundary.get("trusted_assertion_sources") == ["tool_adapter", "runtime_guard", "human_reviewed"]
            and execution_boundary.get("known_action_hint_mismatch_behavior") == "WARN"
            and execution_boundary.get("hard_action_signature_mismatch_behavior") == "FAIL"
            and execution_boundary.get("runtime_forbidden_operations") == ["command.execute"]
            and execution_boundary.get("runtime_forbidden_operation_behavior") == "FAIL"
            and execution_boundary.get("exposure_derivation") == EXPOSURE_DERIVATION
            and execution_boundary.get("action_digest_format") == ACTION_DIGEST_FORMAT
            and execution_boundary.get("approval_binding_required_for_gate") == "REQUIRE_EXPLICIT_APPROVAL"
            and execution_boundary.get("validator_establishes_approval") is False
        )
        checks.append(Check(
            "runtime_action_contract_implementation_parity",
            "PASS" if runtime_contract_ok else "FAIL",
            json.dumps(execution_boundary, ensure_ascii=False),
        ))
        integrity = contract.get("integrity") if isinstance(contract.get("integrity"), dict) else {}
        integrity_ok = (
            integrity.get("manifest_format") == TRUST_MANIFEST_FORMAT
            and integrity.get("release_manifest_format") == RELEASE_MANIFEST_FORMAT
            and integrity.get("release_manifest_covers") == "full_distribution_and_archive"
            and integrity.get("algorithm") == "sha256"
            and integrity.get("trusted_core_files") == TRUSTED_CORE_FILES
            and integrity.get("manifest_must_be_out_of_band") is True
            and integrity.get("release_manifest_must_be_out_of_band") is True
            and integrity.get("publisher_authenticity_requires_trusted_channel_or_signature") is True
            and integrity.get("self_attestation_is_sufficient") is False
        )
        checks.append(Check(
            "integrity_contract_implementation_parity",
            "PASS" if integrity_ok else "FAIL",
            json.dumps(integrity, ensure_ascii=False),
        ))

        schema_props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        schema_version_rule = schema_props.get("schema_version") if isinstance(schema_props.get("schema_version"), dict) else {}
        routing_rule = schema_props.get("routing") if isinstance(schema_props.get("routing"), dict) else {}
        routing_props = routing_rule.get("properties") if isinstance(routing_rule.get("properties"), dict) else {}
        normalization_rule = routing_props.get("normalization") if isinstance(routing_props.get("normalization"), dict) else {}
        inputs_rule = routing_props.get("inputs") if isinstance(routing_props.get("inputs"), dict) else {}
        execution_rule = schema_props.get("execution_boundary") if isinstance(schema_props.get("execution_boundary"), dict) else {}
        execution_props = execution_rule.get("properties") if isinstance(execution_rule.get("properties"), dict) else {}
        integrity_rule = schema_props.get("integrity") if isinstance(schema_props.get("integrity"), dict) else {}
        integrity_props = integrity_rule.get("properties") if isinstance(integrity_rule.get("properties"), dict) else {}
        expected_schema_version = next(iter(SUPPORTED_SCHEMA_VERSIONS)) if len(SUPPORTED_SCHEMA_VERSIONS) == 1 else None
        checks.append(Check(
            "schema_version_contract_parity",
            "PASS" if schema_version_rule.get("const") == expected_schema_version else "FAIL",
            f"schema const={schema_version_rule.get('const')!r}, expected={expected_schema_version!r}",
        ))
        checks.append(Check(
            "normalization_schema_implementation_parity",
            "PASS" if normalization_rule.get("const") == ROUTING_NORMALIZATION_ID else "FAIL",
            f"schema const={normalization_rule.get('const')!r}, implemented={ROUTING_NORMALIZATION_ID!r}",
        ))
        checks.append(Check(
            "routing_inputs_schema_implementation_parity",
            "PASS" if inputs_rule.get("const") == ROUTING_INPUTS else "FAIL",
            f"schema const={inputs_rule.get('const')!r}, implemented={ROUTING_INPUTS!r}",
        ))
        checks.append(Check(
            "execution_boundary_schema_implementation_parity",
            "PASS" if execution_props.get("required_inputs", {}).get("const") == EXECUTION_BOUNDARY_INPUTS else "FAIL",
            f"schema const={execution_props.get('required_inputs', {}).get('const')!r}",
        ))
        checks.append(Check(
            "integrity_schema_implementation_parity",
            "PASS" if (integrity_props.get("manifest_format", {}).get("const") == TRUST_MANIFEST_FORMAT
                       and integrity_props.get("release_manifest_format", {}).get("const") == RELEASE_MANIFEST_FORMAT
                       and integrity_props.get("algorithm", {}).get("const") == "sha256") else "FAIL",
            f"manifest_format={integrity_props.get('manifest_format', {}).get('const')!r}, release_manifest_format={integrity_props.get('release_manifest_format', {}).get('const')!r}, algorithm={integrity_props.get('algorithm', {}).get('const')!r}",
        ))

        contract_digest = canonical_policy_contract_digest(contract)
        checks.append(Check(
            "policy_contract_digest",
            "PASS" if re.fullmatch(r"sha256:[0-9a-f]{64}", contract_digest) else "FAIL",
            contract_digest,
        ))
        readme_path = root / "README.md"
        canonical_artifact_documented = False
        if readme_path.is_file():
            canonical_artifact_documented = "`universal-agent-docs.zip`" in readme_path.read_text(encoding="utf-8")
        checks.append(Check(
            "canonical_artifact_name_documented",
            "PASS" if canonical_artifact_documented else "FAIL",
            "universal-agent-docs.zip",
        ))

        checks.append(Check("canonical_name", "PASS" if contract.get("project_name") == CANONICAL_ROOT else "FAIL", str(contract.get("project_name"))))
        declared_required = contract.get("distribution", {}).get("required_files", [])
        declared_allowed = contract.get("distribution", {}).get("allowed_files", [])
        checks.append(Check(
            "distribution_manifest_parity",
            "PASS" if declared_required == CANONICAL_REQUIRED_FILES else "FAIL",
            "canonical required file manifest" if declared_required == CANONICAL_REQUIRED_FILES else json.dumps(declared_required, ensure_ascii=False),
        ))
        checks.append(Check(
            "distribution_allowed_manifest_parity",
            "PASS" if declared_allowed == CANONICAL_REQUIRED_FILES else "FAIL",
            "canonical allowed file manifest" if declared_allowed == CANONICAL_REQUIRED_FILES else json.dumps(declared_allowed, ensure_ascii=False),
        ))

    if (root / "AGENTS.md").is_file():
        agents_lines = (root / "AGENTS.md").read_text(encoding="utf-8").splitlines()
        checks.append(Check("root_router_budget", "PASS" if len(agents_lines) <= 150 else "FAIL", f"{len(agents_lines)} lines"))

    if contract is not None and (root / "POLICIES.md").is_file():
        policies_md = (root / "POLICIES.md").read_text(encoding="utf-8")
        ids = [p["id"] for p in contract.get("policies", [])]
        anchors = [p["anchor"] for p in contract.get("policies", [])]
        checks.append(Check("policy_ids_unique", "PASS" if len(ids) == len(set(ids)) else "FAIL", ", ".join(ids)))
        checks.append(Check("policy_anchors_unique", "PASS" if len(anchors) == len(set(anchors)) else "FAIL", ", ".join(anchors)))
        for p in contract.get("policies", []):
            count = policies_md.count(f'id="{p["anchor"]}"')
            checks.append(Check(f"policy_anchor:{p['id']}", "PASS" if count == 1 else "FAIL", f"count={count}"))

        markdown_matrix = parse_policy_matrix(policies_md)
        checks.append(Check("risk_matrix_parity", "PASS" if markdown_matrix == contract["risk_model"]["decision_matrix"] else "FAIL", json.dumps(markdown_matrix, ensure_ascii=False)))

        known = set(ids)
        operations = contract.get("routing", {}).get("operation_catalog", [])
        op_ids = [o["id"] for o in operations]
        checks.append(Check("canonical_operation_ids_unique", "PASS" if len(op_ids) == len(set(op_ids)) else "FAIL", ", ".join(op_ids)))
        lifecycle_cfg = contract.get("operation_lifecycle", {})
        lifecycle_statuses = [o.get("lifecycle_status") for o in operations]
        allowed_statuses = set(lifecycle_cfg.get("allowed_statuses", []))
        lifecycle_bad = [o.get("id") for o in operations if o.get("lifecycle_status") not in allowed_statuses]
        deprecated_bad = [
            o.get("id") for o in operations
            if o.get("lifecycle_status") == "deprecated"
            and (not o.get("replacement_operation") or not o.get("deprecated_since_schema"))
        ]
        lifecycle_contract_ok = (
            lifecycle_cfg.get("canonical_id_is_stable_api") is True
            and lifecycle_cfg.get("rename_strategy") == "ADD_NEW_DEPRECATE_OLD"
            and lifecycle_cfg.get("removal_requires_schema_version_bump") is True
            and lifecycle_cfg.get("semantic_change_requires_schema_version_bump") is True
            and lifecycle_cfg.get("alias_only_change_requires_schema_version_bump") is False
            and lifecycle_cfg.get("deprecated_operation_requires_replacement") is True
            and lifecycle_cfg.get("adapter_must_reject_unknown_operation_ids") is True
        )
        checks.append(Check("operation_lifecycle_contract", "PASS" if lifecycle_contract_ok else "FAIL", json.dumps(lifecycle_cfg, ensure_ascii=False)))
        checks.append(Check("operation_lifecycle_statuses", "PASS" if not lifecycle_bad else "FAIL", ", ".join(x for x in lifecycle_bad if x)))
        checks.append(Check("deprecated_operation_metadata", "PASS" if not deprecated_bad else "FAIL", ", ".join(x for x in deprecated_bad if x)))
        unknown = sorted({pid for op in operations for pid in op["policies"] if pid not in known})
        checks.append(Check("routing_policy_refs", "PASS" if not unknown else "FAIL", ", ".join(unknown)))
        invalid_patterns = []
        alias_operations = aliases_doc.get("operations", {}) if isinstance(aliases_doc, dict) else {}
        alias_ids = set(alias_operations)
        op_id_set = set(op_ids)
        checks.append(Check(
            "routing_alias_operation_parity",
            "PASS" if alias_ids == op_id_set else "FAIL",
            "all canonical operations have exactly one alias entry" if alias_ids == op_id_set else f"missing={sorted(op_id_set-alias_ids)}, extra={sorted(alias_ids-op_id_set)}",
        ))
        for op_id, aliases in alias_operations.items():
            for pattern in aliases.get("patterns", []):
                try:
                    re.compile(pattern)
                except re.error as exc:
                    invalid_patterns.append(f"{op_id}: {pattern!r}: {exc}")
        checks.append(Check("routing_regex_patterns", "PASS" if not invalid_patterns else "FAIL", "; ".join(invalid_patterns)))
        bad_execution_closure = [
            op["id"] for op in operations
            if op.get("requires_execution_policy") and "execution" not in known
        ]
        checks.append(Check("execution_policy_closure", "PASS" if not bad_execution_closure else "FAIL", ", ".join(bad_execution_closure)))
        scenario_without_execution = [
            op["id"] for op in operations
            if op["id"].startswith("test.scenario.")
            and (not op.get("requires_execution_policy") or "execution" not in op.get("policies", []))
        ]
        checks.append(Check(
            "test_scenario_execution_closure",
            "PASS" if not scenario_without_execution else "FAIL",
            ", ".join(scenario_without_execution),
        ))
        production_rule_unknown_ops = set(
            contract.get("execution_boundary", {}).get("production_effect_escalation_operations", [])
        ) - set(op_ids)
        context_rule_unknown_ops = {
            op
            for rule in contract.get("execution_boundary", {}).get("context_effect_escalation_rules", [])
            for op in rule.get("operations", [])
            if op not in set(op_ids)
        }
        boundary_unknown_ops = sorted(production_rule_unknown_ops | context_rule_unknown_ops)
        checks.append(Check(
            "execution_boundary_operation_refs",
            "PASS" if not boundary_unknown_ops else "FAIL",
            ", ".join(boundary_unknown_ops),
        ))

    if root.exists():
        checks.extend(validate_internal_links(root))
        checks.extend(compile_python_sources(root))

    legacy = [
        "CHANGELOG.md", "MIGRATION_V7_TO_V8.md", "MIGRATION_V8_TO_V9.md", "PROJECT_MAP.md", "ARCHITECTURE.md",
        "docs/agent/POLICY_MANIFEST.json", "docs/agent/TASK_SIGNALS.json",
    ]
    present = [x for x in legacy if (root / x).exists()]
    checks.append(Check("legacy_files_removed", "PASS" if not present else "FAIL", ", ".join(present)))

    stale_name_re = re.compile(r"universal-agent-docs-(?:(?:v?\d)|final|new|refactored|clean)(?:[\w.-]*)", re.I)
    stale_hits = []
    if root.exists():
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in {".md", ".json", ".py", ".txt"}:
                try:
                    text = p.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                if stale_name_re.search(text):
                    stale_hits.append(str(p.relative_to(root)))
    checks.append(Check("canonical_name_no_suffix", "PASS" if not stale_hits else "FAIL", ", ".join(stale_hits)))
    return checks


def forbidden_path(name: str, patterns: Iterable[str]) -> bool:
    normalized = name.replace("\\", "/").lstrip("./")
    for pattern in patterns:
        if pattern.endswith("/") and pattern[:-1] in normalized.split("/"):
            return True
        if fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(Path(normalized).name, pattern):
            return True
    return False


def normalize_archive_entry(name: str) -> tuple[str | None, str | None]:
    if "\x00" in name:
        return None, "NUL byte in archive path"
    raw = name.replace("\\", "/")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:/", raw):
        return None, "absolute archive path"
    if ".." in raw.split("/"):
        return None, "archive path traversal component"
    normalized = posixpath.normpath(raw)
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        return None, "archive path traversal"
    return normalized, None


def _distribution_result(**kwargs) -> dict:
    categories = [
        "missing", "unexpected", "forbidden", "unsafe_entries", "duplicate_entries", "name_collisions",
        "resource_limit_violations", "symlinks", "outside_root", "bundle_failures", "integrity_failures",
        "release_integrity_failures"
    ]
    failed = any(kwargs.get(key) for key in categories)
    kwargs["status"] = "FAIL" if failed else "PASS"
    return kwargs


def _archive_collision_key(name: str) -> tuple[str, str]:
    return unicodedata.normalize("NFKC", name), unicodedata.normalize("NFKC", name).casefold()


def _resource_limit_checks(entries: list[tuple[str, int, int]], cfg: dict) -> list[str]:
    """entries are (name, uncompressed_size, compressed_size); compressed_size=-1 for directories."""
    violations: list[str] = []
    if len(entries) > cfg["max_archive_entries"]:
        violations.append(f"entry count {len(entries)} exceeds max_archive_entries={cfg['max_archive_entries']}")
    total = sum(size for _, size, _ in entries)
    if total > cfg["max_total_uncompressed_bytes"]:
        violations.append(
            f"total uncompressed bytes {total} exceeds max_total_uncompressed_bytes={cfg['max_total_uncompressed_bytes']}"
        )
    for name, size, compressed in entries:
        if size > cfg["max_file_uncompressed_bytes"]:
            violations.append(
                f"{name}: uncompressed bytes {size} exceeds max_file_uncompressed_bytes={cfg['max_file_uncompressed_bytes']}"
            )
        if compressed >= 0 and size > 0:
            ratio = float("inf") if compressed == 0 else size / compressed
            if ratio > cfg["max_compression_ratio"]:
                violations.append(
                    f"{name}: compression ratio {ratio:.1f} exceeds max_compression_ratio={cfg['max_compression_ratio']}"
                )
    return violations


def _name_collision_checks(names: list[str], cfg: dict) -> list[str]:
    collisions: list[str] = []
    nfkc_seen: dict[str, str] = {}
    case_seen: dict[str, str] = {}
    for name in names:
        nfkc, folded = _archive_collision_key(name)
        if cfg["reject_unicode_normalization_collisions"]:
            prior = nfkc_seen.get(nfkc)
            if prior is not None and prior != name:
                collisions.append(f"unicode normalization collision: {prior!r} vs {name!r}")
            else:
                nfkc_seen[nfkc] = name
        if cfg["reject_casefold_collisions"]:
            prior = case_seen.get(folded)
            if prior is not None and prior != name:
                collisions.append(f"case-insensitive collision: {prior!r} vs {name!r}")
            else:
                case_seen[folded] = name
    return sorted(set(collisions))


def validate_distribution(path: Path, contract: dict, trusted_manifest: Path | None = None, release_manifest: Path | None = None) -> dict:
    cfg = contract["distribution"]
    canonical_root = cfg["canonical_root"]
    required = list(cfg["required_files"])
    allowed = set(cfg["allowed_files"])
    patterns = cfg["forbidden_patterns"]

    base = {
        "detail": "",
        "missing": [],
        "unexpected": [],
        "forbidden": [],
        "unsafe_entries": [],
        "duplicate_entries": [],
        "name_collisions": [],
        "resource_limit_violations": [],
        "symlinks": [],
        "outside_root": [],
        "bundle_failures": [],
        "integrity_failures": [],
        "release_integrity_failures": [],
    }

    def evaluate_bundle(bundle_root: Path, names: list[str], entries: list[tuple[str, int, int]]) -> dict:
        result = dict(base)
        unique_names = sorted(set(names))
        result["missing"] = sorted(set(required) - set(unique_names))
        if not cfg["allow_unlisted_files"]:
            result["unexpected"] = sorted(set(unique_names) - allowed)
        result["forbidden"] = sorted(x for x in unique_names if forbidden_path(x, patterns))
        result["name_collisions"] = _name_collision_checks(names, cfg)
        result["resource_limit_violations"] = _resource_limit_checks(entries, cfg)
        prelim = any(result[k] for k in [
            "missing", "unexpected", "forbidden", "name_collisions", "resource_limit_violations"
        ])
        if cfg["run_bundle_checks"] and not prelim:
            failures = [c for c in bundle_checks(bundle_root) if c.status != "PASS"]
            result["bundle_failures"] = [f"{c.name}: {c.detail}" for c in failures]
            if trusted_manifest is not None and not result["bundle_failures"]:
                integrity_result = verify_trust_manifest(trusted_manifest, bundle_root)
                result["integrity_failures"] = integrity_result["errors"]
        result["detail"] = f"checked {len(unique_names)} files against canonical manifest"
        return _distribution_result(**result)

    if path.is_dir():
        if (path / "AGENTS.md").is_file():
            bundle_root = path
            outside = []
        elif (path / canonical_root).is_dir():
            bundle_root = path / canonical_root
            outside = [str(p.relative_to(path)).replace("\\", "/") for p in path.rglob("*") if p.is_file() and canonical_root not in p.relative_to(path).parts[:1]]
        else:
            result = dict(base)
            result["detail"] = f"directory must be the bundle root or contain {canonical_root}/"
            result["missing"] = required
            return _distribution_result(**result)

        names: list[str] = []
        entries: list[tuple[str, int, int]] = []
        symlinks: list[str] = []
        for p in bundle_root.rglob("*"):
            rel = str(p.relative_to(bundle_root)).replace("\\", "/")
            if p.is_symlink():
                symlinks.append(rel)
            elif p.is_file():
                names.append(rel)
                try:
                    size = p.stat().st_size
                except OSError:
                    size = cfg["max_file_uncompressed_bytes"] + 1
                entries.append((rel, size, -1))
        result = evaluate_bundle(bundle_root, names, entries)
        if release_manifest is not None:
            result["release_integrity_failures"] = ["full release manifest binds the canonical ZIP artifact; verify it against the ZIP rather than an extracted directory"]
        result["outside_root"] = sorted(outside)
        result["symlinks"] = sorted(symlinks) if cfg["reject_symlinks"] else []
        return _distribution_result(**result)

    if not (path.is_file() and zipfile.is_zipfile(path)):
        result = dict(base)
        result["detail"] = "distribution target must be a directory or ZIP archive"
        result["missing"] = required
        return _distribution_result(**result)

    names: list[str] = []
    all_normalized_files: list[str] = []
    normalized_full_seen: set[str] = set()
    duplicate_entries: list[str] = []
    unsafe_entries: list[str] = []
    symlinks: list[str] = []
    outside_root: list[str] = []
    resource_entries: list[tuple[str, int, int]] = []

    with zipfile.ZipFile(path) as zf:
        safe_files: list[tuple[zipfile.ZipInfo, str]] = []
        for info in zf.infolist():
            normalized, error = normalize_archive_entry(info.filename)
            if error:
                unsafe_entries.append(f"{info.filename}: {error}")
                continue
            assert normalized is not None
            if normalized in normalized_full_seen and not info.is_dir():
                duplicate_entries.append(normalized)
            normalized_full_seen.add(normalized)

            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                symlinks.append(normalized)
                continue
            if info.is_dir():
                resource_entries.append((normalized, 0, -1))
                continue
            all_normalized_files.append(normalized)
            resource_entries.append((normalized, info.file_size, info.compress_size))
            prefix = canonical_root + "/"
            if not normalized.startswith(prefix):
                outside_root.append(normalized)
                continue
            rel = normalized[len(prefix):]
            if not rel or rel.startswith("../"):
                unsafe_entries.append(f"{info.filename}: invalid relative entry")
                continue
            names.append(rel)
            safe_files.append((info, rel))

        result = dict(base)
        result["missing"] = sorted(set(required) - set(names))
        if not cfg["allow_unlisted_files"]:
            result["unexpected"] = sorted(set(names) - allowed)
        result["forbidden"] = sorted(x for x in names if forbidden_path(x, patterns))
        result["unsafe_entries"] = sorted(unsafe_entries) if cfg["reject_unsafe_archive_paths"] else []
        result["duplicate_entries"] = sorted(set(duplicate_entries)) if cfg["reject_duplicate_entries"] else []
        result["name_collisions"] = _name_collision_checks(all_normalized_files, cfg)
        result["resource_limit_violations"] = _resource_limit_checks(resource_entries, cfg)
        result["symlinks"] = sorted(symlinks) if cfg["reject_symlinks"] else []
        result["outside_root"] = sorted(outside_root)

        prelim_errors = any(result[k] for k in [
            "missing", "unexpected", "forbidden", "unsafe_entries", "duplicate_entries", "name_collisions",
            "resource_limit_violations", "symlinks", "outside_root"
        ])
        if cfg["run_bundle_checks"] and not prelim_errors:
            with tempfile.TemporaryDirectory() as td:
                bundle_root = Path(td) / canonical_root
                bundle_root.mkdir(parents=True, exist_ok=True)
                for info, rel in safe_files:
                    target = bundle_root / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, target.open("wb") as dst:
                        # Resource limits were checked from central-directory metadata before extraction.
                        dst.write(src.read(cfg["max_file_uncompressed_bytes"] + 1))
                        if src.read(1):
                            result["resource_limit_violations"].append(f"{rel}: extracted data exceeded declared size limit")
                            break
                if not result["resource_limit_violations"]:
                    failures = [c for c in bundle_checks(bundle_root) if c.status != "PASS"]
                    result["bundle_failures"] = [f"{c.name}: {c.detail}" for c in failures]
                    if trusted_manifest is not None and not result["bundle_failures"]:
                        integrity_result = verify_trust_manifest(trusted_manifest, bundle_root)
                        result["integrity_failures"] = integrity_result["errors"]
                    if release_manifest is not None and not result["bundle_failures"]:
                        release_result = verify_release_manifest(release_manifest, path, contract)
                        result["release_integrity_failures"] = release_result["errors"]
        result["detail"] = f"checked {len(set(names))} files against canonical manifest"
        return _distribution_result(**result)


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

def validate_approval_assertion(
    path: Path,
    contract: dict,
    boundary: dict | None = None,
    root: Path = ROOT,
    replay_registry: Path | None = None,
    consume: bool = False,
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
    now = datetime.now(timezone.utc)
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


def print_checks(checks: list[Check]) -> None:
    for c in checks:
        suffix = f" — {c.detail}" if c.detail else ""
        print(f"[{c.status}] {c.name}{suffix}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate universal-agent-docs")
    parser.add_argument("--route", metavar="TASK", help="route a task through canonical operation normalization")
    parser.add_argument("--operation", action="append", default=[], help="planned canonical operation ID (legacy natural-language alias also accepted); repeatable")
    parser.add_argument("--resource", action="append", default=[], help="affected resource path; repeatable")
    parser.add_argument("--routing-mode", choices=["advisory", "enforcement"], default="advisory", help="advisory warns on unresolved routing; enforcement fails closed")
    parser.add_argument("--action-boundary", action="store_true", help="evaluate an imminent action using runtime actual operations and Effect x Exposure")
    parser.add_argument("--actual-operation", action="append", default=[], help="canonical operation asserted by the runtime/tool adapter at execution time; repeatable")
    parser.add_argument("--actual-action", default="", help="optional concrete command/action text used for advisory hints and high-confidence signature mismatch detection")
    parser.add_argument("--runtime-action", type=Path, help="validate a structured runtime adapter action assertion and evaluate its execution boundary")
    parser.add_argument("--target", action="append", default=[], help="concrete execution target/recipient/resource; repeatable")
    parser.add_argument("--environment", default="", help="execution environment: local/test/staging/production/public/external/unknown")
    parser.add_argument("--exposure", choices=["X0", "X1", "X2", "X3"], help="optional adapter-declared Exposure; may raise but never lower policy-derived Exposure")
    parser.add_argument("--exposure-facts", type=Path, help="JSON object containing raw exposure dimensions for --action-boundary")
    parser.add_argument("--correlation-id", default="", help="stable action correlation ID used to bind explicit approval")
    parser.add_argument("--execution-nonce", default="", help="single-use runtime nonce (minimum 16 characters) bound into action digest")
    parser.add_argument("--effect", choices=["L1", "L2", "L3", "L4"], help="optional runtime-observed Effect escalation; never lowers operation floors")
    parser.add_argument("--policy", action="append", default=[], metavar="ID", help="print a primary-owner policy section by policy ID; repeatable")
    parser.add_argument("--readiness", choices=["development", "deployment"])
    parser.add_argument("--distribution", type=Path, help="validate a complete explicit distribution directory or ZIP")
    parser.add_argument("--trusted-manifest", type=Path, help="verify core policy hashes against an out-of-band trusted manifest; with --distribution, verifies the artifact")
    parser.add_argument("--release-manifest", type=Path, help="verify full distributed-file and ZIP integrity against an out-of-band release manifest; requires --distribution ZIP")
    parser.add_argument("--emit-trust-manifest", type=Path, help="write a detached trust manifest for the current validated core; publish/store it out-of-band")
    parser.add_argument("--approval-assertion", type=Path, help="validate explicit approval structure/time and bind it to the evaluated action when present")
    parser.add_argument("--approval-ledger", type=Path, help="SQLite registry used to detect/record single-use approval replay")
    parser.add_argument("--consume-approval", action="store_true", help="atomically consume the bound approval in --approval-ledger; requires --approval-ledger")
    parser.add_argument("--protected-override", type=Path, help="validate protected override object structure/time only; never establishes authorization")
    parser.add_argument("--override-ledger", type=Path, help="SQLite registry used to detect/record single-use protected override replay")
    parser.add_argument("--consume-override", action="store_true", help="atomically consume the bound protected override in --override-ledger; requires --override-ledger")
    parser.add_argument("--bootstrap-project", type=Path, metavar="REPO", help="scan a repository and write a conservative PROJECT.inferred.md candidate")
    parser.add_argument("--bootstrap-output", type=Path, help="output path for --bootstrap-project; defaults to REPO/PROJECT.inferred.md")
    parser.add_argument("--bootstrap-force", action="store_true", help="allow --bootstrap-project to overwrite its output path")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    contract = load_json(CONTRACT_PATH)
    result: dict = {}
    exit_code = 0

    checks = bundle_checks(ROOT)
    bundle_ok = all(c.status == "PASS" for c in checks)
    result["bundle"] = {"status": "PASS" if bundle_ok else "FAIL", "checks": [asdict(c) for c in checks]}
    if not bundle_ok:
        exit_code = 1

    if args.bootstrap_project:
        try:
            boot = bootstrap_project(args.bootstrap_project, args.bootstrap_output, args.bootstrap_force)
            result["bootstrap_project"] = boot
        except Exception as exc:
            result["bootstrap_project"] = {"status": "FAIL", "error": str(exc)}
            exit_code = 1

    if args.policy:
        try:
            sections = extract_policy_sections(contract, args.policy, POLICIES_PATH)
            result["policy_sections"] = sections
        except Exception as exc:
            result["policy_sections"] = {}
            result["policy_error"] = str(exc)
            exit_code = 1

    if args.route is not None:
        routing = route_policies(contract, args.route, args.operation, args.resource, args.routing_mode)
        result["routing"] = routing
        if routing["routing_status"] == "FAIL":
            exit_code = 1

    approval_boundary = None
    if args.action_boundary:
        exposure_facts = None
        if args.exposure_facts is not None:
            try:
                exposure_facts = load_json(args.exposure_facts)
            except Exception as exc:
                result["execution_boundary"] = {"status": "FAIL", "decision": "BLOCK_POLICY_ERROR", "errors": [f"exposure facts: {exc}"]}
                exit_code = 1
        if "execution_boundary" not in result:
            boundary = evaluate_execution_boundary(
                contract,
                args.operation,
                args.actual_operation,
                args.resource,
                args.target,
                args.environment,
                args.exposure,
                args.effect,
                args.actual_action,
                exposure_facts=exposure_facts,
                correlation_id=args.correlation_id,
                execution_nonce=args.execution_nonce,
                adapter={"id":"validator-cli","surface":"cli","assertion_source":"human_reviewed"},
                semantic_details={},
            )
            result["execution_boundary"] = boundary
            approval_boundary = boundary
            if boundary["status"] != "PASS" or boundary["decision"].startswith("BLOCK_"):
                exit_code = 1

    if args.runtime_action:
        runtime_action_result = validate_runtime_action(args.runtime_action, contract, ROOT)
        result["runtime_action"] = runtime_action_result
        boundary = runtime_action_result.get("boundary", {})
        approval_boundary = boundary if boundary else approval_boundary
        if runtime_action_result["status"] != "PASS" or str(boundary.get("decision", "")).startswith("BLOCK_"):
            exit_code = 1

    if args.approval_assertion:
        approval_result = validate_approval_assertion(
            args.approval_assertion, contract, approval_boundary, ROOT,
            replay_registry=args.approval_ledger, consume=args.consume_approval
        )
        result["approval_assertion"] = approval_result
        if approval_result["object_validity"] != "VALID":
            exit_code = 1

    if args.readiness:
        r = readiness(PROJECT_PATH, args.readiness)
        result["readiness"] = r
        if r["documented"] != "PASS" or r["verified"] == "FAIL":
            exit_code = 1

    if args.distribution:
        d = validate_distribution(args.distribution, contract, args.trusted_manifest, args.release_manifest)
        result["distribution"] = d
        if d["status"] != "PASS":
            exit_code = 1
    elif args.trusted_manifest:
        integrity_result = verify_trust_manifest(args.trusted_manifest, ROOT)
        result["integrity"] = integrity_result
        if integrity_result["status"] != "PASS":
            exit_code = 1
    if args.release_manifest and not args.distribution:
        result["release_integrity"] = {"status": "FAIL", "errors": ["--release-manifest requires --distribution pointing to the canonical ZIP"]}
        exit_code = 1

    if args.emit_trust_manifest:
        if result["bundle"]["status"] != "PASS":
            result["trust_manifest_error"] = "refusing to emit trust manifest for a bundle that failed validation"
            exit_code = 1
        else:
            emitted = write_trust_manifest(args.emit_trust_manifest, ROOT)
            result["emitted_trust_manifest"] = {"path": str(args.emit_trust_manifest), "manifest": emitted}

    if args.consume_override and not args.protected_override:
        result["protected_override_error"] = "--consume-override requires --protected-override"
        exit_code = 1
    if args.override_ledger and not args.protected_override:
        result["protected_override_error"] = "--override-ledger requires --protected-override"
        exit_code = 1

    if args.protected_override:
        o = validate_protected_override(
            args.protected_override, contract, approval_boundary, ROOT,
            replay_registry=args.override_ledger, consume=args.consume_override,
        )
        result["protected_override"] = o
        if o["object_validity"] != "VALID" or o.get("binding") == "INVALID":
            exit_code = 1

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return exit_code

    policy_only = (
        bool(args.policy) and args.route is None and not args.action_boundary and not args.runtime_action and not args.readiness
        and not args.distribution and not args.trusted_manifest and not args.release_manifest and not args.emit_trust_manifest
        and not args.approval_assertion and not args.protected_override and not args.override_ledger and not args.consume_override
        and not args.bootstrap_project
    )
    if policy_only:
        if result["bundle"]["status"] != "PASS":
            print("Bundle validation: FAIL", file=sys.stderr)
            for check in checks:
                if check.status != "PASS":
                    suffix = f" — {check.detail}" if check.detail else ""
                    print(f"[{check.status}] {check.name}{suffix}", file=sys.stderr)
            return exit_code
        if "policy_error" in result:
            print(result["policy_error"], file=sys.stderr)
            return exit_code
        print("\n\n".join(result["policy_sections"].values()))
        return exit_code

    print(f"Bundle validation: {result['bundle']['status']}")
    if result["bundle"]["status"] != "PASS":
        print_checks(checks)
    if "bootstrap_project" in result:
        boot = result["bootstrap_project"]
        print(f"PROJECT bootstrap: {boot.get('status')}" + (f" — {boot.get('output')}" if boot.get('output') else ""))
        if boot.get("note"):
            print(" -", boot["note"])
        if boot.get("error"):
            print(" - error:", boot["error"])
    if "policy_sections" in result:
        if "policy_error" in result:
            print("Policy selector error:", result["policy_error"])
        else:
            for policy_id, section in result["policy_sections"].items():
                print(f"Policy section [{policy_id}]:")
                print(section)
    if "routing" in result:
        r = result["routing"]
        print("Canonical operations:", ", ".join(r["canonical_operations"]) or "(none)")
        print("Routing policies:", ", ".join(r["policies"]) or "(none)")
        if r["matched_resources"]:
            print("Matched resources:")
            for x in r["matched_resources"]:
                print(" -", x)
        print("Routing mode:", r["routing_mode"], "status=", r["routing_status"])
        if r["effect_floors"]:
            print("Effect floors:", ", ".join(f"{k}={v}" for k, v in r["effect_floors"].items()))
        for x in r["warnings"]:
            print(" - warning:", x)
        for x in r["errors"]:
            print(" - error:", x)
    if "execution_boundary" in result:
        b = result["execution_boundary"]
        print(f"Execution boundary: {b['status']} — decision={b['decision']}")
        print("Actual operations:", ", ".join(b["actual_operations"]) or "(none)")
        print(f"Effective risk: Effect={b['effective_effect'] or '(unknown)'} Exposure={b['effective_exposure'] or '(unknown)'} gate={b['action_gate'] or '(none)'}")
        if b["targets"]:
            print("Targets:", ", ".join(b["targets"]))
        if b.get("action_digest"):
            print("Action digest:", b["action_digest"])
        for x in b["escalations"]:
            print(" - escalation:", x)
        for x in b["warnings"]:
            print(" - warning:", x)
        for x in b["errors"]:
            print(" - error:", x)
    if "runtime_action" in result:
        ra = result["runtime_action"]
        print(f"Runtime action assertion: {ra['status']} — schema={ra['schema_status']} adapter_trust={ra['adapter_trust']}")
        if "boundary" in ra:
            b = ra["boundary"]
            print(f"Runtime action boundary: {b['status']} — decision={b['decision']} Effect={b['effective_effect'] or '(unknown)'} Exposure={b['effective_exposure'] or '(unknown)'}")
        for x in ra.get("warnings", []):
            print(" - warning:", x)
        for x in ra.get("errors", []):
            print(" - error:", x)
    if "approval_assertion" in result:
        a = result["approval_assertion"]
        print(f"Approval assertion: {a['object_validity']} — schema={a['schema_status']} temporal={a['temporal']} binding={a['binding']}")
        print(f"Authorization: {a['authorization']} (authority={a['authority']})")
        for x in a.get("warnings", []):
            print(" - warning:", x)
        for x in a.get("errors", []):
            print(" - error:", x)
    if "readiness" in result:
        r = result["readiness"]
        print(f"Documented {r['mode']} readiness: {r['documented']}")
        print(f"Source-evidence-verified {r['mode']} readiness: {r['evidence_verified']}")
        print(f"Execution-verified {r['mode']} readiness: {r['execution_verified']}")
        if r["documented"] != "PASS" or r["verified"] != "PASS":
            print("Documented checks:")
            print_checks([Check(**x) for x in r["documented_checks"]])
            print("Verified checks:")
            print_checks([Check(**x) for x in r["verified_checks"]])
        for warning in r.get("warnings", []):
            print(" - warning:", warning)
    if "distribution" in result:
        d = result["distribution"]
        print(f"Distribution validation: {d['status']} — {d['detail']}")
        for field in [
            "missing", "unexpected", "forbidden", "unsafe_entries", "duplicate_entries", "name_collisions",
            "resource_limit_violations", "symlinks", "outside_root", "bundle_failures", "integrity_failures",
            "release_integrity_failures"
        ]:
            for x in d[field]:
                print(f" - {field}:", x)
    if "release_integrity" in result:
        ri = result["release_integrity"]
        print(f"Release-manifest verification: {ri['status']}")
        for x in ri.get("errors", []):
            print(" - error:", x)
    if "integrity" in result:
        i = result["integrity"]
        print(f"Trusted-manifest verification: {i['status']}")
        for x in i["errors"]:
            print(" - error:", x)
    if "emitted_trust_manifest" in result:
        print("Trust manifest written:", result["emitted_trust_manifest"]["path"])
    if "trust_manifest_error" in result:
        print("Trust manifest error:", result["trust_manifest_error"])
    if "protected_override" in result:
        o = result["protected_override"]
        print(f"Protected override object: {o['object_validity']} (binding={o.get('binding')})")
        print(f"Authorization: {o['authorization']} (authority={o['authority']}, task_approval={o['task_approval']})")
        for x in o["errors"]:
            print(" - error:", x)
        for x in o["warnings"]:
            print(" - warning:", x)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
