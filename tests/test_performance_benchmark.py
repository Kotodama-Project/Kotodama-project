"""Fixed-fixture measurement must not turn partial runs into performance claims."""
import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
from performance_benchmark import runner, worker


def successful():
    return {"schema": runner.VERSION, "status": "PASS", "fixture": "swarm-short",
            "code_digest": "a" * 64, "input_digest": "b" * 64, "result_digest": "c" * 64,
            "model_called": False, "peak_rss_bytes": 12345, "peak_rss_missing": None, "sqlite_version": "test",
            "verification": {"status": "PASS", "profile": "short", "records": 32,
                             "source_pages": 4, "source_utf8_bytes": 6550, "max_payload_bytes": 1840,
                             "payload_limit_bytes": 16384, "boundary_payload_bytes": 16286,
                             "retained_messages": 1000, "admission_vm_steps_before": 1000,
                             "admission_vm_steps_retained": 1100, "replay_vm_steps_retained": 180,
                             "correction_utf8_bytes": 1600, "correction_pages_sent": 1,
                             "fidelity_verified": True, "restart_replay_verified": True,
                             "revocation_verified": True, "source_drift_verified": True,
                             "backpressure_verified": True,
                             "scheduler": {"jobs": 5, "attempts": 5, "snapshot_history_selects": 1,
                                           "snapshot_attempt_selects": 3, "waiting_owner_verified": True,
                                           "independent_reviewer_verified": True}}}


class PerformanceBenchmarkTests(unittest.TestCase):
    def test_rss_units_and_platform_without_counter_are_explicit(self):
        resource = SimpleNamespace(RUSAGE_SELF=0, getrusage=lambda _: SimpleNamespace(ru_maxrss=12))
        with patch.dict(sys.modules, resource=resource):
            with patch.object(worker.sys, "platform", "linux"):
                self.assertEqual(worker.peak_rss(), (12288, None))
            with patch.object(worker.sys, "platform", "darwin"):
                self.assertEqual(worker.peak_rss(), (12, None))
            with patch.object(worker.sys, "platform", "win32"):
                self.assertEqual(worker.peak_rss(), (None, "UNSUPPORTED_PLATFORM"))

    def test_rss_counter_failure_and_partial_missing_preserve_reasons(self):
        resource = SimpleNamespace(RUSAGE_SELF=0, getrusage=lambda _: (_ for _ in ()).throw(OSError()))
        with patch.dict(sys.modules, resource=resource), patch.object(worker.sys, "platform", "linux"):
            self.assertEqual(worker.peak_rss(), (None, "COUNTER_UNAVAILABLE"))
        measured = {**successful(), "wall_ms": 10, "exit_code": 0}
        missing = {**measured, "peak_rss_bytes": None, "peak_rss_missing": "COUNTER_UNAVAILABLE"}
        self.assertEqual(runner._worker_result(json.dumps(missing), 0, "a" * 64), missing)
        for rows, expected in (([missing, missing], "COUNTER_UNAVAILABLE"),
                               ([measured, missing], "PARTIALLY_MISSING")):
            with patch.object(runner, "launch", side_effect=rows):
                report = runner.run_benchmark(samples=2, warmups=0)
            self.assertEqual(report["missing"]["rss"], expected)
            self.assertEqual(report["scope"]["rss_samples"]["missing"], rows.count(missing))
            self.assertEqual(report["scope"]["rss_samples"]["missing_reasons"],
                             {"COUNTER_UNAVAILABLE": rows.count(missing)})
            self.assertEqual(report["summary"]["peak_rss_bytes"]["samples"], rows.count(measured))

    def test_percentiles_are_nearest_rank_and_empty_values_are_unknown(self):
        self.assertEqual(runner.distribution([3, 1, 4, 2]),
                         {"samples": 4, "min": 1, "p50": 2, "p95": 4, "max": 4})
        self.assertEqual(runner.distribution([])["p95"], None)

    def test_permission_and_fixed_fixture_are_required_before_dispatch(self):
        for args in ([], ["--fixture", "private-command"],
                     ["--allow-local-fixture", "--samples", "21"],
                     ["--allow-local-fixture", "--warmups", "4"],
                     ["--allow-local-fixture", "--timeout-seconds", "0"],
                     ["--allow-local-fixture", "--command", "sensitive-example"]):
            with self.subTest(args=args), patch.object(runner, "launch") as launch, contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(runner.main(args), 2)
                self.assertEqual(json.loads(out.getvalue())["status"], "REFUSED")
                self.assertNotIn("sensitive-example", out.getvalue())
                launch.assert_not_called()

    def test_worker_result_requires_bound_code_fixture_and_verification(self):
        result = successful()
        self.assertEqual(runner._worker_result(json.dumps(result), 0, "a" * 64), result)
        for field, value in (("code_digest", "d" * 64), ("model_called", True),
                             ("fixture", "other"), ("input_digest", "not-a-digest"),
                             ("peak_rss_bytes", -1), ("peak_rss_missing", "COUNTER_UNAVAILABLE"), ("verification", {})):
            broken = copy.deepcopy(result); broken[field] = value
            with self.subTest(field=field), self.assertRaises(runner.BenchmarkError):
                runner._worker_result(json.dumps(broken), 0, "a" * 64)
        with self.assertRaises(runner.BenchmarkError):
            runner._worker_result("not json private-path", 0, "a" * 64)

    def test_warmups_are_excluded_from_summary_and_unavailable_rss_is_explicit(self):
        values = [{**successful(), "wall_ms": value, "exit_code": 0, "peak_rss_bytes": None,
                   "peak_rss_missing": "UNSUPPORTED_PLATFORM"}
                  for value in (999, 10, 20)]
        with patch.object(runner, "launch", side_effect=values):
            report = runner.run_benchmark(samples=2, warmups=1)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["summary"]["wall_ms_successful"]["p50"], 10)
        self.assertEqual(report["summary"]["wall_ms_successful"]["p95"], 20)
        self.assertEqual(report["missing"]["rss"], "UNSUPPORTED_PLATFORM")
        self.assertEqual(report["summary"]["peak_rss_bytes"]["samples"], 0)

    def test_every_fixture_verification_flag_is_required(self):
        fields = ["fidelity_verified", "restart_replay_verified", "revocation_verified",
                  "source_drift_verified", "backpressure_verified", "scheduler.waiting_owner_verified",
                  "scheduler.independent_reviewer_verified"]
        for field in fields:
            for damage in ("missing", False, "true"):
                broken = successful()
                target = broken["verification"]
                parts = field.split(".")
                for part in parts[:-1]:
                    target = target[part]
                if damage == "missing":
                    target.pop(parts[-1])
                else:
                    target[parts[-1]] = damage
                with self.subTest(field=field, damage=damage), self.assertRaisesRegex(
                        runner.BenchmarkError, "FIXTURE_VERIFICATION_MISSING"):
                    runner._worker_result(json.dumps(broken), 0, "a" * 64)

    def test_fixture_work_and_payload_contract_cannot_be_shortened(self):
        changes = [("source_pages", 3), ("retained_messages", 0), ("correction_pages_sent", 2),
                   ("source_utf8_bytes", 0), ("max_payload_bytes", 16385),
                   ("boundary_payload_bytes", 16000), ("correction_utf8_bytes", 6551),
                   ("admission_vm_steps_before", -1), ("admission_vm_steps_retained", 4001),
                   ("replay_vm_steps_retained", True), ("scheduler", None),
                   ("scheduler.jobs", 0), ("scheduler.jobs", True), ("scheduler.attempts", 4),
                   ("scheduler.snapshot_history_selects", 0), ("scheduler.snapshot_attempt_selects", 99)]
        for field, value in changes:
            broken = successful()
            target = broken["verification"]
            parts = field.split(".")
            for part in parts[:-1]:
                target = target[part]
            target[parts[-1]] = value
            with self.subTest(field=field), self.assertRaisesRegex(
                    runner.BenchmarkError, "FIXTURE_VERIFICATION_MISSING"):
                runner._worker_result(json.dumps(broken), 0, "a" * 64)

    def test_post_attempt_snapshot_io_failure_preserves_partial_cli_report(self):
        for completed in (1, 2):
            pinned = {"digest": "a" * 64}
            snapshots = [pinned] * completed + [OSError("private-path-not-for-output")]
            result = {**successful(), "wall_ms": 10, "exit_code": 0}
            with self.subTest(completed=completed), patch.object(runner, "code_snapshot", side_effect=snapshots), \
                 patch.object(runner, "launch", return_value=result) as launch, \
                 contextlib.redirect_stdout(io.StringIO()) as out:
                exit_code = runner.main(["--allow-local-fixture", "--samples", "2", "--warmups", "1"])
            report = json.loads(out.getvalue())
            self.assertEqual(exit_code, 1)
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(report["code"], "BENCHMARK_IO_FAILED")
            self.assertEqual(len(report["attempts"]), completed)
            self.assertEqual(report["attempts"][-1]["wall_ms"], 10)
            self.assertEqual(report["scope"]["samples_completed"], completed - 1)
            self.assertEqual(launch.call_count, completed)
            self.assertIsNone(report["summary"]["wall_ms_successful"])
            self.assertIsNone(report["summary"]["peak_rss_bytes"])
            self.assertIsNone(report["input_digest"])
            self.assertNotIn("private-path", out.getvalue())

    def test_result_only_drift_retains_input_identity_and_is_classified_separately(self):
        result = {**successful(), "wall_ms": 10, "exit_code": 0}
        changed = {**result, "result_digest": "d" * 64}
        with patch.object(runner, "launch", side_effect=[result, changed]):
            report = runner.run_benchmark(samples=2, warmups=0)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["code"], "RESULT_CHANGED")
        self.assertEqual(report["input_digest"], "b" * 64)
        self.assertIsNone(report["summary"]["wall_ms_successful"])
        self.assertIsNone(report["summary"]["peak_rss_bytes"])

    def test_launch_io_failure_retains_completed_and_failed_attempts(self):
        for completed in (0, 1):
            result = {**successful(), "wall_ms": 10, "exit_code": 0}
            with self.subTest(completed=completed), patch.object(
                    runner, "launch", side_effect=[result] * completed + [OSError("private-path-not-for-output")]):
                report = runner.run_benchmark(samples=3, warmups=0)
            self.assertEqual(report["code"], "BENCHMARK_IO_FAILED")
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(len(report["attempts"]), completed + 1)
            self.assertEqual(report["attempts"][-1]["status"], "FAIL")
            self.assertGreaterEqual(report["attempts"][-1]["wall_ms"], 0)
            self.assertEqual(report["summary"]["wall_ms_all_samples"]["samples"], completed + 1)
            self.assertIsNone(report["summary"]["wall_ms_successful"])
            self.assertNotIn("private-path", json.dumps(report))

    def test_timeout_preserves_failed_duration_and_does_not_pad_samples(self):
        failed = {"status": "TIMEOUT", "code": "SAMPLE_TIMEOUT", "wall_ms": 12, "exit_code": None}
        with patch.object(runner, "launch", return_value=failed) as launch:
            report = runner.run_benchmark(samples=3, warmups=0)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["scope"]["samples_completed"], 1)
        self.assertEqual(report["scope"]["successful_samples"], 0)
        self.assertTrue(report["scope"]["aborted_early"])
        self.assertEqual(report["missing"]["rss"], "NO_SUCCESSFUL_SAMPLE")
        self.assertEqual(report["summary"]["wall_ms_all_samples"]["p95"], 12)
        self.assertIsNone(report["summary"]["wall_ms_successful"]["p95"])
        self.assertEqual(launch.call_count, 1)

    def test_code_or_input_drift_cannot_publish_a_successful_comparison(self):
        result = {**successful(), "wall_ms": 10, "exit_code": 0}
        with patch.object(runner, "code_snapshot", side_effect=[{"digest": "a" * 64}, {"digest": "d" * 64}]), \
             patch.object(runner, "launch", return_value=result):
            report = runner.run_benchmark(samples=1, warmups=0)
        self.assertEqual(report["code"], "CODE_OR_INPUT_CHANGED")
        self.assertIsNone(report["summary"]["wall_ms_successful"])
        changed = {**result, "input_digest": "d" * 64}
        with patch.object(runner, "launch", side_effect=[result, changed]):
            report = runner.run_benchmark(samples=2, warmups=0)
        self.assertEqual(report["status"], "FAIL")
        self.assertIsNone(report["input_digest"])

    def test_nonzero_child_and_oversized_output_are_not_accepted(self):
        def failed(command, **kwargs):
            kwargs["stdout"].write(json.dumps(successful()).encode())
            kwargs["stderr"].write(b"private-path-not-for-output")
            return subprocess.CompletedProcess(command, 1)
        with patch.object(runner.subprocess, "run", side_effect=failed):
            value = runner.launch(1, "a" * 64)
        self.assertEqual(value["status"], "FAIL")
        self.assertNotIn("private-path", json.dumps(value))
        def oversized(command, **kwargs):
            kwargs["stdout"].write(b"x" * (runner.MAX_RESULT_BYTES + 1))
            return subprocess.CompletedProcess(command, 0)
        with patch.object(runner.subprocess, "run", side_effect=oversized):
            self.assertEqual(runner.launch(1, "a" * 64)["code"], "WORKER_OUTPUT_LIMIT")

    def test_timeout_uses_only_fixed_owned_child_command(self):
        with patch.object(runner.subprocess, "run", side_effect=subprocess.TimeoutExpired("fixed", 1)) as run:
            value = runner.launch(1, "a" * 64)
        self.assertEqual(value["status"], "TIMEOUT")
        command = run.call_args.args[0]
        self.assertEqual(command, [sys.executable, "-B", str(ROOT / "runtime/performance_benchmark/worker.py")])
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_manifest_changes_for_runtime_code_and_contains_no_absolute_paths(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runner, "ROOT", Path(directory)):
            paths = ["tools/performance_benchmark.py", "tools/task_swarm_benchmark.py",
                     "requirements-ci.txt", "requirements-task-swarm-ci.txt",
                     "runtime/task_swarm/protocol.py", "runtime/performance_benchmark/worker.py"]
            for relative in paths:
                file = Path(directory) / relative; file.parent.mkdir(parents=True, exist_ok=True); file.write_text("first")
            before = runner.code_snapshot()
            (Path(directory) / paths[-1]).write_text("second")
            self.assertNotEqual(before["digest"], runner.code_snapshot()["digest"])
            self.assertNotIn(directory, json.dumps(before))

    def test_input_digest_uses_the_pages_actually_generated_for_the_fixture(self):
        profile = SimpleNamespace(name="short", pages=4, records_per_page=8, retained_messages=1000)
        generated = []
        def source(_):
            generated.append("generation-" + str(len(generated) + 1))
            return [generated[-1]]
        fake = SimpleNamespace(PROFILES=[profile], OBJECTIVE="fixed objective", sources=source)
        def report(_):
            fake.sources(profile)
            return {"profiles": [{"status": "PASS", "elapsed_seconds": 1}], "status": "PASS",
                    "model_called": False, "code_digest": "a" * 64, "sqlite_version": "test"}
        fake.report = report
        with patch.dict(sys.modules, task_swarm_benchmark=fake):
            result = worker.run()
        self.assertEqual(generated, ["generation-1"])
        self.assertIs(fake.sources, source)
        self.assertEqual(result["input_digest"], runner.digest({"fixture": "swarm-short",
                         "profile": {"name": "short", "pages": 4, "records_per_page": 8, "retained_messages": 1000},
                         "objective": "fixed objective", "pages": ["generation-1"]}))

    def test_real_cli_runs_fresh_local_fixtures_and_exposes_reproducibility(self):
        samples, warmups, attempt_timeout = 2, 1, 30
        outer_timeout = (samples + warmups) * attempt_timeout + 30
        result = subprocess.run([sys.executable, "-B", str(ROOT / "tools/performance_benchmark.py"),
                                 "--allow-local-fixture", "--samples", str(samples), "--warmups", str(warmups),
                                 "--timeout-seconds", str(attempt_timeout)],
                                cwd=ROOT, capture_output=True, text=True, timeout=outer_timeout)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        value = json.loads(result.stdout)
        self.assertEqual(value["status"], "PASS")
        self.assertEqual(value["scope"]["successful_samples"], 2)
        self.assertEqual(len(value["attempts"]), 3)
        self.assertEqual(len({r["input_digest"] for r in value["attempts"]}), 1)
        self.assertEqual(len({r["result_digest"] for r in value["attempts"]}), 1)
        self.assertFalse(value["model_called"])
        self.assertNotIn(str(ROOT), result.stdout)
        self.assertEqual(value["missing"]["knowledge"], "NOT_IMPLEMENTED")
        self.assertEqual(value["missing"]["voice"], "NOT_IMPLEMENTED")
        self.assertEqual(value["summary"]["wall_ms_successful"]["samples"], 2)
        if sys.platform in {"linux", "darwin"}:
            self.assertEqual(value["summary"]["peak_rss_bytes"]["samples"], 2)


if __name__ == "__main__":
    unittest.main()
