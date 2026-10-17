"""Reproducible real-bundle comparison in one finite CLI loop."""
from __future__ import annotations

import ast
import contextlib
import hashlib
import json
import math
from pathlib import Path
import resource
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from kotodama_kb import foundation, session

# Public baseline: only its byte-verified original capture function is extracted.
BASE = "a3fe774bb44f604b1591fe3577b836c44b92229b"
SAMPLES = 30
AS_OF = "2026-10-10T00:00:00Z"
CASES = [
    ("query_latin", ["query", "context"]),
    ("query_japanese", ["query", "言霊"]),
    ("query_short", ["query", "目的"]),
    ("query_goal", ["query", "KGI", "--goal", "OUT-INTENT"]),
    ("show_section", ["show", "project/goal", "--section", "Required properties", "--max-chars", "600"]),
    ("show_chunk", ["show", "project/goal", "--max-chars", "600"]),
]


def percentile(values, fraction):
    return sorted(values)[math.ceil(len(values) * fraction) - 1]


def baseline_capture():
    raw = subprocess.run(["git", "show", BASE + ":tools/kotodama_kb/foundation.py"],
                         cwd=ROOT, check=True, capture_output=True, text=True, timeout=10).stdout
    node = next(item for item in ast.parse(raw).body if isinstance(item, ast.FunctionDef)
                and item.name == "_capture_inputs")
    node.name = "_benchmark_original_capture"
    tree = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    # Same globals/read/check functions. Only the original path arithmetic differs.
    exec(compile(tree, "<pinned-baseline-capture>", "exec"), foundation.__dict__)
    result = foundation._benchmark_original_capture
    del foundation._benchmark_original_capture
    return result


def main():
    baseline, candidate, read = baseline_capture(), foundation._capture_inputs, foundation._read_bytes
    # Independent untimed inventory: both arms must match the same admitted bytes.
    fixture = session.cli.load_bundle(ROOT, as_of=session.cli._parse_as_of(AS_OF))
    session.cli._require_valid_bundle(fixture)
    fixture_bytes = 0
    for relative, digest in fixture.input_bindings:
        raw = read(ROOT / relative)
        assert hashlib.sha256(raw).hexdigest() == digest
        fixture_bytes += len(raw)
    foundation._assert_current(fixture)
    fixture_info = {"concepts": len(fixture.concepts), "files": len(fixture.input_bindings),
                    "bytes": fixture_bytes, "source_digest": fixture.source_digest}
    active = {"engine": "baseline", "counts": {}}
    outputs = []

    def capture(*args, **kwargs):
        active["counts"]["guards"] += 1
        return (baseline if active["engine"] == "baseline" else candidate)(*args, **kwargs)

    def counted_read(path):
        value = read(path)
        active["counts"]["reads"] += 1
        active["counts"]["bytes"] += len(value)
        return value

    for name, args in CASES:
        rows = {"baseline": [], "candidate": []}
        order = ["baseline", "candidate"]  # startup is separately discarded
        for iteration in range(SAMPLES):
            order.extend(["baseline", "candidate"] if iteration % 2 == 0 else ["candidate", "baseline"])
        request = json.dumps({"id": name, "args": [*args, "--as-of", AS_OF]}).encode() + b"\n"

        class Source:
            position = 0
            def readline(self, limit):
                if self.position >= len(order):
                    return b""
                active["engine"] = order[self.position]
                active["counts"] = {"guards": 0, "reads": 0, "bytes": 0}
                active["sample"] = self.position >= 2
                self.position += 1
                active["wall"] = time.perf_counter_ns()
                active["cpu"] = time.process_time_ns()
                assert len(request) <= limit
                return request

        class Sink:
            def write(self, frame):
                wall = (time.perf_counter_ns() - active["wall"]) / 1e6
                cpu = (time.process_time_ns() - active["cpu"]) / 1e6
                response = json.loads(frame)
                assert response["ok"], response
                if active["sample"]:
                    rows[active["engine"]].append({"wall_ms": wall, "cpu_ms": cpu,
                         "fingerprint": hashlib.sha256(frame).hexdigest(), **active["counts"]})
                return len(frame)
            def flush(self):
                pass

        with mock.patch.object(foundation, "_capture_inputs", capture), \
             mock.patch.object(foundation, "_read_bytes", counted_read), \
             mock.patch.object(sys, "stdin", SimpleNamespace(buffer=Source())), \
             mock.patch.object(sys, "stdout", SimpleNamespace(buffer=Sink())):
            code = session.main(["--root", str(ROOT), "--max-requests", str(len(order))])
        assert code == 0
        expected_guards = 3 if args[0] == "query" else 4
        expected_reads = expected_guards * fixture_info["files"]
        expected_bytes = expected_guards * fixture_info["bytes"]
        assert all(len(row) == SAMPLES for row in rows.values())
        assert len({row["fingerprint"] for group in rows.values() for row in group}) == 1
        assert {(row["guards"], row["reads"], row["bytes"]) for group in rows.values() for row in group} == {
            (expected_guards, expected_reads, expected_bytes)}
        summary = {engine: {metric: {"p50": percentile([row[metric] for row in group], .50),
                                     "p95": percentile([row[metric] for row in group], .95)}
                            for metric in ("wall_ms", "cpu_ms")} for engine, group in rows.items()}
        ratios = {metric: {q: summary["candidate"][metric][q] / summary["baseline"][metric][q]
                           for q in ("p50", "p95")} for metric in ("wall_ms", "cpu_ms")}
        accepted = all(value <= .90 for value in ratios["wall_ms"].values()) and ratios["cpu_ms"]["p50"] <= .90
        outputs.append({"case": name, "args": args, "summary": summary, "candidate_over_baseline": ratios,
                        "quality_equal": True, "source_guards_reads_bytes": [expected_guards, expected_reads, expected_bytes],
                        "acceptance_passed": accepted, "raw": rows})
    foundation._assert_current(fixture)  # Outside timing; refuse a changed experiment corpus.
    print(json.dumps({"base": BASE, "python": sys.version, "samples_per_engine_class": SAMPLES,
          "clock": "nearest-rank p50/p95; wall perf_counter and CPU process_time",
          "boundary": f"same process, unchanged session.main JSONL path, finite {2 + 2 * SAMPLES} requests per session; IPC excluded; shared host",
          "scope": "current admitted fixture shared by both arms; no cap/byte/structural check changes",
          "fixture": fixture_info, "inventory_timing": "before all warmups; excluded from samples",
          "threshold_fixed_before_run": "each class wall p50/p95 >=10% reduction and CPU p50 >=10%; parity and all guards required",
          "accepted": all(row["acceptance_passed"] for row in outputs), "cases": outputs,
          "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
