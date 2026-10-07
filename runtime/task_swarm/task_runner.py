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


def read_json(filename: Path, maximum=2*1024*1024, *, with_digest=False):
    # Pin the actual descriptor before bounded reads. Owner paths are private
    # controlled inputs, but links/large files still cannot widen this reader.
    info = filename.lstat()
    require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400, "RUN_FILE_REFUSED")
    fd = os.open(filename, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
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
        def unique(pairs):
            value = {}
            for key, item in pairs:
                require(key not in value, "RUN_DUPLICATE_JSON_KEY")
                value[key] = item
            return value
        value = json.loads(raw, object_pairs_hook=unique)
        return (value, hashlib.sha256(raw).hexdigest()) if with_digest else value
    finally:
        os.close(fd)


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


def execute_task(owner_path, payload_path, backend, *, cancel_event=None, clock=time.time):
    owner = OwnerFile(owner_path, clock=clock)
    _, owner_input_sha = read_json(Path(owner_path), 1024*1024, with_digest=True)
    payload = read_json(Path(payload_path), 256*1024)
    binding = owner.read_task(payload.get("task_id"))
    payload = validate_input(payload, binding, now=clock())
    plan = make_plan(payload, binding, now=clock())
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
        require(clock() < plan["budget"]["deadline"], "DEADLINE_EXPIRED")
        require(owner.storage()["root"] == root and safe_directory(root) == root, "RUN_STORAGE_CHANGED")
        require(read_json(Path(owner_path), 1024*1024, with_digest=True)[1] == owner_input_sha, "OWNER_INPUT_CHANGED")
    guard()
    directory = root / plan["run_id"]
    if directory.exists():
        safe_directory(directory)
        require((directory / "receipt.json").is_file(), "RUN_RECOVERY_REQUIRED")
        receipt = read_json(directory / "receipt.json")
        require(receipt["binding_digest"] == expected and receipt["owner_input_sha256"] == owner_input_sha and receipt["input_digest"] == digest(payload) and
                receipt["synthetic"] == bool(backend.synthetic), "RUN_REPLAY_CONFLICT")
        required = {*[job+".json" for job in WORK_JOBS], "review.json", "result.json", "input.json", "plan.json"}
        require(set(receipt["artifact_sha256"]) == required, "RUN_RECEIPT_INVALID")
        for name, sha in receipt["artifact_sha256"].items():
            require(name in required, "RUN_RECEIPT_INVALID")
            _, actual = read_json(directory / name, with_digest=True)
            require(actual == sha, "RUN_ARTIFACT_CHANGED")
        guard()
        return {"result": read_json(directory / "result.json"), "receipt": receipt, "duplicate": True}
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
        verify_artifacts()
        if accepted:
            for job, sha in [(name, evidence[name]["sha256"]) for name in WORK_JOBS] + [(REVIEW_JOB, review_sha)]:
                guard()
                verify_artifacts()
                state.accept(plan["run_id"], job, sha, "ref/task-verification/"+review_sha, binding["owner_ref"])
        result = {"state": "needs_review" if accepted else "failed",
                  "reports": reports, "validations": review["validations"],
                  "independent_review": accepted, "model_runtime_verified": not backend.synthetic,
                  "synthetic": bool(backend.synthetic), "task_id": binding["task_id"], "revision": binding["revision"]}
        guard()
        result_sha = write_json(directory / "result.json", result)
        artifact_sha["result.json"] = result_sha
        receipt = {"version":1, "run_id":plan["run_id"], "binding_digest":expected,
                   "owner_input_sha256":owner_input_sha, "input_digest":digest(payload), "synthetic":bool(backend.synthetic),
                   "task_state_changed":False, "accepted":accepted,
                   "artifact_sha256": artifact_sha}
        guard()
        verify_artifacts()
        write_json(directory / "receipt.json", receipt)
        guard()
        return {"result":result, "receipt":receipt, "duplicate":False}
    finally:
        done.set()
        watcher.join(timeout=1)
