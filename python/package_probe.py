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
assert len(modules) == 16
for module in modules:
    importlib.import_module(module.name)
distribution = importlib.metadata.distribution("kotodama-core")
assert distribution.version == core.__version__
scripts = {entry.name: entry.value for entry in distribution.entry_points if entry.group == "console_scripts"}
assert scripts == {"kotodama-core": "kotodama_core.cli:main"}
result = subprocess.run([sys.executable, "-I", "-m", "kotodama_core"], check=True, capture_output=True, text=True, timeout=10)
diagnostic = json.loads(result.stdout)
assert diagnostic["self_check"] is True and diagnostic["provider_verified"] is False
assert diagnostic["public_beta"] == "NO_GO_UNPUBLISHED"
subprocess.run([sys.executable, "-I", "-m", "kotodama_core.task_swarm.mcp_server", "--help"], check=True, capture_output=True, timeout=10)
with tempfile.TemporaryDirectory() as temporary:
    peer = Path(temporary) / "peer"
    venv.EnvBuilder(with_pip=False).create(peer)
    executable = peer / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run([str(executable), "-I", "-c", "import importlib.util; assert importlib.util.find_spec('kotodama_core') is None"], check=True, capture_output=True, timeout=10)
    # The external peer has no core distribution, yet can bootstrap sibling code
    # from this exact installed artifact before loading its optional MCP dependency.
    server = Path(swarm.__file__).with_name("mcp_server.py")
    subprocess.run([str(executable), "-I", str(server), "--help"], check=True, capture_output=True, timeout=10)
print(json.dumps({"status": "INSTALLED_CANDIDATE_PASS", "modules": len(modules), "version": core.__version__, "provider_verified": False}))
