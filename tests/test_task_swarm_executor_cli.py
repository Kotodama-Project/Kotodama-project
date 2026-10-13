"""Real local children through the source CLI; no backend/clock/factory patch.

The two catalog documents are full owner-bound Sources, not a new attachment
format. A separate fixture owner admits candidates and a current reuse grant.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import textwrap
import time

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest environment")

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
from tests.test_knowledge_task_frontier import fixture
from tests.test_knowledge_task_input import (admit, change_declaration, reseal_seed,
                                             small_catalog, source, span)
from tests.test_task_swarm_loop_executor_contract import CHILD
from runtime.task_swarm.learning_reuse import ReuseOwner, learning_source, purpose_digest
from runtime.task_swarm.protocol import SwarmError, canonical, digest
from runtime.task_swarm.task_backend import TaskBackend, checked_backend

MODE = "local_executable_fixture"
INTENT = "Preserve each established measurement and repair only the missing DocB measurement."
UNKNOWN = "An unacquired value stays explicitly unknown, never zero."

CALCULATION = textwrap.dedent(r'''
    import os, re, sqlite3
    core = request["input"].get("core", request["input"])
    with sqlite3.connect(cwd.parent.parent / "execution.sqlite") as db:
        row = db.execute("SELECT identity_json FROM attempts WHERE job_id=? AND state='leased'",
                         (request["dispatch"]["job_id"],)).fetchone()
    assert row is not None and json.loads(row[0])["pid"] == os.getpid()
    acquired, actual, evidence = [], {}, {}
    name = json.loads(core["purpose"].splitlines()[0].split(" DATA=", 1)[1])["doc"] if core["role"] == "work" else None
    partial = name == "DocB.md" and core["round"] == 0
    for material in request["materials"]:
        if name is not None and (partial or material["relative_path"] != name):
            continue
        with pathlib.Path(material["path"]).open("rb") as stream:
            data = stream.read(material["bytes"] + 1)
        assert len(data) == material["bytes"] and hashlib.sha256(data).hexdigest() == material["sha256"]
        acquired.append({"path": material["relative_path"], "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        # Each critic opens both files itself; it never trusts a worker's answer.
        value = re.findall(rb"^LOCAL_MEASUREMENT=(\d+)\r?$", data, re.M)
        assert len(value) == 1
        actual[material["relative_path"]] = int(value[0])
        record = next(s for s in core["view"]["spans"] if s["source_key"] == material["source_key"]
                      and s["start"] == 0 and s["end"] == len(data.decode("utf-8")))
        evidence[material["relative_path"]] = {k: record[k] for k in ("source_key", "source_revision", "start", "end")} | {"quote": record["text"]}
    learning, learning_evidence = [], []
    for record in core["view"]["spans"]:
        try:
            proposal = json.loads(record["text"])
        except ValueError:
            continue
        if isinstance(proposal, dict) and proposal.get("kind") == "task_learning_reuse_proposal":
            learning.append(record["sha256"])
            learning_evidence.append({k: record[k] for k in ("source_key", "source_revision", "start", "end")} | {"quote": record["text"]})
            if "DocA.md" in actual:
                assert proposal["selected"]["claim"]["text"] == str(actual["DocA.md"])
    (cwd / "child-acquisition.json").write_bytes(json.dumps({"materials": acquired, "learning": learning}).encode("utf-8"))
    if core["role"] == "work":
        result = {"job_id": request["dispatch"]["job_id"], "summary": "actual local bytes", "conflicts": [],
            "claims": [{"text": "unknown" if partial else str(actual[name]),
                        "status": "unknown" if partial else "supported",
                        "evidence": [] if partial else [evidence[name], *(learning_evidence if name == "DocA.md" else [])]}]}
    else:
        reports = request["input"]["reports"]
        b_job = next(job for job in core["required_evidence_jobs"]["A3"] if job.startswith("r1-" if core["round"] else "r0-"))
        a_job = core["required_evidence_jobs"]["A2"][0]
        assert reports[a_job]["claims"][0]["text"] == str(actual["DocA.md"])
        valid = reports[b_job]["claims"][0]["text"] == str(actual["DocB.md"])
        gap = {key: value for key, value in evidence["DocB.md"].items() if key != "quote"}
        result = {"parent_input_digest": core["view"]["parent_input_digest"], "plan_digest": core["view"]["plan_digest"],
            "round": core["round"], "report_digests": request["input"]["report_digests"], "validations": []}
        for key, assigned in core["required_evidence_jobs"].items():
            failed = key == "A3" and not valid
            result["validations"].append({"criterion_id": key, "status": "failed" if failed else "passed",
                "evidence": [] if failed else [{"job_id": job, "claim_index": 0} for job in assigned],
                "gap_reason": "DocB value is not established" if failed else None,
                "source_spans": [gap, *[{k: v for k, v in e.items() if k != "quote"} for e in learning_evidence]] if failed else []})
''')


def save(path, value):
    path.write_bytes((canonical(value) + "\n").encode("utf-8"))


def prepare(root, *, second=13, budget=6, fail=False, material_newline=None):
    small_catalog(root)
    expiry = dt.datetime.fromtimestamp(time.time() + 86400, dt.timezone.utc).isoformat()
    for path in (root / "knowledge/synthetic").glob("*.md"):
        raw = path.read_text(encoding="utf-8").replace("2026-12-07T00:00:00Z", expiry)
        if path.stem in {"0", "1"}:
            raw += f"\nLOCAL_MEASUREMENT={5 if path.stem == '0' else second}\n"
        path.write_text(raw, encoding="utf-8", newline=material_newline)
    spec = {"REQ-ROOT": {"children": ["REQ-A", "REQ-B"],
                         "acceptance": ["Every partial result is truthful and missing material stays unknown."]},
            "REQ-A": {"data": {"doc": "DocA.md"}, "acceptance": ["Preserve the established DocA measurement."]},
            "REQ-B": {"data": {"doc": "DocB.md"}, "acceptance": ["Acquire the actual DocB measurement."]}}
    _, seed, owner, file, _ = fixture(root, spec)
    script = CHILD.decode("utf-8")
    script = script[:script.index("acquired = []")] + CALCULATION + script[script.index("output = pathlib.Path"):]
    if fail:
        script = script.replace('acquired, actual, evidence = [], {}, {}', 'raise SystemExit(9)')
    executable = owner.parent / "worker.py"
    executable.write_text(script, encoding="utf-8")
    materials = []
    for index, name in enumerate(("DocA.md", "DocB.md")):
        row = next(row for row in seed["sources"] if row["key"] == source("synthetic/" + str(index), 1, "")["key"])
        raw = row["text"].encode("utf-8")
        (owner.parent / name).write_bytes(raw)
        materials.append({"path": name, "source_key": row["key"], "source_revision": row["revision"],
            "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "capability": "fixture_local_read_observation"})
    policy = {"kind": "task_loop_executor", "version": 1, "mode": MODE, "prompt_contract_version": 1,
        "visibility": "fixture_declared_material_observation", "materials": materials,
        "executable": {"path": executable.name, "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                       "bytes": executable.stat().st_size}}
    policy_text = canonical(policy)
    assert len(policy_text) <= 1000
    request = next(row for row in seed["sources"] if row["key"] == source("request", 1, "")["key"])
    request["text"] = INTENT + "\n" + UNKNOWN + "\n" + policy_text
    seed["request"] = INTENT
    def declaration(value):
        value["intent"] = {"original": span(request, INTENT), "replacements": []}
        value["constraints"] = [span(request, policy_text)]
        value["unknowns"] = [span(request, UNKNOWN)]
        value["budget"] = {"attempt_budget": budget, "deadline": time.time() + 600}
    change_declaration(seed, root, declaration)
    reseal_seed(seed, owner, file)
    document = json.loads(owner.read_bytes())
    document["binding"]["expires_at"] = time.time() + 900
    checks = [{"path": item["path"], "sha256": item["sha256"]} for item in [policy["executable"], *materials]]
    document["source_checks"].extend(checks)
    save(owner, document)
    return seed, owner, file, checks


def cli(root, owner, operation, *args, expected=0, timeout=60):
    outside = root.parent / "unrelated-cwd"
    outside.mkdir(exist_ok=True)
    process = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "tools/knowledge_base.py"),
        "task-input", operation, "--root", str(root), "--owner", str(owner), *map(str, args)],
        cwd=outside, capture_output=True, timeout=timeout)
    assert process.returncode == expected, process.stderr.decode("utf-8")
    return json.loads(process.stderr if expected == 2 else process.stdout)


def admit_executable(candidate, owner, file, checks):
    admit(candidate, owner, file)
    document = json.loads(owner.read_bytes())
    document["source_checks"].extend(checks)
    save(owner, document)


def compile_case(root, **options):
    seed, owner, file, checks = prepare(root, **options)
    before = owner.read_bytes()
    candidate = cli(root, owner, "compile", "--input", file)
    assert owner.read_bytes() == before
    target = root / "candidate.json"
    save(target, candidate)
    admit_executable(candidate, owner, file, checks)
    return seed, owner, file, checks, candidate, target


def execute(root, case, *, expected=0, extra=()):
    return cli(root, case[1], "execute", "--candidate", case[5], "--input", case[2],
        "--executor-mode", MODE, "--worker", "worker-a", "--worker", "worker-b", *extra,
        expected=expected, timeout=60)


def module_cli(root, case, *, python=None, expected=0, extra=(), explicit=True):
    """The installed probe passes its isolated interpreter, without path hooks."""
    plan = root / "supplied-plan.json"
    save(plan, case[4]["supplied_plan"])
    if python is None:
        loader = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('runtime.task_swarm.closed_loop',run_name='__main__')"
        command = [sys.executable, "-I", "-B", "-c", loader, str(ROOT)]
    else:
        command = [str(python), "-I", "-B", "-m", "kotodama_core.task_swarm.closed_loop"]
    outside = root.parent / "unrelated-cwd"
    outside.mkdir(exist_ok=True)
    process = subprocess.run([*command, "--owner", str(case[1]), "--input", str(case[2]), "--plan", str(plan),
        *(["--executor-mode", MODE] if explicit else []), "--worker", "worker-a", "--worker", "worker-b", *map(str, extra)],
        cwd=outside, capture_output=True, timeout=60)
    assert process.returncode == expected, process.stderr.decode("utf-8")
    return json.loads(process.stderr if expected == 2 else process.stdout)


def inspect_children(case, result, *, second=13, calls=5, learning=None):
    binding = json.loads(case[1].read_bytes())["binding"]
    directory = Path(binding["active_home"]) / result["receipt"]["run_id"]
    snapshot = json.loads((directory / "execution.json").read_bytes())
    assert result["receipt"]["budget"]["attempts_used"] == calls
    assert result["receipt"]["model_runtime_verified"] is False
    leaves = case[4]["diagnostics"]["frontier"]["leaf_jobs"]
    names = {row["requirement_id"]: "r0-" + row["job_id"] for row in leaves}
    a, b = names["REQ-A"], names["REQ-B"]
    repaired = "r1-repair-" + b[3:]
    assert json.loads((directory / (a + "-result.json")).read_bytes())["result"]["claims"][0]["text"] == "5"
    assert json.loads((directory / (b + "-result.json")).read_bytes())["result"]["claims"][0]["text"] == "unknown"
    assert {job for job in snapshot["jobs"] if job.startswith("r1-")} == ({repaired, "r1-critic"} if calls == 5 else set())
    if calls == 5:
        assert json.loads((directory / (repaired + "-result.json")).read_bytes())["result"]["claims"][0]["text"] == str(second)
    actors, invocations = {}, set()
    for job, row in snapshot["jobs"].items():
        attempt = row["current_attempt"]
        assert attempt["identity"]["kind"] == "process"
        value = json.loads((directory / (job + "-result.json")).read_bytes())
        runtime = value["receipt"]["runtime"]
        attempt_dir = Path(runtime["paths"]["attempt_dir"])
        raw = Path(runtime["paths"]["input"]).read_bytes()
        assert raw == (attempt_dir / "child-input.bin").read_bytes()
        request = json.loads(raw)
        assert request["dispatch"]["attempt"] == attempt["attempt"]
        from runtime.task_swarm.codex import _same_process
        assert not _same_process(attempt["identity"]["pid"], attempt["identity"]["created_at"])
        observed = json.loads((attempt_dir / "child-acquisition.json").read_bytes())
        expected_docs = [] if job == b else (["DocA.md", "DocB.md"] if job.endswith("critic") else
                                            ["DocA.md"] if job == a else ["DocB.md"])
        assert [item["path"] for item in observed["materials"]] == expected_docs
        assert observed["learning"] == ([] if learning is None else [learning_source(learning)["sha256"]])
        actors[job] = value["receipt"]["actor_ref"]
        invocations.add(value["receipt"]["invocation_ref"])
    assert len(invocations) == calls
    assert actors["r0-critic"] not in {actors[a], actors[b]}
    with sqlite3.connect(directory / "execution.sqlite") as db:
        assert db.execute("SELECT count(*) FROM attempts WHERE job_id=?", (a,)).fetchone()[0] == 1
    return directory


@pytest.mark.parametrize("second", [13, 23])
def test_fresh_source_cli_repair_and_anchored_replay(tmp_path, second):
    case = compile_case(tmp_path, second=second, material_newline="\r\n" if second == 23 else None)
    if second == 23:
        assert b"\r\n" in (case[1].parent/"DocB.md").read_bytes()
    before = case[1].read_bytes()
    result = execute(tmp_path, case)
    assert result["receipt"]["review_passed"] and case[1].read_bytes() == before
    directory = inspect_children(case, result, second=second)
    saved = {str(path.relative_to(directory)): path.read_bytes() for path in directory.rglob("child-input.bin")}
    replay = execute(tmp_path, case, extra=("--receipt-sha256", result["receipt_sha256"]))
    assert replay["duplicate"] and replay["receipt_sha256"] == result["receipt_sha256"]
    assert saved == {str(path.relative_to(directory)): path.read_bytes() for path in directory.rglob("child-input.bin")}
    assert case[1].read_bytes() == before


def test_original_budget_four_is_unresolved_and_replay_keeps_exit_three(tmp_path):
    case = compile_case(tmp_path, budget=4)
    result = execute(tmp_path, case, expected=3)
    assert not result["receipt"]["review_passed"] and result["learning_candidate"] is None
    assert result["candidate"]["stop_reason"] == "attempt_budget_exhausted"
    inspect_children(case, result, calls=3)
    assert execute(tmp_path, case, expected=3, extra=("--receipt-sha256", result["receipt_sha256"]))["duplicate"]


def test_fresh_core_module_requires_explicit_mode_and_replays_without_a_child(tmp_path):
    case = compile_case(tmp_path)
    assert module_cli(tmp_path, case, explicit=False, expected=2)["error"] == "LOOP_SIMULATION_REQUIRED"
    assert not list(case[1].parent.glob("task-run-*"))
    result = module_cli(tmp_path, case)
    directory = inspect_children(case, result)
    before = sorted(str(path) for path in directory.rglob("child-input.bin"))
    assert module_cli(tmp_path, case, extra=("--receipt-sha256", result["receipt_sha256"]))["duplicate"]
    assert before == sorted(str(path) for path in directory.rglob("child-input.bin"))


@pytest.mark.parametrize("kind", ["file", "directory"])
@pytest.mark.parametrize("entry", ["knowledge", "core"])
def test_external_cwd_cli_resolves_owner_aliases_with_relative_materials(tmp_path, kind, entry):
    case = list(compile_case(tmp_path))
    links = tmp_path/"owner-aliases"
    links.mkdir()
    alias = links/("owner.json" if kind == "file" else "owner-home")
    try:
        alias.symlink_to(case[1] if kind == "file" else case[1].parent, target_is_directory=kind == "directory")
    except OSError:
        pytest.skip("owner symlink creation is not available")
    case[1] = alias if kind == "file" else alias/case[1].name
    result = (execute if entry == "knowledge" else module_cli)(tmp_path, case)
    assert result["receipt"]["review_passed"]
    directory = inspect_children(case, result)
    saved = sorted(str(path) for path in directory.rglob("child-input.bin"))
    replay = (execute if entry == "knowledge" else module_cli)(tmp_path, case,
        extra=("--receipt-sha256", result["receipt_sha256"]))
    assert replay["duplicate"] and saved == sorted(str(path) for path in directory.rglob("child-input.bin"))


def test_implicit_anchor_replay_keeps_an_unresolved_receipt_at_exit_three(tmp_path):
    case = compile_case(tmp_path, budget=4)
    result = module_cli(tmp_path, case, expected=3)
    directory = inspect_children(case, result, calls=3)
    before = sorted(str(path) for path in directory.rglob("child-input.bin"))
    replay = module_cli(tmp_path, case, explicit=False, expected=3,
                        extra=("--receipt-sha256", result["receipt_sha256"]))
    assert replay["duplicate"] and replay["receipt"]["review_passed"] is False
    assert before == sorted(str(path) for path in directory.rglob("child-input.bin"))


def test_current_owner_policy_is_required_before_a_child_can_start(tmp_path):
    case = compile_case(tmp_path)
    document = json.loads(case[1].read_bytes())
    document["source_checks"] = [row for row in document["source_checks"] if row["path"] != "worker.py"]
    save(case[1], document)
    before = case[1].read_bytes()
    refused = execute(tmp_path, case, expected=2)
    assert refused["error"] == "LOOP_EXECUTOR_OWNER_MAPPING"
    assert not list(case[1].parent.glob("task-run-*")) and case[1].read_bytes() == before


def test_failed_real_child_returns_typed_refusal_without_a_success_receipt(tmp_path):
    case = compile_case(tmp_path, fail=True)
    before = case[1].read_bytes()
    assert execute(tmp_path, case, expected=2) == {"error": "LOOP_EXECUTOR_FAILURE", "message": "nonzero_exit"}
    assert not list(case[1].parent.glob("task-run-*/receipt.json"))
    assert case[1].read_bytes() == before


@pytest.mark.parametrize("second,owner_alias", [(13, False), (23, False), (23, True)])
def test_learning_cli_uses_current_decision_and_keeps_the_typed_transport(tmp_path, second, owner_alias):
    origin = compile_case(tmp_path, second=second, material_newline="\r\n" if second == 23 else None)
    completed = execute(tmp_path, origin)
    seed = copy.deepcopy(origin[0])
    seed["task_id"] = "task-00000000-0000-4000-8000-000000000002"
    owner, file = origin[1].with_name("learning-owner.json"), origin[2].with_name("learning-input.json")
    save(file, seed)
    document = json.loads(origin[1].read_bytes())
    area = owner.parent / "learning-task"
    area.mkdir()
    document["binding"].update(task_id=seed["task_id"], context_digest=digest(seed), active_home=str(area))
    document["storage"] = {"root": str(area), "mailbox": str(area / "mailbox.sqlite"), "payloads": str(area / "payloads")}
    document["source_checks"] = [*origin[4]["source_checks"], *origin[3],
        {"path": str(file), "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}]
    save(owner, document)
    index = next(i for i, claim in enumerate(completed["candidate"]["claims"]) if claim["claim"]["text"] == "5")
    origin_file = tmp_path / "learning-origin.json"
    save(origin_file, {"origin_owner": str(origin[1]), "origin_input": str(origin[2]),
        "origin_anchor": completed["receipt_sha256"], "claim_index": index})
    candidate = cli(tmp_path, owner, "compile", "--input", file, "--learning-origin", origin_file)
    target = tmp_path / "learning-candidate.json"
    save(target, candidate)
    admit_executable(candidate, owner, file, origin[3])
    learning = candidate["learning"]
    document = json.loads(owner.read_bytes())
    document["learning_reuse"] = {"version": 1, "grant_ref": "ref/grant/cli-learning",
        "policy_revision_ref": "ref/policy/cli-learning", "proposal_digest": digest(learning["proposal"]),
        "origin_receipt_sha256": learning["anchor"], "target_context_digest": digest(candidate["payload"]),
        "purpose_digest": purpose_digest(candidate["payload"]), "reviewer_ref": "verifier",
        "expires_at": document["binding"]["expires_at"]}
    save(owner, document)
    # This is the fixture owner's explicit current decision, not a runtime grant.
    reuse = ReuseOwner(learning["origin_owner"], learning["origin_input"], learning["anchor"],
                      owner, file, learning["proposal"])
    reuse.review("ref/review/cli-learning", "verifier", "allow", "Checked the retained DocA measurement.")
    decision = reuse.decide("ref/owner/synthetic", "ref/review/cli-learning", "allow",
                           "ref/decision/cli-learning", expected_generation=0)
    if owner_alias:
        link = tmp_path/"learning-owner-link.json"
        try:
            link.symlink_to(owner)
        except OSError:
            pytest.skip("owner symlink creation is not available")
        owner = link
    case = (seed, owner, file, origin[3], candidate, target)
    assert execute(tmp_path, case, expected=2)["error"] == "TASK_LEARNING_DECISION_REQUIRED"
    options = ("--learning-decision-digest", digest(decision))
    result = execute(tmp_path, case, extra=options)
    assert result["receipt"]["review_passed"]
    directory = inspect_children(case, result, learning=learning["proposal"], second=second)
    children = sorted(str(path) for path in directory.rglob("child-input.bin"))
    replay = execute(tmp_path, case, extra=(*options, "--receipt-sha256", result["receipt_sha256"]))
    assert replay["duplicate"]
    reuse.decide("ref/owner/synthetic", "ref/review/cli-learning", "revoke",
                 "ref/decision/cli-learning-revoked", expected_generation=1)
    refused = execute(tmp_path, case, expected=2, extra=(*options, "--receipt-sha256", result["receipt_sha256"]))
    assert refused["error"] == "REUSE_DECISION_STALE"
    assert children == sorted(str(path) for path in directory.rglob("child-input.bin"))


@pytest.mark.parametrize("method", ["produce_loop", "review_loop"])
def test_typed_wrapper_keeps_transport_and_pre_post_guards(method):
    events = []
    class Transport(TaskBackend):
        def produce_loop(self, *args, **kwargs):
            events.append("call")
            return {"observed": args, "options": kwargs}
        review_loop = produce_loop
    backend = Transport("fixture.py", loop_mode=MODE)
    wrapper = checked_backend(backend, lambda: events.append("guard"))
    assert isinstance(wrapper, TaskBackend) and wrapper.synthetic is False
    assert wrapper.codex is backend.codex and wrapper.loop_mode == MODE
    assert getattr(wrapper, method)("input", policy="bound") == {"observed": ("input",), "options": {"policy": "bound"}}
    assert events == ["guard", "call", "guard"]
    def refuse():
        raise SwarmError("TASK_CONTEXT_EXPIRED", "current context changed")
    with pytest.raises(SwarmError, match="TASK_CONTEXT_EXPIRED"):
        getattr(checked_backend(backend, refuse), method)("input")
    assert events == ["guard", "call", "guard"]
    checks = []
    def expire_after_call():
        checks.append("guard")
        if len(checks) == 2:
            refuse()
    with pytest.raises(SwarmError, match="TASK_CONTEXT_EXPIRED"):
        getattr(checked_backend(backend, expire_after_call), method)("input")
    assert checks == ["guard", "guard"] and events[-1] == "call"
