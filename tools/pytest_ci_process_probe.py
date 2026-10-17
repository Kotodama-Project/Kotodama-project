"""Opt-in, content-free diagnosis for known Windows child-timeout regressions.

The normal subprocess.run/communicate implementation still owns deadlines,
termination and reaping. Missing diagnostics never turn a failing test green.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from unittest import mock

import psutil
import pytest

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "tests/test_task_swarm_closed_loop_recovery.py::test_recovery_reconstructs_actual_reuse_owner_and_current_decision[none]",
    "tests/test_task_swarm_executor_cli.py::test_learning_cli_uses_current_decision_and_keeps_the_typed_transport[23-False]",
    "tests/test_task_swarm_executor_cli.py::test_learning_cli_uses_current_decision_and_keeps_the_typed_transport[13-False]",
    "tests/test_task_swarm_learning_reuse.py::test_cli_explicit_review_decision_run_and_anchor_replay",
    "tests/test_task_swarm_dependency_recovery.py::test_terminal_resume_preserves_scoped_acceptance",
    "tests/test_task_swarm_dependency_recovery.py::test_two_fresh_resumers_create_only_one_b_attempt",
}
MAX_BYTES = 128 * 1024
MAX_CALLS = 64


def process_state(process):
    """Read counters only; never read argv, environment, files or pipe contents."""
    state = {"pid": process.pid, "returncode": process.poll(), "counters": None}
    for channel in ("stdout", "stderr"):
        reader = getattr(process, channel + "_thread", None)
        state[channel + "_reader_alive"] = reader.is_alive() if reader is not None else None
    if state["returncode"] is not None:
        return state
    try:
        child = psutil.Process(process.pid)
        with child.oneshot():
            cpu = child.cpu_times()
            state["counters"] = {"created_at": child.create_time(), "status": child.status(),
                "cpu_user_seconds": cpu.user, "cpu_system_seconds": cpu.system,
                "rss_bytes": child.memory_info().rss, "threads": child.num_threads()}
            io = child.io_counters()
            state["counters"]["io"] = {name: getattr(io, name) for name in
                ("read_count", "write_count", "read_bytes", "write_bytes")}
    except (psutil.Error, OSError) as error:
        state["unavailable"] = type(error).__name__
    if process.poll() is not None:
        state.update(returncode=process.returncode, counters=None, unavailable="root_exited_during_sample")
    return state


class Probe:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.stream = (self.directory / "events.jsonl").open("xb", buffering=0)
        self.lock = threading.Lock()
        self.calls = self.bytes = self.events = 0
        self.error = None
        self.started = time.perf_counter()
        self.emit("session", head=os.environ.get("KOTODAMA_CI_HEAD_SHA"),
            run_id=os.environ.get("GITHUB_RUN_ID"), attempt=os.environ.get("GITHUB_RUN_ATTEMPT"),
            os=os.environ.get("RUNNER_OS"), probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            limits={"bytes": MAX_BYTES, "calls": MAX_CALLS},
            limitations="root process counters and Python pipe-reader state only; no stack, handle-owner or descendant proof")

    def emit(self, kind, *, _stopped=None, **fields):
        with self.lock:
            if self.error or (_stopped is not None and _stopped.is_set()):
                return
            try:
                data = (json.dumps({"version": 1, "sequence": self.events, "kind": kind,
                    "elapsed_seconds": time.perf_counter() - self.started, **fields},
                    ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
                if self.bytes + len(data) > MAX_BYTES:
                    self.error = "capacity_exceeded"
                    return
                if self.stream.write(data) != len(data):
                    raise OSError("short write")
                self.bytes += len(data)
                self.events += 1
            except (OSError, ValueError, TypeError):
                self.error = "observation_failed"

    def communicate(self, original, process, input=None, timeout=None, *, label):
        if timeout is None or self.calls >= MAX_CALLS:
            if timeout is not None:
                self.error = "call_limit_exceeded"
            return original(process, input=input, timeout=timeout)
        self.calls += 1
        call = self.calls
        stopped = threading.Event()

        def record(phase):
            try:
                begin = time.perf_counter()
                state = process_state(process)
                if not stopped.is_set():
                    self.emit(phase, _stopped=stopped, call=call, label=label, timeout_seconds=timeout, state=state,
                        sample_seconds=time.perf_counter() - begin)
            except Exception:
                # Diagnostics must preserve the underlying subprocess outcome.
                self.error = "sample_failed"

        self.emit("start", call=call, label=label, pid=process.pid, timeout_seconds=timeout)
        timer = None
        try:
            timer = threading.Timer(max(0, timeout - min(2, timeout / 2)), record, args=("near_deadline",))
            timer.daemon = True
            timer.start()
        except Exception:
            self.error = "timer_setup_failed"
        outcome = "interrupted"
        try:
            result = original(process, input=input, timeout=timeout)
            outcome = "completed"
            return result
        except subprocess.TimeoutExpired:
            outcome = "timeout"
            record("timeout")
            raise
        finally:
            stopped.set()
            if timer is not None:
                try:
                    timer.cancel()
                except Exception:
                    self.error = "timer_cancel_failed"
            self.emit("return", call=call, label=label, outcome=outcome,
                returncode=process.returncode)

    def close(self):
        with self.lock:
            try:
                self.stream.close()
            except (OSError, ValueError):
                self.error = "close_failed"
            summary = {"version": 1, "complete": self.error is None, "incomplete_reason": self.error,
                "calls": self.calls, "events": self.events, "bytes": self.bytes,
                "whole_test_perturbation_seconds": None}
            try:
                (self.directory / "summary.json").write_text(json.dumps(summary) + "\n", encoding="ascii")
            except OSError:
                pass  # Absent summary is explicitly unconfirmed observation.


class Plugin:
    def __init__(self, probe):
        self.probe = probe

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_call(self, item):
        if item.nodeid.replace("\\", "/") not in TARGETS:
            return (yield)
        original = subprocess.Popen.communicate

        def communicate(process, input=None, timeout=None):
            command = process.args
            label = None
            if isinstance(command, (list, tuple)) and timeout in (30, 60):
                if str(ROOT / "tests/test_task_swarm_closed_loop_recovery.py") in command:
                    label = "recovery"
                elif str(ROOT / "tools/knowledge_base.py") in command:
                    label = "task-input"
            elif isinstance(command, (list, tuple)) and timeout == 20:
                if str(ROOT / "tests/test_task_swarm_dependency_recovery.py") in command:
                    label = "dependency-recovery"
                elif list(command[1:4]) == ["-B", "-m", "task_swarm.learning_reuse"]:
                    label = "learning-reuse"
            if label is None:
                return original(process, input=input, timeout=timeout)
            return self.probe.communicate(original, process, input, timeout, label=label)

        with mock.patch.object(subprocess.Popen, "communicate", communicate):
            return (yield)

    def pytest_unconfigure(self, config):
        self.probe.close()


def pytest_configure(config):
    directory = os.environ.get("KOTODAMA_CI_PROCESS_PROBE_DIR")
    if not directory:
        raise pytest.UsageError("KOTODAMA_CI_PROCESS_PROBE_DIR is required for the explicit process probe")
    config.pluginmanager.register(Plugin(Probe(directory)), "kotodama-ci-process-probe")
