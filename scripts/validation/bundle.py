from __future__ import annotations

import json
import re
from pathlib import Path

try:
    import jsonschema
except ImportError:  # pragma: no cover - exercised by CLI environments without deps
    jsonschema = None

from .contract import *
from .readiness import validate_internal_links
from .routing import operation_catalog

def parse_policy_matrix(markdown: str) -> dict:
    matrix = {}
    row_re = re.compile(r"^\|\s*(L[1-4])\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*$", re.MULTILINE)
    for m in row_re.finditer(markdown):
        matrix[m.group(1)] = {f"X{i}": m.group(i + 2).strip() for i in range(4)}
    return matrix


GENERATED_POLICY_PATH = "docs/generated-policy-reference.md"


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_generated_policy_reference(contract: dict) -> str:
    """Render machine-owned policy facts from POLICY_CONTRACT.json deterministically."""
    risk = contract["risk_model"]
    execution = contract["execution_boundary"]
    protected = contract["protected_override"]
    lines = [
        "# Generated policy reference",
        "",
        "> 이 문서는 `POLICY_CONTRACT.json`에서 자동 생성된 deterministic projection이다. "
        "Source of Truth가 아니며 직접 수정하지 말고 `python scripts/generate_policy_reference.py`로 갱신한다.",
        "",
        "**Effect levels (machine-owned)**",
        "",
        "| Level | Meaning |",
        "|---|---|",
    ]
    for level, meaning in risk["effect_levels"].items():
        lines.append(f"| {level} | {_markdown_cell(meaning)} |")

    lines.extend([
        "",
        "**Exposure levels (machine-owned)**",
        "",
        "| Level | Meaning |",
        "|---|---|",
    ])
    for level, meaning in risk["exposure_levels"].items():
        lines.append(f"| {level} | {_markdown_cell(meaning)} |")

    exposure_levels = list(risk["exposure_levels"])
    lines.extend([
        "",
        "**Effect × Exposure minimum gate**",
        "",
        "| Effect \\ Exposure | " + " | ".join(exposure_levels) + " |",
        "|---|" + "|".join("---" for _ in exposure_levels) + "|",
    ])
    for effect, row in risk["decision_matrix"].items():
        lines.append(
            "| " + effect + " | "
            + " | ".join(_markdown_cell(row[level]) for level in exposure_levels)
            + " |"
        )

    lines.extend([
        "",
        "**Environment Exposure floors**",
        "",
        "| Environment | Minimum Exposure |",
        "|---|---|",
    ])
    for environment, floor in execution["environment_exposure_floors"].items():
        lines.append(f"| {environment} | {floor} |")

    lines.extend([
        "",
        "**Canonical operation catalog**",
        "",
        "| Operation | Policies | Effect floor | Execution policy | Lifecycle |",
        "|---|---|---|---|---|",
    ])
    for operation in sorted(contract["routing"]["operation_catalog"], key=lambda item: item["id"]):
        lifecycle = operation.get("lifecycle_status", "")
        if lifecycle == "deprecated":
            replacement = operation.get("replacement_operation", "")
            lifecycle = f"deprecated -> {replacement}" if replacement else "deprecated"
        lines.append(
            f"| `{operation['id']}` | "
            f"{_markdown_cell(', '.join(operation.get('policies', [])))} | "
            f"{operation.get('effect_floor', '')} | "
            f"{'yes' if operation.get('requires_execution_policy') else 'no'} | "
            f"{_markdown_cell(lifecycle)} |"
        )

    lines.extend([
        "",
        "**Approval / override binding**",
        "",
        f"- approval gate: `{execution['approval_binding_required_for_gate']}`",
        f"- approval schema: `{execution['approval_assertion_schema']}`",
        f"- approval max TTL: `{execution['approval_max_ttl_seconds']}` seconds",
        f"- protected override gate: `{protected['binding_required_for_gate']}`",
        f"- protected override schema: `{protected['schema']}`",
        f"- protected override max TTL: `{protected['max_ttl_seconds']}` seconds",
        f"- action digest format: `{execution['action_digest_format']}`",
        "",
    ])
    return "\n".join(lines)


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

    template_project = root / "templates" / "PROJECT.md"
    compatibility_project = root / "PROJECT.md"
    if template_project.is_file():
        parity = compatibility_project.is_file() and compatibility_project.read_bytes() == template_project.read_bytes()
        checks.append(Check(
            "project_template_compatibility_parity",
            "PASS" if parity else "FAIL",
            "root PROJECT.md matches templates/PROJECT.md" if parity else "root PROJECT.md must be a byte-for-byte compatibility mirror of templates/PROJECT.md",
        ))

    contract = None
    schema = None
    aliases_doc = None
    aliases_schema = None
    runtime_action_schema = None
    approval_assertion_schema = None
    protected_override_schema = None
    operation_extension_schema = None
    adapter_capabilities_schema = None
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
    try:
        operation_extension_schema = load_json(root / "OPERATION_EXTENSION.schema.json")
    except Exception as exc:
        checks.append(Check("operation_extension_schema_json", "FAIL", str(exc)))
    try:
        adapter_capabilities_schema = load_json(root / "ADAPTER_CAPABILITIES.schema.json")
    except Exception as exc:
        checks.append(Check("adapter_capabilities_schema_json", "FAIL", str(exc)))

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
            if operation_extension_schema is not None:
                try:
                    jsonschema.Draft202012Validator.check_schema(operation_extension_schema)
                    checks.append(Check("operation_extension_schema", "PASS", "operation extension schema validates"))
                except Exception as exc:
                    checks.append(Check("operation_extension_schema", "FAIL", str(exc)))
            if adapter_capabilities_schema is not None:
                try:
                    jsonschema.Draft202012Validator.check_schema(adapter_capabilities_schema)
                    checks.append(Check("adapter_capabilities_schema", "PASS", "adapter capabilities schema validates"))
                except Exception as exc:
                    checks.append(Check("adapter_capabilities_schema", "FAIL", str(exc)))

        schema_version = contract.get("schema_version")
        checks.append(Check(
            "supported_schema_version",
            "PASS" if schema_version in SUPPORTED_SCHEMA_VERSIONS else "FAIL",
            f"declared={schema_version!r}, supported={sorted(SUPPORTED_SCHEMA_VERSIONS)}",
        ))
        authority = contract.get("authority") if isinstance(contract.get("authority"), dict) else {}
        checks.append(Check(
            "authority_prose_validation_scope",
            "PASS" if authority.get("prose_validation_scope") == "EXPLICIT_PARITY_CHECKS_ONLY" else "FAIL",
            json.dumps(authority, ensure_ascii=False),
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
            and execution_boundary.get("operation_semantic_requirements") == OPERATION_SEMANTIC_REQUIREMENTS
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
            and integrity.get("release_provenance") == RELEASE_PROVENANCE
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
            "PASS" if declared_allowed == CANONICAL_ALLOWED_FILES else "FAIL",
            "canonical allowed file manifest" if declared_allowed == CANONICAL_ALLOWED_FILES else json.dumps(declared_allowed, ensure_ascii=False),
        ))

        consumer = contract.get("consumer_distribution") if isinstance(contract.get("consumer_distribution"), dict) else {}
        consumer_ok = (
            consumer.get("canonical_root") == "universal-agent-docs-consumer"
            and consumer.get("policy_root") == ".agent-policy"
            and consumer.get("root_agents_path") == "AGENTS.md"
            and consumer.get("vendored_files_source") == "distribution.required_files"
            and consumer.get("release_manifest_format") == "universal-agent-docs-consumer-release-manifest-v1"
            and consumer.get("overwrite_existing_root_agents") is False
            and consumer.get("extraction_requires_collision_check") is True
        )
        checks.append(Check(
            "consumer_distribution_contract",
            "PASS" if consumer_ok else "FAIL",
            json.dumps(consumer, ensure_ascii=False),
        ))

    if (root / "AGENTS.md").is_file():
        agents_lines = (root / "AGENTS.md").read_text(encoding="utf-8").splitlines()
        checks.append(Check("root_router_budget", "PASS" if len(agents_lines) <= 150 else "FAIL", f"{len(agents_lines)} lines"))

    if contract is not None and (root / "POLICIES.md").is_file():
        policies_md = (root / "POLICIES.md").read_text(encoding="utf-8")
        generated_expected = render_generated_policy_reference(contract)
        generated_path = root / GENERATED_POLICY_PATH
        generated_actual = generated_path.read_text(encoding="utf-8") if generated_path.is_file() else None
        checks.append(Check(
            "generated_policy_reference",
            "PASS" if generated_actual == generated_expected else "FAIL",
            "generated machine-policy reference is current"
            if generated_actual == generated_expected
            else "run python scripts/generate_policy_reference.py",
        ))
        ids = [p["id"] for p in contract.get("policies", [])]
        anchors = [p["anchor"] for p in contract.get("policies", [])]
        checks.append(Check("policy_ids_unique", "PASS" if len(ids) == len(set(ids)) else "FAIL", ", ".join(ids)))
        checks.append(Check("policy_anchors_unique", "PASS" if len(anchors) == len(set(anchors)) else "FAIL", ", ".join(anchors)))
        for p in contract.get("policies", []):
            count = policies_md.count(f'id="{p["anchor"]}"')
            checks.append(Check(f"policy_anchor:{p['id']}", "PASS" if count == 1 else "FAIL", f"count={count}"))

        markdown_matrix = parse_policy_matrix(generated_actual or "")
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
