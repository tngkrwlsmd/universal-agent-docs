from __future__ import annotations

import fnmatch
import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable

from .contract import ENFORCEMENT_REQUIRES_RESOLVED_PLAN, ROOT, load_json

def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"[^\w가-힣]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()



def _positive_prefix_before_negated_tail(value: str) -> str:
    """Keep a clearly positive prefix before a final Korean negated action."""
    matches = list(re.finditer(r"(?:하고|하고서|한\s*다음(?:에)?)\s*", value))
    return value[: matches[-1].end()] if matches else ""


def _strip_korean_mixed_negation(value: str) -> str:
    """Remove only high-confidence Korean negated action spans.

    Examples:
    - "배포하지 말고 테스트해줘" -> "테스트해줘"
    - "테스트하고 배포는 하지 마" -> "테스트하고"
    This is intentionally not a general Korean grammar parser.
    """
    current = value
    connective = re.compile(r"하지\s*(?:말고|않고)")
    while True:
        match = connective.search(current)
        if match is None:
            break
        left, right = current[: match.start()], current[match.end() :]
        current = f"{_positive_prefix_before_negated_tail(left)} {right}".strip()

    terminal = re.search(
        r"(?:하지\s*마(?:세요)?|하지\s*말아(?:줘|주세요)?|실행하지\s*마(?:세요)?)",
        current,
    )
    if terminal is not None:
        current = _positive_prefix_before_negated_tail(current[: terminal.start()]).strip()
    return current


def strip_negated_action_clauses(value: str) -> str:
    """Remove obvious action clauses that are explicitly negated/read-only.

    Natural-language routing is advisory; this deliberately handles only high-confidence
    negation patterns so a phrase such as "do not deploy" is not promoted into an
    execution hint. Ambiguous text stays unclassified rather than inventing intent.
    """
    raw = _strip_korean_mixed_negation(unicodedata.normalize("NFKC", value))
    clauses = re.split(r"(?:[,;]|\bbut\b|\bhowever\b|하지만)", raw, flags=re.I)
    kept: list[str] = []
    negative_markers = (
        r"\bdo\s+not\b", r"\bdon['’]?t\b", r"\bwithout\s+(?:execut|run|deploy|publish|appl)",
        r"하지\s*말", r"하지말", r"실행하지", r"하지\s*않",
    )
    read_only_markers = (r"\breview\b", r"\bexplain\b", r"\bshow\s+me\b", r"검토", r"리뷰", r"설명", r"내용만", r"설정만")
    for clause in clauses:
        if not clause.strip():
            continue
        negated = any(re.search(pattern, clause, flags=re.I) for pattern in negative_markers)
        read_only = any(re.search(pattern, clause, flags=re.I) for pattern in read_only_markers)
        if negated or (read_only and re.search(r"\b(?:plan|without)\b|실행하지", clause, flags=re.I)):
            continue
        kept.append(clause)
    return " ".join(kept)

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


def operation_catalog(contract: dict, extension_registry: dict | None = None) -> dict[str, dict]:
    catalog = {item["id"]: item for item in contract["routing"]["operation_catalog"]}
    if extension_registry:
        for operation_id, operation in extension_registry.get("operations", {}).items():
            if operation_id in catalog:
                raise ValueError(f"extension operation collides with core catalog: {operation_id}")
            catalog[operation_id] = operation
    return catalog


def load_routing_aliases(contract: dict, root: Path = ROOT) -> dict:
    source = contract.get("routing", {}).get("alias_source", "ROUTING_ALIASES.json")
    return load_json(root / source)


def infer_operations(contract: dict, text: str, aliases_doc: dict | None = None) -> list[str]:
    normalized = normalize_text(strip_negated_action_clauses(text))
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
    extension_registry: dict | None = None,
) -> dict:
    """Route through canonical IDs; natural-language aliases are advisory hints only.

    Enforcement requires at least one resolved planned canonical operation. Task-text
    classification and task/plan disagreement stay visible as anomaly signals, but do
    not outrank a canonical plan. The execution boundary remains fail-closed by comparing
    trusted runtime actual operations against that plan.
    """
    catalog = operation_catalog(contract, extension_registry)
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
        "operation_extension_digest": (
            extension_registry.get("combined_digest") if extension_registry else None
        ),
        "policies": policies,
        "matched_resources": matched_resources,
        "warnings": warnings,
        "errors": errors,
    }


_EFFECT_RANK = {"L1": 1, "L2": 2, "L3": 3, "L4": 4}
_EXPOSURE_RANK = {"X0": 0, "X1": 1, "X2": 2, "X3": 3}
