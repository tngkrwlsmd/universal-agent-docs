#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import validate as policy_validate  # noqa: E402

ROOT = SCRIPT_DIR.parent


def render_updated_policies() -> str:
    contract = policy_validate.load_json(ROOT / "POLICY_CONTRACT.json")
    path = ROOT / "POLICIES.md"
    text = path.read_text(encoding="utf-8")
    generated = policy_validate.render_generated_policy_reference(contract)
    start = text.find(policy_validate.GENERATED_POLICY_START)
    end = text.find(policy_validate.GENERATED_POLICY_END)
    if start < 0 or end < start:
        raise RuntimeError("POLICIES.md is missing generated-policy-reference markers")
    end += len(policy_validate.GENERATED_POLICY_END)
    return text[:start] + generated + text[end:]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate or verify machine-owned POLICY_CONTRACT.json reference inside POLICIES.md"
    )
    parser.add_argument("--check", action="store_true", help="fail if the generated block is stale")
    parser.add_argument("--stdout", action="store_true", help="print the updated POLICIES.md instead of writing it")
    args = parser.parse_args()

    path = ROOT / "POLICIES.md"
    current = path.read_text(encoding="utf-8")
    updated = render_updated_policies()
    if args.check:
        if current != updated:
            print("Generated policy reference is stale; run python scripts/generate_policy_reference.py", file=sys.stderr)
            return 1
        print("Generated policy reference: PASS")
        return 0
    if args.stdout:
        print(updated, end="")
        return 0
    path.write_text(updated, encoding="utf-8")
    print("Updated POLICIES.md generated policy reference")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
