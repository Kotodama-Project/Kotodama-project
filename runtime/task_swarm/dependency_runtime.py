"""Stored release reconstruction shared by execution and historical readers."""
from __future__ import annotations

from .protocol import canonical, digest
from .task_contract import require, shape
from .task_runner import read_json, write_json
from .dependency_contract import (REVIEW_ID, attempt_proof, check_descriptor, dependent_input,
                                  descriptor, review_input, validate_prerequisite)


def release(directory, payload, spec, plan, state, metadata, artifacts, dispatches, context_bytes,
            *, guard, invoke, report, save, actor, clock, cancel_event):
    desc, template = descriptor(payload, spec)
    a, b = desc["a_job_id"], desc["b_job_id"]
    response, sha = read_json(directory / (a + "-result.json"), with_digest=True)
    delivered = review_input(template, response["result"], sha)
    guard()
    lease = state.claim(plan["run_id"], actor)
    require(lease is not None and lease["job_id"] == REVIEW_ID, "RUN_REVIEW_MISSING")
    result = invoke(lease, delivered, actor, critic=True)
    passed = validate_prerequisite(result["result"], payload, spec, delivered, response["result"], sha)
    report(lease, result)
    progress = {"metadata": metadata, "artifacts": dict(artifacts),
                "dispatches": dict(dispatches), "context_bytes": context_bytes()}
    progress_sha = save("release-progress.json", progress)
    snapshot = state.snapshot(plan["run_id"])
    certificate = {"version": 1, "run_id": plan["run_id"], "binding_digest": plan["binding_digest"],
        "initial_execution_plan_digest": digest(plan), "descriptor_sha256": digest(desc),
        "progress_sha256": progress_sha, "owner_ref": metadata["owner_ref"],
        "a_job_id": a, "b_job_id": b,
        "a": attempt_proof(snapshot["jobs"][a]["current_attempt"]),
        "review": attempt_proof(snapshot["jobs"][REVIEW_ID]["current_attempt"])}
    stage = {"version": 1, "status": "released" if passed else "blocked", "certificate": certificate,
        "certificate_sha256": digest(certificate), "actual_input_digest": None,
        "accepted_at": clock() if passed else None,
        "verification_ref": "ref/loop/prerequisite/" + digest(certificate) if passed else None}
    if passed:
        from .closed_loop_contract import work_input
        original = next(job for job in spec["jobs"] if "r0-" + job["job_id"] == b)
        b_template = work_input(payload, original, 0, digest(spec), round_plan_digest=digest(spec))
        stage["actual_input_digest"] = digest(dependent_input(b_template, stage, response["result"]))
    # Source/actor/deadline checks and transaction are serialized with owner
    # cancellation. No backend executes inside this operation lock.
    from .closed_loop_recovery import operation_lock
    with operation_lock(directory):
        from .closed_loop_recovery import checked_artifacts
        guard()
        checked_artifacts(directory, artifacts)
        require(read_json(directory / "release-progress.json", with_digest=True) == (progress, progress_sha), "LOOP_RELEASE_CHANGED")
        from .loop_executor_runtime import saved_executor
        executor = saved_executor(directory, payload, plan, state, metadata)
        if executor is not None:
            executor.pin_artifacts(artifacts)
            executor.verify(a, read_json(directory/(a+"-input.json")), response)
            executor.verify(REVIEW_ID, delivered, result)
            executor.current()
        return state.commit_dependency_stage(plan["run_id"], stage,
            expected_state_digest=state.finalization_evidence_digest(plan["run_id"]), cancel_event=cancel_event)


def verify_release(directory, payload, spec, plan, state, metadata):
    """Reconstruct only pinned explicit files; no history scan or fallback."""
    from .closed_loop_contract import work_input
    desc = read_json(directory / "dependency-descriptor.json")
    template = read_json(directory / (REVIEW_ID + "-template.json"))
    check_descriptor(payload, spec, plan, desc, template)
    stage = state.dependency_stage(plan["run_id"])
    require(stage is not None, "RUN_RECOVERY_REQUIRED")
    progress, sha = read_json(directory / "release-progress.json", with_digest=True)
    shape(progress, {"metadata", "artifacts", "dispatches", "context_bytes"}, "LOOP_RELEASE_INVALID")
    require(sha == stage["certificate"]["progress_sha256"] and progress["metadata"] == metadata,
            "LOOP_RELEASE_CHANGED")
    from .closed_loop_recovery import checked_artifacts
    values, _ = checked_artifacts(directory, progress["artifacts"])
    require(values["input.json"] == payload and values["specification.json"] == spec
            and values["plan.json"] == plan and values["dependency-descriptor.json"] == desc
            and values[REVIEW_ID + "-template.json"] == template, "LOOP_RELEASE_CHANGED")
    from .loop_executor_runtime import saved_executor
    executor = saved_executor(directory, payload, plan, state, metadata)
    if executor is not None:
        executor.pin_artifacts(progress["artifacts"])
        executor.pin_artifacts({"release-progress.json": sha})
    a = desc["a_job_id"]
    original = next(job for job in spec["jobs"] if "r0-" + job["job_id"] == a)
    a_input = work_input(payload, original, 0, digest(spec), round_plan_digest=digest(spec))
    require(values[a + "-input.json"] == a_input, "LOOP_RELEASE_CHANGED")
    response = values[a + "-result.json"]
    reviewed = values[REVIEW_ID + "-result.json"]
    for job, value, delivered in ((a, response, a_input),
                                 (REVIEW_ID, reviewed, values[REVIEW_ID + "-input.json"])):
        proof = stage["certificate"]["a" if job == a else "review"]
        receipt = value["receipt"]
        require(progress["artifacts"][job + "-result.json"] == proof["result_digest"]
                and (executor is not None or receipt == {"actor_ref": proof["worker_ref"], "invocation_ref": proof["identity"]["thread_id"],
                                "input_digest": digest(delivered), "synthetic": True})
                and progress["dispatches"][job] == {"declared_input_ref": "ref/loop/" + ("template/" if job == REVIEW_ID else "input/") + job,
                    "declared_input_digest": next(item["payload_digest"] for item in plan["jobs"] if item["job_id"] == job),
                    "delivered_input_digest": digest(delivered)}, "LOOP_RELEASE_CHANGED")
        if executor is not None:
            require(attempt_proof(executor.snapshot["jobs"][job]["current_attempt"]) == proof, "LOOP_RELEASE_CHANGED")
            executor.verify(job, delivered, value)
    actor = metadata["worker_actors"][["r0-"+job["job_id"] for job in sorted(spec["jobs"], key=lambda job:job["job_id"])].index(a)]
    require(response["receipt"]["actor_ref"] == actor
            and reviewed["receipt"]["actor_ref"] == metadata["critic_actor"], "REVIEW_NOT_INDEPENDENT")
    passed = validate_prerequisite(reviewed["result"], payload, spec,
        values[REVIEW_ID + "-input.json"], response["result"], progress["artifacts"][a + "-result.json"])
    require((stage["status"] == "released") == passed, "LOOP_RELEASE_CHANGED")
    if passed:
        original = next(job for job in spec["jobs"] if "r0-" + job["job_id"] == desc["b_job_id"])
        template_b = work_input(payload, original, 0, digest(spec), round_plan_digest=digest(spec))
        require(digest(dependent_input(template_b, stage, response["result"])) == stage["actual_input_digest"], "LOOP_RELEASE_CHANGED")
    require(progress["context_bytes"] == sum(len(canonical(values[job + "-input.json"]).encode("utf-8"))
            for job in (a, REVIEW_ID)), "LOOP_RELEASE_CHANGED")
    if executor is not None:
        executor.current()
    return stage, progress, values


def blocked_result(stage):
    return {"status": "blocked", "error": "LOOP_PREREQUISITE_BLOCKED",
            "evidence_ref": "ref/loop/prerequisite/" + stage["certificate_sha256"],
            "stage": stage, "receipt": None, "learning_candidate": None}
