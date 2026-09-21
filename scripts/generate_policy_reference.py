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


def render_generated_reference() -> str:
    contract = policy_validate.load_json(ROOT / "POLICY_CONTRACT.json")
    return policy_validate.render_generated_policy_reference(contract)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate or verify the generated POLICY_CONTRACT.json reference"
    )
    parser.add_argument("--check", action="store_true", help="fail if the generated reference is stale")
    parser.add_argument("--stdout", action="store_true", help="print generated reference instead of writing it")
    args = parser.parse_args()

    path = ROOT / policy_validate.GENERATED_POLICY_PATH
    generated = render_generated_reference()
    current = path.read_text(encoding="utf-8") if path.is_file() else None
    if args.check:
        if current != generated:
            print(
                "Generated policy reference is stale; run python scripts/generate_policy_reference.py",
                file=sys.stderr,
            )
            return 1
        print("Generated policy reference: PASS")
        return 0
    if args.stdout:
        print(generated, end="")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generated, encoding="utf-8")
    print(f"Updated {policy_validate.GENERATED_POLICY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
