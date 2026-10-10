"""Bounded closed-loop coordinator over the existing owner and SwarmState.

The injectable backend is currently restricted to explicit local simulations.
The same claim/report/verify/accept path handles every frontier and its critic;
no provider, generated planner, Task authority or knowledge adoption is added.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import hashlib
from pathlib import Path
import threading
import time

from . import protocol
from .closed_loop_contract import (integration_candidate, learning_candidate, loop_criteria,
                                   validate_critic, validate_plan, verified_gap)
from .closed_loop_context import derive_child_view, validate_report_in_view
from .owner_file import OwnerFile
from .state import SwarmState
from .task_contract import require, shape, validate_input
from .task_runner import read_json, safe_directory, write_json


MAX_CONTEXT_BYTES = 512 * 1024
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024


def execute_closed_loop(owner_path, payload_path, supplied_plan, backend, *,
                        worker_actors, critic_actor="verifier", repair_planner=None,
                        cancel_event=None, clock=time.time, expected_receipt_sha256=None):
    """Execute a supplied finite DAG and one verified-gap repair in one run.

    ``repair_planner(gap)`` is a pure local data transform, called outside any
    database lock. Provider-backed planning is not supported by this entrypoint.
    A completed run supports anchored readback; an interrupted run requires
    recovery rather than silently re-dispatching work or renewing the budget.
    """
    started = time.monotonic()
    require(getattr(backend, "synthetic", False) is True, "LOOP_SIMULATION_REQUIRED")
    owner_path, payload_path = Path(owner_path), Path(payload_path)
    owner = OwnerFile(owner_path, clock=clock)
    _, owner_sha = read_json(owner_path, 1024 * 1024, with_digest=True)
    payload = read_json(payload_path, 256 * 1024)
    binding = owner.read_task(payload.get("task_id"))
    replay_only = expected_receipt_sha256 is not None
    payload = validate_input(payload, binding, now=clock(), allow_expired_objective=replay_only)
    require(payload["version"] == 2, "LOOP_OBJECTIVE_REQUIRED")
    specification = validate_plan(supplied_plan, payload)
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

    def guard():
        require(not cancellation.is_set(), "RUN_CANCELLED")
        require(protocol.digest(owner.read_task(binding["task_id"])) == binding_digest, "STALE_BINDING")
        require(all(owner.read_binding(binding["task_id"], actor) == original
                    for actor, original in actor_bindings.items()), "STALE_ACTOR")
        require(replay_only or clock() < deadline, "DEADLINE_EXPIRED")
        require(owner.storage()["root"] == root and safe_directory(root) == root, "RUN_STORAGE_CHANGED")
        require(read_json(owner_path, 1024 * 1024, with_digest=True)[1] == owner_sha, "OWNER_INPUT_CHANGED")

    # The Task/revision fixes the run identity, not the supplied plan or attempt.
    # Changing the plan cannot sidestep this directory and refill its budget.
    run_id = "task-run-" + protocol.digest([payload["task_id"], payload["revision"]])[:32]
    directory = root / run_id
    guard()
    if directory.exists():
        safe_directory(directory)
        require((directory / "receipt.json").is_file(), "RUN_RECOVERY_REQUIRED")
        require(isinstance(expected_receipt_sha256, str) and len(expected_receipt_sha256) == 64,
                "RUN_REPLAY_ANCHOR_REQUIRED")
        protocol.digest_ref(expected_receipt_sha256, "receipt anchor")
        receipt, sha = read_json(directory / "receipt.json", with_digest=True)
        require(sha == expected_receipt_sha256, "RUN_REPLAY_ANCHOR_MISMATCH")
        require(receipt.get("coordinator") == "closed_loop_v1", "RUN_REPLAY_CONFLICT")
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
            value, actual = read_json(directory / name, with_digest=True)
            require(actual == expected_sha, "RUN_ARTIFACT_CHANGED")
            checked[name] = value
        require(checked["input.json"] == payload and checked["specification.json"] == specification,
                "RUN_REPLAY_CONFLICT")
        state = SwarmState(directory / "execution.sqlite", owner.read_task, clock=clock)
        snapshot = state.snapshot(run_id)
        require(protocol.canonical(snapshot) == protocol.canonical(checked["execution.json"]),
                "RUN_EXECUTION_CHANGED")
        guard()
        return {"candidate": checked["candidate.json"], "learning_candidate": checked.get("learning.json"),
                "receipt": receipt, "receipt_sha256": sha, "duplicate": True}
    require(expected_receipt_sha256 is None, "RUN_REPLAY_MISSING")
    directory.mkdir(mode=0o700)
    artifacts, artifact_bytes, context_bytes = {}, 0, 0
    save_lock = threading.Lock()

    def save(name, value):
        nonlocal artifact_bytes
        size = len((protocol.canonical(value) + "\n").encode("utf-8"))
        with save_lock:
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
            require(read_json(directory / name, with_digest=True)[1] == sha, "RUN_ARTIFACT_CHANGED")

    save("input.json", payload)
    save("specification.json", specification)
    all_reports, report_jobs, invocations, dispatches = {}, {}, set(), {}
    criteria = loop_criteria(payload)

    def frontier(spec, index, previous=None):
        round_digest = protocol.digest(spec)
        work_inputs, runtime_jobs, job_actors = {}, [], {}
        selected = []
        for number, job in enumerate(sorted(spec["jobs"], key=lambda j: j["job_id"])):
            job_id = f"r{index}-" + job["job_id"]
            view = derive_child_view(payload, job_id, job["selected_spans"],
                                     plan_digest=initial_digest, previous_critic_digest=previous)
            delivered = {"role": "work", "job_id": job_id, "round": index,
                         "round_plan_digest": round_digest, "purpose": job["purpose"],
                         "criterion_ids": job["criterion_ids"],
                         "criteria": {k: criteria[k] for k in job["criterion_ids"]}, "view": view}
            work_inputs[job_id], job_actors[job_id] = delivered, actors[number]
            runtime_jobs.append({"job_id": job_id, "kind": "work", "dependencies": [], "exclusive_keys": [],
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
        save(critic_id + "-template.json", critic_input)
        runtime_jobs.append({"job_id": critic_id, "kind": "review",
                             "dependencies": sorted([*all_reports, *work_inputs]), "exclusive_keys": [],
                             "payload_ref": "ref/loop/template/" + critic_id,
                             "payload_digest": protocol.digest(critic_input)})
        return work_inputs, critic_input, runtime_jobs, job_actors

    work_inputs, critic_input, jobs, job_actors = frontier(specification, 0)
    plan = {"run_id": run_id, "task_id": payload["task_id"], "binding_digest": binding_digest,
            "budget": {**payload["objective"]["budget"], "concurrency": len(actors), "verifier_reserve": 1},
            "jobs": jobs}
    require(len(jobs) <= plan["budget"]["attempt_budget"], "LOOP_ATTEMPT_BUDGET")
    state = SwarmState(directory / "execution.sqlite", owner.read_task, clock=clock)
    plan = state.create_run(plan)
    save("plan.json", plan)
    done = threading.Event()

    def monitor():
        while not done.wait(.1):
            try:
                guard()
            except Exception:
                cancellation.set()
                return

    watcher = threading.Thread(target=monitor, name="loop-owner-watch", daemon=True)
    watcher.start()

    def invoke(lease, delivered, actor, *, critic=False):
        nonlocal context_bytes
        guard()
        if critic:
            template = {key: value for key, value in delivered.items()
                        if key not in {"template_digest", "reports", "report_digests"}}
            require(protocol.digest(template) == delivered["template_digest"] == lease["payload_digest"]
                    and read_json(directory/(lease["job_id"]+"-template.json")) == template,
                    "LOOP_DISPATCH_TEMPLATE_MISMATCH")
        else:
            require(protocol.digest(delivered) == lease["payload_digest"], "LOOP_DISPATCH_INPUT_MISMATCH")
        size = len(protocol.canonical(delivered).encode("utf-8"))
        with save_lock:
            require(context_bytes + size <= MAX_CONTEXT_BYTES, "LOOP_CONTEXT_BUDGET")
            context_bytes += size
            dispatches[lease["job_id"]] = {"declared_input_ref": lease["payload_ref"],
                "declared_input_digest": lease["payload_digest"],
                "delivered_input_digest": protocol.digest(delivered)}
        save(lease["job_id"] + "-input.json", delivered)
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
            state.fail(lease["token"], getattr(exc, "code", "loop backend failed"), retryable=False)
            raise

    def report(lease, value):
        guard()
        sha = save(lease["job_id"] + "-result.json", value)
        state.attach_identity(lease["token"], {"kind": "native", "thread_id": value["receipt"]["invocation_ref"]})
        state.report(lease["token"], "ref/loop/result/" + lease["job_id"], sha,
                     "candidate", "ref/loop/receipt/" + lease["job_id"])
        return sha

    def verify_dispatches(snapshot):
        require(set(dispatches) == set(snapshot["jobs"]), "LOOP_DISPATCH_COVERAGE")
        for job, scheduled in snapshot["jobs"].items():
            actual = read_json(directory/(job+"-input.json"))
            response = read_json(directory/(job+"-result.json"))
            observed = dispatches[job]
            require(observed == {"declared_input_ref": scheduled["payload_ref"],
                    "declared_input_digest": scheduled["payload_digest"],
                    "delivered_input_digest": protocol.digest(actual)}, "LOOP_DISPATCH_INPUT_MISMATCH")
            require(response["receipt"]["input_digest"] == observed["delivered_input_digest"],
                    "LOOP_INPUT_RECEIPT_MISMATCH")
            if scheduled["kind"] == "review":
                template = read_json(directory/(job+"-template.json"))
                require(protocol.digest(template) == observed["declared_input_digest"] == actual["template_digest"]
                        and {k: v for k, v in actual.items() if k not in {"template_digest", "reports", "report_digests"}} == template,
                        "LOOP_DISPATCH_TEMPLATE_MISMATCH")
            else:
                require(observed["declared_input_digest"] == observed["delivered_input_digest"],
                        "LOOP_DISPATCH_INPUT_MISMATCH")

    prior_review, stop_reason, final_critic, critic_sha = None, "review_complete", None, None
    try:
        for round_index in range(2):
            current_jobs, leases = set(work_inputs), {}
            for job_id in sorted(work_inputs):
                guard()
                lease = state.claim(run_id, job_actors[job_id], lease_seconds=min(390, deadline-clock()))
                require(lease is not None and lease["job_id"] == job_id, "RUN_PLAN_ASSIGNMENT")
                leases[job_id] = lease

            def work(job_id):
                lease, delivered = leases[job_id], work_inputs[job_id]
                value = invoke(lease, delivered, job_actors[job_id])
                try:
                    checked = validate_report_in_view(value["result"], delivered["view"], payload,
                                                      allowed_jobs=current_jobs)
                except Exception as exc:
                    state.fail(lease["token"], getattr(exc, "code", "loop report invalid"), retryable=False)
                    raise
                sha = report(lease, value)
                return job_id, checked, sha

            with ThreadPoolExecutor(max_workers=len(work_inputs)) as pool:
                futures = [pool.submit(work, job_id) for job_id in sorted(work_inputs)]
                for future in as_completed(futures):
                    try:
                        job_id, checked, sha = future.result()
                        all_reports[job_id] = checked
                        report_jobs[job_id] = {"artifact_digest": sha,
                            "selected_spans": next(j["selected_spans"] for j in specification["jobs"]
                                if job_id == f"r{round_index}-" + j["job_id"])}
                    except Exception:
                        cancellation.set()
                        raise
            guard()
            critic_id = f"r{round_index}-critic"
            lease = state.claim(run_id, critic_actor, lease_seconds=min(390, deadline-clock()))
            require(lease is not None and lease["job_id"] == critic_id, "RUN_REVIEW_MISSING")
            delivered = {**critic_input, "template_digest": protocol.digest(critic_input), "reports": all_reports,
                         "report_digests": {job: protocol.digest(value) for job, value in all_reports.items()}}
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
                    prior_review=prior_review, repair_admission=admission)
            except Exception as exc:
                state.fail(lease["token"], getattr(exc, "code", "loop critic invalid"), retryable=False)
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
            if repair_planner is None:
                stop_reason = "repair_plan_required"
                break
            guard()
            # Pure supplied planning runs without a SQLite write lock. Recheck
            # owner, deadline, evidence and budget before admitting its result.
            proposal = validate_plan(repair_planner(copy.deepcopy(gap)), payload, gap=gap)
            guard()
            signatures = lambda p: {protocol.canonical({k: v for k, v in j.items() if k != "job_id"}) for j in p["jobs"]}
            if signatures(proposal).issubset(signatures(specification)):
                stop_reason = "unchanged_repair_plan"
                break
            require(len(proposal["jobs"]) <= len(actors), "LOOP_ACTORS_INVALID")
            save("repair-proposal.json", proposal)
            snapshot = state.snapshot(run_id)
            if snapshot["budget"]["remaining_attempts"] < len(proposal["jobs"]) + 1:
                stop_reason = "attempt_budget_exhausted"
                break
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
        candidate = integration_candidate(payload, all_reports, final_critic, critic_sha, stop_reason=stop_reason)
        save("candidate.json", candidate)
        learning = None
        passed = candidate["status"] == "needs_owner_review"
        if passed:
            learning = learning_candidate(candidate)
            save("learning.json", learning)
            cited_jobs = {ref["job_id"] for item in final_critic["validations"] for ref in item["evidence"]}
            for job in sorted(cited_jobs):
                guard()
                verify_artifacts()
                state.accept(run_id, job, report_jobs[job]["artifact_digest"],
                             "ref/loop/verification/" + critic_sha, binding["owner_ref"])
            guard()
            state.accept(run_id, f"r{final_critic['round']}-critic", critic_sha,
                         "ref/loop/verification/" + critic_sha, binding["owner_ref"])
        snapshot = state.snapshot(run_id)
        verify_dispatches(snapshot)
        save("execution.json", snapshot)
        receipt = {"version": 1, "coordinator": "closed_loop_v1", "run_id": run_id, "binding_digest": binding_digest,
                   "owner_input_sha256": owner_sha, "parent_input_digest": parent_digest,
                   "initial_plan_digest": initial_digest, "worker_actors": actors, "critic_actor": critic_actor,
                   "synthetic": True, "model_runtime_verified": False, "task_state_changed": False,
                   "review_passed": passed, "rounds": final_critic["round"] + 1,
                   "budget": snapshot["budget"], "context_bytes": context_bytes,
                   "artifact_bytes": artifact_bytes, "elapsed_seconds": time.monotonic() - started,
                   "dispatches": dispatches, "artifact_sha256": dict(artifacts)}
        guard()
        verify_artifacts()
        receipt_sha = write_json(directory / "receipt.json", receipt)
        guard()
        return {"candidate": candidate, "learning_candidate": learning, "receipt": receipt,
                "receipt_sha256": receipt_sha, "duplicate": False}
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
                "invocation_ref": "simulation-" + delivered["job_id"],
                "input_digest": protocol.digest(delivered), "synthetic": True}}

    def produce(self, delivered, directory, *, actor_ref, **_kwargs):
        return self._response(delivered, self.scenario["work"].get(delivered["job_id"]), actor_ref)

    def review(self, delivered, directory, *, actor_ref, **_kwargs):
        return self._response(delivered, self.scenario["critics"].get(str(delivered["round"])), actor_ref)


def main(argv=None):
    """Run a supplied local scenario through the production coordinator path."""
    import argparse
    import sys
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--simulation", required=True, type=Path,
                        help="Explicit JSON work/critic responses and optional repair plan; never calls a provider")
    parser.add_argument("--worker", required=True, action="append", help="Existing owner actor; repeat for parallel jobs")
    parser.add_argument("--critic", default="verifier")
    parser.add_argument("--receipt-sha256", help="Read back an already completed run using this external anchor")
    args = parser.parse_args(argv)
    try:
        scenario = read_json(args.simulation, 1024 * 1024)
        backend = ScriptedSimulation(scenario)
        repair = scenario["repair_plan"]
        result = execute_closed_loop(args.owner, args.input, read_json(args.plan, 256 * 1024), backend,
            worker_actors=args.worker, critic_actor=args.critic,
            repair_planner=(lambda _gap: copy.deepcopy(repair)) if repair is not None else None,
            expected_receipt_sha256=args.receipt_sha256)
        print(protocol.canonical(result))
        return 0
    except protocol.SwarmError as exc:
        print(protocol.canonical({"error": exc.code, "message": exc.detail}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
