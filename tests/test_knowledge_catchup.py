"""Exercise catch-up failures through the existing knowledge API and CLI."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import test_knowledge_base as base

AS_OF, KB, ROOT = base.AS_OF, base.KB, base.ROOT


class KnowledgeCatchupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = base.KnowledgeBaseTests._minimal_copy(Path(self.temp.name))

    def context(self, bundle, **kwargs):
        options = dict(goals=["OUT-INTENT"], kgis=[], initiatives=[], tags=[], max_concepts=8)
        options.update(kwargs)
        return KB.select_context(bundle, **options)

    def replace(self, relative, before, after):
        path = self.root / relative
        text = path.read_text(encoding="utf-8")
        self.assertIn(before, text)
        path.write_text(text.replace(before, after, 1), encoding="utf-8")

    def test_no_lexical_match_does_not_return_priority_only_results(self):
        bundle = KB.load_bundle(self.root, as_of=AS_OF)
        self.assertEqual((), KB.query_bundle(bundle, "zznohit90127"))

    def test_stale_link_cannot_reenter_context(self):
        self.replace("knowledge/project/current-state.md",
                     "stale_after: 2026-10-07T00:00:00Z", "stale_after: 2026-01-01T00:00:00Z")
        bundle = KB.load_bundle(self.root, as_of=AS_OF)
        selection = self.context(bundle)
        self.assertIn("project/current-state", selection.unresolved_ids)
        self.assertNotIn("project/current-state", {c.concept_id for c in selection.selected})

    def test_invalid_public_bundle_cannot_be_queried_or_delivered(self):
        self.replace("knowledge/project/goal.md", "classification: public_candidate", "classification: internal")
        bundle = KB.load_bundle(self.root, as_of=AS_OF)
        for operation in (lambda: KB.query_bundle(bundle, "goal"), lambda: self.context(bundle)):
            with self.assertRaises(KB.KnowledgeBaseError):
                operation()
        for args in (["query", "goal", "--json"], ["context", "--goal", "OUT-INTENT", "--json"]):
            output = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                code = KB.main([*args, "--root", str(self.root)])
            self.assertNotEqual(0, code)
            self.assertNotIn('"concepts":', output.getvalue())
            self.assertNotIn('"results":', output.getvalue())

    def test_budget_cannot_silently_drop_required_context(self):
        bundle = KB.load_bundle(self.root, as_of=AS_OF)
        selection = self.context(bundle, max_concepts=1)
        self.assertEqual("needs_resolution", KB.context_as_dict(selection, bundle=bundle)["state"])
        self.assertTrue(selection.unresolved_ids)

    def test_zero_budget_is_rejected(self):
        with self.assertRaises(KB.KnowledgeBaseError):
            self.context(KB.load_bundle(self.root, as_of=AS_OF), max_concepts=0)

    def test_pinned_source_change_refuses_old_context(self):
        source = self.root / "STATUS.md"
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        self.replace("knowledge/project/current-state.md", "    resource: ../../STATUS.md",
                     f"    resource: ../../STATUS.md\n    sha256: {digest}")
        before = KB.load_bundle(self.root, as_of=AS_OF)
        self.assertFalse([i for i in before.issues if i.level == "error"])
        self.context(before)
        source.write_text("changed source revision\n", encoding="utf-8")
        after = KB.load_bundle(self.root, as_of=AS_OF)
        self.assertIn("SOURCE_DIGEST_MISMATCH", {i.code for i in after.issues})
        with self.assertRaises(KB.KnowledgeBaseError):
            self.context(after)

    def test_unknown_selector_cannot_look_ready_with_only_governance(self):
        selection = self.context(KB.load_bundle(self.root, as_of=AS_OF), goals=["OUT-NOT-FOUND"])
        self.assertEqual("needs_resolution", KB.context_as_dict(selection, bundle=KB.load_bundle(self.root, as_of=AS_OF))["state"])

    def test_missing_pinned_source_is_error_even_under_warning_profile(self):
        self.replace("knowledge/profile.yaml", "fail_on_missing_repository_sources: true",
                     "fail_on_missing_repository_sources: false")
        source = self.root / "docs/knowledge-observations/2026-09-09-catchup.json"
        source.unlink()  # Only the disposable fixture created by setUp.
        bundle = KB.load_bundle(self.root, as_of=AS_OF)
        self.assertTrue(any(i.level == "error" and i.code == "MISSING_SOURCE" for i in bundle.issues))
        with self.assertRaises(KB.KnowledgeBaseError):
            self.context(bundle)

    def test_japanese_catchup_runs_through_fresh_cli_processes(self):
        query = subprocess.run([sys.executable, "-B", str(ROOT / "tools/knowledge_base.py"),
                                "query", "現在の候補", "--root", str(ROOT), "--json",
                                "--as-of", "2026-09-09T02:00:00+09:00"],
                               capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(0, query.returncode, query.stderr)
        result = json.loads(query.stdout)["results"][0]
        self.assertEqual("project/catchup", result["id"])
        self.assertIn("未統合", result["description"])
        self.assertIn("未確認", result["description"])
        context = subprocess.run([sys.executable, "-B", str(ROOT / "tools/knowledge_base.py"),
                                  "context", "--root", str(ROOT), "--goal", "OUT-INTENT",
                                  "--max-concepts", "8", "--json",
                                  "--as-of", "2026-09-09T02:00:00+09:00"],
                                 capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(0, context.returncode, context.stderr)
        pack = json.loads(context.stdout)
        self.assertEqual("projection_only", pack["authority"])
        self.assertTrue({"project/goal", "project/catchup", "governance/authority-boundaries"}
                        <= {c["id"] for c in pack["concepts"]})

    def test_expired_observation_cannot_be_delivered(self):
        import datetime as dt
        bundle = KB.load_bundle(self.root, as_of=dt.datetime(2026, 9, 11, tzinfo=dt.timezone.utc))
        selection = self.context(bundle)
        self.assertNotIn("project/catchup", {c.concept_id for c in selection.selected})
        self.assertIn("project/catchup", selection.unresolved_ids)

    def test_default_cli_root_and_invalid_budget_have_structured_results(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(0, KB.main(["query", "KGI", "--as-of", "2026-09-09T02:00:00+09:00"]))
            self.assertEqual(2, KB.main(["context", "--goal", "OUT-INTENT", "--max-concepts", "0"]))


if __name__ == "__main__":
    unittest.main()
