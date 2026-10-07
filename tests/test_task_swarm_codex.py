from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import threading
import time
from types import SimpleNamespace
import venv

try:
    import pytest
except ModuleNotFoundError:  # the core unittest gate installs only requirements-ci.txt
    import unittest
    raise unittest.SkipTest("runs under pytest in the required Task swarm validation job (requirements-task-swarm-ci.txt)")


RUNTIME = Path(__file__).resolve().parents[1] / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from task_swarm.codex import BackendError, CodexBackend, _build_command
import task_swarm.codex as codex


THREAD = "11111111-1111-4111-8111-111111111111"
TURN = "22222222-2222-4222-8222-222222222222"
SCHEMA = {
    "type": "object",
    "required": ["job", "answer"],
    "properties": {"job": {"type": "string"}, "answer": {"type": "string", "enum": ["ok"]}},
    "additionalProperties": False,
}


def test_precancelled_attempt_does_not_create_directory_or_child(tmp_path, monkeypatch):
    cancelled = threading.Event()
    cancelled.set()
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("must not spawn"))
    with pytest.raises(BackendError) as raised:
        CodexBackend("not-invoked").invoke("fixture", SCHEMA, tmp_path / "attempt", cancel_event=cancelled)
    assert raised.value.code == "cancelled" and raised.value.retryable is False
    assert not (tmp_path / "attempt").exists()


def test_invalid_cancellation_hook_is_rejected_before_work(tmp_path):
    with pytest.raises(BackendError) as raised:
        CodexBackend("not-invoked").invoke("fixture", SCHEMA, tmp_path / "attempt", cancel_event=lambda: True)
    assert raised.value.code == "cancellation_invalid"
    assert not (tmp_path / "attempt").exists()


def test_invalid_unicode_prompt_is_refused_before_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("must not spawn"))
    with pytest.raises(BackendError) as raised:
        CodexBackend("not-invoked").invoke("\ud800", SCHEMA, tmp_path / "attempt")
    assert raised.value.code == "prompt_invalid" and raised.value.retryable is False
    assert not (tmp_path / "attempt").exists()


@pytest.mark.parametrize("during_input", [False, True])
def test_owner_cancels_owned_child_even_when_it_never_reads_stdin(tmp_path, monkeypatch, during_input):
    fake = _fake_codex(tmp_path)
    monkeypatch.setenv("FAKE_MODE", "timeout")
    cancelled = threading.Event()
    timers = []
    seen = []
    def started(pid, created):
        seen.append((pid, created))
        if during_input:
            timer = threading.Timer(.15, cancelled.set)
            timer.start()
            timers.append(timer)
        else:
            cancelled.set()
    began = time.monotonic()
    try:
        with pytest.raises(BackendError) as raised:
            CodexBackend(fake).invoke("x" * (2 * 1024 * 1024), SCHEMA, tmp_path / "attempt",
                                      timeout=20, cancel_event=cancelled, on_process=started)
        assert raised.value.code == "cancelled" and raised.value.retryable is False
        assert time.monotonic() - began < 6
        assert len(seen) == 1 and not codex._same_process(*seen[0])
        assert not Path(raised.value.paths["receipt"]).exists()
        diagnostics = json.loads(Path(raised.value.paths["diagnostics"]).read_text(encoding="utf-8"))
        assert diagnostics["error_code"] == "cancelled"
        assert diagnostics["cleanup"] in {"terminated", "already_exited", "killed_after_terminate_timeout"}
        assert not list(Path(raised.value.paths["attempt_dir"]).glob("*.raw"))
    finally:
        for timer in timers:
            timer.cancel()
            timer.join()


def test_timeout_is_observed_while_prompt_pipe_is_full(tmp_path, monkeypatch):
    fake = _fake_codex(tmp_path)
    monkeypatch.setenv("FAKE_MODE", "timeout")
    began = time.monotonic()
    with pytest.raises(BackendError) as raised:
        CodexBackend(fake).invoke("x" * (2 * 1024 * 1024), SCHEMA, tmp_path / "attempt", timeout=.15)
    assert raised.value.code == "timeout"
    assert time.monotonic() - began < 6


def test_unconfirmed_stop_is_nonretryable_and_never_claims_cancellation_complete(tmp_path, monkeypatch):
    fake = _fake_codex(tmp_path)
    monkeypatch.setenv("FAKE_MODE", "timeout")
    cancelled = threading.Event()
    seen = []
    same_process = codex._same_process
    def started(pid, created):
        seen.append((pid, created))
        cancelled.set()
    monkeypatch.setattr(codex, "_same_process", lambda *args: False)
    try:
        with pytest.raises(BackendError) as raised:
            CodexBackend(fake).invoke("fixture", SCHEMA, tmp_path / "attempt", timeout=5,
                                      cancel_event=cancelled, on_process=started)
        assert raised.value.code == "stop_unconfirmed" and raised.value.retryable is False
        assert raised.value.diagnostics["cleanup"] == "identity_not_confirmed"
        assert same_process(*seen[0])
        assert not Path(raised.value.paths["receipt"]).exists()
    finally:
        # Restore real ownership checking before stopping only this test's child.
        if seen and same_process(*seen[0]):
            child = codex.psutil.Process(seen[0][0])
            child.terminate()
            child.wait(timeout=5)


def test_internal_failure_cannot_retry_while_child_stop_is_unconfirmed(tmp_path, monkeypatch):
    fake = _fake_codex(tmp_path)
    monkeypatch.setenv("FAKE_MODE", "timeout")
    seen = []
    same_process, original_fstat = codex._same_process, os.fstat
    def unavailable(_fd):
        raise OSError("synthetic observation failure")
    def started(pid, created):
        seen.append((pid, created))
        monkeypatch.setattr(codex, "_same_process", lambda *args: False)
        monkeypatch.setattr(os, "fstat", unavailable)
    try:
        with pytest.raises(BackendError) as raised:
            CodexBackend(fake).invoke("fixture", SCHEMA, tmp_path / "attempt", timeout=5, on_process=started)
        assert raised.value.code == "stop_unconfirmed" and raised.value.retryable is False
        assert same_process(*seen[0])
        assert not Path(raised.value.paths["receipt"]).exists()
    finally:
        monkeypatch.setattr(os, "fstat", original_fstat)
        if seen and same_process(*seen[0]):
            child = codex.psutil.Process(seen[0][0])
            child.terminate()
            child.wait(timeout=5)


def test_cancellation_during_result_validation_never_publishes_completion(tmp_path, monkeypatch):
    fake = _fake_codex(tmp_path)
    monkeypatch.setenv("FIXTURE_SESSIONS", str(tmp_path / "sessions"))
    cancelled = threading.Event()
    validate = codex._validate_schema
    def changed(*args, **kwargs):
        value = validate(*args, **kwargs)
        cancelled.set()
        return value
    monkeypatch.setattr(codex, "_validate_schema", changed)
    with pytest.raises(BackendError) as raised:
        CodexBackend(fake, session_root=tmp_path / "sessions").invoke(
            "fixture", SCHEMA, tmp_path / "attempt", timeout=5, cancel_event=cancelled)
    assert raised.value.code == "cancelled"
    assert not Path(raised.value.paths["receipt"]).exists()


def _fake_codex(tmp_path: Path) -> Path:
    script = tmp_path / "fake_codex.py"
    script.write_text(
        textwrap.dedent(
            r'''
            import json, os, pathlib, sys, time
            from datetime import datetime, timezone
            args = sys.argv[1:]
            output = pathlib.Path(args[args.index("--output-last-message") + 1])
            mode = os.environ.get("FAKE_MODE", "success")
            if mode == "timeout":
                time.sleep(10)
            if mode == "flood":
                chunk = "x" * 65536 + "\n"
                for _ in range(int(os.environ.get("FAKE_FLOOD_CHUNKS", "0"))):
                    sys.stdout.write(chunk)
                sys.stdout.flush()
                time.sleep(10)
            answer = os.environ.get("FAKE_ANSWER", "ok")
            output.write_text(json.dumps({"job": "fixture", "answer": answer}), encoding="utf-8")
            thread = "11111111-1111-4111-8111-111111111111"
            turn = "22222222-2222-4222-8222-222222222222"
            print(json.dumps({"type": "thread.started", "thread_id": thread}))
            print(json.dumps({"type": "turn.started", "turn_id": turn}))
            print(json.dumps({"type": "turn.completed", "turn_id": turn}))
            root = pathlib.Path(os.environ["FIXTURE_SESSIONS"])
            root.mkdir(parents=True, exist_ok=True)
            lines = [
              {"type":"session_meta","payload":{"id":thread,"session_id":thread,"cwd":str(pathlib.Path.cwd()),"timestamp":datetime.now(timezone.utc).isoformat()}},
              {"type":"turn_context","payload":{"turn_id":turn,"model":"gpt-5.6-luna","effort":"max","approval_policy":"never","sandbox_policy":{"type":"read-only"}}},
              {"type":"event_msg","payload":{"type":"task_complete","turn_id":turn,"completed_at":1,"last_agent_message":json.dumps({"job":"fixture","answer":answer})}},
            ]
            if mode == "missing_cwd":
                lines[0]["payload"].pop("cwd")
            if mode == "wrong_output":
                lines[-1]["payload"]["last_agent_message"] = json.dumps({"job":"substituted","answer":"ok"})
            if mode == "stale":
                lines[0]["payload"]["timestamp"] = "2000-01-01T00:00:00Z"
            (root / ("rollout-" + thread + ".jsonl")).write_text("\n".join(json.dumps(item) for item in lines) + "\n", encoding="utf-8")
            '''
        ),
        encoding="utf-8",
    )
    return script


def test_backend_binds_process_stdout_and_completed_rollout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake_codex(tmp_path)
    sessions = tmp_path / "sessions"
    monkeypatch.setenv("FIXTURE_SESSIONS", str(sessions))
    seen: list[tuple[int, float]] = []
    result = CodexBackend(fake, session_root=sessions).invoke(
        "fixture prompt",
        SCHEMA,
        tmp_path / "attempts",
        timeout=2,
        on_process=lambda pid, created: seen.append((pid, created)),
    )
    assert result["result"] == {"job": "fixture", "answer": "ok"}
    assert result["receipt"]["thread_id"] == THREAD
    assert result["receipt"]["turn_id"] == TURN
    assert result["receipt"]["completed"] is True
    assert result["receipt"]["model_observed"] == "gpt-5.6-luna"
    assert result["receipt"]["artifact_digests"]["events"]
    assert len(seen) == 1 and seen[0][0] > 0 and seen[0][1] > 0
    assert Path(result["paths"]["receipt"]).is_file()
    assert Path(result["paths"]["events"]).is_file()


@pytest.mark.parametrize("mode,code", [("missing_cwd", "runtime_cwd_missing"), ("wrong_output", "runtime_output_mismatch"), ("stale", "runtime_not_fresh")])
def test_runtime_requires_observed_cwd_and_matching_output(tmp_path, monkeypatch, mode, code):
    fake = _fake_codex(tmp_path)
    sessions = tmp_path / "sessions"
    monkeypatch.setenv("FIXTURE_SESSIONS", str(sessions))
    monkeypatch.setenv("FAKE_MODE", mode)
    with pytest.raises(BackendError) as raised:
        CodexBackend(fake, session_root=sessions).invoke("fixture", SCHEMA, tmp_path / "attempt", timeout=2)
    assert raised.value.code == code


def test_default_runtime_root_uses_current_codex_home(tmp_path, monkeypatch):
    from task_swarm.codex import _runtime_roots
    monkeypatch.delenv("CODEX_SESSIONS_DIR", raising=False)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    assert _runtime_roots(None) == [(tmp_path / "codex-home/sessions").resolve()]


def test_conflicting_or_non_uuid_stdout_is_refused():
    from task_swarm.codex import _event_identity
    with pytest.raises(BackendError, match="stdout_identity_invalid"):
        _event_identity([{"thread_id":"not-a-uuid"}])
    with pytest.raises(BackendError, match="stdout_identity_ambiguous"):
        _event_identity([{"thread_id":THREAD}, {"thread_id":"33333333-3333-4333-8333-333333333333"}])


def test_backend_rejects_runtime_policy_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake_codex(tmp_path)
    sessions = tmp_path / "sessions"
    monkeypatch.setenv("FIXTURE_SESSIONS", str(sessions))
    with pytest.raises(BackendError) as raised:
        CodexBackend(fake, session_root=sessions).invoke(
            "fixture prompt",
            SCHEMA,
            tmp_path / "attempts",
            timeout=2,
            effort="medium",
        )
    assert raised.value.code == "policy_invalid"


def test_backend_timeout_writes_owned_process_record_and_stops_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake_codex(tmp_path)
    sessions = tmp_path / "sessions"
    monkeypatch.setenv("FIXTURE_SESSIONS", str(sessions))
    monkeypatch.setenv("FAKE_MODE", "timeout")
    with pytest.raises(BackendError) as raised:
        CodexBackend(fake, session_root=sessions).invoke(
            "fixture prompt",
            SCHEMA,
            tmp_path / "attempts",
            timeout=0.1,
        )
    assert raised.value.code == "timeout"
    process_path = Path(raised.value.paths["process"])
    assert process_path.is_file()


def test_peer_command_contains_exact_tools_and_write_opt_in(tmp_path: Path) -> None:
    base = ["codex.exe"]
    readonly = _build_command(
        base,
        schema_path=tmp_path / "schema.json",
        last_message_path=tmp_path / "last.json",
        peer_config={"command": "python", "args": ["mcp_server.py"]},
        authorize_peer_writes=False,
    )
    enabled = _build_command(
        base,
        schema_path=tmp_path / "schema.json",
        last_message_path=tmp_path / "last.json",
        peer_config={"command": "python", "args": ["mcp_server.py"]},
        authorize_peer_writes=True,
    )
    assert "mcp_servers.task_swarm.enabled_tools=[\"peer_list\", \"peer_send\", \"peer_receive\", \"peer_ack\", \"peer_reply\", \"peer_status\"]" in readonly
    assert not any("tools.peer_send.approval_mode" in item for item in readonly)
    assert any("tools.peer_send.approval_mode" in item for item in enabled)
    assert "--dangerously-bypass-approvals-and-sandbox" not in enabled


@pytest.fixture
def peer_startup(tmp_path, monkeypatch):
    monkeypatch.delenv("TASK_SWARM_PYTHON", raising=False)
    monkeypatch.setattr(codex, "__file__", str(tmp_path / "repo/runtime/task_swarm/codex.py"))
    owner = SimpleNamespace(
        task_id="task-1",
        read_binding=lambda task, actor: {"epoch": 1, "invocation_ref": "invocation-a"},
        storage=lambda: {},
    )
    monkeypatch.setattr(codex, "OwnerFile", lambda binding: owner)
    return {"binding": str(tmp_path / "owner.json"), "actor": "actor-a", "epoch": 1, "invocation": "invocation-a"}


@pytest.mark.parametrize("selection", ["default", "environment"])
def test_peer_python_preserves_venv_and_its_installed_packages(tmp_path, monkeypatch, peer_startup, selection):
    environment = tmp_path / "peer-venv"
    venv.EnvBuilder(with_pip=False, symlinks=os.name != "nt").create(environment)
    executable = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if os.name != "nt":
        assert executable.is_symlink(), "POSIX regression must exercise a symlinked venv interpreter"
    child_env = {key: value for key, value in os.environ.items() if key not in {"PYTHONHOME", "PYTHONPATH"}}
    site = subprocess.run(
        [str(executable), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        check=True, capture_output=True, text=True, timeout=30, env=child_env,
    ).stdout.strip()
    Path(site, "peer_fixture_dependency.py").write_text("MARKER = 'venv-only'\n", encoding="utf-8")
    alias = tmp_path / "venv-alias"
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(environment), str(alias))
    else:
        alias.symlink_to(environment, target_is_directory=True)
    selected = alias / executable.relative_to(environment)
    if selection == "environment":
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("TASK_SWARM_PYTHON", str(selected.relative_to(tmp_path)))
    else:
        monkeypatch.setattr(codex.sys, "executable", str(selected))
    config = codex._peer_config(peer_startup, authorize_peer_writes=False)
    assert config["command"] == str(selected.absolute())
    child = subprocess.run(
        [config["command"], "-c", "import peer_fixture_dependency as p; print(p.MARKER)"],
        check=True, capture_output=True, text=True, timeout=30, env=child_env,
    )
    assert child.stdout.strip() == "venv-only"


def test_peer_python_selection_keeps_existing_precedence(tmp_path, monkeypatch, peer_startup):
    candidate = tmp_path / "repo/venv-peer" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"fixture")
    candidate.chmod(0o755)
    assert codex._peer_config(peer_startup, authorize_peer_writes=False)["command"] == str(candidate)
    monkeypatch.setenv("TASK_SWARM_PYTHON", sys.executable)
    assert codex._peer_config(peer_startup, authorize_peer_writes=False)["command"] == str(Path(sys.executable).absolute())


def test_peer_python_requires_os_execute_permission(monkeypatch, peer_startup):
    monkeypatch.setattr(codex.os, "access", lambda path, mode: False)
    with pytest.raises(BackendError) as raised:
        codex._peer_config(peer_startup, authorize_peer_writes=False)
    assert raised.value.code == "peer_python_invalid"
    assert raised.value.retryable is False


@pytest.mark.parametrize("selection", ["default", "environment"])
@pytest.mark.parametrize("kind", ["missing", "directory"])
def test_invalid_peer_python_is_refused_before_codex_start(tmp_path, monkeypatch, peer_startup, selection, kind):
    selected = tmp_path / "invalid-python"
    if kind == "directory":
        selected.mkdir()
    if selection == "environment":
        monkeypatch.setenv("TASK_SWARM_PYTHON", str(selected))
    else:
        monkeypatch.setattr(codex.sys, "executable", str(selected))

    def unexpected_start(*args, **kwargs):
        pytest.fail("invalid peer interpreter must be rejected before starting Codex")

    monkeypatch.setattr(codex.subprocess, "Popen", unexpected_start)
    with pytest.raises(BackendError) as raised:
        CodexBackend("unused-codex").invoke("fixture", SCHEMA, tmp_path / "attempts", peer=peer_startup)
    assert raised.value.code == "peer_python_invalid"
    assert raised.value.retryable is False


FREE_SCHEMA = {
    "type": "object",
    "required": ["job", "answer"],
    "properties": {"job": {"type": "string"}, "answer": {"type": "string"}},
    "additionalProperties": False,
}


@pytest.mark.parametrize("answer", ["rotated the token handling", "no secret leaked in logs", "password policy reviewed"])
def test_honest_results_that_mention_secret_words_are_not_corrupted(tmp_path, monkeypatch, answer):
    fake = _fake_codex(tmp_path)
    sessions = tmp_path / "sessions"
    monkeypatch.setenv("FIXTURE_SESSIONS", str(sessions))
    monkeypatch.setenv("FAKE_ANSWER", answer)
    result = CodexBackend(fake, session_root=sessions).invoke("fixture", FREE_SCHEMA, tmp_path / "attempt", timeout=5)
    assert result["result"]["job"] == "fixture"
    assert result["receipt"]["completed_output_matches"] is True


def test_redaction_is_idempotent_and_keeps_json_valid():
    import json
    from task_swarm.codex import _safe_text
    once = _safe_text('{"token":"abc123","note":"token handling"}')
    assert _safe_text(once) == once
    assert json.loads(once)["token"] == "[REDACTED]"


def test_unbounded_child_output_is_stopped_at_the_limit(tmp_path, monkeypatch):
    import task_swarm.codex as codex
    fake = _fake_codex(tmp_path)
    sessions = tmp_path / "sessions"
    monkeypatch.setenv("FIXTURE_SESSIONS", str(sessions))
    monkeypatch.setenv("FAKE_MODE", "flood")
    monkeypatch.setenv("FAKE_FLOOD_CHUNKS", "64")  # 4 MiB against a 1 MiB cap
    monkeypatch.setattr(codex, "MAX_STDOUT_BYTES", 1024 * 1024)
    with pytest.raises(BackendError) as raised:
        CodexBackend(fake, session_root=sessions).invoke("fixture", FREE_SCHEMA, tmp_path / "attempt", timeout=30)
    assert raised.value.code == "output_limit"
    assert not list((tmp_path / "attempt").rglob(".stdout.raw")), "raw unredacted spool must be removed"
