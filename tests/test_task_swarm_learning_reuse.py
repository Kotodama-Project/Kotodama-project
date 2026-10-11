"""Two local processes and the real coordinator; no model or provider calls."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest job")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from task_swarm.closed_loop import execute_closed_loop
from task_swarm.closed_loop_contract import loop_criteria
from task_swarm.learning_reuse import ReuseOwner, learning_source, propose_learning, purpose_digest, with_learning_source
from task_swarm.protocol import SwarmError, digest
from test_task_swarm_closed_loop import MeasuredBackend, execute, repair_for, setup_loop
from test_task_swarm_objectives import span


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def setup_reuse(tmp_path, *, now=1000, observation=8, grant_lifetime=100):
    a = tmp_path / "a"; a.mkdir()
    origin = setup_loop(a, jobs=1)
    if observation != 8:
        measure = origin[6]
        measure["text"] = measure["text"].replace("memory=8", f"memory={observation}")
        measure["sha256"] = hashlib.sha256(measure["text"].encode()).hexdigest()
        origin[4]["jobs"][0]["selected_spans"][1] = span(measure, f"memory={observation}")
    origin[3]["objective"]["budget"]["deadline"] = now + 100
    origin[2]["binding"].update(expires_at=now+200, context_digest=digest(origin[3]))
    save(origin[1], origin[3])
    origin[2]["source_checks"][0]["sha256"] = hashlib.sha256(origin[1].read_bytes()).hexdigest()
    save(origin[0], origin[2])
    origin[4]["parent_input_digest"] = digest(origin[3])
    completed = execute_closed_loop(origin[0], origin[1], origin[4], MeasuredBackend(origin[3], origin[6]),
        worker_actors=origin[5], repair_planner=repair_for(origin[3]), clock=lambda: now)
    index = next(i for i, item in enumerate(completed["candidate"]["claims"])
                 if item["claim"]["text"] == f"memory={observation}")
    proposal = propose_learning(origin[0], origin[1], completed["receipt_sha256"], index, clock=lambda: now)
    b = tmp_path / "b"; b.mkdir()
    root = b / "operations"; root.mkdir()
    payload = copy.deepcopy(origin[3])
    payload.update(task_id="task-00000000-0000-4000-8000-000000000002", revision=1)
    payload["sources"] = [s for s in payload["sources"] if s["key"] != "c"*64]
    payload["objective"]["budget"]["attempt_budget"] = 4
    payload = with_learning_source(payload, proposal)
    source = learning_source(proposal)
    input_path, owner_path = b / "input.json", b / "owner.json"
    save(input_path, payload)
    document = copy.deepcopy(origin[2])
    document["binding"].update(task_id=payload["task_id"], revision=payload["revision"],
        context_digest=digest(payload), active_home=str(root))
    document["storage"] = {"root": str(root), "mailbox": str(root/"mailbox.sqlite"), "payloads": str(root/"payloads")}
    document["source_checks"] = [{"path": str(input_path), "sha256": hashlib.sha256(input_path.read_bytes()).hexdigest()}]
    document["learning_reuse"] = {"version": 1, "grant_ref": "ref/grant/one-reuse",
        "policy_revision_ref": "ref/policy/reuse-one", "proposal_digest": digest(proposal),
        "origin_receipt_sha256": completed["receipt_sha256"], "target_context_digest": digest(payload),
        "purpose_digest": purpose_digest(payload), "reviewer_ref": "verifier", "expires_at": now+grant_lifetime}
    save(owner_path, document)
    arguments = {"origin_owner": str(origin[0]), "origin_input": str(origin[1]),
        "anchor": completed["receipt_sha256"], "target_owner": str(owner_path),
        "target_input": str(input_path), "proposal": proposal}
    reuse = ReuseOwner(**arguments, clock=lambda: now)
    plan = {"version": 1, "parent_input_digest": digest(payload), "jobs": [{"job_id": "apply-memory",
        "purpose": "Use the reviewed memory observation for the same comparison.",
        "criterion_ids": list(loop_criteria(payload)), "selected_spans": [span(source, source["text"])]}]}
    return reuse, arguments, plan, payload, document, origin


def allow(reuse):
    reuse.review("ref/review/one-learning", "verifier", "allow", "The selected observation is source supported in this scope.")
    return reuse.decide("ref/owner/fixture", "ref/review/one-learning", "allow",
                        "ref/decision/one-learning", expected_generation=0)


class ReadingBackend:
    synthetic = True

    def __init__(self, *, ignore=False, after_work=None):
        self.ignore, self.after_work, self.calls = ignore, after_work, []

    @staticmethod
    def observed(delivered):
        for record in delivered["view"]["spans"]:
            try:
                value = json.loads(record["text"])
            except ValueError:
                continue
            if value.get("kind") == "task_learning_reuse_proposal":
                claim = value["selected"]["claim"]["text"]
                count = int(claim.split("=")[1])
                at = record["text"].index(claim)
                evidence = {"source_key": record["source_key"], "source_revision": record["source_revision"],
                    "start": record["start"] + at, "end": record["start"] + at + len(claim), "quote": claim}
                return count, evidence, record
        record = next(record for record in delivered["view"]["spans"] if "不明" in record["text"])
        return None, None, record

    def response(self, delivered, result, actor):
        self.calls.append(delivered["role"])
        return {"result": result, "receipt": {"actor_ref": actor,
            "invocation_ref": "reading-" + delivered["job_id"], "input_digest": digest(delivered), "synthetic": True}}

    def produce(self, delivered, directory, *, actor_ref, **kwargs):
        count, evidence, _ = self.observed(delivered)
        text = "Memory is unknown without a reviewed observation." if count is None else f"Use measured memory budget {0 if self.ignore else count}."
        result = {"job_id": delivered["job_id"], "summary": text, "conflicts": [],
                  "claims": [{"text": text, "status": "unknown" if count is None else "supported",
                              "evidence": [] if evidence is None else [evidence]}]}
        if self.after_work:
            self.after_work()
        return self.response(delivered, result, actor_ref)

    def review(self, delivered, directory, *, actor_ref, **kwargs):
        count, _, record = self.observed(delivered)
        reports = delivered["reports"]
        refs = [{"job_id": job, "claim_index": 0} for job in reports]
        correct = count is not None and all(r["claims"][0]["text"] == f"Use measured memory budget {count}." for r in reports.values())
        validations = []
        for key in delivered["criteria"]:
            failed = not correct and key in {"R", "A1"}
            validations.append({"criterion_id": key, "status": "failed" if failed else "passed",
                "evidence": [] if failed else refs,
                "gap_reason": "The consumer ignored the reviewed observation." if failed else None,
                "source_spans": [{k: record[k] for k in ("source_key", "source_revision", "start", "end")}] if failed else []})
        result = {"parent_input_digest": delivered["view"]["parent_input_digest"],
            "plan_digest": delivered["view"]["plan_digest"], "round": delivered["round"],
            "report_digests": {job: digest(value) for job, value in reports.items()}, "validations": validations}
        return self.response(delivered, result, actor_ref)


def run(reuse, plan, backend, decision, **kwargs):
    return reuse.execute(digest(decision), plan, backend, worker_actors=["worker-a"], **kwargs)


def fresh_run():
    arguments = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if arguments.get("mode") == "no_learning":
        result = execute_closed_loop(arguments["owner"], arguments["input"], arguments["plan"],
                                     ReadingBackend(), worker_actors=["worker-a"], clock=lambda: 1000)
    else:
        reuse = ReuseOwner(**arguments["owner"], clock=lambda: 1000)
        result = run(reuse, arguments["plan"], ReadingBackend(), arguments["decision"])
    print(json.dumps({"pid": os.getpid(), "result": result}))


def test_two_processes_reuse_actual_claim_through_real_owner_and_coordinator(tmp_path):
    reuse, arguments, plan, payload, document, _ = setup_reuse(tmp_path)
    decision = allow(reuse)
    request = tmp_path / "external-request.json"
    save(request, {"owner": arguments, "plan": plan, "decision": decision})
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": os.pathsep.join([str(Path(__file__).parent), str(Path(__file__).parents[1]/"runtime")])}
    child = subprocess.run([sys.executable, "-c",
        "from test_task_swarm_learning_reuse import fresh_run; fresh_run()", str(request)],
        capture_output=True, text=True, env=env, check=True, timeout=20)
    value = json.loads(child.stdout)
    assert value["pid"] != os.getpid()
    result = value["result"]
    assert result["receipt"]["review_passed"] and result["receipt"]["synthetic"]
    assert result["candidate"]["claims"][0]["claim"]["text"] == "Use measured memory budget 8."
    assert result["reuse_decision_digest"] == digest(decision)
    assert result["receipt"]["budget"]["remaining_attempts"] == 2
    execution = Path(arguments["target_owner"]).parent/"operations"/result["receipt"]["run_id"]
    binding = json.loads((execution/"context-binding.json").read_text())
    assert binding["decision_digest"] == digest(decision)
    assert binding["proposal_digest"] == digest(arguments["proposal"])
    delivered = json.loads((execution/"r0-apply-memory-input.json").read_text())
    assert delivered["view"]["parent_input_digest"] == digest(payload)
    assert delivered["view"]["objective"] == payload["objective"]
    source = learning_source(arguments["proposal"])
    assert any(s["text"] == source["text"] and s["start"] == 0 and s["end"] == len(source["text"])
               for s in delivered["view"]["spans"])
    assert arguments["proposal"]["selected"]["job_id"] == "r1-memory"
    assert "UNSELECTED_SENTINEL" not in json.dumps(delivered)

    # A separate synthetic control Task has the same purpose and budget, but
    # no selected learning, grant, or decision. Its real worker reports unknown.
    control = tmp_path/"control"; control.mkdir()
    root = control/"operations"; root.mkdir()
    no_learning = copy.deepcopy(payload)
    no_learning["task_id"] = "task-00000000-0000-4000-8000-000000000003"
    no_learning["sources"] = [s for s in no_learning["sources"] if s["key"] != learning_source(arguments["proposal"])["key"]]
    control_input, control_owner = control/"input.json", control/"owner.json"
    save(control_input, no_learning)
    control_document = copy.deepcopy(document)
    control_document.pop("learning_reuse")
    control_document["binding"].update(task_id=no_learning["task_id"], context_digest=digest(no_learning), active_home=str(root))
    control_document["storage"] = {"root": str(root), "mailbox": str(root/"mailbox.sqlite"), "payloads": str(root/"payloads")}
    control_document["source_checks"] = [{"path": str(control_input), "sha256": hashlib.sha256(control_input.read_bytes()).hexdigest()}]
    save(control_owner, control_document)
    control_plan = copy.deepcopy(plan)
    control_plan["parent_input_digest"] = digest(no_learning)
    control_plan["jobs"][0]["selected_spans"] = no_learning["objective"]["unknowns"]
    save(request, {"mode": "no_learning", "owner": str(control_owner), "input": str(control_input), "plan": control_plan})
    child = subprocess.run([sys.executable, "-c",
        "from test_task_swarm_learning_reuse import fresh_run; fresh_run()", str(request)],
        capture_output=True, text=True, env=env, check=True, timeout=20)
    negative = json.loads(child.stdout)["result"]
    assert purpose_digest(no_learning) == purpose_digest(payload)
    assert no_learning["objective"]["budget"] == payload["objective"]["budget"]
    assert negative["receipt"]["review_passed"] is False and negative["learning_candidate"] is None
    assert negative["receipt"]["budget"]["attempts_used"] == result["receipt"]["budget"]["attempts_used"] == 2
    control_run = root/negative["receipt"]["run_id"]
    worker = json.loads((control_run/"r0-apply-memory-result.json").read_text())["result"]
    assert worker["claims"][0]["status"] == "unknown"
    assert "reviewed observation" in worker["claims"][0]["text"]


def test_ignored_learning_fails_independent_critic_even_with_valid_source_quote(tmp_path):
    reuse, _, plan, _, _, _ = setup_reuse(tmp_path)
    result = run(reuse, plan, ReadingBackend(ignore=True), allow(reuse))
    assert not result["receipt"]["review_passed"]
    assert result["learning_candidate"] is None
    assert result["candidate"]["status"] == "unresolved"


def test_changed_valid_observation_changes_the_consumer_result(tmp_path):
    reuse, _, plan, _, _, _ = setup_reuse(tmp_path, observation=11)
    result = run(reuse, plan, ReadingBackend(), allow(reuse))
    assert result["receipt"]["review_passed"]
    assert result["candidate"]["claims"][0]["claim"]["text"] == "Use measured memory budget 11."


@pytest.mark.parametrize("outcome", ["reject", "revoke", "supersede"])
def test_current_negative_decision_prevents_any_consumer_call(tmp_path, outcome):
    reuse, _, plan, _, _, _ = setup_reuse(tmp_path)
    allow(reuse)
    decision = reuse.decide("ref/owner/fixture", "ref/review/one-learning", outcome,
                            "ref/decision/stop", expected_generation=1)
    backend = ReadingBackend()
    with pytest.raises(SwarmError, match="REUSE_NOT_ALLOWED"):
        run(reuse, plan, backend, decision)
    assert backend.calls == []


def test_no_decision_cannot_dispatch_or_silently_promote(tmp_path):
    reuse, _, plan, _, _, _ = setup_reuse(tmp_path)
    backend = ReadingBackend()
    with pytest.raises(SwarmError, match="REUSE_EVIDENCE_MISSING"):
        reuse.execute("a"*64, plan, backend, worker_actors=["worker-a"])
    assert backend.calls == []


def test_raw_coordinator_cannot_replace_real_decision_reader_with_success_callback(tmp_path):
    reuse, _, plan, _, _, _ = setup_reuse(tmp_path)
    backend = ReadingBackend()
    with pytest.raises(SwarmError, match="LOOP_REUSE_CONTEXT_REQUIRED"):
        execute_closed_loop(reuse.target_owner, reuse.target_input, plan, backend,
                            worker_actors=["worker-a"], clock=lambda: 1000)
    with pytest.raises(TypeError):
        execute_closed_loop(reuse.target_owner, reuse.target_input, plan, backend,
            worker_actors=["worker-a"], clock=lambda: 1000, context_guard=lambda: True,
            context_binding={"kind": "unverified"})
    assert backend.calls == []


def test_claim_excerpt_without_full_provenance_cannot_reach_worker(tmp_path):
    reuse, _, plan, payload, _, _ = setup_reuse(tmp_path)
    decision = allow(reuse)
    source = learning_source(reuse.proposal)
    plan["jobs"][0]["selected_spans"] = [span(source, "memory=8")]
    backend = ReadingBackend()
    with pytest.raises(SwarmError, match="REUSE_CLAIM_NOT_DELIVERED"):
        run(reuse, plan, backend, decision)
    assert backend.calls == []


def test_successful_reuse_replays_same_evidence_but_revocation_blocks_future_use(tmp_path):
    reuse, _, plan, _, _, _ = setup_reuse(tmp_path)
    decision = allow(reuse)
    backend = ReadingBackend()
    result = run(reuse, plan, backend, decision)
    assert run(reuse, plan, backend, decision, expected_receipt_sha256=result["receipt_sha256"])["duplicate"]
    assert len(backend.calls) == 2
    reuse.decide("ref/owner/fixture", "ref/review/one-learning", "revoke", "ref/decision/stop", expected_generation=1)
    with pytest.raises(SwarmError, match="REUSE_DECISION_STALE"):
        run(reuse, plan, backend, decision, expected_receipt_sha256=result["receipt_sha256"])
    assert len(backend.calls) == 2


def test_expired_objective_allows_only_anchored_readback_under_current_reuse_authority(tmp_path):
    reuse, arguments, plan, _, _, _ = setup_reuse(tmp_path, grant_lifetime=150)
    decision = allow(reuse)
    backend = ReadingBackend()
    result = run(reuse, plan, backend, decision)
    reuse.clock = lambda: 1125
    replay = run(reuse, plan, backend, decision, expected_receipt_sha256=result["receipt_sha256"])
    assert replay["duplicate"] and len(backend.calls) == 2
    with pytest.raises(SwarmError, match="OBJECTIVE_DEADLINE_INVALID"):
        run(reuse, plan, backend, decision)
    reader = ReuseOwner(**arguments, clock=lambda: 1125, allow_expired_objective=True)
    with pytest.raises(SwarmError, match="OBJECTIVE_DEADLINE_INVALID"):
        reader.decide("ref/owner/fixture", "ref/review/one-learning", "allow",
                      "ref/decision/late", expected_generation=1)
    reuse.clock = lambda: 1150
    with pytest.raises(SwarmError, match="REUSE_GRANT_EXPIRED"):
        run(reuse, plan, backend, decision, expected_receipt_sha256=result["receipt_sha256"])
    assert len(backend.calls) == 2


def test_cas_idempotency_and_old_allow_cannot_overwrite_revocation(tmp_path):
    reuse, _, _, _, _, _ = setup_reuse(tmp_path)
    first = allow(reuse)
    same = reuse.decide("ref/owner/fixture", "ref/review/one-learning", "allow",
                        "ref/decision/one-learning", expected_generation=0)
    assert same == first
    with pytest.raises(SwarmError, match="REUSE_DECISION_CONFLICT"):
        reuse.decide("ref/owner/fixture", "ref/review/one-learning", "reject",
                     "ref/decision/one-learning", expected_generation=1)
    reuse.decide("ref/owner/fixture", "ref/review/one-learning", "revoke", "ref/decision/stop", expected_generation=1)
    with pytest.raises(SwarmError, match="REUSE_DECISION_STALE"):
        reuse.current(digest(first))
    with pytest.raises(SwarmError, match="REUSE_GENERATION_CONFLICT"):
        reuse.decide("ref/owner/fixture", "ref/review/one-learning", "allow", "ref/decision/stale", expected_generation=1)


def test_same_generation_concurrent_decisions_have_exactly_one_winner(tmp_path):
    reuse, _, _, _, _, _ = setup_reuse(tmp_path)
    reuse.review("ref/review/one-learning", "verifier", "allow", "Exact observation supported.")
    barrier = threading.Barrier(2)
    def choose(key):
        barrier.wait()
        try:
            return reuse.decide("ref/owner/fixture", "ref/review/one-learning", "allow", key, expected_generation=0)
        except SwarmError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(choose, ["ref/decision/left", "ref/decision/right"]))
    assert sum(isinstance(value, dict) for value in result) == 1
    assert "REUSE_GENERATION_CONFLICT" in result


@pytest.mark.parametrize("operation", ["review", "decide", "current"])
def test_owner_change_during_scope_check_does_not_commit_or_admit(tmp_path, operation):
    reuse, _, _, _, doc, _ = setup_reuse(tmp_path)
    decision = allow(reuse)
    read_scope = reuse._scope
    def changed_scope(**kwargs):
        scope = read_scope(**kwargs)
        doc["learning_reuse"]["policy_revision_ref"] = "ref/policy/revised-during-read"
        save(reuse.target_owner, doc)
        return scope
    reuse._scope = changed_scope
    with pytest.raises(SwarmError, match="REUSE_AUTHORITY_CHANGED"):
        if operation == "review":
            reuse.review("ref/review/changed", "verifier", "allow", "Current scope checked.")
        elif operation == "decide":
            reuse.decide("ref/owner/fixture", "ref/review/one-learning", "revoke",
                         "ref/decision/changed", expected_generation=1)
        else:
            reuse.current(digest(decision))
    with reuse.state._connect() as db:
        assert db.execute("SELECT count(*) FROM learning_reuse_reviews").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM learning_reuse_decisions").fetchone()[0] == 1


@pytest.mark.parametrize("mutation", ["receipt", "proposal", "grant", "source", "reviewer", "expiry"])
def test_drift_after_decision_prevents_consumer(tmp_path, mutation):
    reuse, args, plan, _, doc, origin = setup_reuse(tmp_path)
    decision = allow(reuse)
    if mutation == "receipt":
        path = reuse.directory / "receipt.json"
        value = json.loads(path.read_text()); value["rounds"] = 1; save(path, value)
    elif mutation == "proposal":
        reuse.proposal["selected"]["claim"]["text"] = "memory=999"
    elif mutation == "source":
        origin[1].write_text(origin[1].read_text() + " ", encoding="utf-8")
    elif mutation == "grant":
        doc["learning_reuse"]["policy_revision_ref"] = "ref/policy/new"; save(Path(args["target_owner"]), doc)
    elif mutation == "reviewer":
        doc["actors"]["verifier"]["actor_status"] = "revoked"; save(Path(args["target_owner"]), doc)
    else:
        reuse.clock = lambda: 1100
    backend = ReadingBackend()
    with pytest.raises((SwarmError, ValueError)):
        run(reuse, plan, backend, decision)
    assert backend.calls == []


def test_revocation_after_work_keeps_result_unaccepted(tmp_path):
    reuse, _, plan, _, _, _ = setup_reuse(tmp_path)
    decision = allow(reuse)
    def revoke():
        reuse.decide("ref/owner/fixture", "ref/review/one-learning", "revoke", "ref/decision/stop", expected_generation=1)
    with pytest.raises(SwarmError):
        run(reuse, plan, ReadingBackend(after_work=revoke), decision)
    b = Path(reuse.target_input)
    owner = json.loads(reuse.target_owner.read_text())
    import sqlite3
    database = Path(owner["storage"]["root"]) / ("task-run-" + digest(["task-00000000-0000-4000-8000-000000000002", 1])[:32]) / "execution.sqlite"
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT count(*) FROM jobs WHERE state='accepted'").fetchone()[0] == 0


def test_review_and_decision_require_distinct_actual_current_owner_actors(tmp_path):
    reuse, _, _, _, _, _ = setup_reuse(tmp_path)
    with pytest.raises(SwarmError, match="REUSE_REVIEWER_NOT_AUTHORIZED"):
        reuse.review("ref/review/one-learning", "worker-a", "allow", "self review")
    reuse.review("ref/review/one-learning", "verifier", "reject", "Does not support the proposed scope.")
    with pytest.raises(SwarmError, match="REUSE_REVIEW_REJECTED"):
        reuse.decide("ref/owner/fixture", "ref/review/one-learning", "allow", "ref/decision/a", expected_generation=0)
    with pytest.raises(SwarmError, match="REUSE_DECISION_NOT_OWNER"):
        reuse.decide("worker-a", "ref/review/one-learning", "reject", "ref/decision/a", expected_generation=0)


def test_cli_explicit_review_decision_run_and_anchor_replay(tmp_path):
    reuse, arguments, plan, payload, _, _ = setup_reuse(tmp_path, now=time.time())
    context, plan_path, scenario_path = (tmp_path/name for name in ("context.json", "plan.json", "scenario.json"))
    save(context, arguments); save(plan_path, plan)
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1]/"runtime"), "PYTHONDONTWRITEBYTECODE": "1"}
    command = [sys.executable, "-B", "-m", "task_swarm.learning_reuse"]
    def cli(*args):
        response = subprocess.run([*command, *args], env=env, capture_output=True, text=True, timeout=20)
        assert response.returncode == 0, response.stderr
        return json.loads(response.stdout)
    proposal = cli("propose", "--owner", arguments["origin_owner"], "--input", arguments["origin_input"],
                   "--anchor", arguments["anchor"], "--claim-index", str(arguments["proposal"]["claim_index"]))
    assert proposal == arguments["proposal"]
    cli("review", "--context", str(context), "--review-ref", "ref/review/cli", "--reviewer", "verifier",
        "--outcome", "allow", "--reason", "The exact observation is independently reviewed for this Task.")
    decision = cli("decide", "--context", str(context), "--actor", "ref/owner/fixture", "--review-ref", "ref/review/cli",
                   "--outcome", "allow", "--key", "ref/decision/cli", "--expected-generation", "0")
    assert cli("current", "--context", str(context), "--decision-digest", digest(decision)) == decision
    # Explicit scenario results are computed from the delivered learning body.
    from task_swarm.closed_loop_context import derive_child_view
    view = derive_child_view(payload, "r0-apply-memory", plan["jobs"][0]["selected_spans"], plan_digest=digest(plan))
    backend = ReadingBackend()
    work = backend.produce({"job_id": "r0-apply-memory", "role": "work", "view": view}, None, actor_ref="worker-a")["result"]
    critic = backend.review({"job_id": "r0-critic", "role": "critic", "round": 0, "view": view,
        "reports": {"r0-apply-memory": work}, "criteria": loop_criteria(payload)}, None, actor_ref="verifier")["result"]
    save(scenario_path, {"work": {"r0-apply-memory": work}, "critics": {"0": critic}, "repair_plan": None})
    run_args = ("run", "--context", str(context), "--decision-digest", digest(decision), "--plan", str(plan_path),
                "--simulation", str(scenario_path), "--worker", "worker-a")
    result = cli(*run_args)
    assert result["receipt"]["review_passed"] and result["reuse_decision_digest"] == digest(decision)
    assert cli(*run_args, "--receipt-sha256", result["receipt_sha256"])["duplicate"]
