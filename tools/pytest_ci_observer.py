"""Bounded pytest event evidence; no scheduler, signal handler or outcome rewrite.

Load explicitly with PYTEST_PLUGINS=tools.pytest_ci_observer. Verify with
``python -B tools/pytest_ci_observer.py DIRECTORY`` after pytest succeeds.
"""
from __future__ import annotations

from contextlib import nullcontext
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import uuid

import pytest

MAX_BYTES = 16 * 1024 * 1024
MAX_RECORD = 64 * 1024
MAX_EVENTS = 20000
FINAL_BYTES = 8192
PREFIX = "KOTODAMA_PYTEST_EVENT "


def encoded(value):
    return (json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n").encode()


class Observer:
    def __init__(self, config):
        self.config = config
        self.started = time.perf_counter()
        self.hook_seconds = 0.0
        self.limit = int(os.environ.get("KOTODAMA_CI_OBSERVATION_MAX_BYTES", MAX_BYTES))
        if not 512 <= self.limit <= MAX_BYTES:
            raise pytest.UsageError("observation byte limit must be between 512 and 16777216")
        self.directory = Path(os.environ["KOTODAMA_CI_OBSERVATION_DIR"])
        self.directory.mkdir(parents=True, exist_ok=False)
        self.stream = (self.directory / "events.jsonl").open("xb", buffering=0)
        self.bytes = self.console_bytes = self.sequence = 0
        self.sha = hashlib.sha256()
        self.error = None
        self.collection_done = False
        self.collected = self.started_tests = self.finished_tests = self.subtests = 0
        self.current = None
        self.identifier = uuid.uuid4().hex
        root = Path(__file__).resolve().parents[1]
        def revision(ref):
            return subprocess.check_output(["git", "rev-parse", ref], cwd=root, timeout=5, text=True).strip()
        versions = {}
        for name in ("pytest", "pluggy", "mcp", "psutil"):
            try:
                versions[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                versions[name] = None
        self.emit("session_start", source={
            "checkout_sha": revision("HEAD"), "checkout_tree": revision("HEAD^{tree}"),
            "lock_sha256": hashlib.sha256((root / "requirements-task-swarm-ci.txt").read_bytes()).hexdigest(),
            "observer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }, run={name: os.environ.get(name) for name in (
            "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB", "GITHUB_WORKFLOW",
            "GITHUB_SHA", "KOTODAMA_CI_HEAD_SHA", "RUNNER_OS", "RUNNER_ARCH", "ImageOS", "ImageVersion",
        )}, environment={
            "python": platform.python_version(), "implementation": platform.python_implementation(),
            "system": platform.system(), "release": platform.release(), "machine": platform.machine(),
            "packages": versions,
        }, selection={"python_files": config.getini("python_files"), "collect_only": config.option.collectonly},
            limits={"stream_bytes": self.limit, "console_bytes": self.limit,
                    "record_bytes": MAX_RECORD, "events": MAX_EVENTS, "final_bytes": FINAL_BYTES},
            unknown={"cpu_seconds": None, "peak_rss_bytes": None, "queue_seconds": None,
                     "whole_process_observer_overhead_seconds": None},
            subtest_identity="pytest-rendered message/parameters plus ordered occurrence; no semantic canonicalization")
        self.hook_seconds = time.perf_counter() - self.started

    def emit(self, kind, **fields):
        begin = time.perf_counter()
        try:
            if self.error:
                return
            data = encoded({"version": 1, "observation_id": self.identifier, "sequence": self.sequence,
                            "elapsed_seconds": time.perf_counter() - self.started, "kind": kind, **fields})
            console = b"\n" + PREFIX.encode() + data
            if len(data) > MAX_RECORD or self.sequence >= MAX_EVENTS or self.console_bytes + len(console) > self.limit:
                self.error = "capacity_exceeded"
                return
            if self.stream.write(data) != len(data):
                raise OSError("short observation write")
            self.sha.update(data)
            self.bytes += len(data)
            self.sequence += 1
            self.console_bytes += len(console)
            capture = self.config.pluginmanager.get_plugin("capturemanager")
            with capture.global_and_fixture_disabled() if capture else nullcontext():
                sys.stdout.write(console.decode())
                sys.stdout.flush()
        except (OSError, ValueError, TypeError):
            # Do not rewrite pytest's result or stop remaining tests. The separate
            # success-only verifier refuses absent/incomplete evidence.
            self.error = "observation_write_or_encoding_failed"
        finally:
            self.hook_seconds += time.perf_counter() - begin

    def pytest_collectreport(self, report):
        reason = report.longrepr[2] if report.skipped and isinstance(report.longrepr, tuple) else None
        self.emit("collector", nodeid=report.nodeid, outcome=report.outcome, skip_reason=reason)

    def pytest_collection_finish(self, session):
        for index, item in enumerate(session.items):
            self.emit("collected", occurrence=index, nodeid=item.nodeid)
        self.collected = len(session.items)
        self.collection_done = True
        self.emit("collection_finish", count=self.collected)

    def pytest_runtest_logstart(self, nodeid, location):
        self.current = self.started_tests
        self.started_tests += 1
        self.emit("test_start", occurrence=self.current, nodeid=nodeid)

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_runtest_setup(self, item):
        self.emit("phase_start", occurrence=self.current, nodeid=item.nodeid, when="setup")
        return (yield)

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_runtest_call(self, item):
        self.emit("phase_start", occurrence=self.current, nodeid=item.nodeid, when="call")
        return (yield)

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_runtest_teardown(self, item):
        self.emit("phase_start", occurrence=self.current, nodeid=item.nodeid, when="teardown")
        return (yield)

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_runtest_logreport(self, report):
        result = yield
        context = getattr(report, "context", None)
        fields = {"occurrence": self.current, "nodeid": report.nodeid, "when": report.when,
                  "outcome": report.outcome, "duration_seconds": report.duration,
                  "start": report.start, "stop": report.stop,
                  "wasxfail": getattr(report, "wasxfail", None),
                  "skip_reason": report.longrepr[2] if report.skipped and isinstance(report.longrepr, tuple) else None}
        if context is not None:
            fields["subtest"] = {"occurrence": self.subtests, "message": context.msg, "parameters": dict(context.kwargs)}
            self.subtests += 1
        self.emit("subtest" if context is not None else "phase", **fields)
        return result

    def pytest_runtest_logfinish(self, nodeid, location):
        self.finished_tests += 1
        self.emit("test_finish", occurrence=self.current, nodeid=nodeid)

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_sessionfinish(self, session, exitstatus):
        result = yield
        self.emit("session_finish", pytest_exit_code=int(session.exitstatus))
        reason = self.error
        if reason is None and (not self.collection_done or self.config.option.collectonly):
            reason = "no_execution_inventory"
        if reason is None and (self.collected != self.started_tests or self.collected != self.finished_tests
                               or int(session.exitstatus) not in (0, 1)):
            reason = "execution_incomplete"
        final = {"version": 1, "observation_id": self.identifier,
                 "complete": reason is None, "incomplete_reason": reason,
                 "pytest_exit_code": int(session.exitstatus), "collected": self.collected,
                 "started": self.started_tests, "finished": self.finished_tests, "subtests": self.subtests,
                 "events": self.sequence, "stream_bytes": self.bytes, "console_bytes": self.console_bytes,
                 "events_sha256": self.sha.hexdigest(), "elapsed_seconds": time.perf_counter() - self.started,
                 "observer_hook_seconds_before_final_write": self.hook_seconds,
                 "overhead_scope": "metadata plus event serialization/write/flush hooks; excludes import, final write, verification, upload and test perturbation"}
        try:
            data = encoded(final)
            if len(data) > FINAL_BYTES:
                raise ValueError("final observation too large")
            staged = self.directory / "final.partial.json"
            staged.write_bytes(data)
            staged.replace(self.directory / "final.json")
        except (OSError, ValueError):
            pass  # Missing final is never complete; preserve pytest's exit code.
        return result

    def pytest_unconfigure(self, config):
        self.stream.close()


def pytest_configure(config):
    if "KOTODAMA_CI_OBSERVATION_DIR" not in os.environ:
        raise pytest.UsageError("KOTODAMA_CI_OBSERVATION_DIR is required for the explicit observer")
    config.pluginmanager.register(Observer(config), "kotodama-ci-observer")


def verify(directory):
    """Validate the reported execution inventory, not just a matching checksum."""
    import math

    directory = Path(directory)
    final_path, events_path = directory / "final.json", directory / "events.jsonl"
    if final_path.stat().st_size > FINAL_BYTES or events_path.stat().st_size > MAX_BYTES:
        raise ValueError("evidence exceeds capacity")
    final = json.loads(final_path.read_bytes())
    if (final.get("complete") is not True or final.get("incomplete_reason") is not None
            or type(final.get("version")) is not int or final["version"] != 1
            or type(final.get("pytest_exit_code")) is not int or final["pytest_exit_code"] not in (0, 1)):
        raise ValueError("observation is incomplete")
    expected, started, finished = [], [], []
    subtests = count = size = 0
    collected = ended = failed = False
    current = active = last = None
    phases = {}
    sha = hashlib.sha256()

    def bind(event):
        if (current is None or type(event["occurrence"]) is not int
                or event["occurrence"] != current or event["nodeid"] != expected[current]):
            raise ValueError("event is not bound to the current collected occurrence")

    def next_phase():
        if "setup" not in phases:
            return "setup"
        if phases["setup"] == "passed" and "call" not in phases:
            return "call"
        return "teardown" if "teardown" not in phases else None

    with events_path.open("rb") as stream:
        for line in stream:
            if len(line) > MAX_RECORD or not line.endswith(b"\n") or count >= MAX_EVENTS:
                raise ValueError("invalid event boundary")
            event = json.loads(line)
            if (ended or type(event["version"]) is not int or event["version"] != 1
                    or type(event["sequence"]) is not int or event["sequence"] != count
                    or event["observation_id"] != final["observation_id"]):
                raise ValueError("event identity or order changed")
            sha.update(line)
            size += len(line)
            count += 1
            last = event
            kind = event["kind"]
            if count == 1 and kind != "session_start":
                raise ValueError("session identity missing")
            if kind == "session_start":
                if count != 1 or event["selection"]["collect_only"]:
                    raise ValueError("not one executed session")
            elif kind == "collector":
                if collected or event["outcome"] not in ("passed", "failed", "skipped"):
                    raise ValueError("invalid collection outcome")
                failed |= event["outcome"] == "failed"
            elif kind == "collected":
                if (collected or type(event["occurrence"]) is not int or event["occurrence"] != len(expected)
                        or not isinstance(event["nodeid"], str)):
                    raise ValueError("collection order changed")
                expected.append(event["nodeid"])
            elif kind == "collection_finish":
                if collected or event["count"] != len(expected):
                    raise ValueError("collection inventory changed")
                collected = True
            elif kind == "test_start":
                if not collected or current is not None or event["occurrence"] != len(started):
                    raise ValueError("execution order changed")
                current = len(started)
                bind(event)
                started.append(event["nodeid"])
                phases = {}
            elif kind == "phase_start":
                bind(event)
                if active is not None or event["when"] != next_phase() or event["when"] is None:
                    raise ValueError("phase start missing, repeated or out of order")
                active = event["when"]
            elif kind in ("phase", "subtest"):
                bind(event)
                if event["outcome"] not in ("passed", "failed", "skipped") or active is None:
                    raise ValueError("invalid outcome or missing phase start")
                for field in ("duration_seconds", "start", "stop"):
                    value = event[field]
                    if type(value) not in (int, float) or not math.isfinite(value):
                        raise ValueError("invalid phase time")
                if event["duration_seconds"] < 0:
                    raise ValueError("invalid phase duration")
                failed |= event["outcome"] == "failed"
                if kind == "subtest":
                    # Pytest 9.1.1 reports a subtest as `call`, even inside a
                    # fixture's setup or teardown. Bind its parent, not the two
                    # distinct meanings of `when`.
                    context = event["subtest"]
                    if (event["when"] != "call" or type(context["occurrence"]) is not int
                            or context["occurrence"] != subtests or "message" not in context
                            or not isinstance(context["parameters"], dict)
                            or not all(isinstance(value, str) for value in context["parameters"].values())):
                        raise ValueError("subtest phase or order changed")
                    subtests += 1
                else:
                    if event["when"] != active:
                        raise ValueError("phase outcome does not match its start")
                    phases[active] = event["outcome"]
                    active = None
            elif kind == "test_finish":
                bind(event)
                if active is not None or next_phase() is not None or current != len(finished):
                    raise ValueError("test finished without all required phase outcomes")
                finished.append(event["nodeid"])
                current = None
            elif kind == "session_finish":
                if (not collected or current is not None or type(event["pytest_exit_code"]) is not int
                        or event["pytest_exit_code"] not in (0, 1)
                        or failed and event["pytest_exit_code"] == 0):
                    raise ValueError("session outcome contradicts its execution evidence")
                ended = True
            else:
                raise ValueError("unknown event kind")
    if (not ended or last["pytest_exit_code"] != final["pytest_exit_code"]
            or sha.hexdigest() != final["events_sha256"] or count != final["events"] or size != final["stream_bytes"]
            or expected != started or expected != finished
            or len(expected) != final["collected"] or len(started) != final["started"]
            or len(finished) != final["finished"] or subtests != final["subtests"]):
        raise ValueError("evidence inventory or final digest mismatch")
    return final


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            raise ValueError("usage: pytest_ci_observer.py DIRECTORY")
        result = verify(sys.argv[1])
        print(json.dumps({"complete": True, "pytest_exit_code": result["pytest_exit_code"], "events": result["events"]}))
        raise SystemExit(result["pytest_exit_code"])
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        print('{"complete":false,"reason":"missing_or_incomplete_observation"}')
        raise SystemExit(3)
