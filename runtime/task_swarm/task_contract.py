"""Pure Task-run input/output contract; never creates authority or executes work."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from .protocol import SwarmError, canonical, digest, integer, validate_binding
from .task_planning import objective_criteria, validate_objective


WORK_JOBS = ("facts", "counterpoints", "options")
REVIEW_JOB = "review"
BASE_CRITERIA = {
    "C1": "依頼の問いに答えている",
    "C2": "主張ごとにTaskへ束縛された資料の根拠位置がある",
    "C3": "資料にない推測を事実として扱わない",
    "C4": "三つの報告の食い違いを隠さず示す",
}
MAX_INPUT_BYTES = 256 * 1024


def require(value: bool, code: str) -> None:
    if not value:
        raise SwarmError(code, "Task run contract refused")


def shape(value: Any, keys: set[str], code: str) -> None:
    require(isinstance(value, dict) and set(value) == keys, code)


def text(value: Any, limit: int, code: str) -> None:
    require(isinstance(value, str) and bool(value.strip()) and len(value) <= limit, code)
    require("\x00" not in value, code)
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise SwarmError(code, "text must be valid UTF-8") from exc


def validate_input(payload: Mapping[str, Any], binding: Mapping[str, Any], *, now: float) -> dict:
    require(isinstance(payload, dict), "TASK_INPUT_INVALID")
    version = payload.get("version")
    require(type(version) is int and version in (1, 2), "TASK_INPUT_INVALID")
    shape(payload, {"version", "task_id", "revision", "request", "acceptance", "sources"} |
          ({"objective"} if version == 2 else set()), "TASK_INPUT_INVALID")
    require(isinstance(payload["task_id"], str) and re.fullmatch(
        r"task-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", payload["task_id"]) is not None, "TASK_ID_INVALID")
    integer(payload["revision"], "Task revision", maximum=2**53-1)
    text(payload["request"], 4000, "TASK_REQUEST_INVALID")
    require(isinstance(payload["acceptance"], list) and len(payload["acceptance"]) <= 20, "TASK_ACCEPTANCE_INVALID")
    for criterion in payload["acceptance"]:
        text(criterion, 1000, "TASK_ACCEPTANCE_INVALID")
    require(isinstance(payload["sources"], list) and 1 <= len(payload["sources"]) <= 10, "TASK_SOURCES_INVALID")
    seen = set()
    for source in payload["sources"]:
        shape(source, {"key", "revision", "text", "sha256"}, "TASK_SOURCE_INVALID")
        require(isinstance(source["key"], str) and re.fullmatch(r"[a-f0-9]{64}", source["key"]) is not None, "TASK_SOURCE_INVALID")
        integer(source["revision"], "Source revision", minimum=0, maximum=2**53-1)
        text(source["text"], 12000, "TASK_SOURCE_INVALID")
        identity = (source["key"], source["revision"])
        require(identity not in seen, "TASK_SOURCE_DUPLICATE")
        seen.add(identity)
        try:
            encoded = source["text"].encode("utf-8")
        except UnicodeError as exc:
            raise SwarmError("TASK_SOURCE_INVALID", "source must be UTF-8 text") from exc
        require(hashlib.sha256(encoded).hexdigest() == source["sha256"], "TASK_SOURCE_DIGEST_MISMATCH")
    try:
        raw = canonical(payload).encode("utf-8")
    except (UnicodeError, ValueError, TypeError) as exc:
        raise SwarmError("TASK_INPUT_INVALID", "input must be finite JSON") from exc
    require(len(raw) <= MAX_INPUT_BYTES, "TASK_INPUT_LIMIT")
    current = validate_binding(binding, now=now)
    require(current["task_id"] == payload["task_id"], "WRONG_TASK")
    require(current["revision"] == payload["revision"], "STALE_BINDING")
    require(current["context_digest"] == digest(payload), "TASK_CONTEXT_MISMATCH")
    require(current["capability_ref"] == "ref/capability/swarm_research", "TASK_CAPABILITY_MISMATCH")
    require(current["expires_at"] - now <= 1260, "TASK_DEADLINE_TOO_LONG")
    if version == 2:
        validate_objective(payload, current, now=now)
    return json.loads(raw)


def criteria(payload: dict) -> dict[str, str]:
    return {**BASE_CRITERIA, **{f"U{i+1}": value for i, value in enumerate(payload["acceptance"])},
            **(objective_criteria(payload) if payload["version"] == 2 else {})}


def make_plan(payload: dict, binding: Mapping[str, Any], *, now: float) -> dict:
    payload = validate_input(payload, binding, now=now)
    current = validate_binding(binding, now=now)
    # Task ID/revision is the stable retry identity; immutable binding and input
    # digests are compared by the existing SwarmState before any repeat claim.
    run_id = "task-run-" + digest([payload["task_id"], payload["revision"]])[:32]
    budget = {"attempt_budget": 6, "concurrency": 3, "verifier_reserve": 1, "deadline": current["expires_at"]}
    if payload["version"] == 2:
        budget.update(payload["objective"]["budget"])
    jobs = [{"job_id": name, "kind": "work", "dependencies": [], "exclusive_keys": [],
             "payload_ref": "ref/task-input/" + name,
             "payload_digest": digest({"perspective": name, "payload": payload})}
            for name in WORK_JOBS]
    jobs.append({"job_id": REVIEW_JOB, "kind": "review", "dependencies": list(WORK_JOBS),
                 "exclusive_keys": [], "payload_ref": "ref/task-input/review",
                 "payload_digest": digest({"payload": payload, "criteria": criteria(payload)})})
    return {"run_id": run_id, "task_id": payload["task_id"], "binding_digest": digest(current),
            "budget": budget, "jobs": jobs}


def validate_report(value: dict, job_id: str, payload: dict) -> dict:
    require(job_id in WORK_JOBS, "REPORT_JOB_INVALID")
    shape(value, {"job_id", "summary", "claims", "conflicts"}, "REPORT_INVALID")
    require(value["job_id"] == job_id, "REPORT_JOB_MISMATCH")
    text(value["summary"], 6000, "REPORT_SUMMARY_INVALID")
    require(isinstance(value["claims"], list) and 1 <= len(value["claims"]) <= 30, "REPORT_CLAIMS_INVALID")
    require(isinstance(value["conflicts"], list) and len(value["conflicts"]) <= 20, "REPORT_CONFLICTS_INVALID")
    for conflict in value["conflicts"]:
        text(conflict, 1000, "REPORT_CONFLICTS_INVALID")
    sources = {(source["key"], source["revision"]): source["text"] for source in payload["sources"]}
    for claim in value["claims"]:
        shape(claim, {"text", "status", "evidence"}, "REPORT_CLAIM_INVALID")
        text(claim["text"], 3000, "REPORT_CLAIM_INVALID")
        require(isinstance(claim["status"], str) and claim["status"] in {"supported", "inference", "unknown"}, "REPORT_CLAIM_INVALID")
        require(isinstance(claim["evidence"], list) and len(claim["evidence"]) <= 10, "REPORT_EVIDENCE_INVALID")
        require(claim["status"] != "supported" or bool(claim["evidence"]), "REPORT_EVIDENCE_REQUIRED")
        for evidence in claim["evidence"]:
            shape(evidence, {"source_key", "source_revision", "start", "end", "quote"}, "REPORT_EVIDENCE_INVALID")
            require(isinstance(evidence["source_key"], str), "REPORT_SOURCE_MISMATCH")
            integer(evidence["source_revision"], "Source revision", minimum=0, maximum=2**53-1)
            source = sources.get((evidence["source_key"], evidence["source_revision"]))
            require(source is not None, "REPORT_SOURCE_MISMATCH")
            start = integer(evidence["start"], "span start", minimum=0, maximum=len(source))
            end = integer(evidence["end"], "span end", minimum=1, maximum=len(source))
            require(start < end and evidence["quote"] == source[start:end], "REPORT_SPAN_MISMATCH")
    return json.loads(canonical(value))


def validate_review(value: dict, payload: dict, reports: Mapping[str, dict]) -> dict:
    shape(value, {"context_digest", "report_digests", "validations"}, "REVIEW_INVALID")
    require(value["context_digest"] == digest(payload), "REVIEW_CONTEXT_MISMATCH")
    require(isinstance(reports, Mapping) and set(reports) == set(WORK_JOBS), "REVIEW_INPUT_INVALID")
    checked = {job: validate_report(report, job, payload) for job, report in reports.items()}
    report_digests = {job: digest(report) for job, report in checked.items()}
    require(value["report_digests"] == dict(report_digests), "REVIEW_STALE")
    expected = criteria(payload)
    require(isinstance(value["validations"], list) and len(value["validations"]) == len(expected), "REVIEW_COVERAGE_REQUIRED")
    found = set()
    for item in value["validations"]:
        shape(item, {"criterion_id", "status", "evidence", "gap_reason"}, "REVIEW_CRITERION_INVALID")
        name = item["criterion_id"]
        require(isinstance(name, str) and name in expected and name not in found, "REVIEW_COVERAGE_REQUIRED")
        found.add(name)
        require(isinstance(item["status"], str) and item["status"] in {"passed", "failed", "blocked", "not_run"}, "REVIEW_STATUS_INVALID")
        require(isinstance(item["evidence"], list) and len(item["evidence"]) <= 30, "REVIEW_EVIDENCE_INVALID")
        for ref in item["evidence"]:
            shape(ref, {"job_id", "claim_index"}, "REVIEW_EVIDENCE_INVALID")
            require(isinstance(ref["job_id"], str) and ref["job_id"] in WORK_JOBS, "REVIEW_EVIDENCE_INVALID")
            integer(ref["claim_index"], "claim index", minimum=0, maximum=len(checked[ref["job_id"]]["claims"])-1)
        if item["status"] == "passed":
            require(bool(item["evidence"]) and item["gap_reason"] is None, "REVIEW_EVIDENCE_REQUIRED")
            if name == "C4":
                require({ref["job_id"] for ref in item["evidence"]} == set(WORK_JOBS), "REVIEW_COMPARISON_REQUIRED")
        else:
            text(item["gap_reason"], 1000, "REVIEW_GAP_REQUIRED")
    return json.loads(canonical(value))
