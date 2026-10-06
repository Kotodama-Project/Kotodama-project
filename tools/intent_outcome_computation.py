"""Deterministic candidate arithmetic over an admitted, declared snapshot.

No file, process, network, clock, adoption, grant or knowledge writes. The caller
must validate the closed snapshot schema and bind this exact source artifact.
"""
from datetime import datetime, timezone
import hashlib
import json

VERSION = "kotodama.intent-outcome-computation/v1"
PARAMETERS = ("metric_id", "window_start", "window_end", "exclusion_mode")


class MetricRefused(ValueError):
    pass


def digest(value):
    encoded=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def instant(value):
    result=datetime.fromisoformat(value.replace("Z","+00:00"))
    if result.tzinfo is None:
        raise MetricRefused("METRIC_TIMEZONE_REQUIRED")
    return result.astimezone(timezone.utc)


def evaluate(snapshot):
    """Count due admitted cases; an artifact or KPI proxy is never completion."""
    parameters=snapshot["parameters"]
    if set(parameters)!=set(PARAMETERS) or parameters["metric_id"]!="KGI-INTENT":
        raise MetricRefused("METRIC_PARAMETERS_INVALID")
    start,end=instant(parameters["window_start"]),instant(parameters["window_end"])
    if end<=start or parameters["exclusion_mode"] not in {"none","receipted_withdrawal_or_cancel"}:
        raise MetricRefused("METRIC_WINDOW_OR_POLICY_INVALID")
    cases=snapshot["cases"]
    if len(cases)>1024:
        raise MetricRefused("METRIC_CASE_LIMIT")
    # A snapshot has one current row per admitted intent, not one row per
    # artifact, revision, agent, PR, review, or receipt.
    for field in ("case_ref","intent_ref","intent_revision_ref"):
        values=[case[field] for case in cases]
        if len(set(values))!=len(values):
            raise MetricRefused("METRIC_DUPLICATE_CASE_OR_INTENT")
    outcomes=[case["outcome"]["ref"] for case in cases if case["outcome"] is not None]
    if len(set(outcomes))!=len(outcomes):
        raise MetricRefused("METRIC_OUTCOME_REUSED")
    receipts={}
    for case in cases:
        for key in ("intent_review","work","verification","acceptance","learning","exclusion"):
            item=case[key]
            if item is None:
                continue
            ref=item["receipt_ref"];value=digest(item)
            if ref in receipts and receipts[ref]!=value:
                raise MetricRefused("METRIC_RECEIPT_BINDING_CONFLICT")
            receipts[ref]=value

    admitted_due,excluded,numerator,denominator,outside,review=[],[],[],[],[],[]
    violations=[];reason_counts={}
    def reason(code):
        reason_counts[code]=reason_counts.get(code,0)+1

    for case in sorted(cases,key=lambda item:item["case_ref"]):
        identifier=case["case_ref"]
        violations.extend((identifier,value) for value in case["violations"])
        if case["admitted"] and case["admitted_at"] is None:
            raise MetricRefused("METRIC_ADMISSION_TIME_MISSING")
        admitted=case["admitted"] and instant(case["admitted_at"])<=end
        if not admitted or not start<=instant(case["due_at"])<end:
            outside.append(identifier)
            continue
        admitted_due.append(identifier)
        if case["kpi_change"]=="improved" and case["outcome_change"]!="improved":
            review.append(identifier);reason("KPI_WITHOUT_OUTCOME_IMPROVEMENT")
        exclusion=case["exclusion"]
        terminal=case["state"] in {"withdrawn","cancelled"}
        valid_exclusion=bool(terminal and exclusion and exclusion["action"]==case["state"]
            and exclusion["owner_ref"]==case["owner_ref"] and exclusion["intent_revision_ref"]==case["intent_revision_ref"]
            and instant(case["admitted_at"])<=instant(exclusion["recorded_at"])<=end)
        if parameters["exclusion_mode"]=="receipted_withdrawal_or_cancel" and valid_exclusion:
            excluded.append(identifier)
            continue
        denominator.append(identifier)
        if terminal:
            reason("TERMINAL_CASE_NOT_EXCLUDED")
            if not valid_exclusion:
                review.append(identifier)
            continue
        if case["state"]!="completed":
            reason("OUTCOME_INCOMPLETE")
            continue
        if any(case[key] is None for key in ("source","intent_review","work","outcome","verification","acceptance","learning")):
            reason("OUTCOME_EVIDENCE_MISSING")
            continue
        source,intent,work,outcome,verification,acceptance,learning=(case[key] for key in
            ("source","intent_review","work","outcome","verification","acceptance","learning"))
        revision=case["intent_revision_ref"];request=case["request_sha256"]
        policy_refs=[acceptance[key] for key in ("policy_ref","policy_revision_ref","policy_adoption_receipt_ref")]
        acceptance_bound=(all(value is None for value in policy_refs) if acceptance["mode"]=="owner" else all(value is not None for value in policy_refs))
        bindings=(intent["intent_ref"]==case["intent_ref"] and intent["intent_revision_ref"]==revision
            and intent["source_ref"]==source["ref"] and intent["source_revision_ref"]==source["revision_ref"] and intent["source_sha256"]==source["sha256"]
            and intent["request_sha256"]==request and work["intent_revision_ref"]==revision and work["request_sha256"]==request
            and work["scope_matched"] is True and outcome["request_sha256"]==request
            and verification["outcome_sha256"]==outcome["sha256"] and verification["intent_revision_ref"]==revision
            and verification["reviewer_ref"]!=work["executor_ref"] and verification["verdict"]=="pass"
            and acceptance["owner_ref"]==case["owner_ref"] and acceptance["outcome_sha256"]==outcome["sha256"]
            and acceptance["request_sha256"]==request and acceptance["verdict"]=="accepted"
            and acceptance["requested_outcome_met"] is True and acceptance_bound
            and learning["intent_revision_ref"]==revision and learning["disposition"]=="retained")
        chronology=(instant(case["admitted_at"])<=instant(intent["reviewed_at"])<=instant(work["started_at"])
            and instant(work["grant_issued_at"])<=instant(work["started_at"])<instant(work["grant_expires_at"])
            and instant(work["started_at"])<=instant(verification["verified_at"])<=instant(acceptance["accepted_at"])
            <=instant(learning["recorded_at"])<=end)
        if not bindings or not chronology:
            reason("OUTCOME_EVIDENCE_BINDING_OR_TIME")
            continue
        if case["violations"]:
            reason("OUTCOME_BOUNDARY_VIOLATION")
            continue
        numerator.append(identifier)

    guardrail="FAIL" if violations else "NO_REPORTED_VIOLATION"
    disposition="HARD_GUARDRAIL_FAILURE" if violations else "REVIEW_REQUIRED" if review else "NOT_MEASURED" if not denominator else "CANDIDATE_ONLY"
    groups={"admitted_due":admitted_due,"numerator":numerator,"denominator":denominator,"excluded":excluded,"outside_window_or_unadmitted":outside,"review_required":sorted(set(review))}
    return {"metric_id":"KGI-INTENT","computation_version":VERSION,"parameters":dict(parameters),
        "counts":{key:len(values) for key,values in groups.items()},"id_set_sha256":{key:digest(sorted(values)) for key,values in groups.items()},
        "ratio":None if not denominator else {"numerator":len(numerator),"denominator":len(denominator)},
        "reason_counts":dict(sorted(reason_counts.items())),"guardrail":guardrail,"violation_count":len(violations),
        "violation_set_sha256":digest(sorted(violations)),"disposition":disposition,
        "measurement_form_adopted":False,"evidence_authenticity":"UNVERIFIED","coverage_authenticity":"UNVERIFIED",
        "baseline":"unknown","target":"not_adopted","deadline":"not_adopted","measurement_policy_adopted":False,
        "authority_granted":False,"current_truth_changed":False,"public_beta_go":False,"final_human_go":False}
