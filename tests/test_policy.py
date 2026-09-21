from __future__ import annotations

import unittest

from .policy_test_support import ROOT, mod


class FacadeCompatibilityTests(unittest.TestCase):
    def test_validator_is_modular_with_compatibility_facade(self):
        facade = (ROOT / "scripts" / "validate.py").read_text(encoding="utf-8")
        self.assertLessEqual(len(facade.splitlines()), 450)
        self.assertEqual("validation.routing", mod.route_policies.__module__)
        self.assertEqual("validation.risk", mod.derive_exposure_floor.__module__)
        self.assertEqual("validation.runtime", mod.evaluate_execution_boundary.__module__)
        self.assertEqual("validation.integrity", mod.write_release_manifest.__module__)
        self.assertEqual("validation.readiness", mod.readiness.__module__)
        self.assertEqual("validation.bundle", mod.bundle_checks.__module__)
        self.assertEqual("validation.distribution", mod.validate_distribution.__module__)
        self.assertEqual("validation.approval", mod.validate_approval_assertion.__module__)
        self.assertEqual("validation.override", mod.validate_protected_override.__module__)
        self.assertIn("from validation.runtime import *", facade)
        self.assertIn("from validation.distribution import", facade)


if __name__ == "__main__":
    unittest.main()
