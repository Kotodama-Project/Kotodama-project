from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "tools" / "validate_migration_batch_a022.py"
SPEC = importlib.util.spec_from_file_location("validate_migration_batch_a022", VALIDATOR_PATH)
assert SPEC is not None and SPEC.loader is not None
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class A022MigrationBatchTests(unittest.TestCase):
    def _fixture(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name) / "candidate"
        root.mkdir()
        for relative in VALIDATOR.REQUIRED_PATHS:
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        return temporary, root

    @staticmethod
    def _manifest(root: Path) -> dict[str, object]:
        return json.loads(
            (root / VALIDATOR.MANIFEST_PATH).read_text(encoding="utf-8")
        )

    @staticmethod
    def _write_manifest(root: Path, manifest: dict[str, object]) -> None:
        (root / VALIDATOR.MANIFEST_PATH).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_exact_candidate_passes_but_admission_remains_blocked(self) -> None:
        result = VALIDATOR.validate(ROOT)
        manifest = self._manifest(ROOT)

        self.assertEqual(result["status"], "PASS", result["errors"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["source_entries"], 16)
        self.assertEqual(
            result["decisions"],
            {"PRIVATE_RETAIN": 8, "PUBLIC_REAUTHOR": 6, "SUPERSEDED": 2},
        )
        self.assertEqual(result["unique_reauthored_destinations"], 4)
        self.assertEqual(result["source_architecture_blob_reuse"], 0)
        self.assertEqual(result["private_source_path_leakage"], 0)
        self.assertEqual(result["candidate_scan_findings"], 0)
        self.assertEqual(result["admission_status"], "BLOCKED")
        self.assertEqual(
            manifest["component_license"]["source_derived_scope"],
            sorted(VALIDATOR.DESTINATIONS),
        )
        self.assertIn(
            "MISSING_APPLICABLE_A022_PRIVATE_SOURCE_HISTORY_RECEIPT",
            result["no_go_reasons"],
        )

    def test_candidate_hashes_are_stable_across_checkout_line_endings(self) -> None:
        temporary, root = self._fixture()
        with temporary:
            text_paths = [*VALIDATOR.DESTINATIONS, VALIDATOR.LICENSE_PATH]
            for relative in text_paths:
                path = root / relative
                path.write_bytes(
                    path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                )

            result = VALIDATOR.validate(root)

            self.assertEqual(result["status"], "PASS", result["errors"])
            self.assertEqual(result["admission_status"], "BLOCKED")

    def test_required_document_symlink_is_rejected_before_resolution(self) -> None:
        temporary, root = self._fixture()
        with temporary:
            destination = root / "docs" / "architecture" / "README.md"
            target = root / "replacement.md"
            shutil.copy2(destination, target)
            destination.unlink()
            try:
                destination.symlink_to(target)
            except OSError as error:
                self.skipTest(f"symlink creation unavailable: {error}")

            result = VALIDATOR.validate(root)

            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(
                any("symlink" in error for error in result["errors"]),
                result["errors"],
            )

    def test_oversized_required_file_is_rejected_before_unbounded_read(self) -> None:
        temporary, root = self._fixture()
        with temporary:
            target = root / "docs" / "architecture" / "README.md"
            target.write_bytes(b"x" * (256 * 1024 + 1))
            original_read_bytes = Path.read_bytes

            def reject_unbounded_read(path: Path) -> bytes:
                if path == target:
                    raise AssertionError("oversized file was read without a bound")
                return original_read_bytes(path)

            with patch.object(Path, "read_bytes", reject_unbounded_read):
                result = VALIDATOR.validate(root)

            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(
                any("exceeds 262144 bytes" in error for error in result["errors"]),
                result["errors"],
            )

    def test_non_string_source_path_is_refused_without_sorting_error(self) -> None:
        temporary, root = self._fixture()
        with temporary:
            manifest = self._manifest(root)
            manifest["entries"][0]["source_path"] = None
            self._write_manifest(root, manifest)

            result = VALIDATOR.validate(root)

            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(
                any("source paths must be strings" in error for error in result["errors"]),
                result["errors"],
            )

    def test_source_path_scan_exemption_is_limited_to_manifest_entries(self) -> None:
        temporary, root = self._fixture()
        with temporary:
            manifest = self._manifest(root)
            manifest["metadata"] = {
                "source_path": "https://private.example.invalid/unreviewed"
            }
            self._write_manifest(root, manifest)

            result = VALIDATOR.validate(root)

            self.assertEqual(result["status"], "FAIL")
            self.assertGreater(result["candidate_scan_findings"], 0)
            self.assertTrue(
                any("live_connection_url" in error for error in result["errors"]),
                result["errors"],
            )

    def test_missing_null_contract_fields_are_not_equivalent_to_explicit_null(self) -> None:
        temporary, root = self._fixture()
        with temporary:
            manifest = self._manifest(root)
            private = next(
                entry for entry in manifest["entries"] if entry["decision"] == "PRIVATE_RETAIN"
            )
            del private["destination_path"]
            self._write_manifest(root, manifest)

            result = VALIDATOR.validate(root)

            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(
                any("missing required entry fields" in error for error in result["errors"]),
                result["errors"],
            )

    def test_exact_sixteen_source_mapping_fails_closed_on_drift(self) -> None:
        mutations = (
            lambda manifest: manifest["entries"].append(copy.deepcopy(manifest["entries"][0])),
            lambda manifest: manifest["entries"][0].__setitem__("source_mode", "100755"),
            lambda manifest: manifest["entries"][0].__setitem__(
                "source_blob_sha", "0" * 40
            ),
            lambda manifest: manifest["entries"][0].__setitem__(
                "source_path", "architecture/unlisted.md"
            ),
        )

        for mutate in mutations:
            with self.subTest(mutation=mutate):
                temporary, root = self._fixture()
                with temporary:
                    manifest = self._manifest(root)
                    mutate(manifest)
                    self._write_manifest(root, manifest)
                    result = VALIDATOR.validate(root)
                    self.assertEqual(result["status"], "FAIL")
                    self.assertTrue(
                        any("mapping" in error or "16" in error for error in result["errors"]),
                        result["errors"],
                    )

    def test_private_retain_and_unchanged_blob_controls_fail_closed(self) -> None:
        temporary, root = self._fixture()
        with temporary:
            manifest = self._manifest(root)
            private = next(
                entry for entry in manifest["entries"] if entry["decision"] == "PRIVATE_RETAIN"
            )
            private["destination_path"] = "docs/architecture/README.md"
            private["destination_blob_sha"] = private["source_blob_sha"]
            private["body_exported"] = True
            copied_destination = root / "docs" / "architecture" / "README.md"
            private["source_blob_sha"] = VALIDATOR.git_blob_sha(
                copied_destination.read_bytes()
                .replace(b"\r\n", b"\n")
                .replace(b"\r", b"\n")
            )
            self._write_manifest(root, manifest)

            result = VALIDATOR.validate(root)
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(
                any("PRIVATE_RETAIN" in error for error in result["errors"]),
                result["errors"],
            )
            self.assertTrue(
                any("mapping" in error for error in result["errors"]), result["errors"]
            )
            self.assertGreater(result["source_architecture_blob_reuse"], 0)

    def test_consolidation_coverage_and_private_path_leakage_fail_closed(self) -> None:
        temporary, root = self._fixture()
        with temporary:
            manifest = self._manifest(root)
            coordination = [
                entry
                for entry in manifest["entries"]
                if entry.get("consolidation_group") == "coordination"
            ]
            coordination[1]["semantic_coverage"] = list(
                coordination[0]["semantic_coverage"]
            )
            private_path = next(
                entry["source_path"]
                for entry in manifest["entries"]
                if entry["decision"] == "PRIVATE_RETAIN"
            )
            self._write_manifest(root, manifest)
            target = root / "docs" / "architecture" / "README.md"
            target.write_text(
                target.read_text(encoding="utf-8") + f"\n{private_path}\n",
                encoding="utf-8",
            )

            result = VALIDATOR.validate(root)
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(
                any("coverage overlaps" in error for error in result["errors"]),
                result["errors"],
            )
            self.assertGreater(result["private_source_path_leakage"], 0)

    def test_candidate_scan_and_blocked_gates_fail_closed(self) -> None:
        temporary, root = self._fixture()
        with temporary:
            manifest = self._manifest(root)
            manifest["admission_gates"]["license_and_provenance"] = "PASS"
            self._write_manifest(root, manifest)
            target = root / "docs" / "architecture" / "plan-runtime.md"
            target.write_text(
                target.read_text(encoding="utf-8") + "\ncontact: person@example.invalid\n",
                encoding="utf-8",
            )

            result = VALIDATOR.validate(root)
            self.assertEqual(result["status"], "FAIL")
            self.assertGreater(result["candidate_scan_findings"], 0)
            self.assertTrue(
                any("admission gates" in error for error in result["errors"]),
                result["errors"],
            )
            self.assertEqual(result["admission_status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
