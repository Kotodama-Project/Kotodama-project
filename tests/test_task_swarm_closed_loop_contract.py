"""Critic inputs are complete, dispatch-bound and derived from prior failures."""
import copy
import hashlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from task_swarm.closed_loop_context import derive_child_view
from task_swarm.closed_loop_contract import loop_criteria, validate_critic
from task_swarm.protocol import SwarmError, canonical, digest
from test_task_swarm_closed_loop_context import fixture, report, span


PLAN = "d" * 64


def artifact_digest(value):
    return hashlib.sha256((canonical(value) + "\n").encode()).hexdigest()


def dispatched(payload, reports, index=0, previous=None, selected=None):
    detail = payload["sources"][3]
    view = derive_child_view(payload, f"r{index}-critic",
        [span(detail, "必要な追加根拠です。")] if selected is None else selected,
        plan_digest=PLAN, previous_critic_digest=previous)
    template = {"role": "critic", "job_id": f"r{index}-critic", "round": index,
        "round_plan_digest": PLAN if index == 0 else "e" * 64,
        "criteria": loop_criteria(payload), "view": view}
    return {**template, "template_digest": digest(template), "reports": copy.deepcopy(reports),
            "report_digests": {job: digest(value) for job, value in reports.items()}}


def review(payload, reports, index=0, failed=()):
    detail = payload["sources"][3]
    return {"parent_input_digest": digest(payload), "plan_digest": PLAN, "round": index,
        "report_digests": {job: digest(value) for job, value in reports.items()},
        "validations": [{"criterion_id": key, "status": "failed" if key in failed else "passed",
            "evidence": [] if key in failed else [{"job_id": job, "claim_index": 0}
                                                  for job in reports],
            "gap_reason": "Missing the measured detail." if key in failed else None,
            "source_spans": [span(detail, "必要な追加根拠です。")] if key in failed else []}
            for key in loop_criteria(payload)]}


def scheduled(job_id, kind="work", dependencies=()):
    return {"job_id": job_id, "kind": kind, "dependencies": list(dependencies),
            "exclusive_keys": [], "payload_ref": "ref/" + job_id, "payload_digest": "f" * 64}


class ClosedLoopCriticContractTests(unittest.TestCase):
    def setUp(self):
        self.payload = fixture()
        self.reports = {job: report(self.payload, "必要な追加根拠です。", job=job)
                        for job in ("r0-a", "r0-b")}
        self.input = dispatched(self.payload, self.reports)
        self.value = review(self.payload, self.reports)
        self.options = {"view": self.input["view"], "plan_digest": PLAN, "round_index": 0,
                        "initial_execution_plan_digest": "a" * 64,
                        "expected_jobs": tuple(self.reports), "dispatched_input": self.input,
                        "dispatched_input_digest": digest(self.input)}

    def check(self, value=None, reports=None, **changes):
        options = {**self.options, **changes}
        return validate_critic(self.value if value is None else value, self.payload,
                               self.reports if reports is None else reports, **options)

    def refuses(self, code, function):
        with self.assertRaises(SwarmError) as raised:
            function()
        self.assertEqual(raised.exception.code, code)

    def second_round(self):
        prior = review(self.payload, self.reports, failed=("R", "A1"))
        response = {"result": prior, "receipt": {"input_digest": digest(self.input),
            "actor_ref": "verifier", "invocation_ref": "prior-review", "synthetic": True}}
        self.prior = {"response": response, "dispatched_input": copy.deepcopy(self.input),
                      "dispatched_input_digest": digest(self.input)}
        self.admission = {"round": 1, "initial_plan_digest": "a" * 64,
            "critic_job_id": "r0-critic", "critic_result_digest": artifact_digest(response),
            "proposal_digest": "e" * 64, "jobs": [scheduled("r1-repair"),
                scheduled("r1-critic", "review", [*self.reports, "r1-repair"])]}
        self.reports["r1-repair"] = report(self.payload, "必要な追加根拠です。", job="r1-repair")
        self.input = dispatched(self.payload, self.reports, 1, artifact_digest(response))
        self.value = review(self.payload, self.reports, 1)
        self.options.update(view=self.input["view"], round_index=1,
            expected_jobs=tuple(self.reports), dispatched_input=self.input,
            dispatched_input_digest=digest(self.input), prior_review=self.prior,
            repair_admission=self.admission)

    def test_complete_first_round_is_valid(self):
        self.assertEqual(self.check(), self.value)

    def test_omitted_planned_report_cannot_be_hidden_by_matching_subset_digests(self):
        reports = {"r0-a": self.reports["r0-a"]}
        value = review(self.payload, reports)
        delivered = dispatched(self.payload, reports)
        self.refuses("LOOP_REPORT_SET", lambda: self.check(value, reports,
            view=delivered["view"], dispatched_input=delivered, dispatched_input_digest=digest(delivered)))

    def test_extra_unplanned_report_is_refused(self):
        reports = {**self.reports, "r0-extra": report(self.payload, "必要な追加根拠です。", job="r0-extra")}
        delivered = dispatched(self.payload, reports)
        self.refuses("LOOP_REPORT_SET", lambda: self.check(review(self.payload, reports), reports,
            dispatched_input=delivered, dispatched_input_digest=digest(delivered)))

    def test_second_round_uses_every_actual_prior_failure(self):
        self.second_round()
        self.assertEqual(self.check(), self.value)
        for criterion in ("R", "A1"):
            with self.subTest(criterion=criterion):
                value = copy.deepcopy(self.value)
                next(v for v in value["validations"] if v["criterion_id"] == criterion)["evidence"] = [
                    {"job_id": "r0-a", "claim_index": 0}]
                self.refuses("LOOP_REPAIR_EVIDENCE_REQUIRED", lambda: self.check(value))

    def test_second_round_cannot_omit_previous_review_or_admission(self):
        self.second_round()
        for key in ("prior_review", "repair_admission"):
            with self.subTest(key=key):
                self.refuses("LOOP_REPAIR_BINDING_REQUIRED", lambda: self.check(**{key: None}))

    def test_second_round_cannot_omit_an_admitted_repair_job(self):
        self.second_round()
        self.admission["jobs"].insert(0, scheduled("r1-unreported"))
        self.refuses("LOOP_REPAIR_BINDING", self.check)

    def test_second_round_cannot_bind_an_old_job_as_repair(self):
        self.second_round()
        self.admission["jobs"][0]["job_id"] = "r0-a"
        self.refuses("LOOP_REPAIR_BINDING", self.check)

    def test_second_round_requires_the_exact_prior_response_digest(self):
        self.second_round()
        self.admission["critic_result_digest"] = "b" * 64
        self.refuses("LOOP_REPAIR_BINDING", self.check)

    def test_repair_admission_must_belong_to_the_initial_execution_plan(self):
        self.second_round()
        self.admission["initial_plan_digest"] = "b" * 64
        self.refuses("LOOP_REPAIR_BINDING", self.check)

    def test_prior_report_cannot_be_replaced_in_the_second_round(self):
        self.second_round()
        self.reports["r0-a"]["conflicts"].append("Previously unreported disagreement.")
        self.value = review(self.payload, self.reports, 1)
        self.input = dispatched(self.payload, self.reports, 1, artifact_digest(self.prior["response"]))
        self.refuses("LOOP_PRIOR_REPORT_CHANGED", lambda: self.check(view=self.input["view"],
            dispatched_input=self.input, dispatched_input_digest=digest(self.input)))

    def test_changed_critic_view_metadata_is_rejected_before_gap_use(self):
        value = review(self.payload, self.reports, failed=("R",))
        for field, replacement in (("parent_input_digest", "b" * 64),
                                   ("plan_digest", "b" * 64), ("job_id", "r0-other"),
                                   ("view_digest", "b" * 64), ("version", True)):
            with self.subTest(field=field):
                view = copy.deepcopy(self.input["view"])
                view[field] = replacement
                with self.assertRaises(SwarmError):
                    self.check(value, view=view)

    def test_self_consistent_but_undispatched_view_cannot_authorize_a_gap(self):
        hidden = span(self.payload["sources"][3], "UNSELECTED-DETAIL")
        view = derive_child_view(self.payload, "r0-critic", [hidden], plan_digest=PLAN)
        value = review(self.payload, self.reports, failed=("R",))
        next(v for v in value["validations"] if v["criterion_id"] == "R")["source_spans"] = [hidden]
        self.refuses("LOOP_CRITIC_DISPATCH_MISMATCH", lambda: self.check(value, view=view))

    def test_changing_both_view_and_dispatch_still_requires_saved_dispatch_digest(self):
        view = copy.deepcopy(self.input["view"])
        view["job_id"] = "r0-other"
        view["view_digest"] = digest({k: v for k, v in view.items() if k != "view_digest"})
        delivered = copy.deepcopy(self.input)
        delivered["view"] = view
        self.refuses("LOOP_CRITIC_DISPATCH_MISMATCH", lambda: self.check(view=view, dispatched_input=delivered))

    def test_delivered_proper_subspan_remains_a_valid_gap(self):
        value = review(self.payload, self.reports, failed=("R",))
        next(v for v in value["validations"] if v["criterion_id"] == "R")["source_spans"] = [
            span(self.payload["sources"][3], "追加根拠")]
        self.assertEqual(self.check(value), value)

    def test_expected_job_set_is_required_and_cannot_be_empty_or_duplicated(self):
        options = {key: value for key, value in self.options.items() if key != "expected_jobs"}
        with self.assertRaises(TypeError):
            validate_critic(self.value, self.payload, self.reports, **options)
        for jobs in ((), None, "r0-a", ("r0-a", "r0-a"), ("r0-critic", "r0-b"),
                     ("r0-a", "r1-repair"), ("r0-a", [])):
            with self.subTest(jobs=jobs):
                self.refuses("LOOP_REPORT_SET", lambda: self.check(expected_jobs=jobs))

    def test_a_report_must_identify_its_planned_job(self):
        self.reports["r0-b"]["job_id"] = "r0-a"
        self.input = dispatched(self.payload, self.reports)
        self.refuses("REPORT_JOB_MISMATCH", lambda: self.check(review(self.payload, self.reports),
            dispatched_input=self.input, dispatched_input_digest=digest(self.input)))

    def test_current_dispatch_must_contain_the_exact_report_set_and_template(self):
        for change in (lambda value: value["reports"].pop("r0-b"),
                       lambda value: value.update(template_digest="a" * 64),
                       lambda value: value.update(job_id="r0-other"),
                       lambda value: value.update(round=True),
                       lambda value: value.update(round_plan_digest="a" * 64)):
            with self.subTest(change=change):
                delivered = copy.deepcopy(self.input)
                change(delivered)
                self.refuses("LOOP_CRITIC_DISPATCH_MISMATCH", lambda: self.check(
                    dispatched_input=delivered, dispatched_input_digest=digest(delivered)))

    def test_prior_review_is_fully_revalidated_before_deriving_the_gap(self):
        self.second_round()
        for kind in ("missing_criterion", "all_passed", "blocked", "bad_dispatch", "bad_receipt"):
            with self.subTest(kind=kind):
                prior = copy.deepcopy(self.prior)
                validations = prior["response"]["result"]["validations"]
                if kind == "missing_criterion":
                    validations.pop()
                elif kind == "all_passed":
                    prior["response"]["result"] = review(self.payload, prior["dispatched_input"]["reports"])
                elif kind == "blocked":
                    validations[0]["status"] = "blocked"
                elif kind == "bad_dispatch":
                    prior["dispatched_input"]["view"]["view_digest"] = "a" * 64
                else:
                    prior["response"]["receipt"]["input_digest"] = "a" * 64
                admission = {**self.admission, "critic_result_digest": artifact_digest(prior["response"])}
                with self.assertRaises(SwarmError):
                    self.check(prior_review=prior, repair_admission=admission)

    def test_incomplete_prior_or_admission_is_a_typed_refusal(self):
        self.second_round()
        for field in ("response", "dispatched_input", "dispatched_input_digest"):
            with self.subTest(field=field):
                prior = {key: value for key, value in self.prior.items() if key != field}
                self.refuses("LOOP_REPAIR_BINDING", lambda: self.check(prior_review=prior))
        for jobs in (None, [], [{}], [{**self.admission["jobs"][0], "job_id": []},
                                    self.admission["jobs"][1]]):
            with self.subTest(jobs=jobs):
                self.refuses("LOOP_REPAIR_BINDING", lambda: self.check(
                    repair_admission={**self.admission, "jobs": jobs}))

    def test_round_one_view_requires_the_bound_previous_critic(self):
        self.second_round()
        delivered = copy.deepcopy(self.input)
        delivered["view"] = derive_child_view(self.payload, "r1-critic",
            [span(self.payload["sources"][3], "必要な追加根拠です。")],
            plan_digest=PLAN, previous_critic_digest="a" * 64)
        delivered["template_digest"] = digest({key: value for key, value in delivered.items()
            if key not in {"template_digest", "reports", "report_digests"}})
        self.refuses("CLOSED_LOOP_VIEW_BINDING", lambda: self.check(view=delivered["view"],
            dispatched_input=delivered, dispatched_input_digest=digest(delivered)))

    def test_first_round_cannot_skip_to_second_round_binding(self):
        self.refuses("LOOP_REPAIR_BINDING", lambda: self.check(prior_review={}))

    def test_independent_comparison_still_requires_every_report(self):
        next(value for value in self.value["validations"] if value["criterion_id"] == "I")["evidence"].pop()
        self.refuses("LOOP_COMPARISON_REQUIRED", self.check)


if __name__ == "__main__":
    unittest.main()
