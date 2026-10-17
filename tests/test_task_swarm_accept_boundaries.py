"""Acceptance eligibility is rechecked inside the existing state transaction."""
import copy
import sqlite3
import sys
import threading
from pathlib import Path

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest job")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from task_swarm.protocol import SwarmError, digest, validate_binding
from task_swarm.state import SwarmState


def reported(tmp_path):
    now = [1000]
    binding = dict(task_id="task-accept", revision=1, context_digest="a" * 64,
                   owner_ref="owner", active_home="local", authority_ref="authority",
                   capability_ref="capability", expires_at=2000, status="active")
    state = SwarmState(tmp_path / "state.sqlite", lambda _: copy.deepcopy(binding), lambda: now[0])
    plan = dict(run_id="run-accept", task_id="task-accept", binding_digest=digest(validate_binding(binding, now=now[0])),
                budget=dict(attempt_budget=4, concurrency=2, deadline=1100), jobs=[
                    dict(job_id=job, kind="work", dependencies=[], exclusive_keys=[],
                         payload_ref="payload-" + job, payload_digest="b" * 64) for job in ("a", "b")])
    state.create_run(plan)
    for actor in ("worker-a", "worker-b"):
        lease = state.claim("run-accept", actor)
        state.report(lease["token"], "result", "c" * 64, "candidate", "receipt")
    return state, now


@pytest.mark.parametrize("stop", ["cancel", "deadline"])
def test_prior_acceptance_is_preserved_when_next_acceptance_stops(tmp_path, stop):
    state, now = reported(tmp_path)
    state.accept("run-accept", "a", "c" * 64, "verification", "owner")
    event = threading.Event()
    if stop == "cancel":
        event.set()
    else:
        now[0] = 1100
    with pytest.raises(SwarmError, match="RUN_CANCELLED|DEADLINE_EXPIRED"):
        state.accept("run-accept", "b", "c" * 64, "verification", "owner", cancel_event=event)
    with sqlite3.connect(state.db_path) as conn:
        assert conn.execute("SELECT job_id,state FROM jobs ORDER BY job_id").fetchall() == [
            ("a", "accepted"), ("b", "reported")]
        assert conn.execute("SELECT job_id,state FROM attempts ORDER BY job_id").fetchall() == [
            ("a", "accepted"), ("b", "reported")]


@pytest.mark.parametrize("stop", ["cancel", "deadline"])
def test_idempotent_acceptance_also_checks_current_eligibility(tmp_path, stop):
    state, now = reported(tmp_path)
    args = ("run-accept", "a", "c" * 64, "verification", "owner")
    first = state.accept(*args)
    assert state.accept(*args) == first
    event = threading.Event()
    if stop == "cancel":
        event.set()
    else:
        now[0] = 1100
    with pytest.raises(SwarmError, match="RUN_CANCELLED|DEADLINE_EXPIRED"):
        state.accept(*args, cancel_event=event)


def test_invalid_cancellation_object_is_rejected_without_writes(tmp_path):
    state, _ = reported(tmp_path)
    with pytest.raises(SwarmError, match="RUN_CANCELLATION_INVALID"):
        state.accept("run-accept", "a", "c" * 64, "verification", "owner", cancel_event=object())
    assert state.snapshot("run-accept")["accepted"] == 0


@pytest.mark.parametrize("phase", ["after_begin", "after_update"])
@pytest.mark.parametrize("stop", ["cancel", "deadline"])
def test_transaction_stop_rolls_back_both_rows(tmp_path, monkeypatch, phase, stop):
    state, now = reported(tmp_path)
    event = threading.Event()
    original = state._transaction

    def stop_now():
        event.set() if stop == "cancel" else now.__setitem__(0, 1100)

    def transaction():
        conn = original()
        if phase == "after_begin":
            stop_now()
        else:
            conn.set_trace_callback(lambda sql: stop_now() if sql.startswith("UPDATE jobs SET state = 'accepted'") else None)
        return conn

    monkeypatch.setattr(state, "_transaction", transaction)
    with pytest.raises(SwarmError, match="RUN_CANCELLED|DEADLINE_EXPIRED"):
        state.accept("run-accept", "a", "c" * 64, "verification", "owner", cancel_event=event)
    with sqlite3.connect(state.db_path) as conn:
        assert conn.execute("SELECT DISTINCT state FROM jobs").fetchall() == [("reported",)]
        assert conn.execute("SELECT DISTINCT state FROM attempts").fetchall() == [("reported",)]
