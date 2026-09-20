from __future__ import annotations

import json
import re
import subprocess
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .contract import (
    Check,
    PROJECT_END,
    PROJECT_FACT_KEYS,
    PROJECT_FACT_STATUSES,
    PROJECT_PATH,
    PROJECT_START,
    POLICIES_PATH,
    REVIEW_FRESHNESS_DAYS,
    load_json,
)

def extract_policy_sections(
    contract: dict,
    policy_ids: Iterable[str],
    path: Path = POLICIES_PATH,
) -> dict[str, str]:
    """Return complete primary-owner Markdown sections for requested policy IDs."""
    catalog = {item["id"]: item for item in contract.get("policies", [])}
    requested = list(dict.fromkeys(str(x).strip() for x in policy_ids if str(x).strip()))
    unknown = [x for x in requested if x not in catalog]
    if unknown:
        raise ValueError("unknown policy id(s): " + ", ".join(unknown))
    text = path.read_text(encoding="utf-8")
    sections: dict[str, str] = {}
    for policy_id in requested:
        anchor = catalog[policy_id]["anchor"]
        token = f'<a id="{anchor}"></a>'
        start = text.find(token)
        if start < 0:
            raise ValueError(f"missing policy anchor: {anchor}")
        next_match = re.search(r'\n<a id="policy-[a-z0-9-]+"></a>', text[start + len(token):])
        end = len(text) if next_match is None else start + len(token) + next_match.start()
        sections[policy_id] = text[start:end].strip()
    return sections


def validate_project_facts_shape(data: object) -> list[str]:
    """Validate PROJECT.md's machine block defensively without assuming nested types."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["project facts root must be a JSON object"]

    profile = data.get("profile")
    if not isinstance(profile, str) or not profile.strip():
        errors.append("profile must be a non-empty string")

    facts = data.get("facts")
    if not isinstance(facts, dict):
        errors.append("facts must be an object")
    else:
        for key in PROJECT_FACT_KEYS:
            if key not in facts:
                errors.append(f"facts.{key} is required")
        for key, item in facts.items():
            if not isinstance(item, dict):
                errors.append(f"facts.{key} must be an object")
                continue
            for field in ("value", "status", "evidence"):
                if field not in item:
                    errors.append(f"facts.{key}.{field} is required")
            value = item.get("value")
            status = item.get("status")
            evidence = item.get("evidence")
            if value is not None and not isinstance(value, str):
                errors.append(f"facts.{key}.value must be a string")
            if status not in PROJECT_FACT_STATUSES:
                errors.append(f"facts.{key}.status must be one of {sorted(PROJECT_FACT_STATUSES)}")
            if evidence is not None and not isinstance(evidence, str):
                errors.append(f"facts.{key}.evidence must be a string")

    components = data.get("components")
    if not isinstance(components, list):
        errors.append("components must be an array")
    else:
        for idx, component in enumerate(components):
            if not isinstance(component, dict):
                errors.append(f"components[{idx}] must be an object")
                continue
            for field in ("name", "path", "responsibility"):
                value = component.get(field)
                if not isinstance(value, str):
                    errors.append(f"components[{idx}].{field} must be a string")
            component_facts = component.get("facts")
            if component_facts is not None:
                if not isinstance(component_facts, dict):
                    errors.append(f"components[{idx}].facts must be an object")
                else:
                    allowed_component_facts = {"build_command", "test_command", "runtime", "deploy_command", "deploy_target"}
                    for key, item in component_facts.items():
                        if key not in allowed_component_facts:
                            errors.append(f"components[{idx}].facts.{key} is not supported")
                            continue
                        if not isinstance(item, dict):
                            errors.append(f"components[{idx}].facts.{key} must be an object")
                            continue
                        for field in ("value", "status", "evidence"):
                            if field not in item:
                                errors.append(f"components[{idx}].facts.{key}.{field} is required")
                        if item.get("value") is not None and not isinstance(item.get("value"), str):
                            errors.append(f"components[{idx}].facts.{key}.value must be a string")
                        if item.get("status") not in PROJECT_FACT_STATUSES:
                            errors.append(f"components[{idx}].facts.{key}.status must be one of {sorted(PROJECT_FACT_STATUSES)}")
                        if item.get("evidence") is not None and not isinstance(item.get("evidence"), str):
                            errors.append(f"components[{idx}].facts.{key}.evidence must be a string")

    review = data.get("review")
    if not isinstance(review, dict):
        errors.append("review must be an object")
    else:
        for field in ("reviewed_revision", "reviewed_at"):
            value = review.get(field)
            if not isinstance(value, str):
                errors.append(f"review.{field} must be a string")
        reviewed_paths = review.get("reviewed_paths", [])
        if not isinstance(reviewed_paths, list) or any(not isinstance(x, str) or not x.strip() for x in reviewed_paths):
            errors.append("review.reviewed_paths must be an array of non-empty strings when provided")
    return errors


def _reviewed_at_timestamp(value: str) -> tuple[datetime | None, str | None]:
    raw = value.strip()
    if not raw:
        return None, "reviewed_at is missing"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        try:
            parsed = datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
            return parsed, None
        except ValueError:
            return None, "reviewed_at must be a valid ISO-8601 date or timezone-aware datetime"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None, "reviewed_at must be a valid ISO-8601 date or timezone-aware datetime"
    if parsed.tzinfo is None:
        return None, "reviewed_at datetime must include timezone"
    return parsed.astimezone(timezone.utc), None


def _readiness_structure_failure(mode: str, errors: list[str]) -> dict:
    detail = "; ".join(errors)
    check = asdict(Check("project_facts_structure", "FAIL", detail))
    return {
        "mode": mode,
        "documented": "FAIL",
        "evidence_verified": "FAIL",
        "execution_verified": "NOT_RUN",
        "verified": "FAIL",
        "documented_checks": [check],
        "verified_checks": [check],
        "warnings": [],
        "errors": errors,
    }


def parse_project_facts(path: Path = PROJECT_PATH) -> dict:
    text = path.read_text(encoding="utf-8")
    if PROJECT_START not in text or PROJECT_END not in text:
        raise ValueError("PROJECT.md project-facts markers are missing")
    body = text.split(PROJECT_START, 1)[1].split(PROJECT_END, 1)[0]
    match = re.search(r"```json\s*(.*?)\s*```", body, flags=re.DOTALL)
    if not match:
        raise ValueError("PROJECT.md project-facts JSON block is missing")
    return json.loads(match.group(1))


def path_from_value(project_root: Path, value: str) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else (project_root / p)


def git_head(project_root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
        return out.stdout.strip()
    except Exception:
        return None


def _command_literal_is_active(target: Path, content: str, literal: str) -> tuple[bool, str]:
    """Best-effort source-aware command check.

    It deliberately does not claim that a command will execute successfully. The goal
    is narrower: avoid treating a comment-only occurrence as command-source evidence.
    """
    wanted = _normalized_value(literal)
    name = target.name.casefold()
    if name == "package.json":
        try:
            doc = json.loads(content)
        except Exception as exc:
            return False, f"package.json parse failed: {exc}"
        scripts = doc.get("scripts") if isinstance(doc, dict) else None
        if not isinstance(scripts, dict):
            return False, "package.json has no scripts object"
        values = [value for value in scripts.values() if isinstance(value, str)]
        if any(wanted == _normalized_value(value) for value in values):
            return True, "matched package.json scripts value"
        return False, "literal was not an exact package.json scripts value"

    lines = content.splitlines()
    active_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", "//", ";", "<!--")):
            continue
        active_lines.append(line)
    for line in active_lines:
        if wanted in _normalized_value(line):
            if name in {"makefile", "gnumakefile"} or name.endswith(".mk"):
                return True, "matched non-comment Makefile line"
            return True, "matched non-comment source line"
    return False, "literal appears only in comments or is absent"


def git_reviewed_paths_unchanged(project_root: Path, reviewed_revision: str, paths: Iterable[str]) -> tuple[bool | None, str]:
    path_list = [str(x).strip() for x in paths if str(x).strip()]
    if not path_list:
        return None, "no reviewed_paths configured"
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_root), "diff", "--quiet", reviewed_revision, "HEAD", "--", *path_list],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        return None, f"git diff failed: {exc}"
    if proc.returncode == 0:
        return True, "reviewed paths are unchanged since documented revision"
    if proc.returncode == 1:
        return False, "reviewed paths changed since documented revision"
    return None, proc.stderr.strip() or f"git diff returned {proc.returncode}"


def _read_text_evidence(project_root: Path, payload: str, kind: str) -> tuple[str, str, str | None]:
    if "::" not in payload:
        return "FAIL", f"{kind} evidence must be {kind}:<path>::<literal>", None
    file_part, literal = payload.split("::", 1)
    target = path_from_value(project_root, file_part.strip())
    if not target.is_file():
        return "FAIL", f"missing evidence file: {target}", None
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "MANUAL", f"binary/non-UTF8 evidence file: {target}", None
    if kind == "command-source":
        active, active_detail = _command_literal_is_active(target, content, literal)
        if not active:
            return "FAIL", f"command literal is not active in {target}: {literal!r}; {active_detail}", None
        return "PASS", f"command literal verified in active source {target}: {active_detail}", literal
    if literal not in content:
        return "FAIL", f"literal not found in {target}: {literal!r}", None
    return "PASS", f"literal found in {target}", literal


def verify_evidence(project_root: Path, evidence: str) -> tuple[str, str]:
    """Verify a standalone evidence reference without claiming semantic linkage to a fact."""
    evidence = (evidence or "").strip()
    if not evidence:
        return "FAIL", "evidence is empty"
    if evidence.startswith("manual:"):
        return "MANUAL", evidence[7:].strip() or "manual verification required"
    if evidence.startswith("path:"):
        target = path_from_value(project_root, evidence[5:].strip())
        return ("PASS", str(target)) if target.exists() else ("FAIL", f"missing path: {target}")
    for kind in ("contains", "command-source", "value-source"):
        prefix = kind + ":"
        if evidence.startswith(prefix):
            status, detail, _ = _read_text_evidence(project_root, evidence[len(prefix):], kind)
            return status, detail
    if evidence == "git:HEAD":
        return "MANUAL", "use reviewed_revision comparison instead of evidence=git:HEAD"
    return "MANUAL", "untyped evidence is not auto-verified; use path:, command-source:, value-source:, contains:, or manual:"


def _same_resolved_path(a: Path, b: Path) -> bool:
    try:
        return a.resolve(strict=False) == b.resolve(strict=False)
    except OSError:
        return False


def _normalized_value(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).strip()).casefold()


def verify_fact_evidence(project_root: Path, key: str, value: str, evidence: str) -> tuple[str, str]:
    """Verify evidence using fact-specific evidence types and semantic linkage."""
    evidence = (evidence or "").strip()
    if evidence.startswith("manual:"):
        return "MANUAL", evidence[7:].strip() or "manual verification required"

    if key in {"repository_root", "primary_source"}:
        if not evidence.startswith("path:"):
            return "FAIL", f"{key} requires path:<path> evidence for automatic verification"
        value_path = path_from_value(project_root, value)
        evidence_path = path_from_value(project_root, evidence[5:].strip())
        if not evidence_path.exists():
            return "FAIL", f"missing evidence path: {evidence_path}"
        if not value_path.exists():
            return "FAIL", f"fact path does not exist: {value_path}"
        if not _same_resolved_path(value_path, evidence_path):
            return "FAIL", f"evidence path does not identify fact value: value={value_path}, evidence={evidence_path}"
        return "PASS", str(value_path.resolve(strict=False))

    if key in {"build_command", "test_command", "deploy_command"}:
        prefix = "command-source:"
        if not evidence.startswith(prefix):
            return "FAIL", f"{key} requires command-source:<path>::<literal> or manual: evidence"
        status, detail, literal = _read_text_evidence(project_root, evidence[len(prefix):], "command-source")
        if status != "PASS":
            return status, detail
        if _normalized_value(literal or "") != _normalized_value(value):
            return "FAIL", f"command-source literal does not equal documented {key} value"
        return "PASS", detail

    if key in {"runtime", "deploy_target"}:
        prefix = "value-source:"
        if not evidence.startswith(prefix):
            return "FAIL", f"{key} requires value-source:<path>::<literal> or manual: evidence"
        status, detail, literal = _read_text_evidence(project_root, evidence[len(prefix):], "value-source")
        if status != "PASS":
            return status, detail
        if _normalized_value(literal or "") != _normalized_value(value):
            return "FAIL", f"value-source literal does not equal documented {key} value"
        return "PASS", detail

    return verify_evidence(project_root, evidence)


def readiness(project_path: Path = PROJECT_PATH, mode: str = "development", project_root: Path | None = None) -> dict:
    try:
        facts_doc = parse_project_facts(project_path)
    except Exception as exc:
        return _readiness_structure_failure(mode, [f"PROJECT.md parse error: {exc}"])

    shape_errors = validate_project_facts_shape(facts_doc)
    if shape_errors:
        return _readiness_structure_failure(mode, shape_errors)

    project_root = (project_root or project_path.parent).resolve()
    facts = facts_doc["facts"]
    required = ["repository_root", "primary_source", "build_command", "test_command", "runtime"]
    if mode == "deployment":
        required += ["deploy_command", "deploy_target"]

    documented: list[Check] = []
    verified: list[Check] = []
    warnings: list[str] = []

    if facts_doc.get("profile") == "template":
        documented.append(Check("profile", "FAIL", "profile is still template"))
    else:
        documented.append(Check("profile", "PASS", str(facts_doc.get("profile"))))

    for key in required:
        item = facts[key]
        value = item["value"].strip()
        status = item["status"]
        evidence = item["evidence"].strip()
        if status == "N/A":
            ok = bool(evidence)
            documented.append(Check(key, "PASS" if ok else "FAIL", "N/A" if ok else "N/A requires reason/evidence"))
            verified.append(Check(key, "MANUAL", "N/A rationale is a human claim"))
            continue
        doc_ok = status == "Confirmed" and bool(value) and bool(evidence)
        documented.append(Check(key, "PASS" if doc_ok else "FAIL", f"status={status!r}, value={value!r}, evidence={evidence!r}"))
        if not doc_ok:
            verified.append(Check(key, "FAIL", "not documented as Confirmed with value and evidence"))
            continue
        result_status, detail = verify_fact_evidence(project_root, key, value, evidence)
        verified.append(Check(key, result_status, detail))

    components = facts_doc["components"]
    if components:
        documented.append(Check("components", "PASS", f"{len(components)} component(s)"))
        component_failures = []
        for idx, component in enumerate(components):
            component_path = component["path"].strip()
            if not component_path or not path_from_value(project_root, component_path).exists():
                component_failures.append(component_path or "<missing path>")
            for key, item in component.get("facts", {}).items():
                value = item["value"].strip()
                status = item["status"]
                evidence = item["evidence"].strip()
                check_name = f"components[{idx}].{key}"
                if status == "N/A":
                    documented.append(Check(check_name, "PASS" if evidence else "FAIL", "N/A" if evidence else "N/A requires reason/evidence"))
                    verified.append(Check(check_name, "MANUAL", "N/A rationale is a human claim"))
                    continue
                doc_ok = status == "Confirmed" and bool(value) and bool(evidence)
                documented.append(Check(check_name, "PASS" if doc_ok else "FAIL", f"status={status!r}, value={value!r}, evidence={evidence!r}"))
                if doc_ok:
                    result_status, detail = verify_fact_evidence(project_root, key, value, evidence)
                    verified.append(Check(check_name, result_status, detail))
                else:
                    verified.append(Check(check_name, "FAIL", "not documented as Confirmed with value and evidence"))
        verified.append(Check("components", "PASS" if not component_failures else "FAIL", ", ".join(component_failures) if component_failures else "all component paths exist"))
    else:
        documented.append(Check("components", "FAIL", "at least one component is required"))
        verified.append(Check("components", "FAIL", "no components to verify"))

    review = facts_doc["review"]
    reviewed = review["reviewed_revision"].strip()
    reviewed_paths = [str(x).strip() for x in review.get("reviewed_paths", []) if str(x).strip()]
    if reviewed_paths:
        documented.append(Check("reviewed_paths", "PASS", ", ".join(reviewed_paths)))
    if reviewed:
        documented.append(Check("reviewed_revision", "PASS", reviewed))
        head = git_head(project_root)
        if head is None:
            verified.append(Check("reviewed_revision", "MANUAL", "project root is not a Git repository or Git is unavailable"))
        elif reviewed == head:
            verified.append(Check("reviewed_revision", "PASS", f"documented revision equals HEAD={head}"))
        elif reviewed_paths:
            unchanged, detail = git_reviewed_paths_unchanged(project_root, reviewed, reviewed_paths)
            if unchanged is True:
                verified.append(Check("reviewed_revision", "PASS", f"documented={reviewed}, HEAD={head}; {detail}"))
            elif unchanged is False:
                verified.append(Check("reviewed_revision", "FAIL", f"documented={reviewed}, HEAD={head}; {detail}"))
            else:
                verified.append(Check("reviewed_revision", "MANUAL", f"documented={reviewed}, HEAD={head}; {detail}"))
        else:
            verified.append(Check("reviewed_revision", "FAIL", f"documented={reviewed}, HEAD={head}; configure reviewed_paths to permit unrelated HEAD changes"))
    else:
        documented.append(Check("reviewed_revision", "FAIL", "missing"))
        verified.append(Check("reviewed_revision", "FAIL", "missing"))

    reviewed_at_raw = review["reviewed_at"].strip()
    reviewed_at, reviewed_at_error = _reviewed_at_timestamp(reviewed_at_raw)
    if reviewed_at_error:
        documented.append(Check("reviewed_at", "FAIL", reviewed_at_error))
        verified.append(Check("reviewed_at", "FAIL", reviewed_at_error))
    else:
        assert reviewed_at is not None
        documented.append(Check("reviewed_at", "PASS", reviewed_at_raw))
        today = datetime.now(timezone.utc).date()
        if reviewed_at.date() > today:
            verified.append(Check("reviewed_at", "FAIL", f"reviewed_at is in the future: {reviewed_at_raw}"))
        else:
            age_days = (today - reviewed_at.date()).days
            verified.append(Check("reviewed_at", "PASS", f"review age={age_days} day(s)"))
            if age_days > REVIEW_FRESHNESS_DAYS:
                warnings.append(
                    f"project facts were last reviewed {age_days} days ago; refresh evidence if project topology or commands may have changed"
                )

    documented_pass = all(x.status == "PASS" for x in documented)
    if not documented_pass:
        verified_state = "FAIL"
    elif any(x.status == "FAIL" for x in verified):
        verified_state = "FAIL"
    elif any(x.status == "MANUAL" for x in verified):
        verified_state = "PARTIAL"
    else:
        verified_state = "PASS"

    return {
        "mode": mode,
        "documented": "PASS" if documented_pass else "FAIL",
        "evidence_verified": verified_state,
        "execution_verified": "NOT_RUN",
        "verified": verified_state,
        "documented_checks": [asdict(x) for x in documented],
        "verified_checks": [asdict(x) for x in verified],
        "warnings": warnings,
        "errors": [],
    }


def extract_internal_links(markdown: str) -> list[str]:
    links = []
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", markdown):
        target = target.strip()
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        links.append(target)
    return links


def validate_internal_links(root: Path) -> list[Check]:
    checks: list[Check] = []
    for md in sorted(root.rglob("*.md")):
        text = md.read_text(encoding="utf-8")
        for target in extract_internal_links(text):
            path_part, _, anchor = target.partition("#")
            dest = (md.parent / path_part).resolve() if path_part else md.resolve()
            if not dest.exists():
                checks.append(Check(f"link:{md.relative_to(root)}", "FAIL", f"missing {target}"))
                continue
            if anchor and dest.suffix.lower() == ".md":
                content = dest.read_text(encoding="utf-8")
                if f'id="{anchor}"' not in content and f"id='{anchor}'" not in content:
                    if anchor.startswith("policy-"):
                        checks.append(Check(f"anchor:{md.relative_to(root)}", "FAIL", f"missing #{anchor} in {dest.relative_to(root)}"))
    if not checks:
        checks.append(Check("internal_links", "PASS", "all checked relative links resolve"))
    return checks


def _candidate_fact(value: str = "", status: str = "Unknown", evidence: str = "") -> dict:
    return {"value": value, "status": status, "evidence": evidence}


def _makefile_recipe(path: Path, target: str) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    in_target = False
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            if in_target and not line.startswith("\t"):
                break
            continue
        if not line.startswith((" ", "\t")) and re.match(rf"^{re.escape(target)}\s*:", line):
            in_target = True
            continue
        if in_target:
            if line.startswith("\t"):
                command = line.strip()
                if command and not command.startswith("#"):
                    return command
            elif not line.startswith(" "):
                break
    return None


def bootstrap_project(repo_root: Path, output: Path | None = None, force: bool = False) -> dict:
    """Generate a conservative PROJECT candidate from observable repository evidence.

    Nothing is promoted to Confirmed. Automatically detected facts remain Inferred so
    readiness cannot become documented-PASS merely because bootstrap ran.
    """
    repo_root = repo_root.resolve()
    if not repo_root.is_dir():
        raise ValueError(f"repository root is not a directory: {repo_root}")
    output = output.resolve() if output is not None else repo_root / "PROJECT.inferred.md"
    if output.exists() and not force:
        raise FileExistsError(f"refusing to overwrite existing bootstrap output: {output}; use --bootstrap-force")

    detected_paths: list[str] = []
    facts = {
        "repository_root": _candidate_fact(".", "Inferred", "path:."),
        "primary_source": _candidate_fact(),
        "build_command": _candidate_fact(),
        "test_command": _candidate_fact(),
        "runtime": _candidate_fact(),
        "deploy_command": _candidate_fact(),
        "deploy_target": _candidate_fact(),
    }

    source_candidates = ["src", "app", "lib", "services", "packages", "apps", "backend", "frontend"]
    for rel in source_candidates:
        if (repo_root / rel).is_dir():
            facts["primary_source"] = _candidate_fact(rel, "Inferred", f"path:{rel}")
            detected_paths.append(rel)
            break

    package_json = repo_root / "package.json"
    if package_json.is_file():
        detected_paths.append("package.json")
        try:
            package = load_json(package_json)
        except Exception:
            package = {}
        scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
        if isinstance(scripts, dict):
            build = scripts.get("build")
            test = scripts.get("test")
            if isinstance(build, str) and build.strip():
                facts["build_command"] = _candidate_fact(build.strip(), "Inferred", f"command-source:package.json::{build.strip()}")
            if isinstance(test, str) and test.strip():
                facts["test_command"] = _candidate_fact(test.strip(), "Inferred", f"command-source:package.json::{test.strip()}")
        engines = package.get("engines", {}) if isinstance(package, dict) else {}
        node = engines.get("node") if isinstance(engines, dict) else None
        if isinstance(node, str) and node.strip():
            facts["runtime"] = _candidate_fact(node.strip(), "Inferred", f"value-source:package.json::{node.strip()}")

    makefile = repo_root / "Makefile"
    if makefile.is_file():
        detected_paths.append("Makefile")
        if facts["build_command"]["status"] == "Unknown":
            cmd = _makefile_recipe(makefile, "build")
            if cmd:
                facts["build_command"] = _candidate_fact(cmd, "Inferred", f"command-source:Makefile::{cmd}")
        if facts["test_command"]["status"] == "Unknown":
            cmd = _makefile_recipe(makefile, "test")
            if cmd:
                facts["test_command"] = _candidate_fact(cmd, "Inferred", f"command-source:Makefile::{cmd}")
        deploy = _makefile_recipe(makefile, "deploy")
        if deploy:
            facts["deploy_command"] = _candidate_fact(deploy, "Inferred", f"command-source:Makefile::{deploy}")

    runtime_sources = [
        (".python-version", lambda text: next((x.strip() for x in text.splitlines() if x.strip()), "")),
        (".tool-versions", lambda text: next((x.strip() for x in text.splitlines() if x.strip()), "")),
    ]
    if facts["runtime"]["status"] == "Unknown":
        for rel, extractor in runtime_sources:
            path = repo_root / rel
            if path.is_file():
                detected_paths.append(rel)
                try:
                    literal = extractor(path.read_text(encoding="utf-8"))
                except Exception:
                    literal = ""
                if literal:
                    facts["runtime"] = _candidate_fact(literal, "Inferred", f"value-source:{rel}::{literal}")
                    break
    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file():
        detected_paths.append("pyproject.toml")
        if facts["runtime"]["status"] == "Unknown":
            try:
                pytext = pyproject.read_text(encoding="utf-8")
            except Exception:
                pytext = ""
            m = re.search(r"^requires-python\s*=\s*['\"]([^'\"]+)['\"]", pytext, flags=re.MULTILINE)
            if m:
                literal = m.group(1).strip()
                facts["runtime"] = _candidate_fact(literal, "Inferred", f"value-source:pyproject.toml::{literal}")

    components: list[dict] = []
    for parent in ["services", "packages", "apps"]:
        base = repo_root / parent
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if child.is_dir() and not child.name.startswith("."):
                rel = str(child.relative_to(repo_root)).replace("\\", "/")
                components.append({
                    "name": child.name,
                    "path": rel,
                    "responsibility": "Inferred component candidate; confirm responsibility and boundaries",
                })
                detected_paths.append(rel)
    if not components and facts["primary_source"]["status"] == "Inferred":
        rel = facts["primary_source"]["value"]
        components.append({
            "name": Path(rel).name or "source",
            "path": rel,
            "responsibility": "Inferred primary source component; confirm responsibility and boundaries",
        })

    reviewed_revision = git_head(repo_root) or ""
    reviewed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    data = {
        "profile": "inferred-bootstrap-candidate",
        "facts": facts,
        "components": components,
        "review": {
            "reviewed_revision": reviewed_revision,
            "reviewed_at": reviewed_at,
            "reviewed_paths": sorted(set(detected_paths)),
        },
    }
    block = json.dumps(data, ensure_ascii=False, indent=2)
    markdown = (
        "# PROJECT.md — inferred bootstrap candidate\n\n"
        "> 이 파일은 repository 관찰로 생성한 **후보**다. 자동 탐색 결과는 `Confirmed`로 승격하지 않는다. "
        "실제 evidence를 검토한 뒤 필요한 fact만 `Confirmed` 또는 근거 있는 `N/A`로 변경한다.\n\n"
        + PROJECT_START + "\n```json\n" + block + "\n```\n" + PROJECT_END
        + "\n\n## Bootstrap notes\n\n"
          "- 생성기는 기존 `PROJECT.md`를 덮어쓰지 않는다.\n"
          "- `Inferred` 상태는 documented readiness를 통과시키지 않는다.\n"
          "- 잘못 추론된 command/runtime/component는 삭제하거나 실제 Source of Truth에 맞게 수정한다.\n"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    return {
        "status": "PASS",
        "repository_root": str(repo_root),
        "output": str(output),
        "profile": data["profile"],
        "inferred_facts": sorted(k for k, v in facts.items() if v["status"] == "Inferred"),
        "unknown_facts": sorted(k for k, v in facts.items() if v["status"] == "Unknown"),
        "components": [x["path"] for x in components],
        "note": "No fact was auto-promoted to Confirmed.",
    }
