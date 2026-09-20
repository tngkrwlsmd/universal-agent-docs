from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
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
    "scripts/validate.py",
    "scripts/validation/__init__.py",
    "scripts/validation/contract.py",
    "scripts/validation/routing.py",
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
    "README.md",
    "LICENSE",
    "requirements.txt",
    "requirements.lock",
    "scripts/validate.py",
    "scripts/validation/__init__.py",
    "scripts/validation/contract.py",
    "scripts/validation/routing.py",
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
    "tests/test_policy.py",
    "tests/test_fuzz.py",
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
    ".github/workflows/verify-release.yml",
    "conformance/README.md",
    "conformance/schema.json",
    "conformance/result.schema.json",
    "conformance/suite.json",
    "conformance/reference_runner.py",
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
