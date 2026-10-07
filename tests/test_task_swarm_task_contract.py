"""Closed, synthetic Task-run contract, no process/model/provider execution."""
import copy
import hashlib
from pathlib import Path
import sys

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest job")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from task_swarm.protocol import SwarmError, digest
from task_swarm.task_contract import (
    WORK_JOBS, criteria, make_plan, validate_input, validate_report, validate_review,
)


def fixture():
    source = "合成の資料。観測値は42。未確認の理由は分からない。"
    payload = {"version": 1, "task_id": "task-00000000-0000-4000-8000-000000000001", "revision": 2,
               "request": "観測値と未確認事項を分けて整理する", "acceptance": ["元の資料を示す"],
               "sources": [{"key": "a"*64, "revision": 4, "text": source,
                            "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest()}]}
    binding = {"task_id": payload["task_id"], "revision": 2, "context_digest": digest(payload),
               "owner_ref": "ref/owner/fixture", "active_home": "fixture",
               "authority_ref": "ref/authority/fixture", "capability_ref": "ref/capability/swarm_research",
               "expires_at": 2200, "status": "active"}
    report = {"job_id": "facts", "summary": "合成要約", "claims": [
        {"text": "合成資料は42と記載する", "status": "supported", "evidence": [
            {"source_key": "a"*64, "source_revision": 4, "start": 0, "end": 6, "quote": source[:6]}]}],
        "conflicts": []}
    reports = {job: {**copy.deepcopy(report), "job_id": job} for job in WORK_JOBS}
    review = {"context_digest": digest(payload), "report_digests": {job: digest(value) for job, value in reports.items()},
              "validations": [{"criterion_id": name, "status": "passed",
                               "evidence": [{"job_id": job, "claim_index": 0} for job in (WORK_JOBS if name == "C4" else ("facts",))], "gap_reason": None}
                              for name in criteria(payload)]}
    return payload, binding, reports, review


def test_closed_input_plan_has_stable_task_identity_and_bounded_independent_review():
    payload, binding, reports, review = fixture()
    checked = validate_input(payload, binding, now=1000)
    assert checked == payload and checked is not payload
    plan = make_plan(payload, binding, now=1000)
    assert plan["budget"] == {"attempt_budget": 6, "concurrency": 3, "verifier_reserve": 1, "deadline": 2200}
    assert len(plan["jobs"]) == 4
    assert plan["jobs"][-1]["kind"] == "review"
    assert plan["jobs"][-1]["dependencies"] == list(WORK_JOBS)
    assert make_plan(payload, binding, now=1001) == plan
    assert validate_review(review, payload, reports) == review
    binding["expires_at"] = 1300
    assert make_plan(payload, binding, now=1000)["budget"]["deadline"] == 1300


@pytest.mark.parametrize("field,value,code", [
    ("task_id", "task-00000000-0000-4000-8000-000000000002", "WRONG_TASK"),
    ("revision", 3, "STALE_BINDING"), ("revision", True, "INVALID_LIMIT"),
    ("context_digest", "0"*64, "TASK_CONTEXT_MISMATCH"),
    ("capability_ref", "ref/capability/research", "TASK_CAPABILITY_MISMATCH"),
    ("status", "cancelled", "INACTIVE_TASK"), ("expires_at", 999, "EXPIRED_BINDING"),
    ("expires_at", 3000, "TASK_DEADLINE_TOO_LONG"),
])
def test_changed_owner_cannot_reuse_task_input(field, value, code):
    payload, binding, _, _ = fixture()
    binding[field] = value
    with pytest.raises(SwarmError) as raised:
        validate_input(payload, binding, now=1000)
    assert raised.value.code == code


def test_source_bytes_versions_duplicates_and_unknown_input_are_not_silently_truncated():
    for mutation in ("text", "revision", "duplicate", "extra", "size"):
        payload, binding, _, _ = fixture()
        if mutation == "text":
            payload["sources"][0]["text"] += "変更"
        elif mutation == "revision":
            payload["sources"][0]["revision"] = True
        elif mutation == "duplicate":
            payload["sources"].append(copy.deepcopy(payload["sources"][0]))
        elif mutation == "extra":
            payload["privilege"] = "owner"
        else:
            payload["request"] = "x"*4001
        with pytest.raises(SwarmError):
            validate_input(payload, binding, now=1000)


def test_report_requires_exact_current_source_span_and_does_not_promote_inferences():
    for mutation in ("missing", "quote", "revision", "offset", "job", "unknown", "claim"):
        payload, _, reports, _ = fixture()
        report = reports["facts"]
        evidence = report["claims"][0]["evidence"][0]
        if mutation == "missing": report["claims"][0]["evidence"] = []
        elif mutation == "quote": evidence["quote"] = "別の本文"
        elif mutation == "revision": evidence["source_revision"] = 3
        elif mutation == "offset": evidence["end"] = 999
        elif mutation == "job": report["job_id"] = "review"
        elif mutation == "unknown": report["grant"] = "write"
        else: report["claims"][0]["status"] = "confirmed"
        with pytest.raises(SwarmError):
            validate_report(report, "facts", payload)
    payload, _, reports, _ = fixture()
    reports["facts"]["claims"][0].update(status="inference", evidence=[])
    assert validate_report(reports["facts"], "facts", payload)["claims"][0]["status"] == "inference"


def test_review_binds_exact_reports_and_every_user_criterion():
    for mutation in ("stale", "missing", "duplicate", "unknown", "evidence", "index", "gap", "comparison"):
        payload, _, reports, review = fixture()
        if mutation == "stale": reports["facts"]["summary"] = "別の要約"
        elif mutation == "missing": review["validations"].pop()
        elif mutation == "duplicate": review["validations"][-1] = copy.deepcopy(review["validations"][0])
        elif mutation == "unknown": review["grant"] = True
        elif mutation == "evidence": review["validations"][0]["evidence"] = []
        elif mutation == "index": review["validations"][0]["evidence"][0]["claim_index"] = 1
        elif mutation == "comparison": review["validations"][3]["evidence"].pop()
        else: review["validations"][0]["status"] = "blocked"
        with pytest.raises(SwarmError):
            validate_review(review, payload, reports)
    payload, _, reports, review = fixture()
    review["validations"][0].update(status="not_run", evidence=[], gap_reason="合成試験の未検査")
    result = validate_review(review, payload, reports)
    assert result["validations"][0]["status"] == "not_run"


@pytest.mark.parametrize("field,value", [("request", "別の問いへ変更"), ("acceptance", ["別の受入条件"])])
def test_review_cannot_borrow_identical_reports_for_different_task_requirements(field, value):
    payload, _, reports, review = fixture()
    payload[field] = value
    with pytest.raises(SwarmError) as raised:
        validate_review(review, payload, reports)
    assert raised.value.code == "REVIEW_CONTEXT_MISMATCH"


@pytest.mark.parametrize("field", ["summary", "claim", "conflict", "gap"])
def test_output_lone_surrogates_are_typed_refusals(field):
    payload, _, reports, review = fixture()
    if field == "summary": reports["facts"]["summary"] = "\ud800"
    elif field == "claim": reports["facts"]["claims"][0]["text"] = "\ud800"
    elif field == "conflict": reports["facts"]["conflicts"] = ["\ud800"]
    else:
        review["validations"][0].update(status="blocked", evidence=[], gap_reason="\ud800")
    with pytest.raises(SwarmError):
        if field == "gap":
            validate_review(review, payload, reports)
        else:
            validate_report(reports["facts"], "facts", payload)
