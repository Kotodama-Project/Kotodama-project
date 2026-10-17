"""Bound a hierarchy reference to the existing completed local loop evidence.

Only temporary copies of the saved SQLite database are opened by SwarmState.
The shared terminal/process verifiers own the execution protocol; this module
adds the hierarchy context projection and its final current-source fence.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from runtime.task_swarm.protocol import canonical, digest
from runtime.task_swarm.task_contract import require


def _same(left, right):
    return canonical(left) == canonical(right)


def _contains(view, span):
    return any(row["source_key"] == span["source_key"] and row["source_revision"] == span["source_revision"]
               and row["start"] <= span["start"] < span["end"] <= row["end"] for row in view["spans"])


def saved_executor_plan(owner, payload, binding, owner_sha, directory, receipt, receipt_sha,
                        values, required_spans, check_deadline, resources, current_sources):
    """Read one externally anchored completed run, then retain its final fence.

    Execution deadlines do not expire historical receipts. The caller still
    checks the current owner/Source lifetime and its bounded query deadline.
    Learning reuse requires a separate current decision reader and is refused.
    """
    from runtime.task_swarm.closed_loop_recovery import terminal_evidence
    from runtime.task_swarm.loop_executor import MODE, executor_version
    from runtime.task_swarm.loop_executor_runtime import saved_executor
    from runtime.task_swarm.repair_planning import _inspection_cut, _inspection_state

    run_id, plan = receipt["run_id"], values["plan.json"]
    require(type(receipt.get("rounds")) is int and receipt["rounds"] in (1, 2),
            "FINALIZATION_ROUND_CONFLICT")
    require({"execution.json", "candidate.json", "specification.json", "input.json",
             "r0-critic-template.json", "executor-policy.json"} <= values.keys(), "RUN_RECEIPT_INVALID")
    require("context-binding.json" not in values, "HIERARCHY_CURRENT_DECISION_UNRESOLVED")
    require(executor_version(plan, values["r0-critic-template.json"]) == 1,
            "LOOP_EXECUTOR_VERSION")
    require(_same(values["input.json"], payload) and plan.get("run_id") == run_id
            and plan.get("task_id") == payload["task_id"] and plan.get("binding_digest") == digest(binding),
            "RUN_REPLAY_CONFLICT")
    dependency = plan.get("execution_contract_version") == 3
    private = Path(resources.enter_context(TemporaryDirectory(prefix="kotodama-hierarchy-inspect-")))
    database = directory / "execution.sqlite"
    cut = _inspection_cut(database, private)
    state = _inspection_state(private / database.name, owner, owner.clock, dependency=dependency)
    stored = state.finalization(run_id)
    require(stored is not None and _same(stored["receipt"], receipt)
            and stored["checkpoint_digest"] == receipt.get("finalization_checkpoint_digest"),
            "FINALIZATION_CONFLICT")
    record = stored["checkpoint"]
    expected = {"run_id": run_id, "binding_digest": digest(binding), "owner_ref": binding["owner_ref"],
                "owner_input_sha256": owner_sha, "parent_input_digest": digest(payload),
                "worker_actors": receipt.get("worker_actors"), "critic_actor": receipt.get("critic_actor")}
    require(all(_same(record.get(key), value) for key, value in expected.items()), "RUN_REPLAY_CONFLICT")
    require(record.get("reuse_context") is None and record.get("context_binding_digest") == digest(None),
            "HIERARCHY_CURRENT_DECISION_UNRESOLVED")
    snapshot = state.snapshot(run_id)
    require(_same(snapshot, values["execution.json"]), "RUN_EXECUTION_CHANGED")
    require(all(_same(receipt.get(key), record.get(key)) for key in
                ("initial_plan_digest", "rounds", "dispatches", "context_bytes"))
            and _same(receipt.get("budget"), snapshot["budget"]), "FINALIZATION_CONFLICT")
    if dependency:
        require(all(_same(receipt.get(key), record.get(key)) for key in
                    ("preaccepted", "dependency_evidence_digest")), "FINALIZATION_CONFLICT")
    require(type(receipt.get("version")) is int and receipt["version"] == (3 if dependency else 2)
            and receipt.get("coordinator") == f"closed_loop_v{receipt['version']}", "LOOP_EVIDENCE_POLICY")
    check_deadline()
    candidate, learning, accepts, critic_sha, _ = terminal_evidence(directory, payload, record, state)
    require(_same(candidate, values["candidate.json"]) and _same(learning, values.get("learning.json"))
            and digest(candidate) == record.get("candidate_digest") and digest(learning) == record.get("learning_digest")
            and _same(accepts, record.get("accepts"))
            and record.get("verification_ref") == "ref/loop/verification/" + critic_sha
            and type(receipt.get("review_passed")) is bool and receipt["review_passed"] == (learning is not None),
            "FINALIZATION_CONFLICT")
    require({job for job, row in snapshot["jobs"].items() if row["state"] == "accepted"}
            == set(accepts) | set(record.get("preaccepted", {})), "FINALIZATION_OUTPUT_CONFLICT")

    work_views = [values[job + "-input.json"]["view"] for job, row in snapshot["jobs"].items()
                  if row["kind"] == "work"]
    for index in range(receipt["rounds"]):
        critic_view = values[f"r{index}-critic-input.json"]["view"]
        require(all(_contains(critic_view, span) and any(_contains(view, span) for view in work_views)
                    for span in required_spans), "HIERARCHY_PROOF_CONTEXT_MISSING")

    def current():
        current_sources(allow_expired_objective=True)
        check_deadline()
        with TemporaryDirectory(prefix="kotodama-hierarchy-recheck-") as fresh:
            fresh = Path(fresh)
            current_cut = _inspection_cut(database, fresh)
            live = _inspection_state(fresh / database.name, owner, owner.clock, dependency=dependency)
            require(live.cancellation(run_id) is None, "RUN_CANCELLED")
            require(_same(live.finalization(run_id), stored) and _same(live.snapshot(run_id), snapshot),
                    "RUN_EXECUTION_CHANGED")
            require(current_cut == cut, "RUN_ARTIFACT_CHANGED")
            with TemporaryDirectory(prefix="kotodama-hierarchy-final-") as final:
                require(_inspection_cut(database, Path(final)) == cut, "RUN_ARTIFACT_CHANGED")
        check_deadline()

    # terminal_evidence accepted each exact result packet above. Retain those
    # same manifest-pinned bytes in the shared final process/owner fence; do not
    # create new hashes from unverified post-check output.
    executor = saved_executor(directory, payload, plan, state, record, current_guard=current)
    require(executor is not None, "LOOP_EXECUTOR_MODE_UNSUPPORTED")
    executor.pin_artifacts(receipt["artifact_sha256"])
    executor.evidence.pin_receipt("receipt.json", receipt_sha)
    dispatches = []
    for job, row in sorted(snapshot["jobs"].items()):
        delivered, response = values[job + "-input.json"], values[job + "-result.json"]
        runtime = response["receipt"]["runtime"]
        executor.evidence.pin_runtime(runtime)
        core = delivered.get("core", delivered)
        attempt = row["current_attempt"]
        dispatches.append({"job_id": job, "role": core["role"], "round": core["round"],
            "input_file_sha256": receipt["artifact_sha256"][job + "-input.json"], "input_digest": digest(delivered),
            "result_file_sha256": receipt["artifact_sha256"][job + "-result.json"],
            "view_digest": core["view"]["view_digest"], "identity_kind": attempt["identity"]["kind"],
            "attempt": attempt["attempt"], "epoch": attempt["epoch"],
            "runtime_receipt_sha256": runtime["runtime_receipt_sha256"],
            "runtime_rollout_sha256": runtime["runtime_rollout_sha256"]})
    actors = {actor: owner.read_binding(payload["task_id"], actor)
              for actor in [*record["worker_actors"], record["critic_actor"]]}
    impact = values.get("repair-impact.json")
    stage = state.dependency_stage(run_id) if dependency else None
    proof = {"kind": "runtime_plan", "id": run_id, "entity_revision": payload["revision"],
        "revision_scope": "task_run", "status": "saved_artifact_and_execution_consistency",
        "receipt_sha256": receipt_sha, "specification_digest": record["initial_plan_digest"],
        "execution_plan_digest": digest(plan), "execution_mode": MODE, "rounds": receipt["rounds"],
        "finalization_checkpoint_digest": stored["checkpoint_digest"], "dispatches": dispatches,
        "live_execution_state": "completed_cut_checked", "current_cancellation": "not_cancelled_at_read",
        "current_decision": "not_observed", "learning_artifact": "candidate_only" if learning is not None else "absent",
        "repair": None if impact is None else {"impact_sha256": receipt["artifact_sha256"]["repair-impact.json"],
            "retained": impact["retained"], "new_dispatches": [row["job_id"] for row in dispatches if row["round"] == 1]},
        "dependency": None if stage is None else {"release_certificate_sha256": stage["certificate_sha256"],
            "evidence_digest": receipt["dependency_evidence_digest"], "preaccepted_jobs": sorted(record["preaccepted"])}}
    return proof, actors, executor.current
