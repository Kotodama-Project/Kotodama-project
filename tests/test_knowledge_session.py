"""The optional JSONL loop preserves single-shot source and query contracts."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from kotodama_kb import cli, foundation, session

AS_OF = "2026-10-10T00:00:00Z"
LATER = "2027-01-01T00:00:00Z"


class KnowledgeSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = cli.load_bundle(ROOT, as_of=cli._parse_as_of(AS_OF))

    def fixture(self, suffix=""):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        shutil.copytree(ROOT / "knowledge", root / "knowledge")
        for relative, _ in self.bundle.input_bindings:
            destination = root / relative
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, destination)
        if suffix:
            path = root / "knowledge/project/goal.md"
            path.write_text(path.read_text(encoding="utf-8") + suffix, encoding="utf-8")
        return root

    def request(self, instance, args, *, request_id="read", at=AS_OF):
        arguments = args if at is None else [*args, "--as-of", at]
        return json.loads(instance.handle(json.dumps({"id": request_id, "args": arguments},
                                                    ensure_ascii=False).encode("utf-8")))

    def single(self, root, args):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            code = cli.main([*args, "--root", str(root), "--json", "--as-of", AS_OF])
        self.assertEqual(0, code, error.getvalue())
        return json.loads(output.getvalue())

    def test_query_and_show_match_single_shot_including_filters(self):
        instance = session.KnowledgeSession(ROOT)
        cases = [
            ["query", "KGI", "--goal", "OUT-INTENT", "--kgi", "KGI-INTENT", "--limit", "3"],
            ["query", "KGI", "--goal", "OUT-LOCAL", "--initiative", "INIT-CONTEXT-HANDOFF"],
            ["query", "言霊", "--type", "Goal"],
            ["query", "aauniqueabsentqueryzz"],
            ["show", "project/goal", "--section", "Required properties", "--max-chars", "100"],
        ]
        for args in cases:
            with self.subTest(args=args):
                result = self.request(instance, args)
                self.assertTrue(result["ok"], result)
                self.assertEqual(self.single(ROOT, args), result["result"])

    def test_unchanged_bytes_reuse_one_parsed_generation(self):
        instance = session.KnowledgeSession(ROOT)
        with mock.patch.object(cli, "load_bundle", wraps=cli.load_bundle) as load:
            for number in range(5):
                result = self.request(instance, ["query", "KGI"], request_id=str(number))
                self.assertTrue(result["ok"], result)
            self.assertEqual(1, load.call_count)

    def test_same_size_same_mtime_correction_reloads_and_removes_old_text(self):
        root = self.fixture("\n# Revision\nuniquesessionA\n")
        instance = session.KnowledgeSession(root)
        path = root / "knowledge/project/goal.md"
        with mock.patch.object(cli, "load_bundle", wraps=cli.load_bundle) as load:
            first = self.request(instance, ["query", "uniquesessionA"])
            self.assertTrue(first["result"]["results"])
            metadata = path.stat()
            raw = path.read_bytes()
            path.write_bytes(raw.replace(b"uniquesessionA", b"uniquesessionB"))
            os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
            self.assertEqual(metadata.st_size, path.stat().st_size)
            self.assertEqual(metadata.st_mtime_ns, path.stat().st_mtime_ns)
            revised = self.request(instance, ["query", "uniquesessionB"])
            self.assertTrue(revised["ok"], revised)
            self.assertTrue(revised["result"]["results"])
            self.assertNotEqual(first["result"]["source_digest"], revised["result"]["source_digest"])
            self.assertEqual([], self.request(instance, ["query", "uniquesessionA"])["result"]["results"])
            self.assertEqual(2, load.call_count)

    def test_add_rename_and_delete_are_reloaded(self):
        root = self.fixture()
        instance = session.KnowledgeSession(root)
        self.assertTrue(self.request(instance, ["query", "KGI"])["ok"])
        path = root / "knowledge/operations/session-fixture.md"
        raw = (root / "knowledge/operations/refresh-loop.md").read_text(encoding="utf-8")
        path.write_text(raw.replace("id: operations/refresh-loop", "id: operations/session-fixture")
                        + "\nuniquesessionfixture\n", encoding="utf-8")
        index = root / "knowledge/operations/index.md"
        original_index = index.read_text(encoding="utf-8")
        index.write_text(original_index + "\n* [Session fixture](session-fixture.md)\n", encoding="utf-8")
        added = self.request(instance, ["query", "uniquesessionfixture"])
        self.assertTrue(added["ok"], added)
        self.assertEqual(["operations/session-fixture"], [r["id"] for r in added["result"]["results"]])
        renamed = path.with_name("session-renamed.md")
        path.rename(renamed)
        renamed.write_text(renamed.read_text(encoding="utf-8").replace("operations/session-fixture",
                                                                     "operations/session-renamed"), encoding="utf-8")
        index.write_text(index.read_text(encoding="utf-8").replace("session-fixture.md", "session-renamed.md"),
                         encoding="utf-8")
        moved = self.request(instance, ["query", "uniquesessionfixture"])
        self.assertTrue(moved["ok"], moved)
        self.assertEqual(["operations/session-renamed"], [r["id"] for r in moved["result"]["results"]])
        renamed.unlink()
        index.write_text(original_index, encoding="utf-8")
        deleted = self.request(instance, ["query", "uniquesessionfixture"])
        self.assertTrue(deleted["ok"], deleted)
        self.assertEqual([], deleted["result"]["results"])

    def test_missing_bound_source_never_falls_back_to_old_generation(self):
        root = self.fixture()
        instance = session.KnowledgeSession(root)
        self.assertTrue(self.request(instance, ["show", "project/goal"])["ok"])
        (root / "README.md").unlink()
        failed = self.request(instance, ["show", "project/goal"])
        self.assertFalse(failed["ok"])
        self.assertNotIn("result", failed)
        self.assertIsNone(instance._bundle)

    def test_referenced_source_outside_knowledge_is_checked(self):
        root = self.fixture()
        instance = session.KnowledgeSession(root)
        before = self.request(instance, ["show", "project/goal"])
        path = root / "docs/OWNER-INTENT-COMPANY-AGI.md"
        path.write_bytes(path.read_bytes() + b"\nUpdated source.\n")
        after = self.request(instance, ["show", "project/goal"])
        self.assertTrue(after["ok"], after)
        self.assertNotEqual(before["result"]["source_digest"], after["result"]["source_digest"])

    def test_pinned_source_correction_refuses_without_reusing_old_bytes(self):
        root = self.fixture()
        path = root / "knowledge/project/goal.md"
        digest = hashlib.sha256((root / "README.md").read_bytes()).hexdigest()
        path.write_text(path.read_text(encoding="utf-8").replace("resource: ../../README.md",
                        "resource: ../../README.md\n    sha256: " + digest), encoding="utf-8")
        instance = session.KnowledgeSession(root)
        self.assertTrue(self.request(instance, ["show", "project/goal"])["ok"])
        source = root / "README.md"
        source.write_bytes(source.read_bytes() + b"\nChanged pinned source.\n")
        result = self.request(instance, ["show", "project/goal"])
        self.assertEqual("INVALID_BUNDLE", result["error"])
        self.assertNotIn("result", result)
        self.assertIsNone(instance._bundle)

    def test_warm_requests_read_every_source_again_through_final_gate(self):
        instance = session.KnowledgeSession(ROOT)
        self.assertTrue(self.request(instance, ["query", "KGI"])["ok"])
        actual = foundation._capture_inputs
        captured = []
        def observe(root, paths):
            result = actual(root, paths)
            captured.append(result)
            return result
        with mock.patch.object(foundation, "_capture_inputs", side_effect=observe):
            self.assertTrue(self.request(instance, ["query", "KGI"])["ok"])
        self.assertGreaterEqual(len(captured), 2)
        self.assertTrue(all(bindings == self.bundle.input_bindings for bindings in captured))

    def test_revocation_and_non_discoverability_apply_on_next_request(self):
        for change in ("revoke", "hide"):
            with self.subTest(change=change):
                root = self.fixture("\nuniquesessionvisible\n")
                instance = session.KnowledgeSession(root)
                self.assertTrue(self.request(instance, ["show", "project/goal"])["ok"])
                path = root / "knowledge/project/goal.md"
                raw = path.read_text(encoding="utf-8")
                if change == "revoke":
                    raw = raw.replace("knowledge_state: candidate", "knowledge_state: revoked")
                    raw = raw.replace("status: draft", "status: deprecated")
                else:
                    raw = raw.replace("discoverable: true", "discoverable: false")
                path.write_text(raw, encoding="utf-8")
                result = self.request(instance, ["query", "uniquesessionvisible"])
                self.assertTrue(result["ok"], result)
                self.assertEqual([], result["result"]["results"])
                self.assertFalse(self.request(instance, ["show", "project/goal"])["ok"])

    def test_freshness_is_recomputed_in_both_time_directions(self):
        instance = session.KnowledgeSession(ROOT)
        self.assertTrue(self.request(instance, ["show", "project/goal"])["ok"])
        self.assertFalse(self.request(instance, ["show", "project/goal"], at=LATER)["ok"])
        self.assertTrue(self.request(instance, ["show", "project/goal"])["ok"])
        stale = self.request(instance, ["query", "KGI"], at=LATER)
        self.assertEqual([], stale["result"]["results"])
        included = self.request(instance, ["query", "KGI", "--include-stale"], at=LATER)
        self.assertTrue(included["result"]["results"])
        self.assertTrue(all(r["stale"] for r in included["result"]["results"]))
        self.assertTrue(self.request(instance, ["show", "project/goal"])["ok"])

    def test_omitted_audit_time_is_obtained_again_for_every_request(self):
        instance = session.KnowledgeSession(ROOT)
        times = [cli._parse_as_of(AS_OF), cli._parse_as_of(LATER)]
        with mock.patch.object(cli, "_parse_as_of", side_effect=times) as clock:
            self.assertTrue(self.request(instance, ["show", "project/goal"], at=None)["ok"])
            self.assertFalse(self.request(instance, ["show", "project/goal"], at=None)["ok"])
        self.assertEqual([mock.call(None), mock.call(None)], clock.call_args_list)

    def test_unknown_goal_and_read_write_commands_are_explicit_errors(self):
        instance = session.KnowledgeSession(ROOT)
        unknown = self.request(instance, ["query", "KGI", "--goal", "UNDEFINED"])
        self.assertFalse(unknown["ok"])
        self.assertEqual("QUERY_REFERENCE_UNKNOWN", unknown["error"])
        self.assertNotIn("result", unknown)
        for command in ("build", "validate", "context", "audit", "readiness"):
            with self.subTest(command=command):
                failure = self.request(instance, [command])
                self.assertEqual("SESSION_COMMAND_NOT_READ_ONLY", failure["error"])

    def test_root_is_pinned_and_single_shot_resume_args_work(self):
        root = self.fixture("\n# ページ\n日本語🙂e\u0301漢字" * 2)
        instance = session.KnowledgeSession(root)
        first = self.request(instance, ["show", "project/goal", "--max-chars", "7"])
        self.assertTrue(first["ok"], first)
        resumed = self.request(instance, first["result"]["resume_args"])
        self.assertTrue(resumed["ok"], resumed)
        self.assertEqual(first["result"]["next_offset"], resumed["result"]["offset"])
        for flag in ("--root", "--root=", "--roo"):
            args = ["query", "KGI", flag, str(ROOT)] if flag != "--root=" else ["query", "KGI", flag + str(ROOT)]
            with self.subTest(flag=flag):
                self.assertFalse(self.request(instance, args)["ok"])

    def test_source_change_during_final_serialization_emits_only_error(self):
        root = self.fixture()
        instance = session.KnowledgeSession(root)
        path = root / "knowledge/project/goal.md"
        dumps = json.dumps
        raw = dumps({"id": "changed", "args": ["show", "project/goal", "--as-of", AS_OF]}).encode()
        def correct(value, *args, **kwargs):
            result = dumps(value, *args, **kwargs)
            if isinstance(value, dict) and value.get("ok") is True:
                path.write_bytes(path.read_bytes() + b"\nCorrection during serialization.\n")
            return result
        with mock.patch.object(session.json, "dumps", side_effect=correct):
            response = json.loads(instance.handle(raw))
        self.assertEqual("SOURCE_CHANGED_RELOAD_REQUIRED", response["error"])
        self.assertNotIn("result", response)
        self.assertIsNone(instance._bundle)
        self.assertTrue(self.request(instance, ["show", "project/goal"])["ok"])

    def test_invalid_json_and_unicode_are_bounded_errors(self):
        instance = session.KnowledgeSession(ROOT)
        cases = [b"not json", b"\xff", b'{}', b'[]',
                 b'{"id":"a","id":"b","args":["query","KGI"]}',
                 b'{"id":"a","args":["query",NaN]}',
                 b'{"id":"a","args":["query","KGI"],"extra":1}',
                 b'{"id":"\\ud800","args":["query","KGI"]}',
                 b'{"id":"a","args":["query","\\ud800"]}',
                 json.dumps({"id": "a", "args": ["query", "a" * 4097]}).encode()]
        for raw in cases:
            with self.subTest(raw=raw[:60]):
                response = instance.handle(raw)
                self.assertLessEqual(len(response), session.MAX_RESPONSE_BYTES)
                self.assertEqual("SESSION_REQUEST_INVALID", json.loads(response)["error"])

    def test_oversized_requests_and_responses_are_refused(self):
        instance = session.KnowledgeSession(ROOT)
        self.assertEqual("SESSION_REQUEST_BYTE_BUDGET", json.loads(instance.handle(
            b" " * (session.MAX_REQUEST_BYTES + 1)))["error"])
        with mock.patch.object(session, "MAX_RESPONSE_BYTES", 1024):
            response = self.request(instance, ["show", "project/goal"])
        self.assertEqual("SESSION_RESPONSE_BYTE_BUDGET", response["error"])
        self.assertNotIn("result", response)

    def test_escaped_source_surrogate_is_an_encoding_refusal(self):
        root = self.fixture()
        path = root / "knowledge/project/goal.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "title: Kotodama project goal", 'title: "\\uD800"'), encoding="utf-8")
        instance = session.KnowledgeSession(root)
        result = self.request(instance, ["show", "project/goal"])
        self.assertEqual("SESSION_RESPONSE_ENCODING", result["error"])
        self.assertNotIn("result", result)
        self.assertIsNone(instance._bundle)

    def test_request_count_and_transport_do_not_prefetch(self):
        raw = json.dumps({"id": "one", "args": ["query", "missingxyz", "--as-of", AS_OF]}).encode() + b"\n"
        source, sink = io.BytesIO(raw * 3), io.BytesIO()
        self.assertEqual(0, session.run(ROOT, source, sink, max_requests=2))
        self.assertEqual(raw, source.read())
        self.assertEqual(2, len(sink.getvalue().splitlines()))
        for budget in (0, 257, True):
            with self.subTest(budget=budget), self.assertRaisesRegex(cli.KnowledgeBaseError, "COUNT_BUDGET"):
                session.run(ROOT, io.BytesIO(), io.BytesIO(), max_requests=budget)
        oversized = io.BytesIO(b"x" * (session.MAX_REQUEST_BYTES + 2) + b"\n" + raw)
        sink = io.BytesIO()
        self.assertEqual(2, session.run(ROOT, oversized, sink))
        self.assertEqual(1, len(sink.getvalue().splitlines()))
        self.assertEqual(session.MAX_REQUEST_BYTES + 1, oversized.tell())

    def test_real_stdio_entrypoint_has_jsonl_stdout_and_no_writes(self):
        root = self.fixture()
        before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        request = json.dumps({"id": "stdio", "args": ["query", "KGI", "--as-of", AS_OF]}) + "\n"
        completed = subprocess.run([sys.executable, "-B", str(ROOT / "tools/knowledge_session.py"),
                                    "--root", str(root), "--max-requests", "1"], input=request,
                                   text=True, capture_output=True, check=False, timeout=30)
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("", completed.stderr)
        self.assertEqual(1, len(completed.stdout.splitlines()))
        self.assertTrue(json.loads(completed.stdout)["ok"])
        self.assertEqual(before, {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()})


if __name__ == "__main__":
    unittest.main()
