"""Repair admission reuses the same immutable plan, owner and attempt ledger."""
import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest job")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from task_swarm.protocol import SwarmError, digest, validate_binding
from task_swarm.state import SwarmState


def job(name, kind="work", dependencies=()):
    return {"job_id": name, "kind": kind, "dependencies": list(dependencies),
            "exclusive_keys": [], "payload_ref": "ref/payload/"+name, "payload_digest": "a"*64}


def setup_state(tmp_path, *, budget=6, work_count=2):
    owner = {"task_id": "task-fixture", "revision": 1, "context_digest": "a"*64,
             "owner_ref": "owner", "active_home": "fixture", "authority_ref": "authority",
             "capability_ref": "research", "expires_at": 2000, "status": "active"}
    now = [1000]
    state = SwarmState(tmp_path/"execution.sqlite", lambda _: copy.deepcopy(owner), clock=lambda: now[0])
    work_ids = ["r0-a", "r0-b", "r0-c"][:work_count]
    plan = state.create_run({"run_id": "run-fixture", "task_id": owner["task_id"], "binding_digest": digest(validate_binding(owner, now=now[0])),
        "budget": {"attempt_budget": budget, "concurrency": 2, "deadline": 1500, "verifier_reserve": 1},
        "jobs": [*[job(name) for name in work_ids], job("r0-critic", "review", work_ids)]})
    assignments = [("worker-" + name, name) for name in work_ids] + [("critic", "r0-critic")]
    for actor, expected in assignments:
        lease = state.claim(plan["run_id"], actor)
        assert lease["job_id"] == expected
        state.report(lease["token"], "ref/result/"+expected, "b"*64, "candidate", "ref/runtime/"+expected)
    extension = {"round": 1, "initial_plan_digest": digest(plan), "critic_job_id": "r0-critic",
        "critic_result_digest": "b"*64, "proposal_digest": "c"*64,
        "jobs": [job("r1-repair"), job("r1-critic", "review", [*work_ids, "r1-repair"])]}
    return state, plan, extension, owner, now


@pytest.mark.parametrize("budget,retry_allowed", [(6, False), (7, True)])
def test_repair_retry_preserves_an_attempt_for_the_pending_critic(tmp_path, budget, retry_allowed):
    state, plan, extension, owner, now = setup_state(tmp_path, budget=budget, work_count=3)
    state.extend_run(plan["run_id"], extension)
    lease = state.claim(plan["run_id"], "repair-worker")
    assert lease["job_id"] == "r1-repair"
    state.fail(lease["token"], "transient fixture failure", retryable=True)
    restarted = SwarmState(tmp_path / "execution.sqlite", lambda _: owner, clock=lambda: now[0])
    before = restarted.snapshot(plan["run_id"])
    assert before["budget"]["remaining_work_attempts"] == int(retry_allowed)
    retry = restarted.claim(plan["run_id"], "repair-worker")
    if retry_allowed:
        assert retry["job_id"] == "r1-repair"
        restarted.report(retry["token"], "repair-result", "d" * 64, "candidate", "repair-runtime")
        review = restarted.claim(plan["run_id"], "independent-critic")
        assert review["job_id"] == "r1-critic"
        restarted.report(review["token"], "review-result", "e" * 64, "candidate", "review-runtime")
        assert restarted.snapshot(plan["run_id"])["budget"]["attempts_used"] == budget
    else:
        assert retry is None
        after = restarted.snapshot(plan["run_id"])
        assert after["budget"]["attempts_used"] == 5
        assert after["budget"]["remaining_attempts"] == 1
        assert after["jobs"]["r1-critic"]["state"] == "pending"
        assert after["jobs"]["r1-critic"]["attempt_count"] == 0


def test_extension_persists_normalized_jobs_and_replays_semantic_list_order(tmp_path):
    state, plan, extension, owner, now = setup_state(tmp_path)
    extension["jobs"][0]["exclusive_keys"] = ["resource-z", "resource-a"]
    extension["jobs"][1]["dependencies"].reverse()
    normalized = copy.deepcopy(extension)
    for value in normalized["jobs"]:
        value["dependencies"].sort()
        value["exclusive_keys"].sort()
    assert state.extend_run(plan["run_id"], extension) == normalized
    assert state.extension(plan["run_id"]) == normalized
    snapshot = state.snapshot(plan["run_id"])
    for value in normalized["jobs"]:
        assert snapshot["jobs"][value["job_id"]]["dependencies"] == value["dependencies"]
        assert snapshot["jobs"][value["job_id"]]["exclusive_keys"] == value["exclusive_keys"]
    restarted = SwarmState(tmp_path / "execution.sqlite", lambda _: owner, clock=lambda: now[0])
    assert restarted.extend_run(plan["run_id"], normalized) == normalized
    assert restarted.extend_run(plan["run_id"], extension) == normalized
    assert restarted.snapshot(plan["run_id"])["budget"]["attempts_used"] == 3
    assert len(restarted.snapshot(plan["run_id"])["jobs"]) == 5


def test_concurrent_same_round_is_idempotent_and_budget_is_not_refilled(tmp_path):
    state, plan, extension, owner, now = setup_state(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: state.extend_run(plan["run_id"], extension), range(2)))
    assert outcomes == [extension, extension]
    assert state.create_run(plan) == plan
    assert state.snapshot(plan["run_id"])["budget"]["attempts_used"] == 3
    assert len(state.snapshot(plan["run_id"])["jobs"]) == 5
    assert state.extension(plan["run_id"]) == extension
    restarted = SwarmState(tmp_path/"execution.sqlite", lambda _: owner, clock=lambda: now[0])
    lease = restarted.claim(plan["run_id"], "worker-a")
    assert lease["job_id"] == "r1-repair"
    restarted.report(lease["token"], "repair-result", "d"*64, "candidate", "repair-runtime")
    assert restarted.claim(plan["run_id"], "worker-a") is None  # author cannot be its own critic
    review = restarted.claim(plan["run_id"], "critic")
    assert review["job_id"] == "r1-critic"
    restarted.report(review["token"], "review-result", "e"*64, "candidate", "review-runtime")
    assert restarted.snapshot(plan["run_id"])["budget"]["attempts_used"] == 5
    assert restarted.snapshot(plan["run_id"])["jobs"]["r0-critic"]["state"] == "reported"
    assert restarted.claim(plan["run_id"], "new-worker") is None


@pytest.mark.parametrize("change,code", [
    (lambda e: e.update(round=2), "ROUND_LIMIT"),
    (lambda e: e.update(round=True), "ROUND_LIMIT"),
    (lambda e: e.update(initial_plan_digest="d"*64), "ROUND_CONFLICT"),
    (lambda e: e.update(critic_result_digest="d"*64), "ROUND_CRITIC_REQUIRED"),
    (lambda e: e.update(critic_job_id="r0-a"), "ROUND_CRITIC_REQUIRED"),
    (lambda e: e.update(jobs=None), "INVALID_PLAN"),
    (lambda e: e.update(jobs=[job("r1-critic", "review", ["r0-a", "r0-b"])]), "INVALID_PLAN"),
    (lambda e: e["jobs"][0].update(dependencies=["r0-critic"]), "INVALID_PLAN"),
    (lambda e: e["jobs"][1].update(dependencies=["r1-repair"]), "INVALID_PLAN"),
    (lambda e: e["jobs"][0].update(job_id="r0-a"), "INVALID_PLAN"),
])
def test_invalid_round_cannot_leave_partial_jobs(tmp_path, change, code):
    state, plan, extension, _, _ = setup_state(tmp_path)
    change(extension)
    with pytest.raises(SwarmError, match=code):
        state.extend_run(plan["run_id"], extension)
    assert state.extension(plan["run_id"]) is None
    assert len(state.snapshot(plan["run_id"])["jobs"]) == 3


def test_insufficient_remaining_attempts_and_expired_deadline_refuse_the_entire_round(tmp_path):
    state, plan, extension, _, now = setup_state(tmp_path, budget=4)
    with pytest.raises(SwarmError, match="ROUND_BUDGET"):
        state.extend_run(plan["run_id"], extension)
    now[0] = 1501
    with pytest.raises(SwarmError, match="ROUND_BUDGET"):
        state.extend_run(plan["run_id"], extension)
    assert state.extension(plan["run_id"]) is None
    assert len(state.snapshot(plan["run_id"])["jobs"]) == 3


def test_changed_owner_refuses_a_prepared_repair(tmp_path):
    state, plan, extension, owner, _ = setup_state(tmp_path)
    owner["revision"] = 2
    with pytest.raises(SwarmError, match="STALE_BINDING"):
        state.extend_run(plan["run_id"], extension)
    assert state.extension(plan["run_id"]) is None


def test_live_lease_and_unsettled_work_refuse_repair(tmp_path):
    state, plan, extension, _, _ = setup_state(tmp_path)
    # Simulate an interrupted job with a persisted outstanding lease. Admission
    # must not assume another process has stopped or issue replacement work.
    with state._connect() as db:
        db.execute("UPDATE jobs SET state='leased' WHERE run_id=? AND job_id='r0-a'", (plan["run_id"],))
    with pytest.raises(SwarmError, match="ROUND_BUSY"):
        state.extend_run(plan["run_id"], extension)
    with state._connect() as db:
        db.execute("UPDATE jobs SET state='pending' WHERE run_id=? AND job_id='r0-a'", (plan["run_id"],))
    with pytest.raises(SwarmError, match="ROUND_UNSETTLED"):
        state.extend_run(plan["run_id"], extension)
    assert state.extension(plan["run_id"]) is None
