from __future__ import annotations

import importlib.util
import random
import sys
import tempfile
import zipfile
import unicodedata
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


validate = load_module("uad_validate_fuzz", ROOT / "scripts" / "validate.py")
package_mod = load_module("uad_package_fuzz", ROOT / "scripts" / "package.py")
consumer_package_mod = load_module("uad_consumer_package_fuzz", ROOT / "scripts" / "package_consumer.py")


class RoutingPropertyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = validate.load_json(ROOT / "POLICY_CONTRACT.json")
        cls.aliases = validate.load_routing_aliases(cls.contract)

    def test_nfkc_casefold_property_for_ascii_aliases(self):
        # Full-width ASCII should normalize to the same routing signal.
        samples = {
            "run tests": "test.execute",
            "terraform destroy": "cloud.resource_delete",
            "restart service": "service.restart",
            "change firewall rules": "network.configuration_change",
        }
        for phrase, expected in samples.items():
            wide = "".join(chr(ord(ch) + 0xFEE0) if 0x21 <= ord(ch) <= 0x7E else ch for ch in phrase.upper())
            with self.subTest(phrase=phrase, wide=wide):
                ops = validate.infer_operations(self.contract, wide, self.aliases)
                self.assertIn(expected, ops)

    def test_random_punctuation_and_whitespace_do_not_hide_high_risk_phrases(self):
        rng = random.Random(20260920)
        samples = {
            "terraform destroy": "cloud.resource_delete",
            "git reset --hard": "git.destructive_change",
            "delete all customer records in production": "database.destructive_change",
        }
        separators = [" ", "  ", "\t", " / ", " :: ", " !!! "]
        for phrase, expected in samples.items():
            words = phrase.split()
            for i in range(40):
                mutated = separators[rng.randrange(len(separators))].join(words)
                mutated = (" " * rng.randrange(3)) + mutated + ("!" * rng.randrange(3))
                with self.subTest(phrase=phrase, iteration=i, mutated=mutated):
                    ops = validate.infer_operations(self.contract, mutated, self.aliases)
                    self.assertIn(expected, ops)

    def test_korean_literal_token_does_not_match_longer_unrelated_word(self):
        # Guard the classic 로그 -> 로그인 false-positive across attached particles/suffixes.
        for suffix in ["", "은", "도", "에서", "처리", "화면", "버그"]:
            text = "로그인" + suffix
            with self.subTest(text=text):
                self.assertFalse(validate.phrase_matches(validate.normalize_text(text), "로그"))

    def test_enforcement_property_canonical_plan_is_authoritative_over_unknown_task_text(self):
        rng = random.Random(7)
        for i in range(100):
            unknown = "frobnicate_" + "".join(rng.choice("abcdef0123456789") for _ in range(12))
            result = validate.route_policies(
                self.contract,
                unknown,
                ["code.modify"],
                routing_mode="enforcement",
                aliases_doc=self.aliases,
            )
            with self.subTest(i=i, task=unknown):
                self.assertNotEqual("FAIL", result["routing_status"], result)
                self.assertEqual(["code.modify"], result["planned_canonical_operations"])
                self.assertEqual("UNCLASSIFIED", result["task_hint_status"])


class ArchivePropertyTests(unittest.TestCase):
    def test_traversal_variants_are_rejected(self):
        variants = [
            "../outside.txt",
            "../../outside.txt",
            "universal-agent-docs/../../outside.txt",
            "/absolute.txt",
            "C:/absolute.txt",
            "C:\\absolute.txt",
            "./../outside.txt",
        ]
        for name in variants:
            with self.subTest(name=name):
                normalized, error = validate.normalize_archive_entry(name)
                self.assertIsNotNone(error, (name, normalized))

    def test_safe_relative_paths_round_trip_without_parent_segments(self):
        rng = random.Random(99)
        alphabet = "abcdefghijklmnopqrstuvwxyz0123456789_-"
        for i in range(200):
            parts = ["".join(rng.choice(alphabet) for _ in range(rng.randint(1, 12))) for _ in range(rng.randint(1, 5))]
            name = "/".join(parts) + ".txt"
            normalized, error = validate.normalize_archive_entry(name)
            with self.subTest(i=i, name=name):
                self.assertIsNone(error)
                self.assertEqual(name, normalized)
                self.assertNotIn("..", normalized.split("/"))

    def test_unicode_normalization_collision_key_is_stable(self):
        composed = "universal-agent-docs/caf\u00e9.txt"
        decomposed = "universal-agent-docs/cafe\u0301.txt"
        self.assertNotEqual(composed, decomposed)
        self.assertEqual(unicodedata.normalize("NFC", composed), unicodedata.normalize("NFC", decomposed))
        self.assertEqual(validate._archive_collision_key(composed)[0], validate._archive_collision_key(decomposed)[0])


class PackagingPropertyTests(unittest.TestCase):
    def test_consumer_package_is_collision_safe_and_self_verifying(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            result = consumer_package_mod.package_consumer(out)
            self.assertEqual("PASS", result["status"], result)
            zip_path = Path(result["zip"])
            release = Path(result["release_manifest"])
            checked = consumer_package_mod.validate_consumer_zip(
                zip_path, validate.load_json(ROOT / "POLICY_CONTRACT.json"), release
            )
            self.assertEqual("PASS", checked["status"], checked)
            with zipfile.ZipFile(zip_path) as zf:
                infos = [x for x in zf.infolist() if not x.is_dir()]
                names = [x.filename for x in infos]
                self.assertTrue(all(x.compress_type == zipfile.ZIP_STORED for x in infos))
                readme = zf.read("universal-agent-docs-consumer/.agent-policy/README.md").decode("utf-8")
                adoption = zf.read("universal-agent-docs-consumer/.agent-policy/docs/adoption-profiles.md").decode("utf-8")
                project = zf.read("universal-agent-docs-consumer/.agent-policy/PROJECT.md")
            self.assertIn("universal-agent-docs-consumer/AGENTS.md", names)
            self.assertIn("universal-agent-docs-consumer/.agent-policy/README.md", names)
            self.assertNotIn("universal-agent-docs-consumer/README.md", names)
            self.assertNotIn("universal-agent-docs-consumer/LICENSE", names)
            self.assertNotIn("universal-agent-docs-consumer/requirements.txt", names)
            self.assertFalse(any(x.startswith("universal-agent-docs-consumer/tests/") for x in names))
            self.assertFalse(any(x.startswith("universal-agent-docs-consumer/.github/") for x in names))
            self.assertFalse(any(x.startswith("universal-agent-docs-consumer/.agent-policy/examples/") for x in names))
            self.assertNotIn("blob/main/examples/", readme)
            self.assertNotIn("blob/main/examples/", adoption)
            self.assertIn("matching canonical source artifact", readme)
            self.assertIn("matching canonical source artifact", adoption)
            self.assertEqual((ROOT / "templates" / "PROJECT.md").read_bytes(), project)

    def test_consumer_verifier_rejects_symlink_entry(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            result = consumer_package_mod.package_consumer(out)
            original = Path(result["zip"])
            bad = out / "consumer-symlink.zip"
            with zipfile.ZipFile(original) as src, zipfile.ZipFile(bad, "w") as dst:
                for info in src.infolist():
                    data = src.read(info.filename)
                    if info.filename == "universal-agent-docs-consumer/AGENTS.md":
                        link = zipfile.ZipInfo(info.filename, info.date_time)
                        link.create_system = 3
                        link.external_attr = (0o120777 << 16)
                        dst.writestr(link, b".agent-policy/AGENTS.md")
                    else:
                        dst.writestr(info, data)
            checked = consumer_package_mod.validate_consumer_zip(
                bad, validate.load_json(ROOT / "POLICY_CONTRACT.json")
            )
            self.assertEqual("FAIL", checked["status"], checked)
            self.assertTrue(any("symlink" in x for x in checked["errors"]), checked)

    def test_consumer_packager_is_deterministic_and_outputs_detached_files(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first = consumer_package_mod.package_consumer(Path(a))
            second = consumer_package_mod.package_consumer(Path(b))
            self.assertEqual("PASS", first["status"], first)
            self.assertEqual(first["sha256"], second["sha256"])
            self.assertEqual("universal-agent-docs-consumer.zip", Path(first["zip"]).name)
            self.assertEqual("universal-agent-docs-consumer.release.json", Path(first["release_manifest"]).name)
            self.assertEqual("universal-agent-docs-consumer.sha256", Path(first["sha256_file"]).name)
            with zipfile.ZipFile(first["zip"]) as zf:
                self.assertTrue(all(info.compress_type == zipfile.ZIP_STORED for info in zf.infolist() if not info.is_dir()))

    def test_packager_is_deterministic_and_outputs_detached_files(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first = package_mod.package(Path(a))
            second = package_mod.package(Path(b))
            self.assertEqual("PASS", first["status"], first)
            self.assertEqual(first["sha256"], second["sha256"])
            self.assertTrue(Path(first["zip"]).is_file())
            self.assertTrue(Path(first["trust_manifest"]).is_file())
            self.assertTrue(Path(first["release_manifest"]).is_file())
            self.assertTrue(Path(first["sha256_file"]).is_file())
            self.assertEqual("universal-agent-docs.zip", Path(first["zip"]).name)
            self.assertEqual("universal-agent-docs.trust.json", Path(first["trust_manifest"]).name)
            self.assertEqual("universal-agent-docs.release.json", Path(first["release_manifest"]).name)
            self.assertEqual("universal-agent-docs.sha256", Path(first["sha256_file"]).name)
            # Detached artifacts must not be entries in the canonical ZIP.
            import zipfile
            with zipfile.ZipFile(first["zip"]) as zf:
                names = set(zf.namelist())
                self.assertTrue(all(info.compress_type == zipfile.ZIP_STORED for info in zf.infolist() if not info.is_dir()))
            self.assertIn("universal-agent-docs/.gitattributes", names)
            self.assertIn("universal-agent-docs/PROJECT.md", names)
            self.assertIn("universal-agent-docs/templates/PROJECT.md", names)
            self.assertIn("universal-agent-docs/examples/consumer-basic/README.md", names)
            self.assertIn("universal-agent-docs/examples/runtime-adapter/README.md", names)
            self.assertIn("universal-agent-docs/examples/extensions/internal-sandbox-artifact.json", names)
            self.assertIn("universal-agent-docs/examples/capabilities/reference-sandbox-artifact-adapter.json", names)
            self.assertFalse(any(
                name.endswith(".trust.json") or name.endswith(".release.json") or name.endswith(".sha256")
                for name in names
            ))


if __name__ == "__main__":
    unittest.main()
