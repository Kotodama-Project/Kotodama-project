"""Assignment and repair evidence are derived from the immutable execution plan."""
import copy
import hashlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from task_swarm.closed_loop_contract import (evidence_version, loop_criteria,
    required_evidence_jobs, validate_critic, verified_gap, work_input)
from task_swarm.closed_loop_context import derive_child_view
from task_swarm.protocol import SwarmError, canonical, digest
from test_task_swarm_closed_loop_context import fixture, report, span


def template(payload, spec, initial_digest, index, required, previous=None):
    selected = [s for job in spec["jobs"] for s in job["selected_spans"]]
    return {"role": "critic", "job_id": f"r{index}-critic", "round": index,
            "round_plan_digest": digest(spec), "criteria": loop_criteria(payload),
            "view": derive_child_view(payload, f"r{index}-critic", selected,
                plan_digest=initial_digest, previous_critic_digest=previous),
            "evidence_contract_version": 2, "required_evidence_jobs": required}


def runtime_job(name, value, *, critic=False, dependencies=()):
    return {"job_id": name, "kind": "review" if critic else "work", "dependencies": list(dependencies),
            "exclusive_keys": [], "payload_ref": "ref/loop/" + name, "payload_digest": digest(value)}


class CriticEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.payload = fixture()
        self.payload["acceptance"].append("Report the memory comparison.")
        self.selected = span(self.payload["sources"][3], "必要な追加根拠です。")
        common = [key for key in loop_criteria(self.payload) if not key.startswith("A")]
        self.spec = {"version": 1, "parent_input_digest": digest(self.payload), "jobs": [
            {"job_id": "latency", "purpose": "Compare latency", "criterion_ids": common + ["A1"],
             "selected_spans": [self.selected]},
            {"job_id": "memory", "purpose": "Compare memory", "criterion_ids": common + ["A2"],
             "selected_spans": [self.selected]}]}
        self.prepare()

    def prepare(self):
        self.initial_digest = digest(self.spec)
        self.required = required_evidence_jobs(self.payload, self.spec)
        self.inputs = {}
        for job in self.spec["jobs"]:
            value = work_input(self.payload, job, 0, self.initial_digest,
                               round_plan_digest=self.initial_digest)
            self.inputs[value["job_id"]] = value
        self.initial_template = template(self.payload, self.spec, self.initial_digest, 0, self.required)
        self.runtime = {"jobs": [runtime_job(name, value) for name, value in self.inputs.items()] + [
            runtime_job("r0-critic", self.initial_template, critic=True, dependencies=self.inputs)]}
        self.reports = {name: report(self.payload, "必要な追加根拠です。", job=name) for name in self.inputs}
        self.install_review(self.initial_template)
        self.options = dict(view=self.delivered["view"], plan_digest=self.initial_digest, round_index=0,
            initial_execution_plan_digest=digest(self.runtime), expected_jobs=tuple(self.reports),
            dispatched_input=self.delivered, dispatched_input_digest=digest(self.delivered),
            initial_specification=self.spec, initial_runtime_plan=self.runtime,
            initial_template=self.initial_template, work_inputs=self.inputs)

    def install_review(self, value, failed=()):
        self.delivered = {**value, "template_digest": digest(value), "reports": copy.deepcopy(self.reports),
                          "report_digests": {job: digest(result) for job, result in self.reports.items()}}
        self.result = {"parent_input_digest": digest(self.payload), "plan_digest": self.initial_digest,
            "round": value["round"], "report_digests": self.delivered["report_digests"], "validations": [
                {"criterion_id": key, "status": "failed" if key in failed else "passed",
                 "evidence": [] if key in failed else [{"job_id": job, "claim_index": 0}
                     for job in value["required_evidence_jobs"][key]],
                 "gap_reason": "Missing memory measurement" if key in failed else None,
                 "source_spans": [self.selected] if key in failed else []} for key in loop_criteria(self.payload)]}

    def check(self):
        return validate_critic(self.result, self.payload, self.reports, **self.options)

    def refuses(self, code="LOOP_CRITIC_ASSIGNMENT"):
        with self.assertRaises(SwarmError) as caught:
            self.check()
        self.assertEqual(caught.exception.code, code)

    def criterion(self, key):
        return next(item for item in self.result["validations"] if item["criterion_id"] == key)

    def repair(self, count=1):
        self.install_review(self.initial_template, failed=("A2",))
        prior_response = {"result": self.result, "receipt": {"input_digest": digest(self.delivered)}}
        prior = {"response": prior_response, "dispatched_input": self.delivered,
                 "dispatched_input_digest": digest(self.delivered)}
        sha = hashlib.sha256((canonical(prior_response) + "\n").encode()).hexdigest()
        gap = verified_gap(self.result, critic_job_id="r0-critic", critic_result_digest=sha)
        repair = {"version": 1, "parent_input_digest": digest(self.payload), "jobs": [
            {"job_id": f"fix{i}", "purpose": "Supply memory evidence", "criterion_ids": ["A2"],
             "selected_spans": [self.selected]} for i in range(count)]}
        required = required_evidence_jobs(self.payload, self.spec, repair, gap=gap)
        jobs = []
        for job in repair["jobs"]:
            value = work_input(self.payload, job, 1, self.initial_digest,
                               round_plan_digest=digest(repair), previous=sha)
            self.inputs[value["job_id"]] = value
            self.reports[value["job_id"]] = report(self.payload, "必要な追加根拠です。", job=value["job_id"])
            jobs.append(runtime_job(value["job_id"], value))
        review_template = template(self.payload, repair, self.initial_digest, 1, required, sha)
        jobs.append(runtime_job("r1-critic", review_template, critic=True, dependencies=self.reports))
        admission = {"round": 1, "initial_plan_digest": digest(self.runtime), "critic_job_id": "r0-critic",
                     "critic_result_digest": sha, "proposal_digest": digest(repair), "jobs": jobs}
        self.install_review(review_template)
        self.options.update(view=self.delivered["view"], round_index=1, expected_jobs=tuple(self.reports),
            dispatched_input=self.delivered, dispatched_input_digest=digest(self.delivered),
            prior_review=prior, repair_admission=admission, repair_specification=repair)
        return required

    def test_one_leaf_only_uses_its_assignment_and_common_uses_all(self):
        self.assertEqual(self.required["A1"], ["r0-latency"])
        self.assertEqual(self.required["A2"], ["r0-memory"])
        self.assertEqual(self.required["I"], ["r0-latency", "r0-memory"])
        self.assertEqual(self.check(), self.result)

    def test_shared_root_assignment_requires_both_leaves(self):
        self.spec["jobs"][1]["criterion_ids"].append("A1")
        self.prepare()
        self.assertEqual(self.required["A1"], ["r0-latency", "r0-memory"])
        self.criterion("A1")["evidence"].pop()
        self.refuses()

    def test_wrong_leaf_missing_extra_duplicate_and_failed_wrong_leaf_refuse(self):
        original = copy.deepcopy(self.result)
        for refs in ([{"job_id": "r0-latency", "claim_index": 0}], [],
                     [{"job_id": job, "claim_index": 0} for job in self.reports],
                     [{"job_id": "r0-memory", "claim_index": 0}] * 2):
            with self.subTest(refs=refs):
                self.result = copy.deepcopy(original)
                self.criterion("A2")["evidence"] = refs
                self.refuses()
        self.result = copy.deepcopy(original)
        value = self.criterion("A2")
        value.update(status="failed", evidence=[{"job_id": "r0-latency", "claim_index": 0}],
                     gap_reason="Missing memory", source_spans=[self.selected])
        self.refuses()

    def test_common_assignments_cannot_omit_a_leaf(self):
        self.spec["jobs"][1]["criterion_ids"].remove("R")
        with self.assertRaisesRegex(SwarmError, "LOOP_COMMON_CRITERIA_COVERAGE"):
            self.prepare()

    def test_repair_reopens_shared_conditions_but_not_unrelated_leaf(self):
        required = self.repair()
        self.assertEqual(required["A1"], ["r0-latency"])
        self.assertEqual(required["A2"], ["r0-memory", "r1-fix0"])
        self.assertEqual(required["R"], ["r0-latency", "r0-memory", "r1-fix0"])
        self.assertEqual(self.check(), self.result)
        for name in ("A2", "R", "I", "O1", "Q1"):
            with self.subTest(name=name):
                old = self.criterion(name)["evidence"]
                self.criterion(name)["evidence"] = [ref for ref in old if not ref["job_id"].startswith("r1-")]
                self.refuses()
                self.criterion(name)["evidence"] = old

    def test_all_repair_contributors_and_original_leaf_are_required(self):
        self.repair(2)
        self.assertEqual(self.check(), self.result)
        for missing in ("r0-memory", "r1-fix0", "r1-fix1"):
            original = self.criterion("A2")["evidence"]
            self.criterion("A2")["evidence"] = [ref for ref in original if ref["job_id"] != missing]
            self.refuses()
            self.criterion("A2")["evidence"] = original

    def test_work_self_declared_assignment_cannot_replace_initial_plan(self):
        self.inputs["r0-memory"]["criterion_ids"] = ["A1"]
        self.refuses("LOOP_WORK_BINDING")

    def test_unadmitted_repair_specification_refuses(self):
        self.repair()
        self.options["repair_specification"] = copy.deepcopy(self.options["repair_specification"])
        self.options["repair_specification"]["jobs"][0]["criterion_ids"] = ["A1"]
        self.refuses("LOOP_REPAIR_BINDING")

    def test_proposal_without_actual_admission_cannot_add_repair_influence(self):
        self.options["repair_specification"] = copy.deepcopy(self.spec)
        self.refuses("LOOP_REPAIR_BINDING")

    def test_template_mapping_and_version_cannot_override_runtime_plan(self):
        for key, value in (("evidence_contract_version", 1), ("evidence_contract_version", 3),
                           ("required_evidence_jobs", {})):
            with self.subTest(key=key, value=value):
                self.prepare()
                self.initial_template[key] = value
                self.refuses("LOOP_EVIDENCE_POLICY")
        self.prepare()
        self.delivered["required_evidence_jobs"] = {}
        self.options["dispatched_input_digest"] = digest(self.delivered)
        self.refuses("LOOP_EVIDENCE_POLICY")

    def test_policy_is_mandatory_and_state_digest_cannot_be_rebound(self):
        for key in ("initial_specification", "initial_runtime_plan", "initial_template", "work_inputs"):
            with self.subTest(key=key):
                args = {k: v for k, v in self.options.items() if k != key}
                with self.assertRaises(TypeError):
                    validate_critic(self.result, self.payload, self.reports, **args)
        self.runtime["jobs"][-1]["payload_digest"] = "a" * 64
        self.refuses("LOOP_EVIDENCE_POLICY")


if __name__ == "__main__":
    unittest.main()
