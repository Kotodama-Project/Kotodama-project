"""Terminal-only recovery for a verified, owner-bound closed-loop run.

This module never invokes a backend, admits work, renews a lease or changes a
Task. The checkpoint and progress remain in the existing execution database.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path

from . import protocol
from .closed_loop_contract import integration_candidate, learning_candidate, validate_critic, validate_plan, verified_gap, evidence_version
from .closed_loop_context import validate_report_in_view
from .task_contract import require
from .task_runner import read_json, safe_directory, write_json


MAX_ARTIFACT_BYTES = 2 * 1024 * 1024


@contextmanager
def operation_lock(directory):
    """Crash-released local OS lock, using the existing Company Pack pattern."""
    directory = safe_directory(directory)
    path = directory / "finalization.lock"
    require(not path.is_symlink(), "RUN_STORAGE_CHANGED")
    with path.open("a+b") as stream:
        if path.stat().st_size == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise protocol.SwarmError("FINALIZATION_BUSY", "another finalizer holds the run") from exc
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise protocol.SwarmError("FINALIZATION_BUSY", "another finalizer holds the run") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def checked_artifacts(directory, artifacts):
    """Read only a bounded explicit manifest, never scan unrelated history."""
    require(isinstance(artifacts, dict) and 3 <= len(artifacts) <= 32, "FINALIZATION_ARTIFACT_INVALID")
    values, total = {}, 0
    safe_directory(directory)
    for name, expected in artifacts.items():
        require(isinstance(name, str) and Path(name).name == name and name.endswith(".json"),
                "FINALIZATION_ARTIFACT_INVALID")
        protocol.digest_ref(expected, "artifact digest")
        value, actual = read_json(directory / name, with_digest=True)
        require(actual == expected, "RUN_ARTIFACT_CHANGED")
        values[name] = value
        total += (directory / name).stat().st_size
        require(total <= MAX_ARTIFACT_BYTES, "LOOP_ARTIFACT_BUDGET")
    return values, total


def terminal_evidence(directory, payload, record, state):
    """Revalidate actual delivered inputs, every report and each critic."""
    values, total = checked_artifacts(directory, record["artifact_sha256"])
    require({"input.json", "specification.json", "plan.json"} <= values.keys(), "FINALIZATION_ARTIFACT_INVALID")
    require(protocol.canonical(values["input.json"]) == protocol.canonical(payload), "RUN_REPLAY_CONFLICT")
    require(protocol.digest(values.get("context-binding.json")) == record["context_binding_digest"],
            "RUN_CONTEXT_REPLAY_CONFLICT")
    specification = validate_plan(values["specification.json"], payload)
    require(protocol.digest(specification) == record["initial_plan_digest"], "RUN_REPLAY_CONFLICT")
    plan = values["plan.json"]
    require(protocol.digest(plan) == record["initial_execution_plan_digest"], "RUN_REPLAY_CONFLICT")
    admission = values.get("extension.json")
    scheduled = {job["job_id"]: job for job in [*plan["jobs"], *(admission["jobs"] if admission else [])]}
    snapshot = state.snapshot(record["run_id"])
    require(protocol.canonical(snapshot["plan"]) == protocol.canonical(plan)
            and protocol.canonical(snapshot.get("extension")) == protocol.canonical(admission)
            and set(snapshot["jobs"]) == set(scheduled), "FINALIZATION_PLAN_CONFLICT")
    version = evidence_version(plan, values["r0-critic-template.json"])
    require(type(record.get("version")) is int and record["version"] == version, "LOOP_EVIDENCE_POLICY")
    for job, expected in scheduled.items():
        current = snapshot["jobs"][job]
        require(all(protocol.canonical(current[key]) == protocol.canonical(value) for key, value in expected.items())
                and current["state"] in {"reported", "accepted"} and current["attempt_count"] == 1,
                "FINALIZATION_UNSETTLED")
        attempt = current["current_attempt"]
        proof = values[job + "-result.json"]["receipt"]
        require(attempt["state"] == current["state"] and attempt["outcome"] == "candidate"
                and attempt["result_digest"] == record["artifact_sha256"][job + "-result.json"]
                and attempt["result_ref"] == "ref/loop/result/" + job
                and attempt["runtime_receipt_ref"] == "ref/loop/receipt/" + job
                and attempt["worker_ref"] == proof["actor_ref"]
                and attempt["identity"] == {"kind": "native", "thread_id": proof["invocation_ref"]},
                "FINALIZATION_STATE_CHANGED")
    rounds = 2 if admission else 1
    require(set(record["dispatches"]) == set(scheduled), "LOOP_DISPATCH_COVERAGE")
    require(record["rounds"] == rounds, "FINALIZATION_ROUND_CONFLICT")
    reports, invocations, report_sha, prior = {}, set(), {}, None
    context_bytes = 0
    for index in range(rounds):
        work = sorted(job for job, item in scheduled.items()
                      if job.startswith(f"r{index}-") and item["kind"] == "work")
        require(1 <= len(work) <= len(record["worker_actors"]), "FINALIZATION_PLAN_CONFLICT")
        if index:
            proposal = validate_plan(values["repair-proposal.json"], payload,
                                     gap=verified_gap(
                                         critic, critic_job_id="r0-critic", critic_result_digest=critic_sha))
            require(protocol.digest(proposal) == admission["proposal_digest"], "FINALIZATION_PLAN_CONFLICT")
        for number, job in enumerate([*work, f"r{index}-critic"]):
            require(job in scheduled, "FINALIZATION_PLAN_CONFLICT")
            delivered, response = values[job + "-input.json"], values[job + "-result.json"]
            proof = response["receipt"]
            actor = record["critic_actor"] if scheduled[job]["kind"] == "review" else record["worker_actors"][number]
            require(proof["actor_ref"] == actor and proof["input_digest"] == protocol.digest(delivered)
                    and proof["synthetic"] is True and proof["invocation_ref"] not in invocations,
                    "LOOP_INPUT_RECEIPT_MISMATCH")
            invocations.add(proof["invocation_ref"])
            observed = record["dispatches"][job]
            require(observed == {"declared_input_ref": scheduled[job]["payload_ref"],
                    "declared_input_digest": scheduled[job]["payload_digest"],
                    "delivered_input_digest": protocol.digest(delivered)}, "LOOP_DISPATCH_INPUT_MISMATCH")
            context_bytes += len(protocol.canonical(delivered).encode("utf-8"))
            if scheduled[job]["kind"] == "work":
                require(observed["declared_input_digest"] == observed["delivered_input_digest"],
                        "LOOP_DISPATCH_INPUT_MISMATCH")
                reports[job] = validate_report_in_view(response["result"], delivered["view"], payload, allowed_jobs=work)
                report_sha[job] = record["artifact_sha256"][job + "-result.json"]
                continue
            template = values[job + "-template.json"]
            require(protocol.digest(template) == observed["declared_input_digest"] == delivered["template_digest"]
                    and protocol.canonical({k: v for k, v in delivered.items()
                        if k not in {"template_digest", "reports", "report_digests"}}) == protocol.canonical(template),
                    "LOOP_DISPATCH_TEMPLATE_MISMATCH")
            require(protocol.canonical(delivered["reports"]) == protocol.canonical(reports), "LOOP_REPORT_SET_MISMATCH")
            critic = validate_critic(response["result"], payload, reports, view=delivered["view"],
                plan_digest=record["initial_plan_digest"], round_index=index,
                initial_execution_plan_digest=protocol.digest(plan),
                expected_jobs=tuple(j for j, item in scheduled.items()
                    if item["kind"] == "work" and (index or j.startswith("r0-"))),
                dispatched_input=delivered, dispatched_input_digest=observed["delivered_input_digest"],
                prior_review=prior, repair_admission=admission if index else None,
                initial_specification=specification, initial_runtime_plan=plan,
                initial_template=values["r0-critic-template.json"],
                work_inputs={j: values[j+"-input.json"] for j, item in scheduled.items() if item["kind"] == "work"},
                repair_specification=proposal if index else None)
            critic_sha = record["artifact_sha256"][job + "-result.json"]
            prior = {"response": response, "dispatched_input": delivered,
                     "dispatched_input_digest": observed["delivered_input_digest"]}
    require(context_bytes == record["context_bytes"] and context_bytes <= 512 * 1024, "LOOP_CONTEXT_BUDGET")
    candidate = integration_candidate(payload, reports, critic, critic_sha, stop_reason=record["stop_reason"])
    learning = learning_candidate(candidate) if candidate["status"] == "needs_owner_review" else None
    accepts = {ref["job_id"]: report_sha[ref["job_id"]]
               for item in critic["validations"] for ref in item["evidence"]} if learning else {}
    if learning:
        accepts[f"r{rounds-1}-critic"] = critic_sha
    return candidate, learning, accepts, critic_sha, total


def make_checkpoint(directory, payload, state, metadata, *, artifact_sha256, dispatches,
                    rounds, stop_reason, context_bytes, observed_elapsed_seconds):
    version = evidence_version(read_json(directory/"plan.json"), read_json(directory/"r0-critic-template.json"))
    record = {"version": version, **metadata, "artifact_sha256": dict(artifact_sha256),
              "dispatches": dict(dispatches), "rounds": rounds, "stop_reason": stop_reason,
              "context_bytes": context_bytes, "observed_elapsed_seconds": observed_elapsed_seconds}
    candidate, learning, accepts, critic_sha, _ = terminal_evidence(directory, payload, record, state)
    record.update(candidate_digest=protocol.digest(candidate), learning_digest=protocol.digest(learning),
                  accepts=accepts, verification_ref="ref/loop/verification/" + critic_sha,
                  state_digest=state.finalization_evidence_digest(record["run_id"]))
    return state.prepare_finalization(record["run_id"], record)


def finalize(directory, payload, state, metadata, *, guard, reuse_owner=None, cancel_event=None):
    """Finish exactly the checkpointed accepts/outputs. Caller holds OS lock."""
    guard()
    stored = state.finalization(metadata["run_id"])
    require(stored is not None, "RUN_RECOVERY_REQUIRED")
    record, checkpoint_digest = stored["checkpoint"], stored["checkpoint_digest"]
    require(all(protocol.canonical(record[key]) == protocol.canonical(value) for key, value in metadata.items()),
            "FINALIZATION_CONFLICT")
    candidate, learning, accepts, critic_sha, artifact_bytes = terminal_evidence(directory, payload, record, state)
    require(protocol.digest(candidate) == record["candidate_digest"]
            and protocol.digest(learning) == record["learning_digest"]
            and accepts == record["accepts"] and record["verification_ref"] == "ref/loop/verification/" + critic_sha,
            "FINALIZATION_CONFLICT")
    if reuse_owner is not None:
        reuse_owner.validate_candidate(candidate)
    outputs = {"candidate.json": candidate}
    if learning is not None:
        outputs["learning.json"] = learning
    else:
        require(not (directory / "learning.json").exists(), "FINALIZATION_OUTPUT_CONFLICT")
    require(not (directory / "receipt.json").exists(), "RUN_REPLAY_ANCHOR_REQUIRED")
    if (directory / "execution.json").exists():
        current = state.snapshot(record["run_id"])
        require({job for job, value in current["jobs"].items() if value["state"] == "accepted"} == set(accepts)
                and protocol.canonical(read_json(directory / "execution.json")) == protocol.canonical(current),
                "FINALIZATION_OUTPUT_CONFLICT")
    # Refuse malformed/conflicting existing outputs before committing an accept.
    for name, expected in outputs.items():
        if (directory / name).exists():
            require(read_json(directory / name, with_digest=True)[1]
                    == hashlib.sha256((protocol.canonical(expected) + "\n").encode("utf-8")).hexdigest(),
                    "FINALIZATION_OUTPUT_CONFLICT")
    for job, result_sha in sorted(accepts.items()):
        guard()
        checked_artifacts(directory, record["artifact_sha256"])
        state.accept(record["run_id"], job, result_sha, record["verification_ref"], record["owner_ref"],
                     cancel_event=cancel_event)
    guard()
    state.finalization(record["run_id"])
    snapshot = state.snapshot(record["run_id"])
    outputs["execution.json"] = snapshot
    artifacts = dict(record["artifact_sha256"])
    for name, value in outputs.items():
        raw = (protocol.canonical(value) + "\n").encode("utf-8")
        artifacts[name] = hashlib.sha256(raw).hexdigest()
        artifact_bytes += len(raw)
    require(artifact_bytes <= MAX_ARTIFACT_BYTES, "LOOP_ARTIFACT_BUDGET")
    receipt = {"version": record["version"], "coordinator": f"closed_loop_v{record['version']}", **{key: record[key] for key in (
        "run_id", "binding_digest", "owner_input_sha256", "parent_input_digest", "initial_plan_digest",
        "worker_actors", "critic_actor")}, "synthetic": True, "model_runtime_verified": False,
        "task_state_changed": False, "review_passed": learning is not None, "rounds": record["rounds"],
        "budget": snapshot["budget"], "context_bytes": record["context_bytes"], "artifact_bytes": artifact_bytes,
        "elapsed_seconds": record["observed_elapsed_seconds"],
        "timing": {"scope": "observed_before_finalization_checkpoint", "after_checkpoint_seconds": None},
        "finalization_checkpoint_digest": checkpoint_digest, "dispatches": record["dispatches"],
        "artifact_sha256": artifacts}
    if stored["receipt"] is not None:
        require(protocol.canonical(receipt) == protocol.canonical(stored["receipt"]), "FINALIZATION_CONFLICT")
        receipt = stored["receipt"]
    # Validate the complete expected set before writing any missing output.
    for name, value in outputs.items():
        if (directory / name).exists():
            require(read_json(directory / name, with_digest=True)[1] == artifacts[name], "FINALIZATION_OUTPUT_CONFLICT")
    guard()
    state.pin_final_receipt(record["run_id"], checkpoint_digest, receipt)
    for name, value in outputs.items():
        guard()
        checked_artifacts(directory, record["artifact_sha256"])
        state.finalization(record["run_id"])
        if not (directory / name).exists():
            write_json(directory / name, value)
        require(read_json(directory / name, with_digest=True)[1] == artifacts[name], "FINALIZATION_OUTPUT_CONFLICT")
    guard()
    checked_artifacts(directory, artifacts)
    state.finalization(record["run_id"])
    # A staged receipt is not a completed run. A prior fully written stage
    # may be reused only when it exactly matches the pinned receipt; malformed
    # or changed staging is refused, never repaired from untrusted bytes.
    pending = directory / ".receipt-pending.json"
    created = not pending.exists()
    try:
        if created:
            receipt_sha = write_json(pending, receipt)
        else:
            saved, receipt_sha = read_json(pending, with_digest=True)
            require(saved == receipt, "FINALIZATION_OUTPUT_CONFLICT")
        guard()
        checked_artifacts(directory, artifacts)
        state.finalization(record["run_id"])
        expected_sha = hashlib.sha256((protocol.canonical(receipt) + "\n").encode("utf-8")).hexdigest()
        require(read_json(pending, with_digest=True) == (receipt, expected_sha)
                and receipt_sha == expected_sha, "RUN_OUTPUT_READBACK")
        guard()
        # This publication cutoff has no post-rename guard: return the exact
        # anchor even if a stop arrives after the final eligibility observation.
        os.replace(pending, directory / "receipt.json")
    except Exception:
        if created:
            try:
                pending.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    return {"candidate": candidate, "learning_candidate": learning, "receipt": receipt,
            "receipt_sha256": receipt_sha, "duplicate": False}
