"""Opt-in stdin submission proofs; fake rollouts never prove model consumption."""
from __future__ import annotations

import errno
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import threading

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest environment")

RUNTIME = Path(__file__).resolve().parents[1] / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import task_swarm.codex as codex
import task_swarm.task_runner as runner
from task_swarm.codex import BackendError, CodexBackend
from task_swarm.protocol import SwarmError

LIMIT = 256 * 1024
SEVEN = {"schema", "command", "process", "events", "stderr", "last_message", "result"}
SCHEMA = {"type": "object", "properties": {"answer": {"type": "string", "enum": ["ok"]}},
          "required": ["answer"], "additionalProperties": False}


def executable(tmp_path, monkeypatch, *, closed=False):
    """A real local executable writes its own protocol output and rollout."""
    script = tmp_path / "input-fixture.py"
    script.write_bytes(textwrap.dedent(r'''
        import json, os, pathlib, sys, uuid
        from datetime import datetime, timezone
        args = sys.argv[1:]
        pathlib.Path.cwd().joinpath("work").mkdir()
        output = pathlib.Path(args[args.index("--output-last-message") + 1])
        if os.environ.get("CLOSED_INPUT") == "yes":
            sys.stdin.close()
        else:
            pathlib.Path.cwd().joinpath("child-input.bin").write_bytes(sys.stdin.buffer.read())
        result = {"answer": "ok"}
        output.write_bytes(json.dumps(result).encode("utf-8"))
        thread, turn = str(uuid.uuid4()), str(uuid.uuid4())
        print(json.dumps({"type": "thread.started", "thread_id": thread}))
        print(json.dumps({"type": "turn.started", "turn_id": turn}))
        print(json.dumps({"type": "turn.completed", "turn_id": turn}))
        root = pathlib.Path(os.environ["INPUT_FIXTURE_SESSIONS"])
        root.mkdir(parents=True, exist_ok=True)
        rows = [
          {"type": "session_meta", "payload": {"id": thread, "session_id": thread,
              "cwd": str(pathlib.Path.cwd()), "timestamp": datetime.now(timezone.utc).isoformat()}},
          {"type": "turn_context", "payload": {"turn_id": turn, "model": "gpt-5.6-luna",
              "effort": "max", "approval_policy": "never", "sandbox_policy": {"type": "read-only"}}},
          {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": turn,
              "completed_at": 1, "last_agent_message": json.dumps(result)}}]
        (root / ("rollout-" + thread + ".jsonl")).write_bytes(
            ("\n".join(json.dumps(row) for row in rows) + "\n").encode("utf-8"))
    ''').encode("utf-8"))
    sessions = tmp_path / "sessions"
    monkeypatch.setenv("INPUT_FIXTURE_SESSIONS", str(sessions))
    monkeypatch.setenv("CLOSED_INPUT", "yes" if closed else "no")
    return CodexBackend(script, session_root=sessions)


def pipe_proxy(monkeypatch, *, wait_for_exit=False, short=False, stage=None, error=None):
    """Forward the actual pipe; synchronization changes no child output."""
    original = codex.subprocess.Popen
    failures, processes = [], []

    def spawn(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        stream = process.stdin

        class Pipe:
            def write(self, raw):
                if wait_for_exit:
                    process.wait(timeout=5)
                try:
                    if stage == "write":
                        raise error
                    if short:
                        return stream.write(raw[:-1])
                    if stage in {"bool", "none"}:
                        stream.write(raw)
                        return True if stage == "bool" else None
                    return stream.write(raw)
                except (OSError, ValueError) as exc:
                    failures.append(exc)
                    raise

            def flush(self):
                if stage == "flush":
                    raise error
                return stream.flush()

            def close(self):
                stream.close()
                if stage == "close":
                    raise error

        process.stdin = Pipe()
        return process

    monkeypatch.setattr(codex.subprocess, "Popen", spawn)
    return failures, processes


def invoke(backend, tmp_path, prompt="original\r\n日本語\0end", **options):
    return backend.invoke(prompt, SCHEMA, tmp_path / "attempts", timeout=8, **options)


def assert_closed_pipe_failure(error):
    # CPython's subprocess._stdin_write documents Windows EINVAL when the
    # child exits or closes stdin (bpo-19612 / bpo-30418).
    assert isinstance(error, BrokenPipeError) or (
        sys.platform == "win32" and type(error) is OSError and error.errno == errno.EINVAL
    ), repr(error)


def check_input(value, expected):
    paths = {key: Path(path) for key, path in value["paths"].items()}
    return runner._verify_recorded_input(value["receipt"], paths, expected)


def structural_native_evidence(value):
    """Unit metadata only: no real preflight, permission or model assertion."""
    from task_swarm.confidential import runtime_paths
    attempt = Path(value["paths"]["attempt_dir"])
    work = attempt / "work"
    command = json.loads(Path(value["paths"]["command"]).read_bytes())
    allowed = {**runtime_paths(command["argv"][0]), str(work): "read"}
    profile = {"type": "managed", "network": "restricted", "file_system": {
        "type": "restricted", "entries": [
            {"path": {"type": "special", "value": {"kind": "root"}}, "access": "deny"},
            *[{"path": {"type": "path", "path": path}, "access": access} for path, access in allowed.items()]]}}
    rollout = Path(value["receipt"]["runtime_receipt_path"])
    rows = [json.loads(line) for line in rollout.read_bytes().splitlines()]
    rows[0]["payload"]["cwd"] = str(work)
    rows[1]["payload"].update(permission_profile=profile, active_permission_profile={"id": "task-input"})
    rollout.write_bytes(("\n".join(json.dumps(row) for row in rows) + "\n").encode("utf-8"))
    value["receipt"].update(runtime_cwd=str(work), permission_probe={
        "kind": "task_synthetic_permission_probe_v1", "outer_read_denied": True,
        "inner_metadata_read_denied": True, "model_called": False},
        permission_profile_sha256=hashlib.sha256(codex._json_dump(profile).encode("utf-8")).hexdigest())
    codex._write_json(Path(value["paths"]["receipt"]), value["receipt"])
    return value


def test_default_closed_pipe_retains_seven_artifacts(tmp_path, monkeypatch):
    backend = executable(tmp_path, monkeypatch, closed=True)
    failures, processes = pipe_proxy(monkeypatch, wait_for_exit=True)
    value = invoke(backend, tmp_path, "x" * LIMIT)
    assert len(failures) == 1
    assert_closed_pipe_failure(failures[0])
    assert processes[0].poll() == 0
    assert value["result"] == {"answer": "ok"}
    assert set(value["receipt"]["artifact_digests"]) == SEVEN
    assert "input" not in value["paths"] and "stdin_submission" not in value["receipt"]


def test_opt_in_real_broken_pipe_cannot_publish_success(tmp_path, monkeypatch):
    backend = executable(tmp_path, monkeypatch, closed=True)
    failures, processes = pipe_proxy(monkeypatch, wait_for_exit=True)
    with pytest.raises(BackendError) as caught:
        invoke(backend, tmp_path, "x" * LIMIT, record_input=True)
    assert caught.value.code == "stdin_write_failed" and not caught.value.retryable
    assert len(failures) == 1 and caught.value.__cause__ is failures[0]
    assert processes[0].poll() == 0
    assert not Path(caught.value.paths["receipt"]).exists()
    assert Path(caught.value.paths["input"]).read_bytes() == b"x" * LIMIT


@pytest.mark.parametrize("prompt", ["", "original\r\n日本語\0end", "x" * LIMIT], ids=["empty", "unicode", "cap"])
def test_recorded_bytes_match_the_real_child_without_consumption_claim(tmp_path, monkeypatch, prompt):
    backend = executable(tmp_path, monkeypatch)
    value = invoke(backend, tmp_path, prompt, record_input=True)
    raw = prompt.encode("utf-8")
    assert Path(value["paths"]["input"]).read_bytes() == raw
    assert Path(value["paths"]["attempt_dir"], "child-input.bin").read_bytes() == raw
    assert value["receipt"]["stdin_submission"] == {
        "version": 1, "encoding": "utf-8", "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(), "writer_status": "pipe_write_completed"}
    assert set(value["receipt"]["artifact_digests"]) == SEVEN | {"input"}
    assert check_input(value, raw) is None
    assert "consumed" not in json.dumps(value["receipt"])
    assert "model_verified" not in json.dumps(value["receipt"])
    assert value["receipt"]["permission_probe"] is None


@pytest.mark.parametrize("invalid", [None, 1, "yes"])
def test_record_flag_and_cap_are_checked_before_any_child(tmp_path, monkeypatch, invalid):
    monkeypatch.setattr(codex.subprocess, "Popen", lambda *a, **kw: pytest.fail("must not launch"))
    with pytest.raises(BackendError) as caught:
        CodexBackend("not-used").invoke("x", SCHEMA, tmp_path / "attempts", record_input=invalid)
    assert caught.value.code == "stdin_record_invalid" and not (tmp_path / "attempts").exists()
    with pytest.raises(BackendError) as caught:
        CodexBackend("not-used").invoke("x" * (LIMIT + 1), SCHEMA, tmp_path / "attempts", record_input=True)
    assert caught.value.code == "prompt_input_limit" and not (tmp_path / "attempts").exists()


@pytest.mark.parametrize("stage", ["write", "flush", "close", "short", "bool", "none"])
def test_write_failures_preserve_cause_and_owned_cleanup(tmp_path, monkeypatch, stage):
    backend = executable(tmp_path, monkeypatch)
    error = OSError("private fixture writer failure")
    _, processes = pipe_proxy(monkeypatch, short=stage == "short", stage=stage, error=error)
    with pytest.raises(BackendError) as caught:
        invoke(backend, tmp_path, record_input=True)
    assert caught.value.code == "stdin_write_failed" and not caught.value.retryable
    if stage in {"write", "flush", "close"}:
        assert caught.value.__cause__ is error
    assert processes[0].poll() is not None
    assert not Path(caught.value.paths["receipt"]).exists()


def test_input_change_after_process_start_is_not_a_new_success_digest(tmp_path, monkeypatch):
    backend = executable(tmp_path, monkeypatch)
    original = codex.subprocess.Popen
    changed = []

    def spawn(*args, **kwargs):
        process = original(*args, **kwargs)
        path = Path(kwargs["cwd"]) / "input.txt"
        raw = path.read_bytes()
        path.write_bytes(b"z" * len(raw))
        changed.append(hashlib.sha256(path.read_bytes()).hexdigest())
        return process

    monkeypatch.setattr(codex.subprocess, "Popen", spawn)
    with pytest.raises(BackendError) as caught:
        invoke(backend, tmp_path, record_input=True)
    assert caught.value.code == "stdin_record_changed"
    assert not Path(caught.value.paths["receipt"]).exists()
    diagnostics = json.loads(Path(caught.value.paths["diagnostics"]).read_bytes())
    assert diagnostics["artifact_digests"]["input"] == changed[0]


@pytest.mark.parametrize("mutation", ["missing", "body", "sha", "length", "status", "version_bool", "length_bool"])
def test_saved_input_is_strictly_reopened(tmp_path, monkeypatch, mutation):
    value = invoke(executable(tmp_path, monkeypatch), tmp_path, "raw", record_input=True)
    marker = value["receipt"]["stdin_submission"]
    if mutation == "missing":
        Path(value["paths"]["input"]).unlink()
    elif mutation == "body":
        Path(value["paths"]["input"]).write_bytes(b"new")
    else:
        key, replacement = {"sha": ("sha256", "0" * 64), "length": ("bytes", 2),
            "status": ("writer_status", "consumed"), "version_bool": ("version", True),
            "length_bool": ("bytes", True)}[mutation]
        marker[key] = replacement
    with pytest.raises((SwarmError, OSError)):
        check_input(value, b"raw")


@pytest.mark.parametrize("invalid", ["raw", bytearray(b"raw"), b"x" * (LIMIT + 1), b"\xff"],
                         ids=["text", "mutable", "cap_plus_one", "invalid_utf8"])
def test_expected_input_type_and_limit_are_validated_first(tmp_path, invalid):
    with pytest.raises(SwarmError) as caught:
        runner.verify_runtime({}, tmp_path, expected_input=invalid)
    assert caught.value.code == "RUN_RUNTIME_INPUT_INVALID"


def test_technical_fixture_does_not_gain_a_native_permission_proof(tmp_path, monkeypatch):
    value = invoke(executable(tmp_path, monkeypatch), tmp_path, "raw", record_input=True)
    with pytest.raises(SwarmError) as caught:
        runner.verify_runtime(value, tmp_path / "attempts", freeze=True, expected_input=b"raw")
    assert caught.value.code == "RUN_RUNTIME_POLICY_MISSING"
    assert "runtime_receipt_sha256" not in value


def test_default_reader_does_not_automatically_admit_eight_artifacts(tmp_path, monkeypatch):
    value = invoke(executable(tmp_path, monkeypatch), tmp_path, "raw", record_input=True)
    with pytest.raises(SwarmError) as caught:
        runner.verify_runtime(value, tmp_path / "attempts", freeze=True)
    assert caught.value.code == "RUN_RUNTIME_PATH_CHANGED"


@pytest.mark.skipif(os.name != "posix", reason="the existing native permission reader requires POSIX/ELF")
@pytest.mark.parametrize("record", [False, True])
def test_full_native_reader_keeps_legacy_and_opt_in_proofs_separate(tmp_path, monkeypatch, record):
    value = invoke(executable(tmp_path, monkeypatch), tmp_path, "raw", record_input=record)
    value = structural_native_evidence(value)
    options = {"expected_input": b"raw"} if record else {}
    runner.verify_runtime(value, tmp_path / "attempts", freeze=True, **options)
    runner.verify_runtime(value, tmp_path / "attempts", **options)
    assert set(value["receipt"]["artifact_digests"]) == SEVEN | ({"input"} if record else set())
    if record:
        with pytest.raises(SwarmError):
            runner.verify_runtime(value, tmp_path / "attempts", expected_input=b"new")
    else:
        with pytest.raises(SwarmError):
            runner.verify_runtime(value, tmp_path / "attempts", expected_input=b"raw")


@pytest.mark.skipif(os.name != "posix", reason="the existing native permission reader requires POSIX/ELF")
@pytest.mark.parametrize("freeze", [True, False], ids=["freeze", "replay"])
def test_input_changed_during_profile_validation_cannot_freeze_or_replay(tmp_path, monkeypatch, freeze):
    import task_swarm.confidential as confidential
    value = structural_native_evidence(invoke(executable(tmp_path, monkeypatch), tmp_path, "raw", record_input=True))
    if not freeze:
        runner.verify_runtime(value, tmp_path / "attempts", freeze=True, expected_input=b"raw")
    original = confidential.require_observed_profile
    frozen = {key: value[key] for key in ("runtime_rollout_sha256", "runtime_receipt_sha256") if key in value}

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        Path(value["paths"]["input"]).write_bytes(b"new")
        return result

    monkeypatch.setattr(confidential, "require_observed_profile", changed)
    with pytest.raises(SwarmError) as caught:
        runner.verify_runtime(value, tmp_path / "attempts", freeze=freeze, expected_input=b"raw")
    assert caught.value.code == "RUN_RUNTIME_INPUT_CHANGED"
    assert Path(value["paths"]["input"]).read_bytes() == b"new"
    assert {key: value[key] for key in ("runtime_rollout_sha256", "runtime_receipt_sha256") if key in value} == frozen


@pytest.mark.skipif(os.name != "posix", reason="the existing native permission reader requires POSIX/ELF")
@pytest.mark.parametrize("mutation,code", [("pid", "RUN_RUNTIME_IDENTITY_CHANGED"),
    ("created_at", "RUN_RUNTIME_IDENTITY_CHANGED"), ("root", "RUN_RUNTIME_PATH_CHANGED"),
    ("profile", "CONFIDENTIAL_RUNTIME_POLICY_UNVERIFIED")])
def test_opt_in_does_not_weaken_current_process_root_or_profile_checks(tmp_path, monkeypatch, mutation, code):
    value = structural_native_evidence(invoke(executable(tmp_path, monkeypatch), tmp_path, "raw", record_input=True))
    if mutation in {"pid", "created_at"}:
        path = Path(value["paths"]["process"])
        process = json.loads(path.read_bytes())
        process[mutation] += 1
        codex._write_json(path, process)
        value["receipt"]["artifact_digests"]["process"] = hashlib.sha256(path.read_bytes()).hexdigest()
        codex._write_json(Path(value["paths"]["receipt"]), value["receipt"])
    elif mutation == "root":
        value["paths"]["attempt_dir"] = str(tmp_path / "foreign" / "attempt-elsewhere")
    else:
        path = Path(value["receipt"]["runtime_receipt_path"])
        rows = [json.loads(line) for line in path.read_bytes().splitlines()]
        rows[1]["payload"]["permission_profile"]["network"] = "enabled"
        path.write_bytes(("\n".join(json.dumps(row) for row in rows) + "\n").encode("utf-8"))
    with pytest.raises(SwarmError) as caught:
        runner.verify_runtime(value, tmp_path / "attempts", freeze=True, expected_input=b"raw")
    assert caught.value.code == code


def test_final_artifact_refresh_cannot_rebind_a_later_changed_input(tmp_path, monkeypatch):
    backend = executable(tmp_path, monkeypatch)
    original = codex._write_json

    def changed(path, data):
        original(path, data)
        if path.name == "receipt.json":
            path.with_name("input.txt").write_bytes(b"new")

    monkeypatch.setattr(codex, "_write_json", changed)
    value = invoke(backend, tmp_path, "raw", record_input=True)
    saved = json.loads(Path(value["paths"]["receipt"]).read_bytes())
    sha = hashlib.sha256(b"raw").hexdigest()
    assert saved["artifact_digests"]["input"] == saved["stdin_submission"]["sha256"] == sha
    with pytest.raises(SwarmError) as caught:
        check_input(value, b"raw")
    assert caught.value.code == "RUN_RUNTIME_INPUT_CHANGED"


def test_input_record_failure_never_launches_a_child(tmp_path, monkeypatch):
    backend = executable(tmp_path, monkeypatch)
    error = OSError("fixture disk failure")
    original = codex._atomic_write

    def failed(path, raw):
        if path.name == "input.txt":
            raise error
        original(path, raw)

    monkeypatch.setattr(codex, "_atomic_write", failed)
    monkeypatch.setattr(codex.subprocess, "Popen", lambda *a, **kw: pytest.fail("must not launch"))
    with pytest.raises(BackendError) as caught:
        invoke(backend, tmp_path, record_input=True)
    assert caught.value.code == "stdin_record_failed" and caught.value.__cause__ is error
    assert not Path(caught.value.paths["process"]).exists()
    assert not Path(caught.value.paths["receipt"]).exists()


@pytest.mark.parametrize("flow", ["success", "body_changed", "oversize", "broken_pipe"])
def test_every_input_digest_uses_only_the_bounded_descriptor_reader(tmp_path, monkeypatch, flow):
    backend = executable(tmp_path, monkeypatch, closed=flow == "broken_pipe")
    failures = []
    if flow == "broken_pipe":
        failures, _ = pipe_proxy(monkeypatch, wait_for_exit=True)
    elif flow != "success":
        spawn = codex.subprocess.Popen

        def changed(*args, **kwargs):
            process = spawn(*args, **kwargs)
            Path(kwargs["cwd"], "input.txt").write_bytes(b"new" if flow == "body_changed" else b"x" * (LIMIT + 1))
            return process

        monkeypatch.setattr(codex.subprocess, "Popen", changed)
    original_read = Path.read_bytes
    original_bounded = runner.read_bytes
    bounded = []

    def no_unbounded(path):
        if path.name == "input.txt":
            pytest.fail("recorded input must never use Path.read_bytes, including failure cleanup")
        return original_read(path)

    def read_bounded(path, maximum=2*1024*1024):
        if path.name == "input.txt":
            bounded.append(maximum)
        return original_bounded(path, maximum)

    monkeypatch.setattr(Path, "read_bytes", no_unbounded)
    monkeypatch.setattr(runner, "read_bytes", read_bounded)
    if flow == "success":
        value = invoke(backend, tmp_path, "raw", record_input=True)
        assert check_input(value, b"raw") is None
        assert value["receipt"]["artifact_digests"]["input"] == hashlib.sha256(b"raw").hexdigest()
    else:
        prompt = "x" * LIMIT if flow == "broken_pipe" else "raw"
        with pytest.raises(BackendError) as caught:
            invoke(backend, tmp_path, prompt, record_input=True)
        assert caught.value.code == {"body_changed": "stdin_record_changed", "oversize": "stdin_record_failed",
                                     "broken_pipe": "stdin_write_failed"}[flow]
        if flow == "broken_pipe":
            assert len(failures) == 1 and caught.value.__cause__ is failures[0]
            assert_closed_pipe_failure(failures[0])
        assert not Path(caught.value.paths["receipt"]).exists()
    assert bounded and set(bounded) == {LIMIT}


@pytest.mark.parametrize("flow", ["hash_only", "broken_pipe", "cancel"])
def test_missing_bounded_input_digest_refuses_success_and_preserves_original_failure(tmp_path, monkeypatch, flow):
    backend = executable(tmp_path, monkeypatch, closed=flow != "hash_only")
    failures = []
    if flow != "hash_only":
        failures, _ = pipe_proxy(monkeypatch, wait_for_exit=True)
    cancelled = threading.Event()
    if flow == "cancel":
        join = codex.threading.Thread.join

        def cancelling_join(thread, *args, **kwargs):
            result = join(thread, *args, **kwargs)
            if thread.name == "swarm-prompt-writer":
                cancelled.set()
            return result

        monkeypatch.setattr(codex.threading.Thread, "join", cancelling_join)
    original = codex._artifact_digests
    bounded = runner.read_bytes
    blocked = []

    def failed_input(path, maximum=2*1024*1024):
        if path.name == "input.txt":
            blocked.append(maximum)
            raise OSError("fixture input digest unavailable")
        return bounded(path, maximum)

    def incomplete(paths):
        with monkeypatch.context() as context:
            context.setattr(runner, "read_bytes", failed_input)
            return original(paths)

    monkeypatch.setattr(codex, "_artifact_digests", incomplete)
    with pytest.raises(BackendError) as caught:
        invoke(backend, tmp_path, "raw" if flow == "hash_only" else "x" * LIMIT,
               record_input=True, cancel_event=cancelled)
    assert caught.value.code == {"hash_only": "stdin_record_failed", "broken_pipe": "stdin_write_failed",
                                 "cancel": "cancelled"}[flow]
    if flow == "broken_pipe":
        assert len(failures) == 1 and caught.value.__cause__ is failures[0]
        assert_closed_pipe_failure(failures[0])
    assert blocked and set(blocked) == {LIMIT}
    assert not Path(caught.value.paths["receipt"]).exists()


def test_module_entrypoint_forwards_recording_without_changing_native_flags(tmp_path, monkeypatch):
    backend = executable(tmp_path, monkeypatch)
    value = codex.invoke("raw", SCHEMA, tmp_path / "attempts", executable=backend.executable,
                         session_root=backend.session_root, timeout=8, record_input=True)
    assert check_input(value, b"raw") is None
    assert value["receipt"]["sandbox"] == "read-only" and value["receipt"]["approval_policy"] == "never"


def test_cancel_during_writer_join_takes_priority_over_pipe_error(tmp_path, monkeypatch):
    backend = executable(tmp_path, monkeypatch, closed=True)
    pipe_proxy(monkeypatch, wait_for_exit=True)
    cancelled = threading.Event()
    original = codex.threading.Thread.join

    def join(thread, *args, **kwargs):
        result = original(thread, *args, **kwargs)
        if thread.name == "swarm-prompt-writer":
            cancelled.set()
        return result

    monkeypatch.setattr(codex.threading.Thread, "join", join)
    with pytest.raises(BackendError) as caught:
        invoke(backend, tmp_path, "x" * LIMIT, record_input=True, cancel_event=cancelled)
    assert caught.value.code == "cancelled" and not caught.value.retryable
    assert not Path(caught.value.paths["receipt"]).exists()


def test_current_actor_callback_refusal_precedes_stdin(tmp_path, monkeypatch):
    backend = executable(tmp_path, monkeypatch)
    refusal = SwarmError("STALE_ACTOR", "actor changed")

    def actor(*_args):
        raise refusal

    with pytest.raises(BackendError) as caught:
        invoke(backend, tmp_path, record_input=True, on_process=actor)
    assert caught.value.code == "process_callback" and caught.value.__cause__ is refusal
    assert not Path(caught.value.paths["receipt"]).exists()
    assert not Path(caught.value.paths["attempt_dir"], "child-input.bin").exists()
