"""Synthetic permission probes only; no model, provider or real auth file."""
import json
import os
from pathlib import Path
import shutil
import sys

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest job")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from task_swarm.confidential import ConfidentialScope, profile, runtime_paths
from task_swarm.protocol import SwarmError


def test_profile_does_not_extend_a_broad_read_or_write_preset():
    args = profile("fixture", {"/synthetic/input":"read"}, network=False)
    assert 'permissions.fixture.filesystem={":root"="deny","/synthetic/input"="read"}' in args
    assert "permissions.fixture.network.enabled=false" in args
    assert not any(":minimal" in item or "extends" in item for item in args)


@pytest.mark.skipif(os.name == "posix", reason="non-POSIX refusal")
def test_native_windows_never_claims_task_confidentiality(tmp_path):
    with pytest.raises(SwarmError) as raised:
        ConfidentialScope(tmp_path, sys.executable)
    assert raised.value.code == "CONFIDENTIAL_SCOPE_REQUIRES_POSIX"


@pytest.mark.skipif(os.name != "posix", reason="POSIX isolation construction")
def test_dedicated_home_preserves_auth_without_aliasing_ambient_login(tmp_path):
    auth_home = tmp_path/"original"
    auth_home.mkdir(mode=0o700)
    auth = auth_home/"auth.json"
    auth.write_text('{"synthetic":true}', encoding="utf-8")
    auth.chmod(0o600)
    (auth_home/"unrelated-private-file").write_text("not an input", encoding="utf-8")
    attempt = tmp_path/"attempt"
    attempt.mkdir()
    scope = ConfidentialScope(attempt, sys.executable, task_codex_home=auth_home, environment={"PATH":os.environ.get("PATH",""),"CODEX_HOME":str(tmp_path/"ambient"),"PRIVATE_TEST_ENV":"must-not-propagate"})
    assert scope.codex_home == auth_home and not auth.is_symlink()
    assert not list(attempt.rglob("auth.json"))
    assert "PRIVATE_TEST_ENV" not in scope.env and scope.env["HOME"] != str(auth_home)
    assert any(str(auth_home) in arg for arg in scope.outer)
    assert not any(str(auth_home) in arg for arg in scope.inner)
    assert auth.read_text(encoding="utf-8") == '{"synthetic":true}'
    with pytest.raises(SwarmError) as raised:
        scope.wrap([sys.executable,"exec","-s","read-only","-"])
    assert raised.value.code == "CONFIDENTIAL_PREFLIGHT_REQUIRED"


@pytest.mark.skipif(os.name != "posix", reason="POSIX ownership and link checks")
@pytest.mark.parametrize("kind", ["ambient", "symlink", "hardlink", "public"])
def test_shared_or_aliased_auth_is_refused_before_sandbox(tmp_path, kind):
    home = tmp_path/"dedicated"
    home.mkdir(mode=0o700)
    auth = home/"auth.json"
    source = tmp_path/"synthetic-auth"
    source.write_text("{}", encoding="utf-8")
    source.chmod(0o600)
    if kind == "symlink":
        auth.symlink_to(source)
    elif kind == "hardlink":
        auth.hardlink_to(source)
    else:
        auth.write_text("{}", encoding="utf-8")
        auth.chmod(0o644 if kind == "public" else 0o600)
    attempt = tmp_path/"attempt"
    attempt.mkdir()
    with pytest.raises(SwarmError):
        ConfidentialScope(attempt, sys.executable, task_codex_home=home,
                          environment={"CODEX_HOME":str(home if kind == "ambient" else tmp_path/"ambient")})
    assert source.read_text(encoding="utf-8") == "{}"
    assert list(attempt.iterdir()) == []


@pytest.mark.skipif(os.name != "posix", reason="actual POSIX Codex sandbox")
def test_actual_codex_sandbox_denies_sibling_and_metadata_reads_without_a_model(tmp_path, monkeypatch):
    executable = os.environ.get("KOTODAMA_TEST_CODEX_SANDBOX")
    if not executable:
        pytest.skip("the CI job installs and pins the Codex sandbox binary")
    auth_home = tmp_path/"synthetic-auth"
    auth_home.mkdir(mode=0o700)
    (auth_home/"auth.json").write_text("{}", encoding="utf-8")
    (auth_home/"auth.json").chmod(0o600)
    attempt = tmp_path/"attempt"
    attempt.mkdir()
    scope = ConfidentialScope(attempt, executable, task_codex_home=auth_home,
                              environment={"PATH":os.environ["PATH"],"CODEX_HOME":str(tmp_path/"ambient")})
    import subprocess
    run = subprocess.run
    observed = []
    def capture(*args, **kwargs):
        result = run(*args, **kwargs)
        observed.append((result.returncode,result.stdout[:2000],result.stderr[:4000]))
        return result
    monkeypatch.setattr(subprocess,"run",capture)
    try:
        proof = scope.preflight()
    except SwarmError:
        # This test has only synthetic files/auth; retain bounded CLI diagnostics.
        pytest.fail(repr(observed))
    assert proof["outer_read_denied"] and proof["inner_metadata_read_denied"]
    assert proof["model_called"] is False
    command = scope.wrap([str(Path(executable).resolve()),"exec","-s","read-only","-"])
    assert "read-only" not in command
    assert 'default_permissions="task-input"' in command
    for feature in ("apps","plugins","shell_tool","unified_exec","view_image","browser_use"):
        assert f"features.{feature}=false" in command
