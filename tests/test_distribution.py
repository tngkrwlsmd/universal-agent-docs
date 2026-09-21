from __future__ import annotations

import json
import shutil
import stat
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

from tests.policy_test_support import ROOT, mod

class DistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = mod.load_json(ROOT / "POLICY_CONTRACT.json")
        cls.required = cls.contract["distribution"]["required_files"]
        cls.canonical_root = cls.contract["distribution"]["canonical_root"]

    def write_valid_zip(self, path: Path, mutate=None, extras=None):
        with zipfile.ZipFile(path, "w") as zf:
            for rel in self.required:
                data = (ROOT / rel).read_bytes()
                if mutate is not None:
                    data = mutate(rel, data)
                zf.writestr(f"{self.canonical_root}/{rel}", data)
            for name, data in extras or []:
                zf.writestr(name, data)

    def test_complete_zip_passes(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "universal-agent-docs.zip"
            self.write_valid_zip(z)
            result = mod.validate_distribution(z, self.contract)
            self.assertEqual("PASS", result["status"], result)

    def test_partial_zip_fails_missing_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "partial.zip"
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr("universal-agent-docs/AGENTS.md", "ok")
            result = mod.validate_distribution(z, self.contract)
            self.assertEqual("FAIL", result["status"])
            self.assertTrue(result["missing"])

    def test_zip_with_pyc_fails(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "bad.zip"
            self.write_valid_zip(z, extras=[("universal-agent-docs/scripts/__pycache__/x.pyc", b"x")])
            result = mod.validate_distribution(z, self.contract)
            self.assertEqual("FAIL", result["status"])
            self.assertTrue(result["forbidden"])

    def test_zip_with_unexpected_file_fails(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "bad.zip"
            self.write_valid_zip(z, extras=[("universal-agent-docs/EXTRA.txt", b"x")])
            result = mod.validate_distribution(z, self.contract)
            self.assertEqual("FAIL", result["status"])
            self.assertIn("EXTRA.txt", result["unexpected"])

    def test_zip_traversal_entry_fails(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "bad.zip"
            self.write_valid_zip(z, extras=[("../outside.txt", b"x")])
            result = mod.validate_distribution(z, self.contract)
            self.assertEqual("FAIL", result["status"])
            self.assertTrue(result["unsafe_entries"])

    def test_zip_absolute_entry_fails(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "bad.zip"
            self.write_valid_zip(z, extras=[("/outside.txt", b"x")])
            result = mod.validate_distribution(z, self.contract)
            self.assertEqual("FAIL", result["status"])
            self.assertTrue(result["unsafe_entries"])

    def test_zip_duplicate_entry_fails(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "bad.zip"
            self.write_valid_zip(z)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(z, "a") as zf:
                    zf.writestr("universal-agent-docs/AGENTS.md", "duplicate")
            result = mod.validate_distribution(z, self.contract)
            self.assertEqual("FAIL", result["status"])
            self.assertTrue(result["duplicate_entries"])

    def test_zip_symlink_entry_fails(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "bad.zip"
            self.write_valid_zip(z)
            info = zipfile.ZipInfo("universal-agent-docs/link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(z, "a") as zf:
                zf.writestr(info, "AGENTS.md")
            result = mod.validate_distribution(z, self.contract)
            self.assertEqual("FAIL", result["status"])
            self.assertTrue(result["symlinks"])


    def test_zip_casefold_name_collision_fails(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "bad.zip"
            self.write_valid_zip(z, extras=[(f"{self.canonical_root}/readme.md", b"x")])
            result = mod.validate_distribution(z, self.contract)
            self.assertEqual("FAIL", result["status"])
            self.assertTrue(result["name_collisions"])

    def test_zip_unicode_normalization_collision_fails(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "bad.zip"
            self.write_valid_zip(z, extras=[
                (f"{self.canonical_root}/caf\u00e9.txt", b"x"),
                (f"{self.canonical_root}/cafe\u0301.txt", b"x"),
            ])
            result = mod.validate_distribution(z, self.contract)
            self.assertEqual("FAIL", result["status"])
            self.assertTrue(result["name_collisions"])

    def test_zip_file_size_limit_fails_before_extraction(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "bad.zip"
            limit = self.contract["distribution"]["max_file_uncompressed_bytes"]
            def mutate(rel, data):
                return b"x" * (limit + 1) if rel == "AGENTS.md" else data
            self.write_valid_zip(z, mutate=mutate)
            result = mod.validate_distribution(z, self.contract)
            self.assertEqual("FAIL", result["status"])
            self.assertTrue(result["resource_limit_violations"])

    def test_zip_compression_ratio_limit_fails(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "bad.zip"
            with zipfile.ZipFile(z, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for rel in self.required:
                    data = (ROOT / rel).read_bytes()
                    if rel == "AGENTS.md":
                        data = b"A" * 300000
                    zf.writestr(f"{self.canonical_root}/{rel}", data)
            result = mod.validate_distribution(z, self.contract)
            self.assertEqual("FAIL", result["status"])
            self.assertTrue(any("compression ratio" in x for x in result["resource_limit_violations"]), result)

    def test_semantically_broken_bundle_fails_even_with_complete_manifest(self):
        def mutate(rel, data):
            if rel == "POLICY_CONTRACT.json":
                obj = json.loads(data.decode("utf-8"))
                obj["project_name"] = "wrong-name"
                return json.dumps(obj).encode("utf-8")
            return data

        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "bad.zip"
            self.write_valid_zip(z, mutate=mutate)
            result = mod.validate_distribution(z, self.contract)
            self.assertEqual("FAIL", result["status"])
            self.assertTrue(result["bundle_failures"])

    def test_trusted_manifest_detects_semantic_policy_mutation_in_distribution(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = Path(td) / "trusted.json"
            mod.write_trust_manifest(manifest, ROOT)

            def mutate(rel, data):
                if rel == "POLICIES.md":
                    text = data.decode("utf-8")
                    text = text.replace(
                        "operational instruction으로 승격하지 않는다",
                        "operational instruction으로 승격한다",
                        1,
                    )
                    return text.encode("utf-8")
                return data

            z = Path(td) / "tampered.zip"
            self.write_valid_zip(z, mutate=mutate)
            result = mod.validate_distribution(z, self.contract, manifest)
            self.assertEqual("FAIL", result["status"])
            self.assertIn("sha256 mismatch: POLICIES.md", result["integrity_failures"])

    def test_full_release_manifest_verifies_archive_and_all_distribution_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            z = root / "universal-agent-docs.zip"
            manifest = root / "universal-agent-docs.release.json"
            self.write_valid_zip(z)
            data = mod.write_release_manifest(manifest, z, ROOT)
            self.assertIn("PROJECT.md", data["files"])
            self.assertIn("tests/test_policy.py", data["files"])
            result = mod.validate_distribution(z, self.contract, release_manifest=manifest)
            self.assertEqual("PASS", result["status"], result)

    def test_full_release_manifest_detects_non_core_release_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            z = root / "universal-agent-docs.zip"
            manifest = root / "universal-agent-docs.release.json"
            self.write_valid_zip(z)
            mod.write_release_manifest(manifest, z, ROOT)

            def mutate(rel, data):
                if rel == "README.md":
                    return data + b"\n"
                return data

            self.write_valid_zip(z, mutate=mutate)
            result = mod.validate_distribution(z, self.contract, release_manifest=manifest)
            self.assertEqual("FAIL", result["status"], result)
            self.assertTrue(result["release_integrity_failures"], result)
            self.assertTrue(any("artifact SHA-256 mismatch" in x or "README.md" in x for x in result["release_integrity_failures"]), result)

    def test_complete_directory_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / self.canonical_root
            root.mkdir()
            for rel in self.required:
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / rel, target)
            result = mod.validate_distribution(root, self.contract)
            self.assertEqual("PASS", result["status"], result)
