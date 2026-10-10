"""Pure contracts for a bounded, owner-bound research repair round.

Plans are supplied data, not generated authority. This first slice admits a
finite parallel frontier followed by a critic, and at most one repair frontier.
"""
from __future__ import annotations

import json
import re

from .protocol import canonical, digest
from .task_contract import require, shape, text
from .task_planning import _Sources, objective_criteria


def loop_criteria(payload):
    result = {
        "R": "Answer the current request: " + payload["request"],
        "S": "Bind factual claims to supplied source spans.",
        "U": "Keep uncertainty and inference explicit.",
        "I": "Compare the relevant reports and preserve disagreements.",
    }
    result.update({f"A{i+1}": value for i, value in enumerate(payload["acceptance"])})
    result.update(objective_criteria(payload))
    return result


def span_identity(span):
    return tuple(span[key] for key in ("source_key", "source_revision", "start", "end"))


def validate_plan(value, payload, *, gap=None):
    shape(value, {"version", "parent_input_digest", "jobs"}, "LOOP_PLAN_INVALID")
    require(type(value["version"]) is int and value["version"] == 1, "LOOP_PLAN_INVALID")
    require(value["parent_input_digest"] == digest(payload), "LOOP_PLAN_STALE")
    require(isinstance(value["jobs"], list) and 1 <= len(value["jobs"]) <= 3, "LOOP_PLAN_LIMIT")
    criteria, sources = loop_criteria(payload), _Sources(payload)
    expected = set(gap["failed_criteria"]) if gap else set(criteria)
    permitted_spans = {span_identity(s) for s in gap["source_spans"]} if gap else None
    ids, covered, selected = set(), set(), set()
    for job in value["jobs"]:
        shape(job, {"job_id", "purpose", "criterion_ids", "selected_spans"}, "LOOP_JOB_INVALID")
        name = job["job_id"]
        require(isinstance(name, str) and re.fullmatch(r"[a-z][a-z0-9_-]{0,55}", name)
                is not None and name != "critic" and name not in ids, "LOOP_JOB_ID_INVALID")
        ids.add(name)
        text(job["purpose"], 2000, "LOOP_PURPOSE_REQUIRED")
        assigned = job["criterion_ids"]
        require(isinstance(assigned, list) and bool(assigned)
                and all(isinstance(k, str) and k in expected for k in assigned)
                and len(set(assigned)) == len(assigned), "LOOP_CRITERIA_INVALID")
        covered.update(assigned)
        spans = job["selected_spans"]
        require(isinstance(spans, list) and 1 <= len(spans) <= 32, "LOOP_CONTEXT_REQUIRED")
        seen = set()
        for span in spans:
            sources.span(span)
            identity = span_identity(span)
            require(identity not in seen, "LOOP_CONTEXT_DUPLICATE")
            require(permitted_spans is None or identity in permitted_spans, "LOOP_REPAIR_SCOPE")
            seen.add(identity)
        selected.update(seen)
    require(covered == expected, "LOOP_PLAN_COVERAGE")
    if gap:
        require(selected == permitted_spans, "LOOP_GAP_COVERAGE")
    return json.loads(canonical(value))


def validate_critic(value, payload, reports, *, view, plan_digest, round_index,
                    repaired_criteria=(), repair_jobs=()):
    shape(value, {"parent_input_digest", "plan_digest", "round", "report_digests", "validations"},
          "LOOP_CRITIC_INVALID")
    require(value["parent_input_digest"] == digest(payload) and value["plan_digest"] == plan_digest
            and type(value["round"]) is int and value["round"] == round_index, "LOOP_CRITIC_STALE")
    require(value["report_digests"] == {k: digest(v) for k, v in reports.items()}, "LOOP_CRITIC_STALE")
    expected, found, sources = loop_criteria(payload), set(), _Sources(payload)
    require(isinstance(value["validations"], list) and len(value["validations"]) == len(expected),
            "LOOP_CRITIC_COVERAGE")
    for item in value["validations"]:
        shape(item, {"criterion_id", "status", "evidence", "gap_reason", "source_spans"},
              "LOOP_CRITIC_CRITERION")
        name, status = item["criterion_id"], item["status"]
        require(isinstance(name, str) and name in expected and name not in found, "LOOP_CRITIC_COVERAGE")
        found.add(name)
        require(isinstance(status, str) and status in {"passed", "failed", "blocked", "not_run"},
                "LOOP_CRITIC_STATUS")
        refs = item["evidence"]
        require(isinstance(refs, list) and len(refs) <= 30, "LOOP_CRITIC_EVIDENCE")
        for ref in refs:
            shape(ref, {"job_id", "claim_index"}, "LOOP_CRITIC_EVIDENCE")
            job, index = ref["job_id"], ref["claim_index"]
            require(isinstance(job, str) and job in reports and type(index) is int
                    and 0 <= index < len(reports[job]["claims"]), "LOOP_CRITIC_EVIDENCE")
        spans = item["source_spans"]
        require(isinstance(spans, list) and len(spans) <= 32, "LOOP_CRITIC_GAP")
        for span in spans:
            sources.span(span)
            require(any(record["source_key"] == span["source_key"]
                        and record["source_revision"] == span["source_revision"]
                        and record["start"] <= span["start"] < span["end"] <= record["end"]
                        for record in view["spans"]), "LOOP_GAP_NOT_DELIVERED")
        if status == "passed":
            require(bool(refs) and item["gap_reason"] is None and not spans, "LOOP_CRITIC_EVIDENCE")
            if name == "I":
                require({ref["job_id"] for ref in refs} == set(reports), "LOOP_COMPARISON_REQUIRED")
            if name in repaired_criteria:
                require(any(ref["job_id"] in repair_jobs for ref in refs), "LOOP_REPAIR_EVIDENCE_REQUIRED")
        else:
            text(item["gap_reason"], 1000, "LOOP_CRITIC_GAP")
            require(status != "failed" or bool(spans), "LOOP_CRITIC_GAP")
    return json.loads(canonical(value))


def verified_gap(critic, *, critic_job_id, critic_result_digest):
    """Only a fully run critic with actual failures permits another frontier."""
    statuses = {item["status"] for item in critic["validations"]}
    if "failed" not in statuses or statuses.intersection({"blocked", "not_run"}):
        return None
    failed = [item for item in critic["validations"] if item["status"] == "failed"]
    spans = {span_identity(span): span for item in failed for span in item["source_spans"]}
    return {"parent_input_digest": critic["parent_input_digest"], "plan_digest": critic["plan_digest"],
            "critic_job_id": critic_job_id, "critic_result_digest": critic_result_digest,
            "failed_criteria": [item["criterion_id"] for item in failed],
            "source_spans": list(spans.values()), "validations": failed}


def integration_candidate(payload, reports, critic, critic_digest, *, stop_reason):
    """Deterministic evidence assembly, awaiting owner review and adoption."""
    refs = {(ref["job_id"], ref["claim_index"]) for item in critic["validations"]
            if item["status"] == "passed" for ref in item["evidence"]}
    passed = all(item["status"] == "passed" for item in critic["validations"])
    return {"kind": "integrated_candidate", "status": "needs_owner_review" if passed else "unresolved",
            "task_id": payload["task_id"], "revision": payload["revision"],
            "parent_input_digest": digest(payload), "final_critic_digest": critic_digest,
            "claims": [{"job_id": job, "claim_index": index, "claim": reports[job]["claims"][index]}
                       for job, index in sorted(refs)],
            "conflicts": [{"job_id": job, "text": conflict} for job, report in reports.items()
                          for conflict in report["conflicts"]],
            "validations": critic["validations"], "stop_reason": stop_reason,
            "owner_accepted": False, "model_runtime_verified": False}


def learning_candidate(candidate):
    require(candidate["status"] == "needs_owner_review", "LOOP_LEARNING_UNVERIFIED")
    return {"kind": "learning_candidate", "status": "unadopted",
            "task_id": candidate["task_id"], "revision": candidate["revision"],
            "parent_input_digest": candidate["parent_input_digest"],
            "integrated_candidate_digest": digest(candidate),
            "final_critic_digest": candidate["final_critic_digest"], "claims": candidate["claims"],
            "requires_owner_adoption": True, "next_context_eligible": False}
