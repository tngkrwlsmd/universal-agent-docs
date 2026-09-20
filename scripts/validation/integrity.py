from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .contract import (
    CANONICAL_ROOT,
    CONTRACT_PATH,
    RELEASE_MANIFEST_FORMAT,
    ROOT,
    TRUSTED_CORE_FILES,
    TRUST_MANIFEST_FORMAT,
    load_json,
)

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
