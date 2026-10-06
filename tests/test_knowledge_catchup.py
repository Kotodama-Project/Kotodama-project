"""Source-bound catch-up rejects drift without inventing delivery or authority."""
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import test_knowledge_base as base

KB, AS_OF, ROOT = base.KB, base.AS_OF, base.ROOT


class KnowledgeCatchupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="knowledge-catchup-")
        self.addCleanup(temporary.cleanup)
        self.root = base.KnowledgeBaseTests._minimal_copy(Path(temporary.name).resolve())

    def context(self, bundle, **kwargs):
        options = dict(goals=["OUT-INTENT"], kgis=[], initiatives=[], tags=[], max_concepts=8)
        options.update(kwargs)
        return KB.select_context(bundle, **options)

    def change(self, relative, before, after):
        path = self.root / relative
        text = path.read_text(encoding="utf-8")
        self.assertIn(before, text)
        path.write_text(text.replace(before, after, 1), encoding="utf-8")

    def pin(self, digest=None):
        source = self.root / "STATUS.md"
        digest = digest or hashlib.sha256(source.read_bytes()).hexdigest()
        self.change("knowledge/project/current-state.md", "    resource: ../../STATUS.md",
                    f"    resource: ../../STATUS.md\n    sha256: {digest}")
        return source

    def test_changed_pin_preserves_standard_conformance_but_refuses_profile_and_context(self):
        source = self.pin()
        before = KB.load_bundle(self.root, as_of=AS_OF)
        self.context(before)
        source.write_text("changed source revision\n", encoding="utf-8")
        after = KB.load_bundle(self.root, as_of=AS_OF)
        self.assertIn("SOURCE_DIGEST_MISMATCH", {issue.code for issue in after.issues})
        verdicts = KB.validation_verdicts(after)
        self.assertEqual(verdicts["OKF_CONFORMANT"]["verdict"], "PASS")
        self.assertEqual(verdicts["KOTODAMA_PROFILE_PASS"]["verdict"], "FAIL")
        with self.assertRaises(KB.KnowledgeBaseError):
            self.context(after)
        with self.assertRaises(KB.KnowledgeBaseError):
            self.context(before)

    def test_pin_is_checked_against_final_snapshot_not_an_earlier_read(self):
        source = self.pin()
        globals_ = KB.load_bundle.__globals__
        capture = globals_["_capture_inputs"]
        changed = False
        def replace_before_snapshot(root, paths):
            nonlocal changed
            paths = tuple(paths)
            if source in paths and not changed:
                source.write_text("new bytes at snapshot capture\n", encoding="utf-8")
                changed = True
            return capture(root, paths)
        with mock.patch.dict(globals_, {"_capture_inputs": replace_before_snapshot}):
            bundle = KB.load_bundle(self.root, as_of=AS_OF)
        self.assertTrue(changed)
        self.assertIn("SOURCE_DIGEST_MISMATCH", {issue.code for issue in bundle.issues})
        with self.assertRaises(KB.KnowledgeBaseError):
            self.context(bundle)

    def test_missing_source_and_unresolved_remote_pin_refuse(self):
        source = self.pin()
        source.unlink()
        missing = KB.load_bundle(self.root, as_of=AS_OF)
        self.assertIn("MISSING_SOURCE", {issue.code for issue in missing.issues})
        self.change("knowledge/project/current-state.md", "resource: ../../STATUS.md", "resource: https://example.invalid/source")
        remote = KB.load_bundle(self.root, as_of=AS_OF)
        self.assertIn("SOURCE_DIGEST_UNAVAILABLE", {issue.code for issue in remote.issues})
        with self.assertRaises(KB.KnowledgeBaseError):
            self.context(remote)

    def test_invalid_pin_is_not_a_normative_okf_failure(self):
        self.pin("invalid-pin")
        bundle = KB.load_bundle(self.root, as_of=AS_OF)
        # The closed producer schema rejects the malformed value before semantic
        # source processing; retain that stronger boundary.
        self.assertIn("CONCEPT_SCHEMA", {issue.code for issue in bundle.issues})
        self.assertEqual(KB.validation_verdicts(bundle)["KOTODAMA_PROFILE_PASS"]["verdict"], "FAIL")
        self.assertEqual(KB.validation_verdicts(bundle)["OKF_CONFORMANT"]["verdict"], "PASS")

    def test_noncritical_stale_concept_cannot_reenter_through_context_links(self):
        self.change("knowledge/operations/agent-context.md", "stale_after: 2026-12-07T00:00:00Z", "stale_after: 2020-01-01T00:00:00Z")
        bundle = KB.load_bundle(self.root, as_of=AS_OF)
        context = self.context(bundle)
        self.assertNotIn("operations/agent-context", {item.concept_id for item in context.selected})
        self.assertIn("operations/agent-context", context.unresolved_ids)

    def test_critical_context_precedes_high_priority_optional_content(self):
        for relative, priority in (("project/current-state.md", 900), ("operations/agent-context.md", 0)):
            path = self.root / "knowledge" / relative
            path.write_text(re.sub(r"(?m)^  context_priority: \d+$", f"  context_priority: {priority}", path.read_text(encoding="utf-8")), encoding="utf-8")
        bundle = KB.load_bundle(self.root, as_of=AS_OF)
        # OUT-LOCAL now has its own critical definition: seven mandatory
        # Concepts must fit before any optional content can use the budget.
        too_small = self.context(bundle, max_concepts=6)
        self.assertEqual(KB.context_as_dict(too_small, bundle=bundle)["state"], "needs_resolution")
        context = self.context(bundle, max_concepts=7)
        self.assertIn("project/current-state", {item.concept_id for item in context.selected})
        self.assertNotIn("operations/agent-context", {item.concept_id for item in context.selected})
        limited = self.context(bundle, max_concepts=1)
        self.assertEqual(KB.context_as_dict(limited, bundle=bundle)["state"], "needs_resolution")

    def test_existing_no_match_unknown_selector_and_budget_refusals_remain(self):
        bundle = KB.load_bundle(self.root, as_of=AS_OF)
        self.assertEqual(KB.query_bundle(bundle, "zznohit90127"), ())
        with self.assertRaisesRegex(KB.KnowledgeBaseError, "CONTEXT_REFERENCE_UNKNOWN"):
            self.context(bundle, goals=["OUT-NOT-FOUND"])
        with self.assertRaises(KB.KnowledgeBaseError):
            self.context(bundle, max_concepts=0)

    def test_fresh_cli_returns_current_source_procedure_without_historical_snapshot(self):
        result = subprocess.run([sys.executable, "-B", str(ROOT / "tools/knowledge_base.py"),
            "query", "現在の候補", "--root", str(ROOT), "--json", "--as-of", AS_OF.isoformat()],
            capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        first = json.loads(result.stdout)["results"][0]
        self.assertEqual(first["id"], "project/catchup")
        self.assertIn("未統合", first["description"])
        self.assertIn("未確認", first["description"])
        self.assertFalse((ROOT / "docs/knowledge-observations/2026-09-09-catchup.json").exists())


if __name__ == "__main__":
    unittest.main()
