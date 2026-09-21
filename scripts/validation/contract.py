from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    import jsonschema
except ImportError:  # pragma: no cover - exercised by CLI environments without deps
    jsonschema = None

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "POLICY_CONTRACT.json"
SCHEMA_PATH = ROOT / "POLICY_CONTRACT.schema.json"
ALIASES_PATH = ROOT / "ROUTING_ALIASES.json"
ALIASES_SCHEMA_PATH = ROOT / "ROUTING_ALIASES.schema.json"
RUNTIME_ACTION_SCHEMA_PATH = ROOT / "RUNTIME_ACTION.schema.json"
APPROVAL_ASSERTION_SCHEMA_PATH = ROOT / "APPROVAL_ASSERTION.schema.json"
PROTECTED_OVERRIDE_SCHEMA_PATH = ROOT / "PROTECTED_OVERRIDE.schema.json"
OPERATION_EXTENSION_SCHEMA_PATH = ROOT / "OPERATION_EXTENSION.schema.json"
ADAPTER_CAPABILITIES_SCHEMA_PATH = ROOT / "ADAPTER_CAPABILITIES.schema.json"
PROJECT_PATH = ROOT / "PROJECT.md"
PROJECT_TEMPLATE_PATH = ROOT / "templates" / "PROJECT.md"
POLICIES_PATH = ROOT / "POLICIES.md"
AGENTS_PATH = ROOT / "AGENTS.md"
PROJECT_START = "<!-- project-facts:start -->"
PROJECT_END = "<!-- project-facts:end -->"
CANONICAL_ROOT = "universal-agent-docs"
OPERATION_EXTENSION_FORMAT = "universal-agent-docs-operation-extension-v1"
ADAPTER_CAPABILITIES_FORMAT = "universal-agent-docs-adapter-capabilities-v1"
OPERATION_EXTENSION_DIGEST_KEY = "policy_extension_digest"
ADAPTER_CAPABILITY_DIGEST_KEY = "adapter_capability_digest"
EXTENSION_TRUST_REQUIRED_ENVIRONMENTS = {"production", "public", "external"}
_EXTENSION_NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")
_EXTENSION_OPERATION_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")
SUPPORTED_SCHEMA_VERSIONS = {16}
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
OPERATION_SEMANTIC_REQUIREMENTS = [
    {
        "id": "tracked_delete_recoverability",
        "operations": [
            "filesystem.tracked_delete"
        ],
        "required_semantic_details": [
            "recoverability",
            "recovery_revision"
        ],
        "semantic_detail_allowed_values": {
            "recoverability": [
                "git_tracked_clean"
            ]
        },
        "allowed_environments": [
            "local",
            "test"
        ]
    }
]
APPROVAL_MAX_TTL_SECONDS = 1800
PROTECTED_OVERRIDE_MAX_TTL_SECONDS = 900
TARGET_REQUIRED_EFFECT_LEVELS = ["L3", "L4"]
TARGET_REQUIRED_EXPOSURE_LEVELS = ["X2", "X3"]
TRUST_MANIFEST_FORMAT = "universal-agent-docs-trust-manifest-v2"
RELEASE_MANIFEST_FORMAT = "universal-agent-docs-release-manifest-v2"
ACTION_DIGEST_FORMAT = "universal-agent-docs-action-digest-v3"
RELEASE_PROVENANCE = {
    "mechanism": "github_immutable_release_and_artifact_attestation",
    "workflow": ".github/workflows/release.yml",
    "trigger": "semver_tag_push",
    "release_identity": "git_tag",
    "semver_tag_prefix": "v",
    "attestation_action": "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6",
    "signature_model": "sigstore_oidc",
    "required_source_ref_kind": "tag",
    "require_tag_commit_reachable_from_main": True,
    "require_preexisting_tag": True,
    "immutable_release_required": True,
    "github_release_attestation_required": True,
    "verifier_requires_expected_tag": True,
    "verifier_requires_expected_source_digest": True,
    "tag_reuse_forbidden": True,
    "release_version_independent_of_schema_version": True,
    "attested_artifacts": [
        "universal-agent-docs.zip",
        "universal-agent-docs.sha256",
        "universal-agent-docs.trust.json",
        "universal-agent-docs.release.json",
        "universal-agent-docs-consumer.zip",
        "universal-agent-docs-consumer.sha256",
        "universal-agent-docs-consumer.release.json",
    ],
    "consumer_verification_required": True,
}
TRUSTED_CORE_FILES = [
    "AGENTS.md",
    "POLICIES.md",
    "POLICY_CONTRACT.json",
    "POLICY_CONTRACT.schema.json",
    "ROUTING_ALIASES.json",
    "ROUTING_ALIASES.schema.json",
    "RUNTIME_ACTION.schema.json",
    "APPROVAL_ASSERTION.schema.json",
    "PROTECTED_OVERRIDE.schema.json",
    "OPERATION_EXTENSION.schema.json",
    "ADAPTER_CAPABILITIES.schema.json",
    "scripts/validate.py",
    "scripts/generate_policy_reference.py",
    "scripts/validation/__init__.py",
    "scripts/validation/contract.py",
    "scripts/validation/routing.py",
    "scripts/validation/context.py",
    "scripts/validation/risk.py",
    "scripts/validation/runtime.py",
    "scripts/validation/integrity.py",
    "scripts/validation/readiness.py",
    "scripts/validation/bundle.py",
    "scripts/validation/distribution.py",
    "scripts/validation/approval.py",
    "scripts/validation/override.py",
    "scripts/package.py",
    "scripts/package_consumer.py",
    "requirements.txt",
    "requirements.lock",
]
REVIEW_FRESHNESS_DAYS = 90
PROJECT_FACT_KEYS = (
    "repository_root", "primary_source", "build_command", "test_command", "runtime",
    "deploy_command", "deploy_target",
)
PROJECT_FACT_STATUSES = {"Confirmed", "Inferred", "Unknown", "N/A"}
CANONICAL_REQUIRED_FILES = [
    ".gitattributes",
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
    "OPERATION_EXTENSION.schema.json",
    "ADAPTER_CAPABILITIES.schema.json",
    "README.md",
    "docs/adoption-profiles.md",
    "docs/extensions.md",
    "docs/generated-policy-reference.md",
    "docs/threat-model.md",
    "LICENSE",
    "requirements.txt",
    "requirements.lock",
    "scripts/validate.py",
    "scripts/generate_policy_reference.py",
    "scripts/conformance.py",
    "scripts/validation/__init__.py",
    "scripts/validation/contract.py",
    "scripts/validation/routing.py",
    "scripts/validation/context.py",
    "scripts/validation/risk.py",
    "scripts/validation/runtime.py",
    "scripts/validation/integrity.py",
    "scripts/validation/readiness.py",
    "scripts/validation/bundle.py",
    "scripts/validation/distribution.py",
    "scripts/validation/approval.py",
    "scripts/validation/override.py",
    "scripts/package.py",
    "scripts/package_consumer.py",
    "tests/__init__.py",
    "tests/policy_test_support.py",
    "tests/test_bundle.py",
    "tests/test_routing.py",
    "tests/test_runtime.py",
    "tests/test_approval.py",
    "tests/test_readiness.py",
    "tests/test_adoption.py",
    "tests/test_distribution.py",
    "tests/test_override.py",
    "tests/test_policy.py",
    "tests/test_fuzz.py",
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
    ".github/workflows/verify-release.yml",
    "evaluation/README.md",
    "conformance/README.md",
    "conformance/corpus.schema.json",
    "conformance/result.schema.json",
    "conformance/coverage.json",
    "conformance/golden.json",
    "conformance/invalid.json",
    "tests/test_conformance.py"
]

CANONICAL_SOURCE_ONLY_FILES = [
    "templates/PROJECT.md",
    "examples/capabilities/reference-sandbox-artifact-adapter.json",
    "examples/consumer-basic/README.md",
    "examples/consumer-basic/after/AGENTS.md",
    "examples/consumer-basic/after/Makefile",
    "examples/consumer-basic/after/PROJECT.reviewed.md",
    "examples/consumer-basic/after/pyproject.toml",
    "examples/consumer-basic/after/src/__init__.py",
    "examples/consumer-basic/after/src/greeter.py",
    "examples/consumer-basic/after/tests/__init__.py",
    "examples/consumer-basic/after/tests/test_greeter.py",
    "examples/consumer-basic/before/AGENTS.md",
    "examples/consumer-basic/before/Makefile",
    "examples/consumer-basic/before/pyproject.toml",
    "examples/consumer-basic/before/src/__init__.py",
    "examples/consumer-basic/before/src/greeter.py",
    "examples/consumer-basic/before/tests/__init__.py",
    "examples/consumer-basic/before/tests/test_greeter.py",
    "examples/extensions/internal-sandbox-artifact.json",
    "examples/runtime-adapter/README.md",
    "examples/runtime-adapter/mock_runtime.py",
    "examples/runtime-adapter/sandbox_artifact_adapter.py",
    "evaluation/scenarios.json",
    "evaluation/smoke.json",
    "evaluation/regression.json",
    "conformance/reference-javascript/runner.mjs",
    "scripts/evaluate.py",
    "scripts/policy_diff.py",
    "scripts/benchmark.py",
    "examples/runtime-adapter/github_issue_adapter.py",
    "tests/test_consumer_example.py",
    "tests/test_extensibility.py",
    "tests/test_runtime_adapter_example.py",
    "tests/test_sandbox_adapter.py",
    "tests/test_github_reference_adapter.py",
    "tests/test_evaluation.py",
    "tests/test_policy_diff.py",
    "tests/test_benchmark.py",
    "tests/test_source_surface.py"
]
CANONICAL_ALLOWED_FILES = CANONICAL_REQUIRED_FILES + CANONICAL_SOURCE_ONLY_FILES

@dataclass
class Check:
    name: str
    status: str
    detail: str = ""


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _canonical_json_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _logical_source_name(path: Path, root: Path = ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def load_operation_extensions(
    paths: Iterable[Path | str],
    contract: dict,
    expected_digests: Iterable[str] = (),
    root: Path = ROOT,
) -> dict:
    """Load explicit organization/vendor operation extensions without mutating the core contract.

    Extension operations are intentionally explicit-plan only. Natural-language aliases remain
    owned by the core ROUTING_ALIASES.json so loading an extension cannot silently broaden task
    interpretation. The returned combined digest is bound into semantic_details whenever an
    extension operation reaches the execution boundary.
    """
    source_paths = [Path(path).resolve() for path in paths]
    expected_digest_set = {str(value).strip() for value in expected_digests if str(value).strip()}
    extension_schema = load_json(root / "OPERATION_EXTENSION.schema.json")
    if not source_paths:
        return {
            "format": OPERATION_EXTENSION_FORMAT,
            "namespaces": [],
            "operations": {},
            "combined_digest": None,
            "integrity": "UNVERIFIED",
            "authority": "NOT_ESTABLISHED",
            "diagnostic_sources": [],
        }

    core_operations = {
        item["id"]: item
        for item in contract.get("routing", {}).get("operation_catalog", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    core_namespaces = {operation_id.split(".", 1)[0] for operation_id in core_operations}
    policy_ids = {item["id"] for item in contract.get("policies", []) if isinstance(item, dict)}
    lifecycle = contract.get("operation_lifecycle", {})
    allowed_statuses = set(lifecycle.get("allowed_statuses", ["active", "deprecated"]))
    effect_rank = {"L1": 1, "L2": 2, "L3": 3, "L4": 4}
    exposure_levels = {"X0", "X1", "X2", "X3"}
    top_level_allowed = {"format", "namespace", "operations"}
    operation_allowed = {
        "id", "policies", "effect_floor", "requires_execution_policy", "lifecycle_status",
        "replacement_operation", "deprecated_since_schema", "supported_adapters",
        "exposure_floor", "production_effect", "allowed_environments",
        "required_semantic_details", "semantic_detail_allowed_values",
    }

    errors: list[str] = []
    namespaces: set[str] = set()
    operations: dict[str, dict] = {}
    normalized_documents: list[dict] = []

    for source_path in source_paths:
        try:
            document = load_json(source_path)
            if jsonschema is not None:
                jsonschema.validate(document, extension_schema)
        except Exception as exc:
            errors.append(f"{source_path}: {exc}")
            continue
        if not isinstance(document, dict):
            errors.append(f"{source_path}: extension document must be a JSON object")
            continue
        extra_top = sorted(set(document) - top_level_allowed)
        if extra_top:
            errors.append(f"{source_path}: unsupported top-level field(s): {', '.join(extra_top)}")
        if document.get("format") != OPERATION_EXTENSION_FORMAT:
            errors.append(
                f"{source_path}: format must be {OPERATION_EXTENSION_FORMAT!r}"
            )
        namespace = document.get("namespace")
        if not isinstance(namespace, str) or not _EXTENSION_NAMESPACE_RE.fullmatch(namespace):
            errors.append(
                f"{source_path}: namespace must match {_EXTENSION_NAMESPACE_RE.pattern!r}"
            )
            continue
        if namespace in core_namespaces:
            errors.append(f"{source_path}: namespace {namespace!r} collides with a core operation namespace")
        if namespace in namespaces:
            errors.append(f"{source_path}: duplicate extension namespace {namespace!r}")
        namespaces.add(namespace)

        raw_operations = document.get("operations")
        if not isinstance(raw_operations, list) or not raw_operations:
            errors.append(f"{source_path}: operations must be a non-empty array")
            continue
        normalized_operations: list[dict] = []
        for index, raw in enumerate(raw_operations):
            prefix = f"{source_path}: operations[{index}]"
            if not isinstance(raw, dict):
                errors.append(f"{prefix} must be an object")
                continue
            extra_fields = sorted(set(raw) - operation_allowed)
            if extra_fields:
                errors.append(f"{prefix}: unsupported field(s): {', '.join(extra_fields)}")
            operation_id = raw.get("id")
            if (
                not isinstance(operation_id, str)
                or not _EXTENSION_OPERATION_RE.fullmatch(operation_id)
                or not operation_id.startswith(namespace + ".")
            ):
                errors.append(
                    f"{prefix}: id must be a canonical operation under namespace {namespace!r}"
                )
                continue
            if operation_id in core_operations:
                errors.append(f"{prefix}: id {operation_id!r} collides with a core operation")
                continue
            if operation_id in operations:
                errors.append(f"{prefix}: duplicate extension operation id {operation_id!r}")
                continue

            policies = raw.get("policies")
            if not isinstance(policies, list) or not policies or any(
                not isinstance(item, str) or item not in policy_ids for item in policies
            ):
                errors.append(f"{prefix}: policies must contain only known core policy IDs")
                continue
            effect_floor = raw.get("effect_floor")
            if effect_floor not in effect_rank:
                errors.append(f"{prefix}: effect_floor must be one of {sorted(effect_rank)}")
                continue
            requires_execution_policy = raw.get("requires_execution_policy")
            if not isinstance(requires_execution_policy, bool):
                errors.append(f"{prefix}: requires_execution_policy must be boolean")
                continue
            lifecycle_status = raw.get("lifecycle_status")
            if lifecycle_status not in allowed_statuses:
                errors.append(f"{prefix}: lifecycle_status must be one of {sorted(allowed_statuses)}")
                continue
            supported_adapters = raw.get("supported_adapters")
            if (
                not isinstance(supported_adapters, list)
                or not supported_adapters
                or any(not isinstance(item, str) or not item.strip() for item in supported_adapters)
            ):
                errors.append(f"{prefix}: supported_adapters must be a non-empty string array")
                continue

            exposure_floor = raw.get("exposure_floor")
            if exposure_floor is not None and exposure_floor not in exposure_levels:
                errors.append(f"{prefix}: exposure_floor must be one of {sorted(exposure_levels)}")
            production_effect = raw.get("production_effect")
            if production_effect is not None:
                if production_effect not in effect_rank:
                    errors.append(f"{prefix}: production_effect must be one of {sorted(effect_rank)}")
                elif effect_rank[production_effect] < effect_rank[effect_floor]:
                    errors.append(f"{prefix}: production_effect cannot lower effect_floor")
            allowed_environments = raw.get("allowed_environments", [])
            if (
                not isinstance(allowed_environments, list)
                or any(item not in KNOWN_ENVIRONMENTS for item in allowed_environments)
            ):
                errors.append(f"{prefix}: allowed_environments contains an unknown environment")
            required_semantic_details = raw.get("required_semantic_details", [])
            if (
                not isinstance(required_semantic_details, list)
                or any(not isinstance(item, str) or not item for item in required_semantic_details)
            ):
                errors.append(f"{prefix}: required_semantic_details must be a string array")
            semantic_allowed = raw.get("semantic_detail_allowed_values", {})
            if not isinstance(semantic_allowed, dict) or any(
                not isinstance(key, str) or not isinstance(values, list)
                for key, values in semantic_allowed.items()
            ):
                errors.append(f"{prefix}: semantic_detail_allowed_values must map names to arrays")

            normalized = {
                "id": operation_id,
                "policies": sorted(set(policies)),
                "effect_floor": effect_floor,
                "requires_execution_policy": requires_execution_policy,
                "lifecycle_status": lifecycle_status,
                "supported_adapters": sorted(set(item.strip() for item in supported_adapters)),
                "extension_namespace": namespace,
            }
            for optional in (
                "replacement_operation", "deprecated_since_schema", "exposure_floor",
                "production_effect",
            ):
                if optional in raw:
                    normalized[optional] = raw[optional]
            if allowed_environments:
                normalized["allowed_environments"] = sorted(set(allowed_environments))
            if required_semantic_details:
                normalized["required_semantic_details"] = sorted(set(required_semantic_details))
            if semantic_allowed:
                normalized["semantic_detail_allowed_values"] = {
                    key: sorted(values, key=lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True))
                    for key, values in sorted(semantic_allowed.items())
                }

            operations[operation_id] = normalized
            normalized_operations.append({k: v for k, v in normalized.items() if k != "extension_namespace"})

        normalized_documents.append({
            "format": OPERATION_EXTENSION_FORMAT,
            "namespace": namespace,
            "operations": sorted(normalized_operations, key=lambda item: item["id"]),
        })

    all_operation_ids = set(core_operations) | set(operations)
    for operation_id, operation in operations.items():
        if operation.get("lifecycle_status") == "deprecated":
            replacement = operation.get("replacement_operation")
            deprecated_since = operation.get("deprecated_since_schema")
            if not isinstance(replacement, str) or replacement not in all_operation_ids:
                errors.append(
                    f"{operation_id}: deprecated extension operation requires a known replacement_operation"
                )
            if not isinstance(deprecated_since, int) or deprecated_since < 1:
                errors.append(
                    f"{operation_id}: deprecated extension operation requires deprecated_since_schema >= 1"
                )

    if errors:
        raise ValueError("operation extension validation failed: " + "; ".join(errors))

    normalized_documents.sort(key=lambda item: item["namespace"])
    combined_digest = _canonical_json_digest(normalized_documents)
    return {
        "format": OPERATION_EXTENSION_FORMAT,
        "namespaces": sorted(namespaces),
        "operations": operations,
        "combined_digest": combined_digest,
        "integrity": "MATCHED" if combined_digest in expected_digest_set else "UNVERIFIED",
        "authority": "NOT_ESTABLISHED",
        "diagnostic_sources": [_logical_source_name(path, root) for path in source_paths],
    }


def load_adapter_capabilities(
    paths: Iterable[Path | str],
    expected_digests: Iterable[str] = (),
    root: Path = ROOT,
) -> dict:
    """Load explicit adapter capability declarations.

    A capability declaration is independent evidence from the extension-side adapter
    allowlist. Digest matching proves exact semantics against a separately supplied
    expectation; it does not authenticate organization authority.
    """
    source_paths = [Path(path).resolve() for path in paths]
    expected_digest_set = {str(value).strip() for value in expected_digests if str(value).strip()}
    if not source_paths:
        return {
            "format": ADAPTER_CAPABILITIES_FORMAT,
            "adapters": {},
            "combined_digest": None,
            "integrity": "UNVERIFIED",
            "authority": "NOT_ESTABLISHED",
            "diagnostic_sources": [],
        }

    schema = load_json(root / "ADAPTER_CAPABILITIES.schema.json")
    errors: list[str] = []
    adapters: dict[str, dict] = {}
    normalized_documents: list[dict] = []
    for source_path in source_paths:
        try:
            document = load_json(source_path)
            if jsonschema is not None:
                jsonschema.validate(document, schema)
        except Exception as exc:
            errors.append(f"{source_path}: {exc}")
            continue
        if document.get("format") != ADAPTER_CAPABILITIES_FORMAT:
            errors.append(f"{source_path}: format must be {ADAPTER_CAPABILITIES_FORMAT!r}")
            continue
        adapter_id = str(document.get("adapter_id", "")).strip()
        if not adapter_id:
            errors.append(f"{source_path}: adapter_id must be non-empty")
            continue
        if adapter_id in adapters:
            errors.append(f"{source_path}: duplicate adapter capability declaration {adapter_id!r}")
            continue
        supported_operations = sorted(set(document.get("supported_operations", [])))
        normalized = {
            "format": ADAPTER_CAPABILITIES_FORMAT,
            "adapter_id": adapter_id,
            "supported_operations": supported_operations,
        }
        if document.get("version"):
            normalized["version"] = str(document["version"])
        normalized["document_digest"] = _canonical_json_digest({
            key: normalized[key] for key in normalized if key != "document_digest"
        })
        adapters[adapter_id] = normalized
        normalized_documents.append({
            key: normalized[key] for key in normalized if key != "document_digest"
        })

    if errors:
        raise ValueError("adapter capability validation failed: " + "; ".join(errors))

    normalized_documents.sort(key=lambda item: item["adapter_id"])
    combined_digest = _canonical_json_digest(normalized_documents)
    return {
        "format": ADAPTER_CAPABILITIES_FORMAT,
        "adapters": adapters,
        "combined_digest": combined_digest,
        "integrity": "MATCHED" if combined_digest in expected_digest_set else "UNVERIFIED",
        "authority": "NOT_ESTABLISHED",
        "diagnostic_sources": [_logical_source_name(path, root) for path in source_paths],
    }


def load_extension_runtime_inputs(
    extension_paths: Iterable[Path | str],
    capability_paths: Iterable[Path | str],
    contract: dict,
    expected_extension_digests: Iterable[str] = (),
    expected_capability_digests: Iterable[str] = (),
) -> tuple[dict | None, dict | None, dict, int]:
    """Load optional extension/capability inputs and return CLI-ready status without policy decisions."""
    result: dict = {}
    exit_code = 0
    extension_registry = None
    adapter_capabilities = None
    extension_paths = list(extension_paths)
    capability_paths = list(capability_paths)

    if extension_paths:
        try:
            extension_registry = load_operation_extensions(
                extension_paths, contract, expected_digests=expected_extension_digests
            )
            result["operation_extensions"] = {
                "status": "PASS",
                "schema": "VALID",
                "namespaces": extension_registry["namespaces"],
                "operation_ids": sorted(extension_registry["operations"]),
                "combined_digest": extension_registry["combined_digest"],
                "integrity": extension_registry["integrity"],
                "authority": extension_registry["authority"],
                "diagnostic_sources": extension_registry["diagnostic_sources"],
            }
        except Exception as exc:
            result["operation_extensions"] = {
                "status": "FAIL", "schema": "INVALID", "error": str(exc)
            }
            exit_code = 1

    if capability_paths:
        try:
            adapter_capabilities = load_adapter_capabilities(
                capability_paths, expected_digests=expected_capability_digests
            )
            result["adapter_capabilities"] = {
                "status": "PASS",
                "schema": "VALID",
                "adapter_ids": sorted(adapter_capabilities["adapters"]),
                "combined_digest": adapter_capabilities["combined_digest"],
                "integrity": adapter_capabilities["integrity"],
                "authority": adapter_capabilities["authority"],
                "diagnostic_sources": adapter_capabilities["diagnostic_sources"],
            }
        except Exception as exc:
            result["adapter_capabilities"] = {
                "status": "FAIL", "schema": "INVALID", "error": str(exc)
            }
            exit_code = 1

    return extension_registry, adapter_capabilities, result, exit_code


def canonical_policy_contract_digest(contract: dict) -> str:
    """Return a stable semantic SHA-256 for the machine policy contract.

    The project intentionally has no date/version suffix in its artifact name. Approval
    binding instead pins the exact canonical JSON semantics of POLICY_CONTRACT.json.
    """
    encoded = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
