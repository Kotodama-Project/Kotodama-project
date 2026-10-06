import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import knowledge_work_validator as validator
from create_knowledge_work_package import create_package
from compile_knowledge_context import compile_context
from knowledge_context import context_digest

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
        report, package = validator.validate_package(self.root, NOW)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(package, self.package)
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
        self.assertEqual(compile_context(self.root, now=NOW)["state"], "needs_resolution")
        source["expires_at"] = NOW.isoformat()
        self.save()
        at_expiry = validator.validate_package(self.root, NOW)[0]
        self.assertIn("SOURCE_EXPIRED", at_expiry["errors"])
        just_before = validator.validate_package(self.root, NOW - timedelta(microseconds=1))[0]
        self.assertEqual(just_before["status"], "PASS", just_before["errors"])
        self.assertNotIn("SOURCE_EXPIRED", just_before["errors"])

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
        report, package = validator.validate_package(self.root, NOW)
        self.assertEqual(report["errors"], ["SENSITIVITY_CEILING"])
        self.assertIsNone(package)
        self.assertIsNone(report["package_id"])
        self.assertIsNone(report["package_sha256"])
        self.assertEqual(report["bindings"], [])
        self.assertNotIn("PRIVATE_FIXTURE", json.dumps(report))

    def test_compiler_ceiling_refusal_erases_all_private_context(self):
        self.package["sensitivity"] = "restricted"
        self.package["objective"] = "PRIVATE_COMPILER_OBJECTIVE"
        self.package["criteria"][0]["description"] = "PRIVATE_CRITERION"
        self.save()
        result = compile_context(self.root, now=NOW)
        self.assertEqual(result["errors"], ["SENSITIVITY_CEILING"])
        self.assertIsNone(result["work"])
        self.assertIsNone(result["source_digest"])
        self.assertIsNone(result["context_sha256"])
        self.assertNotIn("PRIVATE_", json.dumps(result))

    def test_mandatory_and_byte_budgets_refuse_instead_of_truncating(self):
        for limits, reason in (({"max_claims":1}, "REQUIRED_CONTEXT_BUDGET"), ({"max_bytes":256}, "CONTEXT_BYTE_BUDGET")):
            with self.subTest(limits=limits):
                result = compile_context(self.root, now=NOW, **limits)
                self.assertEqual(result["state"], "needs_resolution")
                self.assertIn(reason, result["errors"])
                self.assertIsNone(result["work"])
                self.assertEqual(result["concepts"], [])
                self.assertEqual(result["omitted_ids"], [])

    def test_invalid_schema_cannot_return_an_unclassified_package(self):
        self.package["sensitivity"] = "unknown"
        self.package["objective"] = "UNCLASSIFIED_FIXTURE_NOT_FOR_API"
        self.save()
        report, package = validator.validate_package(self.root, NOW)
        self.assertEqual(report["errors"], ["SCHEMA_INVALID"])
        self.assertIsNone(package)
        self.assertNotIn("UNCLASSIFIED_FIXTURE", json.dumps(report))

    def test_compiler_cannot_bypass_the_executor_context_byte_ceiling(self):
        for number in range(2):
            claim=copy.deepcopy(self.package["claims"][0])
            claim["id"]=f"claim-overflow-{number}"
            self.package["claims"].append(claim)
        for claim in self.package["claims"]:
            claim["statement"]="x"*4000
        self.save()
        self.assertEqual(self.errors(),[])
        self.assertEqual(compile_context(self.root,now=NOW,max_bytes=16384)["errors"],["CONTEXT_BYTE_BUDGET"])
        with self.assertRaises(ValueError):
            compile_context(self.root,now=NOW,max_bytes=65536)

    def test_downgraded_classification_never_returns_package_even_at_restricted_ceiling(self):
        self.package["sources"][0]["sensitivity"] = "restricted"
        self.save()
        report, package = validator.validate_package(self.root, NOW, ceiling="restricted")
        self.assertIn("SENSITIVITY_DOWNGRADE", report["errors"])
        self.assertIsNone(package)

    def test_candidate_requires_source_backed_material_claim(self):
        for sources in [[], self.package["sources"]]:
            with self.subTest(has_sources=bool(sources)):
                self.package["sources"] = sources
                self.package["claims"] = [{"id": "claim-assumption", "kind": "assumption", "statement": "Unproven fixture hypothesis.", "source_refs": [], "material": False, "sensitivity": "public"}]
                self.package["assumptions"] = [{"id": "hypothesis", "statement": "Unproven fixture hypothesis.", "claim_refs": ["claim-assumption"]}]
                self.save()
                report, package = validator.validate_package(self.root, NOW)
                self.assertIn("CANDIDATE_INCOMPLETE", report["errors"])
                self.assertIsNone(package)

    def test_related_claims_cannot_be_dropped_under_assumptions_or_contradictions(self):
        optional = copy.deepcopy(self.package["claims"][0])
        optional.update(id="claim-optional", kind="assumption", material=False)
        self.package["claims"].append(optional)
        self.package["assumptions"].append({"id": "assumption-one", "statement": "A tracked assumption.", "claim_refs": ["claim-optional"]})
        self.package["contradictions"].append({"id": "conflict-one", "claim_refs": ["claim-optional", "claim-scope"], "severity": 2, "state": "open"})
        self.save()
        self.assertEqual(self.errors(), [])
        self.assertEqual(compile_context(self.root, now=NOW, max_claims=2)["state"], "needs_resolution")
        result = compile_context(self.root, now=NOW, max_claims=3)
        self.assertEqual(result["state"], "ready_candidate")
        selected = {claim["id"] for claim in result["work"]["selected_claims"]}
        self.assertTrue(all(set(item["claim_refs"]) <= selected for item in result["work"]["assumptions"] + result["work"]["contradictions"]))

    def test_compiler_uses_one_closed_envelope_without_source_body(self):
        result = compile_context(self.root, now=NOW)
        schema = json.loads((ROOT/"schemas/knowledge-context-bundle.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema,format_checker=FormatChecker()).validate(result)
        self.assertEqual(result["kind"], "kotodama.generated-knowledge-context")
        self.assertEqual(result["schema_revision"], "v2")
        self.assertFalse(any(result["claims"].values()))
        self.assertEqual(result["context_sha256"], context_digest(result))
        self.assertNotIn("Synthetic scenario, not a real conversation", json.dumps(result))
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_acceptance_change_changes_context_and_refusal_hides_deliverables(self):
        first = compile_context(self.root, now=NOW)
        self.package["criteria"][0]["description"] += " and revised acceptance"
        self.save()
        second = compile_context(self.root, now=NOW)
        self.assertNotEqual(first["context_sha256"], second["context_sha256"])
        self.assertNotEqual(first["source_digest"], second["source_digest"])
        self.assertIn("revised acceptance", second["work"]["acceptance_criteria"][0]["description"])
        refused = compile_context(self.root, now=NOW, max_bytes=256)
        self.assertIsNone(refused["work"])
        self.assertNotIn("revised acceptance", json.dumps(refused))

    def test_source_changed_during_context_assembly_cannot_be_returned(self):
        import compile_knowledge_context as compiler
        original = compiler.make_context
        def change(**kwargs):
            result = original(**kwargs)
            if result["state"] == "ready_candidate":
                path = self.root/"source.txt"
                path.write_bytes(path.read_bytes()+b" changed during compilation")
            return result
        with mock.patch.object(compiler,"make_context",side_effect=change):
            result = compiler.compile_context(self.root,now=NOW)
        self.assertEqual(result["errors"],["SOURCE_DRIFT"])
        self.assertIsNone(result["work"])

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
        schema = json.loads((ROOT / "schemas/knowledge-work-validation-report.schema.json").read_text(encoding="utf-8"))
        report_validator = Draft202012Validator(schema, format_checker=FormatChecker())
        report, _ = validator.validate_package(self.root, NOW)
        self.assertEqual(report["status"], "PASS")
        reports = [report]
        with mock.patch.object(validator, "MAX_TOTAL_BYTES", 1):
            reports.append(validator.validate_package(self.root, NOW)[0])
        (self.root / validator.MANIFEST).write_bytes(b'{"opaque-source-body":')
        reports.append(validator.validate_package(self.root, NOW)[0])
        self.assertEqual([r["status"] for r in reports], ["PASS", "FAIL", "FAIL"])
        for report in reports:
            report_validator.validate(report)
            encoded = json.dumps(report)
            self.assertNotIn("Synthetic scenario, not a real conversation", encoded)
            self.assertNotIn("opaque-source-body", encoded)
            self.assertNotIn(str(self.root), encoded)

    def test_initializer_preserves_existing_data_and_creates_unbound_draft(self):
        target = Path(self.temp.name) / "new"
        result = create_package(target, "new-package")
        self.assertFalse(result["work_bound"])
        before = (target / validator.MANIFEST).read_bytes()
        with self.assertRaises(FileExistsError):
            create_package(target, "replacement")
        self.assertEqual((target / validator.MANIFEST).read_bytes(), before)
        self.assertEqual(compile_context(target, ceiling="restricted", now=NOW)["errors"], ["CANDIDATE_REQUIRED"])

if __name__ == "__main__":
    unittest.main()
