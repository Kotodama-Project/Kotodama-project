"""Bounded closed-loop coordinator over the existing owner and SwarmState.

The injectable backend is currently restricted to explicit local simulations.
The same claim/report/verify/accept path handles every frontier and its critic;
No provider, Task authority or knowledge adoption is added.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
from pathlib import Path
import threading
import time

from . import protocol
from .closed_loop_contract import (loop_criteria, span_identity, validate_critic, validate_plan, verified_gap,
                                   evidence_version, required_evidence_jobs, work_input)
from .closed_loop_context import derive_child_view, validate_report_in_view
from .repair_planning import make_impact, derive_repair
from .closed_loop_cancellation import cancel_closed_loop
from .closed_loop_recovery import finalize, make_checkpoint, operation_lock, terminal_evidence, read_artifact
from .owner_file import OwnerFile
from .state import SwarmState
from .task_contract import require, shape, validate_input
from .task_runner import read_json, safe_directory, write_json


MAX_CONTEXT_BYTES = 512 * 1024
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024


def execute_closed_loop(owner_path, payload_path, supplied_plan, backend, *,
                        worker_actors, critic_actor="verifier", repair_planner=None,
                        cancel_event=None, clock=time.time, expected_receipt_sha256=None,
                        reuse_context=None, resume_finalization=False):
    """Execute a supplied parallel frontier and one verified-gap repair in one run.

    This low-level API executes an explicit caller plan; Source provenance of
    its dependency edge requires the source producer and candidate validator.
    The assigned-leaf repair is derived locally. An optional pure callback may
    propose the identical plan, but cannot override its scope or select legacy mode.
    A completed run supports anchored readback. Explicit terminal checkpoint
    resume never re-dispatches work or renews the budget; earlier interruptions
    require recovery outside this entrypoint.
    """
    started = time.monotonic()
    require(getattr(backend, "synthetic", False) is True, "LOOP_SIMULATION_REQUIRED")
    require(type(resume_finalization) is bool and not (resume_finalization and expected_receipt_sha256 is not None),
            "FINALIZATION_OPTIONS_INVALID")
    stage_resume = False
    replay_only = expected_receipt_sha256 is not None
    owner_path, payload_path = Path(owner_path), Path(payload_path)
    owner = OwnerFile(owner_path, clock=clock)
    _, owner_sha = read_json(owner_path, 1024 * 1024, with_digest=True)
    has_reuse_grant = "learning_reuse" in read_json(owner_path, 1024 * 1024)
    if resume_finalization:
        # Recover only the stored bounded configuration. Actual current owner,
        # source and reuse decision validation below remains mandatory.
        original = read_json(payload_path, 256 * 1024)
        original = validate_input(original, owner.read_task(original.get("task_id")), now=clock())
        resume_id = "task-run-" + protocol.digest([original["task_id"], original["revision"]])[:32]
        resume_dir = owner.storage()["root"] / resume_id
        require(resume_dir.is_dir(), "RUN_RECOVERY_REQUIRED")
        resume_dir = safe_directory(resume_dir)
        require((resume_dir / "execution.sqlite").is_file(), "RUN_RECOVERY_REQUIRED")
        resume_state = SwarmState(resume_dir / "execution.sqlite", owner.read_task, clock=clock)
        checkpoint = resume_state.finalization(resume_id)
        if checkpoint is None:
            stored_plan = read_json(resume_dir / "plan.json")
            require(stored_plan.get("execution_contract_version") == 3, "RUN_RECOVERY_REQUIRED")
            stage = resume_state.dependency_stage(resume_id)
            require(stage is not None, "RUN_RECOVERY_REQUIRED")
            progress, progress_sha = read_json(resume_dir / "release-progress.json", with_digest=True)
            require(progress_sha == stage["certificate"]["progress_sha256"], "LOOP_RELEASE_CHANGED")
            saved_context = progress["metadata"]["reuse_context"]
            stage_resume = True
        else:
            saved_context = checkpoint["checkpoint"]["reuse_context"]
        require(reuse_context is None or protocol.canonical(reuse_context) == protocol.canonical(saved_context),
                "RUN_CONTEXT_REPLAY_CONFLICT")
        reuse_context = saved_context
    require(has_reuse_grant == (reuse_context is not None), "LOOP_REUSE_CONTEXT_REQUIRED")
    reuse_owner, context_binding, decision_digest = None, None, None
    if reuse_context is not None:
        # Construct the actual current owner/store reader here. A caller's
        # success callback or self-declared binding cannot replace this check.
        shape(reuse_context, {"origin_owner", "origin_input", "anchor", "proposal", "decision_digest"},
              "LOOP_REUSE_CONTEXT_INVALID")
        require(len(protocol.canonical(reuse_context).encode("utf-8")) <= 32768,
                "LOOP_REUSE_CONTEXT_INVALID")
        from .learning_reuse import ReuseOwner
        decision_digest = reuse_context["decision_digest"]
        reuse_owner = ReuseOwner(reuse_context["origin_owner"], reuse_context["origin_input"],
            reuse_context["anchor"], owner_path, payload_path, reuse_context["proposal"], clock=clock,
            allow_expired_objective=replay_only)
        context_binding = reuse_owner.context_binding(decision_digest)
    payload = read_json(payload_path, 256 * 1024)
    binding = owner.read_task(payload.get("task_id"))
    payload = validate_input(payload, binding, now=clock(), allow_expired_objective=replay_only)
    require(payload["version"] == 2, "LOOP_OBJECTIVE_REQUIRED")
    specification = validate_plan(supplied_plan, payload)
    initial_specification = specification
    from .dependency_contract import descriptor, dependent_input, execution_version, REVIEW_ID
    from .dependency_runtime import verify_release, blocked_result, release as release_prerequisite
    dependency = specification["version"] == 2
    dependency_stage = None
    dependency_descriptor, prerequisite_template = descriptor(payload, specification) if dependency else (None, None)
    initial_digest, parent_digest = protocol.digest(specification), protocol.digest(payload)
    root = safe_directory(owner.storage()["root"])
    require(Path(binding["active_home"]).is_absolute()
            and Path(binding["active_home"]).resolve() == root, "RUN_HOME_MISMATCH")
    require(isinstance(worker_actors, (list, tuple)) and 1 <= len(worker_actors) <= 3,
            "LOOP_ACTORS_INVALID")
    actors = list(worker_actors)
    for actor in [*actors, critic_actor]:
        protocol.ref(actor, "loop actor")
    require(len(set([*actors, critic_actor, binding["owner_ref"]])) == len(actors) + 2,
            "RUN_OWNER_INDEPENDENCE")
    require(len(specification["jobs"]) <= len(actors), "LOOP_ACTORS_INVALID")
    actor_bindings = {actor: owner.read_binding(binding["task_id"], actor)
                      for actor in [*actors, critic_actor]}
    for value in actor_bindings.values():
        require(value["actor_status"] == "active" and value["capability_ref"] == binding["capability_ref"],
                "RUN_ACTOR_SCOPE_INVALID")
    cancellation = cancel_event if cancel_event is not None else threading.Event()
    require(isinstance(cancellation, threading.Event), "RUN_CANCELLATION_INVALID")
    binding_digest = protocol.digest(binding)
    deadline = payload["objective"]["budget"]["deadline"]
    state = None
    failures = []
    failure_lock = threading.Lock()

    def guard():
        if state is not None:
            require(state.cancellation(run_id) is None, "RUN_CANCELLED")
        with failure_lock:
            failure = failures[0] if failures else None
            cancelled = cancellation.is_set()
        if failure is not None:
            raise protocol.SwarmError(*failure)
        require(not cancelled, "RUN_CANCELLED")
        require(protocol.digest(owner.read_task(binding["task_id"])) == binding_digest, "STALE_BINDING")
        require(all(owner.read_binding(binding["task_id"], actor) == original
                    for actor, original in actor_bindings.items()), "STALE_ACTOR")
        require(replay_only or clock() < deadline, "DEADLINE_EXPIRED")
        require(owner.storage()["root"] == root and safe_directory(root) == root, "RUN_STORAGE_CHANGED")
        require(read_json(owner_path, 1024 * 1024, with_digest=True)[1] == owner_sha, "OWNER_INPUT_CHANGED")
        if reuse_owner is not None:
            reuse_owner.current(decision_digest)

    # The Task/revision fixes the run identity, not the supplied plan or attempt.
    # Changing the plan cannot sidestep this directory and refill its budget.
    run_id = "task-run-" + protocol.digest([payload["task_id"], payload["revision"]])[:32]
    directory = root / run_id
    if directory.is_dir():
        safe_directory(directory)
        if (directory / "execution.sqlite").is_file():
            state = SwarmState(directory / "execution.sqlite", owner.read_task, clock=clock)
    def finalization_metadata(runtime_plan):
        return {"run_id": run_id, "binding_digest": binding_digest, "owner_ref": binding["owner_ref"],
                "owner_input_sha256": owner_sha, "parent_input_digest": parent_digest,
                "initial_plan_digest": initial_digest, "initial_execution_plan_digest": protocol.digest(runtime_plan),
                "worker_actors": actors, "critic_actor": critic_actor,
                "actor_binding_digests": {k: protocol.digest(v) for k, v in actor_bindings.items()},
                "reuse_context": reuse_context, "context_binding_digest": protocol.digest(context_binding)}

    guard()
    resume_progress = None
    if dependency and directory.is_dir() and not (directory / "receipt.json").exists():
        require(state is not None, "RUN_RECOVERY_REQUIRED")
        if state.finalization(run_id) is None:
            with operation_lock(directory):
                guard()
                saved_plan = read_json(directory / "plan.json")
                require(state.snapshot(run_id)["plan"] == saved_plan, "RUN_REPLAY_CONFLICT")
                dependency_stage, progress, saved_values = verify_release(directory, payload, specification,
                    saved_plan, state, finalization_metadata(saved_plan))
                if dependency_stage["status"] == "blocked":
                    require(expected_receipt_sha256 is None, "RUN_REPLAY_MISSING")
                    return blocked_result(dependency_stage)
                require(stage_resume and resume_finalization, "RUN_RECOVERY_REQUIRED")
                b_row = state.snapshot(run_id)["jobs"][dependency_descriptor["b_job_id"]]
                require(b_row["state"] == "pending" and b_row["attempt_count"] == 0, "RUN_RECOVERY_REQUIRED")
                resume_progress = progress
    if directory.exists() and resume_progress is None:
        safe_directory(directory)
        if resume_finalization:
            with operation_lock(directory):
                require(not (directory / "receipt.json").exists(), "RUN_REPLAY_ANCHOR_REQUIRED")
                guard()
                state = SwarmState(directory / "execution.sqlite", owner.read_task, clock=clock)
                result = finalize(directory, payload, state, finalization_metadata(read_json(directory / "plan.json")),
                                  guard=guard, reuse_owner=reuse_owner, cancel_event=cancellation)
                return {**result, "recovered_finalization": True}
        require((directory / "receipt.json").is_file(), "RUN_RECOVERY_REQUIRED")
        require(isinstance(expected_receipt_sha256, str) and len(expected_receipt_sha256) == 64,
                "RUN_REPLAY_ANCHOR_REQUIRED")
        protocol.digest_ref(expected_receipt_sha256, "receipt anchor")
        receipt, sha = read_json(directory / "receipt.json", with_digest=True)
        require(sha == expected_receipt_sha256, "RUN_REPLAY_ANCHOR_MISMATCH")
        require(receipt["binding_digest"] == binding_digest and receipt["owner_input_sha256"] == owner_sha
                and receipt["parent_input_digest"] == parent_digest
                and receipt["initial_plan_digest"] == initial_digest
                and receipt["worker_actors"] == actors and receipt["critic_actor"] == critic_actor,
                "RUN_REPLAY_CONFLICT")
        artifacts = receipt["artifact_sha256"]
        require(isinstance(artifacts, dict) and {"input.json", "specification.json", "plan.json",
                "candidate.json", "execution.json"}.issubset(artifacts), "RUN_RECEIPT_INVALID")
        checked = {}
        for name, expected_sha in artifacts.items():
            require(isinstance(name, str) and Path(name).name == name and name.endswith(".json"),
                    "RUN_RECEIPT_INVALID")
            value, actual = read_artifact(directory / name, with_digest=True)
            require(actual == expected_sha, "RUN_ARTIFACT_CHANGED")
            checked[name] = value
        require(checked["input.json"] == payload and checked["specification.json"] == specification,
                "RUN_REPLAY_CONFLICT")
        require(checked.get("context-binding.json") == context_binding, "RUN_CONTEXT_REPLAY_CONFLICT")
        state = SwarmState(directory / "execution.sqlite", owner.read_task, clock=clock)
        finalization = None
        if "finalization_checkpoint_digest" in receipt:
            finalization = state.finalization(run_id)
            require(finalization is not None
                    and finalization["checkpoint_digest"] == receipt["finalization_checkpoint_digest"]
                    and protocol.canonical(finalization["receipt"]) == protocol.canonical(receipt),
                    "FINALIZATION_CONFLICT")
        snapshot = state.snapshot(run_id)
        require(protocol.canonical(snapshot) == protocol.canonical(checked["execution.json"]),
                "RUN_EXECUTION_CHANGED")
        require(protocol.canonical(snapshot["plan"]) == protocol.canonical(checked["plan.json"]),
                "FINALIZATION_PLAN_CONFLICT")
        evidence = evidence_version(checked["plan.json"], checked["r0-critic-template.json"])
        version = execution_version(checked["plan.json"]) or evidence
        require(type(receipt.get("version")) is int and receipt["version"] == version
                and receipt.get("coordinator") == f"closed_loop_v{version}", "LOOP_EVIDENCE_POLICY")
        if version in (2, 3):
            require(finalization is not None, "LOOP_EVIDENCE_POLICY")
            candidate, learning, _, _, _ = terminal_evidence(directory, payload, finalization["checkpoint"], state)
            require(candidate == checked["candidate.json"] and learning == checked.get("learning.json"),
                    "FINALIZATION_CONFLICT")
        guard()
        if reuse_owner is not None:
            reuse_owner.validate_candidate(checked["candidate.json"])
        return {"candidate": checked["candidate.json"], "learning_candidate": checked.get("learning.json"),
                "receipt": receipt, "receipt_sha256": sha, "duplicate": True}
    require(expected_receipt_sha256 is None, "RUN_REPLAY_MISSING")
    require(not resume_finalization or resume_progress is not None, "RUN_RECOVERY_REQUIRED")
    # A structurally valid per-job selection can exceed the critic's union.
    # Refuse before claiming this Task/revision's directory, so a corrected
    # initial plan can still run without resetting any admitted run or budget.
    require(len({span_identity(span) for job in specification["jobs"]
                 for span in job["selected_spans"]}) <= 32, "LOOP_CONTEXT_LIMIT")
    required_evidence_jobs(payload, initial_specification)
    if resume_progress is None:
        directory.mkdir(mode=0o700)
    artifacts = dict(resume_progress["artifacts"]) if resume_progress else {}
    if resume_progress:
        artifacts["release-progress.json"] = read_json(directory / "release-progress.json", with_digest=True)[1]
    artifact_bytes = sum((directory / name).stat().st_size for name in artifacts)
    context_bytes = resume_progress["context_bytes"] if resume_progress else 0
    save_lock = threading.Lock()

    def save(name, value):
        nonlocal artifact_bytes
        size = len((protocol.canonical(value) + "\n").encode("utf-8"))
        with save_lock:
            if name in artifacts:
                require(read_json(directory / name) == value, "RUN_ARTIFACT_CHANGED")
                return artifacts[name]
            require(artifact_bytes + size <= MAX_ARTIFACT_BYTES, "LOOP_ARTIFACT_BUDGET")
            sha = write_json(directory / name, value)
            artifacts[name] = sha
            artifact_bytes += size
        return sha

    def verify_artifacts():
        safe_directory(directory)
        with save_lock:
            expected = list(artifacts.items())
        for name, sha in expected:
            require(read_artifact(directory / name, with_digest=True)[1] == sha, "RUN_ARTIFACT_CHANGED")

    save("input.json", payload)
    save("specification.json", specification)
    if context_binding is not None:
        save("context-binding.json", context_binding)
    all_reports, report_jobs, invocations, dispatches = {}, {}, set(), {}
    if dependency:
        save("dependency-descriptor.json", dependency_descriptor)
        save(REVIEW_ID + "-template.json", prerequisite_template)
    if resume_progress:
        dispatches.update(resume_progress["dispatches"])
        a = dependency_descriptor["a_job_id"]
        response = read_json(directory / (a + "-result.json"))
        all_reports[a] = response["result"]
        report_jobs[a] = {"artifact_digest": artifacts[a + "-result.json"],
            "selected_spans": next(job["selected_spans"] for job in specification["jobs"] if "r0-" + job["job_id"] == a)}
        invocations.update(read_json(directory / (name + "-result.json"))["receipt"]["invocation_ref"] for name in dispatches)
    impact, impact_sha = None, None
    criteria = loop_criteria(payload)

    def frontier(spec, index, previous=None):
        round_digest = protocol.digest(spec)
        work_inputs, runtime_jobs, job_actors = {}, [], {}
        selected = []
        for number, job in enumerate(sorted(spec["jobs"], key=lambda j: j["job_id"])):
            job_id = f"r{index}-" + job["job_id"]
            delivered = work_input(payload, job, index, initial_digest,
                                   round_plan_digest=round_digest, previous=previous)
            if dependency and index:
                delivered = dependent_input(delivered, dependency_stage, all_reports[dependency_descriptor["a_job_id"]])
            work_inputs[job_id], job_actors[job_id] = delivered, actors[number]
            dependencies = [dependency_descriptor["a_job_id"]] if dependency and (index or job_id == dependency_descriptor["b_job_id"]) else []
            runtime_jobs.append({"job_id": job_id, "kind": "work", "dependencies": dependencies, "exclusive_keys": [],
                                 "payload_ref": "ref/loop/input/" + job_id,
                                 "payload_digest": protocol.digest(delivered)})
            selected.extend(job["selected_spans"])
        # The critic sees all reports, including earlier conflicts, and the
        # bounded union of their source context. No source lookup is implicit.
        for old in report_jobs.values():
            selected.extend(old["selected_spans"])
        unique = {tuple(s[k] for k in ("source_key", "source_revision", "start", "end")): s for s in selected}
        require(len(unique) <= 32, "LOOP_CONTEXT_LIMIT")
        critic_id = f"r{index}-critic"
        critic_input = {"role": "critic", "job_id": critic_id, "round": index,
                        "round_plan_digest": round_digest, "criteria": criteria,
                        "view": derive_child_view(payload, critic_id, list(unique.values()),
                            plan_digest=initial_digest, previous_critic_digest=previous)}
        gap = verified_gap(prior_review["response"]["result"], critic_job_id="r0-critic",
                           critic_result_digest=previous) if index else None
        if dependency:
            critic_input.update(execution_contract_version=3, dependency_descriptor_sha256=protocol.digest(dependency_descriptor))
            if index == 0:
                runtime_jobs.append({"job_id": REVIEW_ID, "kind": "review", "dependencies": [dependency_descriptor["a_job_id"]],
                    "exclusive_keys": [], "payload_ref": "ref/loop/template/" + REVIEW_ID,
                    "payload_digest": protocol.digest(prerequisite_template)})
        critic_input.update(repair_planning_contract=2 if dependency else 1, repair_impact_sha256=impact_sha if index else None)
        critic_input.update(evidence_contract_version=2, required_evidence_jobs=required_evidence_jobs(
            payload, initial_specification, spec if index else None, gap=gap))
        save(critic_id + "-template.json", critic_input)
        runtime_jobs.append({"job_id": critic_id, "kind": "review",
                             "dependencies": sorted(set(all_reports) | set(work_inputs)), "exclusive_keys": [],
                             "payload_ref": "ref/loop/template/" + critic_id,
                             "payload_digest": protocol.digest(critic_input)})
        return work_inputs, critic_input, runtime_jobs, job_actors

    work_inputs, critic_input, jobs, job_actors = frontier(specification, 0)
    plan = {"run_id": run_id, "task_id": payload["task_id"], "binding_digest": binding_digest,
            "budget": {**payload["objective"]["budget"], "concurrency": len(actors), "verifier_reserve": 2 if dependency else 1},
            "jobs": jobs}
    if dependency:
        plan.update(execution_contract_version=3, dependency_descriptor_sha256=protocol.digest(dependency_descriptor))
    require(len(jobs) <= plan["budget"]["attempt_budget"], "LOOP_ATTEMPT_BUDGET")
    state = SwarmState(directory / "execution.sqlite", owner.read_task, clock=clock)
    plan = state.create_run(plan)
    save("plan.json", plan)
    done = threading.Event()

    def monitor():
        while not done.wait(.1):
            try:
                guard()
            except Exception as exc:
                with failure_lock:
                    if not failures and not cancellation.is_set():
                        if isinstance(exc, protocol.SwarmError):
                            failures.append((exc.code, exc.detail))
                        else:
                            failures.append(("BINDING_UNAVAILABLE",
                                             "Task owner binding could not be validated"))
                    cancellation.set()
                return

    watcher = threading.Thread(target=monitor, name="loop-owner-watch", daemon=True)
    watcher.start()

    def fail_preserving_error(lease, error, fallback):
        try:
            state.fail(lease["token"], getattr(error, "code", fallback), retryable=False)
        except Exception:
            # A revoked owner can refuse cleanup too. Keep the operation's
            # original failure and leave its attempt for explicit recovery.
            pass

    def invoke(lease, delivered, actor, *, critic=False):
        nonlocal context_bytes
        guard()
        if reuse_owner is not None and not critic:
            reuse_owner.validate_delivery(delivered)
        if critic:
            template = {key: value for key, value in delivered.items()
                        if key not in {"template_digest", "reports", "report_digests", "report", "report_sha256", "release_certificate", "release_certificate_sha256", "prerequisite_inputs"}}
            require(protocol.digest(template) == delivered["template_digest"] == lease["payload_digest"]
                    and read_json(directory/(lease["job_id"]+"-template.json")) == template,
                    "LOOP_DISPATCH_TEMPLATE_MISMATCH")
        else:
            require(protocol.digest(delivered) == lease.get("delivered_input_digest", lease["payload_digest"]), "LOOP_DISPATCH_INPUT_MISMATCH")
        size = len(protocol.canonical(delivered).encode("utf-8"))
        with save_lock:
            require(context_bytes + size <= MAX_CONTEXT_BYTES, "LOOP_CONTEXT_BUDGET")
            context_bytes += size
            dispatches[lease["job_id"]] = {"declared_input_ref": lease["payload_ref"],
                "declared_input_digest": lease["payload_digest"],
                "delivered_input_digest": protocol.digest(delivered)}
        save(lease["job_id"] + "-input.json", delivered)
        guard()
        method = backend.review if critic else backend.produce
        try:
            value = method(copy.deepcopy(delivered), directory / (lease["job_id"] + "-attempt"),
                           actor_ref=actor, timeout=min(360, deadline-clock()), cancel_event=cancellation)
            guard()
            shape(value, {"result", "receipt"}, "LOOP_BACKEND_INVALID")
            receipt = value["receipt"]
            shape(receipt, {"actor_ref", "invocation_ref", "input_digest", "synthetic"}, "LOOP_RECEIPT_INVALID")
            require(receipt["actor_ref"] == actor and receipt["input_digest"] == protocol.digest(delivered)
                    and receipt["synthetic"] is True, "LOOP_INPUT_RECEIPT_MISMATCH")
            identity = protocol.ref(receipt["invocation_ref"], "invocation reference")
            with save_lock:
                require(identity not in invocations, "REVIEW_NOT_INDEPENDENT")
                invocations.add(identity)
            return value
        except Exception as exc:
            fail_preserving_error(lease, exc, "loop backend failed")
            raise

    def report(lease, value):
        guard()
        sha = save(lease["job_id"] + "-result.json", value)
        state.attach_identity(lease["token"], {"kind": "native", "thread_id": value["receipt"]["invocation_ref"]})
        state.report(lease["token"], "ref/loop/result/" + lease["job_id"], sha,
                     "candidate", "ref/loop/receipt/" + lease["job_id"])
        return sha

    prior_review, stop_reason, final_critic, critic_sha = None, "review_complete", None, None
    try:
        for round_index in range(2):
            current_jobs, leases = set(work_inputs), {}

            def work(job_id, lease=None):
                lease, delivered = lease or leases[job_id], work_inputs[job_id]
                value = invoke(lease, delivered, job_actors[job_id])
                try:
                    checked = validate_report_in_view(value["result"], delivered["view"], payload,
                                                      allowed_jobs=current_jobs)
                except Exception as exc:
                    fail_preserving_error(lease, exc, "loop report invalid")
                    raise
                sha = report(lease, value)
                return job_id, checked, sha

            def remember(result):
                job_id, checked, sha = result
                all_reports[job_id] = checked
                report_jobs[job_id] = {"artifact_digest": sha,
                    "selected_spans": next(j["selected_spans"] for j in specification["jobs"]
                        if job_id == f"r{round_index}-" + j["job_id"])}

            if dependency:
                order = [dependency_descriptor["a_job_id"], dependency_descriptor["b_job_id"]] if not round_index else sorted(work_inputs)
                for job_id in order:
                    if resume_progress and job_id == dependency_descriptor["a_job_id"]:
                        continue
                    guard()
                    if job_id != dependency_descriptor["a_job_id"]:
                        work_inputs[job_id] = dependent_input(
                            {k:v for k,v in work_inputs[job_id].items() if k != "prerequisite"},
                            dependency_stage, all_reports[dependency_descriptor["a_job_id"]])
                    with operation_lock(directory):
                        guard()
                        lease = state.claim(run_id, job_actors[job_id], lease_seconds=min(390, deadline-clock()))
                    require(lease is not None and lease["job_id"] == job_id, "RUN_PLAN_ASSIGNMENT")
                    remember(work(job_id, lease))
                    if job_id == dependency_descriptor["a_job_id"]:
                        dependency_stage = release_prerequisite(directory, payload, initial_specification, plan,
                            state, finalization_metadata(plan), artifacts, dispatches, lambda: context_bytes,
                            guard=guard, invoke=invoke, report=report, fail=fail_preserving_error,
                            save=save, actor=critic_actor, clock=clock,
                            cancel_event=cancellation)
                        if dependency_stage["status"] == "blocked":
                            return blocked_result(dependency_stage)
            else:
                for job_id in sorted(work_inputs):
                    guard()
                    lease = state.claim(run_id, job_actors[job_id], lease_seconds=min(390, deadline-clock()))
                    require(lease is not None and lease["job_id"] == job_id, "RUN_PLAN_ASSIGNMENT")
                    leases[job_id] = lease
                with ThreadPoolExecutor(max_workers=len(work_inputs)) as pool:
                    futures = [pool.submit(work, job_id) for job_id in sorted(work_inputs)]
                    for future in as_completed(futures):
                        try:
                            remember(future.result())
                        except Exception:
                            cancellation.set()
                            raise
            # Future completion order must not determine critic iteration,
            # later context order, or integration/learning artifact bytes.
            all_reports = dict(sorted(all_reports.items()))
            report_jobs = dict(sorted(report_jobs.items()))
            guard()
            critic_id = f"r{round_index}-critic"
            lease = state.claim(run_id, critic_actor, lease_seconds=min(390, deadline-clock()))
            require(lease is not None and lease["job_id"] == critic_id, "RUN_REVIEW_MISSING")
            delivered = {**critic_input, "template_digest": protocol.digest(critic_input), "reports": all_reports,
                         "report_digests": {job: protocol.digest(value) for job, value in all_reports.items()}}
            if dependency:
                delivered.update(release_certificate=dependency_stage["certificate"],
                                 release_certificate_sha256=dependency_stage["certificate_sha256"])
                from .dependency_contract import prerequisite_inputs
                delivered["prerequisite_inputs"] = prerequisite_inputs({
                    job: read_json(directory / (job + "-input.json")) for job in all_reports})
            reviewed = invoke(lease, delivered, critic_actor, critic=True)
            try:
                admission = state.extension(run_id)
                planned = [*plan["jobs"], *(admission["jobs"] if admission else [])]
                final_critic = validate_critic(reviewed["result"], payload, all_reports,
                    view=critic_input["view"], plan_digest=initial_digest, round_index=round_index,
                    initial_execution_plan_digest=protocol.digest(plan),
                    expected_jobs=tuple(job["job_id"] for job in planned if job["kind"] == "work"),
                    dispatched_input=read_json(directory/(critic_id+"-input.json")),
                    dispatched_input_digest=dispatches[critic_id]["delivered_input_digest"],
                    prior_review=prior_review, repair_admission=admission,
                    initial_specification=initial_specification, initial_runtime_plan=plan,
                    initial_template=read_json(directory/"r0-critic-template.json"),
                    work_inputs={job["job_id"]: read_json(directory/(job["job_id"]+"-input.json"))
                                 for job in planned if job["kind"] == "work"},
                    repair_specification=specification if round_index else None,
                    repair_impact=impact if round_index else None, execution_snapshot=state.snapshot(run_id),
                    dependency_stage=dependency_stage)
                if reuse_owner is not None:
                    reuse_owner.validate_review(final_critic, all_reports)
            except Exception as exc:
                fail_preserving_error(lease, exc, "loop critic invalid")
                raise
            critic_sha = report(lease, reviewed)
            verify_artifacts()
            prior_review = {"response": read_json(directory/(critic_id+"-result.json")),
                "dispatched_input": read_json(directory/(critic_id+"-input.json")),
                "dispatched_input_digest": dispatches[critic_id]["delivered_input_digest"]}
            gap = verified_gap(final_critic, critic_job_id=critic_id, critic_result_digest=critic_sha)
            if gap is None or round_index == 1:
                stop_reason = "review_complete" if all(v["status"] == "passed" for v in final_critic["validations"]) else "unresolved_review"
                break
            guard()
            try:
                proposal, _ = derive_repair(payload, initial_specification, gap)
            except protocol.SwarmError as exc:
                if not dependency or exc.code != "LOOP_DEPENDENCY_REPAIR_UNSUPPORTED":
                    raise
                stop_reason = "dependency_repair_unsupported"
                break
            if repair_planner is not None:
                supplied = validate_plan(repair_planner(copy.deepcopy(gap)), payload, gap=gap)
                guard()
                require(protocol.canonical(supplied) == protocol.canonical(proposal), "LOOP_REPAIR_PROPOSAL_MISMATCH")
            require(len(proposal["jobs"]) <= len(actors), "LOOP_ACTORS_INVALID")
            snapshot = state.snapshot(run_id)
            if snapshot["budget"]["remaining_attempts"] < len(proposal["jobs"]) + 1:
                stop_reason = "attempt_budget_exhausted"
                break
            proposal, impact = make_impact(payload, initial_specification, plan, prior_review,
                {job["job_id"]: read_json(directory/(job["job_id"]+"-input.json"))
                 for job in plan["jobs"] if job["kind"] == "work"}, snapshot)
            save("repair-proposal.json", proposal)
            impact_sha = save("repair-impact.json", impact)
            work_inputs, critic_input, jobs, job_actors = frontier(proposal, 1, critic_sha)
            verify_artifacts()
            extension = {"round": 1, "initial_plan_digest": protocol.digest(plan),
                         "critic_job_id": critic_id, "critic_result_digest": critic_sha,
                         "proposal_digest": protocol.digest(proposal), "jobs": jobs}
            guard()
            extension = state.extend_run(run_id, extension)
            save("extension.json", extension)
            specification = proposal
        require(final_critic is not None and critic_sha is not None, "LOOP_REVIEW_REQUIRED")
        with operation_lock(directory):
            guard()
            verify_artifacts()
            metadata = finalization_metadata(plan)
            make_checkpoint(directory, payload, state, metadata, artifact_sha256=artifacts,
                dispatches=dispatches, rounds=final_critic["round"] + 1, stop_reason=stop_reason,
                context_bytes=context_bytes, observed_elapsed_seconds=time.monotonic() - started)
            return finalize(directory, payload, state, metadata, guard=guard, reuse_owner=reuse_owner, cancel_event=cancellation)
    except Exception as exc:
        with failure_lock:
            failure = failures[0] if failures else None
        if failure is not None:
            if isinstance(exc, protocol.SwarmError):
                cancelled = exc.code == "RUN_CANCELLED"
            else:
                from .codex import BackendError
                cancelled = isinstance(exc, BackendError) and exc.code == "cancelled"
            if cancelled:
                # A later durable cancellation still wins over this monitor's
                # earlier refusal. Failed readback cannot authorize translation.
                try:
                    cause_applies = state.cancellation(run_id) is None
                except Exception:
                    cause_applies = False
                if cause_applies:
                    raise protocol.SwarmError(*failure) from exc
        raise
    finally:
        done.set()
        watcher.join(timeout=1)


class ScriptedSimulation:
    """Explicit, bounded scenario data for CLI acceptance runs; no model calls."""
    synthetic = True

    def __init__(self, scenario):
        shape(scenario, {"work", "critics", "repair_plan"}, "LOOP_SCENARIO_INVALID")
        require(isinstance(scenario["work"], dict) and isinstance(scenario["critics"], dict),
                "LOOP_SCENARIO_INVALID")
        self.scenario = copy.deepcopy(scenario)

    @staticmethod
    def _response(delivered, result, actor_ref):
        require(result is not None, "LOOP_SCENARIO_RESPONSE_MISSING")
        return {"result": copy.deepcopy(result), "receipt": {"actor_ref": actor_ref,
                "invocation_ref": "simulation-" + delivered.get("job_id", delivered.get("core", {}).get("job_id", "invalid")),
                "input_digest": protocol.digest(delivered), "synthetic": True}}

    def produce(self, delivered, directory, *, actor_ref, **_kwargs):
        return self._response(delivered, self.scenario["work"].get(delivered["job_id"]), actor_ref)

    def review(self, delivered, directory, *, actor_ref, **_kwargs):
        key = "prerequisite" if "core" in delivered else str(delivered["round"])
        return self._response(delivered, self.scenario["critics"].get(key), actor_ref)


def main(argv=None):
    """Run a supplied local scenario through the production coordinator path."""
    import argparse
    import sys
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--simulation", type=Path,
                        help="Explicit JSON work/critic responses and optional repair plan; never calls a provider")
    parser.add_argument("--worker", required=True, action="append", help="Existing owner actor; repeat for parallel jobs")
    parser.add_argument("--critic", default="verifier")
    parser.add_argument("--receipt-sha256", help="Read back an already completed run using this external anchor")
    parser.add_argument("--resume-finalization", action="store_true",
                        help="Finish a terminal checkpoint, or continue released A->B with --simulation; never retry an unknown attempt")
    args = parser.parse_args(argv)
    try:
        if args.resume_finalization and args.simulation is None:
            class NoDispatch:
                synthetic = True

                def produce(self, *_args, **_kwargs):
                    raise protocol.SwarmError("FINALIZATION_DISPATCH_FORBIDDEN", "recovery cannot dispatch")

                review = produce

            backend, repair = NoDispatch(), None
        else:
            require(args.simulation is not None, "LOOP_SIMULATION_REQUIRED")
            scenario = read_json(args.simulation, 1024 * 1024)
            backend = ScriptedSimulation(scenario)
            repair = scenario["repair_plan"]
        result = execute_closed_loop(args.owner, args.input, read_json(args.plan, 256 * 1024), backend,
            worker_actors=args.worker, critic_actor=args.critic,
            repair_planner=(lambda _gap: copy.deepcopy(repair)) if repair is not None else None,
            expected_receipt_sha256=args.receipt_sha256, resume_finalization=args.resume_finalization)
        print(protocol.canonical(result))
        return 3 if result.get("status") == "blocked" else 0
    except protocol.SwarmError as exc:
        print(protocol.canonical({"error": exc.code, "message": exc.detail}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
