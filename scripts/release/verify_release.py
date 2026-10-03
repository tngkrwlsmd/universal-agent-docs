#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ASSET_NAMES = (
    "universal-agent-docs.zip",
    "universal-agent-docs.sha256",
    "universal-agent-docs.trust.json",
    "universal-agent-docs.release.json",
    "universal-agent-docs-consumer.zip",
    "universal-agent-docs-consumer.sha256",
    "universal-agent-docs-consumer.release.json",
)
DEFAULT_ATTEMPTS = 4
DEFAULT_BASE_DELAY_SECONDS = 10
SOURCE_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def backoff_delay_seconds(failed_attempt: int, base_delay_seconds: int) -> int:
    if failed_attempt < 1:
        raise ValueError("failed_attempt must be >= 1")
    if base_delay_seconds < 0:
        raise ValueError("base_delay_seconds must be >= 0")
    return base_delay_seconds * (2 ** (failed_attempt - 1))


def _run(command: list[str]) -> bool:
    return subprocess.run(command, check=False).returncode == 0


def _require(command: list[str]) -> None:
    subprocess.run(command, check=True)


def _require_assets(asset_dir: Path) -> None:
    missing = [name for name in ASSET_NAMES if not (asset_dir / name).is_file()]
    if missing:
        raise RuntimeError("missing release asset(s): " + ", ".join(missing))


def verify_release_attestation(
    *,
    repo: str,
    tag: str,
    asset_dir: Path,
    attempts: int = DEFAULT_ATTEMPTS,
    base_delay_seconds: int = DEFAULT_BASE_DELAY_SECONDS,
) -> None:
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    _require_assets(asset_dir)

    for attempt in range(1, attempts + 1):
        verified = _run(["gh", "release", "verify", tag, "--repo", repo])
        if verified:
            for name in ASSET_NAMES:
                if not _run([
                    "gh",
                    "release",
                    "verify-asset",
                    tag,
                    str(asset_dir / name),
                    "--repo",
                    repo,
                ]):
                    verified = False
                    break

        if verified:
            print(f"immutable release attestation verified on attempt {attempt}")
            return

        if attempt == attempts:
            raise RuntimeError(
                f"immutable release attestation did not become available after {attempts} attempts"
            )

        delay = backoff_delay_seconds(attempt, base_delay_seconds)
        print(
            f"release attestation not ready; retrying in {delay}s "
            f"(attempt {attempt}/{attempts})",
            file=sys.stderr,
        )
        time.sleep(delay)


def verify_build_provenance(
    *,
    repo: str,
    tag: str,
    source_sha: str,
    asset_dir: Path,
    signer_workflow: str | None = None,
) -> None:
    if not SOURCE_SHA_RE.fullmatch(source_sha):
        raise ValueError("source_sha must be a lowercase 40-hex commit SHA")
    _require_assets(asset_dir)
    signer = signer_workflow or f"github.com/{repo}/.github/workflows/release.yml"

    for name in ASSET_NAMES:
        _require([
            "gh",
            "attestation",
            "verify",
            str(asset_dir / name),
            "--repo",
            repo,
            "--signer-workflow",
            signer,
            "--source-ref",
            f"refs/tags/{tag}",
            "--source-digest",
            source_sha,
        ])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify universal-agent-docs release attestation and build provenance"
    )
    parser.add_argument("--mode", choices=("release", "provenance", "all"), default="all")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-sha", default="")
    parser.add_argument("--asset-dir", type=Path, required=True)
    parser.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS)
    parser.add_argument("--base-delay-seconds", type=int, default=DEFAULT_BASE_DELAY_SECONDS)
    parser.add_argument("--signer-workflow")
    args = parser.parse_args()

    if not args.repo:
        parser.error("--repo is required when GITHUB_REPOSITORY is not set")

    asset_dir = args.asset_dir.resolve()
    try:
        if args.mode in {"release", "all"}:
            verify_release_attestation(
                repo=args.repo,
                tag=args.tag,
                asset_dir=asset_dir,
                attempts=args.attempts,
                base_delay_seconds=args.base_delay_seconds,
            )
        if args.mode in {"provenance", "all"}:
            if not args.source_sha:
                parser.error("--source-sha is required for provenance verification")
            verify_build_provenance(
                repo=args.repo,
                tag=args.tag,
                source_sha=args.source_sha,
                asset_dir=asset_dir,
                signer_workflow=args.signer_workflow,
            )
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"release verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
