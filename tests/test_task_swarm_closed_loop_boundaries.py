"""Publication, aggregation and stop-boundary regressions for the local loop."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest job")

from test_task_swarm_closed_loop import MeasuredBackend, setup_loop
from task_swarm import closed_loop as coordinator
from task_swarm.protocol import SwarmError, canonical, digest
from task_swarm.state import SwarmState


def complete_setup(path):
    setup = setup_loop(path)
    setup[4]["jobs"][1].update(job_id="memory", selected_spans=[{
        "source_key": setup[6]["key"], "source_revision": setup[6]["revision"],
        "start": 9, "end": 17}])
    return setup


def run(setup, backend=None, *, event=None, clock=None):
    return coordinator.execute_closed_loop(setup[0], setup[1], setup[4],
        backend or MeasuredBackend(setup[3], setup[6]), worker_actors=setup[5],
        cancel_event=event, clock=clock or (lambda: 1000))


def directory(setup):
    return Path(setup[2]["storage"]["root"]) / (
        "task-run-" + digest([setup[3]["task_id"], setup[3]["revision"]])[:32])


def test_aggregate_33_spans_rejects_before_directory_and_allows_valid_retry(tmp_path):
    setup = complete_setup(tmp_path)
    valid = copy.deepcopy(setup[4])
    spans = [{"source_key": setup[6]["key"], "source_revision": setup[6]["revision"],
              "start": n, "end": n + 1} for n in range(33)]
    setup[4]["jobs"][0]["selected_spans"] = spans[:17]
    setup[4]["jobs"][1]["selected_spans"] = spans[17:]
    backend = MeasuredBackend(setup[3], setup[6])
    with pytest.raises(SwarmError, match="LOOP_CONTEXT_LIMIT"):
        run(setup, backend)
    assert not backend.inputs
    assert not directory(setup).exists()
    setup[4].clear()
    setup[4].update(valid)
    assert run(setup)["receipt"]["review_passed"] is True


def test_opposite_completion_order_has_identical_candidate_and_learning_bytes(tmp_path, monkeypatch):
    class Conflicts(MeasuredBackend):
        def produce(self, delivered, *args, **kwargs):
            result = super().produce(delivered, *args, **kwargs)
            result["result"]["conflicts"] = [delivered["job_id"] + " conflict"]
            return result

    values = []
    for reverse in (False, True):
        path = tmp_path / str(reverse)
        path.mkdir()
        setup = complete_setup(path)
        monkeypatch.setattr(coordinator, "as_completed", lambda fs: iter(list(fs)[::(-1 if reverse else 1)]))
        result = run(setup, Conflicts(setup[3], setup[6]))
        values.append(tuple(canonical(result[key]) for key in ("candidate", "learning_candidate")))
    assert values[0] == values[1]


@pytest.mark.parametrize("stop", ["cancel", "deadline", "owner"])
def test_receipt_staging_rechecks_eligibility_before_publication(tmp_path, monkeypatch, stop):
    setup = complete_setup(tmp_path)
    event, now = threading.Event(), [1000]
    original = coordinator.write_json

    def write(path, value):
        sha = original(path, value)
        if value.get("coordinator") == "closed_loop_v1":
            if stop == "cancel":
                event.set()
            elif stop == "deadline":
                now[0] = 1100
            else:
                changed = json.loads(setup[0].read_bytes())
                changed["binding"]["status"] = "revoked"
                setup[0].write_bytes(json.dumps(changed).encode())
        return sha

    monkeypatch.setattr(coordinator, "write_json", write)
    with pytest.raises(SwarmError):
        run(setup, event=event, clock=lambda: now[0])
    assert not (directory(setup) / "receipt.json").exists()


@pytest.mark.parametrize("stop", ["cancel", "deadline", "owner"])
def test_receipt_commit_returns_anchor_despite_later_stop(tmp_path, monkeypatch, stop):
    setup = complete_setup(tmp_path)
    event, now = threading.Event(), [1000]
    original_write, original_replace = coordinator.write_json, os.replace

    def later_stop():
        if stop == "cancel":
            event.set()
        elif stop == "deadline":
            now[0] = 1100
        else:
            changed = json.loads(setup[0].read_bytes())
            changed["binding"]["status"] = "revoked"
            setup[0].write_bytes(json.dumps(changed).encode())

    def write(path, value):
        sha = original_write(path, value)
        if Path(path).name == "receipt.json":
            later_stop()
        return sha

    def replace(source, target):
        result = original_replace(source, target)
        if Path(target).name == "receipt.json":
            later_stop()
        return result

    monkeypatch.setattr(coordinator, "write_json", write)
    monkeypatch.setattr(os, "replace", replace)
    result = run(setup, event=event, clock=lambda: now[0])
    raw = (directory(setup) / "receipt.json").read_bytes()
    assert result["receipt_sha256"] == hashlib.sha256(raw).hexdigest()
    assert json.loads(raw) == result["receipt"]
    assert not (directory(setup) / ".receipt-pending.json").exists()


@pytest.mark.parametrize("phase", ["after_begin", "after_update"])
@pytest.mark.parametrize("stop", ["cancel", "deadline"])
def test_accept_rechecks_stop_in_transaction_and_rolls_back(tmp_path, monkeypatch, phase, stop):
    setup = complete_setup(tmp_path)
    event, now, accepting = threading.Event(), [1000], [False]
    original_accept, original_transaction = SwarmState.accept, SwarmState._transaction

    def set_stop():
        event.set() if stop == "cancel" else now.__setitem__(0, 1100)

    def accept(self, *args, **kwargs):
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
                conn.set_trace_callback(lambda sql: set_stop() if sql.startswith("UPDATE jobs SET state = 'accepted'") else None)
        return conn

    monkeypatch.setattr(SwarmState, "accept", accept)
    monkeypatch.setattr(SwarmState, "_transaction", transaction)
    with pytest.raises(SwarmError, match="RUN_CANCELLED|DEADLINE_EXPIRED"):
        run(setup, event=event, clock=lambda: now[0])
    with sqlite3.connect(directory(setup) / "execution.sqlite") as conn:
        assert conn.execute("SELECT count(*) FROM jobs WHERE state='accepted'").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM attempts WHERE state='accepted'").fetchone()[0] == 0
    assert not (directory(setup) / "receipt.json").exists()


def test_exactly_32_unique_spans_and_duplicate_across_jobs_are_admitted(tmp_path):
    setup = complete_setup(tmp_path)
    spans = [{"source_key": setup[6]["key"], "source_revision": setup[6]["revision"],
              "start": n, "end": n + 1} for n in range(30)]
    # Include complete quote spans for the worker fixture, yielding 32 unique.
    full = [setup[4]["jobs"][0]["selected_spans"][0], setup[4]["jobs"][1]["selected_spans"][0]]
    setup[4]["jobs"][0]["selected_spans"] = spans[:15] + full
    setup[4]["jobs"][1]["selected_spans"] = full[::-1] + spans[15:]
    assert run(setup)["receipt"]["review_passed"] is True


def test_staged_receipt_tampering_is_refused_without_publication(tmp_path, monkeypatch):
    setup = complete_setup(tmp_path)
    original = coordinator.write_json

    def write(path, value):
        sha = original(path, value)
        if value.get("coordinator") == "closed_loop_v1":
            Path(path).write_bytes(b"{}\n")
        return sha

    monkeypatch.setattr(coordinator, "write_json", write)
    with pytest.raises(SwarmError, match="RUN_OUTPUT_READBACK"):
        run(setup)
    assert not (directory(setup) / "receipt.json").exists()
    assert not (directory(setup) / ".receipt-pending.json").exists()
