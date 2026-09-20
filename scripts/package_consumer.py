#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate as policy_validate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
INSTALL_FORMAT = "universal-agent-docs-consumer-install-v1"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_consumer_agents(policy_root: str) -> bytes:
    source = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    def rewrite(match: re.Match[str]) -> str:
        label, dest = match.group(1), match.group(2)
        if dest == "PROJECT.md" or dest.startswith("PROJECT.md#"):
            return f"[{label}]({dest})"
        if dest.startswith(("http://", "https://", "#", policy_root + "/")):
            return match.group(0)
        return f"[{label}]({policy_root}/{dest})"

    rewritten = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", rewrite, source)
    lines = rewritten.splitlines()
    banner = (
        "> Consumer layout: the canonical universal-agent-docs runtime core is vendored under "
        f"`{policy_root}/`. Project-specific facts live in the consuming repository's root "
        f"`PROJECT.md`; `{policy_root}/PROJECT.md` is the upstream template copy only. "
        f"Run readiness with `python {policy_root}/scripts/validate.py --readiness development "
        "--project-file ./PROJECT.md --project-root .`."
    )
    return (lines[0] + "\n\n" + banner + "\n\n" + "\n".join(lines[1:]) + "\n").encode("utf-8")


def render_install_marker(contract: dict) -> bytes:
    cfg = contract["consumer_distribution"]
    marker = {
        "format": INSTALL_FORMAT,
        "policy_schema_version": contract["schema_version"],
        "policy_contract_digest": policy_validate.canonical_policy_contract_digest(contract),
        "vendored_files": list(cfg["vendored_files"]),
    }
    return (json.dumps(marker, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _consumer_expected(contract: dict) -> tuple[str, str, list[str]]:
    cfg = contract["consumer_distribution"]
    root = cfg["canonical_root"]
    policy_root = cfg["policy_root"]
    expected = [cfg["root_agents_path"]]
    expected += [f"{policy_root}/{rel}" for rel in cfg["vendored_files"]]
    expected.append(f"{policy_root}/{cfg['install_marker_path']}")
    return root, policy_root, expected


def _source_for_vendored(contract: dict, installed_rel: str) -> str:
    overrides = contract["consumer_distribution"].get("vendored_file_source_overrides", {})
    return overrides.get(installed_rel, installed_rel)


def _write_entry(zf: zipfile.ZipFile, arcname: str, data: bytes, executable: bool = False) -> None:
    info = zipfile.ZipInfo(arcname, FIXED_ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    mode = 0o755 if executable else 0o644
    info.external_attr = (0o100000 | mode) << 16
    zf.writestr(info, data)


def validate_consumer_zip(path: Path, contract: dict, release_manifest: Path | None = None) -> dict:
    root, policy_root, expected = _consumer_expected(contract)
    if not path.is_file() or not zipfile.is_zipfile(path):
        return {"status": "FAIL", "errors": ["consumer distribution must be a ZIP archive"], "checked_files": 0}

    cfg = contract["distribution"]
    consumer_cfg = contract["consumer_distribution"]
    prefix = root + "/"
    errors: list[str] = []
    safe_files: dict[str, zipfile.ZipInfo] = {}
    normalized_full_seen: set[str] = set()
    duplicate_entries: list[str] = []
    normalized_names: list[str] = []
    resource_entries: list[tuple[str, int, int]] = []
    symlinks: list[str] = []
    outside_root: list[str] = []

    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            normalized, error = policy_validate.normalize_archive_entry(info.filename)
            if error or normalized is None:
                errors.append(f"unsafe consumer ZIP entry: {info.filename}: {error}")
                continue
            if normalized in normalized_full_seen and not info.is_dir():
                duplicate_entries.append(normalized)
            normalized_full_seen.add(normalized)
            normalized_names.append(normalized)
            resource_entries.append((normalized, info.file_size, -1 if info.is_dir() else info.compress_size))

            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                symlinks.append(normalized)
                continue
            if info.is_dir():
                continue
            if not normalized.startswith(prefix):
                outside_root.append(normalized)
                continue
            rel = normalized[len(prefix):]
            if not rel:
                errors.append(f"unsafe consumer ZIP entry: {info.filename}: empty relative path")
                continue
            safe_files[rel] = info

        if duplicate_entries and cfg["reject_duplicate_entries"]:
            errors.append("consumer ZIP duplicate entries: " + ", ".join(sorted(set(duplicate_entries))))
        collisions = policy_validate._name_collision_checks(normalized_names, cfg)
        if collisions:
            errors.extend(collisions)
        limit_errors = policy_validate._resource_limit_checks(resource_entries, cfg)
        if limit_errors:
            errors.extend(limit_errors)
        if symlinks and cfg["reject_symlinks"]:
            errors.append("consumer ZIP symlinks: " + ", ".join(sorted(symlinks)))
        if outside_root:
            errors.append("consumer ZIP entries outside canonical root: " + ", ".join(sorted(outside_root)))

        rels = sorted(safe_files)
        missing = sorted(set(expected) - set(rels))
        extra = sorted(set(rels) - set(expected))
        if missing:
            errors.append("consumer ZIP missing: " + ", ".join(missing))
        if extra:
            errors.append("consumer ZIP has unexpected files: " + ", ".join(extra))
        forbidden = sorted(rel for rel in rels if policy_validate.forbidden_path(rel, cfg["forbidden_patterns"]))
        if forbidden:
            errors.append("consumer ZIP contains forbidden files: " + ", ".join(forbidden))

        if not errors:
            root_agents_rel = consumer_cfg["root_agents_path"]
            if zf.read(prefix + root_agents_rel) != render_consumer_agents(policy_root):
                errors.append("consumer root AGENTS.md does not match canonical generated router")

        marker_rel = f"{policy_root}/{consumer_cfg['install_marker_path']}"
        if not errors:
            try:
                marker = json.loads(zf.read(prefix + marker_rel).decode("utf-8"))
            except Exception as exc:
                errors.append(f"consumer install marker: {exc}")
            else:
                expected_marker = json.loads(render_install_marker(contract).decode("utf-8"))
                if marker != expected_marker:
                    errors.append("consumer install marker mismatch")

        if not errors:
            with tempfile.TemporaryDirectory() as td:
                nested = Path(td) / "policy"
                nested.mkdir()
                for rel in consumer_cfg["vendored_files"]:
                    target = nested / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(zf.read(prefix + policy_root + "/" + rel))
                marker_target = nested / consumer_cfg["install_marker_path"]
                marker_target.write_bytes(zf.read(prefix + marker_rel))
                failures = [c for c in policy_validate.bundle_checks(nested) if c.status != "PASS"]
                errors.extend(f"nested consumer core {c.name}: {c.detail}" for c in failures)

        if release_manifest is not None and not errors:
            try:
                manifest = json.loads(release_manifest.read_text(encoding="utf-8"))
            except Exception as exc:
                errors.append(f"consumer release manifest: {exc}")
            else:
                if manifest.get("format") != consumer_cfg["release_manifest_format"]:
                    errors.append("consumer release manifest format mismatch")
                if manifest.get("artifact_name") != path.name:
                    errors.append("consumer release manifest artifact_name mismatch")
                if manifest.get("artifact_sha256") != _sha256_file(path):
                    errors.append("consumer release manifest artifact_sha256 mismatch")
                file_hashes = manifest.get("files", {})
                if set(file_hashes) != set(expected):
                    errors.append("consumer release manifest file set mismatch")
                else:
                    for rel in expected:
                        if file_hashes[rel] != _sha256_bytes(zf.read(prefix + rel)):
                            errors.append(f"consumer release manifest hash mismatch: {rel}")

    return {"status": "FAIL" if errors else "PASS", "errors": errors, "checked_files": len(expected)}


def package_consumer(output_dir: Path) -> dict:
    failures = [c for c in policy_validate.bundle_checks(ROOT) if c.status != "PASS"]
    if failures:
        raise RuntimeError("source bundle validation failed: " + "; ".join(f"{c.name}: {c.detail}" for c in failures))

    contract = policy_validate.load_json(ROOT / "POLICY_CONTRACT.json")
    cfg = contract["consumer_distribution"]
    root, policy_root, _ = _consumer_expected(contract)
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / "universal-agent-docs-consumer.zip"
    release_path = output_dir / "universal-agent-docs-consumer.release.json"
    sha_path = output_dir / "universal-agent-docs-consumer.sha256"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
        _write_entry(zf, f"{root}/{cfg['root_agents_path']}", render_consumer_agents(policy_root))
        for installed_rel in cfg["vendored_files"]:
            source_rel = _source_for_vendored(contract, installed_rel)
            source = ROOT / source_rel
            if not source.is_file():
                raise FileNotFoundError(f"consumer source file is missing: {source_rel}")
            executable = installed_rel.startswith("scripts/") and installed_rel.endswith(".py")
            _write_entry(zf, f"{root}/{policy_root}/{installed_rel}", source.read_bytes(), executable)
        _write_entry(
            zf,
            f"{root}/{policy_root}/{cfg['install_marker_path']}",
            render_install_marker(contract),
        )

    with zipfile.ZipFile(zip_path) as zf:
        prefix = root + "/"
        _, _, expected = _consumer_expected(contract)
        file_hashes = {rel: _sha256_bytes(zf.read(prefix + rel)) for rel in expected}
    manifest = {
        "format": cfg["release_manifest_format"],
        "project_name": contract["project_name"],
        "policy_schema_version": contract["schema_version"],
        "policy_contract_digest": policy_validate.canonical_policy_contract_digest(contract),
        "artifact_name": zip_path.name,
        "artifact_sha256": _sha256_file(zip_path),
        "files": file_hashes,
    }
    release_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sha_path.write_text(f"{manifest['artifact_sha256']}  {zip_path.name}\n", encoding="utf-8")

    validation = validate_consumer_zip(zip_path, contract, release_path)
    if validation["status"] != "PASS":
        raise RuntimeError("consumer package self-validation failed: " + json.dumps(validation, ensure_ascii=False))
    return {
        "status": "PASS",
        "zip": str(zip_path),
        "release_manifest": str(release_path),
        "sha256_file": str(sha_path),
        "validation": validation,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or verify the slim collision-safe consumer policy bundle")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--release-manifest", type=Path)
    args = parser.parse_args()
    contract = policy_validate.load_json(ROOT / "POLICY_CONTRACT.json")
    if args.verify:
        result = validate_consumer_zip(
            args.verify.resolve(), contract,
            args.release_manifest.resolve() if args.release_manifest else None,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "PASS" else 1
    try:
        result = package_consumer(args.output_dir.resolve())
    except Exception as exc:
        print(f"Consumer packaging: FAIL — {exc}", file=sys.stderr)
        return 1
    print("Consumer packaging: PASS")
    print("ZIP:", result["zip"])
    print("Detached consumer release manifest:", result["release_manifest"])
    print("SHA file:", result["sha256_file"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
