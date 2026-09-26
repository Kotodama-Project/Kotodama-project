from __future__ import annotations

import copy
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
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

    def test_provenance_shape_and_fixed_metadata_fail_closed(self) -> None:
        mutations = {
            "extra root field": lambda p: p.update(source_body="ordinary fixture prose"),
            "extra row field": lambda p: p["entries"][0].update(source_body="ordinary fixture prose"),
            "missing root field": lambda p: p.pop("entry_scope"),
            "missing row field": lambda p: p["entries"][0].pop("decision"),
            "changed author handle": lambda p: p["entries"][0].update(author_github_handles=["fixture-author"]),
            "changed history count": lambda p: p["entries"][0].update(commits_touching_source=99),
            "changed withheld count": lambda p: p["entries"][0].update(withheld_author_identities=99),
            "changed identity policy": lambda p: p.update(author_identity_policy="ordinary fixture prose"),
            "changed entry scope": lambda p: p.update(entry_scope="ordinary fixture prose"),
            "changed decision": lambda p: p["entries"][0].update(decision="PRIVATE_RETAIN"),
            "changed destination": lambda p: p["entries"][0].update(destination_path="ordinary fixture prose"),
            "missing source path": lambda p: p["entries"][0].pop("source_path"),
            "invalid source path type": lambda p: p["entries"][0].update(source_path=[]),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                temporary, root = self._fixture()
                with temporary:
                    path = root / VALIDATOR.PROVENANCE_PATH
                    provenance = json.loads(path.read_text(encoding="utf-8"))
                    mutate(provenance)
                    path.write_text(json.dumps(provenance), encoding="utf-8")
                    result = VALIDATOR.validate(root)
                    self.assertEqual(result["status"], "FAIL", result["errors"])
                    self.assertEqual(result["admission_status"], "BLOCKED")
                    self.assertTrue(any("provenance" in error for error in result["errors"]))


    def test_fixed_manifest_rejects_extra_and_changed_metadata(self) -> None:
        mutations = {
            "extra root": lambda m: m.update(note="ordinary fixture prose"),
            "extra nested source": lambda m: m["source"].update(note="ordinary fixture prose"),
            "extra entry": lambda m: m["entries"][0].update(note="ordinary fixture prose"),
            "changed rationale": lambda m: m["entries"][0].update(rationale="ordinary fixture prose"),
            "invalid review type": lambda m: m["admission_gates"].update(independent_review=[]),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                temporary, root = self._fixture()
                with temporary:
                    path = root / VALIDATOR.MANIFEST_PATH
                    manifest = json.loads(path.read_text(encoding="utf-8"))
                    mutate(manifest)
                    path.write_text(json.dumps(manifest), encoding="utf-8")
                    result = VALIDATOR.validate(root)
                    self.assertEqual(result["status"], "FAIL", result["errors"])
                    self.assertEqual(result["admission_status"], "BLOCKED")
                    self.assertIn("manifest must match the fixed public metadata record", result["errors"])

    def test_metadata_formatting_and_both_review_states_are_preserved(self) -> None:
        for review in ("PENDING", "PASSED_INDEPENDENT_REVIEW"):
            with self.subTest(review=review):
                temporary, root = self._fixture()
                with temporary:
                    for relative in (VALIDATOR.MANIFEST_PATH, VALIDATOR.PROVENANCE_PATH):
                        path = root / relative
                        value = json.loads(path.read_text(encoding="utf-8"))
                        if relative == VALIDATOR.MANIFEST_PATH:
                            value["admission_gates"]["independent_review"] = review
                        path.write_text(json.dumps(value, sort_keys=True, indent=4), encoding="utf-8")
                    result = VALIDATOR.validate(root)
                    self.assertEqual(result["status"], "PASS", result["errors"])
                    self.assertEqual(result["admission_status"], "BLOCKED" if review == "PENDING" else "ADMITTED")

    def test_duplicate_fields_and_nonfinite_json_are_refused(self) -> None:
        for relative in (VALIDATOR.MANIFEST_PATH, VALIDATOR.PROVENANCE_PATH):
            for invalid in ("duplicate", "NaN", "Infinity", "1e999"):
                with self.subTest(path=relative, invalid=invalid):
                    temporary, root = self._fixture()
                    with temporary:
                        path = root / relative
                        text = path.read_text(encoding="utf-8")
                        if invalid == "duplicate":
                            field = '"batch_id": "A022",'
                            self.assertEqual(text.count(field), 1)
                            text = text.replace(field, field + " " + field, 1)
                        else:
                            text = text.replace("{", '{"numeric_fixture": ' + invalid + ",", 1)
                        path.write_text(text, encoding="utf-8")
                        result = VALIDATOR.validate(root)
                        self.assertEqual(result["status"], "FAIL", result["errors"])
                        self.assertEqual(result["admission_status"], "BLOCKED")
                        self.assertTrue(any("UTF-8 JSON" in error for error in result["errors"]), result["errors"])

    def test_windows_user_path_scan_covers_serialized_text(self) -> None:
        value = "C:" + chr(92) + "Users" + chr(92) + "fixture" + chr(92) + "note.txt"
        for text in (value, json.dumps({"note": value}), repr(value)):
            with self.subTest(serialized=text != value):
                findings = VALIDATOR._scan_text(Path("fixture.json"), text)
                self.assertTrue(any("absolute_user_path" in finding for finding in findings))

    def test_private_receipt_digest_is_bound_to_the_public_record(self) -> None:
        temporary, root = self._fixture()
        with temporary:
            path = root / VALIDATOR.PROVENANCE_PATH
            provenance = json.loads(path.read_text(encoding="utf-8"))
            provenance["private_source_history_receipt_sha256"] = "0" * 64
            path.write_text(json.dumps(provenance), encoding="utf-8")
            result = VALIDATOR.validate(root)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["admission_status"], "BLOCKED")
            self.assertIn(
                "provenance must bind the private source-history receipt digest",
                result["errors"],
            )


    def test_read_limit_accepts_boundary_and_refuses_growth(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = Path("fixture.json")
            (root / relative).write_bytes(b"x" * 8)
            original_fdopen = VALIDATOR.os.fdopen
            for grew in (False, True):
                with self.subTest(grew=grew):
                    reads = []

                    @contextmanager
                    def observed_open(fd, mode):
                        with original_fdopen(fd, mode) as stream:
                            proxy = mock.Mock(wraps=stream)

                            def bounded_read(size):
                                reads.append(size)
                                self.assertEqual(size, 9)
                                return b"x" * 9 if grew else stream.read(size)

                            proxy.read.side_effect = bounded_read
                            yield proxy

                    errors: list[str] = []
                    with mock.patch.object(VALIDATOR, "MAX_FILE_BYTES", 8), mock.patch.object(
                        VALIDATOR.os, "fdopen", side_effect=observed_open
                    ):
                        data = VALIDATOR._read_bounded(root, relative, errors)
                    self.assertEqual(reads, [9])
                    self.assertEqual(data, None if grew else b"x" * 8)
                    self.assertEqual(errors, ["file exceeds 8 bytes: fixture.json"] if grew else [])


    def test_reparse_parent_and_leaf_are_refused_before_open(self) -> None:
        # Portable metadata fixture; real Windows junction behavior belongs to CI.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            relative = Path("nested/fixture.json")
            (root / relative).parent.mkdir()
            (root / relative).write_bytes(b"{}")
            original_lstat = Path.lstat
            for target in ((root / relative).parent, root / relative):
                for attributes, tag in ((0x400, 0), (0, 0xA0000003)):
                    with self.subTest(target=target.name, attributes=attributes, tag=tag):
                        def reparse_lstat(path, *args, **kwargs):
                            info = original_lstat(path, *args, **kwargs)
                            if path == target:
                                return SimpleNamespace(
                                    st_mode=info.st_mode, st_dev=info.st_dev,
                                    st_ino=info.st_ino, st_size=info.st_size,
                                    st_file_attributes=attributes, st_reparse_tag=tag,
                                )
                            return info

                        errors: list[str] = []
                        with mock.patch.object(Path, "lstat", reparse_lstat), mock.patch.object(
                            VALIDATOR.os, "open", side_effect=AssertionError("reparse path opened")
                        ):
                            self.assertIsNone(VALIDATOR._read_bounded(root, relative, errors))
                        self.assertEqual(errors, ["reparse point is not allowed: nested/fixture.json"])


    def test_resolved_candidate_must_stay_inside_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            relative = Path("fixture.json")
            candidate = root / relative
            candidate.write_bytes(b"{}")
            original_resolve = Path.resolve

            def escaped_resolution(path, *args, **kwargs):
                if path == candidate:
                    return root.parent / "outside-fixture.json"
                return original_resolve(path, *args, **kwargs)

            errors: list[str] = []
            with mock.patch.object(Path, "resolve", escaped_resolution), mock.patch.object(
                VALIDATOR.os, "open", side_effect=AssertionError("escaping path opened")
            ):
                self.assertIsNone(VALIDATOR._read_bounded(root, relative, errors))
            self.assertEqual(errors, ["missing, escaping, or unreadable path: fixture.json"])


    def test_required_parent_symlink_is_refused(self) -> None:
        temporary, root = self._fixture()
        with temporary:
            directory = root / Path(next(iter(VALIDATOR.DESTINATIONS))).parent
            target = root / "unlisted-fixture-directory"
            directory.rename(target)
            try:
                directory.symlink_to(target, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlink creation unavailable: {error}")
            result = VALIDATOR.validate(root)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["admission_status"], "BLOCKED")
            for relative in VALIDATOR.DESTINATIONS:
                self.assertIn(f"symlink is not allowed: {relative}", result["errors"])


    def test_exact_candidate_passes_and_reports_the_recorded_admission(self) -> None:
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
        self.assertEqual(
            manifest["component_license"]["source_derived_scope"],
            sorted(VALIDATOR.DESTINATIONS),
        )
        if manifest["admission_gates"]["independent_review"] == "PASSED_INDEPENDENT_REVIEW":
            self.assertEqual(result["admission_status"], "ADMITTED")
            self.assertEqual(result["no_go_reasons"], [])
        else:
            self.assertEqual(result["admission_status"], "BLOCKED")
            self.assertEqual(result["no_go_reasons"], ["INDEPENDENT_REVIEW_PENDING"])

    def test_admission_gates_and_provenance_fail_closed(self) -> None:
        def gate(value):
            return lambda manifest, provenance: manifest["admission_gates"].update(value)

        def prov(update):
            return lambda manifest, provenance: update(provenance)

        mutations = {
            "issue 25 gate reopened": gate({"license_and_provenance": "BLOCKED_ISSUE_25"}),
            "governance gate reopened": gate({"public_governance": "BLOCKED_PR_18_AND_ISSUE_19"}),
            "unknown review state": gate({"independent_review": "APPROVED"}),
            "receipt digest removed": prov(lambda p: p.pop("private_source_history_receipt_sha256")),
            "receipt did not pass": prov(lambda p: p.update(private_source_history_result="FINDINGS")),
            "author is not a handle": prov(lambda p: p["entries"][0].update(author_github_handles=["Some Person"])),
            "re-authored source missing": prov(lambda p: p["entries"].pop()),
            # The private path is read from the manifest so this file never names it.
            "private source listed": lambda manifest, provenance: provenance["entries"].append(
                dict(
                    provenance["entries"][0],
                    source_path=next(
                        entry["source_path"]
                        for entry in manifest["entries"]
                        if entry["decision"] == "PRIVATE_RETAIN"
                    ),
                )
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                temporary, root = self._fixture()
                with temporary:
                    manifest = self._manifest(root)
                    provenance_path = root / VALIDATOR.PROVENANCE_PATH
                    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
                    mutate(manifest, provenance)
                    self._write_manifest(root, manifest)
                    provenance_path.write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
                    result = VALIDATOR.validate(root)
                    self.assertEqual(result["status"], "FAIL", label)
                    self.assertEqual(result["admission_status"], "BLOCKED", label)

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
            # Line endings must not change the admission decision either.
            self.assertEqual(
                result["admission_status"], VALIDATOR.validate(ROOT)["admission_status"]
            )

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
