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

CONSUMER_DOC_REPLACEMENTS = {
    "README.md": {
        "[Profile A/B consumer example](examples/consumer-basic/README.md)": "matching canonical source artifact의 `examples/consumer-basic/README.md`",
        "[runtime adapter examples](examples/runtime-adapter/README.md)": "matching canonical source artifact의 `examples/runtime-adapter/README.md`",
    },
    "docs/adoption-profiles.md": {
        "[Profile A/B consumer example](../examples/consumer-basic/README.md)": "matching canonical source artifact의 `examples/consumer-basic/README.md`",
    },
}


def render_consumer_vendored_file(rel: str) -> bytes:
    source_path = ROOT / "templates" / "PROJECT.md" if rel == "PROJECT.md" else ROOT / rel
    data = source_path.read_bytes()
    replacements = CONSUMER_DOC_REPLACEMENTS.get(rel)
    if not replacements:
        return data
    text = data.decode("utf-8")
    for old, new in replacements.items():
        if old not in text:
            raise ValueError(f"consumer documentation replacement is stale for {rel}: {old}")
        text = text.replace(old, new)
    return text.encode("utf-8")


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
        if dest.startswith(("http://", "https://", "#", policy_root + "/")):
            return match.group(0)
        return f"[{label}]({policy_root}/{dest})"

    rewritten = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", rewrite, source)
    lines = rewritten.splitlines()
    banner = (
        "> Consumer layout: the canonical universal-agent-docs bundle is vendored under "
        f"`{policy_root}/`. Bare policy filenames mentioned below refer to that directory; "
        f"project facts live at `{policy_root}/PROJECT.md`. When validating readiness, run "
        f"`python {policy_root}/scripts/validate.py --project-root . --readiness development` "
        "from the consuming repository root so evidence paths and Git revision checks target the project, not the vendored policy directory."
    )
    return (lines[0] + "\n\n" + banner + "\n\n" + "\n".join(lines[1:]) + "\n").encode("utf-8")


def _consumer_expected(contract: dict) -> tuple[str, str, list[str]]:
    cfg = contract["consumer_distribution"]
    root = cfg["canonical_root"]
    policy_root = cfg["policy_root"]
    expected = [cfg["root_agents_path"]] + [
        f"{policy_root}/{rel}" for rel in contract["distribution"]["required_files"]
    ]
    return root, policy_root, expected


def _write_entry(zf: zipfile.ZipFile, arcname: str, data: bytes, executable: bool = False) -> None:
    info = zipfile.ZipInfo(arcname, FIXED_ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    mode = 0o755 if executable else 0o644
    info.external_attr = (0o100000 | mode) << 16
    zf.writestr(info, data)


def validate_consumer_zip(path: Path, contract: dict, release_manifest: Path | None = None) -> dict:
    root, policy_root, expected = _consumer_expected(contract)
    cfg = contract["distribution"]
    if not path.is_file() or not zipfile.is_zipfile(path):
        return {"status":"FAIL","errors":["consumer distribution must be a ZIP archive"]}

    errors: list[str] = []
    prefix = root + "/"
    with zipfile.ZipFile(path) as zf:
        normalized_seen: set[str] = set()
        normalized_files: list[str] = []
        resource_entries: list[tuple[str, int, int]] = []
        rels: list[str] = []
        names: list[str] = []
        duplicates: list[str] = []
        symlinks: list[str] = []

        for info in zf.infolist():
            normalized, error = policy_validate.normalize_archive_entry(info.filename)
            if error or normalized is None:
                errors.append(f"unsafe consumer ZIP entry: {info.filename}: {error or 'invalid path'}")
                continue
            if normalized in normalized_seen and not info.is_dir():
                duplicates.append(normalized)
            normalized_seen.add(normalized)

            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                symlinks.append(normalized)
                continue
            if info.is_dir():
                resource_entries.append((normalized, 0, -1))
                continue

            normalized_files.append(normalized)
            resource_entries.append((normalized, info.file_size, info.compress_size))
            names.append(normalized)
            if not normalized.startswith(prefix):
                errors.append(f"consumer ZIP entry is outside canonical root: {info.filename}")
                continue
            rels.append(normalized[len(prefix):])

        if duplicates:
            errors.append("consumer ZIP contains duplicate entries: " + ", ".join(sorted(set(duplicates))))
        if symlinks and cfg.get("reject_symlinks", True):
            errors.append("consumer ZIP contains symlink entries: " + ", ".join(sorted(symlinks)))
        errors.extend(policy_validate._name_collision_checks(normalized_files, cfg))
        errors.extend(policy_validate._resource_limit_checks(resource_entries, cfg))

        forbidden = sorted(rel for rel in rels if policy_validate.forbidden_path(rel, cfg.get("forbidden_patterns", [])))
        if forbidden:
            errors.append("consumer ZIP contains forbidden paths: " + ", ".join(forbidden))

        if sorted(rels) != sorted(expected):
            missing = sorted(set(expected) - set(rels))
            extra = sorted(set(rels) - set(expected))
            if missing:
                errors.append("consumer ZIP missing: " + ", ".join(missing))
            if extra:
                errors.append("consumer ZIP has unexpected files: " + ", ".join(extra))

        root_agents_name = prefix + contract["consumer_distribution"]["root_agents_path"]
        if root_agents_name in names and zf.read(root_agents_name) != render_consumer_agents(policy_root):
            errors.append("consumer root AGENTS.md does not match canonical generated router")

        if not errors:
            with tempfile.TemporaryDirectory() as td:
                nested = Path(td) / "policy"
                nested.mkdir()
                for rel in contract["distribution"]["required_files"]:
                    target = nested / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(zf.read(prefix + policy_root + "/" + rel))
                failures = [c for c in policy_validate.bundle_checks(nested) if c.status != "PASS"]
                errors.extend(f"nested bundle {c.name}: {c.detail}" for c in failures)

        if release_manifest is not None and not errors:
            try:
                manifest = json.loads(release_manifest.read_text(encoding="utf-8"))
            except Exception as exc:
                errors.append(f"consumer release manifest: {exc}")
            else:
                if manifest.get("format") != contract["consumer_distribution"]["release_manifest_format"]:
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

    return {"status":"FAIL" if errors else "PASS","errors":errors,"checked_files":len(expected)}


def package_consumer(output_dir: Path) -> dict:
    failures = [c for c in policy_validate.bundle_checks(ROOT) if c.status != "PASS"]
    if failures:
        raise RuntimeError("source bundle validation failed: " + "; ".join(f"{c.name}: {c.detail}" for c in failures))

    contract = policy_validate.load_json(ROOT / "POLICY_CONTRACT.json")
    root, policy_root, expected = _consumer_expected(contract)
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / "universal-agent-docs-consumer.zip"
    release_path = output_dir / "universal-agent-docs-consumer.release.json"
    sha_path = output_dir / "universal-agent-docs-consumer.sha256"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
        _write_entry(zf, f"{root}/AGENTS.md", render_consumer_agents(policy_root))
        for rel in contract["distribution"]["required_files"]:
            data = render_consumer_vendored_file(rel)
            executable = rel.startswith("scripts/") and rel.endswith(".py")
            _write_entry(zf, f"{root}/{policy_root}/{rel}", data, executable)

    with zipfile.ZipFile(zip_path) as zf:
        prefix = root + "/"
        file_hashes = {rel:_sha256_bytes(zf.read(prefix + rel)) for rel in expected}
    manifest = {
        "format": contract["consumer_distribution"]["release_manifest_format"],
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
    return {"status":"PASS","zip":str(zip_path),"sha256":manifest["artifact_sha256"],"release_manifest":str(release_path),"sha256_file":str(sha_path),"validation":validation}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or verify the collision-safe consumer policy bundle")
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
    print("SHA-256:", result["sha256"])
    print("Detached consumer release manifest:", result["release_manifest"])
    print("SHA file:", result["sha256_file"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
