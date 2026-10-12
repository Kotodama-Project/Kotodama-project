"""Deterministic, same-revision repair of assigned leaves; no I/O or authority.

Callers authenticate the runtime plan, original dispatch and execution snapshot.
The resulting impact is derived evidence, never a replacement Task ledger.
"""
from __future__ import annotations

import hashlib

from .protocol import canonical, digest
from .task_contract import require

PROFILE_FIELDS = {"repair_planning_contract", "repair_impact_sha256"}


def profile(template):
    """Read only after the initial template has been bound to persisted state."""
    fields = PROFILE_FIELDS.intersection(template)
    if not fields:
        return None
    require(fields == PROFILE_FIELDS and type(template["repair_planning_contract"]) is int
            and template["repair_planning_contract"] in (1, 2)
            and template.get("evidence_contract_version") == 2,
            "LOOP_REPAIR_PROFILE")
    require(template["repair_planning_contract"] != 2 or template.get("execution_contract_version") == 3,
            "LOOP_REPAIR_PROFILE")
    return template["repair_planning_contract"]


def file_sha(value):
    return hashlib.sha256((canonical(value) + "\n").encode("utf-8")).hexdigest()


def derive_repair(payload, initial, gap):
    """Return the full assigned-leaf repair or refuse; never trim to a budget."""
    from .closed_loop_contract import span_identity, validate_plan
    initial = validate_plan(initial, payload)
    require(isinstance(gap, dict) and gap.get("parent_input_digest") == digest(payload)
            and gap.get("plan_digest") == digest(initial), "LOOP_REPAIR_BINDING")
    failed = set(gap["failed_criteria"])
    if initial["version"] == 2:
        from .dependency_contract import roles
        a, b = roles(initial)
        allowed = set(b["criterion_ids"]) - set(a["criterion_ids"])
        require(failed <= allowed, "LOOP_DEPENDENCY_REPAIR_UNSUPPORTED")
    records = {item["criterion_id"]: item for item in gap["validations"]}
    require(failed and set(records) == failed and len(records) == len(gap["validations"]),
            "LOOP_REPAIR_BINDING")
    jobs, assignments, covered, selected = [], [], set(), set()
    for original in sorted(initial["jobs"], key=lambda job: job["job_id"]):
        assigned = sorted(failed.intersection(original["criterion_ids"]))
        if not assigned:
            continue
        spans = {span_identity(span): span for key in assigned for span in records[key]["source_spans"]}
        require(spans, "LOOP_REPAIR_SCOPE")
        selected.update(spans)
        covered.update(assigned)
        job_id = "repair-" + original["job_id"]
        detail = [{"criterion_id": key, "gap_reason": records[key]["gap_reason"],
                   "evidence": records[key]["evidence"]} for key in assigned]
        jobs.append({"job_id": job_id,
                     "purpose": original["purpose"] + "\nRepair verified gaps: " + canonical(detail),
                     "criterion_ids": assigned,
                     "selected_spans": [spans[key] for key in sorted(spans)]})
        assignments.append({"job_id": "r1-" + job_id, "origin_job_id": "r0-" + original["job_id"],
                            "failed_criteria": assigned, "selected_spans": jobs[-1]["selected_spans"]})
    require(covered == failed and selected == {span_identity(s) for s in gap["source_spans"]},
            "LOOP_GAP_COVERAGE")
    plan = validate_plan({"version": 1, "parent_input_digest": digest(payload), "jobs": jobs}, payload, gap=gap)
    return plan, assignments


def make_impact(payload, initial, runtime_plan, prior, work_inputs, snapshot):
    """Revalidate prior evidence and reconstruct the original pre-repair cut.

    Later repair attempts and acceptance timestamps are deliberately excluded.
    Live admission must independently recheck its remaining budget and leases.
    """
    from .closed_loop_contract import validate_critic, verified_gap
    initial_jobs = {job["job_id"] for job in runtime_plan["jobs"]}
    work = {job["job_id"] for job in runtime_plan["jobs"] if job["kind"] == "work"}
    require(canonical(snapshot["plan"]) == canonical(runtime_plan), "LOOP_REPAIR_STATE")
    previous = prior["dispatched_input"]
    template = {key: value for key, value in previous.items()
                if key not in {"template_digest", "reports", "report_digests", "release_certificate", "release_certificate_sha256", "prerequisite_inputs"}}
    critic = validate_critic(prior["response"]["result"], payload, previous["reports"],
        view=previous["view"], plan_digest=digest(initial), round_index=0,
        initial_execution_plan_digest=digest(runtime_plan), expected_jobs=work,
        dispatched_input=previous, dispatched_input_digest=prior["dispatched_input_digest"],
        initial_specification=initial, initial_runtime_plan=runtime_plan,
        initial_template=template, work_inputs=work_inputs,
        dependency_stage=snapshot.get("dependency_stage"))
    require(prior["response"]["receipt"]["input_digest"] == prior["dispatched_input_digest"],
            "LOOP_INPUT_RECEIPT_MISMATCH")
    critic_sha = file_sha(prior["response"])
    gap = verified_gap(critic, critic_job_id="r0-critic", critic_result_digest=critic_sha)
    require(gap is not None, "LOOP_REPAIR_BINDING")
    proposal, assignments = derive_repair(payload, initial, gap)
    attempts, retained = [], []
    targeted = {item["origin_job_id"] for item in assignments}
    for name in sorted(initial_jobs):
        row = snapshot["jobs"][name]
        require(row["state"] in {"reported", "accepted"} and row["attempts"], "LOOP_REPAIR_STATE")
        for attempt in row["attempts"]:
            attempts.append({key: attempt[key] for key in ("job_id", "attempt", "token", "epoch")})
        if name == "r0-critic":
            require(row["current_attempt"]["result_digest"] == critic_sha, "LOOP_REPAIR_STATE")
        if name in work - targeted:
            retained.append({"job_id": name, "input_digest": digest(work_inputs[name]),
                "report_digest": digest(previous["reports"][name]),
                "result_sha256": row["current_attempt"]["result_digest"]})
    remaining = runtime_plan["budget"]["attempt_budget"] - len(attempts)
    require(remaining >= len(proposal["jobs"]) + 1, "LOOP_REPAIR_BUDGET")
    impact = {"version": 1, "kind": "assigned_gap_repair", "task_id": payload["task_id"],
        "revision": payload["revision"], "parent_input_digest": digest(payload),
        "initial_specification_digest": digest(initial), "initial_execution_plan_digest": digest(runtime_plan),
        "critic_result_sha256": critic_sha, "critic_input_digest": prior["dispatched_input_digest"],
        "gap_digest": digest(gap), "failed_criteria": sorted(gap["failed_criteria"]),
        "assignments": assignments, "retained": retained, "proposal_digest": digest(proposal),
        "budget_cut": {"attempt_budget": runtime_plan["budget"]["attempt_budget"],
                       "deadline": runtime_plan["budget"]["deadline"], "attempts": attempts,
                       "attempts_used": len(attempts), "remaining_attempts": remaining},
        "planned_calls": len(proposal["jobs"]) + 1}
    if initial["version"] == 2:
        from .dependency_contract import check_stage
        stage = check_stage(snapshot.get("dependency_stage"), runtime_plan)
        require(stage["status"] == "released", "LOOP_RELEASE_INVALID")
        impact.update(version=2, release_certificate_sha256=stage["certificate_sha256"])
    return proposal, impact


def inspect_repair(owner_path, payload_path, *, clock=None):
    """Read a saved, current r0 review; return a proposal without admitting it."""
    from pathlib import Path
    import time
    from .closed_loop_contract import evidence_version
    from .owner_file import OwnerFile
    from .state import SwarmState
    from .task_contract import validate_input
    from .task_runner import read_json, safe_directory
    clock = clock or time.time
    owner = OwnerFile(owner_path, clock=clock)
    _, owner_sha = read_json(Path(owner_path), 1024 * 1024, with_digest=True)
    binding = owner.read_task()
    payload = validate_input(read_json(Path(payload_path), 256 * 1024), binding, now=clock())
    run_id = "task-run-" + digest([payload["task_id"], payload["revision"]])[:32]
    directory = safe_directory(owner.storage()["root"] / run_id)
    # This standalone entry has no origin context/current decision reader.
    # A stored learning lane cannot be inspected using a bare owner alone.
    require("learning_reuse" not in read_json(Path(owner_path), 1024 * 1024)
            and not (directory/"context-binding.json").exists(),
            "LOOP_REUSE_INSPECTION_UNSUPPORTED")
    require(read_json(directory/"input.json") == payload, "RUN_REPLAY_CONFLICT")
    initial = read_json(directory/"specification.json")
    plan = read_json(directory/"plan.json")
    state = SwarmState(directory/"execution.sqlite", owner.read_task, clock=clock)
    stage = state.dependency_stage(run_id)
    if stage is not None:
        progress, progress_sha = read_json(directory/"release-progress.json", with_digest=True)
        require(progress_sha == stage["certificate"]["progress_sha256"], "LOOP_RELEASE_CHANGED")
        require(isinstance(progress, dict), "LOOP_RELEASE_INVALID")
        metadata, artifacts = progress.get("metadata"), progress.get("artifacts")
        require(isinstance(metadata, dict) and isinstance(artifacts, dict)
                and "reuse_context" in metadata, "LOOP_RELEASE_INVALID")
        require(metadata["reuse_context"] is None
                and metadata.get("context_binding_digest") == digest(None)
                and "context-binding.json" not in artifacts,
                "LOOP_REUSE_INSPECTION_UNSUPPORTED")
    finalization = state.finalization(run_id)
    if finalization is not None:
        checkpoint = finalization["checkpoint"]
        require(checkpoint["reuse_context"] is None
                and checkpoint["context_binding_digest"] == digest(None)
                and "context-binding.json" not in checkpoint["artifact_sha256"],
                "LOOP_REUSE_INSPECTION_UNSUPPORTED")
    snapshot = state.snapshot(run_id)
    require(state.cancellation(run_id) is None, "RUN_CANCELLED")
    require(plan["binding_digest"] == digest(binding) and plan["run_id"] == run_id,
            "LOOP_REPAIR_STATE")
    template = read_json(directory/"r0-critic-template.json")
    require(canonical(snapshot["plan"]) == canonical(plan), "LOOP_REPAIR_STATE")
    evidence_version(plan, template)
    require(profile(template) in (1, 2), "LOOP_REPAIR_PROFILE")
    require(all(snapshot["jobs"][job["job_id"]]["state"] in {"reported", "accepted"}
                for job in plan["jobs"]), "LOOP_REPAIR_STATE")
    response = read_json(directory/"r0-critic-result.json")
    delivered = read_json(directory/"r0-critic-input.json")
    inputs = {}
    for job in plan["jobs"]:
        name = job["job_id"]
        value, sha = read_json(directory/(name+"-result.json"), with_digest=True)
        require(snapshot["jobs"][name]["current_attempt"]["result_digest"] == sha,
                "RUN_ARTIFACT_CHANGED")
        if job["kind"] == "work":
            require(value["result"] == delivered["reports"][name], "LOOP_PRIOR_REPORT_CHANGED")
            inputs[name] = read_json(directory/(name+"-input.json"))
    result = make_impact(payload, initial, plan, {"response": response, "dispatched_input": delivered,
                        "dispatched_input_digest": digest(delivered)}, inputs, snapshot)
    require(read_json(Path(owner_path), 1024 * 1024, with_digest=True)[1] == owner_sha
            and owner.read_task() == binding and read_json(Path(payload_path), 256 * 1024) == payload,
            "STALE_BINDING")
    validate_input(payload, binding, now=clock())
    require(state.cancellation(run_id) is None, "RUN_CANCELLED")
    return {"proposal": result[0], "impact": result[1], "admitted": False}


def main(argv=None):
    """Inspect a saved gap without changing the Task or dispatching work."""
    import argparse
    import sys
    from .protocol import SwarmError
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--input", required=True)
    args = parser.parse_args(argv)
    try:
        print(canonical(inspect_repair(args.owner, args.input)))
        return 0
    except OSError:
        print(canonical({"error": "RUN_ARTIFACT_CHANGED", "message": "saved input is unavailable"}), file=sys.stderr)
        return 2
    except SwarmError as error:
        print(canonical({"error": error.code, "message": error.detail}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
