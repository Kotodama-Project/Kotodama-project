"""Regression tests for the clean-history A017 hierarchy batch and its admission record."""

from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import json
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "tools" / "validate_migration_batch_a017.py"
SPEC = importlib.util.spec_from_file_location("validate_migration_batch_a017", VALIDATOR_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class A017MigrationBatchTests(unittest.TestCase):
    def _candidate_copy(self, parent: Path) -> Path:
        candidate = parent / "candidate"
        for relative in VALIDATOR.REQUIRED_PATHS:
            source = ROOT / relative
            target = candidate / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        return candidate

    def _fixture(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        return temporary, self._candidate_copy(Path(temporary.name))

    def test_provenance_shape_and_fixed_metadata_fail_closed(self) -> None:
        mutations = {
            "extra root field": lambda p: p.update(source_body="ordinary fixture prose"),
            "extra row field": lambda p: p["entries"][0].update(source_body="ordinary fixture prose"),
            "missing root field": lambda p: p.pop("author_identity_policy"),
            "missing row field": lambda p: p["entries"][0].pop("decision"),
            "changed author handle": lambda p: p["entries"][0].update(author_github_handles=["fixture-author"]),
            "changed history count": lambda p: p["entries"][0].update(commits_touching_source=99),
            "changed withheld count": lambda p: p["entries"][0].update(withheld_author_identities=99),
            "changed identity policy": lambda p: p.update(author_identity_policy="ordinary fixture prose"),
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
                            field = '"batch_id": "A017",'
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
                findings = VALIDATOR._scan_text(Path("fixture.json"), text, include_private_refs=True)
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


    def test_oversized_file_is_refused_before_open(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = Path("fixture.json")
            (root / relative).write_bytes(b"x" * 9)
            errors: list[str] = []
            with mock.patch.object(VALIDATOR, "MAX_FILE_BYTES", 8), mock.patch.object(
                VALIDATOR.os, "open", side_effect=AssertionError("oversized file opened")
            ):
                self.assertIsNone(VALIDATOR._read_bounded(root, relative, errors))
            self.assertEqual(errors, ["file exceeds 8 bytes: fixture.json"])


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


    def test_required_file_symlink_is_refused(self) -> None:
        for relative in (VALIDATOR.MANIFEST_PATH, Path(next(iter(VALIDATOR.TEMPLATE_SPECS)))):
            with self.subTest(path=relative):
                temporary, root = self._fixture()
                with temporary:
                    candidate = root / relative
                    target = root / "unlisted-fixture.json"
                    shutil.copy2(candidate, target)
                    candidate.unlink()
                    try:
                        candidate.symlink_to(target)
                    except OSError as error:
                        self.skipTest(f"symlink creation unavailable: {error}")
                    result = VALIDATOR.validate(root)
                    self.assertEqual(result["status"], "FAIL")
                    self.assertEqual(result["admission_status"], "BLOCKED")
                    self.assertIn(f"symlink is not allowed: {relative.as_posix()}", result["errors"])


    def test_required_parent_symlink_is_refused(self) -> None:
        temporary, root = self._fixture()
        with temporary:
            directory = root / Path(next(iter(VALIDATOR.TEMPLATE_SPECS))).parent
            target = root / "unlisted-fixture-directory"
            directory.rename(target)
            try:
                directory.symlink_to(target, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlink creation unavailable: {error}")
            result = VALIDATOR.validate(root)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["admission_status"], "BLOCKED")
            for relative in VALIDATOR.TEMPLATE_SPECS:
                self.assertIn(f"symlink is not allowed: {relative}", result["errors"])


    def test_validation_never_uses_unbounded_destination_rereads(self) -> None:
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("unbounded read")):
            result = VALIDATOR.validate(ROOT)
        self.assertEqual(result["status"], "PASS", result["errors"])
        self.assertEqual(result["source_template_blob_reuse"], 0)

    def test_exact_candidate_passes_and_reports_the_recorded_admission(self) -> None:
        result = VALIDATOR.validate(ROOT)
        self.assertEqual(result["status"], "PASS", msg=result["errors"])
        self.assertEqual(result["source_entries"], 10)
        self.assertEqual(result["decisions"], {"RE_AUTHORED": 9, "SUPERSEDED": 1})
        self.assertEqual(result["unique_destinations"], 8)
        self.assertEqual(result["source_template_blob_reuse"], 0)
        self.assertEqual(result["candidate_scan_findings"], 0)
        manifest = json.loads((ROOT / VALIDATOR.MANIFEST_PATH).read_text(encoding="utf-8"))
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
            "unknown review state": gate({"independent_review": "APPROVED"}),
            "receipt digest removed": prov(lambda p: p.pop("private_source_history_receipt_sha256")),
            "receipt did not pass": prov(lambda p: p.update(private_source_history_result="FINDINGS")),
            "author is not a handle": prov(lambda p: p["entries"][0].update(author_github_handles=["Some Person <someone@example.com>"])),
            "source missing": prov(lambda p: p["entries"].pop()),
            "wrong rightsholder record": prov(lambda p: p.update(rightsholder_record="https://example.com/")),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                candidate = self._candidate_copy(Path(temporary))
                manifest_path = candidate / VALIDATOR.MANIFEST_PATH
                provenance_path = candidate / VALIDATOR.PROVENANCE_PATH
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
                mutate(manifest, provenance)
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                provenance_path.write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
                result = VALIDATOR.validate(candidate)
                self.assertEqual(result["status"], "FAIL", msg=label)
                self.assertEqual(result["admission_status"], "BLOCKED", msg=label)

    def test_manifest_binds_two_task_sources_and_supersedes_duplicate_requirement(self) -> None:
        manifest = json.loads((ROOT / VALIDATOR.MANIFEST_PATH).read_text(encoding="utf-8"))
        entries = {entry["source_path"]: entry for entry in manifest["entries"]}

        task_sources = (
            "forest/_templates/layers/L7_task_template.md",
            "forest/_templates/session/TASK.md",
        )
        self.assertEqual(
            {entries[path]["destination_path"] for path in task_sources},
            {"templates/hierarchy/task.md"},
        )
        self.assertEqual(
            entries["forest/_templates/session/REQUIREMENT.md"]["decision"],
            "SUPERSEDED",
        )
        self.assertEqual(
            entries["forest/_templates/session/REQUIREMENT.md"]["destination_path"],
            "templates/hierarchy/requirement.md",
        )

    def test_unallowlisted_or_missing_manifest_entry_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = self._candidate_copy(Path(temporary))
            manifest_path = candidate / VALIDATOR.MANIFEST_PATH
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["entries"].pop()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            result = VALIDATOR.validate(candidate)
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(
                any("exact sorted ten-path allowlist" in error for error in result["errors"]),
                msg=result["errors"],
            )

    def test_private_runtime_reference_and_blob_drift_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = self._candidate_copy(Path(temporary))
            task_path = candidate / "templates/hierarchy/task.md"
            task_path.write_text(
                task_path.read_text(encoding="utf-8") + "\nprivate bridge: runtime.app\n",
                encoding="utf-8",
            )

            result = VALIDATOR.validate(candidate)
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(
                any("destination blob mismatch" in error for error in result["errors"]),
                msg=result["errors"],
            )
            self.assertTrue(
                any("private_runtime_path" in error for error in result["errors"]),
                msg=result["errors"],
            )

    def test_catalog_and_guide_are_scanned_for_candidate_secrets_and_pii(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = self._candidate_copy(Path(temporary))
            mutations = {
                VALIDATOR.CATALOG_PATH: "contact@example.com",
                VALIDATOR.GUIDE_PATH: "ghp_aaaaaaaaaaaaaaaaaaaa",
            }
            for relative, marker in mutations.items():
                path = candidate / relative
                path.write_text(
                    path.read_text(encoding="utf-8") + f"\n{marker}\n",
                    encoding="utf-8",
                )

            result = VALIDATOR.validate(candidate)

            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(
                any("scan finding email" in error for error in result["errors"]),
                msg=result["errors"],
            )
            self.assertTrue(
                any("scan finding scm_access_token" in error for error in result["errors"]),
                msg=result["errors"],
            )
            self.assertTrue(
                any("templates/README.md" in error for error in result["errors"]),
                msg=result["errors"],
            )
            self.assertTrue(
                any("docs/TEMPLATE-GUIDE.md" in error for error in result["errors"]),
                msg=result["errors"],
            )

    def test_session_context_schema_enforces_iso8601_timestamp(self) -> None:
        schema = json.loads((ROOT / VALIDATOR.SCHEMA_PATH).read_text(encoding="utf-8"))
        context = json.loads((ROOT / VALIDATOR.CONTEXT_PATH).read_text(encoding="utf-8"))
        context["created_at"] = "yesterday"
        validator = Draft202012Validator(schema, format_checker=FormatChecker())

        with self.assertRaises(ValidationError):
            validator.validate(context)

    def test_schema_contract_is_bound_completely(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = self._candidate_copy(Path(temporary))
            schema_path = candidate / VALIDATOR.SCHEMA_PATH
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            schema["$id"] = "https://example.invalid/weakened-schema.json"
            schema["properties"]["session_id"] = {}
            schema_path.write_text(json.dumps(schema), encoding="utf-8")

            result = VALIDATOR.validate(candidate)

            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(
                any("schema" in error.lower() for error in result["errors"]),
                msg=result["errors"],
            )

    def test_manifest_rollback_contract_is_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = self._candidate_copy(Path(temporary))
            manifest_path = candidate / VALIDATOR.MANIFEST_PATH
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["rollback"]["strategy"] = "DELETE_SOURCE_HISTORY"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            result = VALIDATOR.validate(candidate)

            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(
                any("rollback contract" in error for error in result["errors"]),
                msg=result["errors"],
            )

    def test_session_context_uses_portable_absolute_schema_identifier(self) -> None:
        schema = json.loads((ROOT / VALIDATOR.SCHEMA_PATH).read_text(encoding="utf-8"))
        context = json.loads((ROOT / VALIDATOR.CONTEXT_PATH).read_text(encoding="utf-8"))

        self.assertTrue(context["$schema"].startswith("https://"))
        self.assertEqual(context["$schema"], schema["$id"])

    def test_non_string_manifest_source_path_returns_structured_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = self._candidate_copy(Path(temporary))
            manifest_path = candidate / VALIDATOR.MANIFEST_PATH
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["entries"][0]["source_path"] = ["forest/_templates/INDEX_TEMPLATE.md"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            result = VALIDATOR.validate(candidate)

            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(
                any("source_path must be a string" in error for error in result["errors"]),
                msg=result["errors"],
            )


if __name__ == "__main__":
    unittest.main()
