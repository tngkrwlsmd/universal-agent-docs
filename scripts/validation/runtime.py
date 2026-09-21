from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

try:
    import jsonschema
except ImportError:  # pragma: no cover - exercised by CLI environments without deps
    jsonschema = None

from .contract import (
    ACTION_DIGEST_FORMAT,
    CONTEXT_EFFECT_ESCALATION_RULES,
    KNOWN_ENVIRONMENTS,
    OPERATION_SEMANTIC_REQUIREMENTS,
    OPERATION_EXTENSION_DIGEST_KEY,
    ADAPTER_CAPABILITY_DIGEST_KEY,
    EXTENSION_TRUST_REQUIRED_ENVIRONMENTS,
    PRODUCTION_EFFECT_ESCALATION_OPERATIONS,
    ROOT,
    TARGET_REQUIRED_EFFECT_LEVELS,
    TARGET_REQUIRED_EXPOSURE_LEVELS,
    canonical_policy_contract_digest,
    load_json,
)
from .risk import (
    _EFFECT_RANK,
    _EXPOSURE_RANK,
    _concrete_targets,
    _max_level,
    derive_exposure_floor,
    infer_hard_action_operations,
)
from .routing import infer_operations, load_routing_aliases, operation_catalog, route_policies

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
    extension_registry: dict | None = None,
    adapter_capabilities: dict | None = None,
) -> dict:
    """Evaluate the policy gate for an imminent action.

    Runtime/tool adapters assert action facts and canonical operations. They do not own
    Exposure classification: the validator derives a conservative floor from raw facts
    and environment. Adapter-declared Exposure is optional and may only raise that floor.
    The function computes the minimum gate but deliberately does not authenticate an
    approval issuer or protected-override authority.
    """
    catalog = operation_catalog(contract, extension_registry)
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
    extension_operations = extension_registry.get("operations", {}) if extension_registry else {}
    used_extension_operations = [
        operation_id for operation_id in valid_actual if operation_id in extension_operations
    ]
    adapter_id = str((adapter or {}).get("id", "")).strip()
    capability_adapters = adapter_capabilities.get("adapters", {}) if adapter_capabilities else {}
    adapter_capability = capability_adapters.get(adapter_id)
    for operation_id in used_extension_operations:
        supported_adapters = extension_operations[operation_id].get("supported_adapters", [])
        if adapter_id not in supported_adapters:
            errors.append(
                f"extension operation {operation_id!r} is not declared for adapter {adapter_id!r}; "
                f"supported adapters: {supported_adapters!r}"
            )
        if adapter_capability is None:
            errors.append(
                f"extension operation {operation_id!r} requires an explicit capability declaration "
                f"for adapter {adapter_id!r}"
            )
        elif operation_id not in set(adapter_capability.get("supported_operations", [])):
            errors.append(
                f"adapter {adapter_id!r} capability does not declare extension operation {operation_id!r}"
            )
    if used_extension_operations and env in EXTENSION_TRUST_REQUIRED_ENVIRONMENTS:
        if not extension_registry or extension_registry.get("integrity") != "MATCHED":
            errors.append(
                f"extension integrity must be MATCHED against a separately supplied expected digest in environment {env!r}"
            )
        if not adapter_capabilities or adapter_capabilities.get("integrity") != "MATCHED":
            errors.append(
                f"adapter capability integrity must be MATCHED against a separately supplied expected digest in environment {env!r}"
            )

    route = route_policies(
        contract, "", valid_actual, resource_list, "enforcement", aliases_doc,
        extension_registry=extension_registry,
    )
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
    if env == "production":
        extension_production_effect = _max_level(
            [
                extension_operations[operation_id].get("production_effect")
                for operation_id in used_extension_operations
                if extension_operations[operation_id].get("production_effect") in _EFFECT_RANK
            ],
            _EFFECT_RANK,
        )
        if (
            extension_production_effect is not None
            and (
                effective_effect is None
                or _EFFECT_RANK[extension_production_effect] > _EFFECT_RANK[effective_effect]
            )
        ):
            effective_effect = extension_production_effect
            escalations.append(
                f"operation extension escalated production Effect to {extension_production_effect}"
            )
    if runtime_effect in _EFFECT_RANK:
        if effective_effect is None or _EFFECT_RANK[runtime_effect] > _EFFECT_RANK[effective_effect]:
            effective_effect = runtime_effect
            escalations.append(f"runtime_effect raised effective Effect to {runtime_effect}")

    supplied_semantic_values = semantic_details if isinstance(semantic_details, dict) else {}
    semantic_values = dict(supplied_semantic_values)
    if used_extension_operations:
        for reserved_key in (OPERATION_EXTENSION_DIGEST_KEY, ADAPTER_CAPABILITY_DIGEST_KEY):
            if reserved_key in semantic_values:
                errors.append(
                    f"semantic_details.{reserved_key} is reserved for policy extension/capability binding"
                )
        semantic_values[OPERATION_EXTENSION_DIGEST_KEY] = extension_registry["combined_digest"]
        if adapter_capabilities is not None:
            semantic_values[ADAPTER_CAPABILITY_DIGEST_KEY] = adapter_capabilities.get("combined_digest")

    semantic_rules = cfg.get("operation_semantic_requirements", OPERATION_SEMANTIC_REQUIREMENTS)
    for rule in semantic_rules:
        if not set(rule.get("operations", [])).intersection(valid_actual):
            continue
        if env not in set(rule.get("allowed_environments", [])):
            errors.append(
                f"operation semantic requirement {rule.get('id')!r} does not allow environment {env!r}"
            )
        for key in rule.get("required_semantic_details", []):
            value = semantic_values.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                errors.append(
                    f"operation semantic requirement {rule.get('id')!r} requires semantic_details.{key}"
                )
        for key, allowed in rule.get("semantic_detail_allowed_values", {}).items():
            if key in semantic_values and semantic_values[key] not in allowed:
                errors.append(
                    f"operation semantic requirement {rule.get('id')!r} requires semantic_details.{key} in {allowed!r}"
                )

    for operation_id in used_extension_operations:
        extension_operation = extension_operations[operation_id]
        allowed_environments = extension_operation.get("allowed_environments", [])
        if allowed_environments and env not in allowed_environments:
            errors.append(
                f"extension operation {operation_id!r} does not allow environment {env!r}; "
                f"allowed={allowed_environments!r}"
            )
        for key in extension_operation.get("required_semantic_details", []):
            value = semantic_values.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                errors.append(
                    f"extension operation {operation_id!r} requires semantic_details.{key}"
                )
        for key, allowed in extension_operation.get("semantic_detail_allowed_values", {}).items():
            if key in semantic_values and semantic_values[key] not in allowed:
                errors.append(
                    f"extension operation {operation_id!r} requires semantic_details.{key} in {allowed!r}"
                )

    exposure_result = derive_exposure_floor(contract, env, exposure_facts, declared_exposure)
    errors.extend(exposure_result["errors"])
    warnings.extend(exposure_result["warnings"])
    effective_exposure = exposure_result["effective_exposure"]
    exposure_contributions = list(exposure_result["contributions"])
    extension_exposure_floor = _max_level(
        [
            extension_operations[operation_id].get("exposure_floor")
            for operation_id in used_extension_operations
            if extension_operations[operation_id].get("exposure_floor") in _EXPOSURE_RANK
        ],
        _EXPOSURE_RANK,
    )
    if (
        extension_exposure_floor is not None
        and (
            effective_exposure is None
            or _EXPOSURE_RANK[extension_exposure_floor] > _EXPOSURE_RANK[effective_exposure]
        )
    ):
        effective_exposure = extension_exposure_floor
        exposure_contributions.append({
            "source": "operation_extension",
            "value": ",".join(sorted(used_extension_operations)),
            "floor": extension_exposure_floor,
        })
        escalations.append(
            f"operation extension raised Exposure floor to {extension_exposure_floor}"
        )
    for item in exposure_contributions:
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
            semantic_details=semantic_values,
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
        "semantic_details": semantic_values,
        "action_hints": action_hints,
        "action_hint_gaps": action_hint_gaps,
        "hard_action_hints": hard_action_hints,
        "hard_action_hint_gaps": hard_action_hint_gaps,
        "policies": route["policies"],
        "resources": resource_list,
        "targets": concrete_targets,
        "environment": env,
        "exposure_facts": normalized_exposure_facts,
        "exposure_contributions": exposure_contributions,
        "declared_exposure": declared_exposure,
        "derived_exposure": exposure_result["derived_exposure"],
        "runtime_effect": runtime_effect,
        "effective_effect": effective_effect,
        "effective_exposure": effective_exposure,
        "action_gate": gate,
        "escalations": list(dict.fromkeys(escalations)),
        "approval": "NOT_ESTABLISHED",
        "extension_integrity": (
            extension_registry.get("integrity") if used_extension_operations and extension_registry else "NOT_APPLICABLE"
        ),
        "extension_authority": (
            extension_registry.get("authority") if used_extension_operations and extension_registry else "NOT_APPLICABLE"
        ),
        "adapter_capability_integrity": (
            adapter_capabilities.get("integrity") if used_extension_operations and adapter_capabilities else "NOT_APPLICABLE"
        ),
        "adapter_capability_authority": (
            adapter_capabilities.get("authority") if used_extension_operations and adapter_capabilities else "NOT_APPLICABLE"
        ),
        "protected_override_authorization": "NOT_ESTABLISHED",
        "errors": errors,
        "warnings": warnings,
    }


def validate_runtime_action(
    path: Path,
    contract: dict,
    root: Path = ROOT,
    extension_registry: dict | None = None,
    adapter_capabilities: dict | None = None,
) -> dict:
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
        extension_registry=extension_registry,
        adapter_capabilities=adapter_capabilities,
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
