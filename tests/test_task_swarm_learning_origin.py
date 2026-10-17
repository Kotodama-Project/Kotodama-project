"""A warmed real-child origin still reads current evidence at every guard."""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import threading

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest environment")

from test_task_swarm_loop_executor_runtime import setup_executor, execute
from task_swarm import loop_executor_runtime
from task_swarm.learning_reuse import ReuseOwner, propose_learning, purpose_digest, with_learning_source
from task_swarm.protocol import SwarmError, canonical, digest


@pytest.fixture(scope="module")
def origin(tmp_path_factory):
    setup = setup_executor(tmp_path_factory.mktemp("retained-origin"))
    completed = execute(setup)
    index = next(i for i, claim in enumerate(completed["candidate"]["claims"]) if claim["claim"]["text"] == "5")
    proposal = propose_learning(setup[0], setup[1], completed["receipt_sha256"], index, clock=lambda: 1000)
    payload = copy.deepcopy(setup[3])
    payload["task_id"] = "task-00000000-0000-4000-8000-000000000002"
    payload = with_learning_source(payload, proposal)
    owner, file = setup[0].with_name("target-owner.json"), setup[1].with_name("target-input.json")
    file.write_text(canonical(payload))
    document = copy.deepcopy(setup[2])
    area = owner.parent / "target-operations"
    area.mkdir()
    document["binding"].update(task_id=payload["task_id"], context_digest=digest(payload), active_home=str(area))
    document["storage"] = {"root": str(area), "mailbox": str(area/"mailbox.sqlite"), "payloads": str(area/"payloads")}
    document["source_checks"].append({"path": str(file), "sha256": hashlib.sha256(file.read_bytes()).hexdigest()})
    document["learning_reuse"] = {"version": 1, "grant_ref": "ref/grant/retained-origin",
        "policy_revision_ref": "ref/policy/retained-origin", "proposal_digest": digest(proposal),
        "origin_receipt_sha256": completed["receipt_sha256"], "target_context_digest": digest(payload),
        "purpose_digest": purpose_digest(payload), "reviewer_ref": "verifier", "expires_at": document["binding"]["expires_at"]}
    owner.write_text(canonical(document))
    reuse = ReuseOwner(setup[0], setup[1], completed["receipt_sha256"], owner, file, proposal, clock=lambda: 1000)
    reuse.review("ref/review/retained-origin", "verifier", "allow", "Verified actual local observation.")
    decision = reuse.decide(document["binding"]["owner_ref"], "ref/review/retained-origin", "allow",
                            "ref/decision/retained-origin", expected_generation=0)
    return reuse, digest(decision), setup


def test_concurrent_current_reuses_semantics_but_reads_policy_each_time(origin, monkeypatch):
    reuse, decision, _ = origin
    actual_policy, calls, lock = loop_executor_runtime.check_current_executor_policy, [], threading.Lock()
    def policy(*args, **kwargs):
        actual_policy(*args, **kwargs)
        with lock:
            calls.append(threading.get_ident())
    def no_deep_read(*args, **kwargs):
        raise AssertionError("immutable semantic proof was reinterpreted")
    monkeypatch.setattr(loop_executor_runtime, "check_current_executor_policy", policy)
    monkeypatch.setattr(loop_executor_runtime, "verify_loop_response", no_deep_read)
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert all(digest(result) == decision for result in pool.map(reuse.current, [decision] * 6))
    assert len(calls) == 6 and len(set(calls)) > 1


def test_last_policy_cannot_change_any_pinned_proof_or_receipt(origin, monkeypatch):
    reuse, decision, _ = origin
    evidence = reuse._verified_origin.executor.evidence
    pins = {*evidence.proof_pins, *evidence.document_pins, *evidence.receipt_pins}
    actual = loop_executor_runtime.check_current_executor_policy
    for path in pins:
        raw = path.read_bytes()
        def policy(*args, **kwargs):
            actual(*args, **kwargs)
            path.write_bytes(raw + b"\n")
        monkeypatch.setattr(loop_executor_runtime, "check_current_executor_policy", policy)
        try:
            with pytest.raises(SwarmError):
                reuse.current(decision)
        finally:
            path.write_bytes(raw)


@pytest.mark.parametrize("table,column,value", [
    ("attempts", "epoch", "epoch+1"), ("jobs", "reason", "'changed'"),
    ("runs", "deadline", "deadline+1"), ("run_extensions", "extension_json", "extension_json || ' '"),
    ("runs", "plan_json", "'broken'"), ("runs", "plan_json", "'[]'"),
    ("run_finalizations", "checkpoint_json", "checkpoint_json || ' '"),
    ("run_finalizations", "receipt_json", "receipt_json || ' '"),
    ("learning_reuse_decisions", "document_digest", "'changed'"),
    ("learning_reuse_reviews", "document_digest", "'changed'"),
])
def test_last_policy_cannot_change_live_db(origin, monkeypatch, table, column, value):
    reuse, decision, _ = origin
    actual = loop_executor_runtime.check_current_executor_policy
    with closing(sqlite3.connect(reuse.state.db_path)) as db, db:
        old = db.execute(f"SELECT rowid,{column} FROM {table}").fetchall()
    assert old
    def policy(*args, **kwargs):
        actual(*args, **kwargs)
        with closing(sqlite3.connect(reuse.state.db_path)) as db, db:
            db.execute(f"UPDATE {table} SET {column}={value}")
    monkeypatch.setattr(loop_executor_runtime, "check_current_executor_policy", policy)
    try:
        with pytest.raises(SwarmError):
            reuse.current(decision)
    finally:
        with closing(sqlite3.connect(reuse.state.db_path)) as db, db:
            db.executemany(f"UPDATE {table} SET {column}=? WHERE rowid=?", [(value, row) for row, value in old])


def test_legal_decisions_do_not_change_execution_cut_and_latest_head_wins(origin):
    reuse, decision, _ = origin
    cut = reuse._verified_origin.cut
    owner = reuse._scope()[2]["owner_ref"]
    latest = reuse.decide(owner, "ref/review/retained-origin", "allow", "ref/decision/retained-second", expected_generation=1)
    try:
        assert reuse.state.completed_evidence_cut(reuse._verified_origin.executor.plan["run_id"]) == cut
        assert reuse.current(digest(latest)) == latest
        with pytest.raises(SwarmError, match="REUSE_DECISION_STALE"):
            reuse.current(decision)
    finally:
        # Fixture restoration only. The production API never deletes history.
        with closing(sqlite3.connect(reuse.state.db_path)) as db, db:
            db.execute("DELETE FROM learning_reuse_decisions WHERE generation=2")


def test_mutable_proposal_and_current_clock_are_not_cached(origin):
    reuse, decision, _ = origin
    saved = copy.deepcopy(reuse.proposal)
    try:
        reuse.proposal["selected"]["claim"]["text"] = "999"
        with pytest.raises(SwarmError, match="REUSE_PROPOSAL_CHANGED"):
            reuse.current(decision)
    finally:
        reuse.proposal = saved
    try:
        reuse.clock = lambda: 1201
        with pytest.raises(SwarmError):
            reuse.current(decision)
    finally:
        reuse.clock = lambda: 1000


def test_diagnostics_and_path_topology_still_have_the_original_read_contract(origin):
    reuse, decision, _ = origin
    base, attempt, sessions, diagnostics, remaining = reuse._verified_origin.layouts[0]
    raw = diagnostics.read_bytes()
    try:
        diagnostics.write_bytes(b"diagnostic text may change")
        reuse.current(decision)
        diagnostics.write_bytes(b"x" * (remaining + 1))
        with pytest.raises(SwarmError):
            reuse.current(decision)
        diagnostics.unlink()
        with pytest.raises(SwarmError):
            reuse.current(decision)
    finally:
        diagnostics.write_bytes(raw)
    for directory in (attempt, sessions):
        renamed = directory.with_name(directory.name + "-moved")
        directory.rename(renamed)
        try:
            try:
                directory.symlink_to(renamed, target_is_directory=True)
            except OSError:
                pytest.skip("directory symlinks unavailable")
            with pytest.raises(SwarmError):
                reuse.current(decision)
        finally:
            if directory.is_symlink():
                directory.unlink()
            renamed.rename(directory)


def test_missing_database_is_not_recreated_by_a_warm_reader(origin):
    reuse, decision, _ = origin
    database = Path(reuse.state.db_path)
    moved = database.with_name("execution-held.sqlite")
    database.rename(moved)
    try:
        with pytest.raises(SwarmError):
            reuse.current(decision)
        assert not database.exists()
    finally:
        moved.rename(database)


@pytest.mark.parametrize("mutation", ["owner", "actor", "source", "cancel", "clock"])
def test_last_policy_rechecks_authority_and_cancel(origin, monkeypatch, mutation):
    reuse, decision, setup = origin
    path = setup[0] if mutation in {"owner", "actor"} else setup[0].parent / "DocA.txt"
    raw = path.read_bytes()
    actual = loop_executor_runtime.check_current_executor_policy
    executor = reuse._verified_origin.executor
    def policy(*args, **kwargs):
        actual(*args, **kwargs)
        if mutation == "actor":
            value = json.loads(raw)
            value["actors"]["worker-a"]["actor_status"] = "revoked"
            path.write_text(canonical(value))
        elif mutation in {"owner", "source"}:
            path.write_bytes(raw + b"\n")
        elif mutation == "clock":
            reuse.clock = lambda: 1201
        else:
            plan = executor.plan
            record = {"version": 1, "run_id": plan["run_id"], "binding_digest": plan["binding_digest"],
                "initial_execution_plan_digest": digest(plan), "owner_ref": executor.owner.read_task()["owner_ref"],
                "requested_at": 1000}
            with closing(sqlite3.connect(reuse.state.db_path)) as db, db:
                db.execute("INSERT INTO run_cancellations VALUES (?,?)", (plan["run_id"], canonical(record)))
    monkeypatch.setattr(loop_executor_runtime, "check_current_executor_policy", policy)
    try:
        with pytest.raises(SwarmError):
            reuse.current(decision)
    finally:
        path.write_bytes(raw)
        reuse.clock = lambda: 1000
        with closing(sqlite3.connect(reuse.state.db_path)) as db, db:
            db.execute("DELETE FROM run_cancellations")


def test_initial_cut_does_not_repair_missing_schema(origin):
    reuse, _, _ = origin
    with closing(sqlite3.connect(reuse.state.db_path)) as db, db:
        db.execute("ALTER TABLE run_cancellations RENAME TO held_cancellations")
    try:
        with pytest.raises(SwarmError, match="FINALIZATION_STATE_CHANGED"):
            ReuseOwner(reuse.origin_owner, reuse.origin_input, reuse.anchor, reuse.target_owner,
                       reuse.target_input, reuse.proposal, clock=lambda: 1000)
        with closing(sqlite3.connect(reuse.state.db_path)) as db, db:
            assert not db.execute("SELECT name FROM sqlite_master WHERE name='run_cancellations'").fetchall()
    finally:
        with closing(sqlite3.connect(reuse.state.db_path)) as db, db:
            db.execute("ALTER TABLE held_cancellations RENAME TO run_cancellations")


def test_write_cas_fingerprint_does_not_connect_to_a_database(origin, monkeypatch):
    def refuse_connection(*args, **kwargs):
        raise AssertionError("fingerprint must not open a nested database")
    monkeypatch.setattr(sqlite3, "connect", refuse_connection)
    assert len(origin[0]._authority_fingerprint()) == 64
