"""Bounded synthetic CLI measurements for #420; no provider or product logging.

Runs the existing real-CLI acceptance test twice: unchanged module entrypoint,
then a diagnostic entrypoint that times the real ReuseOwner constructor. The
latter imports main explicitly so both constructor call sites can be observed
without a process-wide profiler. All original assertions and 20s deadlines stay.
Only operation names, counts, durations and return codes are printed.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

PREFIX = "KOTODAMA_REUSE_MEASUREMENT "


def child(argv):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
    from task_swarm import learning_reuse
    original = learning_reuse.ReuseOwner.__init__
    measurements = []
    def event(value):
        print(PREFIX + json.dumps(value), file=sys.stderr, flush=True)

    def initialize(self, *args, **kwargs):
        caller = sys._getframe(1).f_code.co_name
        start = time.perf_counter()
        event({"constructor_start": caller})
        try:
            return original(self, *args, **kwargs)
        finally:
            measurement = {"caller": caller, "seconds": time.perf_counter() - start}
            measurements.append(measurement)
            event({"constructor_finish": measurement})

    learning_reuse.ReuseOwner.__init__ = initialize
    try:
        return learning_reuse.main(argv)
    finally:
        learning_reuse.ReuseOwner.__init__ = original
        print(PREFIX + json.dumps({"constructors": measurements}), file=sys.stderr, flush=True)


def measure():
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo / "tests"))
    from test_task_swarm_learning_reuse import test_cli_explicit_review_decision_run_and_anchor_replay
    original = subprocess.run
    script = str(Path(__file__).resolve())
    failed = False
    for mode in ("module", "constructor_probe"):
        observations = []

        def run(command, *args, **kwargs):
            if not isinstance(command, list) or "task_swarm.learning_reuse" not in command:
                return original(command, *args, **kwargs)
            index = command.index("task_swarm.learning_reuse")
            operation = command[index + 1]
            assert kwargs["timeout"] == 20
            if mode == "constructor_probe":
                command = [*command[:index - 1], script, "--child", *command[index + 1:]]
            started = time.perf_counter()
            try:
                result = original(command, *args, **kwargs)
            except subprocess.TimeoutExpired as exc:
                stderr = exc.stderr or b""
                if isinstance(stderr, bytes):
                    stderr = stderr.decode("utf-8", errors="replace")
                events = [json.loads(line[len(PREFIX):]) for line in stderr.splitlines()
                          if line.startswith(PREFIX)]
                print(PREFIX + json.dumps({"mode": mode, "operation": operation,
                    "outcome": "timeout", "timeout_seconds": kwargs["timeout"],
                    "wall_seconds": time.perf_counter() - started,
                    "constructor_events": events}), flush=True)
                raise
            record = {"operation": operation, "replay": "--receipt-sha256" in command,
                      "wall_seconds": time.perf_counter() - started, "returncode": result.returncode}
            if mode == "constructor_probe":
                lines = [line for line in result.stderr.splitlines() if line.startswith(PREFIX)]
                summaries = [json.loads(line[len(PREFIX):]) for line in lines]
                summaries = [item for item in summaries if "constructors" in item]
                assert len(summaries) == 1
                record.update(summaries[0])
            observations.append(record)
            print(PREFIX + json.dumps({"mode": mode, **record}), flush=True)
            return result

        subprocess.run = run
        try:
            with tempfile.TemporaryDirectory(prefix="kotodama-reuse-measure-") as directory:
                test_cli_explicit_review_decision_run_and_anchor_replay(Path(directory))
            assert len(observations) == 6
        except (subprocess.TimeoutExpired, AssertionError) as exc:
            failed = True
            print(PREFIX + json.dumps({"mode": mode, "result": "FAIL",
                                      "error_type": type(exc).__name__}), flush=True)
        finally:
            subprocess.run = original
    print(PREFIX + json.dumps({"result": "FAIL" if failed else "PASS", "platform": sys.platform,
                              "python": sys.version.split()[0]}), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--child"]:
        raise SystemExit(child(sys.argv[2:]))
    if sys.argv[1:]:
        raise SystemExit("usage: measure_learning_reuse_cli.py")
    raise SystemExit(measure())
