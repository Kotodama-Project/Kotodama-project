"""Purpose filters and bounded, revision-bound source reads through the real CLI."""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import knowledge_base as kb
from kotodama_kb import cli

AS_OF = dt.datetime(2026, 10, 10, tzinfo=dt.timezone.utc)


class KnowledgeCliUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = kb.load_bundle(ROOT, as_of=AS_OF)

    def fixture(self, directory, body_suffix=""):
        root = Path(directory)
        shutil.copytree(ROOT / "knowledge", root / "knowledge")
        for relative, _ in self.bundle.input_bindings:
            destination = root / relative
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, destination)
        path = root / "knowledge/project/goal.md"
        path.write_text(path.read_text(encoding="utf-8") + body_suffix, encoding="utf-8")
        return root, kb.load_bundle(root, as_of=AS_OF)

    def run_cli(self, args):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            code = cli.main(args)
        return code, output.getvalue(), error.getvalue()

    def test_filters_apply_before_limit_and_intersect_categories(self):
        rows = kb.query_bundle(self.bundle, "KGI", limit=1,
                               goals=["OUT-INTENT"], kgis=["KGI-INTENT"],
                               initiatives=["INIT-METHOD-RENEWAL"])
        self.assertEqual(1, len(rows))
        self.assertIn("INIT-METHOD-RENEWAL", rows[0].concept.extension["initiative_refs"])
        both = kb.query_bundle(self.bundle, "KGI", goals=["OUT-LOCAL"],
                               initiatives=["INIT-CONTEXT-HANDOFF"])
        self.assertTrue(both)
        for row in both:
            self.assertIn("OUT-LOCAL", row.concept.extension["goal_refs"])
            self.assertIn("INIT-CONTEXT-HANDOFF", row.concept.extension["initiative_refs"])
        self.assertEqual((), kb.query_bundle(self.bundle, "KGI", type_filter="Goal",
                                            goals=["OUT-LOCAL"],
                                            initiatives=["INIT-CONTEXT-HANDOFF"]))
        one = kb.query_bundle(self.bundle, "KGI", limit=100, goals=["OUT-INTENT"])
        two = kb.query_bundle(self.bundle, "KGI", limit=100, goals=["OUT-INTENT", "OUT-LOCAL"])
        self.assertTrue({r.concept.concept_id for r in one} <= {r.concept.concept_id for r in two})

    def test_unknown_references_are_not_empty_success(self):
        for key in ("goals", "kgis", "initiatives"):
            with self.subTest(key=key), self.assertRaisesRegex(kb.KnowledgeBaseError, "QUERY_REFERENCE_UNKNOWN"):
                kb.query_bundle(self.bundle, "KGI", **{key: ["UNDEFINED"]})
        code, output, error = self.run_cli(["query", "KGI", "--goal", "UNDEFINED", "--json"])
        self.assertEqual(2, code)
        self.assertEqual("", output)
        self.assertIn("QUERY_REFERENCE_UNKNOWN", error)

    def test_query_cli_records_effective_variables(self):
        code, output, _ = self.run_cli(["query", "KGI", "--goal", "OUT-INTENT",
                                       "--kgi", "KGI-INTENT", "--json"])
        self.assertEqual(0, code)
        report = json.loads(output)
        self.assertEqual(["OUT-INTENT"], report["filters"]["goals"])
        self.assertTrue(report["results"])

    def test_real_source_lines_and_digest_match_selected_section(self):
        report = kb.inspect_concept(self.bundle, "project/goal", section="Required properties")
        raw = (ROOT / report["path"]).read_text(encoding="utf-8")
        selected = "".join(raw.splitlines(keepends=True)[report["line_start"] - 1:report["line_end"]])
        self.assertEqual(selected, report["content"])
        self.assertEqual(kb.hashlib.sha256(raw.encode("utf-8")).hexdigest(), report["content_sha256"])
        self.assertEqual(self.bundle.source_digest, report["source_digest"])
        self.assertEqual("projection_only", report["authority"])

    def test_japanese_section_nested_headings_and_fences(self):
        suffix = "\n# 日本語の意図\n目的🙂を保持。\n## 子見出し\n条件も保持。\n````text\n# 偽見出し\n```\n# まだcode\n````\n~~~\n# もう一つの偽見出し\n~~~\n# 次の意図 ###\n次は含めない。\n"
        with tempfile.TemporaryDirectory() as directory:
            root, bundle = self.fixture(directory, suffix)
            report = kb.inspect_concept(bundle, "project/goal", section="日本語の意図")
            self.assertIn("条件も保持", report["content"])
            self.assertIn("# 偽見出し", report["content"])
            self.assertNotIn("次は含めない", report["content"])
            self.assertNotIn("偽見出し", [h["title"] for h in report["sections"]])
            code, output, _ = self.run_cli(["show", "project/goal", "--root", str(root),
                                          "--section", "日本語の意図", "--json"])
            self.assertEqual(0, code)
            self.assertEqual(report["content"], json.loads(output)["content"])

    def test_missing_ambiguous_sections_and_outside_ids_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            _, bundle = self.fixture(directory, "\n# Same\nOne.\n# Same\nTwo.\n")
            for section, error in (("Same", "AMBIGUOUS"), ("absent", "UNAVAILABLE")):
                with self.subTest(section=section), self.assertRaisesRegex(kb.KnowledgeBaseError, error):
                    kb.inspect_concept(bundle, "project/goal", section=section)
        with self.assertRaisesRegex(kb.KnowledgeBaseError, "UNAVAILABLE"):
            kb.inspect_concept(self.bundle, "../../README.md")

    def test_container_fences_do_not_expose_fake_sections(self):
        for marker in ("- ```", "1. ~~~", "> ```"):
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as directory:
                fence = marker.split()[-1]
                _, bundle = self.fixture(directory, f"\n{marker}\n  # literal code\n  {fence}\n# Real heading\ntext\n")
                report = kb.inspect_concept(bundle, "project/goal", max_chars=65536)
                self.assertFalse(report["sections_supported"])
                self.assertEqual([], report["sections"])
                self.assertIn("# Real heading", report["content"])
                for section in ("literal code", "Real heading"):
                    with self.assertRaisesRegex(kb.KnowledgeBaseError, "SECTION_STRUCTURE_UNSUPPORTED"):
                        kb.inspect_concept(bundle, "project/goal", section=section)

    def test_resume_arguments_preserve_custom_checkout_and_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.fixture(directory, "\n# Continuation\n" + "独自🙂" * 20)
            code, output, _ = self.run_cli(["show", "project/goal", "--root", str(root),
                                          "--section", "Continuation", "--max-chars", "7", "--json"])
            self.assertEqual(0, code)
            first = json.loads(output)
            code, output, error = self.run_cli(first["resume_args"])
            self.assertEqual(0, code, error)
            second = json.loads(output)
            self.assertEqual(first["source_digest"], second["source_digest"])
            self.assertEqual(first["next_offset"], second["offset"])
            expected = "# Continuation\n" + "独自🙂" * 20
            self.assertEqual(expected[7:14], second["content"])

    def test_padded_list_lines_preserve_section_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            _, bundle = self.fixture(directory, "\n- " + " " * 50000 + "plain text\n# Real heading\ntext\n")
            report = kb.inspect_concept(bundle, "project/goal", section="Real heading")
            self.assertEqual("# Real heading\ntext\n", report["content"])
            self.assertTrue(report["sections_supported"])

    def test_heading_suffix_cleanup_preserves_internal_padding(self):
        title = "start" + " " * 50000 + "ordinary text"
        with tempfile.TemporaryDirectory() as directory:
            _, bundle = self.fixture(directory, "\n# " + title + "\ntext\n# ###\nempty heading\n# C#\nliteral hash\n")
            report = kb.inspect_concept(bundle, "project/goal", section=title, max_chars=65536)
            self.assertEqual("# " + title + "\ntext\n", report["content"])
            titles = [heading["title"] for heading in report["sections"]]
            self.assertIn("", titles)
            self.assertIn("C#", titles)

    def test_unicode_pagination_restores_exact_bytes_and_requires_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            _, bundle = self.fixture(directory, "\n# ページ\n日本語🙂e\u0301漢字\n")
            full = kb.inspect_concept(bundle, "project/goal", section="ページ", max_chars=65536)
            first = kb.inspect_concept(bundle, "project/goal", section="ページ", max_chars=7)
            self.assertTrue(first["truncated"])
            self.assertEqual(7, first["returned_chars"])
            combined, report = first["content"], first
            while report["next_offset"] is not None:
                report = kb.inspect_concept(bundle, "project/goal", section="ページ", max_chars=7,
                                             offset=report["next_offset"], expected_digest=first["source_digest"])
                combined += report["content"]
            self.assertEqual(full["content"], combined)
            self.assertIsNone(report["resume_args"])
            with self.assertRaisesRegex(kb.KnowledgeBaseError, "RESUME_DIGEST_REQUIRED"):
                kb.inspect_concept(bundle, "project/goal", offset=1)
            with self.assertRaisesRegex(kb.KnowledgeBaseError, "SOURCE_CHANGED"):
                kb.inspect_concept(bundle, "project/goal", offset=1, expected_digest="0" * 64)

    def test_stale_and_non_discoverable_concepts_cannot_be_read(self):
        with self.assertRaisesRegex(kb.KnowledgeBaseError, "UNAVAILABLE"):
            kb.inspect_concept(kb.load_bundle(ROOT, as_of=AS_OF.replace(year=2027)), "project/goal")
        for before, after in (("discoverable: true", "discoverable: false"),
                              ("knowledge_state: candidate", "knowledge_state: revoked"),
                              ("status: draft", "status: deprecated")):
            with self.subTest(after=after), tempfile.TemporaryDirectory() as directory:
                root, _ = self.fixture(directory)
                path = root / "knowledge/project/goal.md"
                path.write_text(path.read_text(encoding="utf-8").replace(before, after), encoding="utf-8")
                with self.assertRaisesRegex(kb.KnowledgeBaseError, "UNAVAILABLE|INVALID_BUNDLE"):
                    kb.inspect_concept(kb.load_bundle(root, as_of=AS_OF), "project/goal")

    def test_character_budgets_and_offsets_are_bounded(self):
        for kwargs in ({"max_chars": 0}, {"max_chars": 65537}, {"offset": -1},
                       {"offset": 1000000, "expected_digest": self.bundle.source_digest}):
            with self.subTest(kwargs=kwargs), self.assertRaises(kb.KnowledgeBaseError):
                kb.inspect_concept(self.bundle, "project/goal", **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            _, bundle = self.fixture(directory, "\n".join(f"# section {i}" for i in range(40)))
            report = kb.inspect_concept(bundle, "project/goal", max_chars=10)
            self.assertEqual(32, len(report["sections"]))
            self.assertTrue(report["sections_truncated"])

    def test_correction_during_rendering_never_emits_partial_response(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.fixture(directory)
            renderer = cli.inspection_markdown
            def correct(report):
                result = renderer(report)
                path = root / "knowledge/project/goal.md"
                path.write_text(path.read_text(encoding="utf-8") + "\nCorrection.\n", encoding="utf-8")
                return result
            with mock.patch.object(cli, "inspection_markdown", side_effect=correct):
                code, output, error = self.run_cli(["show", "project/goal", "--root", str(root)])
            self.assertEqual(2, code)
            self.assertEqual("", output)
            self.assertIn("SOURCE_CHANGED_RELOAD_REQUIRED", error)
