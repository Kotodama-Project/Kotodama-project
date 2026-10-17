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
from task_swarm.task_backend import SyntheticTaskBackend, TaskBackend
from task_swarm.task_contract import WORK_JOBS
from task_swarm.task_runner import execute_task, read_json


@pytest.mark.parametrize("raw", [b"", b"{", b"\xff"])
def test_incomplete_owner_json_is_a_typed_refusal(tmp_path, raw):
    file = tmp_path/"owner.json"
    file.write_bytes(raw)
    with pytest.raises(SwarmError) as raised:
        read_json(file)
    assert raised.value.code == "RUN_JSON_INVALID"


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


def test_every_task_producer_and_verifier_requires_the_dedicated_input_scope(tmp_path):
    from types import SimpleNamespace
    _, file, _, _ = setup(tmp_path)
    payload=json.loads(file.read_text(encoding="utf-8"))
    dedicated=tmp_path/"dedicated"
    backend=TaskBackend("not-executed",task_codex_home=dedicated)
    calls=[]
    backend.codex=SimpleNamespace(invoke=lambda *args,**kwargs:calls.append(kwargs))
    options={"timeout":20,"cancel_event":threading.Event(),"on_process":lambda *args:None}
    reports={}
    fixture=SyntheticTaskBackend()
    for job in WORK_JOBS:
        backend.produce(job,payload,tmp_path/job,**options)
        reports[job]=fixture.produce(job,payload,tmp_path/job)["result"]
    backend.review(payload,reports,tmp_path/"review",**options)
    assert len(calls)==4
    assert all(call["confidential"] is True and call["task_codex_home"]==dedicated for call in calls)


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
    repeated = execute_task(owner, file, backend, expected_receipt_sha256=result["receipt_sha256"])
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


def test_replay_returns_the_exact_checked_bytes_not_a_later_unchecked_read(tmp_path, monkeypatch):
    import task_swarm.task_runner as runner
    owner, file, _, _ = setup(tmp_path)
    initial = execute_task(owner,file,SyntheticTaskBackend())
    original = runner.read_json
    changed = []
    def swap(filename,*args,**kwargs):
        result=original(filename,*args,**kwargs)
        if filename.name=="result.json" and kwargs.get("with_digest"):
            replacement=copy.deepcopy(result[0])
            replacement["state"]="tampered_after_hash"
            filename.write_text(json.dumps(replacement),encoding="utf-8")
            changed.append(True)
        return result
    monkeypatch.setattr(runner,"read_json",swap)
    repeated=execute_task(owner,file,SyntheticTaskBackend(),expected_receipt_sha256=initial["receipt_sha256"])
    assert changed and repeated["duplicate"]
    assert repeated["result"] == initial["result"]


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
        execute_task(owner, file, SyntheticTaskBackend(), expected_receipt_sha256=result["receipt_sha256"])
    assert raised.value.code == "RUN_ARTIFACT_CHANGED"


def test_replay_cannot_trust_an_artifact_and_a_rewritten_receipt_hash(tmp_path):
    owner, file, _, root = setup(tmp_path)
    original = execute_task(owner, file, SyntheticTaskBackend())
    directory = root/original["receipt"]["run_id"]
    result_path, receipt_path = directory/"result.json", directory/"receipt.json"
    result = json.loads(result_path.read_bytes())
    result["reports"]["facts"]["summary"] = "forged summary"
    raw = (json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))+"\n").encode()
    result_path.write_bytes(raw)
    receipt = json.loads(receipt_path.read_bytes())
    receipt["artifact_sha256"]["result.json"] = hashlib.sha256(raw).hexdigest()
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(SwarmError) as refused:
        execute_task(owner, file, SyntheticTaskBackend(), expected_receipt_sha256=original["receipt_sha256"])
    assert refused.value.code == "RUN_REPLAY_ANCHOR_MISMATCH"
    with pytest.raises(SwarmError) as missing:
        execute_task(owner, file, SyntheticTaskBackend())
    assert missing.value.code == "RUN_REPLAY_ANCHOR_REQUIRED"


def test_missing_replay_never_starts_a_new_run(tmp_path):
    owner, file, _, root = setup(tmp_path)
    with pytest.raises(SwarmError) as raised:
        execute_task(owner, file, SyntheticTaskBackend(), expected_receipt_sha256="a"*64)
    assert raised.value.code == "RUN_REPLAY_MISSING"
    assert not list(root.iterdir())


def test_aggregate_output_limit_is_checked_before_acceptance(tmp_path):
    import sqlite3
    from contextlib import closing
    owner, file, document, root = setup(tmp_path)
    payload = json.loads(file.read_bytes())
    source = payload["sources"][0]
    source.update(text="a"*11000, sha256=hashlib.sha256(b"a"*11000).hexdigest())
    file.write_text(json.dumps(payload), encoding="utf-8")
    document["binding"]["context_digest"] = digest(payload)
    document["source_checks"][0]["sha256"] = hashlib.sha256(file.read_bytes()).hexdigest()
    owner.write_text(json.dumps(document), encoding="utf-8")
    class Large(SyntheticTaskBackend):
        def produce(self, job, payload, directory, **kwargs):
            value = super().produce(job, payload, directory, **kwargs)
            evidence = {"source_key":source["key"],"source_revision":source["revision"],"start":0,"end":11000,"quote":source["text"]}
            value["result"]["claims"] = [{"text":"supported fixture","status":"supported","evidence":[evidence]*6} for _ in range(12)]
            return value
    with pytest.raises(SwarmError) as raised:
        execute_task(owner, file, Large())
    assert raised.value.code == "RUN_OUTPUT_LIMIT"
    database = next(root.glob("task-run-*/execution.sqlite"))
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT count(*) FROM jobs WHERE state='accepted'").fetchone()[0] == 0
    assert not list(root.glob("task-run-*/receipt.json"))


@pytest.mark.parametrize("mode,code", [("stale", "REVIEW_STALE"), ("identity", "REVIEW_NOT_INDEPENDENT"),
                                     ("revoked", "INACTIVE_TASK"), ("bytes", "RUN_ARTIFACT_CHANGED"),
                                     ("actor", "STALE_ACTOR"), ("requirements", "REVIEW_CONTEXT_MISMATCH")])
def test_review_cannot_accept_changed_reports_owner_or_its_own_producer(tmp_path, monkeypatch, mode, code):
    owner, file, document, root = setup(tmp_path)
    gate = OwnerMonitorGate(monkeypatch) if mode in ("revoked", "actor") else None
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
                gate.wait_until_entered()
                document["binding"]["status"] = "cancelled"
                owner.write_text(json.dumps(document), encoding="utf-8")
                gate.release.set()
                assert kwargs["cancel_event"].wait(10)
            elif mode == "actor":
                gate.wait_until_entered()
                document["actors"]["verifier"]["epoch"] += 1
                owner.write_text(json.dumps(document), encoding="utf-8")
                gate.release.set()
                assert kwargs["cancel_event"].wait(10)
            else:
                target = directory.parent.parent / "facts.json"
                target.write_bytes(target.read_bytes()+b" ")
            return value
    try:
        with pytest.raises(SwarmError) as raised:
            execute_task(owner, file, Backend())
        if gate is not None:
            gate.assert_stopped()
    finally:
        if gate is not None:
            gate.finish()
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


class OwnerMonitorGate:
    """Hold only the owner watcher's real read at an explicit test boundary."""

    def __init__(self, monkeypatch, *, release_on_foreground_error=False, monitor_error=None):
        import task_swarm.task_runner as runner
        self.entered = threading.Event()
        self.release = threading.Event()
        self.thread = None
        self.release_on_foreground_error = release_on_foreground_error
        self.monitor_error = monitor_error
        original_task = runner.OwnerFile.read_task
        original_binding = runner.OwnerFile.read_binding
        original_require = runner.require

        def invoke(original, instance, *args, **kwargs):
            watching = threading.current_thread().name == "swarm-owner-watch"
            try:
                return original(instance, *args, **kwargs)
            except Exception:
                if not watching and self.release_on_foreground_error:
                    self.release.set()
                raise

        def read_task(instance, *args, **kwargs):
            if threading.current_thread().name == "swarm-owner-watch":
                self.thread = threading.current_thread()
                self.entered.set()
                assert self.release.wait(10), "watcher read was not released"
                if self.monitor_error is not None:
                    raise self.monitor_error
            return invoke(original_task, instance, *args, **kwargs)

        def read_binding(instance, *args, **kwargs):
            return invoke(original_binding, instance, *args, **kwargs)

        def require(*args, **kwargs):
            try:
                return original_require(*args, **kwargs)
            except Exception:
                if self.release_on_foreground_error and threading.current_thread().name != "swarm-owner-watch":
                    self.release.set()
                raise

        monkeypatch.setattr(runner.OwnerFile, "read_task", read_task)
        monkeypatch.setattr(runner.OwnerFile, "read_binding", read_binding)
        monkeypatch.setattr(runner, "require", require)

    def wait_until_entered(self):
        assert self.entered.wait(10), "watcher did not reach the read boundary"

    def assert_stopped(self):
        assert self.thread is not None, "watcher was never observed"
        assert not self.thread.is_alive(), "execution returned before the watcher stopped"

    def finish(self):
        self.release.set()
        if self.thread is not None:
            self.thread.join(timeout=10)
            assert not self.thread.is_alive(), "watcher remained alive after execution"


def assert_no_owner_acceptance(root):
    import sqlite3
    from contextlib import closing
    assert not list(root.glob("task-run-*/receipt.json"))
    with closing(sqlite3.connect(next(root.glob("task-run-*/execution.sqlite")))) as connection:
        assert connection.execute("SELECT count(*) FROM jobs WHERE state='accepted'").fetchone()[0] == 0


@pytest.mark.parametrize("order", ["monitor", "foreground"])
@pytest.mark.parametrize("mode,code", [
    ("revoked", "INACTIVE_TASK"),
    ("actor", "STALE_ACTOR"),
    ("expired", "EXPIRED_BINDING"),
])
def test_owner_refusal_reason_is_stable_in_both_observed_orders(tmp_path, monkeypatch, order, mode, code):
    owner, file, document, root = setup(tmp_path)
    gate = OwnerMonitorGate(monkeypatch, release_on_foreground_error=order == "foreground")
    now = [time.time()]

    class Backend(SyntheticTaskBackend):
        def review(self, payload, reports, directory, **kwargs):
            value = super().review(payload, reports, directory, **kwargs)
            gate.wait_until_entered()
            if mode == "revoked":
                document["binding"]["status"] = "cancelled"
                owner.write_text(json.dumps(document), encoding="utf-8")
            elif mode == "actor":
                document["actors"]["verifier"]["epoch"] += 1
                owner.write_text(json.dumps(document), encoding="utf-8")
            else:
                now[0] = document["binding"]["expires_at"] + 1
            if order == "monitor":
                gate.release.set()
                assert kwargs["cancel_event"].wait(10)
            return value

    try:
        with pytest.raises(SwarmError) as raised:
            execute_task(owner, file, Backend(), clock=lambda: now[0])
        gate.assert_stopped()
    finally:
        gate.finish()
    assert raised.value.code == code
    assert_no_owner_acceptance(root)


@pytest.mark.parametrize("kind", [
    "swarm_cancel", "codex_cancel", "stop_unconfirmed", "timeout", "other_swarm", "lookup",
])
def test_monitor_reason_only_translates_explicit_backend_cancellation(tmp_path, monkeypatch, kind):
    from task_swarm.codex import BackendError
    owner, file, document, root = setup(tmp_path)
    gate = OwnerMonitorGate(monkeypatch)
    failures = {
        "swarm_cancel": SwarmError("RUN_CANCELLED", "synthetic cancellation"),
        "codex_cancel": BackendError("cancelled", "synthetic cancellation", retryable=False),
        "stop_unconfirmed": BackendError("stop_unconfirmed", "child stop unconfirmed", retryable=False,
                                          diagnostics={"cleanup": "unconfirmed"}),
        "timeout": BackendError("timeout", "synthetic timeout", retryable=False,
                                diagnostics={"timeout": "fixture"}),
        "other_swarm": SwarmError("RUN_OUTPUT_LIMIT", "synthetic output limit"),
        "lookup": LookupError("unrelated backend failure"),
    }
    failure = failures[kind]

    class Backend(SyntheticTaskBackend):
        def review(self, payload, reports, directory, **kwargs):
            gate.wait_until_entered()
            document["binding"]["status"] = "cancelled"
            owner.write_text(json.dumps(document), encoding="utf-8")
            gate.release.set()
            assert kwargs["cancel_event"].wait(10)
            raise failure

    try:
        with pytest.raises(Exception) as raised:
            execute_task(owner, file, Backend())
        gate.assert_stopped()
    finally:
        gate.finish()
    if kind in ("swarm_cancel", "codex_cancel"):
        assert isinstance(raised.value, SwarmError)
        assert raised.value.code == "INACTIVE_TASK"
        assert raised.value.__cause__ is failure
    else:
        assert raised.value is failure
    assert_no_owner_acceptance(root)


def test_external_cancellation_does_not_acquire_a_later_monitor_reason(tmp_path, monkeypatch):
    owner, file, document, root = setup(tmp_path)
    gate = OwnerMonitorGate(monkeypatch)
    event = threading.Event()

    class Backend(SyntheticTaskBackend):
        def review(self, payload, reports, directory, **kwargs):
            value = super().review(payload, reports, directory, **kwargs)
            gate.wait_until_entered()
            event.set()
            document["binding"]["status"] = "cancelled"
            owner.write_text(json.dumps(document), encoding="utf-8")
            gate.finish()
            return value

    try:
        with pytest.raises(SwarmError) as raised:
            execute_task(owner, file, Backend(), cancel_event=event)
        gate.assert_stopped()
    finally:
        gate.finish()
    assert raised.value.code == "RUN_CANCELLED"
    assert_no_owner_acceptance(root)


def test_untyped_monitor_failure_is_a_bounded_binding_refusal(tmp_path, monkeypatch):
    owner, file, _, root = setup(tmp_path)
    gate = OwnerMonitorGate(monkeypatch, monitor_error=OSError("private fixture diagnostic"))

    class Backend(SyntheticTaskBackend):
        def review(self, payload, reports, directory, **kwargs):
            value = super().review(payload, reports, directory, **kwargs)
            gate.wait_until_entered()
            gate.release.set()
            assert kwargs["cancel_event"].wait(10)
            return value

    try:
        with pytest.raises(SwarmError) as raised:
            execute_task(owner, file, Backend())
        gate.assert_stopped()
    finally:
        gate.finish()
    assert raised.value.code == "BINDING_UNAVAILABLE"
    assert raised.value.detail == "Task owner binding could not be validated"
    assert_no_owner_acceptance(root)
