"""Existing-run cancellation, real process restart and publication ordering."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest job")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from task_swarm import closed_loop, closed_loop_recovery
from task_swarm.closed_loop import cancel_closed_loop, execute_closed_loop
from task_swarm.codex import BackendError
from task_swarm.owner_file import OwnerFile
from task_swarm.protocol import SwarmError, canonical, digest
from task_swarm.state import SwarmState
from task_swarm.task_runner import read_json
from test_task_swarm_closed_loop import MeasuredBackend, execute, setup_loop
from test_task_swarm_closed_loop_recovery import (
    _child as recovery_child, child as crash_child, directory, setup_case, snapshot,
)


def process(tmp_path, mode, *, now=1000):
    return subprocess.run([sys.executable, str(Path(__file__).resolve()),
        "child", str(tmp_path), mode, str(now)], capture_output=True, text=True, timeout=30)


def state(config, *, now=1000):
    owner = OwnerFile(config["owner"], clock=lambda: now)
    return SwarmState(directory(config) / "execution.sqlite", owner.read_task, clock=lambda: now)


def rows(config):
    with sqlite3.connect(directory(config) / "execution.sqlite") as connection:
        return {name: list(connection.execute("SELECT * FROM " + name + " ORDER BY 1,2"))
                for name in ("runs", "jobs", "attempts", "run_extensions", "run_finalizations")}


def cancel(config, *, now=1000):
    return cancel_closed_loop(config["owner"], config["input"], clock=lambda: now)


def _child(tmp_path, mode, now):
    config = read_json(tmp_path / "case.json")
    if mode in {"stop-work", "stop-critic"}:
        original = SwarmState.report
        target = "r0-speed" if mode == "stop-work" else "r0-critic"

        def report(*args, **kwargs):
            answer = original(*args, **kwargs)
            if args[2].endswith(target):
                os._exit(78)
            return answer

        SwarmState.report = report
        return recovery_child(tmp_path, "complete", now, None)
    try:
        if mode == "cancel":
            answer = {"cancellation": cancel(config, now=now)}
        else:
            class NeverDispatch:
                synthetic = True

                def produce(self, *_args, **_kwargs):
                    (tmp_path / "UNAUTHORIZED_CALL").write_bytes(b"called")
                    raise AssertionError("cancelled run dispatched")

                review = produce

            answer = execute_closed_loop(config["owner"], config["input"], config["plan"],
                NeverDispatch(), worker_actors=config["actors"], clock=lambda: now,
                resume_finalization=mode == "resume")
        (tmp_path / "cancel-result.json").write_bytes((canonical(answer) + "\n").encode())
        return 0
    except SwarmError as error:
        (tmp_path / "cancel-result.json").write_bytes(canonical({"error": error.code}).encode())
        return 2


@pytest.mark.parametrize("phase", ["lease", "stop-work", "stop-critic", "checkpoint", "accept", "preimage", "staged"])
def test_cancelled_real_process_never_redispatches_or_resumes(tmp_path, phase):
    config = setup_case(tmp_path)
    stopped = process(tmp_path, phase) if phase.startswith("stop-") else crash_child(tmp_path, phase)
    assert stopped.returncode == (78 if phase.startswith("stop-") else 73), stopped.stderr
    path = directory(config)
    before, execution = rows(config), snapshot(config)
    saved = {name: (path / name).read_bytes() for name in ("input.json", "specification.json", "plan.json")}
    owner_before = Path(config["owner"]).read_bytes()
    stage = (path / ".receipt-pending.json").read_bytes() if (path / ".receipt-pending.json").exists() else None
    accepted = process(tmp_path, "cancel")
    assert accepted.returncode == 0, accepted.stderr
    record = read_json(tmp_path / "cancel-result.json")["cancellation"]
    # A lost ACK is replayable after the run deadline, not after owner expiry.
    assert process(tmp_path, "cancel", now=1101).returncode == 0
    assert read_json(tmp_path / "cancel-result.json")["cancellation"] == record
    for mode in ("normal", "resume", "normal", "resume"):
        result = process(tmp_path, mode)
        assert result.returncode == 2, result.stderr
        assert read_json(tmp_path / "cancel-result.json") == {"error": "RUN_CANCELLED"}
    assert not (tmp_path / "UNAUTHORIZED_CALL").exists()
    assert not (path / "receipt.json").exists()
    assert rows(config) == before
    after = state(config).snapshot(path.name)
    assert after["run_state"] == "cancelled" and after["cancellation"] == record
    assert after["jobs"] == execution["jobs"] and after["budget"] == execution["budget"]
    assert Path(config["owner"]).read_bytes() == owner_before
    assert {name: (path / name).read_bytes() for name in saved} == saved
    if stage is not None:
        assert (path / ".receipt-pending.json").read_bytes() == stage


def test_cancel_does_not_create_a_missing_run(tmp_path):
    config = setup_case(tmp_path)
    with pytest.raises(SwarmError, match="RUN_RECOVERY_REQUIRED"):
        cancel(config)
    assert not directory(config).exists()


@pytest.mark.parametrize("change", ["input", "saved_input", "plan", "specification", "purpose", "template", "source", "owner", "expired"])
def test_cancel_rechecks_existing_input_owner_source_and_plan(tmp_path, change):
    config = setup_case(tmp_path)
    assert crash_child(tmp_path, "checkpoint").returncode == 73
    before = rows(config)
    path = directory(config)
    if change in {"input", "saved_input"}:
        target = Path(config["input"]) if change == "input" else path / "input.json"
        value = read_json(target)
        value["request"] += " changed"
        target.write_bytes(canonical(value).encode())
    elif change == "plan":
        value = read_json(path / "plan.json")
        value["jobs"][0]["payload_digest"] = "0" * 64
        (path / "plan.json").write_bytes(canonical(value).encode())
    elif change == "template":
        value = read_json(path / "r0-critic-template.json")
        value["criteria"]["R"] = "A different valid string in the initial critic input."
        (path / "r0-critic-template.json").write_bytes(canonical(value).encode())
    elif change in {"specification", "purpose"}:
        value = read_json(path / "specification.json")
        if change == "purpose":
            value["jobs"][0]["purpose"] = "A valid but different purpose for the same Task."
        else:
            value["parent_input_digest"] = "0" * 64
        (path / "specification.json").write_bytes(canonical(value).encode())
    else:
        owner = read_json(Path(config["owner"]))
        if change == "source":
            owner["source_checks"][0]["sha256"] = "0" * 64
        elif change == "owner":
            owner["binding"]["owner_ref"] = "another-owner"
        else:
            owner["binding"]["expires_at"] = 999
        Path(config["owner"]).write_bytes(canonical(owner).encode())
    with pytest.raises(SwarmError):
        cancel(config)
    with sqlite3.connect(path / "execution.sqlite") as connection:
        assert connection.execute("SELECT COUNT(*) FROM run_cancellations").fetchone()[0] == 0
    assert rows(config) == before


def test_new_cancellation_after_deadline_refuses_but_owner_expiry_still_blocks_retry(tmp_path):
    config = setup_case(tmp_path)
    assert crash_child(tmp_path, "checkpoint").returncode == 73
    with pytest.raises(SwarmError, match="DEADLINE_EXPIRED"):
        cancel(config, now=1101)
    assert state(config).cancellation(directory(config).name) is None
    record = cancel(config)
    with pytest.raises(SwarmError, match="EXPIRED_BINDING"):
        cancel(config, now=1201)
    assert state(config, now=1201).cancellation(directory(config).name) == record


def test_restoring_original_active_owner_does_not_clear_cancellation(tmp_path):
    config = setup_case(tmp_path)
    assert crash_child(tmp_path, "lease").returncode == 73
    record = cancel(config)
    path = Path(config["owner"])
    original = path.read_bytes()
    revoked = read_json(path)
    revoked["binding"]["status"] = "revoked"
    path.write_bytes(canonical(revoked).encode())
    with pytest.raises(SwarmError):
        cancel(config)
    path.write_bytes(original)
    assert cancel(config) == record
    assert process(tmp_path, "normal").returncode == 2
    assert read_json(tmp_path / "cancel-result.json") == {"error": "RUN_CANCELLED"}


def test_cancel_after_input_save_is_observed_before_backend_entry(tmp_path, monkeypatch):
    setup = setup_loop(tmp_path, jobs=1)
    backend = MeasuredBackend(setup[3], setup[6])
    original = closed_loop.write_json

    def write(path, value):
        result = original(path, value)
        if path.name == "r0-speed-input.json":
            cancel_closed_loop(setup[0], setup[1], clock=lambda: 1000)
        return result

    monkeypatch.setattr(closed_loop, "write_json", write)
    with pytest.raises(SwarmError, match="RUN_CANCELLED"):
        execute(setup, backend)
    assert backend.inputs == []


def test_direct_terminal_readback_cannot_bypass_cancellation(tmp_path):
    config = setup_case(tmp_path)
    assert crash_child(tmp_path, "checkpoint").returncode == 73
    with sqlite3.connect(directory(config) / "execution.sqlite") as connection:
        record = json.loads(connection.execute("SELECT checkpoint_json FROM run_finalizations").fetchone()[0])
    cancel(config)
    with pytest.raises(SwarmError, match="RUN_CANCELLED"):
        closed_loop_recovery.terminal_evidence(directory(config), read_json(Path(config["input"])),
                                               record, state(config))


def test_durable_monitor_signals_backend_and_preserves_original_exception(tmp_path):
    setup = setup_loop(tmp_path, jobs=1)
    started, finished = threading.Event(), threading.Event()
    observed = {}

    class Backend(MeasuredBackend):
        def produce(self, _delivered, _directory, *, cancel_event, **_kwargs):
            started.set()
            assert cancel_event.wait(5), "durable cancellation did not reach running backend"
            raise LookupError("original backend failure")

    def run():
        try:
            execute(setup, Backend(setup[3], setup[6]))
        except Exception as error:
            observed["error"] = error
        finally:
            finished.set()

    runner = threading.Thread(target=run)
    runner.start()
    try:
        assert started.wait(5)
        record = cancel_closed_loop(setup[0], setup[1], clock=lambda: 1000)
        assert finished.wait(5)
        assert type(observed["error"]) is LookupError
        assert str(observed["error"]) == "original backend failure"
        owner = OwnerFile(setup[0], clock=lambda: 1000)
        current = SwarmState(setup[0].parent / "operations" / record["run_id"] / "execution.sqlite",
                             owner.read_task, clock=lambda: 1000).snapshot(record["run_id"])
        assert current["running"] == 1 and current["budget"]["attempts_used"] == 1
        assert current["jobs"]["r0-speed"]["current_attempt"]["identity"] is None
    finally:
        runner.join(timeout=6)
    assert not runner.is_alive()


@pytest.mark.parametrize("validator", ["validate_report_in_view", "validate_critic"])
def test_cancelled_validation_cleanup_preserves_original_error(tmp_path, monkeypatch, validator):
    setup = setup_loop(tmp_path, jobs=1)

    def invalid(*_args, **_kwargs):
        cancel_closed_loop(setup[0], setup[1], clock=lambda: 1000)
        raise ValueError("original validation failure")

    monkeypatch.setattr(closed_loop, validator, invalid)
    with pytest.raises(ValueError, match="original validation failure"):
        execute(setup, MeasuredBackend(setup[3], setup[6]))


def test_transient_backend_stop_is_not_persisted_as_owner_cancellation(tmp_path):
    setup = setup_loop(tmp_path, jobs=1)

    class Backend(MeasuredBackend):
        def produce(self, _delivered, _directory, *, cancel_event, **_kwargs):
            cancel_event.set()
            raise LookupError("temporary stop")

    with pytest.raises(LookupError, match="temporary stop"):
        execute(setup, Backend(setup[3], setup[6]))
    path = next((tmp_path / "operations").glob("task-run-*"))
    current = SwarmState(path / "execution.sqlite", OwnerFile(setup[0], clock=lambda: 1000).read_task,
                         clock=lambda: 1000)
    assert current.cancellation(path.name) is None
    assert current.snapshot(path.name)["failed"] == 1


class OwnerMonitorGate:
    """Order a real owner refusal before a later cancellation, without sleeps."""

    def __init__(self, monkeypatch):
        self.entered, self.release = threading.Event(), threading.Event()
        self.thread = None
        original = closed_loop.OwnerFile.read_task

        def read(owner, *args, **kwargs):
            if threading.current_thread().name == "loop-owner-watch":
                self.thread = threading.current_thread()
                self.entered.set()
                assert self.release.wait(10), "watcher owner read was not released"
            return original(owner, *args, **kwargs)

        monkeypatch.setattr(closed_loop.OwnerFile, "read_task", read)

    def refuse(self, setup, event):
        assert self.entered.wait(10), "watcher did not reach the owner"
        original = setup[0].read_bytes()
        setup[2]["binding"]["status"] = "cancelled"
        setup[0].write_bytes(canonical(setup[2]).encode("utf-8"))
        self.release.set()
        assert event.wait(10), "owner refusal did not signal cancellation"
        self.thread.join(timeout=10)
        assert not self.thread.is_alive()
        setup[0].write_bytes(original)

    def finish(self):
        self.release.set()
        if self.thread is not None:
            self.thread.join(timeout=10)
            assert not self.thread.is_alive(), "watcher remained active"


@pytest.mark.parametrize("failure", [None, "swarm", "native"])
def test_later_durable_cancel_wins_over_monitor_reason(tmp_path, monkeypatch, failure):
    setup = setup_loop(tmp_path, jobs=1)
    gate, records = OwnerMonitorGate(monkeypatch), []
    native = BackendError("cancelled", "backend cancellation", retryable=False)

    class Backend(MeasuredBackend):
        def review(self, *args, **kwargs):
            value = super().review(*args, **kwargs)
            gate.refuse(setup, kwargs["cancel_event"])
            records.append(cancel_closed_loop(setup[0], setup[1], clock=lambda: 1000))
            if failure == "swarm":
                raise SwarmError("RUN_CANCELLED", "backend cancellation")
            if failure == "native":
                raise native
            return value

    backend = Backend(setup[3], setup[6])
    try:
        if failure == "native":
            with pytest.raises(BackendError) as caught:
                execute(setup, backend)
            assert caught.value is native
        else:
            with pytest.raises(SwarmError, match="RUN_CANCELLED"):
                execute(setup, backend)
    finally:
        gate.finish()
    path = setup[0].parent / "operations" / records[0]["run_id"]
    before = {name: (path / name).read_bytes() for name in ("input.json", "plan.json", "specification.json")}
    with sqlite3.connect(path / "execution.sqlite") as conn:
        assert conn.execute("SELECT count(*) FROM run_cancellations").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM jobs WHERE state='leased'").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM jobs WHERE state='accepted'").fetchone()[0] == 0
    calls = len(backend.inputs)
    for resume in (False, True):
        with pytest.raises(SwarmError, match="RUN_CANCELLED"):
            execute(setup, backend, resume_finalization=resume)
    assert len(backend.inputs) == calls and not (path / "receipt.json").exists()
    assert {name: (path / name).read_bytes() for name in before} == before
    assert cancel_closed_loop(setup[0], setup[1], clock=lambda: 1000) == records[0]


def test_unknown_durable_status_preserves_actual_backend_cancel(tmp_path, monkeypatch):
    setup = setup_loop(tmp_path, jobs=1)
    gate = OwnerMonitorGate(monkeypatch)
    failure = BackendError("cancelled", "native cancellation", retryable=False)

    class Backend(MeasuredBackend):
        def review(self, *_args, **kwargs):
            gate.refuse(setup, kwargs["cancel_event"])

            def unavailable(*_args, **_kwargs):
                raise OSError("status unavailable")

            monkeypatch.setattr(SwarmState, "cancellation", unavailable)
            raise failure

    try:
        with pytest.raises(BackendError) as caught:
            execute(setup, Backend(setup[3], setup[6]))
    finally:
        gate.finish()
    assert caught.value is failure
    path = next((tmp_path / "operations").glob("task-run-*"))
    assert not (path / "receipt.json").exists()
    with sqlite3.connect(path / "execution.sqlite") as conn:
        assert conn.execute("SELECT count(*) FROM run_cancellations").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM jobs WHERE state='accepted'").fetchone()[0] == 0


def test_active_finalizer_lock_refuses_cancel_then_published_anchor_is_unchanged(tmp_path):
    config = setup_case(tmp_path)
    assert crash_child(tmp_path, "checkpoint").returncode == 73
    command = [sys.executable, str(Path(__file__).with_name("test_task_swarm_closed_loop_recovery.py")),
               "child", str(tmp_path), "hold", "1000"]
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        import time
        deadline = time.monotonic() + 5
        while not (tmp_path / "LOCK_HELD").exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(.01)
        assert (tmp_path / "LOCK_HELD").exists()
        with pytest.raises(SwarmError, match="FINALIZATION_BUSY"):
            cancel(config)
        assert state(config).cancellation(directory(config).name) is None
    finally:
        (tmp_path / "RELEASE").write_bytes(b"release")
        output, error = child.communicate(timeout=10)
    assert child.returncode == 0, (output, error)
    receipt = (directory(config) / "receipt.json").read_bytes()
    with pytest.raises(SwarmError, match="RUN_CANCELLATION_RECEIPT_PRESENT"):
        cancel(config)
    assert state(config).cancellation(directory(config).name) is None
    assert (directory(config) / "receipt.json").read_bytes() == receipt
    assert crash_child(tmp_path, "replay", anchor=hashlib.sha256(receipt).hexdigest()).returncode == 0


def test_last_guard_to_rename_is_inside_same_lock_as_cancellation(tmp_path, monkeypatch):
    setup = setup_loop(tmp_path, jobs=1)
    original = os.replace
    attempted = []

    def replace(source, target):
        if Path(target).name == "receipt.json":
            with pytest.raises(SwarmError, match="FINALIZATION_BUSY"):
                cancel_closed_loop(setup[0], setup[1], clock=lambda: 1000)
            attempted.append(True)
        return original(source, target)

    monkeypatch.setattr(closed_loop_recovery.os, "replace", replace)
    answer = execute(setup, MeasuredBackend(setup[3], setup[6]))
    assert attempted == [True]
    assert answer["receipt_sha256"] == hashlib.sha256(
        (setup[0].parent / "operations" / answer["receipt"]["run_id"] / "receipt.json").read_bytes()).hexdigest()


@pytest.mark.parametrize("receipt", [b'{"torn":', b"{}\n"])
def test_any_published_receipt_entry_refuses_cancel_without_claiming_success(tmp_path, receipt):
    config = setup_case(tmp_path)
    assert crash_child(tmp_path, "checkpoint").returncode == 73
    path = directory(config) / "receipt.json"
    path.write_bytes(receipt)
    before = rows(config)
    with pytest.raises(SwarmError, match="RUN_CANCELLATION_RECEIPT_PRESENT"):
        cancel(config)
    assert path.read_bytes() == receipt and rows(config) == before
    assert state(config).cancellation(path.parent.name) is None


if __name__ == "__main__":
    assert len(sys.argv) == 5 and sys.argv[1] == "child"
    raise SystemExit(_child(Path(sys.argv[2]), sys.argv[3], float(sys.argv[4])))
