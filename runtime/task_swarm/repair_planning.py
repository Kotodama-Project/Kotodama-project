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
            and template["repair_planning_contract"] == 1
            and template.get("evidence_contract_version") == 2,
            "LOOP_REPAIR_PROFILE")
    return 1


def file_sha(value):
    return hashlib.sha256((canonical(value) + "\n").encode("utf-8")).hexdigest()


def derive_repair(payload, initial, gap):
    """Return the full assigned-leaf repair or refuse; never trim to a budget."""
    from .closed_loop_contract import span_identity, validate_plan
    initial = validate_plan(initial, payload)
    require(isinstance(gap, dict) and gap.get("parent_input_digest") == digest(payload)
            and gap.get("plan_digest") == digest(initial), "LOOP_REPAIR_BINDING")
    failed = set(gap["failed_criteria"])
    records = {item["criterion_id"]: item for item in gap["validations"]}
    require(failed and set(records) == failed and len(records) == len(gap["validations"]),
            "LOOP_REPAIR_BINDING")
    jobs, assignments, covered, selected = [], [], set(), set()
    for ordinal, original in enumerate(sorted(initial["jobs"], key=lambda job: job["job_id"])):
        assigned = sorted(failed.intersection(original["criterion_ids"]))
        if not assigned:
            continue
        spans = {span_identity(span): span for key in assigned for span in records[key]["source_spans"]}
        require(spans, "LOOP_REPAIR_SCOPE")
        selected.update(spans)
        covered.update(assigned)
        # Initial IDs start with a letter; ordinals occupy a disjoint namespace.
        job_id = "repair-" + (original["job_id"] if len(original["job_id"]) <= 49 else str(ordinal))
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
                if key not in {"template_digest", "reports", "report_digests"}}
    critic = validate_critic(prior["response"]["result"], payload, previous["reports"],
        view=previous["view"], plan_digest=digest(initial), round_index=0,
        initial_execution_plan_digest=digest(runtime_plan), expected_jobs=work,
        dispatched_input=previous, dispatched_input_digest=prior["dispatched_input_digest"],
        initial_specification=initial, initial_runtime_plan=runtime_plan,
        initial_template=template, work_inputs=work_inputs)
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
    return proposal, impact

def _stream_identity(stream):
    """Compare open handles without mixing Windows lstat/fstat identities."""
    import os
    if os.name != "nt":
        metadata = os.fstat(stream.fileno())
        require(metadata.st_ino != 0, "RUN_ARTIFACT_CHANGED")
        return metadata.st_dev, metadata.st_ino
    import ctypes
    from ctypes import wintypes
    import msvcrt
    # Keep the structure and function prototype local to this call. Mutating a
    # cached ctypes function's argtypes would race with concurrent inspectors.
    class FileIdInfo(ctypes.Structure):
        _fields_ = [("volume", ctypes.c_ulonglong), ("identifier", ctypes.c_ubyte * 16)]
    query = ctypes.WinDLL("kernel32", use_last_error=True).GetFileInformationByHandleEx
    query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    query.restype = wintypes.BOOL
    information = FileIdInfo()
    require(query(msvcrt.get_osfhandle(stream.fileno()), 18,
                  ctypes.byref(information), ctypes.sizeof(information)), "RUN_ARTIFACT_CHANGED")
    require(information.volume != 0 and any(information.identifier), "RUN_ARTIFACT_CHANGED")
    return information.volume, bytes(information.identifier)


def _inspection_cut(database, destination):
    """Copy a bounded physical cut using only reads of original DB/WAL/SHM."""
    import os
    import stat
    from contextlib import ExitStack
    limit = 8 * 1024 * 1024
    paths = [database, database.with_name(database.name + "-wal"),
             database.with_name(database.name + "-shm")]
    def identity(metadata):
        return (metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_size,
                metadata.st_mtime_ns, metadata.st_ctime_ns)
    fingerprint = []
    with ExitStack() as stack:
        streams, before, descriptors, handles = [], [], [], []
        for index, path in enumerate(paths):
            try:
                metadata = path.lstat()
            except FileNotFoundError:
                require(index != 0, "LOOP_REPAIR_STATE")
                before.append(None); streams.append(None)
                descriptors.append(None); handles.append(None)
                continue
            require(stat.S_ISREG(metadata.st_mode), "LOOP_REPAIR_STATE")
            stream = stack.enter_context(path.open("rb"))
            descriptor = os.fstat(stream.fileno())
            require(stat.S_ISREG(descriptor.st_mode), "LOOP_REPAIR_STATE")
            handle = _stream_identity(stream)
            with path.open("rb") as named:
                require(_stream_identity(named) == handle, "RUN_ARTIFACT_CHANGED")
            require(identity(path.lstat()) == identity(metadata), "RUN_ARTIFACT_CHANGED")
            before.append(metadata); streams.append(stream)
            descriptors.append(descriptor); handles.append(handle)
        require(sum(item.st_size for item in descriptors if item is not None) <= limit,
                "LOOP_REPAIR_STATE")
        consumed = 0
        for index, (path, stream, metadata) in enumerate(zip(paths, streams, before)):
            if stream is None:
                fingerprint.append(None)
                continue
            checksum = hashlib.sha256()
            output = (stack.enter_context((destination / path.name).open("xb"))
                      if index != 2 else None)
            count = 0
            while True:
                block = stream.read(64 * 1024)
                if not block:
                    break
                count += len(block); consumed += len(block)
                require(consumed <= limit, "LOOP_REPAIR_STATE")
                checksum.update(block)
                if output is not None:
                    output.write(block)
            require(count == descriptors[index].st_size
                    and identity(os.fstat(stream.fileno())) == identity(descriptors[index]),
                    "RUN_ARTIFACT_CHANGED")
            fingerprint.append((identity(metadata), handles[index], checksum.hexdigest()))
        for path, metadata, stream, descriptor, handle in zip(paths, before, streams, descriptors, handles):
            try:
                current = path.lstat()
            except FileNotFoundError:
                current = None
            require((None if current is None else identity(current))
                    == (None if metadata is None else identity(metadata)), "RUN_ARTIFACT_CHANGED")
            if stream is not None:
                with path.open("rb") as named:
                    require(_stream_identity(named) == handle == _stream_identity(stream),
                            "RUN_ARTIFACT_CHANGED")
                require(identity(os.fstat(stream.fileno())) == identity(descriptor)
                        and identity(path.lstat()) == identity(metadata), "RUN_ARTIFACT_CHANGED")
    return fingerprint


def _inspection_state(database, owner, clock):
    """Validate the copied original schema before any scheduler initializer."""
    import sqlite3
    from contextlib import closing
    required = {
        "runs": "run_id task_id binding_digest plan_json attempt_budget concurrency deadline created_at",
        "jobs": "run_id job_id kind dependencies_json exclusive_keys_json payload_ref payload_digest state reason accepted_digest verification_ref accepted_owner_ref accepted_at",
        "attempts": "token run_id job_id attempt epoch worker_ref state lease_until identity_json result_ref result_digest outcome runtime_receipt_ref reason retryable per_job_limit created_at updated_at",
        "run_extensions": "run_id extension_json",
        "run_finalizations": "run_id checkpoint_json progress_json receipt_json",
        "run_cancellations": "run_id cancellation_json",
    }
    try:
        with database.open("rb") as stream:
            require(stream.read(16) == b"SQLite format 3\x00", "LOOP_REPAIR_STATE")
        # The copy's own SHM may be rebuilt. immutable=1 would omit committed WAL.
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
            require(conn.execute("PRAGMA quick_check").fetchall() == [("ok",)], "LOOP_REPAIR_STATE")
            for table, columns in required.items():
                actual = {row[1] for row in conn.execute("PRAGMA table_info(" + table + ")")}
                require(set(columns.split()) <= actual, "LOOP_REPAIR_STATE")
    except sqlite3.Error as error:
        from .protocol import SwarmError
        raise SwarmError("LOOP_REPAIR_STATE", "saved execution state is invalid") from error
    from .state import SwarmState
    return SwarmState(database, owner.read_task, clock=clock)

def inspect_repair(owner_path, payload_path, *, clock=None):
    """Read a saved, current r0 review; return a proposal without admitting it."""
    from pathlib import Path
    import time
    from .closed_loop_contract import evidence_version
    from .owner_file import OwnerFile
    from tempfile import TemporaryDirectory
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
    with TemporaryDirectory(prefix="kotodama-repair-inspect-") as private:
        cut = _inspection_cut(directory/"execution.sqlite", Path(private))
        state = _inspection_state(Path(private)/"execution.sqlite", owner, clock)
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
        require(profile(template) == 1, "LOOP_REPAIR_PROFILE")
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
        with TemporaryDirectory(prefix="kotodama-repair-recheck-") as fresh:
            current = _inspection_cut(directory/"execution.sqlite", Path(fresh))
            live = _inspection_state(Path(fresh)/"execution.sqlite", owner, clock)
            require(live.cancellation(run_id) is None, "RUN_CANCELLED")
            live.snapshot(run_id)
            require(current == cut, "RUN_ARTIFACT_CHANGED")
            # A writer or cancellation during the fresh read is also a changed cut.
            with TemporaryDirectory(prefix="kotodama-repair-final-") as final:
                require(_inspection_cut(directory/"execution.sqlite", Path(final)) == cut,
                        "RUN_ARTIFACT_CHANGED")
        require(read_json(Path(owner_path), 1024 * 1024, with_digest=True)[1] == owner_sha
                and owner.read_task() == binding and read_json(Path(payload_path), 256 * 1024) == payload,
                "STALE_BINDING")
        validate_input(payload, binding, now=clock())
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
