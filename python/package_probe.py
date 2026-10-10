"""Execute with an artifact installed in a new venv, outside the source checkout."""
import hashlib
import importlib
import importlib.abc
import importlib.metadata
import json
import pkgutil
import subprocess
import sys
import tempfile
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
assert len(modules) == 20
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
from kotodama_core.task_swarm.closed_loop_context import derive_child_view
from kotodama_core.task_swarm.closed_loop_contract import loop_criteria, validate_plan
loop_plan = {"version": 1, "parent_input_digest": core.digest(request), "jobs": [
    {"job_id": "inspect", "purpose": "Inspect the current supplied request.",
     "criterion_ids": list(loop_criteria(request)), "selected_spans": [span(current, current_request)]}]}
assert validate_plan(loop_plan, request) == loop_plan
view = derive_child_view(request, "r0-inspect", loop_plan["jobs"][0]["selected_spans"],
                         plan_digest=core.digest(loop_plan))
assert view["parent_input_digest"] == core.digest(request) and view["request"] == current_request
try:
    validate_input(request, binding, now=1150)
except core.SwarmError as error:
    assert error.code == "OBJECTIVE_DEADLINE_INVALID"
else:
    raise AssertionError("expired objective accepted for new work")
assert validate_input(request, binding, now=1150, allow_expired_objective=True) == request

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
