"""Finite dependency policy and state transitions; no external workers."""
import copy
import json
import sys
import threading
from pathlib import Path

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest job")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from task_swarm.closed_loop_contract import validate_plan
from task_swarm.dependency_contract import descriptor, attempt_proof
from task_swarm.protocol import SwarmError, digest, validate_binding
from task_swarm.state import SwarmState
from test_task_swarm_closed_loop import setup_loop


def dependency_setup(tmp_path):
    setup = setup_loop(tmp_path)
    spec = setup[4]
    spec["version"] = 2
    spec["jobs"][0]["requires"] = []
    spec["jobs"][1]["requires"] = [spec["jobs"][0]["job_id"]]
    return setup


def plan_schema():
    from jsonschema import Draft202012Validator
    path = Path(__file__).resolve().parents[1] / "schemas/task-swarm-plan.schema.json"
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


def test_actual_execution_plan_matches_public_schema(tmp_path):
    from test_task_swarm_dependency_loop import setup_dependency, Calculation
    from test_task_swarm_closed_loop import execute
    setup = setup_dependency(tmp_path)
    result = execute(setup, Calculation(setup[3], setup[6]))
    directory = setup[0].parent / "operations" / result["receipt"]["run_id"]
    plan = json.loads((directory / "plan.json").read_text(encoding="utf-8"))
    assert plan["execution_contract_version"] == 3
    plan_schema().validate(plan)


def test_genuine_old_writer_plan_matches_schema_and_current_reader(tmp_path):
    # Produced by SwarmState.create_run from the pinned public old writer,
    # not made by deleting version markers from a new execution.
    path = Path(__file__).with_name("fixtures") / "task-swarm/legacy-plan-b6d8041.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["writer_commit"] == "b6d8041b0baeadbff64c982b6220b30dbdfc82b2"
    assert "execution_contract_version" not in record["plan"]
    plan_schema().validate(record["plan"])
    state = SwarmState(tmp_path / "old-plan.sqlite", lambda _: record["binding"], lambda: record["clock"])
    assert state.create_run(record["plan"]) == record["plan"]


@pytest.mark.parametrize("job_id,kind", [
    ("aaa-extra-work", "work"), ("aaa-extra-review", "review"),
    ("r1-repair-b", "work"),
])
def test_initial_dependency_plan_refuses_every_noninitial_job(tmp_path, job_id, kind):
    import sqlite3
    from contextlib import closing
    state, original, _ = state_fixture(tmp_path)
    plan = copy.deepcopy(original)
    plan["run_id"] = "extra-job-run"
    plan["jobs"].append({"job_id": job_id, "kind": kind, "dependencies": [],
                         "exclusive_keys": [], "payload_ref": "ref/extra", "payload_digest": "f" * 64})
    try:
        state.create_run(plan)
    except SwarmError as error:
        assert error.code == "LOOP_DEPENDENCY_PLAN"
    else:
        lease = state.claim(plan["run_id"], "worker-extra")
        pytest.fail(f"unadmitted initial job accepted; first claim: {lease['job_id']}")
    with closing(sqlite3.connect(state.db_path)) as db:
        assert db.execute("SELECT count(*) FROM runs WHERE run_id=?", (plan["run_id"],)).fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM jobs WHERE run_id=?", (plan["run_id"],)).fetchone()[0] == 0


@pytest.mark.parametrize("change", [
    {"execution_contract_version": None}, {"dependency_descriptor_sha256": None},
    {"execution_contract_version": True}, {"execution_contract_version": "3"},
    {"execution_contract_version": 2}, {"execution_contract_version": 4},
    {"dependency_descriptor_sha256": "bad"}, {"new_unknown_field": True},
])
def test_plan_schema_and_runtime_refuse_malformed_execution_markers(tmp_path, change):
    state, plan, _ = state_fixture(tmp_path)
    for key, value in change.items():
        if value is None:
            del plan[key]
        else:
            plan[key] = value
    assert not plan_schema().is_valid(plan)
    with pytest.raises(SwarmError):
        state.create_run(plan)


def test_descriptor_has_no_template_hash_cycle(tmp_path):
    setup = dependency_setup(tmp_path)
    spec = validate_plan(setup[4], setup[3])
    desc, envelope = descriptor(setup[3], spec)
    assert desc["gate"] == ["A1"]
    assert envelope["descriptor_sha256"] == digest(desc)
    assert desc["review_core_digest"] == envelope["core_digest"] == digest(envelope["core"])
    assert digest(envelope) != envelope["core_digest"]
    changed = copy.deepcopy(spec); changed["jobs"][0]["purpose"] += "!"
    assert descriptor(setup[3], changed) != (desc, envelope)


@pytest.mark.parametrize("case", ["cycle", "second_edge", "missing", "third_leaf", "shared_gate"])
def test_only_single_source_edge_and_nonempty_exclusive_gate(tmp_path, case):
    setup = dependency_setup(tmp_path)
    spec = setup[4]
    if case == "cycle": spec["jobs"][0]["requires"] = [spec["jobs"][1]["job_id"]]
    if case == "second_edge": spec["jobs"][1]["requires"] *= 2
    if case == "missing": spec["jobs"][1]["requires"] = ["missing"]
    if case == "third_leaf": spec["jobs"].append({**spec["jobs"][1], "job_id": "third"})
    if case == "shared_gate": spec["jobs"][1]["criterion_ids"].append("A1")
    with pytest.raises(SwarmError):
        descriptor(setup[3], validate_plan(spec, setup[3]))


def state_fixture(tmp_path):
    binding = {"task_id": "task-demo", "revision": 1, "context_digest": "a"*64,
        "owner_ref": "owner", "active_home": "local", "authority_ref": "authority",
        "capability_ref": "capability", "expires_at": 2000, "status": "active"}
    binding = validate_binding(binding, now=1000)
    state = SwarmState(tmp_path/"state.sqlite", lambda _: copy.deepcopy(binding), lambda: 1000)
    def job(name, kind="work", deps=()):
        return {"job_id":name,"kind":kind,"dependencies":list(deps),"exclusive_keys":[],
                "payload_ref":"ref/"+name,"payload_digest":"b"*64}
    plan = state.create_run({"run_id":"run", "task_id":binding["task_id"], "binding_digest":digest(binding),
        "execution_contract_version":3, "dependency_descriptor_sha256":"c"*64,
        "budget":{"attempt_budget":6,"concurrency":2,"deadline":1100,"verifier_reserve":2},
        "jobs":[job("r0-a"),job("r0-b",deps=["r0-a"]),job("r0-prerequisite","review",["r0-a"]),
                job("r0-critic","review",["r0-a","r0-b"])]})
    for worker in ("worker-a","reviewer"):
        lease = state.claim("run", worker)
        state.attach_identity(lease["token"], {"kind":"native","thread_id":"invocation-"+worker})
        state.report(lease["token"],"ref/result/"+worker,"d"*64,"candidate","ref/receipt/"+worker)
    snap=state.snapshot("run")
    cert={"version":1,"run_id":"run","binding_digest":digest(binding),"initial_execution_plan_digest":digest(plan),
        "descriptor_sha256":"c"*64,"progress_sha256":"e"*64,"owner_ref":"owner","a_job_id":"r0-a","b_job_id":"r0-b",
        "a":attempt_proof(snap["jobs"]["r0-a"]["current_attempt"]),
        "review":attempt_proof(snap["jobs"]["r0-prerequisite"]["current_attempt"])}
    stage={"version":1,"status":"released","certificate":cert,"certificate_sha256":digest(cert),
        "actual_input_digest":"f"*64,"accepted_at":1000,"verification_ref":"ref/loop/prerequisite/"+digest(cert)}
    return state, plan, stage


def test_accept_without_release_does_not_unlock_b(tmp_path):
    state, _, stage=state_fixture(tmp_path)
    state.accept("run","r0-a","d"*64,"ref/other","owner")
    assert state.claim("run","worker-b") is None
    assert state.dependency_stage("run") is None


def test_release_is_atomic_immutable_and_pins_actual_digest(tmp_path):
    state, _, stage=state_fixture(tmp_path)
    cas=state.finalization_evidence_digest("run")
    assert state.commit_dependency_stage("run",stage,expected_state_digest=cas)==stage
    assert state.commit_dependency_stage("run",stage,expected_state_digest=cas)==stage
    lease=state.claim("run","worker-b")
    assert lease["job_id"]=="r0-b" and lease["delivered_input_digest"]=="f"*64
    changed=copy.deepcopy(stage);changed["actual_input_digest"]="a"*64
    with pytest.raises(SwarmError,match="LOOP_RELEASE_IMMUTABLE"):
        state.commit_dependency_stage("run",changed,expected_state_digest=cas)


def test_cancelled_release_rolls_back_a_and_stage(tmp_path):
    state, _, stage=state_fixture(tmp_path)
    event=threading.Event();event.set()
    before=state.finalization_evidence_digest("run")
    with pytest.raises(SwarmError,match="RUN_CANCELLED"):
        state.commit_dependency_stage("run",stage,expected_state_digest=before,cancel_event=event)
    assert state.finalization_evidence_digest("run")==before
    assert state.dependency_stage("run") is None


def test_blocked_stage_preserves_pending_jobs_and_no_a_accept(tmp_path):
    state, _, stage=state_fixture(tmp_path)
    stage.update(status="blocked",actual_input_digest=None,accepted_at=None,verification_ref=None)
    state.commit_dependency_stage("run",stage,expected_state_digest=state.finalization_evidence_digest("run"))
    assert state.claim("run","worker-b") is None
    snapshot=state.snapshot("run")
    assert snapshot["jobs"]["r0-a"]["state"]=="reported"
    assert snapshot["jobs"]["r0-b"]["state"]==snapshot["jobs"]["r0-critic"]["state"]=="pending"


def test_failed_b_cannot_be_released_as_a_fresh_retry(tmp_path):
    state,_,stage=state_fixture(tmp_path)
    state.commit_dependency_stage("run",stage,expected_state_digest=state.finalization_evidence_digest("run"))
    lease=state.claim("run","worker-b")
    state.fail(lease["token"],"unknown external outcome",retryable=True)
    assert state.claim("run","worker-b") is None
    assert state.snapshot("run")["jobs"]["r0-b"]["attempt_count"]==1


def test_expiry_at_release_precommit_rolls_back_both_rows(tmp_path):
    state,_,stage=state_fixture(tmp_path)
    before=state.finalization_evidence_digest("run")
    readings=iter([1000,1000,1000,1101])
    state._now=lambda:next(readings)
    with pytest.raises(SwarmError,match="DEADLINE_EXPIRED"):
        state.commit_dependency_stage("run",stage,expected_state_digest=before)
    state._now=lambda:1000
    assert state.finalization_evidence_digest("run")==before
    assert state.dependency_stage("run") is None


from task_swarm.dependency_contract import roles, execution_version, check_stage, REVIEW_ID


@pytest.mark.parametrize("case", ["cycle", "second_edge", "missing", "third_leaf"])
def test_pure_roles_rejects_non_single_edge(tmp_path, case):
    setup = dependency_setup(tmp_path)
    spec = setup[4]
    if case == "cycle": spec["jobs"][0]["requires"] = [spec["jobs"][1]["job_id"]]
    if case == "second_edge": spec["jobs"][1]["requires"] *= 2
    if case == "missing": spec["jobs"][1]["requires"] = ["missing"]
    if case == "third_leaf": spec["jobs"].append({**spec["jobs"][1], "job_id": "third"})
    with pytest.raises(SwarmError, match="LOOP_DEPENDENCY_PLAN"):
        roles(spec)


def test_pure_roles_identifies_original_prerequisite_and_dependent(tmp_path):
    setup = dependency_setup(tmp_path)
    a, b = roles(setup[4])
    assert a is setup[4]["jobs"][0]
    assert b is setup[4]["jobs"][1]
    assert b["requires"] == [a["job_id"]]


@pytest.mark.parametrize("policy", [
    {"execution_contract_version": 3},
    {"dependency_descriptor_sha256": "c" * 64},
    {"execution_contract_version": True, "dependency_descriptor_sha256": "c" * 64},
    {"execution_contract_version": 2, "dependency_descriptor_sha256": "c" * 64},
    {"execution_contract_version": 4, "dependency_descriptor_sha256": "c" * 64},
])
def test_pure_execution_fields_reject_unknown_partial_or_boolean_policy(policy):
    with pytest.raises(SwarmError, match="LOOP_DEPENDENCY_POLICY"):
        execution_version(policy)


def test_pure_execution_fields_keep_legacy_absence_distinct():
    assert execution_version({}) is None
    assert execution_version({"execution_contract_version": 3,
                              "dependency_descriptor_sha256": "c" * 64}) == 3


def pure_stage():
    # Shape fixture only. It does not assert ledger/owner authenticity or release B.
    plan = {"run_id": "run", "binding_digest": "a" * 64,
        "execution_contract_version": 3, "dependency_descriptor_sha256": "c" * 64,
        "jobs": [{"job_id": "r0-a", "kind": "work", "dependencies": []},
                 {"job_id": "r0-b", "kind": "work", "dependencies": ["r0-a"]}]}
    def proof(name):
        return {"job_id": name, "token": "token-" + name, "epoch": 0, "attempt": 1,
            "worker_ref": "ref/worker/" + name, "identity": {"kind": "native", "thread_id": name},
            "result_digest": "d" * 64, "result_ref": "ref/result/" + name,
            "runtime_receipt_ref": "ref/receipt/" + name}
    certificate = {"version": 1, "run_id": "run", "binding_digest": "a" * 64,
        "initial_execution_plan_digest": digest(plan), "descriptor_sha256": "c" * 64,
        "progress_sha256": "e" * 64, "owner_ref": "ref/owner", "a_job_id": "r0-a",
        "b_job_id": "r0-b", "a": proof("r0-a"), "review": proof(REVIEW_ID)}
    stage = {"version": 1, "status": "released", "certificate": certificate,
        "certificate_sha256": digest(certificate), "actual_input_digest": "f" * 64,
        "accepted_at": 1000, "verification_ref": "ref/loop/prerequisite/" + digest(certificate)}
    return plan, stage


def test_pure_stage_shape_has_separate_released_and_blocked_forms():
    plan, stage = pure_stage()
    assert check_stage(stage, plan) is stage
    stage.update(status="blocked", actual_input_digest=None, accepted_at=None, verification_ref=None)
    assert check_stage(stage, plan) is stage


@pytest.mark.parametrize("mutation", ["wrong_plan", "wrong_certificate", "unknown_status", "blocked_with_input"])
def test_pure_stage_shape_rejects_wrong_scope_or_mixed_stage(mutation):
    plan, stage = pure_stage()
    if mutation == "wrong_plan": plan["binding_digest"] = "b" * 64
    if mutation == "wrong_certificate": stage["certificate_sha256"] = "b" * 64
    if mutation == "unknown_status": stage["status"] = "unknown"
    if mutation == "blocked_with_input": stage["status"] = "blocked"
    with pytest.raises(SwarmError, match="LOOP_RELEASE_INVALID"):
        check_stage(stage, plan)
