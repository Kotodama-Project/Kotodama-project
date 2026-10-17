"""Receipt staging and transactional stop boundaries during finalization resume."""
import copy
import hashlib
import json
import os
import sqlite3
import threading
from pathlib import Path

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest job")

from test_task_swarm_closed_loop_boundaries import complete_setup, directory
from test_task_swarm_closed_loop import MeasuredBackend
from test_task_swarm_closed_loop_recovery import child, directory as case_directory, setup_case
from task_swarm import closed_loop as coordinator, closed_loop_recovery as publication
from task_swarm.protocol import SwarmError
from task_swarm.state import SwarmState


class NoDispatch:
    synthetic = True
    def produce(self, *_args, **_kwargs):
        raise AssertionError("resume must not dispatch")
    review = produce


def run(setup, *, resume=False, event=None, now=None):
    return coordinator.execute_closed_loop(setup[0], setup[1], setup[4],
        NoDispatch() if resume else MeasuredBackend(setup[3], setup[6]),
        worker_actors=setup[5], resume_finalization=resume,
        cancel_event=event, clock=lambda: now[0] if now else 1000)


def prepared(tmp_path, monkeypatch):
    setup = complete_setup(tmp_path)
    with monkeypatch.context() as patch:
        def stop(*_args, **_kwargs):
            raise RuntimeError("fixture checkpoint boundary")
        patch.setattr(coordinator, "finalize", stop)
        with pytest.raises(RuntimeError, match="fixture checkpoint boundary"):
            run(setup)
    return setup


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("phase", ["after_begin", "after_job", "after_progress"])
@pytest.mark.parametrize("stop", ["cancel", "deadline"])
def test_accept_stop_rolls_back_checkpoint_progress_with_job_and_attempt(tmp_path, monkeypatch, resume, phase, stop):
    setup = prepared(tmp_path, monkeypatch) if resume else complete_setup(tmp_path)
    event, now, accepting, prior = threading.Event(), [1000], [False], []
    original_accept, original_transaction = SwarmState.accept, SwarmState._transaction

    def set_stop():
        if stop == "cancel":
            event.set()
        else:
            now[0] = 1100

    def accept(self, *args, **kwargs):
        with sqlite3.connect(self.db_path) as conn:
            prior.append(conn.execute("SELECT progress_json FROM run_finalizations").fetchone()[0])
        accepting[0] = True
        try:
            return original_accept(self, *args, **kwargs)
        finally:
            accepting[0] = False

    def transaction(self):
        conn = original_transaction(self)
        if accepting[0]:
            if phase == "after_begin":
                set_stop()
            else:
                target = "UPDATE jobs SET state = 'accepted'" if phase == "after_job" else "UPDATE run_finalizations SET progress_json="
                conn.set_trace_callback(lambda sql: set_stop() if sql.startswith(target) else None)
        return conn

    monkeypatch.setattr(SwarmState, "accept", accept)
    monkeypatch.setattr(SwarmState, "_transaction", transaction)
    with pytest.raises(SwarmError, match="RUN_CANCELLED|DEADLINE_EXPIRED"):
        run(setup, resume=resume, event=event, now=now)
    with sqlite3.connect(directory(setup) / "execution.sqlite") as conn:
        assert conn.execute("SELECT count(*) FROM jobs WHERE state='accepted'").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM attempts WHERE state='accepted'").fetchone()[0] == 0
        assert conn.execute("SELECT progress_json FROM run_finalizations").fetchone()[0] == prior[0]
    assert not (directory(setup) / "receipt.json").exists()


@pytest.mark.parametrize("after_commit", [False, True])
@pytest.mark.parametrize("stop", ["cancel", "deadline", "owner"])
def test_resume_publication_returns_anchor_only_after_final_eligibility(tmp_path, monkeypatch, after_commit, stop):
    setup = prepared(tmp_path, monkeypatch)
    event, now = threading.Event(), [1000]
    original_write, original_replace = publication.write_json, os.replace

    def set_stop():
        if stop == "cancel":
            event.set()
        elif stop == "deadline":
            now[0] = 1100
        else:
            owner = json.loads(setup[0].read_bytes())
            owner["binding"]["status"] = "revoked"
            setup[0].write_bytes(json.dumps(owner).encode())

    def write(path, value):
        sha = original_write(path, value)
        if not after_commit and path.name == ".receipt-pending.json":
            set_stop()
        return sha

    def replace(source, target):
        value = original_replace(source, target)
        if after_commit and Path(target).name == "receipt.json":
            set_stop()
        return value

    monkeypatch.setattr(publication, "write_json", write)
    monkeypatch.setattr(os, "replace", replace)
    if after_commit:
        result = run(setup, resume=True, event=event, now=now)
        raw = (directory(setup) / "receipt.json").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == result["receipt_sha256"]
        assert result["recovered_finalization"] is True
    else:
        with pytest.raises(SwarmError):
            run(setup, resume=True, event=event, now=now)
        assert not (directory(setup) / "receipt.json").exists()


@pytest.mark.parametrize("raw", [b'{"torn":', b'{}\n', None, "reordered"])
def test_resume_rejects_corrupted_or_noncanonical_existing_stage(tmp_path, raw):
    config = setup_case(tmp_path)
    assert child(tmp_path, "staged").returncode == 73
    path = case_directory(config) / ".receipt-pending.json"
    if raw == "reordered":
        record = json.loads(path.read_bytes())
        altered = (json.dumps(dict(reversed(list(record.items()))), ensure_ascii=False,
                              separators=(",", ":")) + "\n").encode("utf-8")
        assert json.loads(altered) == record and altered != path.read_bytes()
    else:
        altered = path.read_bytes() + b" " if raw is None else raw
    path.write_bytes(altered)
    result = child(tmp_path, "resume")
    assert result.returncode == 2, result.stderr
    assert path.read_bytes() == altered
    assert not (path.parent / "receipt.json").exists()
    assert not (tmp_path / "UNAUTHORIZED_CALL").exists()
