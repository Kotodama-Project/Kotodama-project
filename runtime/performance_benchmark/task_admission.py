"""Observe one fixed Node scheduler invocation from outside its process."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from .runner import BenchmarkError, VERSION, digest, distribution

ROOT = Path(__file__).resolve().parents[2]
MAX_OUTPUT_BYTES = 65536
COUNT = 16
ITERATIONS = 262144
WAIT_MS = 40
FLAGS = ("overflow_refused", "cancel_retains_slot_until_settlement", "writer_barrier",
         "all_tasks_settled", "queue_drained", "concurrency_bound")


def code_snapshot():
    paths = ("tools/performance_benchmark.py", "runtime/performance_benchmark/runner.py",
             "runtime/performance_benchmark/task_admission.py", "runtime/performance_benchmark/task_admission.mjs",
             "runtime/discord-template/src/task-admission.mjs", "runtime/discord-template/src/common.mjs")
    files = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in paths}
    return {"digest": digest(files), "files": files}


def quantiles(values):
    result = distribution(values)
    result["p99"] = sorted(values)[math.ceil(len(values) * .99) - 1] if values else None
    return result


def reference_value(index, workload):
    # Independent O(log N) affine composition, not the target's iterative loop.
    value, multiplier, increment, count = index + 1, 1664525, 1013904223, ITERATIONS
    if workload == "wait":
        return value
    while count:
        if count & 1:
            value = (value * multiplier + increment) & 0xffffffff
        increment = (increment * (multiplier + 1)) & 0xffffffff
        multiplier = (multiplier * multiplier) & 0xffffffff
        count >>= 1
    return value


def _number(value):
    return type(value) in (float, int) and math.isfinite(value) and value >= 0


def validate_result(raw, width, workload):
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError):
        raise BenchmarkError("WORKER_OUTPUT_INVALID") from None
    if (not isinstance(result, dict) or result.get("schema") != "kotodama.task-admission-fixture.v1"
            or result.get("status") != "PASS" or result.get("width") != width
            or result.get("workload") != workload or result.get("tasks") != COUNT
            or result.get("iterations") != ITERATIONS or result.get("wait_ms") != WAIT_MS
            or result.get("initial_queued") != COUNT - width
            or type(result.get("peak_active")) is not int or not 1 <= result["peak_active"] <= width
            or not _number(result.get("workload_wall_ms")) or result["workload_wall_ms"] <= 0
            or not isinstance(result.get("node"), str) or not result["node"].startswith("v")):
        raise BenchmarkError("FIXTURE_BINDING_INVALID")
    if any(type(result.get(key)) is not int for key in ("width", "tasks", "iterations", "wait_ms", "initial_queued")):
        raise BenchmarkError("FIXTURE_BINDING_INVALID")
    verification = result.get("verification")
    if not isinstance(verification, dict) or any(verification.get(key) is not True for key in FLAGS):
        raise BenchmarkError("FIXTURE_VERIFICATION_MISSING")
    rows = result.get("rows")
    if not isinstance(rows, list) or len(rows) != COUNT:
        raise BenchmarkError("FIXTURE_RESULT_INVALID")
    for index, row in enumerate(rows):
        if (not isinstance(row, dict) or type(row.get("index")) is not int or row["index"] != index
                or type(row.get("value")) is not int or row["value"] != reference_value(index, workload)
                or any(not _number(row.get(key)) for key in ("queue_wait_ms", "execution_ms", "completion_ms"))
                or not math.isclose(row["queue_wait_ms"] + row["execution_ms"], row["completion_ms"], abs_tol=1e-6)
                or row["completion_ms"] > result["workload_wall_ms"]):
            raise BenchmarkError("FIXTURE_RESULT_INVALID")
    return result


def _observe(command, timeout_seconds):
    """Linux wait4 accounts for startup, final serialization, and process exit.

    The fixed fixture does not spawn children: aggregate target RSS is this one
    Node process. This is not the observer's RSS or a general process-tree tool.
    """
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        started = time.perf_counter()
        process = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr, start_new_session=True)
        timed_out = False
        try:
            deadline = started + timeout_seconds
            while True:
                pid, status, usage = os.wait4(process.pid, os.WNOHANG)
                if pid:
                    process.returncode = os.waitstatus_to_exitcode(status)
                    break
                now = time.perf_counter()
                if now >= deadline:
                    timed_out = True
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    _, status, usage = os.wait4(process.pid, 0)
                    process.returncode = os.waitstatus_to_exitcode(status)
                    break
                time.sleep(min(.005, max(0, deadline - now)))
        finally:
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
        elapsed = (time.perf_counter() - started) * 1000
        rss = usage.ru_maxrss * 1024
        cpu = usage.ru_utime + usage.ru_stime
        rss_ok = type(rss) is int and rss > 0
        cpu_ok = _number(cpu)
        metrics = {"wall_ms": elapsed, "exit_code": process.returncode,
                   "peak_rss_bytes": rss if rss_ok else None,
                   "peak_rss_missing": None if rss_ok else "COUNTER_UNAVAILABLE",
                   "cpu_seconds": cpu if cpu_ok else None,
                   "cpu_missing": None if cpu_ok else "COUNTER_UNAVAILABLE",
                   "owned_process_reaped": True}
        stdout.seek(0)
        raw = stdout.read(MAX_OUTPUT_BYTES + 1)
        if timed_out:
            return {**metrics, "status": "TIMEOUT", "code": "SAMPLE_TIMEOUT"}, None
        if len(raw) > MAX_OUTPUT_BYTES:
            return {**metrics, "status": "FAIL", "code": "WORKER_OUTPUT_LIMIT"}, None
        if process.returncode != 0:
            return {**metrics, "status": "FAIL", "code": "WORKER_FAILED"}, None
        return {**metrics, "status": "PASS", "code": None}, raw


def launch(node, width, workload, timeout_seconds):
    metrics, raw = _observe([node, str(ROOT / "runtime/performance_benchmark/task_admission.mjs"),
                             str(width), workload], timeout_seconds)
    if raw is None:
        return metrics
    try:
        result = validate_result(raw, width, workload)
    except BenchmarkError as exc:
        return {**metrics, "status": "FAIL", "code": str(exc)}
    inputs = {"tasks": COUNT, "iterations": ITERATIONS, "wait_ms": WAIT_MS, "workload": workload,
              "task_indices": list(range(COUNT)), "actor_room_policy": "one distinct actor and room per task"}
    values = [{"index": row["index"], "value": row["value"]} for row in result["rows"]]
    return {**metrics, "node": result["node"], "input_digest": digest(inputs),
            "result_digest": digest(values), "verification": result["verification"],
            "rows": result["rows"], "initial_queued": result["initial_queued"],
            "peak_active": result["peak_active"], "workload_wall_ms": result["workload_wall_ms"],
            "throughput_tasks_per_second": COUNT * 1000 / result["workload_wall_ms"],
            "queue_wait_ms": quantiles([row["queue_wait_ms"] for row in result["rows"]]),
            "execution_ms": quantiles([row["execution_ms"] for row in result["rows"]]),
            "completion_ms": quantiles([row["completion_ms"] for row in result["rows"]])}


def run_benchmark(*, samples=5, warmups=1, timeout_seconds=30, width=1, workload="wait"):
    if (type(samples) is not int or not 1 <= samples <= 20 or type(warmups) is not int
            or not 0 <= warmups <= 3 or type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 120
            or type(width) is not int or width not in (1, 2, 4) or workload not in ("wait", "cpu")):
        raise BenchmarkError("CONFIG_INVALID")
    if sys.platform != "linux" or not hasattr(os, "wait4"):
        raise BenchmarkError("PLATFORM_UNSUPPORTED")
    node = shutil.which("node")
    if node is None:
        raise BenchmarkError("NODE_UNAVAILABLE")
    code = code_snapshot()
    config = {"fixture": "task-admission", "samples": samples, "warmups": warmups,
              "timeout_seconds": timeout_seconds, "width": width, "workload": workload,
              "execution": "fresh-node-process", "percentiles": "nearest-rank"}
    attempts, failure = [], None
    for index in range(samples + warmups):
        started = time.perf_counter()
        try:
            result = launch(node, width, workload, timeout_seconds)
        except OSError:
            result = {"status": "FAIL", "code": "BENCHMARK_IO_FAILED", "exit_code": None,
                      "wall_ms": (time.perf_counter() - started) * 1000}
        attempts.append({"attempt": index + 1, "phase": "warmup" if index < warmups else "sample", **result})
        if result["status"] != "PASS":
            failure = result["code"]
            break
        try:
            if code_snapshot() != code:
                failure = "CODE_CHANGED_DURING_RUN"
        except OSError:
            failure = "BENCHMARK_IO_FAILED"
        if failure:
            break
    successful = [row for row in attempts if row["status"] == "PASS"]
    if any(len({row[key] for row in successful}) > 1 for key in ("input_digest", "result_digest", "node")):
        failure = "INPUT_RESULT_OR_RUNTIME_CHANGED"
    measured = [row for row in successful if row["phase"] == "sample"]
    all_measured = [row for row in attempts if row["phase"] == "sample"]
    complete = not failure and len(attempts) == samples + warmups and len(measured) == samples
    missing = {}
    for name, key in (("rss", "peak_rss_bytes"), ("cpu", "cpu_seconds")):
        absent = sum(row.get(key) is None for row in measured)
        missing[name] = ("NO_SUCCESSFUL_SAMPLE" if not measured else "COUNTER_UNAVAILABLE"
                         if absent == len(measured) else "PARTIALLY_MISSING" if absent else None)
        missing[name + "_samples"] = absent
    return {"schema": VERSION, "status": "PASS" if complete else "FAIL", "code": failure,
            "gate_ceiling": "LOCAL_PASS", "qualification": "NOT_EVALUATED", "synthetic": True,
            "model_called": False, "config": config, "config_digest": digest(config), "code_snapshot": code,
            "input_digest": successful[0]["input_digest"] if successful and not failure else None,
            "environment": {"python": platform.python_version(), "system": platform.system(),
                            "machine": platform.machine(), "logical_cpu_count": os.cpu_count(),
                            "node": successful[0]["node"] if successful else None},
            "scope": {"target_processes": 1, "wall": "spawn through Node exit and reap; includes observer poll delay",
                      "cpu": "wait4 user plus system CPU for the complete fixed Node invocation",
                      "peak_rss": "Linux wait4 whole-lifetime high-water RSS of one Node target; no target children",
                      "includes": ["node-startup", "scheduler-import", "mechanism-checks", "16-task-workload",
                                   "queue-drain", "result-serialization", "node-exit"],
                      "excludes": ["python-observer-resources", "source-preflight", "parent-report-aggregation",
                                   "pipeline-owner-store", "provider", "model", "cold-os-cache"],
                      "cpu_workload": "synchronous fixed work on one event loop; width does not add CPU workers",
                      "warmups": "discarded fresh processes; OS cache may remain warm",
                      "samples_requested": samples, "samples_completed": len(all_measured),
                      "successful_samples": len(measured), "aborted_early": len(attempts) < samples + warmups},
            "summary": {"wall_ms_all_samples": quantiles([row["wall_ms"] for row in all_measured]),
                        **{key: quantiles([row[key] for row in measured if row.get(key) is not None]) if not failure else None
                           for key in ("wall_ms", "peak_rss_bytes", "cpu_seconds", "workload_wall_ms",
                                       "throughput_tasks_per_second")}},
            "missing": {**missing,
                        "pss": "NOT_MEASURED", "event_loop_lag": "NOT_MEASURED",
                        "observer_overhead": "NOT_MEASURED", "quiet_environment": "NOT_VERIFIED"},
            "attempts": attempts}
