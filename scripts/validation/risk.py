from __future__ import annotations

import re
from typing import Iterable

from .contract import ENVIRONMENT_EXPOSURE_FLOORS, EXPOSURE_DERIVATION

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
