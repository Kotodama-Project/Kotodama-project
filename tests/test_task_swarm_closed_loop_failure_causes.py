"""Controlled owner-monitor ordering over the actual local closed-loop API."""
import json
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
from task_swarm import closed_loop
from task_swarm.codex import BackendError
from task_swarm.protocol import SwarmError, canonical
from test_task_swarm_closed_loop import MeasuredBackend, setup_loop


class MonitorGate:
    """Hold the watcher's owner read, leaving real validation in both paths."""

    def __init__(self, monkeypatch, *, foreground_first=False, error=None):
        self.entered, self.release = threading.Event(), threading.Event()
        self.thread, self.error = None, error
        original_task = closed_loop.OwnerFile.read_task
        original_binding = closed_loop.OwnerFile.read_binding
        original_require = closed_loop.require

        def invoke(original, *args, **kwargs):
            try:
                return original(*args, **kwargs)
            except Exception:
                if foreground_first and threading.current_thread().name != "loop-owner-watch":
                    self.release.set()
                raise

        def read_task(instance, *args, **kwargs):
            if threading.current_thread().name == "loop-owner-watch":
                self.thread = threading.current_thread()
                self.entered.set()
                assert self.release.wait(10), "watcher owner read was not released"
                if self.error is not None:
                    raise self.error
            return invoke(original_task, instance, *args, **kwargs)

        monkeypatch.setattr(closed_loop.OwnerFile, "read_task", read_task)
        monkeypatch.setattr(closed_loop.OwnerFile, "read_binding",
                            lambda *a, **k: invoke(original_binding, *a, **k))
        monkeypatch.setattr(closed_loop, "require", lambda *a, **k: invoke(original_require, *a, **k))

    def wait(self):
        assert self.entered.wait(10), "watcher did not reach its owner read"

    def assert_stopped(self):
        assert self.thread is not None and not self.thread.is_alive(), "watcher still running on return"

    def finish(self):
        self.release.set()
        if self.thread is not None:
            self.thread.join(timeout=10)
            assert not self.thread.is_alive()


def run(setup, backend, now, **kwargs):
    return closed_loop.execute_closed_loop(setup[0], setup[1], setup[4], backend,
        worker_actors=setup[5], clock=lambda: now[0], **kwargs)


def refuse_owner(setup, now, mode):
    if mode == "deadline":
        now[0] = 1101
    elif mode == "owner_expired":
        now[0] = 1201
    else:
        if mode == "revoked":
            setup[2]["binding"]["status"] = "cancelled"
        else:
            setup[2]["actors"]["verifier"]["epoch"] += 1
        setup[0].write_bytes(canonical(setup[2]).encode("utf-8"))


def assert_no_acceptance(setup):
    directory = next((setup[0].parent / "operations").glob("task-run-*"))
    assert not (directory / "receipt.json").exists()
    with sqlite3.connect(directory / "execution.sqlite") as connection:
        assert connection.execute("SELECT count(*) FROM jobs WHERE state='accepted'").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM attempts").fetchone()[0] <= 2
    return directory


def assert_no_durable_cancellation_record(connection):
    # Legacy state has no table. A newer schema still must not turn this
    # transient stop or ordinary failure into an explicit cancellation.
    exists = connection.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                "AND name='run_cancellations'").fetchone()
    if exists:
        assert connection.execute("SELECT count(*) FROM run_cancellations").fetchone()[0] == 0


def test_no_durable_cancellation_record_accepts_legacy_or_empty_schema_only():
    with sqlite3.connect(":memory:") as connection:
        assert_no_durable_cancellation_record(connection)
        connection.execute("CREATE TABLE run_cancellations (run_id TEXT PRIMARY KEY)")
        assert_no_durable_cancellation_record(connection)
        connection.execute("INSERT INTO run_cancellations VALUES ('existing-cancelled-run')")
        with pytest.raises(AssertionError):
            assert_no_durable_cancellation_record(connection)


@pytest.mark.parametrize("stage", ["work", "critic"])
@pytest.mark.parametrize("order", ["monitor", "foreground"])
@pytest.mark.parametrize("mode,code", [
    ("revoked", "INACTIVE_TASK"), ("actor", "STALE_ACTOR"),
    ("deadline", "DEADLINE_EXPIRED"), ("owner_expired", "EXPIRED_BINDING"),
])
def test_loop_owner_reason_survives_both_observed_orders(tmp_path, monkeypatch, stage, order, mode, code):
    setup, now = setup_loop(tmp_path, jobs=1), [1000]
    gate = MonitorGate(monkeypatch, foreground_first=order == "foreground")

    class Backend(MeasuredBackend):
        def stop(self, value, kwargs):
            gate.wait()
            refuse_owner(setup, now, mode)
            if order == "monitor":
                gate.release.set()
                assert kwargs["cancel_event"].wait(10)
            return value

        def produce(self, *args, **kwargs):
            value = super().produce(*args, **kwargs)
            return self.stop(value, kwargs) if stage == "work" else value

        def review(self, *args, **kwargs):
            return self.stop(super().review(*args, **kwargs), kwargs)

    try:
        with pytest.raises(SwarmError) as raised:
            run(setup, Backend(setup[3], setup[6]), now)
        gate.assert_stopped()
    finally:
        gate.finish()
    assert raised.value.code == code
    assert_no_acceptance(setup)


@pytest.mark.parametrize("kind", ["swarm", "native", "stop_unconfirmed", "timeout", "other", "duck", "lookup"])
def test_loop_monitor_only_translates_actual_cancellation(tmp_path, monkeypatch, kind):
    setup, now = setup_loop(tmp_path, jobs=1), [1000]
    gate = MonitorGate(monkeypatch)
    class DuckError(LookupError):
        code = "cancelled"
    failures = {
        "swarm": SwarmError("RUN_CANCELLED", "backend cancellation"),
        "native": BackendError("cancelled", "backend cancellation", retryable=False),
        "stop_unconfirmed": BackendError("stop_unconfirmed", "stop unconfirmed", retryable=False,
                                          diagnostics={"cleanup": "unconfirmed"}),
        "timeout": BackendError("timeout", "backend timeout", retryable=False),
        "other": SwarmError("LOOP_CONTEXT_BUDGET", "other failure"),
        "duck": DuckError("not a BackendError"),
        "lookup": LookupError("unrelated failure"),
    }
    failure = failures[kind]
    original_cause = ValueError("earlier failure")
    failure.__cause__ = original_cause

    class Backend(MeasuredBackend):
        def review(self, *_args, **kwargs):
            gate.wait()
            refuse_owner(setup, now, "revoked")
            gate.release.set()
            assert kwargs["cancel_event"].wait(10)
            raise failure

    try:
        with pytest.raises(Exception) as raised:
            run(setup, Backend(setup[3], setup[6]), now)
        gate.assert_stopped()
    finally:
        gate.finish()
    if kind in {"swarm", "native"}:
        assert isinstance(raised.value, SwarmError) and raised.value.code == "INACTIVE_TASK"
        assert raised.value.__cause__ is failure
    else:
        assert raised.value is failure
    assert failure.__cause__ is original_cause
    assert_no_acceptance(setup)


def test_loop_external_cancel_does_not_acquire_later_owner_reason(tmp_path, monkeypatch):
    setup, now, event = setup_loop(tmp_path, jobs=1), [1000], threading.Event()
    gate = MonitorGate(monkeypatch)

    class Backend(MeasuredBackend):
        def review(self, *args, **kwargs):
            value = super().review(*args, **kwargs)
            gate.wait()
            event.set()
            refuse_owner(setup, now, "revoked")
            gate.finish()
            return value

    try:
        with pytest.raises(SwarmError) as raised:
            run(setup, Backend(setup[3], setup[6]), now, cancel_event=event)
        gate.assert_stopped()
    finally:
        gate.finish()
    assert raised.value.code == "RUN_CANCELLED"
    path = assert_no_acceptance(setup)
    with sqlite3.connect(path / "execution.sqlite") as connection:
        assert_no_durable_cancellation_record(connection)


def test_loop_first_monitor_reason_survives_later_owner_change(tmp_path, monkeypatch):
    setup, now = setup_loop(tmp_path, jobs=1), [1000]
    original = setup[0].read_bytes()
    gate = MonitorGate(monkeypatch)

    class Backend(MeasuredBackend):
        def review(self, *args, **kwargs):
            value = super().review(*args, **kwargs)
            gate.wait()
            refuse_owner(setup, now, "revoked")
            gate.release.set()
            assert kwargs["cancel_event"].wait(10)
            setup[2].update(json.loads(original))
            refuse_owner(setup, now, "actor")
            return value

    try:
        with pytest.raises(SwarmError) as raised:
            run(setup, Backend(setup[3], setup[6]), now)
        gate.assert_stopped()
    finally:
        gate.finish()
    assert raised.value.code == "INACTIVE_TASK"
    assert_no_acceptance(setup)


@pytest.mark.parametrize("stage", ["backend", "validate_report_in_view", "validate_critic"])
@pytest.mark.parametrize("revoke_owner", [False, True])
def test_loop_cleanup_preserves_original_error_and_attempt_state(tmp_path, monkeypatch, stage, revoke_owner):
    setup, now = setup_loop(tmp_path, jobs=1), [1000]
    original = setup[0].read_bytes()
    failure, cause = ValueError("original operation failed"), TypeError("original cause")
    failure.__cause__ = cause
    before, cleanup_calls = {}, []
    original_fail = closed_loop.SwarmState.fail

    def cleanup(instance, token, reason, **kwargs):
        cleanup_calls.append((token, reason, kwargs))
        return original_fail(instance, token, reason, **kwargs)

    monkeypatch.setattr(closed_loop.SwarmState, "fail", cleanup)

    def fail(*_args, **_kwargs):
        path = next((setup[0].parent / "operations").glob("task-run-*"))
        with sqlite3.connect(path / "execution.sqlite") as connection:
            before.update({table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                           for table in ("jobs", "attempts")})
        if revoke_owner:
            refuse_owner(setup, now, "revoked")
        raise failure

    backend = MeasuredBackend(setup[3], setup[6])
    if stage == "backend":
        monkeypatch.setattr(backend, "produce", fail)
    else:
        monkeypatch.setattr(closed_loop, stage, fail)
    with pytest.raises(ValueError) as raised:
        run(setup, backend, now)
    assert raised.value is failure and failure.__cause__ is cause
    path = assert_no_acceptance(setup)
    job = "r0-critic" if stage == "validate_critic" else "r0-speed"
    reason = {"backend": "loop backend failed", "validate_report_in_view": "loop report invalid",
              "validate_critic": "loop critic invalid"}[stage]
    assert len(cleanup_calls) == 1
    assert cleanup_calls[0][1:] == (reason, {"retryable": False})
    with sqlite3.connect(path / "execution.sqlite") as connection:
        assert connection.execute("SELECT state FROM jobs WHERE job_id=?", (job,)).fetchone()[0] == (
            "leased" if revoke_owner else "failed")
        attempt = connection.execute("SELECT state, reason, retryable, result_ref, result_digest, "
            "outcome, runtime_receipt_ref FROM attempts WHERE job_id=?", (job,)).fetchone()
        assert attempt == (("leased", None, None) if revoke_owner else ("failed", reason, 0)) + (None,) * 4
        if revoke_owner:
            assert {table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                    for table in before} == before
        assert_no_durable_cancellation_record(connection)
    assert not (path / (job + "-result.json")).exists()
    setup[0].write_bytes(original)
    inputs = len(backend.inputs)
    with pytest.raises(SwarmError, match="RUN_RECOVERY_REQUIRED"):
        run(setup, backend, now)
    assert len(backend.inputs) == inputs


def _cli_probe(path, mode):
    setup, now = setup_loop(path, jobs=1), [1000]
    with pytest.MonkeyPatch.context() as patch:
        gate = MonitorGate(patch, error=OSError("private diagnostic") if mode == "untyped" else None)
        class Backend(MeasuredBackend):
            def review(self, *args, **kwargs):
                value = super().review(*args, **kwargs)
                gate.wait()
                if mode == "native":
                    refuse_owner(setup, now, "revoked")
                if mode == "external":
                    kwargs["cancel_event"].set()
                gate.release.set()
                assert kwargs["cancel_event"].wait(10)
                if mode == "native":
                    raise BackendError("cancelled", "native cancellation", retryable=False)
                return value
        original_execute = closed_loop.execute_closed_loop
        patch.setattr(closed_loop, "execute_closed_loop", lambda *a, **k:
                      original_execute(*a, clock=lambda: now[0], **k))
        patch.setattr(closed_loop, "ScriptedSimulation", lambda _scenario: Backend(setup[3], setup[6]))
        plan, scenario = path / "supplied.json", path / "scenario.json"
        plan.write_bytes(canonical(setup[4]).encode())
        scenario.write_bytes(b'{"repair_plan":null}')
        try:
            status = closed_loop.main(["--owner", str(setup[0]), "--input", str(setup[1]),
                "--plan", str(plan), "--simulation", str(scenario), "--worker", setup[5][0]])
            gate.assert_stopped()
            assert_no_acceptance(setup)
            return status
        finally:
            gate.finish()


@pytest.mark.parametrize("mode,code", [("untyped", "BINDING_UNAVAILABLE"),
                                      ("native", "INACTIVE_TASK"), ("external", "RUN_CANCELLED")])
def test_loop_actual_cli_preserves_bounded_monitor_reason(tmp_path, mode, code):
    child = subprocess.run([sys.executable, str(Path(__file__).resolve()), "probe", str(tmp_path), mode],
                           capture_output=True, text=True, timeout=30)
    assert child.returncode == 2, child.stderr
    assert child.stdout == ""
    result = json.loads(child.stderr)
    assert result["error"] == code and "private diagnostic" not in child.stderr
    if mode == "untyped":
        assert result["message"] == "Task owner binding could not be validated"


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "probe" and sys.argv[3] in {"untyped", "native", "external"}:
        raise SystemExit(_cli_probe(Path(sys.argv[2]), sys.argv[3]))
    raise SystemExit("unknown probe")
