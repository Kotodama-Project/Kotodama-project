"""Invocation-local owner reads retain lazy refusals and callback fences."""
from __future__ import annotations

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest environment")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from task_swarm import owner_file, loop_executor_runtime
from task_swarm.owner_file import OwnerFile, _ForwardClock, _current_read
from task_swarm.protocol import SwarmError, canonical, digest
from task_swarm.task_contract import require


@pytest.fixture
def direct_case(tmp_path):
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


def forwarded(case):
    # A real ReuseOwner's mutable clock field without starting an origin run.
    from task_swarm.learning_reuse import ReuseOwner
    target = object.__new__(ReuseOwner)
    target.clock = time.time
    case.owner.clock = _ForwardClock(target)
    return target


@pytest.fixture(params=("direct", "forwarded"))
def case(direct_case, request):
    if request.param == "forwarded":
        forwarded(direct_case)
    return direct_case


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


@pytest.mark.parametrize("read", ["task", "actor", "storage"])
def test_forwarded_clock_change_inside_a_fence_restarts_the_public_read(direct_case, read):
    target = forwarded(direct_case)
    reader = _current_read(direct_case.owner)
    reader.read_task("task-1")
    calls = []
    def changed():
        calls.append(1)
        # Restore the builtin inside the callback. This old fence must still
        # stay sequential, and the changed Source must be checked first.
        target.clock = time.time
        direct_case.source.write_bytes(b"changed source\n")
        return time.time()
    target.clock = changed
    actions = {"task": lambda: reader.read_task("task-1"),
               "actor": lambda: reader.read_binding("task-1", "worker-a"),
               "storage": reader.storage}
    with pytest.raises(SwarmError, match="SOURCE_BINDING_INVALID"):
        actions[read]()
    assert calls == [1]  # no speculative custom-clock invocation on old bytes
    direct_case.source.write_bytes(b"current source\n")
    with snapshots() as old_fence:
        bindings(reader)
    with snapshots() as new_fence:
        bindings(_current_read(direct_case.owner))
    assert len(old_fence) == 5 and len(new_fence) == 1


def test_forwarded_clock_changed_at_actor_check_falls_back_before_callback(direct_case):
    target = forwarded(direct_case)
    reader = _current_read(direct_case.owner)
    calls, changes, previous = [], [], sys.getprofile()
    def changed():
        calls.append(1)
        direct_case.source.write_bytes(b"changed source\n")
        return time.time()
    def at_actor(frame, event, _arg):
        if event == "call" and frame.f_code is OwnerFile._binding.__code__ and not changes:
            changes.append(1)
            target.clock = changed
    sys.setprofile(at_actor)
    try:
        with pytest.raises(SwarmError, match="SOURCE_BINDING_INVALID"):
            reader.read_binding("task-1", "worker-a")
    finally:
        sys.setprofile(previous)
    assert changes == [1] and calls == [1]


def test_forwarded_custom_clock_keeps_original_sequential_callback_order(direct_case):
    target = forwarded(direct_case)
    calls = []
    def clock():
        calls.append(1)
        if len(calls) == 3:  # task; first actor snapshot; first actor lease
            direct_case.source.write_bytes(b"changed source\n")
        return time.time()
    target.clock = clock
    reader = _current_read(direct_case.owner)
    assert reader is direct_case.owner and calls == []
    reader.read_task("task-1")
    reader.read_binding("task-1", "worker-a")
    with pytest.raises(SwarmError, match="SOURCE_BINDING_INVALID"):
        reader.read_binding("task-1", "worker-b")
    assert len(calls) == 4


@pytest.mark.parametrize("stage", ["policy", "after_policy", "proof"])
def test_final_callback_forwarded_clock_replacement_is_current(direct_case, monkeypatch, stage):
    target = forwarded(direct_case)
    reader = saved_reader(direct_case, monkeypatch)
    def expire(*args, **kwargs):
        target.clock = lambda: direct_case.document["binding"]["expires_at"] + 1
    kwargs = {}
    if stage == "policy":
        monkeypatch.setattr(loop_executor_runtime, "check_current_executor_policy", expire)
    elif stage == "after_policy":
        kwargs["after_policy"] = expire
    else:
        reader.evidence.check = expire
    with pytest.raises(SwarmError, match="EXPIRED_BINDING"):
        reader.current(**kwargs)


@pytest.mark.parametrize("override", ["getattribute", "property", "bridge", "bridge_subclass"])
def test_forwarded_nonstandard_lookup_is_not_inspected_or_shared(direct_case, monkeypatch, override):
    calls = []
    class Target:
        def __init__(self):
            self.clock = time.time
    target = Target()
    bridge = _ForwardClock(target)
    if override == "getattribute":
        def lookup(self, name):
            if name == "clock":
                calls.append(name)
            return object.__getattribute__(self, name)
        monkeypatch.setattr(Target, "__getattribute__", lookup)
    elif override == "property":
        def clock(self):
            calls.append("clock")
            return time.time
        monkeypatch.setattr(Target, "clock", property(clock), raising=False)
    elif override == "bridge":
        original = _ForwardClock.__call__
        def call(self):
            calls.append("clock")
            return original(self)
        monkeypatch.setattr(_ForwardClock, "__call__", call)
    else:
        class CustomBridge(_ForwardClock):
            def __call__(self):
                calls.append("clock")
                return super().__call__()
        bridge = CustomBridge(target)
    direct_case.owner.clock = bridge
    assert _current_read(direct_case.owner) is direct_case.owner and calls == []
    direct_case.owner.read_task("task-1")
    assert calls == ["clock"]


def test_override_added_mid_fence_uses_the_current_public_reader(direct_case, monkeypatch):
    forwarded(direct_case)
    reader = _current_read(direct_case.owner)
    def refuse(*args):
        raise SwarmError("SOURCE_BINDING_INVALID", "current overridden Source reader")
    monkeypatch.setattr(direct_case.owner, "_source_checks", refuse)
    with pytest.raises(SwarmError, match="SOURCE_BINDING_INVALID"):
        reader.read_binding("task-1", "worker-a")


def test_parallel_fences_keep_a_new_thread_local_clock_and_shared_owner_unchanged(direct_case):
    target = forwarded(direct_case)
    bridge = direct_case.owner.clock
    ready, release = threading.Barrier(3), threading.Barrier(3)
    local = threading.local()
    real_time = time.time
    def clock():
        return direct_case.document["binding"]["expires_at"] + 1 if local.expired else real_time()
    def read(expired):
        local.expired = expired
        reader = _current_read(direct_case.owner)
        reader.read_task("task-1")
        ready.wait(timeout=5)
        release.wait(timeout=5)
        try:
            reader.read_binding("task-1", "worker-a")
            return "active"
        except SwarmError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(read, expired) for expired in (False, True)]
        ready.wait(timeout=5)
        target.clock = clock
        release.wait(timeout=5)
        assert [future.result(timeout=5) for future in pending] == ["active", "EXPIRED_BINDING"]
    assert direct_case.owner.clock is bridge and target.clock is clock


def test_bridge_source_descriptor_runs_only_with_a_fresh_public_read(direct_case, monkeypatch):
    target = forwarded(direct_case)
    reader = _current_read(direct_case.owner)
    reader.read_task("task-1")
    calls = []
    def lookup(bridge):
        calls.append(1)
        direct_case.source.write_bytes(b"changed source\n")
        return target
    monkeypatch.setattr(_ForwardClock, "_source", property(lookup))
    assert owner_file._current_clock(direct_case.owner) is None and calls == []
    with pytest.raises(SwarmError, match="SOURCE_BINDING_INVALID"):
        reader.read_task("task-1")
    assert calls == [1]


@pytest.mark.parametrize("target", ["instance", "class"])
def test_late_binding_override_never_receives_a_cached_snapshot(direct_case, monkeypatch, target):
    forwarded(direct_case)
    reader = _current_read(direct_case.owner)
    expected = direct_case.owner.read_binding("task-1", "worker-a")
    calls, changes, previous = [], [], sys.getprofile()
    def replacement(self, snapshot, task_id, actor_ref, **kwargs):
        calls.append(1)
        return expected
    def between(frame, event, _arg):
        if event == "return" and frame.f_code is owner_file._OwnerCurrentRead._task.__code__ and not changes:
            changes.append(1)
            direct_case.source.write_bytes(b"changed source\n")
            if target == "instance":
                monkeypatch.setattr(direct_case.owner, "_binding", replacement.__get__(direct_case.owner))
            else:
                monkeypatch.setattr(OwnerFile, "_binding", replacement)
    sys.setprofile(between)
    try:
        with pytest.raises(SwarmError, match="SOURCE_BINDING_INVALID"):
            reader.read_binding("task-1", "worker-a")
    finally:
        sys.setprofile(previous)
    assert changes == [1] and calls == []


@pytest.mark.parametrize("override", ["clock", "getattribute", "dict"])
def test_owner_lookup_overrides_never_run_against_a_cached_snapshot(direct_case, monkeypatch, override):
    forwarded(direct_case)
    bridge = direct_case.owner.clock
    reader = _current_read(direct_case.owner)
    reader.read_task("task-1")
    calls = []
    def clock(owner):
        calls.append("clock")
        direct_case.source.write_bytes(b"changed source\n")
        return bridge
    def lookup(owner, name):
        if name == "clock":
            return clock(owner)
        return object.__getattribute__(owner, name)
    def namespace(owner, name):
        if name == "__dict__":
            calls.append("dict")
            direct_case.source.write_bytes(b"changed source\n")
            return {"clock": bridge}
        return object.__getattribute__(owner, name)
    if override == "clock":
        monkeypatch.setattr(OwnerFile, "clock", property(clock), raising=False)
    elif override == "getattribute":
        monkeypatch.setattr(OwnerFile, "__getattribute__", lookup)
    else:
        monkeypatch.setattr(OwnerFile, "__getattribute__", namespace)
    assert owner_file._current_clock(direct_case.owner) is None and calls == []
    if override == "dict":
        # A normal public read never asks for the instance namespace. Reject
        # sharing without inventing a new callback or a false Source refusal.
        assert reader.read_task("task-1") == direct_case.owner.read_task("task-1")
        assert calls == []
    else:
        with pytest.raises(SwarmError, match="SOURCE_BINDING_INVALID"):
            reader.read_task("task-1")
        assert calls == ["clock"]


@pytest.mark.parametrize("target", ["owner", "forward_source"])
def test_nonstandard_namespace_is_not_probed_for_current_clock(direct_case, target):
    source = forwarded(direct_case)
    reader = _current_read(direct_case.owner)
    calls = []
    class Namespace(dict):
        def get(self, key, default=None):
            calls.append("get")
            direct_case.source.write_bytes(b"changed source\n")
            return super().get(key, default)
        def __contains__(self, key):
            calls.append("contains")
            direct_case.source.write_bytes(b"changed source\n")
            return super().__contains__(key)
    selected = direct_case.owner if target == "owner" else source
    selected.__dict__ = Namespace(vars(selected))
    assert owner_file._current_clock(direct_case.owner) is None and calls == []
    assert reader.read_task("task-1") == direct_case.owner.read_task("task-1")
    assert calls == []


def test_forward_source_metaclass_is_not_probed_for_current_clock(direct_case):
    calls = []
    class Meta(type):
        def __getattribute__(cls, name):
            calls.append(name)
            return super().__getattribute__(name)
    class Source(metaclass=Meta):
        def __init__(self):
            self.clock = time.time
    direct_case.owner.clock = _ForwardClock(Source())
    assert _current_read(direct_case.owner) is direct_case.owner and calls == []
    assert direct_case.owner.read_task("task-1")["task_id"] == "task-1"
    assert calls == []


@pytest.mark.parametrize("override", ["inherited_clock", "dict"])
def test_forward_source_descriptors_are_not_called_on_old_bytes(direct_case, override):
    forwarded(direct_case)
    reader = _current_read(direct_case.owner)
    calls = []
    class ClockBase:
        @property
        def clock(self):
            calls.append("clock")
            direct_case.source.write_bytes(b"changed source\n")
            return time.time
    class ClockSource(ClockBase):
        pass
    class NamespaceSource:
        def __init__(self):
            self.clock = time.time
        @property
        def __dict__(self):
            calls.append("dict")
            direct_case.source.write_bytes(b"changed source\n")
            return {"clock": time.time}
    direct_case.owner.clock._source = ClockSource() if override == "inherited_clock" else NamespaceSource()
    assert owner_file._current_clock(direct_case.owner) is None and calls == []
    if override == "inherited_clock":
        with pytest.raises(SwarmError, match="SOURCE_BINDING_INVALID"):
            reader.read_task("task-1")
        assert calls == ["clock"]
    else:
        assert reader.read_task("task-1") == direct_case.owner.read_task("task-1")
        assert calls == []


@pytest.mark.parametrize("target", ["owner", "forward_source"])
def test_lookup_method_descriptors_are_inspected_without_binding(direct_case, monkeypatch, target):
    source = forwarded(direct_case)
    reader = _current_read(direct_case.owner)
    reader.read_task("task-1")
    calls = []
    class Lookup:
        def __get__(self, instance, cls):
            calls.append("class" if instance is None else "instance")
            direct_case.source.write_bytes(b"changed source\n")
            return object.__getattribute__ if instance is None else object.__getattribute__.__get__(instance, cls)
    selected_type = type(direct_case.owner if target == "owner" else source)
    monkeypatch.setattr(selected_type, "__getattribute__", Lookup())
    assert owner_file._current_clock(direct_case.owner) is None and calls == []
    with pytest.raises(SwarmError, match="SOURCE_BINDING_INVALID"):
        reader.read_task("task-1")
    assert calls and "class" not in calls


def test_namespace_descriptor_cannot_impersonate_a_builtin_type(direct_case):
    from types import GetSetDescriptorType
    forwarded(direct_case)
    reader = _current_read(direct_case.owner)
    calls = []
    class Namespace:
        @property
        def __class__(self):
            calls.append("class")
            direct_case.source.write_bytes(b"changed source\n")
            return GetSetDescriptorType
        @property
        def __objclass__(self):
            return Source
        def __get__(self, instance, cls):
            calls.append("dict")
            return {"clock": time.time}
    class Source:
        __dict__ = Namespace()
        def __init__(self):
            self.clock = time.time
    direct_case.owner.clock._source = Source()
    assert owner_file._current_clock(direct_case.owner) is None and calls == []
    assert reader.read_task("task-1") == direct_case.owner.read_task("task-1")
    assert calls == []
