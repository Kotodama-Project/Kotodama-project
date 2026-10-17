"""Check the measurement mechanism without qualifying shared-host performance."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import signal
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
from performance_benchmark import runner, task_admission as fixture


def result(width=1, workload="wait"):
    return {"schema": "kotodama.task-admission-fixture.v1", "status": "PASS", "node": "v24.19.0",
            "width": width, "workload": workload, "tasks": 16, "iterations": 262144, "wait_ms": 40,
            "initial_queued": 16 - width, "peak_active": 1, "workload_wall_ms": 100,
            "verification": dict.fromkeys(fixture.FLAGS, True),
            "rows": [{"index": i, "value": fixture.reference_value(i, workload),
                      "queue_wait_ms": i, "execution_ms": 1, "completion_ms": i + 1} for i in range(16)]}


def launched():
    return {"status": "PASS", "code": None, "node": "v24.19.0", "exit_code": 0,
            "input_digest": "a" * 64, "result_digest": "b" * 64, "wall_ms": 3,
            "peak_rss_bytes": 10, "cpu_seconds": .01, "workload_wall_ms": 2,
            "throughput_tasks_per_second": 8, "owned_process_reaped": True}


class TaskAdmissionBenchmarkTests(unittest.TestCase):
    def test_independent_affine_reference_matches_iterative_work(self):
        for index in (0, 7, 15):
            value = index + 1
            for _ in range(fixture.ITERATIONS):
                value = (value * 1664525 + 1013904223) & 0xffffffff
            self.assertEqual(fixture.reference_value(index, "cpu"), value)

    def test_missing_task_wrong_result_and_weakened_guards_are_refused(self):
        for width in (1, 2, 4):
            fixture.validate_result(json.dumps(result(width)), width, "wait")
        bad = []
        for key, value in (("tasks", 15), ("width", True), ("peak_active", 5), ("initial_queued", 0),
                           ("workload_wall_ms", float("nan"))):
            row = result();row[key] = value;bad.append(row)
        for flag in fixture.FLAGS:
            row = result();row["verification"][flag] = False;bad.append(row)
        row = result();row["rows"].pop();bad.append(row)
        for key, value in (("index", 1), ("value", 99), ("execution_ms", -1), ("completion_ms", 99)):
            row = result();row["rows"][0][key] = value;bad.append(row)
        for row in bad:
            with self.assertRaises(runner.BenchmarkError):
                fixture.validate_result(json.dumps(row), 1, "wait")

    def test_no_fixture_permission_or_swarm_only_options_dispatch_nothing(self):
        for args in (["--fixture", "task-admission"], ["--allow-local-fixture", "--width", "2"],
                     ["--allow-local-fixture", "--fixture", "task-admission", "--width", "3"]):
            with patch.object(fixture, "launch") as launch, contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(runner.main(args), 2)
                self.assertEqual(json.loads(output.getvalue())["status"], "REFUSED")
                launch.assert_not_called()

    def test_platform_and_node_missing_are_explicit(self):
        with patch.object(fixture.sys, "platform", "win32"), self.assertRaisesRegex(runner.BenchmarkError, "PLATFORM_UNSUPPORTED"):
            fixture.run_benchmark()
        with patch.object(fixture.sys, "platform", "linux"), \
                patch.object(fixture.os, "wait4", side_effect=AssertionError("must not observe"), create=True), \
                patch.object(fixture.shutil, "which", return_value=None), \
                self.assertRaisesRegex(runner.BenchmarkError, "NODE_UNAVAILABLE"):
            fixture.run_benchmark()

    @unittest.skipUnless(sys.platform == "linux", "Linux external wait4 observer")
    def test_partial_drift_and_missing_counters_do_not_fabricate_samples(self):
        missing = {**launched(), "peak_rss_bytes": None, "cpu_seconds": None}
        with patch.object(fixture.shutil, "which", return_value="node"), patch.object(fixture, "launch", return_value=missing):
            report = fixture.run_benchmark(samples=1, warmups=0)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["qualification"], "NOT_EVALUATED")
        self.assertEqual(report["missing"]["rss"], "COUNTER_UNAVAILABLE")
        self.assertIsNone(report["summary"]["peak_rss_bytes"]["p50"])
        failed = {"status": "TIMEOUT", "code": "SAMPLE_TIMEOUT", "wall_ms": 1, "exit_code": -9}
        with patch.object(fixture.shutil, "which", return_value="node"), patch.object(fixture, "launch", side_effect=[launched(), failed]) as launch:
            report = fixture.run_benchmark(samples=3, warmups=1)
        self.assertEqual(report["status"], "FAIL");self.assertEqual(launch.call_count, 2)
        self.assertEqual(report["scope"]["samples_completed"], 1)
        self.assertEqual(report["missing"]["rss"], "NO_SUCCESSFUL_SAMPLE")
        self.assertIsNone(report["summary"]["wall_ms"])
        with patch.object(fixture.shutil, "which", return_value="node"), patch.object(fixture, "launch", return_value=launched()), \
                patch.object(fixture, "code_snapshot", side_effect=[{"digest": "a"}, OSError("private-path")]):
            report = fixture.run_benchmark(samples=2, warmups=0)
        self.assertEqual(report["code"], "BENCHMARK_IO_FAILED")
        self.assertEqual(len(report["attempts"]), 1);self.assertNotIn("private-path", json.dumps(report))

    @unittest.skipUnless(sys.platform == "linux", "Linux external wait4 observer")
    def test_observer_includes_final_allocation_and_reaps_timeout(self):
        # Allocation after startup and before final output must be covered by OS
        # high-water accounting, even though no sample thread saw its lifetime.
        command = [sys.executable, "-c", "x=bytearray(32*1024*1024); print('done')"]
        metrics, raw = fixture._observe(command, 5)
        self.assertEqual(raw.strip(), b"done");self.assertEqual(metrics["status"], "PASS")
        self.assertGreater(metrics["peak_rss_bytes"], 32 * 1024 * 1024)
        self.assertGreaterEqual(metrics["cpu_seconds"], 0)
        metrics, raw = fixture._observe([sys.executable, "-c", "import time; time.sleep(30)"], .1)
        self.assertEqual(metrics["status"], "TIMEOUT");self.assertIsNone(raw)
        self.assertTrue(metrics["owned_process_reaped"])
        self.assertEqual(metrics["exit_code"], -signal.SIGKILL)

    @unittest.skipUnless(sys.platform == "linux" and shutil.which("node"), "Linux and Node fixture")
    def test_real_fixed_tasks_all_widths_and_workloads_have_identical_results(self):
        for workload in ("wait", "cpu"):
            values = []
            for width in (1, 2, 4):
                sample = fixture.launch(shutil.which("node"), width, workload, 10)
                self.assertEqual(sample["status"], "PASS", sample)
                self.assertTrue(sample["owned_process_reaped"])
                self.assertEqual(sample["initial_queued"], 16 - width)
                self.assertEqual(len(sample["rows"]), 16)
                self.assertTrue(all(sample["verification"][key] for key in fixture.FLAGS))
                values.append((sample["input_digest"], sample["result_digest"]))
            self.assertEqual(len(set(values)), 1)

    def test_manifest_pins_scheduler_common_fixture_and_observer(self):
        pinned = fixture.code_snapshot()
        self.assertIn("runtime/discord-template/src/task-admission.mjs", pinned["files"])
        self.assertIn("runtime/performance_benchmark/task_admission.py", pinned["files"])
        self.assertNotIn(str(ROOT), json.dumps(pinned))


if __name__ == "__main__":
    unittest.main()
