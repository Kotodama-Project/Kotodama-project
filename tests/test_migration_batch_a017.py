"""Regression tests for the clean-history A017 hierarchy candidate."""

from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
