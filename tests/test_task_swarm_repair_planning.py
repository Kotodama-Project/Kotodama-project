"""Assigned-gap planning preserves untouched work and every authority boundary."""
import copy
import hashlib
from pathlib import Path
import subprocess
import sys

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest job")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from task_swarm import closed_loop
from task_swarm.closed_loop_contract import evidence_version, required_evidence_jobs, verified_gap, validate_critic
from task_swarm.owner_file import OwnerFile
from task_swarm.protocol import SwarmError, digest
from task_swarm.repair_planning import derive_repair, inspect_repair, make_impact, file_sha
from task_swarm.state import SwarmState
from task_swarm.task_runner import read_json
from test_task_swarm_closed_loop import setup_loop, MeasuredBackend, execute


def evidence(setup, result):
    directory = setup[0].parent/"operations"/result["receipt"]["run_id"]
    state = SwarmState(directory/"execution.sqlite", OwnerFile(setup[0], clock=lambda: 1000).read_task,
                       clock=lambda: 1000)
    prior = {"response": read_json(directory/"r0-critic-result.json"),
             "dispatched_input": read_json(directory/"r0-critic-input.json"),
             "dispatched_input_digest": result["receipt"]["dispatches"]["r0-critic"]["delivered_input_digest"]}
    return directory, state, prior


def test_automatic_repair_retains_independent_work_and_pre_repair_budget(tmp_path):
    setup = setup_loop(tmp_path)
    backend = MeasuredBackend(setup[3], setup[6])
    result = execute(setup, backend)
    directory, state, _ = evidence(setup, result)
    impact = read_json(directory/"repair-impact.json")
    assert [x["job_id"] for x in backend.inputs].count("r0-uncertainty") == 1
    assert [x["job_id"] for x in impact["retained"]] == ["r0-uncertainty"]
    retained = impact["retained"][0]
    assert retained["input_digest"] == digest(read_json(directory/"r0-uncertainty-input.json"))
    assert retained["result_sha256"] == hashlib.sha256((directory/"r0-uncertainty-result.json").read_bytes()).hexdigest()
    assert impact["budget_cut"]["remaining_attempts"] == 3
    assert state.snapshot(result["receipt"]["run_id"])["budget"]["remaining_attempts"] == 1
    assert inspect_repair(setup[0], setup[1], clock=lambda: 1000)["impact"] == impact
    first = read_json(directory/"r0-critic-template.json")
    second = read_json(directory/"r1-critic-template.json")
    assert first["repair_planning_contract"] == second["repair_planning_contract"] == 1
    assert first["repair_impact_sha256"] is None
    assert second["repair_impact_sha256"] == file_sha(impact)
    before = {p.name: p.read_bytes() for p in directory.glob("*.json")}
    assert execute(setup, backend, expected_receipt_sha256=result["receipt_sha256"])["duplicate"]
    assert len(backend.inputs) == 5
    assert {p.name: p.read_bytes() for p in directory.glob("*.json")} == before


class SharedFailure(MeasuredBackend):
    def review(self, delivered, *args, **kwargs):
        response = super().review(delivered, *args, **kwargs)
        if delivered["round"] == 0:
            failed = next(v for v in response["result"]["validations"] if v["criterion_id"] == "A1")
            shared = next(v for v in response["result"]["validations"] if v["criterion_id"] == "R")
            shared.update(status="failed", evidence=[], gap_reason=failed["gap_reason"],
                          source_spans=copy.deepcopy(failed["source_spans"]))
        return response


def test_shared_failure_keeps_conservative_contribution_for_both_repairs(tmp_path):
    setup = setup_loop(tmp_path)
    result = execute(setup, SharedFailure(setup[3], setup[6]))
    directory, _, _ = evidence(setup, result)
    impact = read_json(directory/"repair-impact.json")
    assert [x["failed_criteria"] for x in impact["assignments"]] == [["A1", "R"], ["R"]]
    required = read_json(directory/"r1-critic-template.json")["required_evidence_jobs"]
    assert set(required["A1"]) == {"r0-speed", "r1-repair-speed", "r1-repair-uncertainty"}
    assert result["receipt"]["budget"]["attempts_used"] == 6


def test_shared_scope_is_not_trimmed_to_fit_remaining_budget(tmp_path):
    setup = setup_loop(tmp_path, jobs=3)
    backend = SharedFailure(setup[3], setup[6])
    result = execute(setup, backend)
    assert len(backend.inputs) == 4
    assert result["candidate"]["stop_reason"] == "attempt_budget_exhausted"
    assert result["learning_candidate"] is None
    assert "repair-impact.json" not in result["receipt"]["artifact_sha256"]


@pytest.mark.parametrize("kind", ["correct", "wrong_scope", "wrong_purpose"])
def test_callback_is_only_a_checked_candidate(tmp_path, kind):
    setup = setup_loop(tmp_path)
    backend = MeasuredBackend(setup[3], setup[6])
    def callback(gap):
        plan, _ = derive_repair(setup[3], setup[4], gap)
        if kind == "wrong_scope":
            plan["jobs"][0]["selected_spans"] = setup[4]["jobs"][0]["selected_spans"]
        if kind == "wrong_purpose":
            plan["jobs"][0]["purpose"] = "An unrelated change"
        return plan
    if kind == "correct":
        assert execute(setup, backend, repair_planner=callback)["receipt"]["review_passed"]
    else:
        with pytest.raises(SwarmError):
            execute(setup, backend, repair_planner=callback)
        assert len(backend.inputs) == 3


def test_marker_removal_cannot_select_legacy(tmp_path):
    setup = setup_loop(tmp_path)
    result = execute(setup, MeasuredBackend(setup[3], setup[6]))
    directory, _, _ = evidence(setup, result)
    template = read_json(directory/"r0-critic-template.json")
    for field in ("repair_planning_contract", "repair_impact_sha256"):
        broken = copy.deepcopy(template); broken.pop(field)
        with pytest.raises(SwarmError):
            evidence_version(read_json(directory/"plan.json"), broken)


@pytest.mark.parametrize("kind", ["missing", "scope", "budget", "attempt_identity", "binding"])
def test_every_impact_field_is_rederived_from_saved_authority(tmp_path, kind):
    setup = setup_loop(tmp_path)
    result = execute(setup, MeasuredBackend(setup[3], setup[6]))
    directory, state, prior = evidence(setup, result)
    impact = read_json(directory/"repair-impact.json")
    if kind == "missing": impact = None
    elif kind == "scope": impact["assignments"][0]["failed_criteria"] = ["R"]
    elif kind == "budget": impact["budget_cut"]["remaining_attempts"] = 1
    elif kind == "attempt_identity": impact["budget_cut"]["attempts"][0]["token"] = "changed"
    else: impact["parent_input_digest"] = "0"*64
    delivered = read_json(directory/"r1-critic-input.json")
    plan = read_json(directory/"plan.json"); extension = read_json(directory/"extension.json")
    scheduled = [*plan["jobs"], *extension["jobs"]]
    with pytest.raises(SwarmError):
        validate_critic(read_json(directory/"r1-critic-result.json")["result"], setup[3], delivered["reports"],
            view=delivered["view"], plan_digest=digest(setup[4]), round_index=1,
            initial_execution_plan_digest=digest(plan),
            expected_jobs=[j["job_id"] for j in scheduled if j["kind"] == "work"],
            dispatched_input=delivered, dispatched_input_digest=digest(delivered),
            initial_specification=setup[4], initial_runtime_plan=plan,
            initial_template=read_json(directory/"r0-critic-template.json"),
            work_inputs={j["job_id"]: read_json(directory/(j["job_id"]+"-input.json")) for j in scheduled if j["kind"] == "work"},
            repair_specification=read_json(directory/"repair-proposal.json"), prior_review=prior,
            repair_admission=extension, repair_impact=impact, execution_snapshot=state.snapshot(plan["run_id"]))


def test_overlong_purpose_is_rejected_without_truncation(tmp_path):
    setup = setup_loop(tmp_path)
    setup[4]["jobs"][0]["purpose"] = "x"*2000
    backend = MeasuredBackend(setup[3], setup[6])
    with pytest.raises(SwarmError, match="LOOP_PURPOSE_REQUIRED"):
        execute(setup, backend)
    assert len(backend.inputs) == 3


def test_inspect_refuses_cancellation_without_mutating_its_record(tmp_path):
    setup = setup_loop(tmp_path)
    from task_swarm.closed_loop_cancellation import cancel_closed_loop
    # A backend failure leaves an existing run; cancellation does not depend on an impact file.
    class Broken(MeasuredBackend):
        def produce(self, *args, **kwargs):
            raise RuntimeError("stopped before report")
    with pytest.raises(RuntimeError): execute(setup, Broken(setup[3], setup[6]))
    record = cancel_closed_loop(setup[0], setup[1], clock=lambda: 1000)
    with pytest.raises(SwarmError, match="RUN_CANCELLED"):
        inspect_repair(setup[0], setup[1], clock=lambda: 1000)
    assert cancel_closed_loop(setup[0], setup[1], clock=lambda: 1000) == record


@pytest.mark.parametrize("field", ["repair-impact.json", "r0-critic-template.json", "r1-critic-template.json"])
def test_process_checkpoint_recovery_rejects_missing_profile_artifacts(tmp_path, field):
    from test_task_swarm_closed_loop_recovery import setup_case, child, directory, snapshot
    config = setup_case(tmp_path)
    assert child(tmp_path, "checkpoint").returncode == 73
    before = snapshot(config)
    (directory(config)/field).unlink()
    assert child(tmp_path, "resume").returncode == 2
    assert snapshot(config) == before
    assert not (tmp_path/"UNAUTHORIZED_CALL").exists()
    assert not (directory(config)/"receipt.json").exists()


def test_learning_origin_rejects_a_missing_impact(tmp_path):
    from test_task_swarm_learning_reuse import setup_reuse
    from task_swarm.learning_reuse import propose_learning
    _, arguments, _, _, _, origin = setup_reuse(tmp_path)
    run_id = "task-run-" + digest([origin[3]["task_id"], origin[3]["revision"]])[:32]
    (origin[0].parent/"operations"/run_id/"repair-impact.json").unlink()
    with pytest.raises(SwarmError):
        propose_learning(origin[0], origin[1], arguments["anchor"], 0, clock=lambda: 1000)


def test_real_inspection_cli_reads_saved_gap_and_does_not_dispatch(tmp_path):
    import json
    import os
    import time
    setup = setup_loop(tmp_path)
    now = time.time()
    setup[3]["objective"]["budget"]["deadline"] = now + 100
    setup[2]["binding"].update(context_digest=digest(setup[3]), expires_at=now+200)
    setup[1].write_text(json.dumps(setup[3]), encoding="utf-8")
    setup[2]["source_checks"][0]["sha256"] = hashlib.sha256(setup[1].read_bytes()).hexdigest()
    setup[0].write_text(json.dumps(setup[2]), encoding="utf-8")
    setup[4]["parent_input_digest"] = digest(setup[3])
    backend = MeasuredBackend(setup[3], setup[6])
    completed = closed_loop.execute_closed_loop(setup[0], setup[1], setup[4], backend,
                                                worker_actors=setup[5], clock=lambda: now)
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]/"runtime"))
    process = subprocess.run([sys.executable, "-m", "task_swarm.repair_planning", "--owner", str(setup[0]),
                              "--input", str(setup[1])], env=env, capture_output=True, text=True, timeout=15)
    assert process.returncode == 0, process.stderr
    value = json.loads(process.stdout)
    assert value["admitted"] is False
    directory, _, _ = evidence(setup, completed)
    assert value["impact"] == read_json(directory/"repair-impact.json")
    assert len(backend.inputs) == 5


def test_partial_and_unknown_profiles_never_fall_back_to_legacy(tmp_path):
    setup = setup_loop(tmp_path)
    result = execute(setup, MeasuredBackend(setup[3], setup[6]))
    directory, _, _ = evidence(setup, result)
    template, plan = read_json(directory/"r0-critic-template.json"), read_json(directory/"plan.json")
    for replacement in (True, 0, 2, "1"):
        broken = {**template, "repair_planning_contract": replacement}
        # Rebind only the local argument to exercise the profile shape beyond the digest guard.
        local_plan = copy.deepcopy(plan)
        next(j for j in local_plan["jobs"] if j["job_id"] == "r0-critic")["payload_digest"] = digest(broken)
        with pytest.raises(SwarmError, match="LOOP_REPAIR_PROFILE"):
            evidence_version(local_plan, broken)


def test_cancellation_does_not_require_a_readable_repair_impact(tmp_path):
    from test_task_swarm_closed_loop_recovery import setup_case, child, directory, snapshot
    from task_swarm.closed_loop_cancellation import cancel_closed_loop
    config = setup_case(tmp_path)
    assert child(tmp_path, "checkpoint").returncode == 73
    (directory(config)/"repair-impact.json").unlink()
    record = cancel_closed_loop(config["owner"], config["input"], clock=lambda: 1000)
    assert record["owner_ref"] == "ref/owner/fixture"
    assert child(tmp_path, "resume").returncode == 2
    assert not (directory(config)/"receipt.json").exists()


def test_inspector_rechecks_objective_deadline_before_return(tmp_path, monkeypatch):
    import task_swarm.repair_planning as planner
    setup = setup_loop(tmp_path)
    result = execute(setup, MeasuredBackend(setup[3], setup[6]))
    directory, state, _ = evidence(setup, result)
    before = state.snapshot(result["receipt"]["run_id"])
    now = [1000]
    original = planner.make_impact
    def crosses_deadline(*args, **kwargs):
        value = original(*args, **kwargs)
        now[0] = setup[3]["objective"]["budget"]["deadline"] + 1
        return value
    monkeypatch.setattr(planner, "make_impact", crosses_deadline)
    with pytest.raises(SwarmError, match="OBJECTIVE_DEADLINE_INVALID"):
        inspect_repair(setup[0], setup[1], clock=lambda: now[0])
    assert state.snapshot(result["receipt"]["run_id"]) == before


@pytest.mark.parametrize("lane", ["allowed", "revoked", "grant_only", "binding_only", "checkpoint_only"])
def test_inspector_refuses_learning_bound_run_without_current_context_reader(tmp_path, lane):
    from test_task_swarm_learning_reuse import setup_reuse, ReadingBackend, allow, save
    reuse, arguments, plan, _, document, _ = setup_reuse(tmp_path)
    decision = allow(reuse)
    backend = ReadingBackend(ignore=True)
    result = reuse.execute(digest(decision), plan, backend, worker_actors=["worker-a"])
    assert result["candidate"]["status"] == "unresolved" and len(backend.calls) == 4
    directory = Path(arguments["target_owner"]).parent/"operations"/result["receipt"]["run_id"]
    if lane == "revoked":
        reuse.decide("ref/owner/fixture", "ref/review/one-learning", "revoke",
                     "ref/decision/revoke-inspection", expected_generation=1)
        with pytest.raises(SwarmError, match="REUSE_DECISION_STALE"):
            reuse.current(digest(decision))
    elif lane == "allowed":
        assert reuse.current(digest(decision))["outcome"] == "allow"
    elif lane == "grant_only":
        (directory/"context-binding.json").unlink()
    else:
        del document["learning_reuse"]
        save(Path(arguments["target_owner"]), document)
        if lane == "checkpoint_only":
            (directory/"context-binding.json").unlink()
    before = {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}
    with pytest.raises(SwarmError, match="LOOP_REUSE_INSPECTION_UNSUPPORTED"):
        inspect_repair(arguments["target_owner"], arguments["target_input"], clock=lambda: 1000)
    assert len(backend.calls) == 4
    assert {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()} == before
