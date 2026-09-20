#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate as policy_validate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_consumer_agents(policy_root: str, project_file: str = "PROJECT.md") -> bytes:
    source = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    def rewrite(match: re.Match[str]) -> str:
        label, dest = match.group(1), match.group(2)
        if dest.startswith(("http://", "https://", "#", policy_root + "/")):
            return match.group(0)
        if dest == "PROJECT.md":
            return f"[{label}]({project_file})"
        return f"[{label}]({policy_root}/{dest})"

    rewritten = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", rewrite, source)
    lines = rewritten.splitlines()
    banner = (
        "> Consumer layout: the canonical universal-agent-docs bundle is vendored under "
        f"`{policy_root}/`. Bare policy filenames mentioned below refer to that directory; "
        f"project facts are project-owned and default to `{project_file}` relative to the consuming repository root. "
        "Use validator --project-file/--project-root when the project uses another location."
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
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    mode = 0o755 if executable else 0o644
    info.external_attr = (0o100000 | mode) << 16
    zf.writestr(info, data)


def validate_consumer_zip(path: Path, contract: dict, release_manifest: Path | None = None) -> dict:
    root, policy_root, expected = _consumer_expected(contract)
    if not path.is_file() or not zipfile.is_zipfile(path):
        return {"status":"FAIL","errors":["consumer distribution must be a ZIP archive"]}
    errors: list[str] = []
    prefix = root + "/"
    with zipfile.ZipFile(path) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        names = [i.filename for i in infos]
        if len(names) != len(set(names)):
            errors.append("consumer ZIP contains duplicate entries")
        rels: list[str] = []
        for name in names:
            normalized, error = policy_validate.normalize_archive_entry(name)
            if error or normalized is None:
                errors.append(f"unsafe consumer ZIP entry: {name}")
                continue
            if not normalized.startswith(prefix):
                errors.append(f"consumer ZIP entry is outside canonical root: {name}")
                continue
            rels.append(normalized[len(prefix):])
        if sorted(rels) != sorted(expected):
            missing = sorted(set(expected) - set(rels))
            extra = sorted(set(rels) - set(expected))
            if missing:
                errors.append("consumer ZIP missing: " + ", ".join(missing))
            if extra:
                errors.append("consumer ZIP has unexpected files: " + ", ".join(extra))

        root_agents_name = prefix + contract["consumer_distribution"]["root_agents_path"]
        if root_agents_name in names and zf.read(root_agents_name) != render_consumer_agents(policy_root, contract["consumer_distribution"]["project_file_default"]):
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

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        _write_entry(zf, f"{root}/AGENTS.md", render_consumer_agents(policy_root, contract["consumer_distribution"]["project_file_default"]))
        for rel in contract["distribution"]["required_files"]:
            data = (ROOT / rel).read_bytes()
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
    return {"status":"PASS","zip":str(zip_path),"release_manifest":str(release_path),"sha256_file":str(sha_path),"validation":validation}


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
    print("Detached consumer release manifest:", result["release_manifest"])
    print("SHA file:", result["sha256_file"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
