"""The offline benchmark must fail when evidence or indexed work regresses."""
from __future__ import annotations

from contextlib import closing, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import task_swarm_benchmark as benchmark


class TaskSwarmBenchmarkTests(unittest.TestCase):
    def test_real_adapters_preserve_context_correction_and_owner_boundary(self):
        report = benchmark.report((benchmark.PROFILES[0],))
        self.assertFalse(report["model_called"])
        self.assertFalse(report["reasoning_quality_measured"])
        self.assertEqual(report["gate_ceiling"], "LOCAL_PASS")
        result = report["profiles"][0]
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["records"], 32)
        self.assertEqual(result["correction_pages_sent"], 1)
        self.assertLess(result["correction_utf8_bytes"], result["source_utf8_bytes"])
        self.assertGreater(result["boundary_payload_bytes"], result["payload_limit_bytes"] - 256)
        self.assertEqual(result["scheduler"]["snapshot_history_selects"], 1)
        self.assertLessEqual(result["scheduler"]["snapshot_attempt_selects"], 3)
        self.assertEqual(result["scheduler"]["attempts"], result["scheduler"]["jobs"])
        raw = json.dumps(report)
        for forbidden in (str(ROOT), "text\":", "invocation_ref", "capability_ref", benchmark.NOTES[1]):
            self.assertNotIn(forbidden, raw)

    def test_benchmark_counter_observes_history_projection_and_repeated_queries(self):
        from test_task_swarm_state import SwarmStateTests
        fixture = SwarmStateTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        state = fixture.state()
        state.create_run(fixture.plan())
        with benchmark.work_counter(state) as counter, closing(state._connect()) as connection:
            connection.execute('select a.token from "attempts" as a where a.run_id=?', ("run-demo",)).fetchall()
            connection.execute('SELECT token FROM main.attempts WHERE run_id=?', ("run-demo",)).fetchall()
            connection.execute('SELECT COUNT(*) FROM attempts WHERE run_id=?', ("run-demo",)).fetchone()
        self.assertEqual(counter["history_selects"], 2)
        self.assertEqual(counter["attempt_selects"], 3)
        self.assertGreater(counter["vm_steps"], 0)

    def test_truncated_source_and_missing_evidence_make_benchmark_fail(self):
        original = benchmark.PeerTools._validated_message
        for damage in ("record", "evidence"):
            def damaged(client, binding, envelope):
                message = original(client, binding, envelope)
                if message["text"].startswith('{"page":'):
                    if damage == "record":
                        page = json.loads(message["text"])
                        page["records"].pop()
                        message["text"] = benchmark.canonical(page)
                    else:
                        message["evidence_refs"] = []
                return message
            with self.subTest(damage=damage), patch.object(benchmark.PeerTools, "_validated_message", damaged):
                with self.assertRaisesRegex(benchmark.SwarmError, "BENCHMARK_REGRESSION"):
                    benchmark.benchmark(benchmark.PROFILES[0])

    def test_correction_only_missing_or_stale_evidence_and_scope_fail(self):
        original = benchmark.PeerTools._validated_message
        for damage in ("missing_evidence", "stale_evidence", "revision", "context_digest"):
            def damaged(client, binding, envelope):
                message = original(client, binding, envelope)
                if message["revision"] == 2 and message["text"].startswith('{"page":'):
                    if damage == "missing_evidence":
                        message["evidence_refs"] = []
                    elif damage == "stale_evidence":
                        message["evidence_refs"] = [f"ref/source/page/{benchmark.PROFILES[0].pages-1}"]
                    elif damage == "revision":
                        message["revision"] = 1
                    else:
                        message["context_digest"] = "a" * 64
                return message
            with self.subTest(damage=damage), patch.object(benchmark.PeerTools, "_validated_message", damaged):
                with self.assertRaisesRegex(benchmark.SwarmError, "BENCHMARK_REGRESSION"):
                    benchmark.benchmark(benchmark.PROFILES[0])

    def test_retained_history_full_scan_is_a_regression(self):
        original = benchmark.seed_history
        def unindexed(client, count):
            original(client, count)
            with closing(sqlite3.connect(client.transport.db_path)) as connection, connection:
                connection.execute("DROP INDEX ix_messages_live_scope")
                connection.execute("DROP INDEX ix_messages_live_recipient")
        with patch.object(benchmark, "seed_history", unindexed):
            with self.assertRaisesRegex(benchmark.SwarmError, "admission work linear"):
                benchmark.benchmark(benchmark.PROFILES[0])

    def test_cli_requires_explicit_fixture_and_preserves_prior_report(self):
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            self.assertEqual(benchmark.main([]), 1)
            work = ROOT / "work"
            work.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(dir=work) as directory:
                report = Path(directory) / "prior.json"
                report.write_text("prior evidence", encoding="utf-8")
                self.assertEqual(benchmark.main(["--allow-local-fixture", "--output", str(report)]), 1)
                self.assertEqual(report.read_text(encoding="utf-8"), "prior evidence")


if __name__ == "__main__":
    unittest.main()
