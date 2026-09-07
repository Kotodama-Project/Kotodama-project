"""Contract tests for the public OKF knowledge bundle and deterministic projections."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "kotodama_knowledge_base", ROOT / "tools" / "knowledge_base.py"
)
assert SPEC and SPEC.loader
KB = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = KB
SPEC.loader.exec_module(KB)

AS_OF = dt.datetime(2026, 9, 7, 4, 0, tzinfo=dt.timezone.utc)


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

    def test_query_is_transparent_and_source_backed(self) -> None:
        results = KB.query_bundle(self.bundle, "KGI", limit=3)
        self.assertTrue(results)
        self.assertEqual("project/success-model", results[0].concept.concept_id)
        self.assertGreater(results[0].score, 0)
        self.assertTrue(results[0].reasons)
        self.assertTrue(results[0].concept.source_resources)

    def test_context_is_bounded_and_keeps_governance(self) -> None:
        selection = KB.select_context(
            self.bundle,
            goals=["OUT-INTENT"],
            kgis=[],
            initiatives=["INIT-KNOWLEDGE-REFRESH"],
            tags=[],
            max_concepts=8,
        )
        selected = {concept.concept_id for concept in selection.selected}
        self.assertLessEqual(len(selected), 8)
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
        self.assertEqual(0, metrics["error_count"])
        self.assertEqual(9, metrics["concept_count"])
        self.assertEqual(1.0, metrics["source_coverage_ratio"])
        self.assertEqual(0.0, metrics["independent_verification_ratio"])
        self.assertEqual(1.0, metrics["retrieval_readiness_ratio"])
        self.assertGreater(metrics["warning_count"], 0)

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

        for relative in (
            "README.md",
            "STATUS.md",
            "ROADMAP.md",
            "AGENTS.md",
            "docs/OWNER-INTENT-COMPANY-AGI.md",
            "docs/PROJECT-MAP.md",
            "docs/CONTEXT-AND-AGENT-RESPONSIBILITY.md",
            "docs/operating-policy.json",
            "docs/INFORMATION-ACCESS.md",
            "docs/SESSION-CONVERSATION-LEDGER.md",
        ):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("test fixture\n", encoding="utf-8")
        return root


if __name__ == "__main__":
    unittest.main()
