"""One real KB projection plus one real reviewed learning; no model calls."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
from tests.test_knowledge_task_input import (STAMP, admit, change_declaration,
    markdown, reseal_seed, setup, small_catalog, source, span)
from kotodama_kb.task_input import compile_task_input, execute_task_input, verify_task_input
from kotodama_kb.task_input_learning import (compile_task_learning_input,
    execute_task_learning_input, verify_task_learning_input)
from runtime.task_swarm.closed_loop import execute_closed_loop
from runtime.task_swarm.learning_reuse import ReuseOwner, learning_source, purpose_digest, with_learning_source
from runtime.task_swarm.protocol import SwarmError, canonical, digest


def save(path, value):
    path.write_bytes(canonical(value).encode("utf-8"))


def once(action):
    lock, done = threading.Lock(), False
    def call():
        nonlocal done
        with lock:
            if not done:
                done = True
                action()
    return call


class ScalingBackend:
    synthetic = True

    def __init__(self, *, ignore=False, after_work=None):
        self.inputs, self.ignore, self.after_work = [], ignore, after_work

    @staticmethod
    def observed(delivered):
        for record in delivered["view"]["spans"]:
            match = re.fullmatch(r"value=(\d+)", record["text"])
            if match:
                return int(match[1]), record, match[0], record["start"]
            try:
                proposal = json.loads(record["text"])
            except ValueError:
                continue
            if isinstance(proposal, dict) and proposal.get("kind") == "task_learning_reuse_proposal":
                text = proposal["selected"]["claim"]["text"]
                match = re.fullmatch(r"value=(\d+)", text)
                if match:
                    return int(match[1]), record, text, record["start"] + record["text"].index(text)
        return None, None, None, None

    def response(self, delivered, result, actor_ref):
        self.inputs.append(copy.deepcopy(delivered))
        return {"result": result, "receipt": {"actor_ref": actor_ref,
            "invocation_ref": "scaled-" + delivered["job_id"],
            "input_digest": digest(delivered), "synthetic": True}}

    def produce(self, delivered, directory, *, actor_ref, **kwargs):
        value, record, quote, start = self.observed(delivered)
        factor = int(re.search(r"FACTOR=(\d+)", delivered["purpose"])[1])
        evidence = [] if record is None else [{"source_key": record["source_key"],
            "source_revision": record["source_revision"], "start": start,
            "end": start + len(quote), "quote": quote}]
        actual = None if value is None else (0 if self.ignore else value * factor)
        claims = [{"text": "value=unknown" if value is None else quote,
                   "status": "unknown" if value is None else "supported", "evidence": evidence},
                  {"text": canonical({"factor": factor, "scaled": actual}),
                   "status": "unknown" if value is None else "inference", "evidence": evidence}]
        result = self.response(delivered, {"job_id": delivered["job_id"],
            "summary": "Compute a scaled observation.", "conflicts": [], "claims": claims}, actor_ref)
        if self.after_work:
            self.after_work()
        return result

    def review(self, delivered, directory, *, actor_ref, **kwargs):
        value, record, _, _ = self.observed(delivered)
        reports = delivered["reports"]
        factors = {}
        # Independent arithmetic from the exact delivered requirement text.
        for row in delivered["view"]["spans"]:
            for match in re.finditer(r"Compute reviewed observation with FACTOR=(\d+)\.", row["text"]):
                factor = int(match[1])
                factors["r0-requirement-" + str(factor - 2)] = factor
        correct = value is not None and set(reports) == set(factors) and all(
            report["claims"][1]["text"] == canonical({"factor": factors[job],
                "scaled": sum(value for _ in range(factors[job]))}) for job, report in reports.items())
        gap = record or next(row for row in delivered["view"]["spans"] if "FACTOR=" in row["text"])
        refs = [{"job_id": job, "claim_index": i} for job in reports for i in (0, 1)]
        return self.response(delivered, {"parent_input_digest": delivered["view"]["parent_input_digest"],
            "plan_digest": delivered["view"]["plan_digest"], "round": delivered["round"],
            "report_digests": delivered["report_digests"], "validations": [
                {"criterion_id": key, "status": "passed" if correct else "failed",
                 "evidence": refs if correct else [],
                 "gap_reason": None if correct else "The scaled observation is absent or incorrect.",
                 "source_spans": [] if correct else [{k: gap[k] for k in
                    ("source_key", "source_revision", "start", "end")}]} for key in delivered["criteria"]]}, actor_ref)


def make_case(root, *, observation=8, corrected=False, now=STAMP):
    bundle, seed, owner, file = setup(root, corrected=corrected)
    requests = [row for row in seed["sources"] if row["key"] == source("request", 1, "")["key"]]
    for row in requests:
        row["text"] = ("Compute every declared factor from the independently reviewed observation."
                       if row["revision"] == 1 else
                       "Compute every declared factor from the current reviewed observation; missing values stay unknown.")
    seed["request"] = requests[-1]["text"]
    def intent(value):
        value["intent"] = {"original": span(requests[0], requests[0]["text"]),
                           "replacements": [span(row, row["text"]) for row in requests[1:]]}
    change_declaration(seed, root, intent)
    for index in range(2):
        row = next(row for row in seed["sources"] if row["key"] == source("REQ-" + str(index), 1, "")["key"])
        need = f"Compute reviewed observation with FACTOR={index + 2}."
        accepted = f"Scaled result uses factor {index + 2} and the current reviewed observation."
        meta = yaml.safe_load(row["text"].split("---", 2)[1])
        meta["task_context"].update(need=need, acceptance=[accepted])
        row["text"] = markdown(meta, need + "\n\n" + accepted)
        (root / "work" / f"REQ-{index}.md").write_bytes(row["text"].encode("utf-8"))
        seed["acceptance"][index] = accepted
    change_declaration(seed, root, lambda value: value["budget"].update(deadline=now + 100))
    reseal_seed(seed, owner, file)
    doc = json.loads(owner.read_bytes())
    doc["binding"]["expires_at"] = now + 200
    save(owner, doc)
    base = compile_task_input(bundle, seed, owner, clock=lambda: now)
    origin = root / "origin"
    origin.mkdir()
    origin_owner, origin_input = origin / "owner.json", origin / "input.json"
    payload = copy.deepcopy(base["payload"])
    payload["task_id"] = "task-00000000-0000-4000-8000-000000000002"
    measurement = source("observation", 1, f"value={observation}")
    payload["sources"].append(measurement)
    save(origin_input, payload)
    origin_doc = copy.deepcopy(doc)
    origin_doc["binding"].update(task_id=payload["task_id"], context_digest=digest(payload), active_home=str(origin))
    origin_doc["storage"] = {"root": str(origin), "mailbox": str(origin / "mailbox.sqlite"),
                             "payloads": str(origin / "payloads")}
    origin_doc["source_checks"] = [*base["source_checks"],
        {"path": str(origin_input), "sha256": hashlib.sha256(origin_input.read_bytes()).hexdigest()}]
    save(origin_owner, origin_doc)
    plan = copy.deepcopy(base["supplied_plan"])
    plan["parent_input_digest"] = digest(payload)
    for job in plan["jobs"]:
        job["selected_spans"].append(span(measurement, measurement["text"]))
    completed = execute_closed_loop(origin_owner, origin_input, plan, ScalingBackend(),
        worker_actors=["worker-a", "worker-b"], clock=lambda: now)
    index = next(i for i, claim in enumerate(completed["candidate"]["claims"])
                 if claim["claim"]["text"] == measurement["text"])
    origin_args = {"origin_owner": str(origin_owner), "origin_input": str(origin_input),
                   "origin_anchor": completed["receipt_sha256"], "claim_index": index}
    return bundle, seed, owner, file, base, origin_args


def compile_learning(case, now=STAMP):
    bundle, seed, owner, _, _, origin = case
    return compile_task_learning_input(bundle, seed, owner, **origin, clock=lambda: now)


def admit_learning(case, candidate, now=STAMP, *, allow=True):
    _, _, owner, file, _, _ = case
    admit(candidate, owner, file)
    learning = candidate["learning"]
    doc = json.loads(owner.read_bytes())
    doc["learning_reuse"] = {"version": 1, "grant_ref": "ref/grant/one-learning",
        "policy_revision_ref": "ref/policy/one-learning", "proposal_digest": digest(learning["proposal"]),
        "origin_receipt_sha256": learning["anchor"], "target_context_digest": digest(candidate["payload"]),
        "purpose_digest": purpose_digest(candidate["payload"]), "reviewer_ref": "verifier",
        "expires_at": now + 150}
    save(owner, doc)
    reuse = ReuseOwner(learning["origin_owner"], learning["origin_input"], learning["anchor"],
                      owner, file, learning["proposal"], clock=lambda: now)
    decision = None
    if allow:
        reuse.review("ref/review/one-learning", "verifier", "allow", "Verified the scaled source observation.")
        decision = reuse.decide("ref/owner/synthetic", "ref/review/one-learning", "allow",
                               "ref/decision/one-learning", expected_generation=0)
    return reuse, decision


class TaskInputLearningTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def execute(self, case, candidate, decision, backend=None, **options):
        backend = backend or ScalingBackend()
        result = execute_task_learning_input(case[0], candidate, case[2], case[3], backend,
            decision_digest=digest(decision), worker_actors=["worker-a", "worker-b"],
            clock=lambda: STAMP, **options)
        return backend, result

    def test_existing_plain_projection_cannot_deliver_the_added_learning(self):
        case = make_case(self.root)
        candidate = compile_learning(case)
        plain = copy.deepcopy(case[4])
        plain["payload"] = with_learning_source(plain["payload"], candidate["learning"]["proposal"])
        admit_learning(case, candidate)
        with self.assertRaisesRegex(SwarmError, "TASK_CONTEXT_CANDIDATE_CHANGED"):
            verify_task_input(case[0], plain, case[2], clock=lambda: STAMP)
        key = learning_source(candidate["learning"]["proposal"])["key"]
        self.assertFalse(any(s["source_key"] == key for j in case[4]["supplied_plan"]["jobs"] for s in j["selected_spans"]))

    def test_exact_source_projection_reaches_both_workers_critic_and_receipt(self):
        case = make_case(self.root, corrected=True)
        before = case[2].read_bytes(), case[3].read_bytes(), copy.deepcopy(case[1])
        candidate = compile_learning(case)
        self.assertEqual(before, (case[2].read_bytes(), case[3].read_bytes(), case[1]))
        self.assertEqual(case[4]["payload"]["objective"], candidate["payload"]["objective"])
        self.assertEqual(case[4]["payload"]["sources"], candidate["payload"]["sources"][:-1])
        self.assertEqual(case[4]["seed_digest"], candidate["seed_digest"])
        self.assertEqual(len(case[4]["payload"]["sources"]) + 1, len(candidate["payload"]["sources"]))
        reuse, decision = admit_learning(case, candidate)
        owner_before = case[2].read_bytes()
        backend, result = self.execute(case, candidate, decision)
        self.assertTrue(result["receipt"]["review_passed"])
        self.assertEqual(owner_before, case[2].read_bytes())
        self.assertEqual(3, len(backend.inputs))
        self.assertEqual(3, result["receipt"]["budget"]["attempts_used"])
        self.assertEqual(1, result["receipt"]["budget"]["remaining_attempts"])
        source_record = learning_source(candidate["learning"]["proposal"])
        directory = case[2].parent / result["receipt"]["run_id"]
        for delivered in backend.inputs:
            stored = json.loads((directory / (delivered["job_id"] + "-input.json")).read_bytes())
            self.assertEqual(delivered, stored)
            self.assertEqual(digest(stored), result["receipt"]["dispatches"][delivered["job_id"]]["delivered_input_digest"])
            self.assertIn(source_record["text"], [s["text"] for s in delivered["view"]["spans"]])
            self.assertEqual(digest(candidate["payload"]), delivered["view"]["parent_input_digest"])
            intent = candidate["payload"]["objective"]["intent"]
            for reference in [intent["original"], *intent["replacements"]]:
                self.assertTrue(any(all(row[key] == reference[key] for key in reference)
                                    for row in delivered["view"]["spans"]))
        binding = json.loads((directory / "context-binding.json").read_bytes())
        self.assertEqual(digest(decision), binding["decision_digest"])
        self.assertEqual([16, 24], [json.loads(r["claims"][1]["text"])["scaled"]
                                  for _, r in sorted(backend.inputs[-1]["reports"].items())])
        replay_backend, replay = self.execute(case, candidate, decision,
            expected_receipt_sha256=result["receipt_sha256"])
        self.assertEqual([], replay_backend.inputs)
        self.assertTrue(replay["duplicate"])
        self.assertEqual(result["receipt"]["budget"], replay["receipt"]["budget"])

    def test_same_budget_without_learning_is_not_a_passing_control(self):
        case = make_case(self.root)
        admit(case[4], case[2], case[3])
        backend = ScalingBackend()
        result = execute_task_input(case[0], case[4], case[2], case[3], backend,
            worker_actors=["worker-a", "worker-b"], clock=lambda: STAMP)
        self.assertFalse(result["receipt"]["review_passed"])
        self.assertEqual(3, result["receipt"]["budget"]["attempts_used"])
        self.assertEqual(4, case[4]["payload"]["objective"]["budget"]["attempt_budget"])
        self.assertTrue(all(self.observation_absent(delivered) for delivered in backend.inputs))

    def test_anchored_replay_rechecks_concept_expiry_before_returning(self):
        from kotodama_kb import task_input_learning as adapter
        small_catalog(self.root)
        expiry = STAMP + 120
        instant = dt.datetime.fromtimestamp(expiry, dt.timezone.utc).isoformat()
        for path in (self.root / "knowledge/synthetic").glob("*.md"):
            path.write_bytes(path.read_bytes().replace(b"2026-12-07T00:00:00Z", instant.encode("utf-8")))
        case = make_case(self.root)
        candidate = compile_learning(case)
        _, decision = admit_learning(case, candidate)
        _, completed = self.execute(case, candidate, decision)
        directory = case[2].parent / completed["receipt"]["run_id"]
        database = directory / "execution.sqlite"
        def snapshot():
            with sqlite3.connect(database) as db:
                rows = list(db.iterdump())
            artifacts = {path.name: path.read_bytes() for path in directory.glob("*.json")}
            return rows, artifacts, case[2].read_bytes(), case[3].read_bytes()
        before = snapshot()
        now = [expiry - 1]
        options = {"decision_digest": digest(decision), "worker_actors": ["worker-a", "worker-b"],
                   "clock": lambda: now[0], "expected_receipt_sha256": completed["receipt_sha256"]}
        positive_backend = ScalingBackend()
        positive = adapter.execute_task_learning_input(case[0], candidate, case[2], case[3],
                                                       positive_backend, **options)
        self.assertTrue(positive["duplicate"])
        self.assertEqual(completed["receipt_sha256"], positive["receipt_sha256"])
        self.assertEqual([], positive_backend.inputs)
        self.assertEqual(before, snapshot())
        actual, entered = adapter.execute_closed_loop, []
        def cross_expiry(*args, **kwargs):
            entered.append(True)
            now[0] = expiry + 1
            return actual(*args, **kwargs)
        backend = ScalingBackend()
        with mock.patch.object(adapter, "execute_closed_loop", cross_expiry), self.assertRaisesRegex(
                SwarmError, "TASK_CONTEXT_EXPIRED"):
            adapter.execute_task_learning_input(case[0], candidate, case[2], case[3], backend, **options)
        self.assertEqual([True], entered)
        self.assertEqual([], backend.inputs)
        self.assertEqual(before, snapshot())

    @staticmethod
    def observation_absent(delivered):
        return ScalingBackend.observed(delivered)[0] is None

    def test_observation_changes_results_and_ignored_learning_fails_critic(self):
        values = []
        for observation, ignored in ((8, False), (11, False), (8, True)):
            with self.subTest(observation=observation, ignored=ignored), tempfile.TemporaryDirectory() as temp:
                case = make_case(Path(temp), observation=observation)
                candidate = compile_learning(case)
                _, decision = admit_learning(case, candidate)
                backend, result = self.execute(case, candidate, decision, ScalingBackend(ignore=ignored))
                self.assertEqual(not ignored, result["receipt"]["review_passed"])
                if not ignored:
                    values.append([json.loads(r["claims"][1]["text"])["scaled"]
                                   for _, r in sorted(backend.inputs[-1]["reports"].items())])
        self.assertEqual([[16, 24], [22, 33]], values)

    def test_decision_revoke_and_mid_call_revoke_stop_without_receipt(self):
        case = make_case(self.root)
        candidate = compile_learning(case)
        reuse, decision = admit_learning(case, candidate)
        def revoke():
            reuse.decide("ref/owner/synthetic", "ref/review/one-learning", "revoke",
                         "ref/decision/revoke", expected_generation=1)
        backend = ScalingBackend(after_work=once(revoke))
        with self.assertRaises(SwarmError):
            self.execute(case, candidate, decision, backend)
        self.assertFalse(list(case[2].parent.glob("task-run-*/receipt.json")))
        with self.assertRaisesRegex(SwarmError, "REUSE_DECISION_STALE"):
            verify_task_learning_input(case[0], candidate, case[2], case[3],
                decision_digest=digest(decision), clock=lambda: STAMP)
        with self.assertRaisesRegex(SwarmError, "REUSE_DECISION_STALE"):
            self.execute(case, candidate, decision)

    def test_standalone_verify_rechecks_decision_after_final_kb_projection(self):
        from kotodama_kb import task_input_learning as adapter
        case = make_case(self.root)
        candidate = compile_learning(case)
        reuse, decision = admit_learning(case, candidate)
        original, calls = adapter._verify_projection, []
        def checked(*args, **kwargs):
            result = original(*args, **kwargs)
            calls.append(None)
            if len(calls) == 2:
                reuse.decide("ref/owner/synthetic", "ref/review/one-learning", "revoke",
                             "ref/decision/revoke", expected_generation=1)
            return result
        with mock.patch.object(adapter, "_verify_projection", checked), self.assertRaisesRegex(
                SwarmError, "REUSE_DECISION_STALE"):
            verify_task_learning_input(case[0], candidate, case[2], case[3],
                decision_digest=digest(decision), clock=lambda: STAMP)
        self.assertEqual(2, len(calls))

    def test_origin_artifact_changes_before_and_during_execution_cannot_publish(self):
        for timing in ("before", "during"):
            with self.subTest(timing=timing), tempfile.TemporaryDirectory() as temporary:
                case = make_case(Path(temporary))
                candidate = compile_learning(case)
                _, decision = admit_learning(case, candidate)
                origin = candidate["learning"]
                payload = json.loads(Path(origin["origin_input"]).read_bytes())
                directory = Path(origin["origin_owner"]).parent / (
                    "task-run-" + digest([payload["task_id"], payload["revision"]])[:32])
                artifact = directory / "r0-requirement-0-result.json"
                def change():
                    artifact.write_bytes(artifact.read_bytes() + b"\n")
                backend = ScalingBackend(after_work=once(change) if timing == "during" else None)
                if timing == "before":
                    change()
                    with self.assertRaises(SwarmError):
                        verify_task_learning_input(case[0], candidate, case[2], case[3],
                            decision_digest=digest(decision), clock=lambda: STAMP)
                with self.assertRaises(SwarmError):
                    self.execute(case, candidate, decision, backend)
                self.assertEqual(timing == "during", bool(backend.inputs))
                self.assertFalse(list(case[2].parent.glob("task-run-*/receipt.json")))
                for database in case[2].parent.glob("task-run-*/execution.sqlite"):
                    with sqlite3.connect(database) as db:
                        self.assertEqual(0, db.execute("SELECT count(*) FROM jobs WHERE state='accepted'").fetchone()[0])
                fresh = ScalingBackend()
                with self.assertRaises(SwarmError):
                    self.execute(case, candidate, decision, fresh)
                self.assertEqual([], fresh.inputs)

    def test_candidate_mutations_owner_sources_and_expiry_are_rejected(self):
        case = make_case(self.root)
        candidate = compile_learning(case)
        _, decision = admit_learning(case, candidate)
        def verify(value=candidate, now=STAMP):
            return verify_task_learning_input(case[0], value, case[2], case[3],
                decision_digest=digest(decision), clock=lambda: now)
        verify()
        for field in ("purpose", "criterion_ids", "selected_spans"):
            changed = copy.deepcopy(candidate)
            job = changed["supplied_plan"]["jobs"][0]
            job[field] = "Other purpose" if field == "purpose" else job[field][:-1]
            with self.subTest(field=field), self.assertRaisesRegex(SwarmError, "TASK_CONTEXT_CANDIDATE_CHANGED"):
                verify(changed)
        with self.assertRaisesRegex(SwarmError, "OBJECTIVE_DEADLINE_INVALID"):
            verify(now=STAMP + 101)
        with self.assertRaisesRegex(SwarmError, "REUSE_GRANT_EXPIRED"):
            verify_task_learning_input(case[0], candidate, case[2], case[3],
                decision_digest=digest(decision), clock=lambda: STAMP + 151, allow_expired=True)
        changed = copy.deepcopy(candidate)
        changed["learning"]["anchor"] = "0" * 64
        with self.assertRaisesRegex(SwarmError, "REUSE_ORIGIN_ANCHOR_MISMATCH"):
            verify(changed)
        changed = copy.deepcopy(candidate)
        changed["diagnostics"]["oversize"] = "x" * (256 * 1024)
        with self.assertRaisesRegex(SwarmError, "TASK_CONTEXT_LIMIT"):
            verify(changed)
        old = (self.root / "work/project.md").read_bytes()
        (self.root / "work/project.md").write_bytes(old + b"\nchanged\n")
        with self.assertRaises(SwarmError):
            verify()

    def test_owner_revision_change_rejects_old_candidate_without_dispatch(self):
        case = make_case(self.root)
        candidate = compile_learning(case)
        _, decision = admit_learning(case, candidate)
        replacement = source("request", 2, "Use only observations approved after the current correction.")
        seed = copy.deepcopy(case[1])
        seed["revision"] = 2
        seed["request"] = replacement["text"]
        seed["sources"].append(replacement)
        change_declaration(seed, self.root, lambda value: value["intent"]["replacements"].append(
            span(replacement, replacement["text"])))
        document = json.loads(case[2].read_bytes())
        document["binding"]["revision"] = 2
        save(case[2], document)
        reseal_seed(seed, case[2], case[3])
        current = compile_task_input(case[0], seed, case[2], clock=lambda: STAMP)
        from kotodama_kb.task_input_learning import _compose
        with self.assertRaisesRegex(SwarmError, "REUSE_PURPOSE_MISMATCH"):
            _compose(current, candidate["learning"])
        backend = ScalingBackend()
        with self.assertRaises(SwarmError):
            self.execute(case, candidate, decision, backend)
        self.assertEqual([], backend.inputs)
        self.assertEqual(2, json.loads(case[2].read_bytes())["binding"]["revision"])

    def test_actor_and_worker_budget_refusals_preserve_owner(self):
        case = make_case(self.root)
        candidate = compile_learning(case)
        _, decision = admit_learning(case, candidate)
        before = case[2].read_bytes()
        backend = ScalingBackend()
        with self.assertRaisesRegex(SwarmError, "LOOP_ACTORS_INVALID"):
            execute_task_learning_input(case[0], candidate, case[2], case[3], backend,
                decision_digest=digest(decision), worker_actors=["worker-a"], clock=lambda: STAMP)
        self.assertEqual([], backend.inputs)
        self.assertEqual(before, case[2].read_bytes())
        document = json.loads(before)
        document["actors"]["verifier"]["epoch"] += 1
        save(case[2], document)
        with self.assertRaisesRegex(SwarmError, "REUSE_REVIEW_STALE"):
            verify_task_learning_input(case[0], candidate, case[2], case[3],
                decision_digest=digest(decision), clock=lambda: STAMP)

    def test_required_source_checks_and_late_kb_change_prevent_publication(self):
        from runtime.task_swarm import closed_loop as loop
        case = make_case(self.root)
        candidate = compile_learning(case)
        _, decision = admit_learning(case, candidate)
        before = case[2].read_bytes()
        document = json.loads(before)
        document["source_checks"] = [row for row in document["source_checks"] if row["path"] == str(case[3])]
        save(case[2], document)
        with self.assertRaisesRegex(SwarmError, "TASK_CONTEXT_OWNER_CHECKS_REQUIRED"):
            verify_task_learning_input(case[0], candidate, case[2], case[3],
                decision_digest=digest(decision), clock=lambda: STAMP)
        case[2].write_bytes(before)
        original = loop.integration_candidate
        changed = []
        def after_reports(payload, *args, **kwargs):
            result = original(payload, *args, **kwargs)
            if payload["task_id"] == candidate["payload"]["task_id"] and not changed:
                changed.append(True)
                path = self.root / "work/project.md"
                path.write_bytes(path.read_bytes() + b"\n")
            return result
        backend = ScalingBackend()
        with mock.patch.object(loop, "integration_candidate", after_reports), self.assertRaises(SwarmError):
            self.execute(case, candidate, decision, backend)
        self.assertEqual([True], changed)
        self.assertEqual(3, len(backend.inputs))
        self.assertFalse(list(case[2].parent.glob("task-run-*/receipt.json")))
        for database in case[2].parent.glob("task-run-*/execution.sqlite"):
            with sqlite3.connect(database) as db:
                self.assertEqual(0, db.execute("SELECT count(*) FROM jobs WHERE state='accepted'").fetchone()[0])

    def test_initial_missing_decision_and_context_override_are_rejected(self):
        case = make_case(self.root)
        candidate = compile_learning(case)
        _, _ = admit_learning(case, candidate, allow=False)
        with self.assertRaisesRegex(SwarmError, "REUSE_EVIDENCE_MISSING"):
            verify_task_learning_input(case[0], candidate, case[2], case[3],
                decision_digest="0" * 64, clock=lambda: STAMP)
        with self.assertRaisesRegex(SwarmError, "TASK_LEARNING_CONTEXT_OVERRIDE"):
            execute_task_learning_input(case[0], candidate, case[2], case[3], ScalingBackend(),
                decision_digest="0" * 64, worker_actors=["worker-a", "worker-b"],
                clock=lambda: STAMP, reuse_context={})

    def test_source_limit_and_selected_union_limit_do_not_drop_context(self):
        case = make_case(self.root)
        full = copy.deepcopy(case[1])
        full["sources"] += [source("extra-" + str(i), 1, "x") for i in range(10-len(full["sources"]))]
        reseal_seed(full, case[2], case[3])
        with self.assertRaisesRegex(SwarmError, "REUSE_SOURCE_LIMIT"):
            compile_task_learning_input(case[0], full, case[2], **case[5], clock=lambda: STAMP)
        from kotodama_kb.task_input_learning import _compose
        base = copy.deepcopy(case[4])
        request = base["payload"]["sources"][0]
        selections = [{"source_key": request["key"], "source_revision": request["revision"],
                       "start": i, "end": i+1} for i in range(32)]
        for job in base["supplied_plan"]["jobs"]:
            job["selected_spans"] = copy.deepcopy(selections)
        with tempfile.TemporaryDirectory() as temporary:
            candidate = compile_learning(make_case(Path(temporary)))
            with self.assertRaises(SwarmError):
                _compose(base, candidate["learning"])

    def _cli_case(self, *, negative=False):
        now = time.time()
        case = make_case(self.root, now=now)
        origin = self.root / "learning-origin.json"
        save(origin, case[5])
        entry = ROOT / "tools/knowledge_base.py"
        def command(operation, *args, expected=0):
            result = subprocess.run([sys.executable, "-I", "-B", str(entry), "task-input", operation,
                "--root", str(self.root), "--owner", str(case[2]), *map(str, args)],
                cwd=self.root / "origin", capture_output=True, timeout=30)
            self.assertEqual(expected, result.returncode, result.stderr.decode("utf-8"))
            self.assertTrue((result.stdout if expected != 2 else result.stderr).endswith(b"\n"))
            return json.loads(result.stdout if expected != 2 else result.stderr)
        before = case[2].read_bytes()
        candidate = command("compile", "--input", case[3], "--learning-origin", origin)
        self.assertEqual(before, case[2].read_bytes())
        target = self.root / "learning-candidate.json"
        save(target, candidate)
        admit_learning(case, candidate, now, allow=False)
        learning = candidate["learning"]
        context = {key: learning[key] for key in ("origin_owner", "origin_input", "anchor", "proposal")}
        context.update(target_owner=str(case[2]), target_input=str(case[3]))
        context_file = self.root / "reuse-context.json"
        save(context_file, context)
        def reuse_command(operation, *args):
            code = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('runtime.task_swarm.learning_reuse',run_name='__main__')"
            result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(ROOT),
                operation, "--context", str(context_file), *map(str, args)],
                cwd=self.root / "origin", capture_output=True, timeout=30)
            self.assertEqual(0, result.returncode, result.stderr.decode("utf-8"))
            return json.loads(result.stdout)
        reuse_command("review", "--review-ref", "ref/review/one-learning", "--reviewer", "verifier",
                      "--outcome", "allow", "--reason", "Checked the current source observation.")
        decision = reuse_command("decide", "--actor", "ref/owner/synthetic", "--review-ref", "ref/review/one-learning",
                      "--outcome", "allow", "--key", "ref/decision/one-learning", "--expected-generation", 0)
        self.assertEqual("binding_and_learning_verified", command("verify", "--candidate", target,
            "--input", case[3], "--learning-decision-digest", digest(decision))["status"])
        backend = ScalingBackend()
        # Produce a deterministic explicit scenario from the same delivered
        # inputs; CLI's real coordinator validates every saved receipt/view.
        from runtime.task_swarm.closed_loop_contract import loop_criteria
        from runtime.task_swarm.closed_loop_context import derive_child_view
        plan = candidate["supplied_plan"]
        work = {}
        for job in plan["jobs"]:
            job_id = "r0-" + job["job_id"]
            delivered = {"role": "work", "job_id": job_id, "round": 0,
                "round_plan_digest": digest(plan), "purpose": job["purpose"],
                "criterion_ids": job["criterion_ids"],
                "criteria": {key: loop_criteria(candidate["payload"])[key] for key in job["criterion_ids"]},
                "view": derive_child_view(candidate["payload"], job_id, job["selected_spans"],
                                          plan_digest=digest(plan))}
            work[delivered["job_id"]] = backend.produce(delivered, self.root, actor_ref="worker-a")["result"]
        refs = [{"job_id": job, "claim_index": i} for job in work for i in (0, 1)]
        scenario = {"work": work, "critics": {"0": {
            "parent_input_digest": digest(candidate["payload"]), "plan_digest": digest(plan), "round": 0,
            "report_digests": {job: digest(report) for job, report in work.items()},
            "validations": [{"criterion_id": key, "status": "passed", "evidence": refs,
                             "gap_reason": None, "source_spans": []} for key in loop_criteria(candidate["payload"])]}},
            "repair_plan": None}
        if negative:
            scenario["critics"]["0"]["validations"][0].update(status="failed", evidence=[],
                gap_reason="The fixture does not establish the first condition.",
                source_spans=[candidate["payload"]["objective"]["constraints"][0]])
        scenario_file = self.root / "scenario.json"
        save(scenario_file, scenario)
        result = command("simulate", "--candidate", target, "--input", case[3], "--simulation", scenario_file,
            "--worker", "worker-a", "--worker", "worker-b", "--learning-decision-digest", digest(decision),
            expected=3 if negative else 0)
        self.assertEqual(not negative, result["receipt"]["review_passed"])
        directory = case[2].parent / result["receipt"]["run_id"]
        saved = {path.name: path.read_bytes() for path in directory.glob("*-input.json")}
        replay = command("simulate", "--candidate", target, "--input", case[3], "--simulation", scenario_file,
            "--worker", "worker-a", "--worker", "worker-b", "--learning-decision-digest", digest(decision),
            "--receipt-sha256", result["receipt_sha256"], expected=3 if negative else 0)
        self.assertTrue(replay["duplicate"])
        self.assertEqual(saved, {path.name: path.read_bytes() for path in directory.glob("*-input.json")})
        self.assertEqual(result["receipt"]["budget"], replay["receipt"]["budget"])
        refused = command("verify", "--candidate", target, "--input", case[3], expected=2)
        self.assertEqual("TASK_LEARNING_DECISION_REQUIRED", refused["error"])

    def test_fresh_isolated_cli_compiles_verifies_and_simulates(self):
        self._cli_case()

    def test_fresh_isolated_cli_negative_critic_and_replay_keep_exit_three(self):
        self._cli_case(negative=True)


if __name__ == "__main__":
    unittest.main()
