"""Bound one fixed, read-only swarm run to its existing owner's input."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import stat
import threading
import time

from .owner_file import OwnerFile
from .protocol import SwarmError, canonical, digest
from .state import SwarmState
from .task_contract import (
    WORK_JOBS, REVIEW_JOB, make_plan, require, validate_input, validate_report, validate_review,
)


def read_bytes(filename: Path, maximum=2*1024*1024):
    # Pin the actual descriptor before bounded reads. Owner paths are private
    # controlled inputs, but links/large files still cannot widen this reader.
    info = filename.lstat()
    require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400, "RUN_FILE_REFUSED")
    fd = os.open(filename, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= maximum, "RUN_FILE_REFUSED")
        require((before.st_dev, before.st_ino) == (info.st_dev, info.st_ino), "RUN_FILE_CHANGED")
        chunks = []
        remaining = before.st_size + 1
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after, named = os.fstat(fd), filename.lstat()
        require(len(raw) == before.st_size and (before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_mtime_ns, after.st_ctime_ns) and (named.st_dev, named.st_ino) ==
                (before.st_dev, before.st_ino) and named.st_nlink == 1 and
                not stat.S_ISLNK(named.st_mode), "RUN_FILE_CHANGED")
        return raw
    finally:
        os.close(fd)


def read_json(filename: Path, maximum=2*1024*1024, *, with_digest=False):
    raw = read_bytes(filename, maximum)
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, "RUN_DUPLICATE_JSON_KEY")
            value[key] = item
        return value
    try:
        value = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError) as exc:
        raise SwarmError("RUN_JSON_INVALID", "Task evidence JSON could not be read") from exc
    return (value, hashlib.sha256(raw).hexdigest()) if with_digest else value


def verify_runtime(value, attempt, *, freeze=False):
    """Reopen nested runtime evidence before publication, acceptance and replay."""
    from datetime import datetime
    from .codex import _paths, _event_identity, _runtime_receipt, _redact, _result_from_message, _json_dump, MODEL, EFFORT
    from .confidential import require_observed_profile, runtime_paths
    receipt, supplied = value["receipt"], value["paths"]
    base = safe_directory(attempt)
    actual_attempt = Path(supplied["attempt_dir"])
    require(actual_attempt.parent == base and actual_attempt.name.startswith("attempt-"), "RUN_RUNTIME_PATH_CHANGED")
    paths = _paths(safe_directory(actual_attempt))
    work = safe_directory(actual_attempt/"work")
    require(supplied == {key:str(path) for key,path in paths.items()}, "RUN_RUNTIME_PATH_CHANGED")
    saved_receipt, receipt_sha = read_json(paths["receipt"], with_digest=True)
    require(saved_receipt == receipt and (freeze or value.get("runtime_receipt_sha256") == receipt_sha),
            "RUN_RUNTIME_RECEIPT_CHANGED")
    required = {"schema", "command", "process", "events", "stderr", "last_message", "result"}
    require(set(receipt.get("artifact_digests", {})) == required, "RUN_RUNTIME_RECEIPT_INVALID")
    for key in required:
        require(hashlib.sha256(read_bytes(paths[key], 16*1024*1024)).hexdigest() == receipt["artifact_digests"][key],
                "RUN_RUNTIME_ARTIFACT_CHANGED")
    require(read_json(paths["result"]) == value["result"], "RUN_RUNTIME_RESULT_CHANGED")
    require(receipt.get("permission_probe") == {"kind":"task_synthetic_permission_probe_v1",
            "outer_read_denied":True,"inner_metadata_read_denied":True,"model_called":False}, "RUN_RUNTIME_POLICY_MISSING")
    events = [json.loads(line) for line in read_bytes(paths["events"],16*1024*1024).splitlines() if line.strip()]
    thread, turn = _event_identity(events)
    process = read_json(paths["process"])
    require(thread == receipt["thread_id"] and (turn is None or turn == receipt["turn_id"]) and
            process["pid"] == receipt["pid"] and abs(process["created_at"]-receipt["created_at"]) <= .001,
            "RUN_RUNTIME_IDENTITY_CHANGED")
    rollout = Path(receipt["runtime_receipt_path"])
    safe_directory(rollout.parent)
    raw = read_bytes(rollout, 16*1024*1024)
    sha = hashlib.sha256(raw).hexdigest()
    if not freeze:
        require(value.get("runtime_rollout_sha256") == sha, "RUN_RUNTIME_ROLLOUT_CHANGED")
    started = datetime.fromisoformat(receipt["started_at"].replace("Z", "+00:00")).timestamp()
    runtime = _runtime_receipt(thread, receipt["turn_id"], rollout.parent, work, started, exact_record=(rollout, raw))
    require(runtime is not None and runtime["runtime_receipt_path"] == str(rollout) and
            runtime["model"] == MODEL and runtime["effort"] == EFFORT and
            runtime["approval_policy"] == "never" and not runtime["turn_failed"] and
            _redact(_result_from_message(runtime["completed_output"])) == value["result"], "RUN_RUNTIME_BINDING_CHANGED")
    command = read_json(paths["command"])
    require(isinstance(command.get("argv"),list) and command["argv"] and
            isinstance(command["argv"][0],str) and Path(command["argv"][0]).is_absolute(), "RUN_RUNTIME_PATH_CHANGED")
    require_observed_profile(runtime["permission_profile"],runtime["active_permission_profile"],
                             {**runtime_paths(command["argv"][0]),str(work):"read"})
    require(receipt.get("permission_profile_sha256") == hashlib.sha256(_json_dump(runtime["permission_profile"]).encode("utf-8")).hexdigest(),
            "RUN_RUNTIME_POLICY_CHANGED")
    require(read_bytes(rollout,16*1024*1024) == raw, "RUN_RUNTIME_ROLLOUT_CHANGED")
    if freeze:
        value["runtime_rollout_sha256"] = sha
        value["runtime_receipt_sha256"] = receipt_sha


def write_json(filename: Path, value):
    raw = (canonical(value)+"\n").encode("utf-8")
    require(len(raw) <= 2*1024*1024, "RUN_OUTPUT_LIMIT")
    with filename.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    checked, sha = read_json(filename, with_digest=True)
    require(checked == value and sha == hashlib.sha256(raw).hexdigest(), "RUN_OUTPUT_READBACK")
    return sha


def safe_directory(directory: Path):
    require(directory.is_absolute(), "RUN_DIRECTORY_REQUIRED")
    for component in reversed((directory, *directory.parents)):
        info = component.lstat()
        require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode) and
                not getattr(info, "st_file_attributes", 0) & 0x400, "RUN_DIRECTORY_REFUSED")
    return directory.resolve(strict=True)


def execute_task(owner_path, payload_path, backend, *, cancel_event=None, clock=time.time, expected_receipt_sha256=None):
    owner = OwnerFile(owner_path, clock=clock)
    _, owner_input_sha = read_json(Path(owner_path), 1024*1024, with_digest=True)
    payload = read_json(Path(payload_path), 256*1024)
    binding = owner.read_task(payload.get("task_id"))
    # A supplied receipt anchor requests readback only. This path cannot create
    # a run and still requires a current owner, exact input and intact artifacts.
    replay_only = expected_receipt_sha256 is not None
    payload = validate_input(payload, binding, now=clock(), allow_expired_objective=replay_only)
    plan = make_plan(payload, binding, now=clock(), allow_expired_objective=replay_only)
    root = safe_directory(owner.storage()["root"])
    require(Path(binding["active_home"]).is_absolute() and Path(binding["active_home"]).resolve() == root, "RUN_HOME_MISMATCH")
    actors = {job: "worker-"+job for job in WORK_JOBS}
    actors[REVIEW_JOB] = "verifier"
    require(binding["owner_ref"] not in actors.values(), "RUN_OWNER_INDEPENDENCE")
    actor_bindings = {actor: owner.read_binding(binding["task_id"], actor) for actor in actors.values()}
    for actor_binding in actor_bindings.values():
        require(actor_binding["actor_status"] == "active" and actor_binding["capability_ref"] == binding["capability_ref"], "RUN_ACTOR_SCOPE_INVALID")
    cancellation = cancel_event if cancel_event is not None else threading.Event()
    require(isinstance(cancellation, threading.Event), "RUN_CANCELLATION_INVALID")
    expected = digest(binding)
    def guard():
        require(not cancellation.is_set(), "RUN_CANCELLED")
        current = owner.read_task(binding["task_id"])
        require(digest(current) == expected, "STALE_BINDING")
        for actor, initial in actor_bindings.items():
            require(owner.read_binding(binding["task_id"], actor) == initial, "STALE_ACTOR")
        require(replay_only or clock() < plan["budget"]["deadline"], "DEADLINE_EXPIRED")
        require(owner.storage()["root"] == root and safe_directory(root) == root, "RUN_STORAGE_CHANGED")
        require(read_json(Path(owner_path), 1024*1024, with_digest=True)[1] == owner_input_sha, "OWNER_INPUT_CHANGED")
    guard()
    directory = root / plan["run_id"]
    if directory.exists():
        safe_directory(directory)
        require((directory / "receipt.json").is_file(), "RUN_RECOVERY_REQUIRED")
        require(isinstance(expected_receipt_sha256, str) and len(expected_receipt_sha256) == 64, "RUN_REPLAY_ANCHOR_REQUIRED")
        receipt, receipt_sha = read_json(directory / "receipt.json", with_digest=True)
        require(receipt_sha == expected_receipt_sha256, "RUN_REPLAY_ANCHOR_MISMATCH")
        require(receipt["binding_digest"] == expected and receipt["owner_input_sha256"] == owner_input_sha and receipt["input_digest"] == digest(payload) and
                receipt["synthetic"] == bool(backend.synthetic), "RUN_REPLAY_CONFLICT")
        required = {*[job+".json" for job in WORK_JOBS], "review.json", "result.json", "input.json", "plan.json"}
        require(set(receipt["artifact_sha256"]) == required, "RUN_RECEIPT_INVALID")
        for name, sha in receipt["artifact_sha256"].items():
            require(name in required, "RUN_RECEIPT_INVALID")
            document, actual = read_json(directory / name, with_digest=True)
            require(actual == sha, "RUN_ARTIFACT_CHANGED")
            if name == "result.json":
                checked_result = document
        if not backend.synthetic:
            for job in (*WORK_JOBS, REVIEW_JOB):
                verify_runtime(read_json(directory/(job+".json")), directory/"attempts"/job)
        guard()
        return {"result": checked_result, "receipt": receipt, "receipt_sha256":receipt_sha, "duplicate": True}
    require(expected_receipt_sha256 is None, "RUN_REPLAY_MISSING")
    directory.mkdir(mode=0o700)
    input_sha = write_json(directory / "input.json", payload)
    plan_sha = write_json(directory / "plan.json", plan)
    state = SwarmState(directory / "execution.sqlite", owner.read_task, clock=clock)
    state.create_run(plan)
    done = threading.Event()
    failures = []
    def monitor():
        while not done.wait(.1):
            try:
                guard()
            except Exception as exc:
                failures.append(getattr(exc, "code", "BINDING_UNAVAILABLE"))
                cancellation.set()
                return
    watcher = threading.Thread(target=monitor, name="swarm-owner-watch", daemon=True)
    watcher.start()
    reports, evidence, leases = {}, {}, {}
    def call(job):
        guard()
        owner.read_binding(binding["task_id"], actors[job])
        lease = leases[job]
        result = backend.produce(job, payload, directory / "attempts" / job,
            timeout=min(360, plan["budget"]["deadline"]-clock()), cancel_event=cancellation,
            on_process=lambda pid, created: state.attach_identity(lease["token"], {"kind":"process","pid":pid,"created_at":created}))
        guard()
        report = validate_report(result["result"], job, payload)
        if not backend.synthetic:
            verify_runtime(result, directory/"attempts"/job, freeze=True)
        sha = write_json(directory / (job+".json"), result)
        guard()
        state.report(lease["token"], "ref/task-result/"+job, sha, "candidate", "ref/task-runtime/"+job)
        return job, report, result["receipt"], sha
    try:
        # Claim order in the state scheduler is deterministic. Dispatch each
        # claimed role from that result rather than relying on thread timing.
        for job in sorted(WORK_JOBS):
            guard()
            lease = state.claim(plan["run_id"], actors[job], lease_seconds=min(390, plan["budget"]["deadline"]-clock()))
            require(lease is not None and lease["job_id"] == job, "RUN_PLAN_ASSIGNMENT")
            leases[job] = lease
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(call, job) for job in WORK_JOBS]
            for future in as_completed(futures):
                try:
                    job, report, receipt, sha = future.result()
                    reports[job], evidence[job] = report, {"receipt": receipt, "sha256": sha}
                except Exception:
                    cancellation.set()
                    raise
        guard()
        owner.read_binding(binding["task_id"], actors[REVIEW_JOB])
        lease = state.claim(plan["run_id"], actors[REVIEW_JOB], lease_seconds=min(390, plan["budget"]["deadline"]-clock()))
        require(lease is not None and lease["job_id"] == REVIEW_JOB, "RUN_REVIEW_MISSING")
        reviewed = backend.review(payload, reports, directory / "attempts" / REVIEW_JOB,
            timeout=min(360, plan["budget"]["deadline"]-clock()), cancel_event=cancellation,
            on_process=lambda pid, created: state.attach_identity(lease["token"], {"kind":"process","pid":pid,"created_at":created}))
        guard()
        review = validate_review(reviewed["result"], payload, reports)
        if not backend.synthetic:
            verify_runtime(reviewed, directory/"attempts"/REVIEW_JOB, freeze=True)
        identities = [item["receipt"].get("invocation_ref" if backend.synthetic else "thread_id") for item in evidence.values()]
        identities.append(reviewed["receipt"].get("invocation_ref" if backend.synthetic else "thread_id"))
        require(all(isinstance(item,str) and item for item in identities) and len(set(identities)) == 4, "REVIEW_NOT_INDEPENDENT")
        review_sha = write_json(directory / "review.json", reviewed)
        state.report(lease["token"], "ref/task-result/review", review_sha, "candidate", "ref/task-runtime/review")
        accepted = all(item["status"] == "passed" for item in review["validations"])
        artifact_sha = {**{job+".json": evidence[job]["sha256"] for job in WORK_JOBS}, "review.json": review_sha,
                        "input.json": input_sha, "plan.json": plan_sha}
        def verify_artifacts():
            safe_directory(directory)
            for name, sha in artifact_sha.items():
                _, actual = read_json(directory / name, with_digest=True)
                require(actual == sha, "RUN_ARTIFACT_CHANGED")
            if not backend.synthetic:
                for job in (*WORK_JOBS, REVIEW_JOB):
                    verify_runtime(read_json(directory/(job+".json")), directory/"attempts"/job)
        verify_artifacts()
        result = {"state": "needs_review" if accepted else "failed",
                  "reports": reports, "validations": review["validations"],
                  "independent_review": accepted, "model_runtime_verified": not backend.synthetic,
                  "synthetic": bool(backend.synthetic), "task_id": binding["task_id"], "revision": binding["revision"]}
        guard()
        result_sha = write_json(directory / "result.json", result)
        artifact_sha["result.json"] = result_sha
        if accepted:
            for job, sha in [(name, evidence[name]["sha256"]) for name in WORK_JOBS] + [(REVIEW_JOB, review_sha)]:
                guard()
                verify_artifacts()
                state.accept(plan["run_id"], job, sha, "ref/task-verification/"+review_sha, binding["owner_ref"])
        receipt = {"version":1, "run_id":plan["run_id"], "binding_digest":expected,
                   "owner_input_sha256":owner_input_sha, "input_digest":digest(payload), "synthetic":bool(backend.synthetic),
                   "task_state_changed":False, "accepted":accepted,
                   "artifact_sha256": artifact_sha}
        guard()
        verify_artifacts()
        receipt_sha = write_json(directory / "receipt.json", receipt)
        guard()
        return {"result":result, "receipt":receipt, "receipt_sha256":receipt_sha, "duplicate":False}
    finally:
        done.set()
        watcher.join(timeout=1)
