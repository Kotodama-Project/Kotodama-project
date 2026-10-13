"""Real local-loop history through the hierarchy reader, without redispatch."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest environment")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
import test_knowledge_task_input as knowledge
from test_task_swarm_loop_executor_runtime import setup_executor, execute, run_directory
from kotodama_kb.hierarchy_reader import trace_current_refs
from kotodama_kb.load import load_bundle
from runtime.task_swarm.protocol import SwarmError, canonical, digest


def inventory(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def completed(root, *, second=13, dependency=False, repair=True, now=1000):
    child = None if repair else lambda script: script.replace(
        'partial = name == "DocB.txt" and core["round"] == 0', "partial = False")
    setup = setup_executor(root, second=second, dependency=dependency, child=child)
    owner, input_file, document, payload, plan, _ = setup
    knowledge.small_catalog(root)
    bundle = load_bundle(root)
    goal = knowledge.source("hierarchy-goal", 1, bundle.concepts[0].document.raw)
    payload["sources"].append(goal)
    payload["objective"]["references"] = [{"kind": "goal", "id": "OUT-INTENT",
                                          "source": knowledge.span(goal, "OUT-INTENT")}]
    payload["objective"]["budget"]["deadline"] = now + 100
    document["binding"]["expires_at"] = now + 200
    (root / "work").mkdir()
    nodes, selected = [], []
    for identifier, kind, parent, fields in [
        ("PROJECT-LOCAL", "project", None, {"constraints": ["Retain the original material evidence."]}),
        ("REQ-LOCAL", "requirement", "PROJECT-LOCAL", {"constraints": [],
            "need": "Read the declared local material values.", "acceptance": ["Preserve DocA while correcting DocB."]}),
    ]:
        metadata = {"id": identifier, "template_kind": kind, "status": "draft", "task_context": fields}
        if parent is not None:
            metadata["parent_ref"] = parent
        statements = [*fields["constraints"], *([fields["need"], *fields["acceptance"]] if parent else [])]
        raw = knowledge.markdown(metadata, "\n\n".join(statements))
        name = "work/" + identifier + ".md"
        (root / name).write_text(raw)
        row = knowledge.source(identifier, 1, raw)
        payload["sources"].append(row)
        selected.append(knowledge.span(row, raw))
        nodes.append({"path": name, "source_key": row["key"], "source_revision": 1})
    for job in plan["jobs"]:
        job["selected_spans"].extend(copy.deepcopy(selected))
    plan["parent_input_digest"] = digest(payload)
    input_file.write_text(canonical(payload))
    document["binding"]["context_digest"] = digest(payload)
    document["source_checks"] = [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in [input_file, root / "worker.py", root / "DocA.txt", root / "DocB.txt",
                  *(root / path for path, _ in bundle.input_bindings), *(root / node["path"] for node in nodes)]]
    owner.write_text(canonical(document))
    result = execute(setup, clock=lambda: now)
    request = {"version": 1, "root_id": "REQ-LOCAL", "nodes": nodes, "references": [
        {"kind": "runtime_plan", "id": result["receipt"]["run_id"], "revision": payload["revision"],
         "mandatory": True, "receipt_sha256": result["receipt_sha256"]}]}
    return setup, bundle, request, result


def trace(fixture, *, clock=lambda: 1000, with_bytes=False):
    setup, bundle, request, _ = fixture
    return trace_current_refs(bundle, setup[3], setup[0], request, clock=clock, with_bytes=with_bytes)


@pytest.mark.parametrize("second", [13, 23])
def test_repair_history_retains_inputs_and_attempts_without_database_or_process_writes(tmp_path, monkeypatch, second):
    fixture = completed(tmp_path, second=second)
    setup, _, _, written = fixture
    before = inventory(tmp_path)
    import subprocess
    from runtime.task_swarm.state import SwarmState
    original = SwarmState.__init__
    inspected = []
    def copied_state(self, database, *args, **kwargs):
        inspected.append(Path(database))
        assert not Path(database).is_relative_to(tmp_path)
        return original(self, database, *args, **kwargs)
    with monkeypatch.context() as scoped:
        scoped.setattr(SwarmState, "__init__", copied_state)
        scoped.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("reader dispatched a child"))
        result, frame = trace(fixture, with_bytes=True)
        assert json.loads(frame) == result
        # The execution budget has expired; still-current historical evidence
        # and owner scope must remain readable without admitting another call.
        historical = trace(fixture, clock=lambda: 1101)
    assert inspected and inventory(tmp_path) == before
    assert result["status"] == historical["status"] == "TRACED_CANDIDATE"
    assert result["dispatch_performed"] is False and result["context_candidate"]["dispatch_ready"] is False
    proof = result["resolved_references"][0]
    assert proof["execution_mode"] == "local_executable_fixture" and proof["rounds"] == 2
    assert proof["receipt_sha256"] == written["receipt_sha256"]
    assert proof["current_cancellation"] == "not_cancelled_at_read"
    assert proof["learning_artifact"] == "candidate_only" and proof["current_decision"] == "not_observed"
    assert len(proof["dispatches"]) == 5
    assert all(row["identity_kind"] == "process" and row["attempt"] == 1 for row in proof["dispatches"])
    assert proof["repair"]["new_dispatches"] == ["r1-critic", "r1-repair-doc-b"]
    retained = proof["repair"]["retained"]
    assert [row["job_id"] for row in retained] == ["r0-doc-a"]
    directory = run_directory(setup)
    assert retained[0]["result_sha256"] == written["receipt"]["artifact_sha256"]["r0-doc-a-result.json"]
    assert json.loads((directory / "r1-repair-doc-b-result.json").read_bytes())["result"]["claims"][0]["text"] == str(second)


@pytest.mark.parametrize("dependency,repair,calls", [(False, False, 3), (True, True, 6)])
def test_normal_and_dependency_terminal_evidence_share_the_existing_verifier(tmp_path, dependency, repair, calls):
    fixture = completed(tmp_path, dependency=dependency, repair=repair)
    before = inventory(tmp_path)
    result = trace(fixture)
    proof = result["resolved_references"][0]
    assert len(proof["dispatches"]) == calls and inventory(tmp_path) == before
    assert proof["rounds"] == (2 if repair else 1)
    assert (proof["repair"] is not None) == repair
    assert (proof["dependency"] is not None) == dependency
    if dependency:
        assert proof["dependency"]["preaccepted_jobs"] == ["r0-doc-a"]
        assert any(row["role"] == "prerequisite_review" for row in proof["dispatches"])


def test_saved_runtime_source_owner_and_anchor_changes_are_refused(tmp_path):
    fixture = completed(tmp_path)
    setup, _, request, _ = fixture
    directory = run_directory(setup)
    runtime = json.loads((directory / "r0-doc-a-result.json").read_bytes())["receipt"]["runtime"]
    targets = [Path(runtime["paths"][key]) for key in ("input", "schema", "process", "receipt")]
    targets += [Path(runtime["receipt"]["runtime_receipt_path"]), tmp_path / "DocB.txt", setup[0]]
    for path in targets:
        original = path.read_bytes()
        try:
            path.write_bytes(original + b" ")
            with pytest.raises(SwarmError):
                trace(fixture)
        finally:
            path.write_bytes(original)
    anchor = request["references"][0]["receipt_sha256"]
    try:
        request["references"][0]["receipt_sha256"] = "0" * 64
        with pytest.raises(SwarmError, match="RUN_REPLAY_ANCHOR_CHANGED"):
            trace(fixture)
    finally:
        request["references"][0]["receipt_sha256"] = anchor
    assert trace(fixture)["status"] == "TRACED_CANDIDATE"


def test_reanchored_receipt_must_preserve_the_verified_checkpoint_projection(tmp_path):
    fixture = completed(tmp_path, dependency=True)
    directory = run_directory(fixture[0])
    path = directory / "receipt.json"
    original = path.read_bytes()
    receipt = json.loads(original)
    reference = fixture[2]["references"][0]
    anchor = reference["receipt_sha256"]
    connection = sqlite3.connect(directory / "execution.sqlite")
    try:
        for key, value in [("rounds", 1), ("initial_plan_digest", "0" * 64),
                           ("worker_actors", None), ("dispatches", {}),
                           ("context_bytes", float(receipt["context_bytes"])), ("budget", {}),
                           ("preaccepted", {}), ("dependency_evidence_digest", "0" * 64)]:
            changed = copy.deepcopy(receipt)
            changed[key] = value
            raw = (canonical(changed) + "\n").encode()
            path.write_bytes(raw)
            reference["receipt_sha256"] = hashlib.sha256(raw).hexdigest()
            connection.execute("UPDATE run_finalizations SET receipt_json=? WHERE run_id=?",
                               (canonical(changed), receipt["run_id"]))
            connection.commit()
            # A caller-supplied new anchor and matching saved receipt cannot
            # change the history established by the unchanged checkpoint.
            with pytest.raises(SwarmError, match="FINALIZATION_CONFLICT|RUN_REPLAY_CONFLICT"):
                trace(fixture)
    finally:
        path.write_bytes(original)
        reference["receipt_sha256"] = anchor
        connection.execute("UPDATE run_finalizations SET receipt_json=? WHERE run_id=?",
                           (canonical(receipt), receipt["run_id"]))
        connection.commit()
        connection.close()
    assert trace(fixture)["status"] == "TRACED_CANDIDATE"


@pytest.mark.parametrize("change", ["actor", "proof", "cancel"])
def test_last_policy_callback_cannot_return_an_old_frame(tmp_path, monkeypatch, change):
    fixture = completed(tmp_path)
    setup = fixture[0]
    directory = run_directory(setup)
    import kotodama_kb.hierarchy_reader as reader
    import runtime.task_swarm.loop_executor_runtime as executor
    original_copy, original_policy = reader._copy, executor.check_current_executor_policy
    ready, changed = [], []
    def frame(value):
        copied = original_copy(value)
        if copied.get("kind") == "kotodama.hierarchy-trace":
            ready.append(True)
        return copied
    def late(*args, **kwargs):
        returned = original_policy(*args, **kwargs)
        if ready and not changed:
            changed.append(True)
            if change == "actor":
                document = json.loads(setup[0].read_bytes())
                document["actors"]["worker-a"]["epoch"] += 1
                document["actors"]["worker-a"]["invocation_ref"] += "-new"
                setup[0].write_text(canonical(document))
            elif change == "proof":
                packet = json.loads((directory / "r0-doc-a-result.json").read_bytes())
                path = Path(packet["receipt"]["runtime"]["paths"]["input"])
                path.write_bytes(path.read_bytes() + b" ")
            else:
                receipt = fixture[3]["receipt"]
                record = {"version": 1, "run_id": receipt["run_id"], "binding_digest": receipt["binding_digest"],
                    "initial_execution_plan_digest": digest(json.loads((directory / "plan.json").read_bytes())),
                    "owner_ref": setup[2]["binding"]["owner_ref"], "requested_at": 1000}
                with sqlite3.connect(directory / "execution.sqlite") as db:
                    db.execute("INSERT INTO run_cancellations VALUES (?,?)", (record["run_id"], canonical(record)))
        return returned
    monkeypatch.setattr(reader, "_copy", frame)
    monkeypatch.setattr(executor, "check_current_executor_policy", late)
    with pytest.raises(SwarmError) as error:
        trace(fixture, with_bytes=True)
    assert ready and changed
    assert error.value.code in {"STALE_ACTOR", "OWNER_INPUT_CHANGED", "RUN_RUNTIME_ARTIFACT_CHANGED", "RUN_CANCELLED"}


def test_missing_database_is_not_initialized_and_wal_readback_is_unchanged(tmp_path):
    fixture = completed(tmp_path)
    database = run_directory(fixture[0]) / "execution.sqlite"
    saved = database.with_suffix(".saved")
    database.rename(saved)
    try:
        before = inventory(tmp_path)
        with pytest.raises(SwarmError, match="LOOP_REPAIR_STATE"):
            trace(fixture)
        assert not database.exists() and inventory(tmp_path) == before
    finally:
        saved.rename(database)
    # A live writer owns the original WAL/SHM. The reader must neither connect
    # to it nor checkpoint/delete those files while reading the committed cut.
    with sqlite3.connect(database) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE unrelated_reader_probe(value TEXT)")
        writer.commit()
        before = inventory(tmp_path)
        assert trace(fixture)["status"] == "TRACED_CANDIDATE"
        assert inventory(tmp_path) == before


def test_expired_owner_and_query_deadline_refuse_without_reinterpreting_history(tmp_path, monkeypatch):
    fixture = completed(tmp_path)
    with pytest.raises(SwarmError):
        trace(fixture, clock=lambda: 1201)
    import kotodama_kb.hierarchy_reader as reader
    original = reader._copy
    def late_frame(value):
        returned = original(value)
        if returned.get("kind") == "kotodama.hierarchy-trace":
            monkeypatch.setattr(reader, "QUERY_SECONDS", 0)
        return returned
    monkeypatch.setattr(reader, "_copy", late_frame)
    with pytest.raises(SwarmError, match="HIERARCHY_QUERY_TIMEOUT"):
        trace(fixture)


def test_current_learning_decision_remains_unobserved(tmp_path):
    fixture = completed(tmp_path)
    setup = fixture[0]
    document = json.loads(setup[0].read_bytes())
    document["learning_reuse"] = {"opaque": "A saved proposal is not a current decision."}
    setup[0].write_text(canonical(document))
    result = trace(fixture)
    assert result["status"] == "BLOCKED" and result["context_candidate"] is None
    assert result["current_learning_decision"] == "not_observed"


def test_standalone_cli_reads_typed_history_from_an_external_directory(tmp_path):
    import subprocess
    fixture = completed(tmp_path, repair=False, now=time.time())
    request = tmp_path.parent / (tmp_path.name + "-request.json")
    request.write_text(canonical(fixture[2]))
    before = inventory(tmp_path)
    result = subprocess.run([sys.executable, "-B", str(ROOT / "tools/hierarchy_trace.py"),
        "--root", str(tmp_path), "--owner", str(fixture[0][0]), "--input", str(fixture[0][1]),
        "--request", str(request)], cwd=tmp_path.parent, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr.decode()
    trace_result = json.loads(result.stdout)
    assert trace_result["status"] == "TRACED_CANDIDATE" and trace_result["dispatch_performed"] is False
    assert trace_result["resolved_references"][0]["execution_mode"] == "local_executable_fixture"
    assert inventory(tmp_path) == before
