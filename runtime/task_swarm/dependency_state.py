"""Atomic prerequisite evidence in the existing execution ledger."""
from __future__ import annotations

import json
import threading

from . import protocol
from .dependency_contract import REVIEW_ID, attempt_proof, check_stage, execution_version
from .task_contract import require


def stage_row(state, conn, run):
    plan = state._plan_from_run(run)
    if execution_version(plan) != 3:
        return None
    row = conn.execute("SELECT stage_json FROM run_dependency_stages WHERE run_id=?", (run["run_id"],)).fetchone()
    if row is None:
        return None
    try:
        stage = check_stage(json.loads(row[0]), plan)
    except (ValueError, KeyError, TypeError) as exc:
        raise protocol.SwarmError("LOOP_RELEASE_INVALID", "stored stage is malformed") from exc
    cert = stage["certificate"]
    for name in ("a", "review"):
        job = conn.execute("SELECT * FROM jobs WHERE run_id=? AND job_id=?", (run["run_id"], cert[name]["job_id"])).fetchone()
        attempts = conn.execute("SELECT * FROM attempts WHERE run_id=? AND job_id=? ORDER BY attempt", (run["run_id"], cert[name]["job_id"])).fetchall()
        require(job is not None and len(attempts) == 1 and attempts[0]["outcome"] == "candidate"
                and attempt_proof(state._attempt_public(attempts[0])) == cert[name]
                and job["state"] in ("reported", "accepted"), "LOOP_RELEASE_CHANGED")
        if name == "a" and stage["status"] == "released":
            require(job["state"] == attempts[0]["state"] == "accepted"
                    and job["accepted_digest"] == cert[name]["result_digest"]
                    and job["verification_ref"] == stage["verification_ref"]
                    and job["accepted_owner_ref"] == cert["owner_ref"]
                    and job["accepted_at"] == stage["accepted_at"], "LOOP_RELEASE_CHANGED")
    require(cert["a"]["worker_ref"] != cert["review"]["worker_ref"], "REVIEW_NOT_INDEPENDENT")
    return stage


def read_stage(state, run_id):
    conn = state._connect()
    try:
        conn.execute("BEGIN")
        return stage_row(state, conn, state._get_run(conn, run_id))
    finally:
        conn.close()


def preaccepted_proof(stage):
    cert = stage["certificate"]
    return {cert["a_job_id"]: {"result_digest": cert["a"]["result_digest"],
        "verification_ref": stage["verification_ref"], "owner_ref": cert["owner_ref"],
        "accepted_at": stage["accepted_at"]}}


def claim_allowed(state, conn, run, job, worker):
    plan = state._plan_from_run(run)
    if execution_version(plan) != 3:
        return True
    if conn.execute("SELECT 1 FROM attempts WHERE run_id=? AND job_id=? LIMIT 1",
                    (run["run_id"], job["job_id"])).fetchone():
        return False
    stage = stage_row(state, conn, run)
    if stage is None:
        # A is the sole dependency-free work job in this closed profile.
        return (job["kind"] == "work" and not json.loads(job["dependencies_json"])) or job["job_id"] == REVIEW_ID
    if stage["status"] == "blocked":
        return False
    cert = stage["certificate"]
    if job["job_id"] in (cert["a_job_id"], REVIEW_ID):
        return False
    if job["kind"] == "work":
        require(json.loads(job["dependencies_json"]) == [cert["a_job_id"]], "LOOP_RELEASE_INVALID")
        require(worker != cert["review"]["worker_ref"], "REVIEW_NOT_INDEPENDENT")
    return True


def commit_stage(state, run_id, stage, expected_state_digest, cancel_event):
    require(cancel_event is None or isinstance(cancel_event, threading.Event), "RUN_CANCELLATION_INVALID")
    prefetched = state._prefetch_owner(state._now(), run_id=run_id)
    conn, ok = state._transaction(), False
    try:
        run = state._get_run(conn, run_id)
        state._require_not_cancelled(conn, run)
        owner = state._run_owner(run, state._now(), prefetched)
        plan = state._plan_from_run(run)
        check_stage(stage, plan)
        old = stage_row(state, conn, run)
        if old is not None:
            require(old == stage, "LOOP_RELEASE_IMMUTABLE")
            ok = True
            return old
        require(protocol.digest(state._finalization_evidence(conn, run_id)) == expected_state_digest,
                "LOOP_RELEASE_CHANGED")
        require(not conn.execute("SELECT 1 FROM run_finalizations WHERE run_id=?", (run_id,)).fetchone(),
                "FINALIZATION_SEALED")
        cert = stage["certificate"]
        require(cert["a"]["worker_ref"] != cert["review"]["worker_ref"]
                and owner["owner_ref"] == cert["owner_ref"]
                and owner["owner_ref"] not in (cert["a"]["worker_ref"], cert["review"]["worker_ref"]),
                "REVIEW_NOT_INDEPENDENT")
        for name in ("a", "review"):
            proof = cert[name]
            job = conn.execute("SELECT * FROM jobs WHERE run_id=? AND job_id=?", (run_id, proof["job_id"])).fetchone()
            attempts = conn.execute("SELECT * FROM attempts WHERE run_id=? AND job_id=?", (run_id, proof["job_id"])).fetchall()
            require(job is not None and job["state"] == "reported" and len(attempts) == 1
                    and attempts[0]["state"] == "reported" and attempts[0]["outcome"] == "candidate"
                    and attempt_proof(state._attempt_public(attempts[0])) == proof, "LOOP_RELEASE_CHANGED")
        if stage["status"] == "released":
            stage = {**stage, "accepted_at": state._now()}
            conn.execute("UPDATE attempts SET state='accepted',updated_at=? WHERE token=?",
                         (stage["accepted_at"], cert["a"]["token"]))
            conn.execute("UPDATE jobs SET state='accepted',accepted_digest=?,verification_ref=?,accepted_owner_ref=?,accepted_at=? WHERE run_id=? AND job_id=?",
                (cert["a"]["result_digest"], stage["verification_ref"], owner["owner_ref"], stage["accepted_at"], run_id, cert["a_job_id"]))
        conn.execute("INSERT INTO run_dependency_stages(run_id,stage_json) VALUES (?,?)", (run_id, protocol.canonical(stage)))
        # This final observation fences all preceding writes in this transaction.
        require(cancel_event is None or not cancel_event.is_set(), "RUN_CANCELLED")
        require(state._now() < float(run["deadline"]), "DEADLINE_EXPIRED")
        ok = True
        return stage
    finally:
        state._finish(conn, ok)
