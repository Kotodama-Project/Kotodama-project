"""Disposable index parity, source corrections and transactional recovery."""
from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import knowledge_base as kb
from kotodama_kb import cli, index

AS_OF = dt.datetime(2026, 10, 10, tzinfo=dt.timezone.utc)


class KnowledgeIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = kb.load_bundle(ROOT, as_of=AS_OF)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.database = self.directory / "knowledge.sqlite"
        index.build_index(self.bundle, self.database)

    def fixture(self, suffix=""):
        root = self.directory / "source"
        shutil.copytree(ROOT / "knowledge", root / "knowledge")
        for relative, _ in self.bundle.input_bindings:
            path = root / relative
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, path)
        path = root / "knowledge/project/goal.md"
        path.write_text(path.read_text(encoding="utf-8") + suffix, encoding="utf-8")
        bundle = kb.load_bundle(root, as_of=AS_OF)
        self.assertFalse([issue for issue in bundle.issues if issue.level == "error"])
        return root, bundle

    def assert_parity(self, bundle, query, **filters):
        actual, report = index.query_index(bundle, self.database, query, **filters)
        self.assertEqual(kb.query_bundle(bundle, query, **filters), actual)
        return report

    def test_public_corpus_rank_reasons_and_filters_match_baseline(self):
        for query in ("意図", "知", "検索", "検証結果", "ｋｇｉ", "project/goal", "context KGI",
                      "OUT-INTENT", "very-absent-token", "---", "context OR intent"):
            with self.subTest(query=query):
                self.assert_parity(self.bundle, query, limit=100)
        for filters in ({"limit": 1, "goals": ["OUT-INTENT"]},
                        {"kgis": ["KGI-INTENT"], "initiatives": ["INIT-METHOD-RENEWAL"]},
                        {"type_filter": "Goal", "tag_filter": "goal"}):
            self.assert_parity(self.bundle, "KGI", **filters)
        for filters in ({"goals": ["UNKNOWN"]}, {"limit": 101}):
            with self.assertRaises(kb.KnowledgeBaseError):
                index.query_index(self.bundle, self.database, "missing", **filters)

    def test_short_terms_and_mixed_queries_report_fallback(self):
        for query in ("知", "意図"):
            self.assertEqual("substring", self.assert_parity(self.bundle, query)["mode"])
        backend = index.verify_index(self.bundle, self.database)["backend"]
        if backend == "fts5-trigram":
            self.assertEqual("fts5-trigram", self.assert_parity(self.bundle, "context")["mode"])
            self.assertEqual("fts5-trigram+substring", self.assert_parity(self.bundle, "context 知")["mode"])

    def test_unicode_normalization_and_punctuation_preserve_substring_parity(self):
        _, bundle = self.fixture('\nＮＦＫＣ ＡＢＣ ｶﾀｶﾅ cafe\u0301 Straße 日本語🙂e\u0301 a-b _id "quoted" 100%\n')
        self.database = self.directory / "unicode.sqlite"
        index.build_index(bundle, self.database)
        for query in ("abc", "ａｂｃ", "カタカナ", "ｶﾀｶﾅ", "café", "cafe\u0301", "STRASSE", "本語",
                      "語🙂", "🙂é", "a-b", "_id", '"quoted"', '" OR "', "%", "\x00"):
            with self.subTest(query=query):
                self.assert_parity(bundle, query)

    def test_unchanged_build_keeps_database_bytes_and_reuses_all_rows(self):
        before = hashlib.sha256(self.database.read_bytes()).hexdigest()
        report = index.build_index(self.bundle, self.database)
        self.assertEqual((0, 0), (report["changed"], report["removed"]))
        self.assertEqual(before, hashlib.sha256(self.database.read_bytes()).hexdigest())
        self.assertEqual(self.bundle.source_digest, index.verify_index(self.bundle, self.database)["source_digest"])

    def test_same_size_same_mtime_correction_requires_rebuild_and_updates_one_row(self):
        root, bundle = self.fixture("\n原意図と検証の限定検索。\n")
        self.database = self.directory / "fixture.sqlite"
        index.build_index(bundle, self.database)
        path = root / "knowledge/project/goal.md"
        stat = path.stat()
        path.write_text(path.read_text(encoding="utf-8").replace("限定検索", "即時検索"), encoding="utf-8")
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        changed = kb.load_bundle(root, as_of=AS_OF)
        self.assertNotEqual(bundle.source_digest, changed.source_digest)
        with self.assertRaisesRegex(kb.KnowledgeBaseError, "INDEX_STALE"):
            index.query_index(changed, self.database, "即時検索")
        self.assertEqual(1, index.build_index(changed, self.database)["changed"])
        self.assert_parity(changed, "即時検索")
        self.assertEqual((), index.query_index(changed, self.database, "限定検索")[0])

    def test_source_only_change_refreshes_generation_without_rewriting_concepts(self):
        root, bundle = self.fixture()
        self.database = self.directory / "fixture.sqlite"
        index.build_index(bundle, self.database)
        path = root / "docs/PRODUCT-DIRECTION.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nSource correction.\n", encoding="utf-8")
        changed = kb.load_bundle(root, as_of=AS_OF)
        with self.assertRaisesRegex(kb.KnowledgeBaseError, "INDEX_STALE"):
            index.verify_index(changed, self.database)
        report = index.build_index(changed, self.database)
        self.assertEqual(0, report["changed"])
        self.assertEqual(changed.source_digest, report["source_digest"])

    def test_expiry_uses_current_audit_instant_without_rebuilding_cache(self):
        expired = kb.load_bundle(ROOT, as_of=AS_OF.replace(year=2027))
        self.assertEqual((), self.assert_expired(expired))
        self.assert_parity(expired, "KGI", include_stale=True)

    def assert_expired(self, bundle):
        self.assert_parity(bundle, "KGI")
        return index.query_index(bundle, self.database, "KGI")[0]

    def test_revocation_and_non_discoverable_rows_never_become_results(self):
        for before, after in (("discoverable: true", "discoverable: false"),
                              ("status: draft", "status: deprecated")):
            with self.subTest(after=after):
                root, bundle = self.fixture()
                path = root / "knowledge/project/goal.md"
                text = path.read_text(encoding="utf-8").replace(before, after)
                if "deprecated" in after:
                    text = text.replace("knowledge_state: candidate", "knowledge_state: revoked")
                path.write_text(text, encoding="utf-8")
                changed = kb.load_bundle(root, as_of=AS_OF)
                database = self.directory / f"state-{len(after)}.sqlite"
                index.build_index(changed, database)
                results, _ = index.query_index(changed, database, "project/goal", include_stale=True)
                self.assertNotIn("project/goal", [item.concept.concept_id for item in results])
                shutil.rmtree(root)

    def test_scope_schema_and_cache_corruption_are_explicit_failures(self):
        _, other = self.fixture()
        with self.assertRaisesRegex(kb.KnowledgeBaseError, "CONTRACT_MISMATCH"):
            index.query_index(other, self.database, "KGI")
        with sqlite3.connect(self.database) as connection:
            metadata = json.loads(connection.execute("SELECT value FROM metadata").fetchone()[0])
            metadata["schema"] = 999
            connection.execute("UPDATE metadata SET value = ?", (json.dumps(metadata),))
        with self.assertRaisesRegex(kb.KnowledgeBaseError, "CONTRACT_MISMATCH"):
            index.build_index(self.bundle, self.database)
        self.database.write_bytes(b"not a SQLite database")
        with self.assertRaisesRegex(kb.KnowledgeBaseError, "INDEX_READ_UNAVAILABLE"):
            index.query_index(self.bundle, self.database, "KGI")

    def test_normalized_row_drift_is_rejected_even_if_candidate_would_be_missing(self):
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE documents SET body = '', title = '', description = '' WHERE concept_id = 'project/goal'")
        with self.assertRaisesRegex(kb.KnowledgeBaseError, "CONTENT_MISMATCH"):
            index.query_index(self.bundle, self.database, "original-missing-candidate")
        with self.assertRaisesRegex(kb.KnowledgeBaseError, "CONTENT_MISMATCH"):
            index.verify_index(self.bundle, self.database)

    def test_non_text_cache_values_are_refused_without_a_traceback(self):
        # Remove triggers so SQLite does not reject the malformed cache first.
        with sqlite3.connect(self.database) as connection:
            connection.execute("DROP TRIGGER IF EXISTS documents_au")
            connection.execute("UPDATE documents SET body = ? WHERE concept_id = 'project/goal'", (b"invalid-blob",))
        with self.assertRaisesRegex(kb.KnowledgeBaseError, "CONTENT_MISMATCH"):
            index.query_index(self.bundle, self.database, "KGI")

    def test_explicit_postings_audit_refuses_drift_and_success_changes_no_bytes(self):
        before = self.database.read_bytes()
        report = index.verify_index(self.bundle, self.database)
        self.assertEqual(before, self.database.read_bytes())
        if report["backend"] != "fts5-trigram":
            self.skipTest("this SQLite has no FTS5 trigram backend")
        self.assertEqual("performed", report["postings_audit"])
        _, query_report = index.query_index(self.bundle, self.database, "KGI")
        self.assertEqual("not_performed", query_report["postings_audit"])
        self.assertEqual("same_operator_cache", query_report["postings_trust"])
        with sqlite3.connect(self.database) as connection:
            connection.execute("INSERT INTO search(search) VALUES ('delete-all')")
        damaged = self.database.read_bytes()
        with self.assertRaisesRegex(kb.KnowledgeBaseError, "POSTINGS_INVALID_OR_UNAVAILABLE"):
            index.verify_index(self.bundle, self.database)
        self.assertEqual(damaged, self.database.read_bytes())

    def test_interrupted_update_rolls_back_rows_and_generation_together(self):
        root, bundle = self.fixture()
        self.database = self.directory / "fixture.sqlite"
        index.build_index(bundle, self.database)
        path = root / "knowledge/project/goal.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nCorrection.\n", encoding="utf-8")
        changed = kb.load_bundle(root, as_of=AS_OF)
        before = self.database.read_bytes()
        with mock.patch.object(index, "_assert_current", side_effect=kb.KnowledgeBaseError("SOURCE_CHANGED")):
            with self.assertRaisesRegex(kb.KnowledgeBaseError, "SOURCE_CHANGED"):
                index.build_index(changed, self.database)
        self.assertEqual(before, self.database.read_bytes())
        index.build_index(changed, self.database)
        self.assert_parity(changed, "Correction")

    def test_removing_rows_is_atomic_and_does_not_leave_old_fts_entries(self):
        reduced = dataclasses.replace(self.bundle, concepts=tuple(
            item for item in self.bundle.concepts if item.concept_id != "project/goal"))
        # Index unit boundary only; a production bundle still goes through load_bundle.
        report = index.build_index(reduced, self.database)
        self.assertEqual(1, report["removed"])
        self.assert_parity(reduced, "project/goal")
        with self.assertRaisesRegex(kb.KnowledgeBaseError, "CONTENT_MISMATCH"):
            index.query_index(self.bundle, self.database, "project/goal")

    def test_real_rename_replaces_old_id_after_current_bundle_is_admitted(self):
        root, bundle = self.fixture()
        self.database = self.directory / "rename.sqlite"
        index.build_index(bundle, self.database)
        old = root / "knowledge/initiatives/context-handoff.md"
        old.rename(old.with_name("context-delivery.md"))
        for path in (root / "knowledge").rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            replacement = text.replace("context-handoff.md", "context-delivery.md").replace(
                "id: initiatives/context-handoff", "id: initiatives/context-delivery")
            if text != replacement:
                path.write_text(replacement, encoding="utf-8")
        changed = kb.load_bundle(root, as_of=AS_OF)
        self.assertEqual(1, index.build_index(changed, self.database)["removed"])
        self.assert_parity(changed, "意図", limit=100)
        results, _ = index.query_index(changed, self.database, "意図", limit=100)
        ids = [item.concept.concept_id for item in results]
        self.assertNotIn("initiatives/context-handoff", ids)
        self.assertIn("initiatives/context-delivery", ids)

    def test_initial_build_interruption_does_not_publish_partial_schema(self):
        path = self.directory / "interrupted.sqlite"
        with mock.patch.object(index, "_assert_current", side_effect=kb.KnowledgeBaseError("SOURCE_CHANGED")):
            with self.assertRaisesRegex(kb.KnowledgeBaseError, "SOURCE_CHANGED"):
                index.build_index(self.bundle, path)
        with sqlite3.connect(path) as connection:
            self.assertEqual([], connection.execute("SELECT name FROM sqlite_master").fetchall())
        index.build_index(self.bundle, path)
        index.verify_index(self.bundle, path)

    def test_unavailable_fts_has_explicit_extension_free_parity(self):
        create = index._create_schema
        class WithoutFTS:
            def __init__(self, connection):
                self.connection = connection
            def execute(self, sql):
                if "CREATE VIRTUAL TABLE" in sql:
                    raise sqlite3.OperationalError("no such module: fts5")
                return self.connection.execute(sql)
        self.database = self.directory / "fallback.sqlite"
        with mock.patch.object(index, "_create_schema", side_effect=lambda connection: create(WithoutFTS(connection))):
            self.assertEqual("substring", index.build_index(self.bundle, self.database)["backend"])
        for query in ("意図", "context", "ｋｇｉ", "context 意図"):
            self.assertEqual("substring", self.assert_parity(self.bundle, query)["mode"])

    def test_writer_contention_is_bounded_and_preserves_existing_generation(self):
        with sqlite3.connect(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            with self.assertRaisesRegex(kb.KnowledgeBaseError, "INDEX_WRITE_UNAVAILABLE"):
                index.build_index(self.bundle, self.database)
        index.verify_index(self.bundle, self.database)

    def test_query_budget_and_missing_cache_do_not_silently_fallback(self):
        for query in ("a" * 4097, " ".join(f"t{i}" for i in range(65))):
            with self.assertRaisesRegex(kb.KnowledgeBaseError, "INDEX_QUERY_BUDGET"):
                index.query_index(self.bundle, self.database, query)
        with self.assertRaisesRegex(kb.KnowledgeBaseError, "INDEX_READ_UNAVAILABLE"):
            index.query_index(self.bundle, self.directory / "absent.sqlite", "KGI")
        self.assertFalse((self.directory / "absent.sqlite").exists())

    def test_cli_index_and_query_share_verified_generation(self):
        args = ["--as-of", AS_OF.isoformat(), "--json"]
        for command in (["index", "--database", str(self.database), "--check", *args],
                        ["query", "KGI", "--index", str(self.database), "--goal", "OUT-INTENT", *args]):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = cli.main(command)
            self.assertEqual(0, code)
            report = json.loads(output.getvalue())
            self.assertEqual(self.bundle.source_digest, report["source_digest"])
        with mock.patch.object(cli, "_assert_current", side_effect=kb.KnowledgeBaseError("SOURCE_CHANGED")):
            output, errors = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                code = cli.main(["query", "KGI", "--index", str(self.database), *args])
            self.assertEqual(2, code)
            self.assertEqual("", output.getvalue())
