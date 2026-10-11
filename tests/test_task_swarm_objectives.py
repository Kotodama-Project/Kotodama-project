"""Opt-in owner-bound objectives; all data and backends are synthetic."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest job")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from task_swarm.protocol import SwarmError, digest
from task_swarm.task_backend import SyntheticTaskBackend, TaskBackend
from task_swarm.task_contract import WORK_JOBS, criteria, make_plan, validate_input, validate_review
from task_swarm.task_runner import execute_task
from task_swarm.task_schemas import review_schema


def source(key, revision, text):
    return {"key": key, "revision": revision, "text": text,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def span(record, text):
    start = record["text"].index(text)
    return {"source_key": record["key"], "source_revision": record["revision"],
            "start": start, "end": start + len(text)}


def fixture():
    original = source("a"*64, 1, "計測結果を整理する")
    current = source("a"*64, 2, "速度とメモリを同じ条件で比較する\n設定の変更は提案だけに留める\n本番の同時利用数は不明\n計測条件と未解決点を示す")
    definitions = source("b"*64, 4, "OUT-INTENT\nKGI-INTENT\nINIT-DYNAMIC-AGENT-CONTEXT")
    request, constraint, unknown, acceptance = current["text"].splitlines()
    payload = {"version": 2, "task_id": "task-00000000-0000-4000-8000-000000000001", "revision": 5,
               "request": request, "acceptance": [acceptance], "sources": [original, current, definitions],
               "objective": {"owner_ref": "ref/owner/fixture",
                    "intent": {"original": span(original, original["text"]), "replacements": [span(current, request)]},
                    "references": [{"kind": kind, "id": identifier, "source": span(definitions, identifier)}
                        for kind, identifier in (("goal", "OUT-INTENT"), ("kgi", "KGI-INTENT"),
                                                 ("initiative", "INIT-DYNAMIC-AGENT-CONTEXT"))],
                    "constraints": [span(current, constraint)], "unknowns": [span(current, unknown)],
                    "acceptance": [span(current, acceptance)],
                    "budget": {"attempt_budget": 4, "deadline": 1100},
                    "stop_conditions": ["cancelled", "binding_changed", "deadline_exceeded"],
                    "rollback": "not_applicable_read_only"}}
    binding = {"task_id": payload["task_id"], "revision": 5, "context_digest": digest(payload),
               "owner_ref": "ref/owner/fixture", "active_home": "fixture",
               "authority_ref": "ref/authority/fixture", "capability_ref": "ref/capability/swarm_research",
               "expires_at": 1200, "status": "active"}
    return payload, binding


def checked(payload, binding):
    return validate_input(payload, {**binding, "context_digest": digest(payload)}, now=1000)


def test_v2_preserves_original_and_correction_and_binds_smaller_budget():
    payload, binding = fixture()
    assert validate_input(payload, binding, now=1000) == payload
    plan = make_plan(payload, binding, now=1000)
    assert plan["budget"] == {"attempt_budget": 4, "concurrency": 3, "verifier_reserve": 1, "deadline": 1100}
    assert list(criteria(payload)) == ["C1", "C2", "C3", "C4", "U1", "O1", "Q1"]
    assert "設定の変更" in criteria(payload)["O1"] and "不明" in criteria(payload)["Q1"]
    assert len(plan["jobs"]) == 4
    assert review_schema(payload)["properties"]["validations"]["minItems"] == 7
    assert "text" not in payload["objective"]["intent"]["original"]
    assert make_plan(payload, binding, now=1001) == plan


def test_v1_payload_and_plan_keep_the_original_shape_and_defaults():
    payload, binding = fixture()
    payload.pop("objective")
    payload["version"] = 1
    binding["context_digest"] = digest(payload)
    assert validate_input(payload, binding, now=1000) == payload
    assert make_plan(payload, binding, now=1000)["budget"] == {
        "attempt_budget": 6, "concurrency": 3, "verifier_reserve": 1, "deadline": 1200}
    assert list(criteria(payload)) == ["C1", "C2", "C3", "C4", "U1"]


@pytest.mark.parametrize("change,code", [
    (lambda p: p.pop("objective"), "TASK_INPUT_INVALID"),
    (lambda p: p.update(version=1), "TASK_INPUT_INVALID"),
    (lambda p: p["objective"].update(owner_ref="ref/owner/other"), "OBJECTIVE_OWNER_MISMATCH"),
    (lambda p: p["objective"].update(privilege="write"), "OBJECTIVE_INVALID"),
    (lambda p: p["objective"].pop("unknowns"), "OBJECTIVE_INVALID"),
    (lambda p: p["objective"]["intent"]["replacements"].clear(), "OBJECTIVE_SOURCE_STALE"),
    (lambda p: p["objective"]["intent"]["replacements"].append(copy.deepcopy(p["objective"]["intent"]["replacements"][0])), "OBJECTIVE_CORRECTION_ORDER"),
    (lambda p: p["objective"]["intent"]["original"].update(source_key="c"*64), "OBJECTIVE_SOURCE_UNKNOWN"),
    (lambda p: p["objective"]["intent"]["original"].update(source_revision=True), "INVALID_LIMIT"),
    (lambda p: p["objective"]["intent"]["original"].update(start=True), "INVALID_LIMIT"),
    (lambda p: p["objective"]["intent"]["original"].update(end=0), "INVALID_LIMIT"),
    (lambda p: p["objective"]["intent"]["original"].update(quote="extra copy"), "OBJECTIVE_SPAN_INVALID"),
    (lambda p: p.update(request="異なる目的"), "OBJECTIVE_REQUEST_MISMATCH"),
    (lambda p: p.update(acceptance=["別の受入条件"]), "OBJECTIVE_ACCEPTANCE_MISMATCH"),
    (lambda p: p["objective"]["constraints"].append(copy.deepcopy(p["objective"]["constraints"][0])), "OBJECTIVE_SPAN_DUPLICATE"),
    (lambda p: p["objective"]["references"].clear(), "OBJECTIVE_REFERENCES_INVALID"),
    (lambda p: p["objective"]["references"].pop(0), "OBJECTIVE_GOAL_REQUIRED"),
    (lambda p: p["objective"]["references"][0].update(kind="metric"), "OBJECTIVE_REFERENCE_INVALID"),
    (lambda p: p["objective"]["references"][0].update(id="KGI-INTENT"), "OBJECTIVE_REFERENCE_INVALID"),
    (lambda p: p["objective"]["references"][0].update(id="OUT-UNKNOWN"), "OBJECTIVE_REFERENCE_MISMATCH"),
    (lambda p: p["objective"]["references"].append(copy.deepcopy(p["objective"]["references"][0])), "OBJECTIVE_REFERENCE_DUPLICATE"),
    (lambda p: p["objective"]["budget"].update(attempt_budget=7), "INVALID_LIMIT"),
    (lambda p: p["objective"]["budget"].update(attempt_budget=3), "INVALID_LIMIT"),
    (lambda p: p["objective"]["budget"].update(attempt_budget=True), "INVALID_LIMIT"),
    (lambda p: p["objective"]["budget"].update(concurrency=4), "OBJECTIVE_BUDGET_INVALID"),
    (lambda p: p["objective"]["budget"].update(deadline=1201), "OBJECTIVE_DEADLINE_INVALID"),
    (lambda p: p["objective"]["budget"].update(deadline=1000), "OBJECTIVE_DEADLINE_INVALID"),
    (lambda p: p["objective"]["budget"].update(deadline="1100"), "INVALID_LIMIT"),
    (lambda p: p["objective"].update(stop_conditions=[]), "OBJECTIVE_STOP_INVALID"),
    (lambda p: p["objective"].update(rollback="write-back"), "OBJECTIVE_ROLLBACK_INVALID"),
])
def test_invalid_objectives_are_rejected_even_with_a_matching_input_digest(change, code):
    payload, binding = fixture()
    change(payload)
    with pytest.raises(SwarmError) as raised:
        checked(payload, binding)
    assert raised.value.code == code


def test_later_source_revision_invalidates_current_goal_and_request_spans():
    for key in ("a", "b"):
        payload, binding = fixture()
        payload["sources"].append(source(key*64, 6, "新しい版"))
        with pytest.raises(SwarmError) as raised:
            checked(payload, binding)
        assert raised.value.code == "OBJECTIVE_SOURCE_STALE"


def test_no_implicit_unknown_or_acceptance_is_invented():
    payload, binding = fixture()
    payload["objective"]["unknowns"] = []
    checked(payload, binding)
    assert "Q1" not in criteria(payload)
    payload["objective"]["acceptance"] = []
    with pytest.raises(SwarmError) as raised:
        checked(payload, binding)
    assert raised.value.code == "OBJECTIVE_ACCEPTANCE_MISMATCH"


def test_old_task_digest_and_review_cannot_be_reused_after_objective_change():
    payload, binding = fixture()
    old = copy.deepcopy(payload)
    backend = SyntheticTaskBackend()
    reports = {job: backend.produce(job, payload, None)["result"] for job in WORK_JOBS}
    review = backend.review(payload, reports, None)["result"]
    payload["objective"]["budget"]["deadline"] -= 1
    with pytest.raises(SwarmError) as raised:
        validate_input(payload, binding, now=1000)
    assert raised.value.code == "TASK_CONTEXT_MISMATCH"
    with pytest.raises(SwarmError) as raised:
        validate_review(review, payload, reports)
    assert raised.value.code == "REVIEW_CONTEXT_MISMATCH"
    fresh = {**binding, "context_digest": digest(payload)}
    assert make_plan(payload, fresh, now=1000)["run_id"] == make_plan(old, binding, now=1000)["run_id"]
    assert make_plan(payload, fresh, now=1000)["jobs"] != make_plan(old, binding, now=1000)["jobs"]


def test_verifier_must_cover_constraints_and_unknowns():
    payload, _ = fixture()
    backend = SyntheticTaskBackend()
    reports = {job: backend.produce(job, payload, None)["result"] for job in WORK_JOBS}
    review = backend.review(payload, reports, None)["result"]
    assert validate_review(review, payload, reports) == review
    review["validations"] = [item for item in review["validations"] if item["criterion_id"] != "Q1"]
    with pytest.raises(SwarmError) as raised:
        validate_review(review, payload, reports)
    assert raised.value.code == "REVIEW_COVERAGE_REQUIRED"


def test_real_backend_prompt_carries_exact_objective_and_review_criteria(tmp_path):
    payload, _ = fixture()
    backend = TaskBackend("not-executed", task_codex_home=tmp_path)
    calls = []
    backend.codex = SimpleNamespace(invoke=lambda *args, **kwargs: calls.append((args, kwargs)))
    options = {"timeout": 10, "cancel_event": threading.Event(), "on_process": lambda *args: None}
    reports = {job: SyntheticTaskBackend().produce(job, payload, None)["result"] for job in WORK_JOBS}
    backend.produce("facts", payload, tmp_path/"facts", **options)
    backend.review(payload, reports, tmp_path/"review", **options)
    packet = json.loads(calls[0][0][0].split("\n", 1)[1])
    review_packet = json.loads(calls[1][0][0].split("\n", 1)[1])
    assert packet["task"] == payload
    assert review_packet["task"] == payload and review_packet["criteria"] == criteria(payload)
    assert review_packet["context_digest"] == digest(payload)
    assert all(kwargs["confidential"] for _, kwargs in calls)


def owner_files(tmp_path):
    payload, binding = fixture()
    root = tmp_path/"run"
    root.mkdir()
    binding["active_home"] = str(root)
    payload_path = tmp_path/"input.json"
    payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    owner = {"binding": binding, "actors": {
        actor: {"epoch": 1, "invocation_ref": "fixture-"+actor, "actor_status": "active",
                "capability_ref": binding["capability_ref"], "peers": []}
        for actor in (*["worker-"+job for job in WORK_JOBS], "verifier")},
        "allowed_actions": [], "source_checks": [{"path": str(payload_path),
            "sha256": hashlib.sha256(payload_path.read_bytes()).hexdigest()}],
        "storage": {"root": str(root), "mailbox": str(root/"mailbox.sqlite"), "payloads": str(root/"payloads")}}
    owner_path = tmp_path/"owner.json"
    owner_path.write_text(json.dumps(owner), encoding="utf-8")
    return payload, owner_path, payload_path, root


def test_v2_reaches_existing_executor_and_replay_without_changing_task_owner(tmp_path):
    payload, owner, file, root = owner_files(tmp_path)
    before = owner.read_bytes()
    result = execute_task(owner, file, SyntheticTaskBackend(), clock=lambda: 1000)
    assert result["result"]["state"] == "needs_review"
    assert result["receipt"]["task_state_changed"] is False
    assert result["receipt"]["input_digest"] == digest(payload)
    assert owner.read_bytes() == before
    run = next(root.glob("task-run-*"))
    assert json.loads((run/"input.json").read_text(encoding="utf-8")) == payload
    assert json.loads((run/"plan.json").read_text())["budget"]["deadline"] == 1100
    repeated = execute_task(owner, file, SyntheticTaskBackend(), clock=lambda: 1000,
                            expected_receipt_sha256=result["receipt_sha256"])
    assert repeated["duplicate"] and repeated["receipt"] == result["receipt"]


def test_objective_deadline_stops_actual_executor_before_receipt(tmp_path):
    _, owner, file, root = owner_files(tmp_path)
    current_time = [1000]
    class Backend(SyntheticTaskBackend):
        def produce(self, *args, **kwargs):
            current_time[0] = 1101
            return super().produce(*args, **kwargs)
    with pytest.raises(SwarmError) as raised:
        execute_task(owner, file, Backend(), clock=lambda: current_time[0])
    assert raised.value.code in {"RUN_CANCELLED", "DEADLINE_EXPIRED"}
    assert not list(root.glob("task-run-*/receipt.json"))


def test_finished_receipt_replay_survives_objective_deadline_without_dispatch(tmp_path):
    _, owner, file, _ = owner_files(tmp_path)
    first = execute_task(owner, file, SyntheticTaskBackend(), clock=lambda: 1000)
    class NoDispatch(SyntheticTaskBackend):
        def produce(self, *args, **kwargs):
            pytest.fail("receipt replay must not dispatch a worker")
        def review(self, *args, **kwargs):
            pytest.fail("receipt replay must not dispatch a reviewer")
    repeated = execute_task(owner, file, NoDispatch(), clock=lambda: 1150,
                            expected_receipt_sha256=first["receipt_sha256"])
    assert repeated["duplicate"] and repeated["receipt"] == first["receipt"]


@pytest.mark.parametrize("anchored,code", [(False, "OBJECTIVE_DEADLINE_INVALID"),
                                          (True, "RUN_REPLAY_MISSING")])
def test_expired_objective_cannot_create_a_run_even_with_replay_anchor(tmp_path, anchored, code):
    _, owner, file, root = owner_files(tmp_path)
    with pytest.raises(SwarmError) as raised:
        execute_task(owner, file, SyntheticTaskBackend(), clock=lambda: 1150,
                     expected_receipt_sha256="a"*64 if anchored else None)
    assert raised.value.code == code
    assert not list(root.iterdir())


@pytest.mark.parametrize("mode,code", [("owner_expired", "EXPIRED_BINDING"),
                                      ("revoked", "INACTIVE_TASK"),
                                      ("cancelled", "RUN_CANCELLED"),
                                      ("wrong_anchor", "RUN_REPLAY_ANCHOR_MISMATCH"),
                                      ("changed_artifact", "RUN_ARTIFACT_CHANGED")])
def test_late_replay_still_requires_live_owner_and_exact_saved_evidence(tmp_path, mode, code):
    _, owner, file, root = owner_files(tmp_path)
    first = execute_task(owner, file, SyntheticTaskBackend(), clock=lambda: 1000)
    event = threading.Event()
    now = 1201 if mode == "owner_expired" else 1150
    if mode == "revoked":
        document = json.loads(owner.read_text(encoding="utf-8"))
        document["binding"]["status"] = "cancelled"
        owner.write_text(json.dumps(document), encoding="utf-8")
    if mode == "cancelled":
        event.set()
    if mode == "changed_artifact":
        result = next(root.glob("task-run-*/result.json"))
        result.write_bytes(result.read_bytes()+b" ")
    with pytest.raises(SwarmError) as raised:
        execute_task(owner, file, SyntheticTaskBackend(), clock=lambda: now, cancel_event=event,
                     expected_receipt_sha256="a"*64 if mode == "wrong_anchor" else first["receipt_sha256"])
    assert raised.value.code == code
