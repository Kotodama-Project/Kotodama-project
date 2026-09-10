from __future__ import annotations

import json
from pathlib import Path
import sys
import textwrap

import pytest


RUNTIME = Path(__file__).resolve().parents[1] / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from task_swarm.codex import BackendError, CodexBackend, _build_command


THREAD = "11111111-1111-4111-8111-111111111111"
TURN = "22222222-2222-4222-8222-222222222222"
SCHEMA = {
    "type": "object",
    "required": ["job", "answer"],
    "properties": {"job": {"type": "string"}, "answer": {"type": "string", "enum": ["ok"]}},
    "additionalProperties": False,
}


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
            output.write_text(json.dumps({"job": "fixture", "answer": "ok"}), encoding="utf-8")
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
              {"type":"event_msg","payload":{"type":"task_complete","turn_id":turn,"completed_at":1,"last_agent_message":json.dumps({"job":"fixture","answer":"ok"})}},
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
