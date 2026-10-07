"""Synthetic owner projection and backend, never a real Discord/provider run."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import subprocess
import os
import threading
import time

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest job")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from task_swarm.protocol import SwarmError, digest
from task_swarm.task_backend import SyntheticTaskBackend
from task_swarm.task_contract import WORK_JOBS
from task_swarm.task_runner import execute_task


def setup(tmp_path):
    root = tmp_path / "operations"
    root.mkdir()
    source = "合成資料。値は42であり、今後の予測は不明。"
    payload = {"version": 1, "task_id": "task-00000000-0000-4000-8000-000000000001", "revision": 1,
               "request": "値と不明事項を示す", "acceptance": ["出典を示す"], "sources": [
                   {"key": "a"*64, "revision": 4, "text": source, "sha256": hashlib.sha256(source.encode()).hexdigest()}]}
    file = tmp_path / "input.json"
    file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    binding = {"task_id": payload["task_id"], "revision": 1, "context_digest": digest(payload),
               "owner_ref": "ref/owner/fixture", "active_home": str(root),
               "authority_ref": "ref/authority/fixture", "capability_ref": "ref/capability/swarm_research",
               "expires_at": time.time()+1200, "status": "active"}
    document = {"binding": binding, "actors": {
        actor: {"epoch": 1, "invocation_ref": "fixture-"+actor, "actor_status": "active",
                "capability_ref": binding["capability_ref"], "peers": []}
        for actor in (*["worker-"+job for job in WORK_JOBS], "verifier")},
        "allowed_actions": [], "source_checks": [{"path":str(file), "sha256":hashlib.sha256(file.read_bytes()).hexdigest()}],
        "storage":{"root":str(root), "mailbox":str(root/"mailbox.sqlite"), "payloads":str(root/"payloads")}}
    owner = tmp_path / "owner.json"
    owner.write_text(json.dumps(document), encoding="utf-8")
    return owner, file, document, root


def test_existing_owner_task_reaches_four_jobs_readback_and_idempotent_result(tmp_path):
    owner, file, document, root = setup(tmp_path)
    before = owner.read_bytes()
    class Backend(SyntheticTaskBackend):
        calls = []
        def produce(self, job, *args, **kwargs):
            self.calls.append(job)
            return super().produce(job, *args, **kwargs)
        def review(self, *args, **kwargs):
            self.calls.append("review")
            return super().review(*args, **kwargs)
    backend = Backend()
    result = execute_task(owner, file, backend)
    assert result["result"]["state"] == "needs_review"
    assert result["result"]["synthetic"] is True and result["result"]["model_runtime_verified"] is False
    assert result["receipt"]["task_state_changed"] is False
    assert result["receipt"]["owner_input_sha256"] == hashlib.sha256(before).hexdigest()
    assert set(backend.calls) == {*WORK_JOBS, "review"}
    assert owner.read_bytes() == before
    repeated = execute_task(owner, file, backend)
    assert repeated["duplicate"] and repeated["receipt"] == result["receipt"]
    assert len(backend.calls) == 4
    assert len(list(root.glob("task-run-*"))) == 1


def test_blocked_review_is_not_owner_acceptance(tmp_path):
    owner, file, _, _ = setup(tmp_path)
    class Backend(SyntheticTaskBackend):
        def review(self, *args, **kwargs):
            value = super().review(*args, **kwargs)
            value["result"]["validations"][0].update(status="blocked", evidence=[], gap_reason="合成の不足")
            return value
    result = execute_task(owner, file, Backend())
    assert result["result"]["state"] == "failed"
    assert result["receipt"]["accepted"] is False
    assert result["result"]["independent_review"] is False


def test_current_owner_revocation_stops_before_any_report_or_completion(tmp_path):
    owner, file, document, root = setup(tmp_path)
    class Backend(SyntheticTaskBackend):
        lock = threading.Lock()
        def produce(self, job, *args, **kwargs):
            with self.lock:
                document["binding"]["status"] = "cancelled"
                owner.write_text(json.dumps(document), encoding="utf-8")
            return super().produce(job, *args, **kwargs)
    with pytest.raises(SwarmError):
        execute_task(owner, file, Backend())
    assert not list(root.glob("task-run-*/receipt.json"))


def test_precancelled_or_wrong_task_input_never_starts_backend(tmp_path):
    owner, file, document, root = setup(tmp_path)
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(SwarmError) as raised:
        execute_task(owner, file, SyntheticTaskBackend(), cancel_event=cancelled)
    assert raised.value.code == "RUN_CANCELLED" and not list(root.iterdir())
    document["binding"]["revision"] = 2
    owner.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(SwarmError) as raised:
        execute_task(owner, file, SyntheticTaskBackend())
    assert raised.value.code == "STALE_BINDING"


def test_tampered_or_incomplete_result_never_launches_another_run(tmp_path):
    owner, file, _, root = setup(tmp_path)
    result = execute_task(owner, file, SyntheticTaskBackend())
    target = root/result["receipt"]["run_id"]/"result.json"
    changed = json.loads(target.read_text(encoding="utf-8"))
    changed["state"] = "accepted"
    target.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(SwarmError) as raised:
        execute_task(owner, file, SyntheticTaskBackend())
    assert raised.value.code == "RUN_ARTIFACT_CHANGED"


@pytest.mark.parametrize("mode,code", [("stale", "REVIEW_STALE"), ("identity", "REVIEW_NOT_INDEPENDENT"),
                                     ("revoked", "INACTIVE_TASK"), ("bytes", "RUN_ARTIFACT_CHANGED"),
                                     ("actor", "STALE_ACTOR"), ("requirements", "REVIEW_CONTEXT_MISMATCH")])
def test_review_cannot_accept_changed_reports_owner_or_its_own_producer(tmp_path, mode, code):
    owner, file, document, root = setup(tmp_path)
    class Backend(SyntheticTaskBackend):
        def review(self, payload, reports, directory, **kwargs):
            value = super().review(payload, reports, directory, **kwargs)
            if mode == "stale":
                value["result"]["report_digests"]["facts"] = "0"*64
            elif mode == "requirements":
                value["result"]["context_digest"] = digest({**payload, "request": "other-requirement"})
            elif mode == "identity":
                value["receipt"]["invocation_ref"] = "fixture-facts"
            elif mode == "revoked":
                document["binding"]["status"] = "cancelled"
                owner.write_text(json.dumps(document), encoding="utf-8")
            elif mode == "actor":
                document["actors"]["verifier"]["epoch"] += 1
                owner.write_text(json.dumps(document), encoding="utf-8")
            else:
                target = directory.parent.parent / "facts.json"
                target.write_bytes(target.read_bytes()+b" ")
            return value
    with pytest.raises(SwarmError) as raised:
        execute_task(owner, file, Backend())
    assert raised.value.code == code
    assert not list(root.glob("task-run-*/receipt.json"))
    # An interrupted attempt cannot be turned into another dispatch by retry.
    if mode not in ("revoked", "actor"):
        with pytest.raises(SwarmError) as retry:
            execute_task(owner, file, SyntheticTaskBackend())
        assert retry.value.code == "RUN_RECOVERY_REQUIRED"


def test_cancelled_backend_observes_parent_event_and_never_saves_completion(tmp_path):
    owner, file, _, root = setup(tmp_path)
    event = threading.Event()
    class Backend(SyntheticTaskBackend):
        def produce(self, job, *args, cancel_event, **kwargs):
            if job == "facts":
                event.set()
            assert cancel_event.wait(2)
            raise SwarmError("RUN_CANCELLED", "synthetic owner stop")
    with pytest.raises(SwarmError):
        execute_task(owner, file, Backend(), cancel_event=event)
    assert not list(root.glob("task-run-*/receipt.json"))


def command(owner, file):
    cli = Path(__file__).resolve().parents[1] / "tools/task_swarm.py"
    return [sys.executable, str(cli), "task-run", "--owner", str(owner), "--input", str(file),
            "--backend", "synthetic", "--allow-local-fixture"]


@pytest.mark.skipif(os.name != "posix", reason="Task process lifecycle is POSIX-only")
def test_actual_task_cli_keeps_parent_pipe_until_complete_and_returns_no_payload(tmp_path):
    owner, file, _, _ = setup(tmp_path)
    child = subprocess.Popen(command(owner, file), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        child.wait(timeout=15)
        output, error = child.communicate(timeout=3)
        assert child.returncode == 0, error
        status = json.loads(output)
        assert status["status"] == "needs_review" and status["synthetic"] is True
        assert status["task_state_changed"] is False
        assert str(tmp_path).encode() not in output and "合成資料".encode() not in output
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


@pytest.mark.skipif(os.name == "posix", reason="non-POSIX Task entrypoint refusal")
def test_actual_cli_refuses_windows_before_any_execution_state(tmp_path):
    owner, file, _, root = setup(tmp_path)
    result = subprocess.run(command(owner, file), input=b"", capture_output=True, timeout=15)
    assert result.returncode == 2
    assert json.loads(result.stderr)["error"] == "POSIX_REQUIRED"
    assert not list(root.iterdir())


def test_cli_requires_separate_fixture_or_codex_invocation_authorization(tmp_path):
    owner, file, _, root = setup(tmp_path)
    result = subprocess.run(command(owner, file)[:-1], input=b"", capture_output=True, timeout=15)
    assert result.returncode == 2
    assert json.loads(result.stderr)["error"] == "LOCAL_FIXTURE_REQUIRED"
    assert not list(root.iterdir())
