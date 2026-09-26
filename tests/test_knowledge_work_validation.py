import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import knowledge_work_validator as validator
from create_knowledge_work_package import create_package

NOW = datetime(2026, 9, 9, tzinfo=timezone.utc)


class KnowledgeWorkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="knowledge-work-")
        self.addCleanup(self.temp.cleanup)
        # Resolve the fixture location: the validator refuses linked ancestors,
        # and some platforms place the temporary directory under one.
        self.root = Path(self.temp.name).resolve() / "package"
        shutil.copytree(ROOT / "examples/knowledge-work/business-rehearsal", self.root)
        self.package = json.loads((self.root / validator.MANIFEST).read_text(encoding="utf-8"))

    def save(self):
        (self.root / validator.MANIFEST).write_text(json.dumps(self.package, ensure_ascii=False) + "\n", encoding="utf-8")

    def errors(self):
        return validator.validate_package(self.root, NOW)[0]["errors"]

    def test_valid_candidate_binds_bytes_but_does_not_grant_authority(self):
        report, _ = validator.validate_package(self.root, NOW)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(len(report["bindings"]), 2)
        self.assertFalse(any(report["claims"].values()))
        self.assertIn("SEMANTIC_REVIEW_NOT_RUN", report["warnings"])

    def test_source_and_deliverable_mutations_are_refused(self):
        for name, code in [("source.txt", "SOURCE_DIGEST_MISMATCH"), ("deliverable.md", "DELIVERABLE_DIGEST_MISMATCH")]:
            with self.subTest(name=name):
                path = self.root / name
                before = path.read_bytes()
                path.write_bytes(before + b"changed")
                self.assertIn(code, self.errors())
                path.write_bytes(before)

    def test_traversal_absolute_backslash_and_git_paths_are_refused(self):
        for path in ["../outside", "/outside", "C:/outside", "a\\b", ".git/config", "a//b"]:
            with self.subTest(path=path):
                self.package["sources"][0]["path"] = path
                self.save()
                self.assertIn("PATH_REFUSED", self.errors())

    def test_symlink_source_is_refused(self):
        source = self.root / "source.txt"
        outside = Path(self.temp.name) / "outside.txt"
        outside.write_bytes(source.read_bytes())
        source.unlink()
        try:
            source.symlink_to(outside)
        except OSError as error:
            if os.name == "nt" and getattr(error, "winerror", None) == 1314:
                self.skipTest("symlink privilege unavailable")
            raise
        self.assertIn("PATH_REFUSED", self.errors())

    def test_hardlinked_source_is_refused(self):
        source = self.root / "source.txt"
        outside = Path(self.temp.name) / "outside.txt"
        os.link(source, outside)
        self.assertIn("FILE_REFUSED", self.errors())

    def test_material_evidence_and_unknown_references_are_refused(self):
        self.package["claims"][0]["source_refs"] = []
        self.save()
        self.assertIn("MATERIAL_CLAIM_UNSUPPORTED", self.errors())
        self.package["claims"][0]["source_refs"] = ["missing"]
        self.save()
        self.assertIn("SOURCE_REF_UNKNOWN", self.errors())

    def test_duplicate_cross_type_ids_are_refused(self):
        self.package["claims"][0]["id"] = self.package["sources"][0]["id"]
        self.save()
        self.assertIn("DUPLICATE_ID", self.errors())

    def test_snapshot_expiry_and_missing_freshness_are_refused(self):
        source = self.package["sources"][0]
        source["kind"] = "local_snapshot"
        self.save()
        self.assertIn("FRESHNESS_REQUIRED", self.errors())
        source["expires_at"] = "2026-09-08T00:00:00Z"
        self.save()
        self.assertIn("SOURCE_EXPIRED", self.errors())

    def test_blocking_question_and_critical_contradiction_prevent_candidate(self):
        self.package["questions"][0]["blocking"] = True
        self.package["contradictions"] = [{"id": "conflict", "claim_refs": ["claim-scope", "claim-acceptance"], "severity": 1, "state": "open"}]
        self.save()
        self.assertIn("BLOCKING_QUESTION_OPEN", self.errors())
        self.assertIn("CONTRADICTION_OPEN", self.errors())

    def test_acceptance_requires_a_current_bidirectional_deliverable_mapping(self):
        self.package["criteria"][0]["deliverable_refs"] = []
        self.save()
        self.assertIn("ACCEPTANCE_PENDING", self.errors())
        self.assertIn("CRITERION_MAPPING_MISMATCH", self.errors())

    def test_self_review_and_changed_subject_are_refused(self):
        self.package["review"] = {"state": "performed", "reviewer_ref": self.package["producer_ref"], "subject_sha256": validator.subject_digest(self.package)}
        self.save()
        self.assertIn("REVIEWER_NOT_INDEPENDENT", self.errors())
        self.package["review"]["reviewer_ref"] = "ref/reviewer/other"
        self.package["objective"] += " changed"
        self.save()
        self.assertIn("REVIEW_BINDING_MISMATCH", self.errors())

    def test_approved_or_verified_states_cannot_be_self_declared(self):
        for state in ["approved", "verified_candidate"]:
            self.package["state"] = state
            self.save()
            self.assertIn("SCHEMA_INVALID", self.errors())

    def test_source_classification_cannot_be_downgraded(self):
        self.package["sources"][0]["sensitivity"] = "restricted"
        self.save()
        self.assertIn("SENSITIVITY_DOWNGRADE", self.errors())

    def test_validator_ceiling_refusal_does_not_return_private_metadata(self):
        self.package["sensitivity"] = "restricted"
        self.package["objective"] = "PRIVATE_FIXTURE_NOT_FOR_PUBLIC_REPORT"
        self.save()
        report, _ = validator.validate_package(self.root, NOW)
        self.assertEqual(report["errors"], ["SENSITIVITY_CEILING"])
        self.assertIsNone(report["package_id"])
        self.assertIsNone(report["package_sha256"])
        self.assertEqual(report["bindings"], [])
        self.assertNotIn("PRIVATE_FIXTURE", json.dumps(report))

    def test_related_claims_cannot_be_dropped_under_assumptions_or_contradictions(self):
        optional = copy.deepcopy(self.package["claims"][0])
        optional.update(id="claim-optional", kind="assumption", material=False)
        self.package["claims"].append(optional)
        self.package["assumptions"].append({"id": "assumption-one", "statement": "A tracked assumption.", "claim_refs": ["claim-optional"]})
        self.package["contradictions"].append({"id": "conflict-one", "claim_refs": ["claim-optional", "claim-scope"], "severity": 2, "state": "open"})
        self.save()
        self.assertEqual(self.errors(), [])

    def test_final_reread_detects_a_source_changed_after_its_initial_read(self):
        original = validator.read_bound
        changed = False
        def read(root, relative, limit):
            nonlocal changed
            content = original(root, relative, limit)
            if relative == "source.txt" and not changed:
                changed = True
                (root / relative).write_bytes(content + b" changed during audit")
            return content
        with mock.patch.object(validator, "read_bound", side_effect=read):
            self.assertIn("SOURCE_DRIFT", self.errors())

    def test_validation_report_schema_and_no_source_body(self):
        report, _ = validator.validate_package(self.root, NOW)
        schema = json.loads((ROOT / "schemas" / "knowledge-work-validation-report.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(report)
        self.assertNotIn("Synthetic scenario, not a real conversation", json.dumps(report))

    def test_initializer_preserves_existing_data_and_creates_unbound_draft(self):
        target = Path(self.temp.name) / "new"
        result = create_package(target, "new-package")
        self.assertFalse(result["work_bound"])
        before = (target / validator.MANIFEST).read_bytes()
        with self.assertRaises(FileExistsError):
            create_package(target, "replacement")
        self.assertEqual((target / validator.MANIFEST).read_bytes(), before)

if __name__ == "__main__":
    unittest.main()
