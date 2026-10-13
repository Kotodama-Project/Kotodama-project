"""Explicit owner cancellation of an existing local closed-loop run.

The public acknowledgment is serialized with final receipt publication. It
records a prohibition on further work, not a worker stop or an execution ACK.
"""
from __future__ import annotations

import os
from pathlib import Path
import time

from . import protocol
from .closed_loop_contract import validate_plan, work_input
from .owner_file import OwnerFile
from .state import SwarmState
from .task_contract import require, validate_input
from .task_runner import read_json, safe_directory


def cancel_closed_loop(owner_path, payload_path, *, clock=time.time):
    """Durably cancel one existing Task/revision, without creating a run.

    A matching retry returns the first cancellation record while the current
    owner remains valid, even after the run deadline. A new cancellation after
    that deadline is refused by the same state transaction that writes it.
    Any existing receipt path refuses cancellation; its presence alone does
    not prove a valid completed outcome. Only anchored execution readback does.
    """
    # Import here to keep the publication helper independent of this adapter.
    from .closed_loop_recovery import operation_lock

    owner_path, payload_path = Path(owner_path), Path(payload_path)
    owner = OwnerFile(owner_path, clock=clock)
    _, owner_sha = read_json(owner_path, 1024 * 1024, with_digest=True)
    raw, input_sha = read_json(payload_path, 256 * 1024, with_digest=True)
    binding = owner.read_task(raw.get("task_id"))
    # This path never dispatches. State distinguishes an existing cancellation
    # retry from a new request and applies the original run deadline to the latter.
    payload = validate_input(raw, binding, now=clock(), allow_expired_objective=True)
    require(payload["version"] == 2, "LOOP_OBJECTIVE_REQUIRED")
    root = safe_directory(owner.storage()["root"])
    require(Path(binding["active_home"]).is_absolute()
            and Path(binding["active_home"]).resolve() == root, "RUN_HOME_MISMATCH")
    run_id = "task-run-" + protocol.digest([payload["task_id"], payload["revision"]])[:32]
    directory = root / run_id
    require(directory.is_dir(), "RUN_RECOVERY_REQUIRED")
    directory = safe_directory(directory)

    def current():
        require(owner.read_task(payload["task_id"]) == binding, "STALE_BINDING")
        require(owner.storage()["root"] == root and safe_directory(root) == root,
                "RUN_STORAGE_CHANGED")
        require(read_json(owner_path, 1024 * 1024, with_digest=True)[1] == owner_sha,
                "OWNER_INPUT_CHANGED")
        require(read_json(payload_path, 256 * 1024, with_digest=True)[1] == input_sha,
                "RUN_INPUT_CHANGED")

    with operation_lock(directory):
        current()
        # Refuse even an unreadable or malformed published entry. Do not rename,
        # repair or interpret it as a completed run as part of cancellation.
        require(not os.path.lexists(directory / "receipt.json"), "RUN_CANCELLATION_RECEIPT_PRESENT")
        require((directory / "execution.sqlite").is_file(), "RUN_RECOVERY_REQUIRED")
        require(read_json(directory / "input.json", 256 * 1024) == payload,
                "RUN_REPLAY_CONFLICT")
        specification = read_json(directory / "specification.json")
        require(validate_plan(specification, payload) == specification, "RUN_REPLAY_CONFLICT")
        plan = read_json(directory / "plan.json")
        state = SwarmState(directory / "execution.sqlite", owner.read_task, clock=clock)
        require(state._normalize_plan(plan, clock(), binding) == plan
                and plan["run_id"] == run_id, "RUN_REPLAY_CONFLICT")
        planned = {job["job_id"]: job for job in plan["jobs"]}
        initial_digest = protocol.digest(specification)
        extra = set()
        if specification["version"] == 2:
            from .dependency_contract import descriptor, execution_version, REVIEW_ID
            desc, pre = descriptor(payload, specification)
            require(execution_version(plan) == 3 and plan["dependency_descriptor_sha256"] == protocol.digest(desc), "RUN_REPLAY_CONFLICT")
            extra.add(REVIEW_ID)
            require(planned[REVIEW_ID]["payload_digest"] == protocol.digest(pre), "RUN_REPLAY_CONFLICT")
        require(set(planned) == {"r0-critic", *("r0-" + job["job_id"] for job in specification["jobs"])} | extra,
                "RUN_REPLAY_CONFLICT")
        for job in specification["jobs"]:
            delivered = work_input(payload, job, 0, initial_digest, round_plan_digest=initial_digest)
            saved = planned[delivered["job_id"]]
            require(saved["kind"] == "work" and saved["payload_digest"] == protocol.digest(delivered),
                    "RUN_REPLAY_CONFLICT")
        template = read_json(directory / "r0-critic-template.json")
        require(planned["r0-critic"]["kind"] == "review"
                and planned["r0-critic"]["payload_digest"] == protocol.digest(template),
                "RUN_REPLAY_CONFLICT")
        current()
        # OS lock -> SQLite is the only public acknowledgment order. This
        # internal writer also checks the stored plan digest and current owner.
        return state._record_cancellation(run_id,
            expected_binding_digest=protocol.digest(binding),
            expected_initial_execution_plan_digest=protocol.digest(plan),
            owner_ref=binding["owner_ref"])
