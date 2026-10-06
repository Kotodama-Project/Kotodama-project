"""Contract tests for the public OKF knowledge bundle and deterministic projections."""

from __future__ import annotations

import datetime as dt
import importlib.util
import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "kotodama_knowledge_base", ROOT / "tools" / "knowledge_base.py"
)
assert SPEC and SPEC.loader
KB = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = KB
SPEC.loader.exec_module(KB)

AS_OF = dt.datetime(2026, 10, 4, 14, 0, tzinfo=dt.timezone.utc)


class KnowledgeBaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = KB.load_bundle(ROOT, as_of=AS_OF)

    def test_bundle_is_okf_and_profile_valid(self) -> None:
        errors = [issue for issue in self.bundle.issues if issue.level == "error"]
        self.assertEqual([], errors)
        self.assertEqual("0.2", self.bundle.profile["okf_version"])
        self.assertEqual(9, len(self.bundle.concepts))
        self.assertEqual(
            {"public_candidate"},
            {concept.extension["classification"] for concept in self.bundle.concepts},
        )
        self.assertTrue(
            all(concept.extension["authority"] == "projection_only" for concept in self.bundle.concepts)
        )
        self.assertTrue(
            all(
                concept.extension["owner_role"] != concept.extension["reviewer_role"]
                for concept in self.bundle.concepts
            )
        )

    def test_generated_catalog_and_graph_are_current(self) -> None:
        self.assertEqual([], KB.build(self.bundle, check=True))
        catalog_path = ROOT / self.bundle.profile["generated_outputs"]["catalog"]
        graph_path = ROOT / self.bundle.profile["generated_outputs"]["graph"]
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        self.assertEqual(self.bundle.source_digest, catalog["source_digest"])
        self.assertEqual(self.bundle.source_digest, graph["source_digest"])
        self.assertEqual(
            {concept.concept_id for concept in self.bundle.concepts},
            {row["id"] for row in catalog["concepts"]},
        )
        edge_keys = {
            (edge["from"], edge["relation"], edge["to"]) for edge in graph["edges"]
        }
        self.assertIn(("project/goal", "advances_goal", "OUT-INTENT"), edge_keys)
        self.assertIn(
            ("operations/refresh-loop", "implements_initiative", "INIT-KNOWLEDGE-REFRESH"),
            edge_keys,
        )

    def test_source_bindings_use_portable_case_sensitive_path_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            paths = [root / "a.md", root / "B.md"]
            for path in paths:
                path.write_text("synthetic bound input\n", encoding="utf-8")
            bindings = KB._capture_inputs(root, paths)
            self.assertEqual([name for name, _ in bindings], ["B.md", "a.md"])
            self.assertEqual(bindings, KB._capture_inputs(root, reversed(paths)))

    def test_query_is_transparent_and_source_backed(self) -> None:
        results = KB.query_bundle(self.bundle, "KGI", limit=3)
        self.assertTrue(results)
        self.assertEqual("project/success-model", results[0].concept.concept_id)
        self.assertGreater(results[0].score, 0)
        self.assertTrue(results[0].reasons)
        self.assertTrue(results[0].concept.source_resources)
        self.assertEqual((), KB.query_bundle(self.bundle, "zzzzuniqueno lexicalmatchzzzz"))

    def test_bounded_reader_compares_ctime_within_descriptor_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bounded.md"
            path.write_bytes(b"owned reader fixture\n")
            read_bytes = KB.load_bundle.__globals__["_read_bytes"]
            actual_fstat = KB.os.fstat
            calls = 0
            def alternate_ctime(descriptor):
                nonlocal calls
                calls += 1
                metadata = actual_fstat(descriptor)
                fields = {name: getattr(metadata, name) for name in dir(metadata) if name.startswith("st_")}
                fields["st_ctime_ns"] += 100
                return SimpleNamespace(**fields)
            with mock.patch.object(KB.os, "fstat", alternate_ctime):
                self.assertEqual(b"owned reader fixture\n", read_bytes(path))
            self.assertEqual(2, calls)
            calls = 0
            def changed_ctime(descriptor):
                metadata = alternate_ctime(descriptor)
                metadata.st_ctime_ns += calls
                return metadata
            with mock.patch.object(KB.os, "fstat", changed_ctime):
                with self.assertRaisesRegex(KB.KnowledgeBaseError, "INPUT_CHANGED_DURING_READ"):
                    read_bytes(path)
            KB.os.link(path, Path(temporary) / "shared.md")
            with self.assertRaisesRegex(KB.KnowledgeBaseError, "INPUT_NOT_BOUNDED_REGULAR_FILE"):
                read_bytes(path)

    def test_context_is_bounded_and_keeps_governance(self) -> None:
        selection = KB.select_context(
            self.bundle,
            goals=["OUT-INTENT"],
            kgis=[],
            initiatives=["INIT-KNOWLEDGE-REFRESH"],
            tags=[],
            max_concepts=9,
        )
        selected = {concept.concept_id for concept in selection.selected}
        self.assertLessEqual(len(selected), 9)
        self.assertIn("governance/authority-boundaries", selected)
        self.assertIn("project/goal", selected)
        self.assertIn("operations/refresh-loop", selected)
        context = KB.context_as_dict(selection, bundle=self.bundle)
        self.assertEqual("ready_candidate", context["state"])
        self.assertEqual("projection_only", context["authority"])
        self.assertIn("Open cited sources", context["consumer_rule"])

    def test_audit_exposes_unverified_state_without_claiming_failure(self) -> None:
        report = KB.audit_report(self.bundle, as_of=AS_OF)
        metrics = report["metrics"]
        self.assertEqual("v2", report["schema_revision"])
        self.assertEqual(0, metrics["error_count"])
        self.assertEqual(9, metrics["concept_count"])
        self.assertEqual(1.0, metrics["source_coverage_ratio"])
        self.assertEqual(0.0, metrics["independent_verification_ratio"])
        self.assertEqual(1.0, metrics["structural_retrieval_eligibility_ratio"])
        self.assertNotIn("retrieval_readiness_ratio", metrics)
        self.assertGreater(metrics["warning_count"], 0)

    def test_standard_profile_and_decision_verdicts_are_separate(self) -> None:
        verdicts = KB.validation_verdicts(self.bundle)
        self.assertEqual("PASS", verdicts["OKF_CONFORMANT"]["verdict"])
        self.assertEqual("PASS", verdicts["KOTODAMA_PROFILE_PASS"]["verdict"])
        self.assertEqual("NOT_EVALUATED", verdicts["DECISION_READY"]["verdict"])

        report = KB.decision_readiness_report(
            self.bundle, task="task:review-fixture", evaluated_at=AS_OF,
            actor="human:reviewer",
            purpose="review project direction",
            concept_ids=["project/goal"],
        )
        self.assertEqual("NEEDS_RESOLUTION", report["DECISION_READY"])
        self.assertEqual(0.0, report["content_ready_ratio"])
        self.assertIn("NO_INDEPENDENT_VERIFICATION", report["concepts"][0]["blockers"])
        self.assertIn("ACTOR_PURPOSE_ACCESS_NOT_RESOLVED", report["global_blockers"])

    def test_okf_conformance_does_not_inherit_strict_profile_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._minimal_copy(Path(temporary))
            goal = root / "knowledge" / "project" / "goal.md"
            goal.write_text("---\ntype: Unknown Producer Type\n---\n\nMinimal OKF concept.\n", encoding="utf-8")
            bundle = KB.load_bundle(root, as_of=AS_OF)
            verdicts = KB.validation_verdicts(bundle)
            self.assertEqual("PASS", verdicts["OKF_CONFORMANT"]["verdict"])
            self.assertEqual("FAIL", verdicts["KOTODAMA_PROFILE_PASS"]["verdict"])

            goal.write_text("---\ntype: ''\n---\n", encoding="utf-8")
            invalid_bundle = KB.load_bundle(root, as_of=AS_OF)
            invalid_verdicts = KB.validation_verdicts(invalid_bundle)
            self.assertEqual("FAIL", invalid_verdicts["OKF_CONFORMANT"]["verdict"])

    def test_public_profile_rejects_internal_concept(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._minimal_copy(Path(temporary))
            goal = root / "knowledge" / "project" / "goal.md"
            goal.write_text(
                goal.read_text(encoding="utf-8").replace(
                    "classification: public_candidate", "classification: internal", 1
                ),
                encoding="utf-8",
            )
            bundle = KB.load_bundle(root, as_of=AS_OF)
            codes = {issue.code for issue in bundle.issues if issue.level == "error"}
            self.assertIn("CLASSIFICATION", codes)

    def test_stale_critical_concept_becomes_unresolved_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._minimal_copy(Path(temporary))
            current = root / "knowledge" / "project" / "current-state.md"
            current.write_text(
                current.read_text(encoding="utf-8").replace(
                    "stale_after: 2026-10-07T00:00:00Z",
                    "stale_after: 2026-01-01T00:00:00Z",
                    1,
                ),
                encoding="utf-8",
            )
            bundle = KB.load_bundle(root, as_of=AS_OF)
            selection = KB.select_context(
                bundle,
                goals=["OUT-INTENT"],
                kgis=[],
                initiatives=[],
                tags=[],
                max_concepts=8,
            )
            self.assertIn("project/current-state", selection.unresolved_ids)
            context = KB.context_as_dict(selection, bundle=bundle)
            self.assertEqual("needs_resolution", context["state"])

    def test_cited_source_change_requires_reload_and_new_projections(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._minimal_copy(Path(temporary))
            before = KB.load_bundle(root, as_of=AS_OF)
            digest = before.source_digest
            source = root / "README.md"
            source.write_text(source.read_text() + "\nPublic source correction.\n")
            self.assertEqual(digest, before.source_digest)
            with self.assertRaisesRegex(KB.KnowledgeBaseError, "SOURCE_CHANGED"):
                KB.query_bundle(before, "KGI")
            with self.assertRaisesRegex(KB.KnowledgeBaseError, "SOURCE_CHANGED"):
                KB.build(before, check=True)
            after = KB.load_bundle(root, as_of=AS_OF)
            self.assertNotEqual(digest, after.source_digest)
            self.assertEqual(2, len(KB.build(after, check=True)))
            KB.build(after, check=False)
            self.assertEqual([], KB.build(after, check=True))

    def test_context_selection_cannot_relabel_an_earlier_source_snapshot(self):
        for change in ("concept", "source", "empty-selection"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                root = self._minimal_copy(Path(temporary))
                if change == "empty-selection":
                    for path in (root / "knowledge").rglob("*.md"):
                        text = path.read_text(encoding="utf-8")
                        path.write_text(text.replace("discoverable: true", "discoverable: false"), encoding="utf-8")
                before = KB.load_bundle(root, as_of=AS_OF)
                selection = self._context(before)
                original_ids = set(before.by_id)
                if change == "empty-selection":
                    self.assertEqual((), selection.selected)
                path = root / ("knowledge/project/goal.md" if change == "concept" else "README.md")
                text = path.read_text(encoding="utf-8")
                corrected = text.replace("description: Connect", "description: Corrected Connect", 1) if change == "concept" else text + "\nPublic source correction.\n"
                self.assertNotEqual(text, corrected)
                path.write_text(corrected, encoding="utf-8")
                after = KB.load_bundle(root, as_of=AS_OF)
                self.assertEqual(original_ids, set(after.by_id))
                self.assertNotEqual(before.source_digest, after.source_digest)
                current = KB.context_as_dict(self._context(after), bundle=after)
                self.assertEqual(after.source_digest, current["source_digest"])
                with self.assertRaisesRegex(KB.KnowledgeBaseError, "CONTEXT_SELECTION_BUNDLE_MISMATCH"):
                    KB.context_as_dict(selection, bundle=after)

    def test_context_selection_is_bound_to_its_root_and_freshness_instant(self):
        selection = self._context(self.bundle)
        reloaded = KB.load_bundle(ROOT, as_of=AS_OF)
        self.assertEqual(self.bundle.source_digest, KB.context_as_dict(selection, bundle=reloaded)["source_digest"])
        later = KB.load_bundle(ROOT, as_of=AS_OF + dt.timedelta(days=7))
        self.assertEqual(self.bundle.source_digest, later.source_digest)
        with self.assertRaisesRegex(KB.KnowledgeBaseError, "CONTEXT_SELECTION_BUNDLE_MISMATCH"):
            KB.context_as_dict(selection, bundle=later)
        with tempfile.TemporaryDirectory() as temporary:
            copied = KB.load_bundle(self._minimal_copy(Path(temporary)), as_of=AS_OF)
            self.assertEqual(self.bundle.source_digest, copied.source_digest)
            with self.assertRaisesRegex(KB.KnowledgeBaseError, "CONTEXT_SELECTION_BUNDLE_MISMATCH"):
                KB.context_as_dict(selection, bundle=copied)

    def test_deprecated_document_status_is_excluded_from_all_retrieval_routes(self):
        # With the intent tag these concepts enter directly, as mandatory
        # governance, and through a one-hop link from the goal, respectively.
        baseline = KB.select_context(self.bundle, goals=[], kgis=[], initiatives=[], tags=["intent"], max_concepts=12)
        baseline_ids = {concept.concept_id for concept in baseline.selected}
        for concept_id in ("project/goal", "governance/authority-boundaries", "project/current-state"):
            self.assertIn(concept_id, baseline_ids)
            with self.subTest(concept=concept_id), tempfile.TemporaryDirectory() as temporary:
                root = self._minimal_copy(Path(temporary))
                path = root / "knowledge" / (concept_id + ".md")
                path.write_text(path.read_text(encoding="utf-8").replace("status: draft", "status: deprecated", 1), encoding="utf-8")
                bundle = KB.load_bundle(root, as_of=AS_OF)
                self.assertFalse(any(issue.level == "error" for issue in bundle.issues))
                self.assertIn("LIFECYCLE_MISMATCH", {issue.code for issue in bundle.issues})
                for include_stale in (False, True):
                    matches = KB.query_bundle(bundle, str(bundle.by_id[concept_id].metadata["title"]), include_stale=include_stale)
                    self.assertNotIn(concept_id, {match.concept.concept_id for match in matches})
                selection = KB.select_context(bundle, goals=[], kgis=[], initiatives=[], tags=["intent"], max_concepts=12)
                self.assertNotIn(concept_id, {concept.concept_id for concept in selection.selected})
                self.assertIn(concept_id, selection.unresolved_ids)
                self.assertEqual("needs_resolution", KB.context_as_dict(selection, bundle=bundle)["state"])
                report = KB.audit_report(bundle, as_of=AS_OF)
                self.assertEqual(8, report["metrics"]["structurally_retrievable_count"])
                ready = KB.decision_readiness_report(bundle, actor="human:reviewer", purpose="review lifecycle", concept_ids=[concept_id])
                self.assertEqual("NOT_READY", ready["concepts"][0]["content_verdict"])
                self.assertIn("DOCUMENT_NOT_STABLE", ready["concepts"][0]["blockers"])

    def test_verified_replaced_knowledge_remains_auditable_without_readiness(self):
        for state in ("confirmed", "deprecated", "revoked"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as temporary:
                root = self._minimal_copy(Path(temporary))
                goal = root / "knowledge/project/goal.md"
                text = goal.read_text(encoding="utf-8").replace("status: draft", "status: stable", 1)
                text = text.replace("knowledge_state: candidate", "knowledge_state: confirmed", 1)
                text = text.replace("sources:\n", "verified: { by: human:independent-fixture, at: 2026-10-04T14:00:00Z }\nsources:\n", 1)
                goal.write_text(text, encoding="utf-8")
                active = KB.load_bundle(root, as_of=AS_OF)
                report = KB.decision_readiness_report(active, actor="human:reviewer", purpose="review lifecycle", concept_ids=["project/goal"])
                self.assertEqual("CONTENT_READY", report["concepts"][0]["content_verdict"])
                self.assertEqual(1, report["content_ready_count"])
                text = text.replace("status: stable", "status: deprecated", 1).replace("knowledge_state: confirmed", "knowledge_state: " + state, 1)
                goal.write_text(text, encoding="utf-8")
                deprecated = KB.load_bundle(root, as_of=AS_OF)
                self.assertFalse(any(issue.level == "error" for issue in deprecated.issues))
                self.assertNotIn("project/goal", {match.concept.concept_id for match in KB.query_bundle(deprecated, "Kotodama project goal", include_stale=True)})
                selection = self._context(deprecated)
                self.assertNotIn("project/goal", {concept.concept_id for concept in selection.selected})
                self.assertIn("project/goal", selection.unresolved_ids)
                report = KB.decision_readiness_report(deprecated, actor="human:reviewer", purpose="review lifecycle", concept_ids=["project/goal"])
                self.assertEqual(0, report["content_ready_count"])
                self.assertIn("DOCUMENT_NOT_STABLE", report["concepts"][0]["blockers"])
                self.assertEqual(8, KB.audit_report(deprecated, as_of=AS_OF)["metrics"]["structurally_retrievable_count"])

    def test_change_during_projection_generation_refuses_before_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._minimal_copy(Path(temporary))
            bundle = KB.load_bundle(root, as_of=AS_OF)
            old = (root / "knowledge/_generated/catalog.json").read_bytes()
            real_catalog = KB.generated_outputs.__globals__["_catalog"]
            def race(admitted):
                result = real_catalog(admitted)
                source = root / "README.md"
                source.write_text(source.read_text() + "\nChanged during build.\n")
                return result
            with mock.patch.dict(KB.generated_outputs.__globals__, {"_catalog": race}):
                with self.assertRaisesRegex(KB.KnowledgeBaseError, "SOURCE_CHANGED"):
                    KB.build(bundle, check=False)
            self.assertEqual(old, (root / "knowledge/_generated/catalog.json").read_bytes())

    def test_change_during_cli_serialization_emits_no_stale_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._minimal_copy(Path(temporary))
            real_dumps = json.dumps
            def correction(value, *args, **kwargs):
                rendered = real_dumps(value, *args, **kwargs)
                if isinstance(value, dict) and value.get("kind") == "kotodama.generated-knowledge-context":
                    source = root / "README.md"
                    source.write_text(source.read_text() + "\nCorrection during rendering.\n")
                return rendered
            stdout, stderr = io.StringIO(), io.StringIO()
            with mock.patch.object(json, "dumps", correction):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    result = KB.main(["context", "--root", str(root), "--goal", "OUT-INTENT", "--json", "--as-of", AS_OF.isoformat()])
            self.assertEqual(2, result)
            self.assertEqual("", stdout.getvalue())
            self.assertIn("SOURCE_CHANGED", stderr.getvalue())

    def test_invalid_nested_metadata_remains_auditable_without_traceback(self):
        for old, new in (("    discoverable: true", "    discoverable: []"),
                         ("  agent_use:\n", "  agent_use: []\n  unused:\n"),
                         ("tags: [goal, intent, company-os, local-first]", "tags: [{}]"),
                         ("  context_priority: 10", "  context_priority: []")):
            with self.subTest(shape=new):
                with tempfile.TemporaryDirectory() as temporary:
                    root = self._minimal_copy(Path(temporary))
                    concept = root / "knowledge/project/goal.md"
                    text = concept.read_text()
                    self.assertIn(old, text)
                    concept.write_text(text.replace(old, new, 1))
                    bundle = KB.load_bundle(root, as_of=AS_OF)
                    self.assertIn("CONCEPT_SCHEMA", {issue.code for issue in bundle.issues})
                    report = KB.audit_report(bundle, as_of=AS_OF)
                    self.assertEqual(0.0, report["metrics"]["structural_retrieval_eligibility_ratio"])
                    ready = KB.decision_readiness_report(bundle, actor="human:reviewer", purpose="review current sources")
                    self.assertEqual(0.0, ready["content_ready_ratio"])
                    self.assertTrue(all(row["blockers"] == ["INVALID_BUNDLE"] for row in ready["concepts"]))

    def test_schema_errors_do_not_reflect_rejected_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._minimal_copy(Path(temporary))
            concept = root / "knowledge/project/goal.md"
            marker = "REJECTED_VALUE_FIXTURE"
            concept.write_text(concept.read_text().replace("classification: public_candidate", "classification: " + marker, 1))
            bundle = KB.load_bundle(root, as_of=AS_OF)
            verdicts = KB.validation_verdicts(bundle)
            self.assertEqual("FAIL", verdicts["KOTODAMA_PROFILE_PASS"]["verdict"])
            self.assertNotIn(marker, json.dumps(verdicts))

    def test_freshness_audit_instant_is_bound_and_visible(self):
        context = KB.context_as_dict(self._context(self.bundle), bundle=self.bundle)
        self.assertEqual(AS_OF.isoformat().replace("+00:00", "Z"), context["as_of"])
        with self.assertRaisesRegex(KB.KnowledgeBaseError, "AUDIT_INSTANT_MISMATCH"):
            KB.audit_report(self.bundle, as_of=AS_OF + dt.timedelta(days=7))
        later = KB.load_bundle(ROOT, as_of=AS_OF + dt.timedelta(days=7))
        self.assertIn("project/current-state", self._context(later).unresolved_ids)

    def test_invalid_bundle_cannot_produce_context_query_or_content_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._minimal_copy(Path(temporary))
            goal = root / "knowledge/project/goal.md"
            text = goal.read_text().replace("status: draft", "status: stable", 1)
            text = text.replace("knowledge_state: candidate", "knowledge_state: confirmed", 1)
            text = text.replace("generated: { by: process:canonical-knowledge-port", "generated: { by: human:self-fixture", 1)
            text = text.replace("sources:\n", "verified: { by: human:self-fixture, at: 2026-10-04T14:00:00Z }\nsources:\n", 1)
            goal.write_text(text)
            bundle = KB.load_bundle(root, as_of=AS_OF)
            self.assertIn("SELF_VERIFICATION", {issue.code for issue in bundle.issues})
            audit = KB.audit_report(bundle, as_of=AS_OF)
            self.assertEqual(0, audit["metrics"]["independently_verified_count"])
            self.assertEqual(0, audit["metrics"]["human_reviewed_count"])
            for action in (lambda: KB.query_bundle(bundle, "goal"),
                           lambda: self._context(bundle),
                           lambda: KB.build(bundle, check=False)):
                with self.assertRaisesRegex(KB.KnowledgeBaseError, "INVALID_BUNDLE"):
                    action()
            report = KB.decision_readiness_report(bundle, actor="human:reviewer", purpose="review", concept_ids=["project/goal"], task="task:review-fixture", evaluated_at=AS_OF)
            self.assertEqual("NEEDS_RESOLUTION", report["DECISION_READY"])
            self.assertEqual(0, report["content_ready_count"])
            self.assertIn("INVALID_BUNDLE", report["global_blockers"])
            goal.write_text(goal.read_text().replace("verified: { by: human:self-fixture", "verified: { by: human:independent-fixture", 1))
            checked = KB.load_bundle(root, as_of=AS_OF)
            checked_audit = KB.audit_report(checked, as_of=AS_OF)
            self.assertEqual(1, checked_audit["metrics"]["independently_verified_count"])
            self.assertEqual(1, checked_audit["metrics"]["human_reviewed_count"])
            self.assertEqual("NEEDS_RESOLUTION", KB.decision_readiness_report(checked, actor="human:reviewer", purpose="review current sources", task="task:review-fixture", evaluated_at=AS_OF)["DECISION_READY"])

    def test_linked_stale_critical_concept_is_not_reintroduced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._minimal_copy(Path(temporary))
            current = root / "knowledge/project/current-state.md"
            current.write_text(current.read_text().replace("2026-10-07T00:00:00Z", "2026-01-01T00:00:00Z"))
            bundle = KB.load_bundle(root, as_of=AS_OF)
            # The goal links to current-state; it does not match the intent tag.
            selected = KB.select_context(bundle, goals=[], kgis=[], initiatives=[], tags=["intent"], max_concepts=12)
            self.assertNotIn("project/current-state", {concept.concept_id for concept in selected.selected})
            self.assertIn("project/current-state", selected.unresolved_ids)

    def test_non_discoverable_mandatory_governance_is_unresolved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._minimal_copy(Path(temporary))
            authority = root / "knowledge/governance/authority-boundaries.md"
            authority.write_text(authority.read_text().replace("discoverable: true", "discoverable: false"))
            selected = self._context(KB.load_bundle(root, as_of=AS_OF))
            self.assertNotIn("governance/authority-boundaries", {concept.concept_id for concept in selected.selected})
            self.assertIn("governance/authority-boundaries", selected.unresolved_ids)

    def test_context_budget_and_unknown_reference_do_not_imply_complete_context(self):
        selected = self._context(self.bundle, budget=1)
        self.assertEqual(1, len(selected.selected))
        self.assertEqual("needs_resolution", KB.context_as_dict(selected, bundle=self.bundle)["state"])
        with self.assertRaises(KB.KnowledgeBaseError):
            self._context(self.bundle, budget=0)
        with self.assertRaisesRegex(KB.KnowledgeBaseError, "CONTEXT_REFERENCE_UNKNOWN"):
            KB.select_context(self.bundle, goals=["OUT-UNKNOWN"], kgis=[], initiatives=[], tags=[], max_concepts=12)

    def test_profile_cannot_relax_public_or_missing_source_guards(self):
        for key, value in (("quality", None), ("allowed_classifications", ["public_candidate", "internal"]), ("generated_outputs", {"catalog": "knowledge/_generated/graph.json", "graph": "knowledge/_generated/graph.json"})):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temporary:
                root = self._minimal_copy(Path(temporary))
                profile_path = root / "knowledge/profile.yaml"
                profile = KB.yaml.safe_load(profile_path.read_text())
                profile[key] = value
                profile_path.write_text(KB.yaml.safe_dump(profile))
                with self.assertRaisesRegex(KB.KnowledgeBaseError, "PROFILE_INVALID"):
                    KB.load_bundle(root, as_of=AS_OF)
        for field, value in (("fail_on_missing_repository_sources", False), ("critical_tags", [])):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = self._minimal_copy(Path(temporary))
                path = root / "knowledge/profile.yaml"
                profile = KB.yaml.safe_load(path.read_text())
                profile["quality"][field] = value
                path.write_text(KB.yaml.safe_dump(profile))
                with self.assertRaisesRegex(KB.KnowledgeBaseError, "PROFILE_INVALID"):
                    KB.load_bundle(root, as_of=AS_OF)

    def test_schema_shape_failure_is_structured_and_not_content_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._minimal_copy(Path(temporary))
            goal = root / "knowledge/project/goal.md"
            raw = goal.read_text()
            head, body = raw.split("---", 2)[1:]
            value = KB.yaml.safe_load(head)
            value["kotodama"] = ["synthetic invalid shape"]
            goal.write_text("---\n" + KB.yaml.safe_dump(value) + "---" + body)
            bundle = KB.load_bundle(root, as_of=AS_OF)
            verdicts = KB.validation_verdicts(bundle)
            self.assertEqual("PASS", verdicts["OKF_CONFORMANT"]["verdict"])
            self.assertEqual("FAIL", verdicts["KOTODAMA_PROFILE_PASS"]["verdict"])
            with self.assertRaisesRegex(KB.KnowledgeBaseError, "INVALID_BUNDLE"):
                self._context(bundle)

    def test_bounded_duplicate_cycle_and_local_schema_inputs(self):
        variants = ("---\ntype: Test\ntype: Other\n---\n", "---\ntype: Test\nextra: &loop [*loop]\n---\n", "---\ntype: Test\nextra: " + "[" * 40 + "0" + "]" * 40 + "\n---\n")
        for text in variants:
            with self.subTest(text=text[:30]), tempfile.TemporaryDirectory() as temporary:
                root = self._minimal_copy(Path(temporary))
                (root / "knowledge/project/goal.md").write_text(text)
                bundle = KB.load_bundle(root, as_of=AS_OF)
                self.assertEqual("FAIL", KB.validation_verdicts(bundle)["OKF_CONFORMANT"]["verdict"])
                with self.assertRaisesRegex(KB.KnowledgeBaseError, "INVALID_BUNDLE"):
                    self._context(bundle)
        with tempfile.TemporaryDirectory() as temporary:
            root = self._minimal_copy(Path(temporary))
            schema = root / "schemas/kotodama-okf-concept.schema.json"
            schema.write_text(json.dumps({"$ref": "https://example.invalid/not-fetched"}))
            with self.assertRaisesRegex(KB.KnowledgeBaseError, "EXTERNAL_SCHEMA_REFERENCE"):
                KB.load_bundle(root, as_of=AS_OF)
        with tempfile.TemporaryDirectory() as temporary:
            root = self._minimal_copy(Path(temporary))
            (root / "knowledge/project/goal.md").write_bytes(b"x" * (KB.MAX_FILE_BYTES + 1))
            with self.assertRaisesRegex(KB.KnowledgeBaseError, "INPUT_NOT_BOUNDED"):
                KB.load_bundle(root, as_of=AS_OF)

    def test_invalid_schema_keywords_are_content_free_admission_refusals(self):
        marker = "synthetic-rejected-schema-value"
        variants = ({"type": 42}, {"properties": [marker]}, {"required": marker})
        for name in ("kotodama-okf-profile.schema.json", "kotodama-okf-concept.schema.json"):
            for schema in variants:
                with self.subTest(schema=name, keyword=next(iter(schema))), tempfile.TemporaryDirectory() as temporary:
                    root = self._minimal_copy(Path(temporary))
                    (root / "schemas" / name).write_text(json.dumps({"title": marker, **schema}), encoding="utf-8")
                    with self.assertRaisesRegex(KB.KnowledgeBaseError, "^INVALID_SCHEMA$"):
                        KB.load_bundle(root, as_of=AS_OF)
                    result = subprocess.run([sys.executable, "-B", str(ROOT / "tools/knowledge_base.py"), "validate", "--root", str(root), "--json"], text=True, capture_output=True, timeout=20)
                    self.assertEqual(2, result.returncode)
                    self.assertEqual("", result.stdout)
                    self.assertEqual("ERROR: INVALID_SCHEMA\n", result.stderr)

    def test_local_schema_resolution_failures_are_bounded_cli_refusals(self):
        for name in ("kotodama-okf-profile.schema.json", "kotodama-okf-concept.schema.json"):
            for schema, code in (({"$ref": "#"}, "SCHEMA_RECURSION_LIMIT"),
                                 ({"$ref": "#/$defs/missing"}, "SCHEMA_REFERENCE_UNRESOLVABLE")):
                with self.subTest(schema=name, code=code), tempfile.TemporaryDirectory() as temporary:
                    root = self._minimal_copy(Path(temporary))
                    (root / "schemas" / name).write_text(json.dumps(schema), encoding="utf-8")
                    with self.assertRaisesRegex(KB.KnowledgeBaseError, code):
                        KB.load_bundle(root, as_of=AS_OF)
                    result = subprocess.run([sys.executable, "-B", str(ROOT / "tools/knowledge_base.py"), "validate", "--root", str(root), "--json"], text=True, capture_output=True, timeout=20)
                    self.assertEqual(2, result.returncode)
                    self.assertEqual("", result.stdout)
                    self.assertEqual("ERROR: " + code + "\n", result.stderr)

    def test_finite_recursive_local_schema_remains_valid(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._minimal_copy(Path(temporary))
            path = root / "schemas/kotodama-okf-concept.schema.json"
            schema = json.loads(path.read_text(encoding="utf-8"))
            schema["$defs"]["owned_tree"] = {"type": "object", "properties": {"child": {"$ref": "#/$defs/owned_tree"}}}
            schema["properties"]["schema_recursion_fixture"] = {"$ref": "#/$defs/owned_tree"}
            path.write_text(json.dumps(schema), encoding="utf-8")
            goal = root / "knowledge/project/goal.md"
            goal.write_text(goal.read_text(encoding="utf-8").replace("sources:\n", "schema_recursion_fixture: { child: { child: {} } }\nsources:\n", 1), encoding="utf-8")
            bundle = KB.load_bundle(root, as_of=AS_OF)
            self.assertFalse(any(issue.level == "error" for issue in bundle.issues))
            result = subprocess.run([sys.executable, "-B", str(ROOT / "tools/knowledge_base.py"), "validate", "--root", str(root), "--json"], text=True, capture_output=True, timeout=20)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("PASS", json.loads(result.stdout)["KOTODAMA_PROFILE_PASS"]["verdict"])

    def test_oversized_numeric_tokens_are_structured_parse_refusals(self):
        digits = "7" * 5000
        variants = (("schemas/kotodama-okf-concept.schema.json", '{"owned_number_fixture":' + digits + '}', "INVALID_JSON"),
                    ("knowledge/profile.yaml", None, "INVALID_YAML"))
        for relative, text, code in variants:
            with self.subTest(path=relative), tempfile.TemporaryDirectory() as temporary:
                root = self._minimal_copy(Path(temporary))
                path = root / relative
                if text is None:
                    text = path.read_text(encoding="utf-8") + "\nowned_number_fixture: " + digits + "\n"
                path.write_text(text, encoding="utf-8")
                with self.assertRaisesRegex(KB.KnowledgeBaseError, code):
                    KB.load_bundle(root, as_of=AS_OF)
                result = subprocess.run([sys.executable, "-B", str(ROOT / "tools/knowledge_base.py"), "validate", "--root", str(root), "--json"], text=True, capture_output=True, timeout=20)
                self.assertEqual(2, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertEqual("ERROR: " + code + "\n", result.stderr)

    def test_cli_default_root_and_invalid_requests_have_no_traceback(self):
        positive = subprocess.run([sys.executable, "-B", str(ROOT / "tools/knowledge_base.py"), "validate", "--json"], cwd=ROOT.parent, text=True, capture_output=True, timeout=20)
        self.assertEqual(0, positive.returncode, positive.stderr)
        self.assertEqual("PASS", json.loads(positive.stdout)["KOTODAMA_PROFILE_PASS"]["verdict"])
        for args in (("context", "--goal", "OUT-INTENT", "--max-concepts", "0", "--json"), ("readiness", "--actor", "", "--purpose", "review")):
            result = subprocess.run([sys.executable, "-B", str(ROOT / "tools/knowledge_base.py"), *args], cwd=ROOT.parent, text=True, capture_output=True, timeout=20)
            self.assertEqual(2, result.returncode)
            self.assertNotIn("Traceback", result.stderr)

    @staticmethod
    def _context(bundle, budget=12):
        return KB.select_context(bundle, goals=["OUT-INTENT"], kgis=[], initiatives=[], tags=[], max_concepts=budget)

    @staticmethod
    def _minimal_copy(temporary: Path) -> Path:
        root = temporary / "repo"
        shutil.copytree(ROOT / "knowledge", root / "knowledge")
        (root / "schemas").mkdir(parents=True)
        for name in (
            "kotodama-okf-profile.schema.json",
            "kotodama-okf-concept.schema.json",
            "session-knowledge-projection.schema.json",
        ):
            shutil.copy2(ROOT / "schemas" / name, root / "schemas" / name)

        # Use the actual admitted public source bytes, not fabricated stand-ins
        # for old excluded policy documents which mask missing-source failures.
        for relative, _ in KB.load_bundle(ROOT, as_of=AS_OF).input_bindings:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                shutil.copy2(ROOT / relative, path)
        return root


if __name__ == "__main__":
    unittest.main()
