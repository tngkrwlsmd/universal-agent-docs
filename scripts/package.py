#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

# Import the validator from the same scripts directory without installing a package.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate as policy_validate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def sha256_bytes(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_deterministic_zip(output: Path, files: list[str], canonical_root: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as zf:
        for rel in files:
            source = ROOT / rel
            if not source.is_file():
                raise FileNotFoundError(f"required distribution file is missing: {rel}")
            info = zipfile.ZipInfo(f"{canonical_root}/{rel}", FIXED_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            # Regular file with portable read permissions; executable bit only for scripts.
            mode = 0o755 if rel.startswith("scripts/") and rel.endswith(".py") else 0o644
            info.external_attr = (0o100000 | mode) << 16
            zf.writestr(info, source.read_bytes())


def package(output_dir: Path) -> dict:
    checks = policy_validate.bundle_checks(ROOT)
    failures = [c for c in checks if c.status != "PASS"]
    if failures:
        raise RuntimeError(
            "bundle validation failed before packaging: "
            + "; ".join(f"{c.name}: {c.detail}" for c in failures)
        )

    contract = policy_validate.load_json(ROOT / "POLICY_CONTRACT.json")
    canonical_root = contract["distribution"]["canonical_root"]
    files = list(contract["distribution"]["required_files"])
    stem = canonical_root
    zip_path = output_dir / f"{stem}.zip"
    trust_path = output_dir / f"{stem}.trust.json"
    release_path = output_dir / f"{stem}.release.json"
    sha_path = output_dir / f"{stem}.sha256"

    write_deterministic_zip(zip_path, files, canonical_root)
    policy_validate.write_trust_manifest(trust_path, ROOT)
    policy_validate.write_release_manifest(release_path, zip_path, ROOT)

    distribution = policy_validate.validate_distribution(zip_path, contract, trust_path, release_path)
    if distribution["status"] != "PASS":
        raise RuntimeError("packaged ZIP failed distribution validation: " + json.dumps(distribution, ensure_ascii=False))

    digest = sha256_bytes(zip_path)
    sha_path.write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8")

    return {
        "status": "PASS",
        "project_name": canonical_root,
        "zip": str(zip_path),
        "sha256": digest,
        "sha256_file": str(sha_path),
        "trust_manifest": str(trust_path),
        "release_manifest": str(release_path),
        "distribution": distribution,
        "note": "Keep the trusted-core and full-release manifests in an independent trusted channel; integrity manifests do not authenticate the publisher by themselves.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and self-verify a canonical universal-agent-docs release bundle")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    try:
        result = package(args.output_dir.resolve())
    except Exception as exc:
        if args.as_json:
            print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"Packaging: FAIL — {exc}", file=sys.stderr)
        return 1

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("Packaging: PASS")
        print("ZIP:", result["zip"])
        print("SHA-256:", result["sha256"])
        print("Detached core trust manifest:", result["trust_manifest"])
        print("Detached full release manifest:", result["release_manifest"])
        print("SHA file:", result["sha256_file"])
        print(result["note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
