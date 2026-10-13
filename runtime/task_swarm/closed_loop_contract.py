"""Pure contracts for a bounded, owner-bound research repair round.

Plans are supplied data, not generated authority. This first slice admits a
finite parallel frontier followed by a critic, and at most one repair frontier.
"""
from __future__ import annotations

import hashlib
import json
import re

from .closed_loop_context import derive_child_view, validate_child_view
from .protocol import canonical, digest, digest_ref
from .task_contract import require, shape, text, validate_report
from .task_planning import _Sources, objective_criteria
from .repair_planning import PROFILE_FIELDS, profile, make_impact, file_sha


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


def work_input(payload, job, round_index, initial_digest, *, round_plan_digest, previous=None):
    """One construction for execution and evidence readback; no implicit lookup."""
    job_id = f"r{round_index}-" + job["job_id"]
    return {"role": "work", "job_id": job_id, "round": round_index,
            "round_plan_digest": round_plan_digest, "purpose": job["purpose"],
            "criterion_ids": job["criterion_ids"],
            "criteria": {key: loop_criteria(payload)[key] for key in job["criterion_ids"]},
            "view": derive_child_view(payload, job_id, job["selected_spans"],
                plan_digest=initial_digest, previous_critic_digest=previous)}


def evidence_version(runtime_plan, initial_template):
    """Read policy only after binding the template to the immutable runtime plan.

    Callers must first compare runtime_plan with the existing DB snapshot. This
    pure helper cannot authenticate a filesystem or grant owner authority.
    """
    require(isinstance(runtime_plan, dict) and isinstance(initial_template, dict), "LOOP_EVIDENCE_POLICY")
    jobs = runtime_plan.get("jobs")
    require(isinstance(jobs, list) and all(isinstance(job, dict) for job in jobs), "LOOP_EVIDENCE_POLICY")
    critics = [job for job in jobs if job.get("job_id") == "r0-critic"]
    require(len(critics) == 1 and critics[0].get("kind") == "review"
            and critics[0].get("payload_digest") == digest(initial_template), "LOOP_EVIDENCE_POLICY")
    version = initial_template.get("evidence_contract_version", 1)
    require(type(version) is int and version in (1, 2), "LOOP_EVIDENCE_POLICY")
    require((version == 2) == ("required_evidence_jobs" in initial_template)
            and (version == 2 or "evidence_contract_version" not in initial_template), "LOOP_EVIDENCE_POLICY")
    keys = {"role", "job_id", "round", "round_plan_digest", "criteria", "view"}
    planning = profile(initial_template)
    require(planning is None or (version == 2 and initial_template["repair_impact_sha256"] is None),
            "LOOP_REPAIR_PROFILE")
    shape(initial_template, keys | (PROFILE_FIELDS if planning else set()) | ({"evidence_contract_version", "required_evidence_jobs"} if version == 2 else set()),
          "LOOP_EVIDENCE_POLICY")
    require(initial_template["role"] == "critic" and initial_template["job_id"] == "r0-critic"
            and type(initial_template["round"]) is int and initial_template["round"] == 0,
            "LOOP_EVIDENCE_POLICY")
    return version


def required_evidence_jobs(payload, initial_specification, repair_specification=None, *, gap=None):
    """Derive all assigned leaves and admitted repair influence, never a result mapping.

    A direct plan supplies assignments only. Source/root all_of completeness is
    established by the separate source-bound initial planner, not inferred here.
    """
    initial = validate_plan(initial_specification, payload)
    leaves = {key: {"r0-" + job["job_id"] for job in initial["jobs"] if key in job["criterion_ids"]}
              for key in loop_criteria(payload)}
    all_leaves = {"r0-" + job["job_id"] for job in initial["jobs"]}
    common = {key for key in leaves if key in {"R", "S", "U", "I"} or key.startswith(("O", "Q"))}
    require(all(leaves[key] == all_leaves for key in common), "LOOP_COMMON_CRITERIA_COVERAGE")
    result = {key: set(value) for key, value in leaves.items()}
    if repair_specification is not None:
        require(gap is not None, "LOOP_REPAIR_BINDING_REQUIRED")
        repair = validate_plan(repair_specification, payload, gap=gap)
        for job in repair["jobs"]:
            affected = set().union(*(leaves[key] for key in job["criterion_ids"]))
            for key in result:
                if affected.intersection(leaves[key]):
                    result[key].add("r1-" + job["job_id"])
    return {key: sorted(value) for key, value in result.items()}


def _check_work_inputs(payload, initial, repair, inputs, scheduled, initial_digest, previous):
    require(isinstance(inputs, dict), "LOOP_WORK_BINDING")
    for index, spec in enumerate([initial] + ([repair] if repair is not None else [])):
        for job in spec["jobs"]:
            expected = work_input(payload, job, index, initial_digest, round_plan_digest=digest(spec),
                                  previous=previous if index else None)
            name = expected["job_id"]
            require(name in inputs and name in scheduled and canonical(inputs[name]) == canonical(expected)
                    and scheduled[name]["kind"] == "work"
                    and scheduled[name]["payload_digest"] == digest(expected), "LOOP_WORK_BINDING")


def _planned_reports(reports, expected_jobs, round_index):
    require(type(round_index) is int and round_index in (0, 1), "LOOP_CRITIC_STALE")
    require(isinstance(expected_jobs, (list, tuple, set, frozenset))
            and 1 <= len(expected_jobs) <= 6, "LOOP_REPORT_SET")
    require(all(isinstance(job, str) and re.fullmatch(r"r[01]-[a-z][a-z0-9_-]{0,55}", job)
                and job not in {"r0-critic", "r1-critic"} for job in expected_jobs), "LOOP_REPORT_SET")
    jobs = set(expected_jobs)
    require(len(jobs) == len(expected_jobs) and isinstance(reports, dict)
            and set(reports) == jobs, "LOOP_REPORT_SET")
    first = {job for job in jobs if job.startswith("r0-")}
    repair = jobs - first
    require(1 <= len(first) <= 3 and (1 <= len(repair) <= 3 if round_index else not repair),
            "LOOP_REPORT_SET")
    return first, repair


def _critic_dispatch(payload, reports, view, plan_digest, round_index,
                     dispatched_input, dispatched_input_digest, previous, round_plan_digest):
    digest_ref(dispatched_input_digest)
    require(isinstance(dispatched_input, dict) and digest(dispatched_input) == dispatched_input_digest,
            "LOOP_CRITIC_DISPATCH_MISMATCH")
    job = f"r{round_index}-critic"
    require(dispatched_input.get("role") == "critic" and dispatched_input.get("job_id") == job
            and type(dispatched_input.get("round")) is int and dispatched_input["round"] == round_index
            and dispatched_input.get("round_plan_digest") == round_plan_digest
            and canonical(dispatched_input.get("criteria")) == canonical(loop_criteria(payload))
            and canonical(dispatched_input.get("view")) == canonical(view)
            and canonical(dispatched_input.get("reports")) == canonical(reports)
            and dispatched_input.get("report_digests") == {k: digest(v) for k, v in reports.items()},
            "LOOP_CRITIC_DISPATCH_MISMATCH")
    template = {k: v for k, v in dispatched_input.items()
                if k not in {"template_digest", "reports", "report_digests"}}
    require(dispatched_input.get("template_digest") == digest(template), "LOOP_CRITIC_DISPATCH_MISMATCH")
    validate_child_view(view, payload, job_id=job, plan_digest=plan_digest,
                        previous_critic_digest=previous)


def _prior_repair(payload, reports, plan_digest, initial_execution_plan_digest,
                  first_jobs, repair_jobs, prior_review, admission, policy):
    require(prior_review is not None and admission is not None, "LOOP_REPAIR_BINDING_REQUIRED")
    shape(prior_review, {"response", "dispatched_input", "dispatched_input_digest"}, "LOOP_REPAIR_BINDING")
    shape(admission, {"round", "initial_plan_digest", "critic_job_id", "critic_result_digest",
                      "proposal_digest", "jobs"}, "LOOP_REPAIR_BINDING")
    response, previous = prior_review["response"], prior_review["dispatched_input"]
    shape(response, {"result", "receipt"}, "LOOP_REPAIR_BINDING")
    require(isinstance(previous, dict) and isinstance(response["receipt"], dict)
            and response["receipt"].get("input_digest") == prior_review["dispatched_input_digest"],
            "LOOP_REPAIR_BINDING")
    prior = validate_critic(response["result"], payload, previous.get("reports"),
        view=previous.get("view"), plan_digest=plan_digest, round_index=0,
        initial_execution_plan_digest=initial_execution_plan_digest,
        expected_jobs=first_jobs, dispatched_input=previous,
        dispatched_input_digest=prior_review["dispatched_input_digest"], **policy)
    # Execution artifacts use write_json's canonical JSON plus one LF. This is
    # the stored result-artifact hash, not the canonical object/input digest.
    previous_digest = hashlib.sha256((canonical(response) + "\n").encode("utf-8")).hexdigest()
    gap = verified_gap(prior, critic_job_id="r0-critic", critic_result_digest=previous_digest)
    require(gap is not None and type(admission["round"]) is int and admission["round"] == 1
            and admission["critic_job_id"] == "r0-critic"
            and admission["critic_result_digest"] == previous_digest
            and admission["initial_plan_digest"] == initial_execution_plan_digest, "LOOP_REPAIR_BINDING")
    digest_ref(admission["initial_plan_digest"])
    digest_ref(admission["proposal_digest"])
    jobs = admission["jobs"]
    require(isinstance(jobs, list) and len(jobs) == len(repair_jobs) + 1, "LOOP_REPAIR_BINDING")
    for job in jobs:
        shape(job, {"job_id", "kind", "dependencies", "exclusive_keys", "payload_ref", "payload_digest"},
              "LOOP_REPAIR_BINDING")
        require(isinstance(job["job_id"], str) and isinstance(job["kind"], str)
                and isinstance(job["dependencies"], list)
                and all(isinstance(dependency, str) for dependency in job["dependencies"]),
                "LOOP_REPAIR_BINDING")
    work = [job for job in jobs if job["kind"] == "work"]
    review = [job for job in jobs if job["kind"] == "review"]
    require(len(work) == len(repair_jobs) and {job["job_id"] for job in work} == repair_jobs
            and len(review) == 1 and review[0]["job_id"] == "r1-critic"
            and isinstance(review[0]["dependencies"], list)
            and len(review[0]["dependencies"]) == len(first_jobs | repair_jobs)
            and set(review[0]["dependencies"]) == first_jobs | repair_jobs, "LOOP_REPAIR_BINDING")
    require(all(canonical(reports[job]) == canonical(previous["reports"][job]) for job in first_jobs),
            "LOOP_PRIOR_REPORT_CHANGED")
    return set(gap["failed_criteria"]), previous_digest, admission["proposal_digest"]


def validate_critic(value, payload, reports, *, view, plan_digest, round_index,
                    initial_execution_plan_digest, expected_jobs, dispatched_input, dispatched_input_digest,
                    initial_specification, initial_runtime_plan, initial_template, work_inputs,
                    repair_specification=None, prior_review=None, repair_admission=None,
                    repair_impact=None, execution_snapshot=None):
    """Validate all planned reports against a stored critic dispatch.

    Expected jobs and dispatch digests come from the coordinator's immutable
    plan/accepted extension and saved dispatch map, never from ``reports``.
    ``plan_digest`` binds the supplied objective plan; the separate execution
    plan digest binds the owner/budget/job ledger used to admit the repair.
    Round one revalidates the prior review and derives every failed criterion;
    callers cannot disable repair checks with an empty or incomplete set.
    This checks evidence consistency, not actor authority or filesystem origin.
    """
    digest_ref(plan_digest)
    digest_ref(initial_execution_plan_digest)
    first_jobs, repair_jobs = _planned_reports(reports, expected_jobs, round_index)
    require(digest(initial_runtime_plan) == initial_execution_plan_digest, "LOOP_EVIDENCE_POLICY")
    version = evidence_version(initial_runtime_plan, initial_template)
    policy = dict(initial_specification=initial_specification, initial_runtime_plan=initial_runtime_plan,
                  initial_template=initial_template, work_inputs=work_inputs)
    require(isinstance(dispatched_input, dict), "LOOP_CRITIC_DISPATCH_MISMATCH")
    required = None
    repaired_criteria, previous, round_plan = set(), None, plan_digest
    if round_index:
        repaired_criteria, previous, round_plan = _prior_repair(payload, reports, plan_digest, initial_execution_plan_digest,
            first_jobs, repair_jobs, prior_review, repair_admission, policy)
    else:
        require(prior_review is None and repair_admission is None and repair_specification is None,
                "LOOP_REPAIR_BINDING")
    if version == 2:
        initial = validate_plan(initial_specification, payload)
        require(digest(initial) == plan_digest
                and {"r0-" + job["job_id"] for job in initial["jobs"]} == first_jobs, "LOOP_WORK_BINDING")
        gap = verified_gap(prior_review["response"]["result"], critic_job_id="r0-critic",
                           critic_result_digest=previous) if round_index else None
        if round_index:
            require(repair_specification is not None and digest(repair_specification) == round_plan,
                    "LOOP_REPAIR_BINDING")
            repair_specification = validate_plan(repair_specification, payload, gap=gap)
            require({"r1-" + job["job_id"] for job in repair_specification["jobs"]} == repair_jobs,
                    "LOOP_WORK_BINDING")
        required = required_evidence_jobs(payload, initial, repair_specification if round_index else None, gap=gap)
        scheduled = {job["job_id"]: job for job in [*initial_runtime_plan["jobs"],
                     *(repair_admission["jobs"] if round_index else [])]}
        require({j for j, item in scheduled.items() if item["kind"] == "work"} == first_jobs | repair_jobs,
                "LOOP_WORK_BINDING")
        current_template = {key: value for key, value in dispatched_input.items()
                            if key not in {"template_digest", "reports", "report_digests"}}
        shape(current_template, set(initial_template), "LOOP_EVIDENCE_POLICY")
        require(scheduled[f"r{round_index}-critic"]["payload_digest"] == digest(current_template),
                "LOOP_EVIDENCE_POLICY")
        _check_work_inputs(payload, initial, repair_specification if round_index else None,
                           work_inputs, scheduled, plan_digest, previous)
        require(dispatched_input.get("evidence_contract_version") == 2
                and canonical(dispatched_input.get("required_evidence_jobs")) == canonical(required),
                "LOOP_EVIDENCE_POLICY")
        planning = profile(initial_template)
        require(profile(current_template) == planning, "LOOP_REPAIR_PROFILE")
        if planning:
            expected_sha = None
            if round_index:
                require(repair_impact is not None and execution_snapshot is not None, "LOOP_REPAIR_IMPACT_REQUIRED")
                proposed, expected_impact = make_impact(payload, initial, initial_runtime_plan,
                                                       prior_review, work_inputs, execution_snapshot)
                require(canonical(proposed) == canonical(repair_specification)
                        and canonical(expected_impact) == canonical(repair_impact), "LOOP_REPAIR_IMPACT_MISMATCH")
                expected_sha = file_sha(expected_impact)
            require(current_template.get("repair_impact_sha256") == expected_sha, "LOOP_REPAIR_IMPACT_MISMATCH")
    else:
        require("evidence_contract_version" not in dispatched_input
                and "required_evidence_jobs" not in dispatched_input, "LOOP_EVIDENCE_POLICY")
    _critic_dispatch(payload, reports, view, plan_digest, round_index, dispatched_input,
                     dispatched_input_digest, previous, round_plan)
    for job, report in reports.items():
        validate_report(report, job, payload, allowed_jobs=expected_jobs)
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
        if required is not None:
            pairs = [(ref["job_id"], ref["claim_index"]) for ref in refs]
            referenced = {ref["job_id"] for ref in refs}
            require(len(pairs) == len(set(pairs)) and referenced <= set(required[name]),
                    "LOOP_CRITIC_ASSIGNMENT")
            if status == "passed":
                require(referenced == set(required[name]), "LOOP_CRITIC_ASSIGNMENT")
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
            "conflicts": [{"job_id": job, "text": conflict} for job, report in sorted(reports.items())
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
