#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# Compatibility facade: existing callers may continue importing scripts/validate.py.
# Policy logic lives in focused modules under scripts/validation/.
from validation.contract import *  # noqa: F401,F403,E402
from validation.routing import *  # noqa: F401,F403,E402
from validation.routing import _korean_literal_token_matches  # noqa: F401,E402
from validation.risk import *  # noqa: F401,F403,E402
from validation.risk import _EFFECT_RANK, _EXPOSURE_RANK, _concrete_targets, _max_level  # noqa: F401,E402
from validation.runtime import *  # noqa: F401,F403,E402
from validation.integrity import *  # noqa: F401,F403,E402
from validation.readiness import *  # noqa: F401,F403,E402
from validation.readiness import (  # noqa: F401,E402
    _candidate_fact,
    _command_literal_is_active,
    _makefile_recipe,
    _normalized_value,
    _read_text_evidence,
    _readiness_structure_failure,
    _reviewed_at_timestamp,
    _same_resolved_path,
)
from validation.bundle import *  # noqa: F401,F403,E402
from validation.distribution import *  # noqa: F401,F403,E402
from validation.distribution import (  # noqa: F401,E402
    _archive_collision_key,
    _distribution_result,
    _name_collision_checks,
    _resource_limit_checks,
)
from validation.approval import *  # noqa: F401,F403,E402
from validation.approval import _approval_replay_state, _parse_timestamp  # noqa: F401,E402
from validation.override import *  # noqa: F401,F403,E402
from validation.override import _override_replay_state  # noqa: F401,E402
from validation.context import *  # noqa: F401,F403,E402
def print_checks(checks: list[Check]) -> None:
    for c in checks:
        suffix = f" — {c.detail}" if c.detail else ""
        print(f"[{c.status}] {c.name}{suffix}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate universal-agent-docs")
    parser.add_argument("--route", metavar="TASK", help="route a task through canonical operation normalization")
    parser.add_argument("--operation", action="append", default=[], help="planned canonical operation ID (legacy natural-language alias also accepted); repeatable")
    parser.add_argument("--resource", action="append", default=[], help="affected resource path; repeatable")
    parser.add_argument("--routing-mode", choices=["advisory", "enforcement"], default="advisory", help="advisory warns on unresolved routing; enforcement fails closed")
    parser.add_argument("--action-boundary", action="store_true", help="evaluate an imminent action using runtime actual operations and Effect x Exposure")
    parser.add_argument("--actual-operation", action="append", default=[], help="canonical operation asserted by the runtime/tool adapter at execution time; repeatable")
    parser.add_argument("--actual-action", default="", help="optional concrete command/action text used for advisory hints and high-confidence signature mismatch detection")
    parser.add_argument("--runtime-action", type=Path, help="validate a structured runtime adapter action assertion and evaluate its execution boundary")
    parser.add_argument("--target", action="append", default=[], help="concrete execution target/recipient/resource; repeatable")
    parser.add_argument("--environment", default="", help="execution environment: local/test/staging/production/public/external/unknown")
    parser.add_argument("--exposure", choices=["X0", "X1", "X2", "X3"], help="optional adapter-declared Exposure; may raise but never lower policy-derived Exposure")
    parser.add_argument("--exposure-facts", type=Path, help="JSON object containing raw exposure dimensions for --action-boundary")
    parser.add_argument("--correlation-id", default="", help="stable action correlation ID used to bind explicit approval")
    parser.add_argument("--execution-nonce", default="", help="single-use runtime nonce (minimum 16 characters) bound into action digest")
    parser.add_argument("--effect", choices=["L1", "L2", "L3", "L4"], help="optional runtime-observed Effect escalation; never lowers operation floors")
    parser.add_argument("--policy", action="append", default=[], metavar="ID", help="print a primary-owner policy section by policy ID; repeatable")
    parser.add_argument("--compiled-policy", action="store_true", help="compile only the policy context applicable to --operation/--resource/--route inputs")
    parser.add_argument("--operation-extension", action="append", type=Path, default=[], metavar="JSON", help="validated organization/vendor operation extension document; repeatable")
    parser.add_argument("--trusted-extension-digest", action="append", default=[], metavar="SHA256", help="out-of-band expected combined extension digest; repeatable")
    parser.add_argument("--adapter-capabilities", action="append", type=Path, default=[], metavar="JSON", help="adapter capability declaration; repeatable")
    parser.add_argument("--trusted-capability-digest", action="append", default=[], metavar="SHA256", help="out-of-band expected combined adapter capability digest; repeatable")
    parser.add_argument("--readiness", choices=["development", "deployment"])
    parser.add_argument("--project-root", type=Path, help="project repository root for readiness evidence/Git checks; defaults to the selected PROJECT.md parent")
    parser.add_argument("--project-file", type=Path, help="project facts Markdown for --readiness; defaults to the policy bundle PROJECT.md")
    parser.add_argument("--distribution", type=Path, help="validate a complete explicit distribution directory or ZIP")
    parser.add_argument("--trusted-manifest", type=Path, help="verify core policy hashes against an out-of-band trusted manifest; with --distribution, verifies the artifact")
    parser.add_argument("--release-manifest", type=Path, help="verify full distributed-file and ZIP integrity against an out-of-band release manifest; requires --distribution ZIP")
    parser.add_argument("--emit-trust-manifest", type=Path, help="write a detached trust manifest for the current validated core; publish/store it out-of-band")
    parser.add_argument("--approval-assertion", type=Path, help="validate explicit approval structure/time and bind it to the evaluated action when present")
    parser.add_argument("--approval-ledger", type=Path, help="SQLite registry used to detect/record single-use approval replay")
    parser.add_argument("--consume-approval", action="store_true", help="atomically consume the bound approval in --approval-ledger; requires --approval-ledger")
    parser.add_argument("--protected-override", type=Path, help="validate protected override object structure/time only; never establishes authorization")
    parser.add_argument("--override-ledger", type=Path, help="SQLite registry used to detect/record single-use protected override replay")
    parser.add_argument("--consume-override", action="store_true", help="atomically consume the bound protected override in --override-ledger; requires --override-ledger")
    parser.add_argument("--bootstrap-project", type=Path, metavar="REPO", help="scan a repository and write a conservative PROJECT.inferred.md candidate")
    parser.add_argument("--bootstrap-output", type=Path, help="output path for --bootstrap-project; defaults to REPO/PROJECT.inferred.md")
    parser.add_argument("--bootstrap-force", action="store_true", help="allow --bootstrap-project to overwrite its output path")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    contract = load_json(CONTRACT_PATH)
    result: dict = {}
    exit_code = 0
    extension_registry, adapter_capabilities, extension_result, extension_exit = load_extension_runtime_inputs(
        args.operation_extension,
        args.adapter_capabilities,
        contract,
        args.trusted_extension_digest,
        args.trusted_capability_digest,
    )
    result.update(extension_result)
    exit_code = max(exit_code, extension_exit)

    checks = bundle_checks(ROOT)
    bundle_ok = all(c.status == "PASS" for c in checks)
    result["bundle"] = {"status": "PASS" if bundle_ok else "FAIL", "checks": [asdict(c) for c in checks]}
    if not bundle_ok:
        exit_code = 1

    if args.bootstrap_project:
        try:
            boot = bootstrap_project(args.bootstrap_project, args.bootstrap_output, args.bootstrap_force)
            result["bootstrap_project"] = boot
        except Exception as exc:
            result["bootstrap_project"] = {"status": "FAIL", "error": str(exc)}
            exit_code = 1

    if args.policy:
        try:
            sections = extract_policy_sections(contract, args.policy, POLICIES_PATH)
            result["policy_sections"] = sections
        except Exception as exc:
            result["policy_sections"] = {}
            result["policy_error"] = str(exc)
            exit_code = 1

    if args.compiled_policy and result.get("operation_extensions", {}).get("status") != "FAIL":
        try:
            compiled = compile_policy_view(
                contract,
                args.route or "",
                args.operation,
                args.resource,
                args.routing_mode,
                extension_registry,
            )
            result["compiled_policy"] = compiled
            if compiled["status"] == "FAIL":
                exit_code = 1
        except Exception as exc:
            result["compiled_policy"] = {"status": "FAIL", "error": str(exc)}
            exit_code = 1
    elif args.route is not None:
        routing = route_policies(
            contract,
            args.route,
            args.operation,
            args.resource,
            args.routing_mode,
            extension_registry=extension_registry,
        )
        result["routing"] = routing
        if routing["routing_status"] == "FAIL":
            exit_code = 1

    approval_boundary = None
    if args.action_boundary:
        exposure_facts = None
        if args.exposure_facts is not None:
            try:
                exposure_facts = load_json(args.exposure_facts)
            except Exception as exc:
                result["execution_boundary"] = {"status": "FAIL", "decision": "BLOCK_POLICY_ERROR", "errors": [f"exposure facts: {exc}"]}
                exit_code = 1
        if "execution_boundary" not in result:
            boundary = evaluate_execution_boundary(
                contract,
                args.operation,
                args.actual_operation,
                args.resource,
                args.target,
                args.environment,
                args.exposure,
                args.effect,
                args.actual_action,
                exposure_facts=exposure_facts,
                correlation_id=args.correlation_id,
                execution_nonce=args.execution_nonce,
                adapter={"id":"validator-cli","surface":"cli","assertion_source":"human_reviewed"},
                semantic_details={},
                extension_registry=extension_registry,
                adapter_capabilities=adapter_capabilities,
            )
            result["execution_boundary"] = boundary
            approval_boundary = boundary
            if boundary["status"] != "PASS" or boundary["decision"].startswith("BLOCK_"):
                exit_code = 1

    if args.runtime_action:
        runtime_action_result = validate_runtime_action(
            args.runtime_action, contract, ROOT,
            extension_registry=extension_registry,
            adapter_capabilities=adapter_capabilities,
        )
        result["runtime_action"] = runtime_action_result
        boundary = runtime_action_result.get("boundary", {})
        approval_boundary = boundary if boundary else approval_boundary
        if runtime_action_result["status"] != "PASS" or str(boundary.get("decision", "")).startswith("BLOCK_"):
            exit_code = 1

    if args.approval_assertion:
        approval_result = validate_approval_assertion(
            args.approval_assertion, contract, approval_boundary, ROOT,
            replay_registry=args.approval_ledger, consume=args.consume_approval,
            extension_registry=extension_registry,
        )
        result["approval_assertion"] = approval_result
        if approval_result["object_validity"] != "VALID":
            exit_code = 1

    if (args.project_root or args.project_file) and not args.readiness:
        result["readiness_error"] = "--project-root/--project-file require --readiness"
        exit_code = 1

    if args.readiness:
        project_path = args.project_file.resolve() if args.project_file else PROJECT_PATH
        project_root = args.project_root.resolve() if args.project_root else project_path.parent
        r = readiness(project_path, args.readiness, project_root=project_root)
        result["readiness"] = r
        if r["documented"] != "PASS" or r["verified"] == "FAIL":
            exit_code = 1

    if args.distribution:
        d = validate_distribution(args.distribution, contract, args.trusted_manifest, args.release_manifest)
        result["distribution"] = d
        if d["status"] != "PASS":
            exit_code = 1
    elif args.trusted_manifest:
        integrity_result = verify_trust_manifest(args.trusted_manifest, ROOT)
        result["integrity"] = integrity_result
        if integrity_result["status"] != "PASS":
            exit_code = 1
    if args.release_manifest and not args.distribution:
        result["release_integrity"] = {"status": "FAIL", "errors": ["--release-manifest requires --distribution pointing to the canonical ZIP"]}
        exit_code = 1

    if args.emit_trust_manifest:
        if result["bundle"]["status"] != "PASS":
            result["trust_manifest_error"] = "refusing to emit trust manifest for a bundle that failed validation"
            exit_code = 1
        else:
            emitted = write_trust_manifest(args.emit_trust_manifest, ROOT)
            result["emitted_trust_manifest"] = {"path": str(args.emit_trust_manifest), "manifest": emitted}

    if args.consume_override and not args.protected_override:
        result["protected_override_error"] = "--consume-override requires --protected-override"
        exit_code = 1
    if args.override_ledger and not args.protected_override:
        result["protected_override_error"] = "--override-ledger requires --protected-override"
        exit_code = 1

    if args.protected_override:
        o = validate_protected_override(
            args.protected_override, contract, approval_boundary, ROOT,
            replay_registry=args.override_ledger, consume=args.consume_override,
            extension_registry=extension_registry,
        )
        result["protected_override"] = o
        if o["object_validity"] != "VALID" or o.get("binding") == "INVALID":
            exit_code = 1

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return exit_code

    compiled_only = (
        args.compiled_policy and not args.policy and not args.action_boundary and not args.runtime_action
        and not args.readiness and not args.project_root and not args.project_file
        and not args.distribution and not args.trusted_manifest and not args.release_manifest
        and not args.emit_trust_manifest and not args.approval_assertion and not args.protected_override
        and not args.override_ledger and not args.consume_override and not args.bootstrap_project
    )
    if compiled_only:
        if result["bundle"]["status"] != "PASS":
            print("Bundle validation: FAIL", file=sys.stderr)
            return exit_code
        compiled = result.get("compiled_policy", {})
        if compiled.get("status") == "FAIL" and compiled.get("error"):
            print(compiled["error"], file=sys.stderr)
            return exit_code
        print(render_compiled_policy_view(compiled), end="")
        return exit_code

    policy_only = (
        bool(args.policy) and args.route is None and not args.compiled_policy and not args.action_boundary and not args.runtime_action and not args.readiness
        and not args.project_root and not args.project_file
        and not args.distribution and not args.trusted_manifest and not args.release_manifest and not args.emit_trust_manifest
        and not args.approval_assertion and not args.protected_override and not args.override_ledger and not args.consume_override
        and not args.bootstrap_project
    )
    if policy_only:
        if result["bundle"]["status"] != "PASS":
            print("Bundle validation: FAIL", file=sys.stderr)
            for check in checks:
                if check.status != "PASS":
                    suffix = f" — {check.detail}" if check.detail else ""
                    print(f"[{check.status}] {check.name}{suffix}", file=sys.stderr)
            return exit_code
        if "policy_error" in result:
            print(result["policy_error"], file=sys.stderr)
            return exit_code
        print("\n\n".join(result["policy_sections"].values()))
        return exit_code

    print(f"Bundle validation: {result['bundle']['status']}")
    if result["bundle"]["status"] != "PASS":
        print_checks(checks)
    if "bootstrap_project" in result:
        boot = result["bootstrap_project"]
        print(f"PROJECT bootstrap: {boot.get('status')}" + (f" — {boot.get('output')}" if boot.get('output') else ""))
        if boot.get("note"):
            print(" -", boot["note"])
        if boot.get("error"):
            print(" - error:", boot["error"])
    if "policy_sections" in result:
        if "policy_error" in result:
            print("Policy selector error:", result["policy_error"])
        else:
            for policy_id, section in result["policy_sections"].items():
                print(f"Policy section [{policy_id}]:")
                print(section)
    if "operation_extensions" in result:
        ext = result["operation_extensions"]
        print(f"Operation extensions: {ext.get('status')}")
        if ext.get("combined_digest"):
            print("Extension digest:", ext["combined_digest"])
        if ext.get("operation_ids"):
            print("Extension operations:", ", ".join(ext["operation_ids"]))
        print("Extension integrity:", ext.get("integrity", "UNVERIFIED"))
        print("Extension authority:", ext.get("authority", "NOT_ESTABLISHED"))
        if ext.get("error"):
            print(" - error:", ext["error"])
    if "adapter_capabilities" in result:
        caps = result["adapter_capabilities"]
        print(f"Adapter capabilities: {caps.get('status')}")
        if caps.get("combined_digest"):
            print("Capability digest:", caps["combined_digest"])
        print("Capability integrity:", caps.get("integrity", "UNVERIFIED"))
        print("Capability authority:", caps.get("authority", "NOT_ESTABLISHED"))
        if caps.get("adapter_ids"):
            print("Capability adapters:", ", ".join(caps["adapter_ids"]))
        if caps.get("error"):
            print(" - error:", caps["error"])
    if "compiled_policy" in result and not compiled_only:
        compiled = result["compiled_policy"]
        if compiled.get("error"):
            print("Compiled policy: FAIL —", compiled["error"])
        else:
            print(render_compiled_policy_view(compiled), end="")
    if "routing" in result:
        r = result["routing"]
        print("Canonical operations:", ", ".join(r["canonical_operations"]) or "(none)")
        print("Routing policies:", ", ".join(r["policies"]) or "(none)")
        if r["matched_resources"]:
            print("Matched resources:")
            for x in r["matched_resources"]:
                print(" -", x)
        print("Routing mode:", r["routing_mode"], "status=", r["routing_status"])
        if r["effect_floors"]:
            print("Effect floors:", ", ".join(f"{k}={v}" for k, v in r["effect_floors"].items()))
        for x in r["warnings"]:
            print(" - warning:", x)
        for x in r["errors"]:
            print(" - error:", x)
    if "execution_boundary" in result:
        b = result["execution_boundary"]
        print(f"Execution boundary: {b['status']} — decision={b['decision']}")
        print("Actual operations:", ", ".join(b["actual_operations"]) or "(none)")
        print(f"Effective risk: Effect={b['effective_effect'] or '(unknown)'} Exposure={b['effective_exposure'] or '(unknown)'} gate={b['action_gate'] or '(none)'}")
        if b["targets"]:
            print("Targets:", ", ".join(b["targets"]))
        if b.get("action_digest"):
            print("Action digest:", b["action_digest"])
        for x in b["escalations"]:
            print(" - escalation:", x)
        for x in b["warnings"]:
            print(" - warning:", x)
        for x in b["errors"]:
            print(" - error:", x)
    if "runtime_action" in result:
        ra = result["runtime_action"]
        print(f"Runtime action assertion: {ra['status']} — schema={ra['schema_status']} adapter_trust={ra['adapter_trust']}")
        if "boundary" in ra:
            b = ra["boundary"]
            print(f"Runtime action boundary: {b['status']} — decision={b['decision']} Effect={b['effective_effect'] or '(unknown)'} Exposure={b['effective_exposure'] or '(unknown)'}")
        for x in ra.get("warnings", []):
            print(" - warning:", x)
        for x in ra.get("errors", []):
            print(" - error:", x)
    if "approval_assertion" in result:
        a = result["approval_assertion"]
        print(f"Approval assertion: {a['object_validity']} — schema={a['schema_status']} temporal={a['temporal']} binding={a['binding']}")
        print(f"Authorization: {a['authorization']} (authority={a['authority']})")
        for x in a.get("warnings", []):
            print(" - warning:", x)
        for x in a.get("errors", []):
            print(" - error:", x)
    if "readiness" in result:
        r = result["readiness"]
        print(f"Documented {r['mode']} readiness: {r['documented']}")
        print(f"Source-evidence-verified {r['mode']} readiness: {r['evidence_verified']}")
        print(f"Execution-verified {r['mode']} readiness: {r['execution_verified']}")
        if r["documented"] != "PASS" or r["verified"] != "PASS":
            print("Documented checks:")
            print_checks([Check(**x) for x in r["documented_checks"]])
            print("Verified checks:")
            print_checks([Check(**x) for x in r["verified_checks"]])
        for warning in r.get("warnings", []):
            print(" - warning:", warning)
    if "distribution" in result:
        d = result["distribution"]
        print(f"Distribution validation: {d['status']} — {d['detail']}")
        for field in [
            "missing", "unexpected", "forbidden", "unsafe_entries", "duplicate_entries", "name_collisions",
            "resource_limit_violations", "symlinks", "outside_root", "bundle_failures", "integrity_failures",
            "release_integrity_failures"
        ]:
            for x in d[field]:
                print(f" - {field}:", x)
    if "release_integrity" in result:
        ri = result["release_integrity"]
        print(f"Release-manifest verification: {ri['status']}")
        for x in ri.get("errors", []):
            print(" - error:", x)
    if "integrity" in result:
        i = result["integrity"]
        print(f"Trusted-manifest verification: {i['status']}")
        for x in i["errors"]:
            print(" - error:", x)
    if "emitted_trust_manifest" in result:
        print("Trust manifest written:", result["emitted_trust_manifest"]["path"])
    if "trust_manifest_error" in result:
        print("Trust manifest error:", result["trust_manifest_error"])
    if "protected_override" in result:
        o = result["protected_override"]
        print(f"Protected override object: {o['object_validity']} (binding={o.get('binding')})")
        print(f"Authorization: {o['authorization']} (authority={o['authority']}, task_approval={o['task_approval']})")
        for x in o["errors"]:
            print(" - error:", x)
        for x in o["warnings"]:
            print(" - warning:", x)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
