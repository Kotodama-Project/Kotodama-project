"""Public learning proposals read original execution files without modifying them."""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest environment")

from test_task_swarm_closed_loop import MeasuredBackend, setup_loop
from test_task_swarm_loop_executor_runtime import setup_executor, execute
from task_swarm.closed_loop import execute_closed_loop
from task_swarm.learning_reuse import main, propose_learning
from task_swarm.protocol import SwarmError, canonical, digest


def origin_case(directory, *, local=False, dependency=False):
    now = time.time()
    setup = setup_executor(directory, dependency=dependency) if local else setup_loop(directory, jobs=1)
    owner, file, document, payload, plan, actors = setup[:6]
    payload["objective"]["budget"]["deadline"] = now + 600
    file.write_text(canonical(payload))
    document["binding"].update(context_digest=digest(payload), expires_at=now + 1200)
    for item in document["source_checks"]:
        if Path(item["path"]).name == file.name:
            item["sha256"] = hashlib.sha256(file.read_bytes()).hexdigest()
    owner.write_text(canonical(document))
    plan["parent_input_digest"] = digest(payload)
    completed = execute(setup, clock=lambda: now) if local else execute_closed_loop(
        owner, file, plan, MeasuredBackend(payload, setup[6]), worker_actors=actors, clock=lambda: now)
    run = directory / "operations" / ("task-run-" + digest([payload["task_id"], payload["revision"]])[:32])
    index = next(i for i, claim in enumerate(completed["candidate"]["claims"])
                 if claim["claim"]["status"] == "supported")
    return owner, file, completed["receipt_sha256"], index, run


def files(directory):
    return {path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in directory.rglob("*") if path.is_file()}


def damage(database, kind):
    if kind == "missing":
        database.unlink()
    elif kind == "invalid":
        database.write_bytes(b"not a SQLite database")
    else:
        with closing(sqlite3.connect(database)) as db:
            db.execute("DROP TABLE " + kind)
            db.commit()


@pytest.mark.parametrize("local", [False, True])
@pytest.mark.parametrize("kind", ["missing", "invalid", "runs", "run_finalizations", "run_cancellations"])
def test_public_proposal_refuses_without_creating_or_repairing_files(tmp_path, local, kind):
    owner, file, anchor, index, run = origin_case(tmp_path, local=local)
    damage(run / "execution.sqlite", kind)
    before = files(tmp_path)
    with pytest.raises(SwarmError):
        propose_learning(owner, file, anchor, index)
    assert files(tmp_path) == before


@pytest.mark.parametrize("kind", ["missing", "invalid", "run_cancellations"])
def test_propose_cli_returns_typed_error_without_writes(tmp_path, capsys, kind):
    owner, file, anchor, index, run = origin_case(tmp_path)
    damage(run / "execution.sqlite", kind)
    before = files(tmp_path)
    assert main(["propose", "--owner", str(owner), "--input", str(file),
                 "--anchor", anchor, "--claim-index", str(index)]) == 2
    output = capsys.readouterr()
    assert output.out == "" and json.loads(output.err)["error"]
    assert files(tmp_path) == before


@pytest.mark.parametrize("local", [False, True])
def test_valid_proposal_keeps_original_database_and_artifacts_identical(tmp_path, local):
    owner, file, anchor, index, _ = origin_case(tmp_path, local=local)
    before = files(tmp_path)
    first = propose_learning(owner, file, anchor, index)
    assert first == propose_learning(owner, file, anchor, index)
    assert first["origin_receipt_sha256"] == anchor
    assert files(tmp_path) == before


def test_origin_never_opens_original_sqlite_even_readonly(tmp_path, monkeypatch):
    owner, file, anchor, index, run = origin_case(tmp_path, local=True)
    connect = sqlite3.connect
    calls = []
    def private_only(database, *args, **kwargs):
        assert str(run) not in str(database)
        calls.append(str(database))
        return connect(database, *args, **kwargs)
    monkeypatch.setattr(sqlite3, "connect", private_only)
    before = files(tmp_path)
    assert propose_learning(owner, file, anchor, index)["origin_receipt_sha256"] == anchor
    assert calls and files(tmp_path) == before


@pytest.mark.parametrize("cancel", [False, True])
def test_live_wal_is_read_without_changing_db_wal_or_shm(tmp_path, cancel):
    owner, file, anchor, index, run = origin_case(tmp_path)
    database = run / "execution.sqlite"
    main_before = database.read_bytes()
    with closing(sqlite3.connect(database)) as db:
        db.execute("PRAGMA wal_autocheckpoint=0")
        if cancel:
            plan = json.loads((run / "plan.json").read_text())
            record = {"version": 1, "run_id": plan["run_id"], "binding_digest": plan["binding_digest"],
                "initial_execution_plan_digest": digest(plan),
                "owner_ref": json.loads(owner.read_text())["binding"]["owner_ref"], "requested_at": time.time()}
            db.execute("INSERT INTO run_cancellations VALUES (?,?)", (plan["run_id"], canonical(record)))
        else:
            db.execute("CREATE TABLE committed_origin_marker(value TEXT)")
            db.execute("INSERT INTO committed_origin_marker VALUES ('committed')")
        db.commit()
        assert database.read_bytes() == main_before and (run / "execution.sqlite-wal").stat().st_size > 32
        before = files(tmp_path)
        if cancel:
            with pytest.raises(SwarmError, match="RUN_CANCELLED"):
                propose_learning(owner, file, anchor, index)
        else:
            assert propose_learning(owner, file, anchor, index)["origin_receipt_sha256"] == anchor
        assert files(tmp_path) == before


@pytest.mark.parametrize("mutation", ["cancel", "proof", "owner", "actor", "source", "receipt", "clock"])
def test_final_policy_after_proposal_construction_observes_current_origin(tmp_path, monkeypatch, mutation):
    from task_swarm import learning_reuse, loop_executor_runtime
    owner, file, anchor, index, run = origin_case(tmp_path, local=True)
    now = [time.time()]
    built, changed = [], []
    original_proposal, original_policy = learning_reuse._proposal, loop_executor_runtime.check_current_executor_policy
    def proposal(*args):
        value = original_proposal(*args)
        built.append(True)
        return value
    with closing(sqlite3.connect(run / "execution.sqlite")) as db:
        db.execute("PRAGMA wal_autocheckpoint=0")
        main_before = (run / "execution.sqlite").read_bytes()
        def policy(*args, **kwargs):
            original_policy(*args, **kwargs)
            if not built or changed:
                return
            changed.append(True)
            if mutation == "cancel":
                plan = json.loads((run / "plan.json").read_text())
                record = {"version": 1, "run_id": plan["run_id"], "binding_digest": plan["binding_digest"],
                    "initial_execution_plan_digest": digest(plan),
                    "owner_ref": json.loads(owner.read_text())["binding"]["owner_ref"], "requested_at": now[0]}
                db.execute("INSERT INTO run_cancellations VALUES (?,?)", (plan["run_id"], canonical(record)))
                db.commit()
                assert (run / "execution.sqlite").read_bytes() == main_before
            elif mutation == "clock":
                now[0] = json.loads(owner.read_text())["binding"]["expires_at"] + 1
            elif mutation == "actor":
                document = json.loads(owner.read_text())
                document["actors"]["worker-a"]["actor_status"] = "revoked"
                owner.write_text(canonical(document))
            else:
                proof = json.loads((run / "r0-doc-a-result.json").read_text())["receipt"]["runtime"]["paths"]["receipt"]
                path = {"proof": Path(proof), "owner": owner, "source": owner.parent / "DocA.txt",
                        "receipt": run / "receipt.json"}[mutation]
                path.write_bytes(path.read_bytes() + b"\n")
        monkeypatch.setattr(learning_reuse, "_proposal", proposal)
        monkeypatch.setattr(loop_executor_runtime, "check_current_executor_policy", policy)
        with pytest.raises(SwarmError):
            propose_learning(owner, file, anchor, index, clock=lambda: now[0])
        assert built and changed


@pytest.mark.parametrize("missing_stage", [False, True])
def test_dependency_origin_retains_its_required_database_schema(tmp_path, missing_stage):
    owner, file, anchor, index, run = origin_case(tmp_path, local=True, dependency=True)
    if missing_stage:
        damage(run / "execution.sqlite", "run_dependency_stages")
    before = files(tmp_path)
    if missing_stage:
        with pytest.raises(SwarmError):
            propose_learning(owner, file, anchor, index)
    else:
        assert propose_learning(owner, file, anchor, index)["origin_receipt_sha256"] == anchor
    assert files(tmp_path) == before


def test_expired_objective_can_be_read_with_current_owner(tmp_path):
    owner, file, anchor, index, _ = origin_case(tmp_path)
    deadline = json.loads(file.read_text())["objective"]["budget"]["deadline"]
    assert propose_learning(owner, file, anchor, index, clock=lambda: deadline + 1)["origin_receipt_sha256"] == anchor
    expiry = json.loads(owner.read_text())["binding"]["expires_at"]
    with pytest.raises(SwarmError):
        propose_learning(owner, file, anchor, index, clock=lambda: expiry + 1)


@pytest.mark.parametrize("mutation", ["missing_id", "wrong_id", "list"])
def test_saved_plan_shape_is_a_typed_refusal(tmp_path, mutation):
    owner, file, _, index, run = origin_case(tmp_path)
    plan_path = run / "plan.json"
    plan = json.loads(plan_path.read_text())
    if mutation == "missing_id":
        del plan["run_id"]
    elif mutation == "wrong_id":
        plan["run_id"] = "task-run-" + "0" * 32
    else:
        plan = []
    plan_path.write_text(canonical(plan))
    receipt_path = run / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["artifact_sha256"]["plan.json"] = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    receipt_path.write_text(canonical(receipt))
    anchor = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    before = files(tmp_path)
    with pytest.raises(SwarmError):
        propose_learning(owner, file, anchor, index)
    assert files(tmp_path) == before


@pytest.mark.parametrize("empty_wal", [False, True])
def test_committed_wal_appearing_after_initial_cut_is_refused(tmp_path, monkeypatch, empty_wal):
    from task_swarm import repair_planning
    owner, file, anchor, index, run = origin_case(tmp_path)
    database = run / "execution.sqlite"
    wal = run / "execution.sqlite-wal"
    assert not wal.exists()
    if empty_wal:
        wal.touch()
    before_main = database.read_bytes()
    actual, changed = repair_planning._inspection_cut, []
    with closing(sqlite3.connect(database)) as db:
        def cut(database, destination, **kwargs):
            result = actual(database, destination, **kwargs)
            if destination.name.startswith("kotodama-learning-read-") and not changed:
                plan = json.loads((run / "plan.json").read_text())
                record = {"version": 1, "run_id": plan["run_id"], "binding_digest": plan["binding_digest"],
                    "initial_execution_plan_digest": digest(plan),
                    "owner_ref": json.loads(owner.read_text())["binding"]["owner_ref"], "requested_at": time.time()}
                db.execute("INSERT INTO run_cancellations VALUES (?,?)", (plan["run_id"], canonical(record)))
                db.commit()
                changed.append(files(tmp_path))
                assert database.read_bytes() == before_main and wal.stat().st_size > 32
            return result
        monkeypatch.setattr(repair_planning, "_inspection_cut", cut)
        with pytest.raises(SwarmError):
            propose_learning(owner, file, anchor, index)
        assert changed and files(tmp_path) == changed[0]


def test_other_readers_can_create_empty_wal_and_touch_derived_shm(tmp_path, monkeypatch):
    from task_swarm import learning_reuse
    owner, file, anchor, index, run = origin_case(tmp_path)
    original, opened = learning_reuse._proposal, []
    database = run / "execution.sqlite"
    before_main = database.read_bytes()
    def proposal(*args):
        value = original(*args)
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
            assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
            opened.append(True)
        return value
    monkeypatch.setattr(learning_reuse, "_proposal", proposal)
    assert propose_learning(owner, file, anchor, index)["origin_receipt_sha256"] == anchor
    assert opened and database.read_bytes() == before_main


def test_reuse_writer_connections_close_before_subsequent_origin_reads(tmp_path, monkeypatch):
    from test_task_swarm_learning_reuse import setup_reuse, allow
    from task_swarm.state import SwarmState
    original, connections = SwarmState._connect, []
    def connect(state):
        db = original(state)
        if str(tmp_path) in str(state.db_path):
            connections.append(db)
        return db
    monkeypatch.setattr(SwarmState, "_connect", connect)
    reuse, *_ = setup_reuse(tmp_path)
    allow(reuse)
    assert connections
    for db in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            db.execute("SELECT 1")


@pytest.mark.parametrize("stored", [None, 1, b"not JSON", "[" * 2000])
def test_malformed_saved_plan_column_is_a_typed_refusal(tmp_path, stored):
    owner, file, anchor, index, run = origin_case(tmp_path)
    with closing(sqlite3.connect(run / "execution.sqlite")) as db:
        db.execute("DROP TABLE runs")
        db.execute("CREATE TABLE runs(run_id TEXT PRIMARY KEY, plan_json)")
        db.execute("INSERT INTO runs VALUES (?,?)", (run.name, stored))
        db.commit()
    before = files(tmp_path)
    with pytest.raises(SwarmError):
        propose_learning(owner, file, anchor, index)
    assert files(tmp_path) == before


@pytest.mark.parametrize("table,column,value", [
    ("runs", "deadline", "deadline+1"), ("jobs", "reason", "'changed'"),
    ("attempts", "epoch", "epoch+1"), ("run_extensions", "extension_json", "extension_json || ' '"),
    ("run_finalizations", "receipt_json", "receipt_json || ' '"),
])
def test_final_copy_comparison_includes_raw_core_values(tmp_path, monkeypatch, table, column, value):
    from task_swarm import learning_reuse
    owner, file, anchor, index, run = origin_case(tmp_path)
    original, changed = learning_reuse._proposal, []
    def proposal(*args):
        result = original(*args)
        with closing(sqlite3.connect(run / "execution.sqlite")) as db:
            db.execute(f"UPDATE {table} SET {column}={value}")
            db.commit()
        changed.append(files(tmp_path))
        return result
    monkeypatch.setattr(learning_reuse, "_proposal", proposal)
    with pytest.raises(SwarmError):
        propose_learning(owner, file, anchor, index)
    assert changed and files(tmp_path) == changed[0]
