"""Fresh-process timings with bounded samples and immutable code inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
MAX_RESULT_BYTES = 65536
VERSION = "kotodama.performance-benchmark.v1"


class BenchmarkError(Exception):
    pass


def digest(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def code_snapshot():
    paths = [ROOT / "tools/performance_benchmark.py", ROOT / "tools/task_swarm_benchmark.py",
             ROOT / "requirements-ci.txt", ROOT / "requirements-task-swarm-ci.txt"]
    paths += sorted((ROOT / "runtime/task_swarm").glob("*.py"))
    paths += sorted((ROOT / "runtime/performance_benchmark").glob("*.py"))
    manifest = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in paths}
    return {"digest": digest(manifest), "files": manifest}


def distribution(values):
    if not values:
        return {"samples": 0, "min": None, "p50": None, "p95": None, "max": None}
    ordered = sorted(values)
    return {"samples": len(ordered), "min": ordered[0],
            "p50": ordered[math.ceil(len(ordered) * .5) - 1],
            "p95": ordered[math.ceil(len(ordered) * .95) - 1], "max": ordered[-1]}


def _valid_digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _worker_result(raw, returncode, pinned):
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise BenchmarkError("WORKER_OUTPUT_INVALID") from None
    if not isinstance(value, dict) or value.get("schema") != VERSION:
        raise BenchmarkError("WORKER_OUTPUT_INVALID")
    if returncode != 0 or value.get("status") != "PASS":
        code = value.get("code")
        allowed = {"DEPENDENCIES_UNAVAILABLE", "FIXTURE_FAILED", "CODE_CHANGED_DURING_RUN"}
        return {"status": "REFUSED" if code == "DEPENDENCIES_UNAVAILABLE" else "FAIL",
                "code": code if code in allowed else "WORKER_FAILED"}
    if (value.get("code_digest") != pinned or value.get("fixture") != "swarm-short"
            or value.get("model_called") is not False
            or not _valid_digest(value.get("input_digest"))
            or not _valid_digest(value.get("result_digest"))):
        raise BenchmarkError("WORKER_BINDING_INVALID")
    rss = value.get("peak_rss_bytes")
    if rss is not None and (type(rss) is not int or rss <= 0):
        raise BenchmarkError("WORKER_OUTPUT_INVALID")
    rss_missing = value.get("peak_rss_missing")
    if ((rss is None and rss_missing not in {"UNSUPPORTED_PLATFORM", "COUNTER_UNAVAILABLE"})
            or (rss is not None and rss_missing is not None)):
        raise BenchmarkError("WORKER_OUTPUT_INVALID")
    expected = value.get("verification")
    if (not isinstance(expected, dict) or expected.get("status") != "PASS"
            or expected.get("profile") != "short" or expected.get("records") != 32
            or not all(expected.get(key) is True for key in
                       ("fidelity_verified", "restart_replay_verified", "source_drift_verified", "backpressure_verified"))):
        raise BenchmarkError("FIXTURE_VERIFICATION_MISSING")
    return value


def launch(timeout_seconds, pinned):
    started = time.perf_counter()
    # Spool both streams: errors never echo raw child output or local paths.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            completed = subprocess.run(
                [sys.executable, "-B", str(ROOT / "runtime/performance_benchmark/worker.py")],
                cwd=ROOT, stdout=stdout, stderr=stderr, timeout=timeout_seconds, check=False)
        except subprocess.TimeoutExpired:
            return {"status": "TIMEOUT", "code": "SAMPLE_TIMEOUT", "exit_code": None,
                    "wall_ms": (time.perf_counter() - started) * 1000}
        wall_ms = (time.perf_counter() - started) * 1000
        stdout.seek(0)
        raw = stdout.read(MAX_RESULT_BYTES + 1)
        if len(raw) > MAX_RESULT_BYTES:
            value = {"status": "FAIL", "code": "WORKER_OUTPUT_LIMIT"}
        else:
            try:
                value = _worker_result(raw, completed.returncode, pinned)
            except BenchmarkError as exc:
                value = {"status": "FAIL", "code": str(exc)}
        return {**value, "exit_code": completed.returncode, "wall_ms": wall_ms}


def run_benchmark(*, samples=5, warmups=1, timeout_seconds=30):
    if (type(samples) is not int or not 1 <= samples <= 20 or type(warmups) is not int
            or not 0 <= warmups <= 3 or type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 120):
        raise BenchmarkError("CONFIG_INVALID")
    code = code_snapshot()
    config = {"fixture": "swarm-short", "samples": samples, "warmups": warmups,
              "timeout_seconds": timeout_seconds, "execution": "fresh-python-process",
              "wall_scope": "spawn-through-child-exit", "percentiles": "nearest-rank"}
    attempts = []
    mismatch = False
    for number in range(samples + warmups):
        result = launch(timeout_seconds, code["digest"])
        attempts.append({"attempt": number + 1, "phase": "warmup" if number < warmups else "sample", **result})
        if code_snapshot() != code:
            mismatch = True
            break
        if result["status"] != "PASS":
            break
    successful = [row for row in attempts if row["status"] == "PASS"]
    if len({row["input_digest"] for row in successful}) > 1 or len({row["result_digest"] for row in successful}) > 1:
        mismatch = True
    measured = [row for row in successful if row["phase"] == "sample"]
    complete = not mismatch and len(attempts) == samples + warmups and len(measured) == samples
    all_measured = [row for row in attempts if row["phase"] == "sample"]
    rss_reasons = {}
    for row in measured:
        if row.get("peak_rss_bytes") is None:
            reason = row["peak_rss_missing"]
            rss_reasons[reason] = rss_reasons.get(reason, 0) + 1
    rss_missing_count = sum(rss_reasons.values())
    rss_status = None
    if not measured:
        rss_status = "NO_SUCCESSFUL_SAMPLE"
    elif rss_missing_count < len(measured) and rss_missing_count:
        rss_status = "PARTIALLY_MISSING"
    elif rss_missing_count:
        rss_status = next(iter(rss_reasons)) if len(rss_reasons) == 1 else "MULTIPLE_REASONS"
    missing = {"rss": rss_status,
               "pss": "NOT_MEASURED", "heap": "NOT_MEASURED", "event_loop_lag": "NOT_MEASURED",
               "cpu_time": "NOT_MEASURED", "knowledge": "NOT_IMPLEMENTED", "voice": "NOT_IMPLEMENTED",
               "provider_model_quality": "NOT_MEASURED"}
    return {"schema": VERSION, "status": "PASS" if complete else "FAIL",
            "code": "CODE_OR_INPUT_CHANGED" if mismatch else None,
            "gate_ceiling": "LOCAL_PASS", "synthetic": True, "model_called": False,
            "config": config, "config_digest": digest(config), "code_snapshot": code,
            "input_digest": successful[0]["input_digest"] if successful and not mismatch else None,
            "environment": {"python": platform.python_version(), "system": platform.system(),
                            "machine": platform.machine(), "logical_cpu_count": os.cpu_count(),
                            "sqlite": successful[0].get("sqlite_version") if successful else None,
                            "dependency_versions": successful[0].get("dependency_versions") if successful else None},
            "scope": {"includes": ["python-startup", "fixture-generation", "sqlite-history", "peer-delivery",
                                   "scheduler", "independent-reference-verification", "cleanup"],
                      "excludes": ["model-reasoning", "live-provider", "deployment", "parent-rss", "cold-os-cache"],
                      "warmups": "discarded fresh processes; OS cache may remain warm",
                      "peak_rss": "child self high-water after fixture/validation; before final JSON encoding and exit; excludes parent",
                      "samples_requested": samples, "samples_completed": len(all_measured),
                      "successful_samples": len(measured), "aborted_early": len(attempts) < samples + warmups,
                      "rss_samples": {"available": len(measured) - rss_missing_count,
                                      "missing": rss_missing_count, "missing_reasons": rss_reasons}},
            "summary": {"wall_ms_all_samples": distribution([row["wall_ms"] for row in all_measured]),
                        "wall_ms_successful": distribution([row["wall_ms"] for row in measured]) if not mismatch else None,
                        "peak_rss_bytes": distribution([row["peak_rss_bytes"] for row in measured
                                                         if row.get("peak_rss_bytes") is not None]) if not mismatch else None},
            "missing": missing, "attempts": attempts}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise BenchmarkError("ARGUMENTS_INVALID")


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument("--allow-local-fixture", action="store_true")
    parser.add_argument("--fixture", choices=["swarm-short"], default="swarm-short")
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    try:
        args = parser.parse_args(argv)
        if not args.allow_local_fixture:
            raise BenchmarkError("LOCAL_FIXTURE_REQUIRED")
        report = run_benchmark(samples=args.samples, warmups=args.warmups, timeout_seconds=args.timeout_seconds)
        print(json.dumps(report, sort_keys=True, ensure_ascii=False, allow_nan=False))
        return 0 if report["status"] == "PASS" else 1
    except (BenchmarkError, OSError) as exc:
        code = str(exc) if isinstance(exc, BenchmarkError) else "BENCHMARK_IO_FAILED"
        print(json.dumps({"schema": VERSION, "status": "REFUSED", "code": code}))
        return 2
