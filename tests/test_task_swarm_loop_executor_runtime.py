"""Real fixture children and saved evidence across the finite loop lifecycle."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import textwrap

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest environment")

from test_task_swarm_loop_executor_contract import CHILD, case
from task_swarm.closed_loop import execute_closed_loop
from task_swarm.closed_loop_contract import loop_criteria
from task_swarm.protocol import SwarmError, canonical, digest
from task_swarm.task_backend import TaskBackend
from task_swarm.task_runner import read_json


CALCULATION = textwrap.dedent('''
    acquired = []
    core = request["input"].get("core", request["input"])
    actual = {}
    evidence = {}
    for material in request["materials"]:
        with pathlib.Path(material["path"]).open("rb") as stream:
            data = stream.read(material["bytes"] + 1)
        assert len(data) == material["bytes"] and hashlib.sha256(data).hexdigest() == material["sha256"]
        acquired.append({"path": material["relative_path"], "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        actual[material["relative_path"]] = int(data.decode("utf-8").strip())
        record = next(s for s in core["view"]["spans"] if s["source_key"] == material["source_key"])
        evidence[material["relative_path"]] = {k: record[k] for k in ("source_key", "source_revision", "start", "end")} | {"quote": record["text"]}
    (cwd / "child-acquisition.json").write_bytes(json.dumps(acquired).encode("utf-8"))
    if core["role"] == "work":
        name = next(iter(actual))
        partial = name == "DocB.txt" and core["round"] == 0
        answer = "unknown" if partial else str(actual[name])
        result = {"job_id": request["dispatch"]["job_id"], "summary": "actual local bytes", "conflicts": [],
            "claims": [{"text": answer, "status": "unknown" if partial else "supported",
                        "evidence": [] if partial else [evidence[name]]}]}
    elif core["role"] == "prerequisite_review":
        report = request["input"]["report"]
        valid = report["claims"][0]["text"] == str(actual["DocA.txt"])
        result = {"kind": "prerequisite_review", "version": 1,
            "descriptor_sha256": request["input"]["descriptor_sha256"], "report_sha256": request["input"]["report_sha256"],
            "validations": [{"criterion_id": key, "status": "passed" if valid else "failed",
                "evidence": [{"job_id": report["job_id"], "claim_index": 0}]} for key in core["gate"]]}
    else:
        reports = request["input"]["reports"]
        b_job = "r1-repair-doc-b" if core["round"] else "r0-doc-b"
        valid = reports[b_job]["claims"][0]["text"] == str(actual["DocB.txt"])
        gap = {key: value for key, value in evidence["DocB.txt"].items() if key != "quote"}
        result = {"parent_input_digest": core["view"]["parent_input_digest"], "plan_digest": core["view"]["plan_digest"],
            "round": core["round"], "report_digests": request["input"]["report_digests"], "validations": []}
        for key, assigned in core["required_evidence_jobs"].items():
            failed = key == "A3" and not valid
            result["validations"].append({"criterion_id": key, "status": "failed" if failed else "passed",
                "evidence": [] if failed else [{"job_id": job, "claim_index": 0} for job in assigned],
                "gap_reason": "DocB value is not established" if failed else None,
                "source_spans": [gap] if failed else []})
''')


def setup_executor(tmp_path, *, second=13, budget=6, dependency=False, child=None):
    payload, _, _, _, _, owner, document = case(tmp_path, second=second)
    script = CHILD.decode()
    script = script[:script.index("acquired = []")] + CALCULATION + script[script.index("output = pathlib.Path"):]
    script = script.replace('cwd = pathlib.Path.cwd()', '''cwd = pathlib.Path.cwd()
import os, sqlite3
with sqlite3.connect(cwd.parent.parent / "execution.sqlite") as db:
    row = db.execute("SELECT identity_json FROM attempts WHERE job_id=? AND state='leased'",
                     (request["dispatch"]["job_id"],)).fetchone()
assert row is not None and json.loads(row[0])["pid"] == os.getpid()
''')
    if child is not None:
        script = child(script)
    (tmp_path/"worker.py").write_text(script)
    current = payload["sources"][1]
    policy_span = payload["objective"]["constraints"][0]
    declaration = json.loads(current["text"][policy_span["start"]:policy_span["end"]])
    raw = (tmp_path/"worker.py").read_bytes()
    declaration["executable"].update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
    current["text"] = current["text"][:policy_span["start"]] + canonical(declaration)
    policy_span["end"] = len(current["text"])
    payload["acceptance"] = ["Preserve DocA", "Preserve uncertainty", "Acquire DocB"]
    payload["objective"]["acceptance"] = []
    for sentence in payload["acceptance"]:
        at = len(current["text"]) + 1
        current["text"] += "\n" + sentence
        payload["objective"]["acceptance"].append({"source_key": current["key"], "source_revision": 2,
                                                   "start": at, "end": len(current["text"])})
    current["sha256"] = hashlib.sha256(current["text"].encode()).hexdigest()
    payload["objective"]["budget"]["attempt_budget"] = budget
    expected = list(loop_criteria(payload))
    plan = {"version": 2 if dependency else 1, "parent_input_digest": digest(payload), "jobs": []}
    for number, doc in enumerate(payload["sources"][-2:]):
        name = "doc-a" if number == 0 else "doc-b"
        plan["jobs"].append({"job_id": name, "purpose": "Acquire " + name,
            "criterion_ids": [key for key in expected if key != "A3"] if not number else [key for key in expected if key not in {"A1", "A2"}],
            "selected_spans": [{"source_key": doc["key"], "source_revision": 1, "start": 0, "end": len(doc["text"])}],
            **({"requires": [] if number == 0 else ["doc-a"]} if dependency else {})})
    actors = ["worker-a", "worker-b"]
    document["actors"] = {actor: {**copy.deepcopy(document["actors"]["worker"]), "invocation_ref": "fixture-" + actor}
                          for actor in [*actors, "verifier"]}
    file = tmp_path/"input.json"
    file.write_text(canonical(payload))
    document["binding"]["context_digest"] = digest(payload)
    document["source_checks"] = [{"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                                 for path in (file, tmp_path/"worker.py", tmp_path/"DocA.txt", tmp_path/"DocB.txt")]
    owner.write_text(canonical(document))
    (tmp_path/"operations").mkdir(exist_ok=True)
    return owner, file, document, payload, plan, actors


def execute(setup, **kwargs):
    owner, file, _, _, plan, actors = setup
    clock = kwargs.pop("clock", lambda: 1000)
    return execute_closed_loop(owner, file, plan, TaskBackend(owner.parent/"worker.py", loop_mode="local_executable_fixture"),
                               worker_actors=actors, clock=clock, **kwargs)


def run_directory(setup):
    payload = setup[3]
    return setup[0].parent/"operations"/("task-run-" + digest([payload["task_id"], payload["revision"]])[:32])


@pytest.mark.parametrize("second", [13, 23])
def test_real_children_repair_only_doc_b_and_replay_without_process(tmp_path, second):
    setup = setup_executor(tmp_path, second=second)
    owner_before = setup[0].read_bytes()
    result = execute(setup)
    directory = run_directory(setup)
    assert result["receipt"]["review_passed"] and result["receipt"]["budget"]["attempts_used"] == 5
    assert result["receipt"]["model_runtime_verified"] is False and setup[0].read_bytes() == owner_before
    assert read_json(directory/"r0-doc-a-result.json")["result"]["claims"][0]["text"] == "5"
    assert read_json(directory/"r0-doc-b-result.json")["result"]["claims"][0]["text"] == "unknown"
    assert read_json(directory/"r1-repair-doc-b-result.json")["result"]["claims"][0]["text"] == str(second)
    assert {job for job in read_json(directory/"execution.json")["jobs"] if job.startswith("r1-")} == {"r1-repair-doc-b", "r1-critic"}
    snapshot = read_json(directory/"execution.json")
    ids = []
    for job, row in snapshot["jobs"].items():
        attempt = row["current_attempt"]
        assert attempt["identity"]["kind"] == "process"
        value = read_json(directory/(job+"-result.json"))
        runtime = value["receipt"]["runtime"]
        raw = Path(runtime["paths"]["input"]).read_bytes()
        assert raw == (Path(runtime["paths"]["attempt_dir"])/"child-input.bin").read_bytes()
        assert json.loads(raw)["dispatch"]["attempt"] == attempt["attempt"]
        ids.append(value["receipt"]["invocation_ref"])
        from task_swarm.codex import _same_process
        assert not _same_process(attempt["identity"]["pid"], attempt["identity"]["created_at"])
    assert len(set(ids)) == 5
    before = sorted(str(path) for path in directory.rglob("attempt-*"))
    assert execute(setup, expected_receipt_sha256=result["receipt_sha256"])["duplicate"]
    assert execute(setup, expected_receipt_sha256=result["receipt_sha256"],
                   clock=lambda: setup[3]["objective"]["budget"]["deadline"] + 1)["duplicate"]
    assert sorted(str(path) for path in directory.rglob("attempt-*")) == before


def test_original_budget_four_returns_unresolved_without_repair_or_learning(tmp_path):
    setup = setup_executor(tmp_path, budget=4)
    result = execute(setup)
    assert result["receipt"]["budget"]["attempts_used"] == 3
    assert result["candidate"]["stop_reason"] == "attempt_budget_exhausted"
    assert result["learning_candidate"] is None
    assert not (run_directory(setup)/"r1-repair-doc-b-input.json").exists()


def test_dependency_release_uses_process_evidence_and_rereads(tmp_path):
    setup = setup_executor(tmp_path, dependency=True)
    result = execute(setup)
    assert result["receipt"]["version"] == 3 and result["receipt"]["budget"]["attempts_used"] == 6
    directory = run_directory(setup)
    b = read_json(directory/"r0-doc-b-input.json")
    assert b["prerequisite"]["report"]["claims"][0]["text"] == "5"
    assert execute(setup, expected_receipt_sha256=result["receipt_sha256"])["duplicate"]


def interrupted(setup):
    def stop(gap):
        raise RuntimeError("pause after first critic")
    with pytest.raises(RuntimeError, match="pause after first critic"):
        execute(setup, repair_planner=stop)


@pytest.mark.parametrize("mutation", ["epoch", "invocation_ref", "raw_owner"])
def test_inspection_without_metadata_rejects_current_actor_and_owner_changes(tmp_path, mutation):
    from task_swarm.repair_planning import inspect_repair
    setup = setup_executor(tmp_path)
    interrupted(setup)
    assert inspect_repair(setup[0], setup[1], clock=lambda: 1000)["admitted"] is False
    document = setup[2]
    if mutation == "epoch":
        document["actors"]["worker-a"]["epoch"] += 1
    elif mutation == "invocation_ref":
        document["actors"]["verifier"]["invocation_ref"] += "-replacement"
    setup[0].write_text(canonical(document) + ("\n" if mutation == "raw_owner" else ""))
    with pytest.raises(SwarmError, match="STALE_ACTOR|OWNER_INPUT_CHANGED"):
        inspect_repair(setup[0], setup[1], clock=lambda: 1000)


@pytest.mark.parametrize("mutation", ["actor", "runtime_input", "saved_result", "saved_input", "deadline", "cancel"])
def test_last_policy_callback_mutation_is_fenced_before_inspection_return(tmp_path, monkeypatch, mutation):
    from task_swarm import loop_executor_runtime as saved
    from task_swarm import loop_executor as policy_module
    from task_swarm.closed_loop_cancellation import cancel_closed_loop
    from task_swarm.repair_planning import inspect_repair
    setup = setup_executor(tmp_path)
    interrupted(setup)
    now = [1000]
    operation = lambda: inspect_repair(setup[0], setup[1], clock=lambda: now[0])
    original = saved.check_current_executor_policy
    observed = []
    def count(*args, **kwargs):
        observed.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(saved, "check_current_executor_policy", count)
    monkeypatch.setattr(policy_module, "check_current_executor_policy", count)
    assert operation()["admitted"] is False
    cutoff = len(observed)
    assert cutoff > 0
    observed.clear()
    def mutate_at_last_check(*args, **kwargs):
        result = count(*args, **kwargs)
        if len(observed) == cutoff:
            if mutation == "actor":
                document = copy.deepcopy(setup[2])
                document["actors"]["verifier"]["epoch"] += 1
                document["actors"]["verifier"]["invocation_ref"] += "-new"
                setup[0].write_text(canonical(document))
            elif mutation == "deadline":
                now[0] = setup[3]["objective"]["budget"]["deadline"] + 1
                assert now[0] < setup[2]["binding"]["expires_at"]
            elif mutation == "cancel":
                cancel_closed_loop(setup[0], setup[1], clock=lambda: now[0])
            else:
                directory = run_directory(setup)
                response = read_json(directory/"r0-doc-a-result.json")
                target = Path(response["receipt"]["runtime"]["paths"]["input"]) if mutation == "runtime_input" else (
                    directory/("r0-doc-a-result.json" if mutation == "saved_result" else "input.json"))
                target.write_bytes(target.read_bytes() + b"\n")
        return result
    monkeypatch.setattr(saved, "check_current_executor_policy", mutate_at_last_check)
    monkeypatch.setattr(policy_module, "check_current_executor_policy", mutate_at_last_check)
    # Read-only inspection checks the original owner bytes as part of its live
    # DB cut before the executor's more specific actor fence.
    expected = {"actor": "STALE_ACTOR|OWNER_INPUT_CHANGED|STALE_BINDING", "runtime_input": "RUN_RUNTIME_ARTIFACT_CHANGED",
                "saved_result": "RUN_ARTIFACT_CHANGED", "saved_input": "RUN_ARTIFACT_CHANGED",
                "deadline": "OBJECTIVE_DEADLINE_INVALID|DEADLINE_EXPIRED", "cancel": "RUN_CANCELLED"}
    with pytest.raises(SwarmError, match=expected[mutation]):
        operation()
    assert len(observed) == cutoff


@pytest.mark.parametrize("artifact", ["input", "process", "events", "schema", "executable"])
def test_saved_runtime_artifact_tamper_refuses_anchored_replay(tmp_path, artifact):
    setup = setup_executor(tmp_path)
    result = execute(setup)
    directory = run_directory(setup)
    response = read_json(directory/"r0-doc-a-result.json")
    target = Path(response["receipt"]["runtime"]["paths"][artifact])
    target.chmod(0o600)
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(SwarmError, match="RUN_RUNTIME_ARTIFACT_CHANGED"):
        execute(setup, expected_receipt_sha256=result["receipt_sha256"])


def test_terminal_resume_and_learning_origin_revalidate_real_proofs(tmp_path, monkeypatch):
    from task_swarm import closed_loop
    from task_swarm.learning_reuse import _origin
    setup = setup_executor(tmp_path)
    original = closed_loop.finalize
    def pause(*args, **kwargs):
        raise RuntimeError("pause before finalization")
    monkeypatch.setattr(closed_loop, "finalize", pause)
    with pytest.raises(RuntimeError, match="pause before finalization"):
        execute(setup)
    directory = run_directory(setup)
    before = sorted(str(path) for path in directory.rglob("attempt-*"))
    monkeypatch.setattr(closed_loop, "finalize", original)
    result = execute(setup, resume_finalization=True)
    assert result["recovered_finalization"]
    assert sorted(str(path) for path in directory.rglob("attempt-*")) == before
    assert _origin(setup[0], setup[1], result["receipt_sha256"], clock=lambda: 1000)[3] == result["candidate"]
    response = read_json(directory/"r1-critic-result.json")
    target = Path(response["receipt"]["runtime"]["paths"]["input"])
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(SwarmError, match="RUN_RUNTIME_ARTIFACT_CHANGED"):
        _origin(setup[0], setup[1], result["receipt_sha256"], clock=lambda: 1000)


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("artifact", ["candidate.json", "learning.json", "execution.json", ".receipt-pending.json"])
def test_publication_last_policy_callback_cannot_change_final_outputs(tmp_path, monkeypatch, artifact, resume):
    import threading
    from task_swarm import closed_loop, loop_executor
    setup = setup_executor(tmp_path)
    if resume:
        original_finalize = closed_loop.finalize
        def pause(*args, **kwargs):
            raise RuntimeError("pause before finalization")
        monkeypatch.setattr(closed_loop, "finalize", pause)
        with pytest.raises(RuntimeError, match="pause before finalization"):
            execute(setup)
        monkeypatch.setattr(closed_loop, "finalize", original_finalize)
    directory = run_directory(setup)
    original_policy = loop_executor.check_current_executor_policy
    current_thread, observations = threading.get_ident(), []
    def change_final_output(*args, **kwargs):
        result = original_policy(*args, **kwargs)
        if threading.get_ident() == current_thread and (directory/".receipt-pending.json").exists():
            observations.append(1)
            if len(observations) == 2:
                target = directory/artifact
                target.write_bytes(target.read_bytes() + b"\n")
        return result
    monkeypatch.setattr(loop_executor, "check_current_executor_policy", change_final_output)
    with pytest.raises(SwarmError, match="RUN_ARTIFACT_CHANGED"):
        execute(setup, resume_finalization=resume)
    assert len(observations) == 2 and not (directory/"receipt.json").exists()


def test_fixed_thirteen_is_not_accepted_for_another_dataset(tmp_path):
    setup = setup_executor(tmp_path, second=23,
        child=lambda script: script.replace('else str(actual[name])', 'else ("13" if name == "DocB.txt" else str(actual[name]))'))
    result = execute(setup)
    assert result["receipt"]["budget"]["attempts_used"] == 5
    assert result["candidate"]["status"] == "unresolved" and result["learning_candidate"] is None


def test_cancellation_does_not_require_saved_executor_proof(tmp_path):
    from task_swarm.closed_loop_cancellation import cancel_closed_loop
    setup = setup_executor(tmp_path)
    interrupted(setup)
    (run_directory(setup)/"executor-policy.json").unlink()
    first = cancel_closed_loop(setup[0], setup[1], clock=lambda: 1000)
    assert cancel_closed_loop(setup[0], setup[1], clock=lambda: 1000) == first


def test_durable_cancellation_stops_and_reaps_owned_fixture_children(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import sqlite3
    import time
    from task_swarm.closed_loop_cancellation import cancel_closed_loop
    from task_swarm.codex import BackendError, _same_process
    setup = setup_executor(tmp_path, child=lambda script: script.replace("acquired = []", "import time\ntime.sleep(20)\nacquired = []"))
    database = run_directory(setup)/"execution.sqlite"
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(execute, setup)
        limit, identities = time.monotonic() + 8, []
        while time.monotonic() < limit:
            if database.exists():
                with sqlite3.connect(database) as db:
                    identities = [json.loads(row[0]) for row in db.execute(
                        "SELECT identity_json FROM attempts WHERE identity_json IS NOT NULL")]
                if len(identities) == 2:
                    break
            time.sleep(.02)
        assert len(identities) == 2
        cancel_closed_loop(setup[0], setup[1], clock=lambda: 1000)
        with pytest.raises((SwarmError, BackendError)) as error:
            future.result(timeout=8)
        assert error.value.code in {"RUN_CANCELLED", "cancelled"}
    assert not (run_directory(setup)/"receipt.json").exists()
    assert all(not _same_process(item["pid"], item["created_at"]) for item in identities)
