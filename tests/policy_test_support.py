from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SPEC = importlib.util.spec_from_file_location("uad_validate", ROOT / "scripts" / "validate.py")
mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)

CONSUMER_SPEC = importlib.util.spec_from_file_location(
    "uad_package_consumer", ROOT / "scripts" / "package_consumer.py"
)
consumer_mod = importlib.util.module_from_spec(CONSUMER_SPEC)
assert CONSUMER_SPEC and CONSUMER_SPEC.loader
sys.modules[CONSUMER_SPEC.name] = consumer_mod
CONSUMER_SPEC.loader.exec_module(consumer_mod)
