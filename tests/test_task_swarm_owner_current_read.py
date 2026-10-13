"""Invocation-local owner reads retain lazy refusals and callback fences."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest environment")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from task_swarm import owner_file, loop_executor_runtime
from task_swarm.owner_file import OwnerFile, _current_read
from task_swarm.protocol import SwarmError, canonical, digest
from task_swarm.task_contract import require


@pytest.fixture
def case(tmp_path):
    source = tmp_path / "source.txt"
    source.write_bytes(b"current source\n")
    root = tmp_path / "operations"
    root.mkdir()
    task = {"task_id": "task-1", "revision": 1, "context_digest": "a" * 64,
            "owner_ref": "owner-1", "active_home": str(root), "authority_ref": "authority-1",
            "capability_ref": "capability-1", "expires_at": time.time() + 3600, "status": "active"}
    document = {"binding": task, "actors": {
        name: {"epoch": 1, "invocation_ref": "invocation-" + name, "actor_status": "active",
               "capability_ref": task["capability_ref"], "peers": []}
        for name in ("worker-a", "worker-b", "verifier")}, "allowed_actions": [],
        "source_checks": [{"path": source.name, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}],
        "storage": {"root": str(root), "mailbox": "mailbox.sqlite", "payloads": "payloads"}}
    path = tmp_path / "owner.json"
    path.write_text(canonical(document), encoding="utf-8")
    return SimpleNamespace(path=path, source=source, root=root, document=document, owner=OwnerFile(path))


def write_owner(case):
    case.path.write_text(canonical(case.document), encoding="utf-8")


def bindings(owner):
    task = owner.read_task("task-1")
    actors = {name: owner.read_binding("task-1", name) for name in ("worker-a", "worker-b", "verifier")}
    return task, actors, owner.storage()


def compare(reader, task, actors):
    require(digest(reader.read_task("task-1")) == digest(task), "STALE_BINDING")
    require(all(reader.read_binding("task-1", name) == expected for name, expected in actors.items()),
            "STALE_ACTOR")


@contextmanager
def snapshots():
    calls, previous = [], sys.getprofile()
    code = OwnerFile._snapshot.__code__
    def observe(frame, event, _arg):
        if event == "call" and frame.f_code is code:
            calls.append(frame.f_locals["self"])
    sys.setprofile(observe)
    try:
        yield calls
    finally:
        sys.setprofile(previous)


def test_one_fence_reads_sources_once_but_every_new_fence_is_fresh(case):
    with snapshots() as old_calls:
        expected = bindings(case.owner)
    with snapshots() as new_calls:
        actual = bindings(_current_read(case.owner))
    assert actual == expected
    assert len(old_calls) == 5 and len(new_calls) == 1
    assert set(vars(case.owner)) == {"path", "clock", "_selected_root"}
    before = case.source.stat()
    case.source.write_bytes(b"changed source\n")
    os.utime(case.source, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert case.source.stat().st_size == before.st_size
    with pytest.raises(SwarmError, match="SOURCE_BINDING_INVALID"):
        _current_read(case.owner)


@pytest.mark.parametrize("mode,code", [
    ("task_and_revoked", "STALE_BINDING"), ("early_stale_late_revoked", "STALE_ACTOR"),
    ("early_stale_late_unknown", "STALE_ACTOR"), ("revoked", "ACTOR_REVOKED"),
    ("unknown", "ACTOR_UNKNOWN"), ("idle", "STALE_ACTOR"),
    ("invocation", "STALE_ACTOR"), ("capability", "STALE_ACTOR"),
    ("expired", "EXPIRED_BINDING"), ("cancelled", "INACTIVE_TASK"),
])
def test_typed_refusal_priority_matches_sequential_reads(case, mode, code):
    task, actors, _ = bindings(case.owner)
    document = case.document
    if mode == "task_and_revoked":
        document["binding"]["revision"] += 1
        document["actors"]["worker-a"]["actor_status"] = "revoked"
    elif mode.startswith("early_stale"):
        document["actors"]["worker-a"]["epoch"] += 1
        if mode.endswith("revoked"):
            document["actors"]["worker-b"]["actor_status"] = "revoked"
        else:
            del document["actors"]["worker-b"]
    elif mode in {"revoked", "idle"}:
        document["actors"]["worker-a"]["actor_status"] = mode
    elif mode == "unknown":
        del document["actors"]["worker-a"]
    elif mode in {"invocation", "capability"}:
        document["actors"]["worker-a"][mode + "_ref"] += "-changed"
    elif mode == "expired":
        document["binding"]["expires_at"] = time.time() - 1
    else:
        document["binding"]["status"] = "cancelled"
    write_owner(case)
    for reader in (lambda: case.owner, lambda: _current_read(case.owner)):
        with pytest.raises(SwarmError) as refused:
            compare(reader(), task, actors)
        assert refused.value.code == code


@pytest.mark.parametrize("name", ["read_task", "read_binding", "storage", "_snapshot",
                                   "_read_json", "_source_checks", "_storage", "_binding"])
@pytest.mark.parametrize("target", ["class", "instance"])
def test_overrides_use_the_original_public_calls(case, monkeypatch, name, target):
    original = getattr(OwnerFile, name)
    calls = []
    def override(*args, **kwargs):
        calls.append(name)
        return original(*args, **kwargs)
    if target == "class":
        monkeypatch.setattr(OwnerFile, name, override)
    else:
        monkeypatch.setattr(case.owner, name, override.__get__(case.owner))
    assert _current_read(case.owner) is case.owner
    bindings(_current_read(case.owner))
    assert calls


@pytest.mark.parametrize("mode", ["subclass", "clock", "module_clock"])
def test_nonstandard_readers_and_clock_callbacks_keep_sequential_semantics(case, monkeypatch, mode):
    if mode == "subclass":
        class CustomOwner(OwnerFile):
            pass
        case.owner = CustomOwner(case.path)
    elif mode == "clock":
        case.owner.clock = lambda: time.time()
    else:
        real_time = time.time
        monkeypatch.setattr(owner_file.time, "time", lambda: real_time())
    assert _current_read(case.owner) is case.owner
    assert bindings(_current_read(case.owner)) == bindings(case.owner)


def test_custom_actor_clock_source_mutation_is_seen_by_next_actor(case):
    calls = []
    def clock():
        calls.append(1)
        if len(calls) == 3:  # task, first actor snapshot, first actor lease
            case.source.write_bytes(b"changed source\n")
        return time.time()
    case.owner.clock = clock
    reader = _current_read(case.owner)
    assert reader is case.owner
    reader.read_task("task-1")
    reader.read_binding("task-1", "worker-a")
    with pytest.raises(SwarmError, match="SOURCE_BINDING_INVALID"):
        reader.read_binding("task-1", "worker-b")


def saved_reader(case, monkeypatch):
    task, actors, _ = bindings(case.owner)
    reader = object.__new__(loop_executor_runtime.SavedExecutor)
    reader.owner, reader.payload = case.owner, {"task_id": "task-1"}
    reader.plan = {"run_id": "run-1", "binding_digest": digest(task)}
    reader.binding = {"actor_binding_digests": {name: digest(value) for name, value in actors.items()},
                      "owner_input_sha256": hashlib.sha256(case.path.read_bytes()).hexdigest()}
    reader.policy, reader.specification, reader.current_guard = {}, {}, None
    reader.state = SimpleNamespace(cancellation=lambda run: None)
    reader.evidence = SimpleNamespace(check=lambda: None)
    reader.directory = case.root / "run-1"
    reader.directory.mkdir()
    monkeypatch.setattr(loop_executor_runtime, "check_current_executor_policy", lambda *a, **k: None)
    return reader


def test_saved_reader_keeps_proof_pre_storage_and_post_authority_separate(case, monkeypatch):
    reader = saved_reader(case, monkeypatch)
    with snapshots() as calls:
        reader.current()
    assert len(calls) == 2  # storage before proof; task + three actors after it
    with snapshots() as calls:
        reader.current()
    assert len(calls) == 2  # no cross-call snapshot cache


@pytest.mark.parametrize("stage", ["policy", "after_policy", "proof"])
@pytest.mark.parametrize("mode,code", [("source", "SOURCE_BINDING_INVALID"),
                                      ("actor", "STALE_ACTOR"), ("expired", "EXPIRED_BINDING")])
def test_saved_reader_refuses_late_changes_after_each_callback(case, monkeypatch, stage, mode, code):
    reader = saved_reader(case, monkeypatch)
    def mutate(*args, **kwargs):
        if mode == "source":
            before = case.source.stat()
            case.source.write_bytes(b"changed source\n")
            os.utime(case.source, ns=(before.st_atime_ns, before.st_mtime_ns))
        elif mode == "actor":
            case.document["actors"]["verifier"]["epoch"] += 1
            write_owner(case)
        else:
            case.document["binding"]["expires_at"] = time.time() - 1
            write_owner(case)
    kwargs = {}
    if stage == "policy":
        monkeypatch.setattr(loop_executor_runtime, "check_current_executor_policy", mutate)
    elif stage == "after_policy":
        kwargs["after_policy"] = mutate
    else:
        reader.evidence.check = mutate
    with pytest.raises(SwarmError, match=code):
        reader.current(**kwargs)


def test_callback_cancellation_and_new_clock_are_observed_before_return(case, monkeypatch):
    reader = saved_reader(case, monkeypatch)
    def cancel():
        reader.state.cancellation = lambda run: {"cancelled": True}
    with pytest.raises(SwarmError, match="RUN_CANCELLED"):
        reader.current(after_policy=cancel)
    reader.state.cancellation = lambda run: None
    def replace_clock():
        case.owner.clock = lambda: case.document["binding"]["expires_at"] + 1
    with pytest.raises(SwarmError, match="EXPIRED_BINDING"):
        reader.current(after_policy=replace_clock)


def test_current_guard_deadline_refusal_precedes_authority_reads(case, monkeypatch):
    reader = saved_reader(case, monkeypatch)
    def expired():
        require(False, "DEADLINE_EXPIRED")
    reader.current_guard = expired
    with snapshots() as calls, pytest.raises(SwarmError, match="DEADLINE_EXPIRED"):
        reader.current()
    assert not calls


@pytest.mark.parametrize("missing", ["owner", "source"])
def test_a_later_fence_does_not_reuse_missing_files(case, missing):
    bindings(_current_read(case.owner))
    (case.path if missing == "owner" else case.source).unlink()
    with pytest.raises(SwarmError, match="BINDING_UNAVAILABLE|SOURCE_BINDING_INVALID"):
        _current_read(case.owner)


def test_standard_clock_coordinator_reaches_fresh_internal_reads(tmp_path, monkeypatch):
    from task_swarm import closed_loop
    from test_task_swarm_closed_loop import MeasuredBackend, setup_loop
    setup = setup_loop(tmp_path)
    owner, file, document, payload, plan, actors, measure = setup
    now = time.time()
    payload["objective"]["budget"]["deadline"] = now + 600
    file.write_text(canonical(payload), encoding="utf-8")
    document["binding"].update(expires_at=now + 1200, context_digest=digest(payload))
    document["source_checks"][0]["sha256"] = hashlib.sha256(file.read_bytes()).hexdigest()
    owner.write_text(canonical(document), encoding="utf-8")
    plan["parent_input_digest"] = digest(payload)
    selected = []
    original = closed_loop._current_read
    def observed(reader):
        current = original(reader)
        selected.append(type(current))
        return current
    monkeypatch.setattr(closed_loop, "_current_read", observed)
    result = closed_loop.execute_closed_loop(owner, file, plan, MeasuredBackend(payload, measure),
                                            worker_actors=actors)
    assert result["receipt"]["budget"]["attempts_used"] == 5
    assert result["candidate"]["status"] == "needs_owner_review"
    assert selected and all(kind is owner_file._OwnerCurrentRead for kind in selected)
