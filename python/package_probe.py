"""Execute with an artifact installed in a new venv, outside the source checkout."""
import hashlib
import copy
import importlib
import importlib.abc
import importlib.metadata
import json
import pkgutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import os
import venv


class PrivateImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"runtime", "task_swarm", "kotodama_operator", "kotodama_control_plane", "ktdm"}:
            raise AssertionError("private or unqualified namespace import")


sys.meta_path.insert(0, PrivateImports())
import kotodama_core as core
import kotodama_core.task_swarm as swarm

assert set(core.__all__) == {"__version__", "canonical", "digest", "SwarmError"}
value = {"日本語": [1, True, None], "a": "é"}
expected = '{"a":"é","日本語":[1,true,null]}'
assert core.canonical(value) == expected
assert core.digest(value) == hashlib.sha256(expected.encode("utf-8")).hexdigest()
try:
    core.canonical(float("nan"))
except core.SwarmError as error:
    assert error.code == "INVALID_DOCUMENT"
else:
    raise AssertionError("non-finite JSON accepted")
cycle = []
cycle.append(cycle)
for invalid in ({1: "value"}, {"nested": {None: "value"}}, (1, 2), "\ud800", cycle):
    for api in (core.canonical, core.digest):
        try:
            api(invalid)
        except core.SwarmError as error:
            assert error.code == "INVALID_DOCUMENT"
        else:
            raise AssertionError("non-JSON input was silently coerced")
modules = list(pkgutil.iter_modules(swarm.__path__, swarm.__name__ + "."))
assert len(modules) == 27
for module in modules:
    importlib.import_module(module.name)
# Exercise both input versions from the installed namespace. Import enumeration
# alone can miss a newly omitted module until a runtime-only branch reaches it.
from kotodama_core.task_swarm.task_contract import criteria, make_plan, validate_input

def source(revision, text):
    return {"key": "a" * 64, "revision": revision, "text": text,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}

def span(record, text):
    start = record["text"].index(text)
    return {"source_key": record["key"], "source_revision": record["revision"],
            "start": start, "end": start + len(text)}

original = source(1, "Original synthetic request")
request = {"version": 1, "task_id": "task-00000000-0000-4000-8000-000000000001", "revision": 2,
           "request": original["text"], "acceptance": [], "sources": [original]}
binding = {"task_id": request["task_id"], "revision": request["revision"],
           "context_digest": core.digest(request), "owner_ref": "ref/owner/fixture",
           "active_home": "fixture", "authority_ref": "ref/authority/fixture",
           "capability_ref": "ref/capability/swarm_research", "expires_at": 1200, "status": "active"}
assert validate_input(request, binding, now=1000) == request
assert make_plan(request, binding, now=1000)["budget"]["deadline"] == 1200
current = source(2, "Current synthetic request\nRead only\nResult unknown\nShow evidence\nOUT-INTENT")
current_request, constraint, unknown, acceptance, goal = current["text"].splitlines()
request.update(version=2, request=current_request, acceptance=[acceptance], sources=[original, current],
               objective={"owner_ref": binding["owner_ref"],
                          "intent": {"original": span(original, original["text"]),
                                     "replacements": [span(current, current_request)]},
                          "references": [{"kind": "goal", "id": goal, "source": span(current, goal)}],
                          "constraints": [span(current, constraint)], "unknowns": [span(current, unknown)],
                          "acceptance": [span(current, acceptance)],
                          "budget": {"attempt_budget": 4, "deadline": 1100},
                          "stop_conditions": ["cancelled", "binding_changed", "deadline_exceeded"],
                          "rollback": "not_applicable_read_only"})
binding["context_digest"] = core.digest(request)
assert validate_input(request, binding, now=1000) == request
assert make_plan(request, binding, now=1000)["budget"]["deadline"] == 1100
assert {"O1", "Q1"} <= criteria(request).keys()
from kotodama_core.task_swarm.repair_planning import derive_repair, make_impact, profile
assert callable(derive_repair) and callable(make_impact)
assert profile({}) is None
from kotodama_core.task_swarm.closed_loop_context import derive_child_view
from kotodama_core.task_swarm.closed_loop import cancel_closed_loop
assert callable(cancel_closed_loop)
from kotodama_core.task_swarm.closed_loop_contract import loop_criteria, validate_plan, work_input, required_evidence_jobs
loop_plan = {"version": 1, "parent_input_digest": core.digest(request), "jobs": [
    {"job_id": "inspect", "purpose": "Inspect the current supplied request.",
     "criterion_ids": list(loop_criteria(request)), "selected_spans": [span(current, current_request)]}]}
assert validate_plan(loop_plan, request) == loop_plan
view = derive_child_view(request, "r0-inspect", loop_plan["jobs"][0]["selected_spans"],
                         plan_digest=core.digest(loop_plan))
assert view["parent_input_digest"] == core.digest(request) and view["request"] == current_request
from kotodama_core.task_swarm.owner_file import OwnerFile
from kotodama_core.task_swarm.state import SwarmState
with tempfile.TemporaryDirectory() as temporary:
    # Exercise the installed adapter against the same existing owner/run. This
    # is state-only setup, not evidence of a provider or worker execution.
    root = Path(temporary) / "operations"
    root.mkdir()
    payload_path, owner_path = Path(temporary) / "input.json", Path(temporary) / "owner.json"
    payload_path.write_bytes(core.canonical(request).encode("utf-8"))
    task_binding = {**binding, "active_home": str(root)}
    owner_path.write_bytes(core.canonical({"binding": task_binding,
        "actors": {"worker": {"epoch": 1, "invocation_ref": "installed-worker",
            "actor_status": "active", "capability_ref": binding["capability_ref"], "peers": []}},
        "allowed_actions": [], "source_checks": [{"path": str(payload_path),
            "sha256": hashlib.sha256(payload_path.read_bytes()).hexdigest()}],
        "storage": {"root": str(root), "mailbox": str(root / "mailbox"),
                    "payloads": str(root / "payloads")}}).encode("utf-8"))
    run_id = "task-run-" + core.digest([request["task_id"], request["revision"]])[:32]
    directory = root / run_id
    directory.mkdir()
    for name, value in {"input.json": request, "specification.json": loop_plan}.items():
        (directory / name).write_bytes(core.canonical(value).encode("utf-8"))
    owner = OwnerFile(owner_path, clock=lambda: 1000)
    state = SwarmState(directory / "execution.sqlite", owner.read_task, clock=lambda: 1000)
    work = work_input(request, loop_plan["jobs"][0], 0, core.digest(loop_plan),
                      round_plan_digest=core.digest(loop_plan))
    template = {"role": "critic", "job_id": "r0-critic", "round": 0,
        "round_plan_digest": core.digest(loop_plan), "criteria": loop_criteria(request),
        "view": derive_child_view(request, "r0-critic", loop_plan["jobs"][0]["selected_spans"],
                                  plan_digest=core.digest(loop_plan)),
        "evidence_contract_version": 2, "required_evidence_jobs": required_evidence_jobs(request, loop_plan)}
    (directory / "r0-critic-template.json").write_bytes(core.canonical(template).encode("utf-8"))
    execution_plan = state.create_run({"run_id": run_id, "task_id": request["task_id"],
        "binding_digest": core.digest(owner.read_task()),
        "budget": {"attempt_budget": 4, "concurrency": 1, "deadline": 1100},
        "jobs": [{"job_id": "r0-inspect", "kind": "work", "dependencies": [],
            "exclusive_keys": [], "payload_ref": "ref/installed/input", "payload_digest": core.digest(work)},
            {"job_id": "r0-critic", "kind": "review", "dependencies": ["r0-inspect"],
            "exclusive_keys": [], "payload_ref": "ref/installed/template", "payload_digest": core.digest(template)}]})
    (directory / "plan.json").write_bytes(core.canonical(execution_plan).encode("utf-8"))
    cancelled = cancel_closed_loop(owner_path, payload_path, clock=lambda: 1000)
    assert cancelled == cancel_closed_loop(owner_path, payload_path, clock=lambda: 1150)
    assert state.snapshot(run_id)["run_state"] == "cancelled"
    assert not (directory / "receipt.json").exists()
try:
    validate_input(request, binding, now=1150)
except core.SwarmError as error:
    assert error.code == "OBJECTIVE_DEADLINE_INVALID"
else:
    raise AssertionError("expired objective accepted for new work")
assert validate_input(request, binding, now=1150, allow_expired_objective=True) == request


def check_dependency_execution():
    """Exercise installed release, long-ID repair, receipt and CLI readback."""
    from kotodama_core.task_swarm.closed_loop import execute_closed_loop
    payload = copy.deepcopy(request)
    measured = {**source(1, "value=17\nIncrement the accepted value"), "key": "c" * 64}
    payload["sources"].append(measured)
    payload["acceptance"].append("Increment the accepted value")
    payload["objective"]["acceptance"].append(span(measured, "Increment the accepted value"))
    payload["objective"]["budget"] = {"attempt_budget": 6, "deadline": time.time() + 600}
    shared = [key for key in loop_criteria(payload) if not key.startswith("A")]
    selected = [span(measured, "value=17")]
    plan = {"version": 2, "parent_input_digest": core.digest(payload), "jobs": [
        {"job_id": "a", "purpose": "Read the supplied value.", "requires": [],
         "criterion_ids": [*shared, "A1"], "selected_spans": selected},
        {"job_id": "z" * 56, "purpose": "Increment the accepted value.", "requires": ["a"],
         "criterion_ids": [*shared, "A2"], "selected_spans": selected}]}

    class Calculation:
        synthetic = True

        def __init__(self):
            self.inputs = []

        def response(self, delivered, result, actor):
            self.inputs.append(copy.deepcopy(delivered))
            name = delivered.get("job_id", delivered.get("core", {}).get("job_id"))
            return {"result": result, "receipt": {"actor_ref": actor,
                "invocation_ref": "installed-" + name, "input_digest": core.digest(delivered), "synthetic": True}}

        def produce(self, delivered, directory, *, actor_ref, **_kwargs):
            record = next(s for s in delivered["view"]["spans"] if s["text"].startswith("value="))
            text, status = record["text"], "supported"
            if "prerequisite" in delivered:
                accepted = int(delivered["prerequisite"]["report"]["claims"][0]["text"].split("=")[1])
                text, status = "derived=" + str(accepted + (2 if delivered["round"] == 0 else 1)), "inference"
            evidence = {key: record[key] for key in ("source_key", "source_revision", "start", "end")}
            return self.response(delivered, {"job_id": delivered["job_id"], "summary": text, "conflicts": [],
                "claims": [{"text": text, "status": status, "evidence": [{**evidence, "quote": record["text"]}]}]}, actor_ref)

        def review(self, delivered, directory, *, actor_ref, **_kwargs):
            view = delivered.get("view", delivered.get("core", {}).get("view"))
            record = next(s for s in view["spans"] if s["text"].startswith("value="))
            if "core" in delivered:
                assert delivered["report"]["claims"][0]["text"] == record["text"]
                result = {"kind": "prerequisite_review", "version": 1,
                    "descriptor_sha256": delivered["descriptor_sha256"], "report_sha256": delivered["report_sha256"],
                    "validations": [{"criterion_id": key, "status": "passed",
                        "evidence": [{"job_id": "r0-a", "claim_index": 0}]} for key in delivered["core"]["gate"]]}
            else:
                expected = int(record["text"].split("=")[1]) + 1
                reports = delivered["reports"]
                gap = {key: record[key] for key in ("source_key", "source_revision", "start", "end")}
                validations = []
                for key, assigned in delivered["required_evidence_jobs"].items():
                    current = [job for job in assigned if job.startswith("r1-")] or assigned
                    failed = key == "A2" and any(reports[job]["claims"][0]["text"] != f"derived={expected}" for job in current)
                    validations.append({"criterion_id": key, "status": "failed" if failed else "passed",
                        "evidence": [] if failed else [{"job_id": job, "claim_index": 0} for job in assigned],
                        "gap_reason": "Independent arithmetic mismatch" if failed else None,
                        "source_spans": [gap] if failed else []})
                result = {"parent_input_digest": core.digest(payload), "plan_digest": view["plan_digest"],
                    "round": delivered["round"], "report_digests": {job: core.digest(report) for job, report in reports.items()},
                    "validations": validations}
            return self.response(delivered, result, actor_ref)

    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        root = folder / "operations"
        root.mkdir()
        payload_path, owner_path = folder / "input.json", folder / "owner.json"
        def write(path, value):
            path.write_bytes((core.canonical(value) + "\n").encode("utf-8"))
        write(payload_path, payload)
        actors = ["worker-a", "worker-b", "verifier"]
        write(owner_path, {"binding": {**binding, "context_digest": core.digest(payload),
                "active_home": str(root), "expires_at": time.time() + 1200},
            "actors": {actor: {"epoch": 1, "invocation_ref": "installed-" + actor,
                "actor_status": "active", "capability_ref": binding["capability_ref"], "peers": []} for actor in actors},
            "allowed_actions": [], "source_checks": [{"path": str(payload_path),
                "sha256": hashlib.sha256(payload_path.read_bytes()).hexdigest()}],
            "storage": {"root": str(root), "mailbox": str(root / "mailbox"), "payloads": str(root / "payloads")}})
        backend = Calculation()
        result = execute_closed_loop(owner_path, payload_path, plan, backend, worker_actors=actors[:2])
        assert result["receipt"]["version"] == 3 and result["receipt"]["review_passed"]
        assert result["receipt"]["budget"]["attempts_used"] == len(backend.inputs) == 6
        directory = root / result["receipt"]["run_id"]
        execution = json.loads((directory / "execution.json").read_text(encoding="utf-8"))
        repaired = next(value for value in backend.inputs if value.get("job_id") == "r1-repair-1")
        assert repaired["prerequisite"]["certificate"] == execution["dependency_stage"]["certificate"]
        assert result["receipt"]["preaccepted"]["r0-a"]["accepted_at"] == execution["jobs"]["r0-a"]["accepted_at"]
        plan_path, scenario_path = folder / "plan.json", folder / "scenario.json"
        write(plan_path, plan)
        write(scenario_path, {"work": {}, "critics": {}, "repair_plan": None})
        replay = subprocess.run([sys.executable, "-I", "-m", "kotodama_core.task_swarm.closed_loop",
            "--owner", str(owner_path), "--input", str(payload_path), "--plan", str(plan_path),
            "--worker", "worker-a", "--worker", "worker-b", "--simulation", str(scenario_path),
            "--receipt-sha256", result["receipt_sha256"]], check=True, capture_output=True, text=True, timeout=30)
        assert json.loads(replay.stdout)["receipt_sha256"] == result["receipt_sha256"]


check_dependency_execution()

distribution = importlib.metadata.distribution("kotodama-core")
assert distribution.version == core.__version__
scripts = {entry.name: entry.value for entry in distribution.entry_points if entry.group == "console_scripts"}
assert scripts == {"kotodama-core": "kotodama_core.cli:main"}
result = subprocess.run([sys.executable, "-I", "-m", "kotodama_core"], check=True, capture_output=True, text=True, timeout=10)
diagnostic = json.loads(result.stdout)
assert diagnostic["self_check"] is True and diagnostic["provider_verified"] is False
assert diagnostic["public_beta"] == "NO_GO_UNPUBLISHED"
subprocess.run([sys.executable, "-I", "-m", "kotodama_core.task_swarm.mcp_server", "--help"], check=True, capture_output=True, timeout=10)
subprocess.run([sys.executable, "-I", "-m", "kotodama_core.task_swarm.closed_loop", "--help"], check=True, capture_output=True, timeout=10)
subprocess.run([sys.executable, "-I", "-m", "kotodama_core.task_swarm.learning_reuse", "--help"], check=True, capture_output=True, timeout=10)
with tempfile.TemporaryDirectory() as temporary:
    peer = Path(temporary) / "peer"
    venv.EnvBuilder(with_pip=False).create(peer)
    executable = peer / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run([str(executable), "-I", "-c", "import importlib.util; assert importlib.util.find_spec('kotodama_core') is None"], check=True, capture_output=True, timeout=10)
    # The external peer has no core distribution, yet can bootstrap sibling code
    # from this exact installed artifact before loading its optional MCP dependency.
    server = Path(swarm.__file__).with_name("mcp_server.py")
    subprocess.run([str(executable), "-I", str(server), "--help"], check=True, capture_output=True, timeout=10)
print(json.dumps({"status": "INSTALLED_CANDIDATE_PASS", "modules": len(modules), "task_input_versions": [1, 2], "version": core.__version__, "provider_verified": False}))
