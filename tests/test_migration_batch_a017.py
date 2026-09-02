"""Regression tests for the clean-history A017 hierarchy candidate."""

from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
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

    def test_exact_candidate_passes_with_admission_still_blocked(self) -> None:
        result = VALIDATOR.validate(ROOT)
        self.assertEqual(result["status"], "PASS", msg=result["errors"])
        self.assertEqual(result["source_entries"], 10)
        self.assertEqual(result["decisions"], {"RE_AUTHORED": 9, "SUPERSEDED": 1})
        self.assertEqual(result["unique_destinations"], 8)
        self.assertEqual(result["source_template_blob_reuse"], 0)
        self.assertEqual(result["candidate_scan_findings"], 0)
        self.assertEqual(result["admission_status"], "BLOCKED")
        self.assertIn("ISSUE_25_LICENSE_PROVENANCE", result["no_go_reasons"])
        self.assertIn(
            "MISSING_PRIVATE_SOURCE_HISTORY_SECRET_PII_RECEIPT",
            result["no_go_reasons"],
        )

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
