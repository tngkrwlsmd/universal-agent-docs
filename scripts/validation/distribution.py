from __future__ import annotations

import fnmatch
import posixpath
import re
import stat
import tempfile
import unicodedata
import zipfile
from pathlib import Path
from typing import Iterable

from .bundle import bundle_checks
from .integrity import verify_release_manifest, verify_trust_manifest

def forbidden_path(name: str, patterns: Iterable[str]) -> bool:
    normalized = name.replace("\\", "/").lstrip("./")
    for pattern in patterns:
        if pattern.endswith("/") and pattern[:-1] in normalized.split("/"):
            return True
        if fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(Path(normalized).name, pattern):
            return True
    return False


def normalize_archive_entry(name: str) -> tuple[str | None, str | None]:
    if "\x00" in name:
        return None, "NUL byte in archive path"
    raw = name.replace("\\", "/")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:/", raw):
        return None, "absolute archive path"
    if ".." in raw.split("/"):
        return None, "archive path traversal component"
    normalized = posixpath.normpath(raw)
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        return None, "archive path traversal"
    return normalized, None


def _distribution_result(**kwargs) -> dict:
    categories = [
        "missing", "unexpected", "forbidden", "unsafe_entries", "duplicate_entries", "name_collisions",
        "resource_limit_violations", "symlinks", "outside_root", "bundle_failures", "integrity_failures",
        "release_integrity_failures"
    ]
    failed = any(kwargs.get(key) for key in categories)
    kwargs["status"] = "FAIL" if failed else "PASS"
    return kwargs


def _archive_collision_key(name: str) -> tuple[str, str]:
    return unicodedata.normalize("NFKC", name), unicodedata.normalize("NFKC", name).casefold()


def _resource_limit_checks(entries: list[tuple[str, int, int]], cfg: dict) -> list[str]:
    """entries are (name, uncompressed_size, compressed_size); compressed_size=-1 for directories."""
    violations: list[str] = []
    if len(entries) > cfg["max_archive_entries"]:
        violations.append(f"entry count {len(entries)} exceeds max_archive_entries={cfg['max_archive_entries']}")
    total = sum(size for _, size, _ in entries)
    if total > cfg["max_total_uncompressed_bytes"]:
        violations.append(
            f"total uncompressed bytes {total} exceeds max_total_uncompressed_bytes={cfg['max_total_uncompressed_bytes']}"
        )
    for name, size, compressed in entries:
        if size > cfg["max_file_uncompressed_bytes"]:
            violations.append(
                f"{name}: uncompressed bytes {size} exceeds max_file_uncompressed_bytes={cfg['max_file_uncompressed_bytes']}"
            )
        if compressed >= 0 and size > 0:
            ratio = float("inf") if compressed == 0 else size / compressed
            if ratio > cfg["max_compression_ratio"]:
                violations.append(
                    f"{name}: compression ratio {ratio:.1f} exceeds max_compression_ratio={cfg['max_compression_ratio']}"
                )
    return violations


def _name_collision_checks(names: list[str], cfg: dict) -> list[str]:
    collisions: list[str] = []
    nfkc_seen: dict[str, str] = {}
    case_seen: dict[str, str] = {}
    for name in names:
        nfkc, folded = _archive_collision_key(name)
        if cfg["reject_unicode_normalization_collisions"]:
            prior = nfkc_seen.get(nfkc)
            if prior is not None and prior != name:
                collisions.append(f"unicode normalization collision: {prior!r} vs {name!r}")
            else:
                nfkc_seen[nfkc] = name
        if cfg["reject_casefold_collisions"]:
            prior = case_seen.get(folded)
            if prior is not None and prior != name:
                collisions.append(f"case-insensitive collision: {prior!r} vs {name!r}")
            else:
                case_seen[folded] = name
    return sorted(set(collisions))


def validate_distribution(path: Path, contract: dict, trusted_manifest: Path | None = None, release_manifest: Path | None = None) -> dict:
    cfg = contract["distribution"]
    canonical_root = cfg["canonical_root"]
    required = list(cfg["required_files"])
    allowed = set(cfg["allowed_files"])
    patterns = cfg["forbidden_patterns"]

    base = {
        "detail": "",
        "missing": [],
        "unexpected": [],
        "forbidden": [],
        "unsafe_entries": [],
        "duplicate_entries": [],
        "name_collisions": [],
        "resource_limit_violations": [],
        "symlinks": [],
        "outside_root": [],
        "bundle_failures": [],
        "integrity_failures": [],
        "release_integrity_failures": [],
    }

    def evaluate_bundle(bundle_root: Path, names: list[str], entries: list[tuple[str, int, int]]) -> dict:
        result = dict(base)
        unique_names = sorted(set(names))
        result["missing"] = sorted(set(required) - set(unique_names))
        if not cfg["allow_unlisted_files"]:
            result["unexpected"] = sorted(set(unique_names) - allowed)
        result["forbidden"] = sorted(x for x in unique_names if forbidden_path(x, patterns))
        result["name_collisions"] = _name_collision_checks(names, cfg)
        result["resource_limit_violations"] = _resource_limit_checks(entries, cfg)
        prelim = any(result[k] for k in [
            "missing", "unexpected", "forbidden", "name_collisions", "resource_limit_violations"
        ])
        if cfg["run_bundle_checks"] and not prelim:
            failures = [c for c in bundle_checks(bundle_root) if c.status != "PASS"]
            result["bundle_failures"] = [f"{c.name}: {c.detail}" for c in failures]
            if trusted_manifest is not None and not result["bundle_failures"]:
                integrity_result = verify_trust_manifest(trusted_manifest, bundle_root)
                result["integrity_failures"] = integrity_result["errors"]
        result["detail"] = f"checked {len(unique_names)} files against canonical manifest"
        return _distribution_result(**result)

    if path.is_dir():
        if (path / "AGENTS.md").is_file():
            bundle_root = path
            outside = []
        elif (path / canonical_root).is_dir():
            bundle_root = path / canonical_root
            outside = [str(p.relative_to(path)).replace("\\", "/") for p in path.rglob("*") if p.is_file() and canonical_root not in p.relative_to(path).parts[:1]]
        else:
            result = dict(base)
            result["detail"] = f"directory must be the bundle root or contain {canonical_root}/"
            result["missing"] = required
            return _distribution_result(**result)

        names: list[str] = []
        entries: list[tuple[str, int, int]] = []
        symlinks: list[str] = []
        for p in bundle_root.rglob("*"):
            rel = str(p.relative_to(bundle_root)).replace("\\", "/")
            if p.is_symlink():
                symlinks.append(rel)
            elif p.is_file():
                names.append(rel)
                try:
                    size = p.stat().st_size
                except OSError:
                    size = cfg["max_file_uncompressed_bytes"] + 1
                entries.append((rel, size, -1))
        result = evaluate_bundle(bundle_root, names, entries)
        if release_manifest is not None:
            result["release_integrity_failures"] = ["full release manifest binds the canonical ZIP artifact; verify it against the ZIP rather than an extracted directory"]
        result["outside_root"] = sorted(outside)
        result["symlinks"] = sorted(symlinks) if cfg["reject_symlinks"] else []
        return _distribution_result(**result)

    if not (path.is_file() and zipfile.is_zipfile(path)):
        result = dict(base)
        result["detail"] = "distribution target must be a directory or ZIP archive"
        result["missing"] = required
        return _distribution_result(**result)

    names: list[str] = []
    all_normalized_files: list[str] = []
    normalized_full_seen: set[str] = set()
    duplicate_entries: list[str] = []
    unsafe_entries: list[str] = []
    symlinks: list[str] = []
    outside_root: list[str] = []
    resource_entries: list[tuple[str, int, int]] = []

    with zipfile.ZipFile(path) as zf:
        safe_files: list[tuple[zipfile.ZipInfo, str]] = []
        for info in zf.infolist():
            normalized, error = normalize_archive_entry(info.filename)
            if error:
                unsafe_entries.append(f"{info.filename}: {error}")
                continue
            assert normalized is not None
            if normalized in normalized_full_seen and not info.is_dir():
                duplicate_entries.append(normalized)
            normalized_full_seen.add(normalized)

            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                symlinks.append(normalized)
                continue
            if info.is_dir():
                resource_entries.append((normalized, 0, -1))
                continue
            all_normalized_files.append(normalized)
            resource_entries.append((normalized, info.file_size, info.compress_size))
            prefix = canonical_root + "/"
            if not normalized.startswith(prefix):
                outside_root.append(normalized)
                continue
            rel = normalized[len(prefix):]
            if not rel or rel.startswith("../"):
                unsafe_entries.append(f"{info.filename}: invalid relative entry")
                continue
            names.append(rel)
            safe_files.append((info, rel))

        result = dict(base)
        result["missing"] = sorted(set(required) - set(names))
        if not cfg["allow_unlisted_files"]:
            result["unexpected"] = sorted(set(names) - allowed)
        result["forbidden"] = sorted(x for x in names if forbidden_path(x, patterns))
        result["unsafe_entries"] = sorted(unsafe_entries) if cfg["reject_unsafe_archive_paths"] else []
        result["duplicate_entries"] = sorted(set(duplicate_entries)) if cfg["reject_duplicate_entries"] else []
        result["name_collisions"] = _name_collision_checks(all_normalized_files, cfg)
        result["resource_limit_violations"] = _resource_limit_checks(resource_entries, cfg)
        result["symlinks"] = sorted(symlinks) if cfg["reject_symlinks"] else []
        result["outside_root"] = sorted(outside_root)

        prelim_errors = any(result[k] for k in [
            "missing", "unexpected", "forbidden", "unsafe_entries", "duplicate_entries", "name_collisions",
            "resource_limit_violations", "symlinks", "outside_root"
        ])
        if cfg["run_bundle_checks"] and not prelim_errors:
            with tempfile.TemporaryDirectory() as td:
                bundle_root = Path(td) / canonical_root
                bundle_root.mkdir(parents=True, exist_ok=True)
                for info, rel in safe_files:
                    target = bundle_root / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, target.open("wb") as dst:
                        # Resource limits were checked from central-directory metadata before extraction.
                        dst.write(src.read(cfg["max_file_uncompressed_bytes"] + 1))
                        if src.read(1):
                            result["resource_limit_violations"].append(f"{rel}: extracted data exceeded declared size limit")
                            break
                if not result["resource_limit_violations"]:
                    failures = [c for c in bundle_checks(bundle_root) if c.status != "PASS"]
                    result["bundle_failures"] = [f"{c.name}: {c.detail}" for c in failures]
                    if trusted_manifest is not None and not result["bundle_failures"]:
                        integrity_result = verify_trust_manifest(trusted_manifest, bundle_root)
                        result["integrity_failures"] = integrity_result["errors"]
                    if release_manifest is not None and not result["bundle_failures"]:
                        release_result = verify_release_manifest(release_manifest, path, contract)
                        result["release_integrity_failures"] = release_result["errors"]
        result["detail"] = f"checked {len(set(names))} files against canonical manifest"
        return _distribution_result(**result)
