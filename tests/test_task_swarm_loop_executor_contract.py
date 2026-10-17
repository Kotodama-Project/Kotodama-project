"""Dormant technical executor primitives never admit a loop or a native model."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import textwrap

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest environment")

RUNTIME = Path(__file__).resolve().parents[1] / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from task_swarm.codex import CodexBackend
from task_swarm.closed_loop_contract import loop_criteria, work_input
from task_swarm.loop_executor import (check_current_executor_policy, derive_executor_policy,
    executor_version, loop_request, loop_schema, verify_loop_response)
from task_swarm.owner_file import OwnerFile
from task_swarm.protocol import SwarmError, canonical, digest
from task_swarm.task_contract import validate_input
from task_swarm.task_runner import verify_runtime


CHILD = textwrap.dedent(r'''
    import hashlib, json, pathlib, sys, uuid
    from datetime import datetime, timezone
    args = sys.argv[1:]
    raw = sys.stdin.buffer.read()
    request = json.loads(raw)
    cwd = pathlib.Path.cwd()
    (cwd / "child-input.bin").write_bytes(raw)
    (cwd / "work").mkdir()
    acquired = []
    evidence = []
    total = 0
    for material in request["materials"]:
        with pathlib.Path(material["path"]).open("rb") as stream:
            data = stream.read(material["bytes"] + 1)
        assert len(data) == material["bytes"] and hashlib.sha256(data).hexdigest() == material["sha256"]
        acquired.append({"path": material["relative_path"], "bytes": len(data),
                         "sha256": hashlib.sha256(data).hexdigest()})
        total += int(data.decode("utf-8").strip())
        record = next(s for s in request["input"]["view"]["spans"]
                      if s["source_key"] == material["source_key"])
        evidence.append({k: record[k] for k in ("source_key", "source_revision", "start", "end")}
                        | {"quote": record["text"]})
    (cwd / "child-acquisition.json").write_bytes(json.dumps(acquired).encode("utf-8"))
    result = {"job_id": request["dispatch"]["job_id"], "summary": "actual local bytes",
              "claims": [{"text": str(total), "status": "supported", "evidence": evidence}],
              "conflicts": []}
    output = pathlib.Path(args[args.index("--output-last-message") + 1])
    output.write_bytes(json.dumps(result).encode("utf-8"))
    thread, turn = str(uuid.uuid4()), str(uuid.uuid4())
    for kind, fields in [("thread.started", {"thread_id": thread}),
                         ("turn.started", {"turn_id": turn}), ("turn.completed", {"turn_id": turn})]:
        print(json.dumps({"type": kind, **fields}), flush=True)
    sessions = cwd.parent / "sessions"
    sessions.mkdir(exist_ok=True)
    records = [
      {"type": "session_meta", "payload": {"id": thread, "session_id": thread,
          "cwd": str(cwd), "timestamp": datetime.now(timezone.utc).isoformat()}},
      {"type": "turn_context", "payload": {"turn_id": turn, "model": "gpt-5.6-luna",
          "effort": "max", "approval_policy": "never", "sandbox_policy": {"type": "read-only"}}},
      {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": turn,
          "completed_at": 1, "last_agent_message": json.dumps(result)}}]
    (sessions / ("rollout-" + thread + ".jsonl")).write_bytes(
        ("\n".join(json.dumps(record) for record in records) + "\n").encode("utf-8"))
''').encode("utf-8")


def case(root, second=13):
    root.mkdir(exist_ok=True)
    exe = root / "worker.py"
    exe.write_bytes(CHILD)
    docs = [(root / "DocA.txt", b"5\n"), (root / "DocB.txt", f"{second}\n".encode())]
    def source(key, revision, value):
        return {"key": hashlib.sha256(key.encode()).hexdigest(), "revision": revision,
                "text": value, "sha256": hashlib.sha256(value.encode()).hexdigest()}
    def span(record, text):
        at = record["text"].index(text)
        return {"source_key": record["key"], "source_revision": record["revision"],
                "start": at, "end": at + len(text)}
    materials = []
    sources = []
    for path, raw in docs:
        path.write_bytes(raw)
        row = source(path.name, 1, raw.decode())
        sources.append(row)
        materials.append({"path": path.name, "source_key": row["key"], "source_revision": 1,
            "sha256": row["sha256"], "bytes": len(raw), "capability": "fixture_local_read_observation"})
    declaration = {"kind": "task_loop_executor", "version": 1, "mode": "local_executable_fixture",
        "prompt_contract_version": 1, "visibility": "fixture_declared_material_observation",
        "executable": {"path": exe.name, "sha256": hashlib.sha256(CHILD).hexdigest(), "bytes": len(CHILD)},
        "materials": materials}
    policy_text = canonical(declaration)
    assert len(policy_text) <= 1000
    original = source("intent", 1, "Original calculation request")
    current = source("intent", 2, "Current calculation request\nOUT-LOOP\nUse real bytes\nUnknown stays unknown\n" + policy_text)
    payload = {"version": 2, "task_id": "task-00000000-0000-4000-8000-000000000375", "revision": 2,
        "request": "Current calculation request", "acceptance": ["Use real bytes"],
        "sources": [original, current, *sources], "objective": {"owner_ref": "ref/owner/fixture",
        "intent": {"original": span(original, original["text"]),
                   "replacements": [span(current, "Current calculation request")]},
        "references": [{"kind": "goal", "id": "OUT-LOOP", "source": span(current, "OUT-LOOP")}],
        "constraints": [span(current, policy_text)], "unknowns": [span(current, "Unknown stays unknown")],
        "acceptance": [span(current, "Use real bytes")], "budget": {"attempt_budget": 6, "deadline": 1100},
        "stop_conditions": ["cancelled", "binding_changed", "deadline_exceeded"],
        "rollback": "not_applicable_read_only"}}
    binding = {"task_id": payload["task_id"], "revision": 2, "context_digest": digest(payload),
        "owner_ref": payload["objective"]["owner_ref"], "active_home": str(root / "operations"),
        "authority_ref": "ref/authority/fixture", "capability_ref": "ref/capability/swarm_research",
        "expires_at": 1200, "status": "active"}
    validate_input(payload, binding, now=1000)
    checks = [{"path": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in [exe, *(p for p, _ in docs)]]
    owner_document = {"binding": binding, "source_checks": checks,
        "actors": {"worker": {"epoch": 1, "invocation_ref": "fixture-worker", "actor_status": "active",
            "capability_ref": binding["capability_ref"], "peers": []}}, "allowed_actions": [],
        "storage": {"root": str(root / "operations"), "mailbox": str(root / "operations/mailbox"),
                    "payloads": str(root / "operations/payloads")}}
    owner_path = root / "owner.json"
    owner_path.write_bytes(canonical(owner_document).encode())
    spec = {"version": 1, "parent_input_digest": digest(payload), "jobs": [
        {"job_id": "doc-a", "purpose": "Acquire DocA", "criterion_ids": list(loop_criteria(payload)),
         "selected_spans": [span(sources[0], sources[0]["text"])]}]}
    policy = derive_executor_policy(payload, spec, payload["objective"]["constraints"][0], owner_base=str(root))
    delivered = work_input(payload, spec["jobs"][0], 0, digest(spec), round_plan_digest=digest(spec))
    identity = {"run_id": "task-run-" + digest([payload["task_id"], 2])[:32], "job_id": "r0-doc-a",
                "actor_ref": "worker", "attempt": 1, "epoch": 1}
    return payload, spec, policy, delivered, identity, owner_path, owner_document


def response(root, *, second=13, use_b=False, snapshot=True):
    payload, spec, policy, delivered, dispatch, owner_path, owner_doc = case(root, second=second)
    if use_b:
        source = payload["sources"][-1]
        spec["jobs"][0]["selected_spans"] = [{"source_key": source["key"], "source_revision": source["revision"],
                                             "start": 0, "end": len(source["text"])}]
        policy = derive_executor_policy(payload, spec, payload["objective"]["constraints"][0], owner_base=str(root))
        delivered = work_input(payload, spec["jobs"][0], 0, digest(spec), round_plan_digest=digest(spec))
    owner = OwnerFile(owner_path, clock=lambda: 1000)
    check_current_executor_policy(policy, payload, spec, owner_path=owner_path, owner_document=owner_doc)
    request = loop_request(policy, delivered, dispatch)
    schema = loop_schema(delivered)
    directory = root / "attempts"
    observed = []
    runtime = CodexBackend(root / "worker.py", session_root=directory / "sessions").invoke(
        request.decode(), schema, directory, timeout=8, record_input=True,
        executable_bytes=(root / "worker.py").read_bytes() if snapshot else None,
        on_process=lambda pid, created: observed.append({"kind": "process", "pid": pid, "created_at": created}))
    attempt = {**dispatch, "worker_ref": dispatch["actor_ref"], "identity": observed[0]}
    value = {"result": copy.deepcopy(runtime["result"]), "receipt": {
        "actor_ref": "worker", "invocation_ref": runtime["receipt"]["thread_id"],
        "input_digest": digest(delivered), "synthetic": True, "executor_contract_version": 1,
        "executor_policy_sha256": digest(policy), "prompt_contract_version": 1,
        "prompt_sha256": hashlib.sha256(request).hexdigest(), "runtime": runtime}}
    options = {"policy": policy, "delivered": delivered, "dispatch_identity": dispatch,
        "expected_attempt": attempt, "expected_schema": schema,
        "current_guard": lambda: owner.read_binding(payload["task_id"], "worker"), "attempt_directory": directory}
    return value, options, request


def test_current_policy_and_material_lane_keep_mandatory_correction(tmp_path):
    payload, spec, policy, delivered, identity, owner, document = case(tmp_path)
    check_current_executor_policy(policy, payload, spec, owner_path=owner, owner_document=document)
    raw = loop_request(policy, delivered, identity)
    request = json.loads(raw)
    assert [m["relative_path"] for m in request["materials"]] == ["DocA.txt"]
    assert "DocB.txt" in canonical(request["input"]["view"]["spans"])
    assert "Original calculation request" in raw.decode() and "Current calculation request" in raw.decode()
    assert policy["parent_input_digest"] == digest(payload) and raw == canonical(request).encode()


def test_executor_axis_requires_the_original_template_digest_and_evidence_two(tmp_path):
    from task_swarm.closed_loop_context import derive_child_view
    from task_swarm.closed_loop_contract import required_evidence_jobs
    payload, spec, policy, _, _, _, _ = case(tmp_path)
    template = {"role": "critic", "job_id": "r0-critic", "round": 0, "round_plan_digest": digest(spec),
        "criteria": loop_criteria(payload), "view": derive_child_view(payload, "r0-critic", spec["jobs"][0]["selected_spans"], plan_digest=digest(spec)),
        "repair_planning_contract": 1, "repair_impact_sha256": None, "evidence_contract_version": 2,
        "required_evidence_jobs": required_evidence_jobs(payload, spec)}
    runtime = {"jobs": [{"job_id": "r0-critic", "kind": "review", "payload_digest": digest(template)}]}
    assert executor_version(runtime, template) is None
    template.update(executor_contract_version=1, executor_policy_sha256=digest(policy))
    with pytest.raises(SwarmError): executor_version(runtime, template)
    runtime["jobs"][0]["payload_digest"] = digest(template)
    before = copy.deepcopy(runtime)
    assert executor_version(runtime, template) == 1 and runtime == before
    for field, value in [("executor_contract_version", True), ("executor_contract_version", 2),
                         ("executor_policy_sha256", None)]:
        bad = {**template, field: value}
        with pytest.raises(SwarmError):
            executor_version({"jobs": [{**runtime["jobs"][0], "payload_digest": digest(bad)}]}, bad)
    bad = {k:v for k,v in template.items() if k != "executor_policy_sha256"}
    with pytest.raises(SwarmError):
        executor_version({"jobs": [{**runtime["jobs"][0], "payload_digest": digest(bad)}]}, bad)


@pytest.mark.parametrize("mutation", ["source_count", "source_chars", "constraint_chars", "duplicate_json", "traversal", "latest", "bool"])
def test_task_source_statement_and_policy_bounds_intersect(tmp_path, mutation):
    payload, spec, policy, _, _, _, _ = case(tmp_path)
    span = payload["objective"]["constraints"][0]
    source = payload["sources"][1]
    if mutation == "source_count":
        for i in range(7):
            payload["sources"].append({"key": digest(i), "revision": 1, "text": "x", "sha256": hashlib.sha256(b"x").hexdigest()})
    elif mutation == "source_chars": source["text"] += "x" * 12001
    elif mutation == "constraint_chars":
        source["text"] += " " * 1001; span["end"] = len(source["text"])
    elif mutation == "latest": payload["sources"].append({**payload["sources"][-2], "revision": 2})
    elif mutation == "bool": payload["revision"] = True
    else:
        raw = source["text"][span["start"]:span["end"]]
        if mutation == "duplicate_json": raw = '{"version":1,' + raw[1:]
        else: raw = raw.replace('"path":"worker.py"', '"path":"../worker.py"')
        source["text"] = source["text"][:span["start"]] + raw
        span["end"] = len(source["text"])
    source["sha256"] = hashlib.sha256(source["text"].encode()).hexdigest()
    spec["parent_input_digest"] = digest(payload)
    with pytest.raises(SwarmError):
        derive_executor_policy(payload, spec, span, owner_base=str(tmp_path))


@pytest.mark.parametrize("field,value", [("prompt_contract_version", True), ("revision", True),
    ("mode", "native_codex"), ("kind", "foreign")])
def test_compiled_candidate_is_not_a_permissive_request_flag(tmp_path, field, value):
    _, _, policy, delivered, identity, _, _ = case(tmp_path)
    policy[field] = value
    with pytest.raises(SwarmError): loop_request(policy, delivered, identity)


def test_malformed_pure_inputs_are_typed_without_wrapping_current_guard_errors(tmp_path):
    _, _, policy, delivered, identity, _, _ = case(tmp_path)
    bad = copy.deepcopy(delivered)
    del bad["view"]["objective"]
    bad["view"]["view_digest"] = digest({k:v for k,v in bad["view"].items() if k != "view_digest"})
    with pytest.raises(SwarmError): loop_request(policy, bad, identity)
    with pytest.raises(SwarmError): loop_schema({"role": "work", "view": {}})


@pytest.mark.parametrize("field,value", [("version", True), ("mode", "native_codex"),
    ("visibility", "enforced_material_isolation"), ("prompt_contract_version", 2)])
def test_policy_unsupported_or_bool_never_falls_back(tmp_path, field, value):
    payload, spec, _, _, _, _, _ = case(tmp_path)
    span = payload["objective"]["constraints"][0]
    source = next(s for s in payload["sources"] if s["key"] == span["source_key"] and s["revision"] == 2)
    declaration = json.loads(source["text"][span["start"]:span["end"]])
    declaration[field] = value
    raw = canonical(declaration)
    source["text"] = source["text"][:span["start"]] + raw
    source["sha256"] = hashlib.sha256(source["text"].encode()).hexdigest()
    span["end"] = span["start"] + len(raw)
    spec["parent_input_digest"] = digest(payload)
    with pytest.raises(SwarmError):
        derive_executor_policy(payload, spec, span, owner_base=str(tmp_path))


@pytest.mark.parametrize("mutation", ["source_sha", "revision", "path", "owner_mapping", "bytes", "file"])
def test_current_source_owner_mapping_and_real_bytes_are_required(tmp_path, mutation):
    payload, spec, policy, _, _, owner, document = case(tmp_path)
    if mutation == "owner_mapping": document["source_checks"] = document["source_checks"][:1]
    elif mutation == "file": (tmp_path / "DocA.txt").write_bytes(b"8\n")
    elif mutation == "path": policy["materials"][0]["path"] = str(tmp_path.parent / "DocA.txt")
    elif mutation == "bytes": policy["materials"][0]["bytes"] = True
    elif mutation == "source_sha": payload["sources"][-2]["sha256"] = "0" * 64
    else: payload["sources"][-2]["revision"] = 2
    with pytest.raises(SwarmError):
        check_current_executor_policy(policy, payload, spec, owner_path=owner, owner_document=document)


def test_dynamic_critic_and_prerequisite_schemas_do_not_use_fixed_three_jobs(tmp_path):
    _, _, _, work, _, _, _ = case(tmp_path)
    report = {"job_id": "r0-doc-a", "summary": "data", "claims": [{"text": "5", "status": "unknown", "evidence": []}], "conflicts": []}
    critic = {"role": "critic", "job_id": "r0-critic", "round": 0, "view": work["view"],
        "criteria": work["criteria"], "reports": {"r0-doc-a": report}, "report_digests": {"r0-doc-a": digest(report)}}
    schema = loop_schema(critic)
    assert set(schema["properties"]["report_digests"]["properties"]) == {"r0-doc-a"}
    pre = {"core": {"role": "prerequisite_review", "job_id": "r0-prerequisite", "gate": ["A1"], "view": work["view"]},
           "descriptor_sha256": "a" * 64, "report_sha256": "b" * 64, "report": report}
    assert loop_schema(pre)["properties"]["kind"]["const"] == "prerequisite_review"


def test_real_child_input_acquisition_and_freeze_replay_are_distinct_from_native(tmp_path):
    value, options, raw = response(tmp_path)
    runtime = value["receipt"]["runtime"]
    attempt = Path(runtime["paths"]["attempt_dir"])
    assert (attempt / "child-input.bin").read_bytes() == Path(runtime["paths"]["input"]).read_bytes() == raw
    assert value["result"]["claims"][0]["text"] == "5"
    assert json.loads((attempt / "child-acquisition.json").read_bytes())[0]["sha256"] == hashlib.sha256(b"5\n").hexdigest()
    verify_loop_response(value, freeze=True, **options)
    before = copy.deepcopy(value)
    verify_loop_response(value, **options)
    assert value == before and set(runtime) == {"result", "receipt", "paths", "runtime_receipt_sha256", "runtime_rollout_sha256"}
    with pytest.raises(SwarmError) as caught:
        verify_runtime(runtime, options["attempt_directory"], freeze=True, expected_input=raw)
    # The native reader's unchanged artifact set rejects the fixture snapshot
    # before its separate permission-profile check.
    assert caught.value.code == "RUN_RUNTIME_PATH_CHANGED"


@pytest.mark.parametrize("number", [13, 23])
def test_real_child_answer_changes_with_the_admitted_material_bytes(tmp_path, number):
    value, options, raw = response(tmp_path, second=number, use_b=True)
    verify_loop_response(value, freeze=True, **options)
    assert value["result"]["claims"][0]["text"] == str(number)
    assert [m["relative_path"] for m in json.loads(raw)["materials"]] == ["DocB.txt"]


@pytest.mark.parametrize("mutation", ["sandbox", "stdout_completion"])
def test_coherent_fresh_runtime_metadata_matches_actual_rollout_and_stdout(tmp_path, mutation):
    value, options, _ = response(tmp_path)
    runtime = value["receipt"]["runtime"]
    if mutation == "sandbox":
        path = Path(runtime["receipt"]["runtime_receipt_path"])
        records = [json.loads(line) for line in path.read_bytes().splitlines()]
        context = next(record for record in records if record["type"] == "turn_context")
        context["payload"]["sandbox_policy"] = {"type": "danger-full-access"}
        path.write_bytes(("\n".join(json.dumps(record) for record in records) + "\n").encode())
    else:
        _replace_events(runtime, lambda records: [record for record in records
                                                  if record["type"] != "turn.completed"])
    with pytest.raises(SwarmError) as caught:
        verify_loop_response(value, freeze=True, **options)
    assert caught.value.code == ("RUN_RUNTIME_BINDING_CHANGED" if mutation == "sandbox"
                                 else "LOOP_EXECUTOR_STDOUT_COMPLETION")
    assert "runtime_receipt_sha256" not in runtime and "runtime_rollout_sha256" not in runtime


def _replace_events(runtime, change):
    path = Path(runtime["paths"]["events"])
    records = change([json.loads(line) for line in path.read_bytes().splitlines()])
    raw = ("\n".join(json.dumps(record) for record in records) + "\n").encode()
    path.write_bytes(raw)
    runtime["receipt"]["artifact_digests"]["events"] = hashlib.sha256(raw).hexdigest()
    Path(runtime["paths"]["receipt"]).write_bytes((canonical(runtime["receipt"]) + "\n").encode())


@pytest.mark.parametrize("kind", ["turn.failed", "error", "turn.error", "turn.completed", "nested_failed"])
def test_coherent_stdout_cannot_add_failure_or_duplicate_completion(tmp_path, kind):
    value, options, _ = response(tmp_path)
    runtime = value["receipt"]["runtime"]
    event = ({"type": "event_msg", "payload": {"type": "task_failed",
              "turn_id": runtime["receipt"]["turn_id"]}} if kind == "nested_failed"
             else {"type": kind, "turn_id": runtime["receipt"]["turn_id"]})
    _replace_events(runtime, lambda records: [*records, event])
    with pytest.raises(SwarmError) as caught:
        verify_loop_response(value, freeze=True, **options)
    assert caught.value.code == "LOOP_EXECUTOR_STDOUT_COMPLETION"


@pytest.mark.parametrize("record", [True, [], {"type": "event_msg", "payload": {"type": []}}])
def test_stdout_non_object_is_a_typed_refusal_before_identity_lookup(tmp_path, record):
    value, options, _ = response(tmp_path)
    runtime = value["receipt"]["runtime"]
    _replace_events(runtime, lambda records: [*records, record])
    with pytest.raises(SwarmError) as caught:
        verify_loop_response(value, freeze=True, **options)
    assert caught.value.code == "LOOP_EXECUTOR_STDOUT_COMPLETION"


@pytest.mark.parametrize("field,identity", [
    ("turn_id", True), ("thread_id", []), ("turn_id", None),
    ("thread_id", ""), ("session_id", None), ("session_id", "")])
@pytest.mark.parametrize("lane", ["outer", "payload"])
def test_present_stdout_identity_is_not_treated_as_an_absent_identity(tmp_path, field, identity, lane):
    value, options, _ = response(tmp_path)
    runtime = value["receipt"]["runtime"]
    def change(records):
        completion = next(record for record in records if record["type"] == "turn.completed")
        target = completion if lane == "outer" else completion.setdefault("payload", {})
        target[field] = identity
        return records
    _replace_events(runtime, change)
    with pytest.raises(SwarmError) as caught:
        verify_loop_response(value, freeze=True, **options)
    assert caught.value.code == "RUN_RUNTIME_IDENTITY_CHANGED"
    assert "runtime_receipt_sha256" not in runtime and "runtime_rollout_sha256" not in runtime


@pytest.mark.parametrize("lane", ["outer", "payload"])
@pytest.mark.parametrize("matches", [False, True])
def test_present_stdout_thread_aliases_must_agree(tmp_path, lane, matches):
    value, options, _ = response(tmp_path)
    runtime = value["receipt"]["runtime"]
    thread = runtime["receipt"]["thread_id"]
    alias = thread if matches else ("1" if thread[0] != "1" else "2") + thread[1:]
    def change(records):
        started = next(record for record in records if record["type"] == "thread.started")
        target = started if lane == "outer" else started.setdefault("payload", {})
        target.update(thread_id=thread, session_id=alias)
        return records
    _replace_events(runtime, change)
    if matches:
        verify_loop_response(value, freeze=True, **options)
        before = copy.deepcopy(value)
        verify_loop_response(value, **options)
        assert value == before
    else:
        with pytest.raises(SwarmError) as caught:
            verify_loop_response(value, freeze=True, **options)
        assert caught.value.code == "RUN_RUNTIME_IDENTITY_CHANGED"
        assert "runtime_receipt_sha256" not in runtime and "runtime_rollout_sha256" not in runtime


def test_stdout_completion_without_repeated_turn_id_keeps_unique_runtime_binding(tmp_path):
    value, options, _ = response(tmp_path)
    runtime = value["receipt"]["runtime"]
    def omit_completion_id(records):
        next(record for record in records if record["type"] == "turn.completed").pop("turn_id")
        return records
    _replace_events(runtime, omit_completion_id)
    verify_loop_response(value, freeze=True, **options)
    before = copy.deepcopy(value)
    verify_loop_response(value, **options)
    assert value == before


@pytest.mark.parametrize("mutation", ["bool", "missing_intent", "record_sha"])
def test_self_consistent_view_digest_does_not_allow_malformed_or_dropped_mandatory_records(tmp_path, mutation):
    _, _, policy, delivered, dispatch, _, _ = case(tmp_path)
    view = delivered["view"]
    if mutation == "bool": view["spans"][-1]["source_revision"] = True
    elif mutation == "missing_intent": view["spans"] = view["spans"][1:]
    else: view["spans"][-1]["sha256"] = "0" * 64
    view["view_digest"] = digest({k:v for k,v in view.items() if k != "view_digest"})
    with pytest.raises(SwarmError): loop_request(policy, delivered, dispatch)


@pytest.mark.parametrize("mutation", ["input", "actor", "process", "schema", "command", "rollout", "policy", "extra", "native"])
def test_saved_proof_tamper_cannot_be_frozen_or_replayed(tmp_path, mutation):
    value, options, _ = response(tmp_path)
    verify_loop_response(value, freeze=True, **options)
    runtime = value["receipt"]["runtime"]
    if mutation == "input":
        p = Path(runtime["paths"]["input"]); raw = p.read_bytes(); p.write_bytes(b"!" + raw[1:])
    elif mutation == "actor": value["receipt"]["actor_ref"] = "other"
    elif mutation == "process": options["expected_attempt"]["identity"]["pid"] += 1
    elif mutation == "policy": value["receipt"]["executor_policy_sha256"] = "0" * 64
    elif mutation == "extra": runtime["unverified"] = True
    elif mutation == "native": runtime["receipt"]["permission_probe"] = {"model_called": False}
    else:
        path = Path(runtime["receipt"]["runtime_receipt_path"] if mutation == "rollout" else runtime["paths"][mutation])
        path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(SwarmError): verify_loop_response(value, **options)


def test_current_guard_cause_and_late_input_change_are_preserved(tmp_path):
    value, options, _ = response(tmp_path)
    error = LookupError("current guard refused")
    def guard(): raise error
    with pytest.raises(LookupError) as caught:
        verify_loop_response(value, current_guard=guard, **{k:v for k,v in options.items() if k != "current_guard"})
    assert caught.value is error
    calls = []
    def late():
        calls.append(1)
        if len(calls) == 2:
            path = Path(value["receipt"]["runtime"]["paths"]["input"])
            raw = path.read_bytes(); path.write_bytes(b"!" + raw[1:])
    with pytest.raises(SwarmError):
        verify_loop_response(value, freeze=True, current_guard=late,
                             **{k:v for k,v in options.items() if k != "current_guard"})


def test_byte_limit_and_late_packet_change_cannot_make_a_new_success(tmp_path):
    value, options, _ = response(tmp_path)
    for limit in (1, True, 2*1024*1024+1):
        with pytest.raises(SwarmError): verify_loop_response(value, freeze=True, maximum_bytes=limit, **options)
    calls = []
    def mutate():
        calls.append(1)
        if len(calls) == 2: value["receipt"]["runtime"]["result"]["summary"] = "changed after verification"
    with pytest.raises(SwarmError) as caught:
        verify_loop_response(value, freeze=True, current_guard=mutate,
                             **{k:v for k,v in options.items() if k != "current_guard"})
    assert caught.value.code == "LOOP_EXECUTOR_PACKET_CHANGED"


@pytest.mark.parametrize("field", ["actor", "outer_result"])
def test_final_guard_cannot_mutate_an_already_checked_outer_response(tmp_path, field):
    value, options, _ = response(tmp_path)
    calls = []
    def mutate():
        calls.append(1)
        if len(calls) == 2:
            if field == "actor": value["receipt"]["actor_ref"] = "other"
            else: value["result"]["summary"] = "changed outer result"
    with pytest.raises(SwarmError):
        verify_loop_response(value, freeze=True, current_guard=mutate,
                             **{k:v for k,v in options.items() if k != "current_guard"})


def test_existing_non_synthetic_loop_admission_is_still_closed(tmp_path):
    from task_swarm.closed_loop import execute_closed_loop
    from task_swarm.task_backend import TaskBackend
    with pytest.raises(SwarmError) as caught:
        execute_closed_loop(tmp_path / "missing-owner", tmp_path / "missing-input", {},
            TaskBackend(tmp_path / "worker.py", task_codex_home=tmp_path / "home"), worker_actors=["worker"])
    assert caught.value.code == "LOOP_SIMULATION_REQUIRED"
