"""Real owner/state coordinator with bounded, data-dependent local workers."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from task_swarm.closed_loop import execute_closed_loop
from task_swarm.closed_loop_contract import loop_criteria, validate_plan
from task_swarm.protocol import SwarmError, digest
from task_swarm.task_runner import read_json
from test_task_swarm_objectives import fixture, source, span


def setup_loop(tmp_path, *, budget=6, jobs=2):
    payload, binding = fixture()
    measure = source("c"*64, 1, "speed=42\nmemory=8\nUNSELECTED_SENTINEL")
    payload["sources"].append(measure)
    payload["objective"]["budget"]["attempt_budget"] = budget
    root = tmp_path / "operations"
    root.mkdir()
    file = tmp_path / "input.json"
    file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    binding.update(active_home=str(root), context_digest=digest(payload))
    actors = ["worker-a", "worker-b", "worker-c"][:jobs]
    document = {"binding": binding, "actors": {
        actor: {"epoch": 1, "invocation_ref": "invocation-"+actor,
                "actor_status": "active", "capability_ref": binding["capability_ref"], "peers": []}
        for actor in [*actors, "verifier"]}, "allowed_actions": [],
        "source_checks": [{"path": str(file), "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}],
        "storage": {"root": str(root), "mailbox": str(root/"mailbox.sqlite"), "payloads": str(root/"payloads")}}
    owner = tmp_path / "owner.json"
    owner.write_text(json.dumps(document), encoding="utf-8")
    expected = list(loop_criteria(payload))
    plan = {"version": 1, "parent_input_digest": digest(payload), "jobs": [
        {"job_id": "speed", "purpose": "Read measured speed while preserving the owner's constraints.",
         "criterion_ids": expected, "selected_spans": [span(measure, "speed=42"), span(measure, "memory=8")]}]}
    if jobs > 1:
        plan["jobs"].append({"job_id": "uncertainty", "purpose": "Compare measured facts with explicit unknowns.",
            "criterion_ids": ["U", "I", "Q1"], "selected_spans": [span(measure, "speed=42")]})
    if jobs > 2:
        plan["jobs"].append({"job_id": "constraints", "purpose": "Check the read-only constraint.",
            "criterion_ids": ["O1"], "selected_spans": [span(measure, "speed=42")]})
    return owner, file, document, payload, plan, actors, measure


class MeasuredBackend:
    synthetic = True

    def __init__(self, payload, measure, *, barrier=None):
        self.payload, self.measure, self.barrier = payload, measure, barrier
        self.inputs, self.lock = [], threading.Lock()

    def envelope(self, delivered, result, actor):
        with self.lock:
            self.inputs.append(copy.deepcopy(delivered))
        return {"result": result, "receipt": {"actor_ref": actor,
            "invocation_ref": "synthetic-" + delivered["job_id"],
            "input_digest": digest(delivered), "synthetic": True}}

    def produce(self, delivered, directory, *, actor_ref, **kwargs):
        if self.barrier and delivered["round"] == 0:
            self.barrier.wait(timeout=3)
        record = next(s for s in delivered["view"]["spans"] if s["text"].startswith(("speed=", "memory=")))
        evidence = {key: record[key] for key in ("source_key", "source_revision", "start", "end")}
        report = {"job_id": delivered["job_id"], "summary": record["text"], "conflicts": [],
                  "claims": [{"text": record["text"], "status": "supported",
                              "evidence": [{**evidence, "quote": record["text"]}]}]}
        return self.envelope(delivered, report, actor_ref)

    def review(self, delivered, directory, *, actor_ref, **kwargs):
        reports = delivered["reports"]
        memory_record = next(s for s in delivered["view"]["spans"] if s["text"] == "memory=8")
        memory_span = {key: memory_record[key] for key in ("source_key", "source_revision", "start", "end")}
        speed = next(job for job, report in reports.items() if report["claims"][0]["text"] == "speed=42")
        memory = next((job for job, report in reports.items() if report["claims"][0]["text"] == "memory=8"), None)
        validations = []
        for key in delivered["criteria"]:
            failed = key in {"R", "A1"} and memory is None
            target = memory if key in {"R", "A1"} and memory else speed
            validations.append({"criterion_id": key, "status": "failed" if failed else "passed",
                "evidence": [] if failed else ([{"job_id": job, "claim_index": 0} for job in reports]
                    if key == "I" else [{"job_id": target, "claim_index": 0}]),
                "gap_reason": "The memory observation is missing." if failed else None,
                "source_spans": [memory_span] if failed else []})
        result = {"parent_input_digest": digest(self.payload),
                  "plan_digest": delivered["view"]["plan_digest"], "round": delivered["round"],
                  "report_digests": {job: digest(report) for job, report in reports.items()},
                  "validations": validations}
        return self.envelope(delivered, result, actor_ref)


def repair_for(payload):
    def repair(gap):
        return {"version": 1, "parent_input_digest": digest(payload), "jobs": [{"job_id": "memory",
            "purpose": "Supply the specifically missing memory measurement for the failed criteria.",
            "criterion_ids": gap["failed_criteria"], "selected_spans": gap["source_spans"]}]}
    return repair


def execute(setup, backend, **kwargs):
    owner, file, _, payload, plan, actors, _ = setup
    return execute_closed_loop(owner, file, plan, backend, worker_actors=actors,
                               repair_planner=repair_for(payload), clock=lambda: 1000, **kwargs)


def test_parallel_critic_repair_integrates_without_changing_owner_or_renewing_budget(tmp_path):
    setup = setup_loop(tmp_path)
    owner, _, _, payload, plan, _, measure = setup
    before = owner.read_bytes()
    backend = MeasuredBackend(payload, measure, barrier=threading.Barrier(2))
    result = execute(setup, backend)
    assert result["candidate"]["status"] == "needs_owner_review"
    assert result["candidate"]["parent_input_digest"] == digest(payload)
    assert result["receipt"]["rounds"] == 2
    assert result["receipt"]["budget"]["attempts_used"] == 5
    assert result["receipt"]["budget"]["remaining_attempts"] == 1
    assert result["receipt"]["context_bytes"] > 0 and result["receipt"]["artifact_bytes"] > 0
    assert result["receipt"]["elapsed_seconds"] >= 0
    assert result["receipt"]["task_state_changed"] is False and owner.read_bytes() == before
    assert result["learning_candidate"]["status"] == "unadopted"
    assert result["learning_candidate"]["next_context_eligible"] is False
    assert {item["claim"]["text"] for item in result["candidate"]["claims"]} == {"speed=42", "memory=8"}
    assert len(backend.inputs) == 5
    assert all("UNSELECTED_SENTINEL" not in json.dumps(value) for value in backend.inputs)
    views = [value["view"] for value in backend.inputs]
    assert all(view["parent_input_digest"] == digest(payload) for view in views)
    assert views[-1]["previous_critic_digest"] is not None
    directory = owner.parent/"operations"/result["receipt"]["run_id"]
    snapshot = read_json(directory/"execution.json")
    assert snapshot["jobs"]["r0-critic"]["state"] == "reported"
    assert snapshot["jobs"]["r1-critic"]["state"] == "accepted"
    assert len(snapshot["plan"]["jobs"]) == 3
    assert len(snapshot["jobs"]) == 5
    extension = read_json(directory/"extension.json")
    assert snapshot["extension"] == extension
    assert extension["initial_plan_digest"] == digest(snapshot["plan"])
    replayed = execute(setup, backend, expected_receipt_sha256=result["receipt_sha256"])
    assert replayed["duplicate"] and replayed["candidate"] == result["candidate"]
    assert len(backend.inputs) == 5


@pytest.mark.parametrize("jobs", [1, 2, 3])
def test_supplied_objective_decomposition_changes_real_delivered_jobs(tmp_path, jobs):
    setup = setup_loop(tmp_path, jobs=jobs)
    backend = MeasuredBackend(setup[3], setup[6])
    result = execute(setup, backend)
    assert result["receipt"]["budget"]["attempts_used"] == jobs + 3
    assert len([value for value in backend.inputs if value["round"] == 0 and value["role"] == "work"]) == jobs
    assert result["receipt"]["initial_plan_digest"] == digest(setup[4])


@pytest.mark.parametrize("budget,jobs", [(4, 2), (5, 3)])
def test_insufficient_original_budget_stops_without_repair_or_learning(tmp_path, budget, jobs):
    setup = setup_loop(tmp_path, budget=budget, jobs=jobs)
    backend = MeasuredBackend(setup[3], setup[6])
    result = execute(setup, backend)
    assert result["candidate"]["status"] == "unresolved"
    assert result["candidate"]["stop_reason"] == "attempt_budget_exhausted"
    assert result["learning_candidate"] is None
    assert len(backend.inputs) == jobs + 1
    assert result["receipt"]["budget"]["attempts_used"] == jobs + 1


@pytest.mark.parametrize("status", ["blocked", "not_run"])
def test_nonexecuted_or_external_gap_does_not_trigger_repair(tmp_path, status):
    setup = setup_loop(tmp_path)
    class Backend(MeasuredBackend):
        def review(self, *args, **kwargs):
            result = super().review(*args, **kwargs)
            next(v for v in result["result"]["validations"] if v["status"] == "failed")["status"] = status
            return result
    backend = Backend(setup[3], setup[6])
    result = execute(setup, backend)
    assert len(backend.inputs) == 3 and result["learning_candidate"] is None
    assert result["candidate"]["stop_reason"] == "unresolved_review"


def test_repair_cannot_fake_success_using_only_old_evidence(tmp_path):
    setup = setup_loop(tmp_path)
    class Backend(MeasuredBackend):
        def review(self, delivered, *args, **kwargs):
            result = super().review(delivered, *args, **kwargs)
            if delivered["round"] == 1:
                for validation in result["result"]["validations"]:
                    validation["evidence"] = [{"job_id": "r0-speed", "claim_index": 0}]
            return result
    backend = Backend(setup[3], setup[6])
    with pytest.raises(SwarmError, match="LOOP_REPAIR_EVIDENCE_REQUIRED"):
        execute(setup, backend)
    assert not list((setup[0].parent/"operations").glob("*/receipt.json"))
    with pytest.raises(SwarmError, match="RUN_RECOVERY_REQUIRED"):
        execute(setup, backend)
    assert len(backend.inputs) == 5


def test_source_revocation_after_work_cancels_before_any_review(tmp_path):
    setup = setup_loop(tmp_path, jobs=1)
    class Backend(MeasuredBackend):
        def produce(self, *args, **kwargs):
            result = super().produce(*args, **kwargs)
            setup[1].write_text("{}", encoding="utf-8")
            return result
    backend = Backend(setup[3], setup[6])
    with pytest.raises(SwarmError):
        execute(setup, backend)
    assert len(backend.inputs) == 1
    assert not list((setup[0].parent/"operations").glob("*/receipt.json"))


def test_unseen_source_evidence_and_wrong_input_receipts_fail_before_review(tmp_path):
    setup = setup_loop(tmp_path, jobs=1)
    class Backend(MeasuredBackend):
        def produce(self, delivered, *args, **kwargs):
            result = super().produce(delivered, *args, **kwargs)
            result["receipt"]["input_digest"] = "0"*64
            return result
    backend = Backend(setup[3], setup[6])
    with pytest.raises(SwarmError, match="LOOP_INPUT_RECEIPT_MISMATCH"):
        execute(setup, backend)
    assert len(backend.inputs) == 1


def test_changed_plan_cannot_start_a_new_budget_and_replay_rejects_tampering(tmp_path):
    setup = setup_loop(tmp_path)
    backend = MeasuredBackend(setup[3], setup[6])
    result = execute(setup, backend)
    setup[4]["jobs"][0]["purpose"] = "Changed purpose"
    with pytest.raises(SwarmError, match="RUN_REPLAY_CONFLICT"):
        execute(setup, backend, expected_receipt_sha256=result["receipt_sha256"])
    setup[4]["jobs"][0]["purpose"] = "Read measured speed while preserving the owner's constraints."
    directory = setup[0].parent/"operations"/result["receipt"]["run_id"]
    artifact = read_json(directory/"r0-critic-result.json")
    artifact["result"]["validations"][0]["status"] = "passed"
    (directory/"r0-critic-result.json").write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(SwarmError, match="RUN_ARTIFACT_CHANGED"):
        execute(setup, backend, expected_receipt_sha256=result["receipt_sha256"])
    assert len(backend.inputs) == 5


def test_purpose_and_criterion_changes_change_delivered_input_but_keep_owner_goal(tmp_path):
    setup = setup_loop(tmp_path, jobs=1)
    plan = copy.deepcopy(setup[4])
    validate_plan(plan, setup[3])
    backend = MeasuredBackend(setup[3], setup[6])
    execute(setup, backend)
    initial, repair = [i for i in backend.inputs if i["role"] == "work"]
    assert initial["purpose"] != repair["purpose"] and initial["criterion_ids"] != repair["criterion_ids"]
    assert digest(initial) != digest(repair)
    assert initial["view"]["objective"] == repair["view"]["objective"] == setup[3]["objective"]


def test_first_pass_needs_no_repair_and_still_records_actual_costs(tmp_path):
    setup = setup_loop(tmp_path)
    setup[4]["jobs"][1].update(job_id="memory", selected_spans=[span(setup[6], "memory=8")])
    result = execute(setup, MeasuredBackend(setup[3], setup[6]))
    assert result["receipt"]["rounds"] == 1
    assert result["receipt"]["budget"]["attempts_used"] == 3
    assert result["receipt"]["review_passed"] is True
    assert result["receipt"]["model_runtime_verified"] is False
    assert "cost" not in result["receipt"] and "rss" not in result["receipt"]


def test_context_limit_stops_before_a_backend_call_and_cannot_be_reset_by_restart(tmp_path, monkeypatch):
    import task_swarm.closed_loop as coordinator
    setup = setup_loop(tmp_path, jobs=1)
    backend = MeasuredBackend(setup[3], setup[6])
    monkeypatch.setattr(coordinator, "MAX_CONTEXT_BYTES", 1)
    with pytest.raises(SwarmError, match="LOOP_CONTEXT_BUDGET"):
        execute(setup, backend)
    assert not backend.inputs
    with pytest.raises(SwarmError, match="RUN_RECOVERY_REQUIRED"):
        execute(setup, backend)
    assert not backend.inputs


def test_noncooperative_callback_cannot_publish_after_deadline(tmp_path):
    setup = setup_loop(tmp_path, jobs=1)
    now, entered, release, cancelled = [1000], threading.Event(), threading.Event(), threading.Event()
    errors = []
    class Backend(MeasuredBackend):
        def produce(self, *args, **kwargs):
            entered.set()
            release.wait(timeout=3)  # Deliberately ignores cancellation until released by the test.
            return super().produce(*args, **kwargs)
    def run():
        try:
            execute_closed_loop(setup[0], setup[1], setup[4], Backend(setup[3], setup[6]),
                worker_actors=setup[5], repair_planner=repair_for(setup[3]),
                clock=lambda: now[0], cancel_event=cancelled)
        except Exception as error:
            errors.append(error)
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        assert entered.wait(timeout=2)
        now[0] = 1101
        assert cancelled.wait(timeout=2)
        assert worker.is_alive()  # Threads cannot forcibly stop an arbitrary Python callback.
    finally:
        release.set()
        worker.join(timeout=3)
    assert not worker.is_alive() and errors and isinstance(errors[0], SwarmError)
    assert not list((setup[0].parent/"operations").glob("*/receipt.json"))
    with pytest.raises(SwarmError, match="RUN_RECOVERY_REQUIRED"):
        execute(setup, MeasuredBackend(setup[3], setup[6]))


def test_critic_reusing_a_worker_invocation_is_rejected(tmp_path):
    setup = setup_loop(tmp_path, jobs=1)
    class Backend(MeasuredBackend):
        def review(self, *args, **kwargs):
            result = super().review(*args, **kwargs)
            result["receipt"]["invocation_ref"] = "synthetic-r0-speed"
            return result
    with pytest.raises(SwarmError, match="REVIEW_NOT_INDEPENDENT"):
        execute(setup, Backend(setup[3], setup[6]))


def test_comparison_criterion_must_reference_every_report(tmp_path):
    setup = setup_loop(tmp_path)
    class Backend(MeasuredBackend):
        def review(self, *args, **kwargs):
            result = super().review(*args, **kwargs)
            next(v for v in result["result"]["validations"] if v["criterion_id"] == "I")["evidence"] = [
                {"job_id": "r0-speed", "claim_index": 0}]
            return result
    with pytest.raises(SwarmError, match="LOOP_COMPARISON_REQUIRED"):
        execute(setup, Backend(setup[3], setup[6]))


def test_critic_cannot_request_parent_source_it_was_never_given(tmp_path):
    setup = setup_loop(tmp_path, jobs=1)
    class Backend(MeasuredBackend):
        def review(self, *args, **kwargs):
            result = super().review(*args, **kwargs)
            next(v for v in result["result"]["validations"] if v["status"] == "failed")["source_spans"] = [
                span(setup[6], "UNSELECTED_SENTINEL")]
            return result
    backend = Backend(setup[3], setup[6])
    with pytest.raises(SwarmError, match="LOOP_GAP_NOT_DELIVERED"):
        execute(setup, backend)
    assert len(backend.inputs) == 2


@pytest.mark.parametrize("field", ["parent_input_digest", "plan_digest", "report_digests", "round"])
def test_critic_for_different_input_plan_or_reports_cannot_be_accepted(tmp_path, field):
    setup = setup_loop(tmp_path, jobs=1)
    class Backend(MeasuredBackend):
        def review(self, *args, **kwargs):
            result = super().review(*args, **kwargs)
            result["result"][field] = {} if field == "report_digests" else (1 if field == "round" else "0"*64)
            return result
    backend = Backend(setup[3], setup[6])
    with pytest.raises(SwarmError, match="LOOP_CRITIC_STALE"):
        execute(setup, backend)
    assert len(backend.inputs) == 2
    directory = next((setup[0].parent/"operations").iterdir())
    assert not (directory/"receipt.json").exists()


def test_critic_template_and_actual_dependency_input_are_separately_bound(tmp_path):
    setup = setup_loop(tmp_path, jobs=1)
    result = execute(setup, MeasuredBackend(setup[3], setup[6]))
    directory = setup[0].parent/"operations"/result["receipt"]["run_id"]
    plan = read_json(directory/"plan.json")
    declared = next(job["payload_digest"] for job in plan["jobs"] if job["kind"] == "review")
    delivered = read_json(directory/"r0-critic-input.json")
    receipt = read_json(directory/"r0-critic-result.json")["receipt"]
    assert declared != digest(delivered)
    assert receipt["input_digest"] == digest(delivered)
    assert delivered["template_digest"] == declared
    assert result["receipt"]["dispatches"]["r0-critic"]["declared_input_digest"] == declared
    assert delivered["report_digests"] == read_json(directory/"r0-critic-result.json")["result"]["report_digests"]


def test_cli_runs_a_fully_declared_scenario_through_owner_and_state(tmp_path):
    setup = setup_loop(tmp_path, jobs=1)
    owner, file, document, payload, plan, actors, measure = setup
    now = time.time()
    payload["objective"]["budget"]["deadline"] = now + 1000
    document["binding"].update(expires_at=now+1100, context_digest=digest(payload))
    file.write_text(json.dumps(payload), encoding="utf-8")
    document["source_checks"][0]["sha256"] = hashlib.sha256(file.read_bytes()).hexdigest()
    owner.write_text(json.dumps(document), encoding="utf-8")
    plan["parent_input_digest"] = digest(payload)
    selected = [span(measure, "speed=42"), span(measure, "memory=8")]
    plan["jobs"][0]["selected_spans"] = selected
    claims = [{"text": text, "status": "supported", "evidence": [{**location, "quote": text}]}
              for text, location in zip(["speed=42", "memory=8"], selected)]
    report = {"job_id": "r0-speed", "summary": "Measured values", "claims": claims, "conflicts": []}
    review = {"parent_input_digest": digest(payload), "plan_digest": digest(plan), "round": 0,
        "report_digests": {"r0-speed": digest(report)}, "validations": [
            {"criterion_id": key, "status": "passed", "evidence": [{"job_id": "r0-speed", "claim_index": 0}],
             "gap_reason": None, "source_spans": []} for key in loop_criteria(payload)]}
    plan_path, scenario_path = tmp_path/"plan.json", tmp_path/"scenario.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    scenario_path.write_text(json.dumps({"work": {"r0-speed": report}, "critics": {"0": review},
                                         "repair_plan": None}), encoding="utf-8")
    import os
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]/"runtime"),
           "PYTHONDONTWRITEBYTECODE": "1"}
    command = [sys.executable, "-B", "-m", "task_swarm.closed_loop", "--owner", str(owner),
               "--input", str(file), "--plan", str(plan_path), "--simulation", str(scenario_path),
               "--worker", actors[0]]
    completed = subprocess.run(command, env=env, text=True, capture_output=True, timeout=20)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["receipt"]["review_passed"] and result["receipt"]["budget"]["attempts_used"] == 2
    replay = subprocess.run([*command, "--receipt-sha256", result["receipt_sha256"]],
                            env=env, text=True, capture_output=True, timeout=20)
    assert replay.returncode == 0, replay.stderr
    assert json.loads(replay.stdout)["duplicate"] is True


def test_state_extension_is_one_atomic_idempotent_round_with_immutable_initial_plan(tmp_path):
    setup = setup_loop(tmp_path)
    result = execute(setup, MeasuredBackend(setup[3], setup[6]))
    from task_swarm.owner_file import OwnerFile
    from task_swarm.state import SwarmState
    directory = setup[0].parent/"operations"/result["receipt"]["run_id"]
    state = SwarmState(directory/"execution.sqlite", OwnerFile(setup[0], clock=lambda: 1000).read_task,
                       clock=lambda: 1000)
    extension = read_json(directory/"extension.json")
    assert state.extend_run(result["receipt"]["run_id"], extension) == extension
    changed = copy.deepcopy(extension)
    changed["proposal_digest"] = "1"*64
    with pytest.raises(SwarmError, match="ROUND_CONFLICT"):
        state.extend_run(result["receipt"]["run_id"], changed)
    changed["round"] = 2
    with pytest.raises(SwarmError, match="ROUND_LIMIT"):
        state.extend_run(result["receipt"]["run_id"], changed)
    with sqlite3.connect(directory/"execution.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM run_extensions").fetchone()[0] == 1
        assert len(json.loads(db.execute("SELECT plan_json FROM runs").fetchone()[0])["jobs"]) == 3
