"""Closed two-leaf prerequisite contracts; no owner or storage authority."""
from __future__ import annotations

from .protocol import canonical, digest
from .task_contract import require, shape

EXECUTION_FIELDS = {"execution_contract_version", "dependency_descriptor_sha256"}
DELIVERY_FIELDS = {"release_certificate", "release_certificate_sha256"}
REVIEW_ID = "r0-prerequisite"


def execution_version(plan):
    fields = EXECUTION_FIELDS.intersection(plan)
    if not fields:
        return None
    require(fields == EXECUTION_FIELDS and type(plan["execution_contract_version"]) is int
            and plan["execution_contract_version"] == 3, "LOOP_DEPENDENCY_POLICY")
    from .protocol import digest_ref
    digest_ref(plan["dependency_descriptor_sha256"])
    return 3


def roles(spec):
    require(spec.get("version") == 2 and len(spec["jobs"]) == 2, "LOOP_DEPENDENCY_PLAN")
    first = [job for job in spec["jobs"] if job["requires"] == []]
    require(len(first) == 1, "LOOP_DEPENDENCY_PLAN")
    second = [job for job in spec["jobs"] if job is not first[0]]
    require(second[0]["requires"] == [first[0]["job_id"]], "LOOP_DEPENDENCY_PLAN")
    return first[0], second[0]


def descriptor(payload, spec):
    from .closed_loop_contract import required_evidence_jobs, work_input
    from .closed_loop_context import derive_child_view
    a, b = roles(spec)
    aid, bid = "r0-" + a["job_id"], "r0-" + b["job_id"]
    gate = sorted(key for key, jobs in required_evidence_jobs(payload, spec).items()
                  if key.startswith("A") and jobs == [aid])
    require(gate, "LOOP_PREREQUISITE_GATE_EMPTY")
    initial = digest(spec)
    core = {"kind": "prerequisite_review", "version": 1, "role": "prerequisite_review",
            "job_id": REVIEW_ID, "round": 0, "gate": gate,
            "view": derive_child_view(payload, REVIEW_ID, a["selected_spans"], plan_digest=initial)}
    b_input = work_input(payload, b, 0, initial, round_plan_digest=initial)
    value = {"version": 1, "a_job_id": aid, "b_job_id": bid, "gate": gate,
             "b_template_digest": digest(b_input), "review_core_digest": digest(core)}
    envelope = {"core": core, "core_digest": digest(core), "descriptor_sha256": digest(value)}
    return value, envelope


def check_descriptor(payload, spec, plan, value, template):
    expected, review = descriptor(payload, spec)
    require(execution_version(plan) == 3 and value == expected and template == review
            and plan["dependency_descriptor_sha256"] == digest(expected), "LOOP_DEPENDENCY_POLICY")
    jobs = {job["job_id"]: job for job in plan["jobs"]}
    require(jobs[REVIEW_ID]["kind"] == "review"
            and jobs[REVIEW_ID]["payload_digest"] == digest(review)
            and jobs[REVIEW_ID]["dependencies"] == [expected["a_job_id"]], "LOOP_DEPENDENCY_POLICY")
    return expected


def review_input(template, report, report_sha):
    return {**template, "template_digest": digest(template), "report": report,
            "report_sha256": report_sha}


def validate_prerequisite(value, payload, spec, delivered, report, report_sha):
    from .closed_loop_context import validate_report_in_view
    expected, template = descriptor(payload, spec)
    require(delivered == review_input(template, report, report_sha), "LOOP_PREREQUISITE_INPUT")
    a = expected["a_job_id"]
    from .closed_loop_context import derive_child_view
    original = next(job for job in spec["jobs"] if "r0-" + job["job_id"] == a)
    view = derive_child_view(payload, a, original["selected_spans"], plan_digest=digest(spec))
    checked = validate_report_in_view(report, view, payload, allowed_jobs=[a])
    # Unsupported claims never become accepted prerequisite material, even if
    # a reviewer says passed. They remain report evidence in a blocked stage.
    supported = bool(checked["claims"]) and not checked["conflicts"] and all(
        claim["status"] == "supported" for claim in checked["claims"])
    shape(value, {"kind", "version", "descriptor_sha256", "report_sha256", "validations"},
          "LOOP_PREREQUISITE_REVIEW")
    require(value["kind"] == "prerequisite_review" and type(value["version"]) is int
            and value["version"] == 1 and value["descriptor_sha256"] == digest(expected)
            and value["report_sha256"] == report_sha, "LOOP_PREREQUISITE_REVIEW")
    require(isinstance(value["validations"], list)
            and len(value["validations"]) == len(expected["gate"]), "LOOP_PREREQUISITE_GATE")
    found, passed = set(), supported
    for item in value["validations"]:
        shape(item, {"criterion_id", "status", "evidence"}, "LOOP_PREREQUISITE_GATE")
        key = item["criterion_id"]
        require(key in expected["gate"] and key not in found
                and item["status"] in ("passed", "failed", "unknown"), "LOOP_PREREQUISITE_GATE")
        found.add(key)
        require(isinstance(item["evidence"], list) and len(item["evidence"]) <= 30,
                "LOOP_PREREQUISITE_EVIDENCE")
        indices = set()
        for ref in item["evidence"]:
            shape(ref, {"job_id", "claim_index"}, "LOOP_PREREQUISITE_EVIDENCE")
            index = ref["claim_index"]
            require(ref["job_id"] == a and type(index) is int and 0 <= index < len(checked["claims"])
                    and index not in indices, "LOOP_PREREQUISITE_EVIDENCE")
            indices.add(index)
        require(item["status"] != "passed" or bool(indices), "LOOP_PREREQUISITE_EVIDENCE")
        passed = passed and item["status"] == "passed"
    return passed


def dependent_input(template, stage, report):
    require(stage["status"] == "released", "LOOP_PREREQUISITE_BLOCKED")
    cert = stage["certificate"]
    return {**template, "prerequisite": {"report": report,
        "result_sha256": cert["a"]["result_digest"], "certificate": cert,
        "certificate_sha256": stage["certificate_sha256"]}}



def prerequisite_inputs(work_inputs):
    """Public critic view of the actual delivered dependency lane and its hash."""
    return {name: {"delivered_input_digest": digest(value), "prerequisite": value["prerequisite"]}
            for name, value in sorted(work_inputs.items()) if "prerequisite" in value}


def check_stage(stage, plan):
    shape(stage, {"version", "status", "certificate", "certificate_sha256", "actual_input_digest",
                  "accepted_at", "verification_ref"}, "LOOP_RELEASE_INVALID")
    cert = stage["certificate"]
    shape(cert, {"version", "run_id", "binding_digest", "initial_execution_plan_digest",
                 "descriptor_sha256", "progress_sha256", "owner_ref", "a_job_id", "b_job_id", "a", "review"}, "LOOP_RELEASE_INVALID")
    require(execution_version(plan) == 3 and type(stage["version"]) is int and stage["version"] == 1
            and type(cert["version"]) is int and cert["version"] == 1 and stage["status"] in ("released", "blocked")
            and cert["run_id"] == plan["run_id"] and cert["binding_digest"] == plan["binding_digest"]
            and cert["initial_execution_plan_digest"] == digest(plan)
            and cert["descriptor_sha256"] == plan["dependency_descriptor_sha256"]
            and stage["certificate_sha256"] == digest(cert), "LOOP_RELEASE_INVALID")
    from .protocol import digest_ref
    digest_ref(cert["progress_sha256"])
    jobs = {job["job_id"]: job for job in plan["jobs"]}
    require(cert["a_job_id"] in jobs and cert["b_job_id"] in jobs
            and jobs[cert["a_job_id"]]["kind"] == jobs[cert["b_job_id"]]["kind"] == "work"
            and jobs[cert["a_job_id"]]["dependencies"] == []
            and jobs[cert["b_job_id"]]["dependencies"] == [cert["a_job_id"]]
            and cert["a"]["job_id"] == cert["a_job_id"]
            and cert["review"]["job_id"] == REVIEW_ID, "LOOP_RELEASE_INVALID")
    for key in ("a", "review"):
        shape(cert[key], {"job_id", "token", "epoch", "attempt", "worker_ref", "identity",
                          "result_digest", "result_ref", "runtime_receipt_ref"}, "LOOP_RELEASE_INVALID")
    if stage["status"] == "released":
        from .protocol import digest_ref, timestamp
        digest_ref(stage["actual_input_digest"])
        timestamp(stage["accepted_at"])
        require(stage["verification_ref"] == "ref/loop/prerequisite/" + digest(cert), "LOOP_RELEASE_INVALID")
    else:
        require(stage["actual_input_digest"] is None and stage["accepted_at"] is None
                and stage["verification_ref"] is None, "LOOP_RELEASE_INVALID")
    return stage


def attempt_proof(attempt):
    return {key: attempt[key] for key in ("job_id", "token", "epoch", "attempt", "worker_ref", "identity",
                                          "result_digest", "result_ref", "runtime_receipt_ref")}
