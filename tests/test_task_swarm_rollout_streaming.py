"""Bounded rollout reads preserve runtime identity and completion semantics."""
from __future__ import annotations

import json
from datetime import datetime
import os
from pathlib import Path
import sys
import weakref

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest job")

RUNTIME = Path(__file__).resolve().parents[1] / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))
from task_swarm import codex

THREAD = "11111111-1111-4111-8111-111111111111"
TURN = "22222222-2222-4222-8222-222222222222"
OTHER_TURN = "33333333-3333-4333-8333-333333333333"


def records(cwd, *, turn=TURN):
    return [
        {"type": "session_meta", "payload": {"id": THREAD, "cwd": str(cwd),
         "timestamp": "2026-10-10T00:00:00Z"}},
        {"type": "turn_context", "payload": {"turn_id": turn, "model": codex.MODEL,
         "effort": codex.EFFORT, "approval_policy": "never",
         "sandbox_policy": {"type": "read-only"}}},
        {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": turn,
         "completed_at": 42, "last_agent_message": '{"answer":"日本語😀"}'}},
    ]


def encode(items):
    return "\n".join(json.dumps(item, ensure_ascii=False) for item in items).encode("utf-8")


def fixture(tmp_path, data=None):
    path = tmp_path / f"rollout-{THREAD}.jsonl"
    path.write_bytes(encode(records(tmp_path)) if data is None else data)
    return path


def resolve(tmp_path, **kwargs):
    return codex._runtime_receipt(THREAD, TURN, tmp_path, tmp_path, **kwargs)


@pytest.mark.parametrize("exact", [False, True])
def test_unicode_invalid_utf8_and_final_line_without_newline_keep_the_receipt(tmp_path, exact):
    data = encode(records(tmp_path)).replace("日本語".encode(), b"name\xff")
    path = fixture(tmp_path, data)
    result = resolve(tmp_path, **({"exact_record": (path, data)} if exact else {}))
    assert result["thread_id"] == THREAD and result["turn_id"] == TURN
    assert result["completed_output"] == '{"answer":"name\ufffd😀"}'
    assert result["completed_at"] == 42 and result["model"] == codex.MODEL
    assert result["runtime_receipt_path"] == str(path)


@pytest.mark.parametrize("separator", ["\n", "\r\n", "\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"])
def test_all_existing_splitlines_separators_remain_compatible(tmp_path, separator):
    data = separator.join(json.dumps(item, ensure_ascii=False) for item in records(tmp_path)).encode()
    fixture(tmp_path, data)
    assert resolve(tmp_path)["completed_at"] == 42
    assert list(codex._runtime_lines(tmp_path / f"rollout-{THREAD}.jsonl")) == data.decode("utf-8").splitlines()


def test_large_single_line_below_limit_is_not_silently_truncated(tmp_path):
    ignored = json.dumps({"unrelated": "x" * (1024 * 1024)}).encode() + b"\n"
    fixture(tmp_path, ignored + encode(records(tmp_path)))
    assert resolve(tmp_path)["completed_output"] == '{"answer":"日本語😀"}'


def test_partial_last_json_remains_ignored_instead_of_becoming_a_completion(tmp_path):
    fixture(tmp_path, encode(records(tmp_path)[:2]) + b'\n{"type":"event_msg","payload":')
    with pytest.raises(codex._RuntimeResolutionError, match="no completed local turn") as raised:
        resolve(tmp_path)
    assert raised.value.code == "runtime_turn_mismatch"


@pytest.mark.parametrize("exact", [False, True])
def test_rollout_limit_is_independent_from_stdout_limit_and_refuses_oversize(tmp_path, monkeypatch, exact):
    monkeypatch.setattr(codex, "MAX_RUNTIME_ROLLOUT_BYTES", 256)
    monkeypatch.setattr(codex, "MAX_STDOUT_BYTES", 1)
    path = fixture(tmp_path, b" " * 257)
    with pytest.raises(codex._RuntimeResolutionError) as raised:
        resolve(tmp_path, **({"exact_record": (path, path.read_bytes())} if exact else {}))
    assert raised.value.code == "runtime_rollout_limit"
    path.write_bytes(b" " * 256)
    assert resolve(tmp_path, **({"exact_record": (path, path.read_bytes())} if exact else {})) is None


@pytest.mark.parametrize("change", ["append", "replace", "unlink", "overwrite"])
def test_a_rollout_changed_during_streaming_cannot_publish_a_receipt(tmp_path, monkeypatch, change):
    path = fixture(tmp_path)
    original = codex.json.loads
    changed = False
    mutation_succeeded = False
    mutation_error = None
    descriptor_snapshots = []
    original_fstat = codex.os.fstat

    def fingerprint(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def named_snapshot():
        try:
            return fingerprint(path.stat())
        except OSError as exc:
            return {"errno": exc.errno, "winerror": getattr(exc, "winerror", None)}

    named_before = named_snapshot()

    def observed_fstat(fd):
        info = original_fstat(fd)
        descriptor_snapshots.append(fingerprint(info))
        return info

    def load(value, *args, **kwargs):
        nonlocal changed, mutation_succeeded, mutation_error
        result = original(value, *args, **kwargs)
        if not changed:
            changed = True
            try:
                if change == "append":
                    with path.open("ab") as out:
                        out.write(b"\n{}")
                elif change == "replace":
                    replacement = tmp_path / "replacement"
                    replacement_bytes = path.read_bytes()
                    replacement.write_bytes(replacement_bytes)
                    if os.name == "nt":
                        # Windows denies replacing this open target even with
                        # delete sharing. Move it aside, then rebind its name.
                        os.rename(path, tmp_path / "held-old")
                        assert not path.exists()
                    os.replace(replacement, path)
                    replacement_info = path.stat()
                    assert path.read_bytes() == replacement_bytes
                    assert (replacement_info.st_dev, replacement_info.st_ino) != named_before[:2]
                elif change == "unlink":
                    path.unlink()
                else:
                    with path.open("r+b") as out:
                        out.write(b" ")
                    info = path.stat()
                    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
            except OSError as exc:
                # _runtime_receipt treats an OSError as an unreadable candidate.
                # A failed fixture mutation must not be mistaken for a missed
                # runtime mutation; expose its native error before that catch.
                mutation_error = (f"fixture {change} failed: {type(exc).__name__} "
                                  f"errno={exc.errno!r} winerror={getattr(exc, 'winerror', None)!r}; "
                                  f"named_before={named_before!r} named_after={named_snapshot()!r} "
                                  f"descriptor_snapshots={descriptor_snapshots!r}")
                pytest.fail(mutation_error, pytrace=False)
            mutation_succeeded = True
        return result

    monkeypatch.setattr(codex.json, "loads", load)
    monkeypatch.setattr(codex.os, "fstat", observed_fstat)
    with pytest.raises(codex._RuntimeResolutionError) as raised:
        resolve(tmp_path)
        pytest.fail(f"runtime did not reject {change}; attempted={changed!r} "
                    f"succeeded={mutation_succeeded!r} named_before={named_before!r} "
                    f"named_after={named_snapshot()!r} descriptor_snapshots={descriptor_snapshots!r}")
    assert changed and mutation_succeeded, mutation_error
    assert raised.value.code == "runtime_rollout_changed"


def test_disappearance_before_open_preserves_missing_receipt_result(tmp_path, monkeypatch):
    path = fixture(tmp_path)
    original = codex._open_runtime_rollout

    def open_file(candidate):
        if candidate == path:
            raise FileNotFoundError("synthetic disappearance")
        return original(candidate)

    monkeypatch.setattr(codex, "_open_runtime_rollout", open_file)
    assert resolve(tmp_path) is None


def test_exact_bytes_remain_the_supplied_snapshot_without_reopening_the_path(tmp_path):
    path = tmp_path / "missing.jsonl"
    result = resolve(tmp_path, exact_record=(path, encode(records(tmp_path))))
    assert result["runtime_receipt_path"] == str(path)


def test_completed_turn_selection_ambiguity_and_failure_remain_explicit(tmp_path):
    items = records(tmp_path) + records(tmp_path, turn=OTHER_TURN)[1:]
    items.append({"type": "event_msg", "payload": {"type": "turn_failed", "turn_id": OTHER_TURN}})
    fixture(tmp_path, encode(items))
    assert resolve(tmp_path)["turn_failed"] is False
    assert codex._runtime_receipt(THREAD, OTHER_TURN, tmp_path, tmp_path)["turn_failed"] is True
    with pytest.raises(codex._RuntimeResolutionError) as raised:
        codex._runtime_receipt(THREAD, None, tmp_path, tmp_path)
    assert raised.value.code == "runtime_turn_ambiguous"


def test_multiple_matching_files_and_last_context_keep_existing_selection(tmp_path):
    first = fixture(tmp_path)
    second = tmp_path / f"z-{THREAD}.jsonl"
    updated = records(tmp_path)
    updated[1]["payload"]["effort"] = "synthetic-last-context"
    second.write_bytes(encode(updated))
    result = resolve(tmp_path)
    assert result["runtime_receipt_path"] == str(first)
    assert result["effort"] == "synthetic-last-context"


def test_streaming_checks_owner_cancellation_between_records(tmp_path):
    fixture(tmp_path, b"{}\n" * 1000 + encode(records(tmp_path)))
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == 8:
            raise codex.BackendError("cancelled", "synthetic owner cancellation", retryable=False)

    with pytest.raises(codex.BackendError) as raised:
        resolve(tmp_path, check_cancelled=cancel)
    assert raised.value.code == "cancelled" and calls == 8


def test_backend_owner_cancellation_reaches_rollout_parsing(tmp_path, monkeypatch):
    import threading
    from test_task_swarm_codex import _fake_codex, SCHEMA

    fake = _fake_codex(tmp_path)
    sessions = tmp_path / "sessions"
    monkeypatch.setenv("FIXTURE_SESSIONS", str(sessions))
    cancelled = threading.Event()
    original = codex._runtime_lines

    def after_first_line(*args, **kwargs):
        for line in original(*args, **kwargs):
            cancelled.set()
            yield line

    monkeypatch.setattr(codex, "_runtime_lines", after_first_line)
    with pytest.raises(codex.BackendError) as raised:
        codex.CodexBackend(fake, session_root=sessions).invoke(
            "synthetic fixture", SCHEMA, tmp_path / "attempts", timeout=2,
            cancel_event=cancelled,
        )
    assert raised.value.code == "cancelled"


def test_oversized_real_file_is_refused_before_any_payload_read(tmp_path, monkeypatch):
    path = tmp_path / f"rollout-{THREAD}.jsonl"
    with path.open("wb") as out:
        out.truncate(100 * 1024 * 1024)
    original = codex._open_runtime_rollout

    class NoPayloadRead:
        def __init__(self, file):
            self.file = file
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.file.close()
        def fileno(self):
            return self.file.fileno()
        def readline(self, *args):
            pytest.fail("oversized rollout payload must not be read")

    def opened(candidate):
        file = original(candidate)
        return NoPayloadRead(file) if candidate == path else file

    monkeypatch.setattr(codex, "_open_runtime_rollout", opened)
    with pytest.raises(codex._RuntimeResolutionError) as raised:
        resolve(tmp_path)
    assert raised.value.code == "runtime_rollout_limit"


@pytest.mark.parametrize("descriptor_changes", [False, True])
def test_descriptor_and_named_metadata_use_separate_baselines(tmp_path, monkeypatch, descriptor_changes):
    from types import SimpleNamespace

    fixture(tmp_path)
    original = codex.os.fstat
    calls = 0

    def descriptor_stat(fd):
        nonlocal calls
        calls += 1
        info = original(fd)
        # Windows fstat can report change time while stat reports birth time:
        # both descriptor observations differ from Path.stat but are stable
        # unless a change is explicitly injected into the second observation.
        return SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino,
                               st_size=info.st_size, st_ctime_ns=info.st_ctime_ns + 100,
                               st_mtime_ns=info.st_mtime_ns + (1 if descriptor_changes and calls > 1 else 0))

    monkeypatch.setattr(codex.os, "fstat", descriptor_stat)
    if descriptor_changes:
        with pytest.raises(codex._RuntimeResolutionError) as raised:
            resolve(tmp_path)
        assert raised.value.code == "runtime_rollout_changed"
    else:
        assert resolve(tmp_path)["completed_at"] == 42


def test_opened_descriptor_must_match_the_observed_named_file(tmp_path, monkeypatch):
    path = fixture(tmp_path, b"named file A\n")
    other = tmp_path / "other.jsonl"
    other.write_bytes(b"opened file B\n")
    monkeypatch.setattr(codex, "_open_runtime_rollout", lambda _: other.open("rb"))
    with pytest.raises(codex._RuntimeResolutionError) as raised:
        list(codex._runtime_lines(path))
    assert raised.value.code == "runtime_rollout_changed"


@pytest.mark.parametrize("failure", ["cancelled", "runtime_rollout_limit"])
def test_concurrent_mutation_does_not_replace_the_original_read_failure(tmp_path, monkeypatch, failure):
    path = fixture(tmp_path, b"{}\n")
    monkeypatch.setattr(codex, "MAX_RUNTIME_ROLLOUT_BYTES", 32)
    calls = 0
    cancelled = codex.BackendError("cancelled", "synthetic cancellation", retryable=False)

    def mutate():
        nonlocal calls
        calls += 1
        assert calls == 1
        if failure == "cancelled":
            path.unlink()
            raise cancelled
        path.write_bytes(b" " * 33)

    exception = codex.BackendError if failure == "cancelled" else codex._RuntimeResolutionError
    with pytest.raises(exception) as raised:
        list(codex._runtime_lines(path, check_cancelled=mutate))
    assert raised.value.code == failure
    if failure == "cancelled":
        assert raised.value is cancelled


def test_early_generator_close_still_checks_for_mutation(tmp_path):
    path = fixture(tmp_path, b"{}\n{}\n")
    lines = codex._runtime_lines(path)
    assert next(lines) == "{}"
    path.unlink()
    with pytest.raises(codex._RuntimeResolutionError) as raised:
        lines.close()
    assert raised.value.code == "runtime_rollout_changed"


def test_named_metadata_change_is_not_hidden_by_stable_descriptor(tmp_path, monkeypatch):
    from types import SimpleNamespace

    fixture(tmp_path)
    original = codex.os.fstat
    first = None

    def stable_descriptor(fd):
        nonlocal first
        if first is None:
            info = original(fd)
            first = SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino,
                                    st_size=info.st_size, st_ctime_ns=info.st_ctime_ns,
                                    st_mtime_ns=info.st_mtime_ns)
        return first

    monkeypatch.setattr(codex.os, "fstat", stable_descriptor)
    original_loads = codex.json.loads
    changed = False

    def update(value, *args, **kwargs):
        nonlocal changed
        parsed = original_loads(value, *args, **kwargs)
        if not changed:
            changed = True
            path = tmp_path / f"rollout-{THREAD}.jsonl"
            info = path.stat()
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
        return parsed

    monkeypatch.setattr(codex.json, "loads", update)
    with pytest.raises(codex._RuntimeResolutionError) as raised:
        resolve(tmp_path)
    assert raised.value.code == "runtime_rollout_changed"


@pytest.mark.parametrize("failure", [None, "invalid", "crt", "stream"])
def test_windows_rollout_opener_shares_delete_and_transfers_handle_ownership(tmp_path, monkeypatch, failure):
    import ctypes
    from ctypes import wintypes
    from types import SimpleNamespace

    path = tmp_path / "fixture.jsonl"
    calls, closed = [], []
    native_handle = 0x123456789ABC

    class NativeCall:
        def __init__(self, function):
            self.function = function
        def __call__(self, *args):
            return self.function(*args)

    def create(*args):
        calls.append(args)
        return wintypes.HANDLE(-1).value if failure == "invalid" else native_handle

    kernel = SimpleNamespace(CreateFileW=NativeCall(create),
                             CloseHandle=NativeCall(lambda handle: closed.append(("native", handle))))
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)
    monkeypatch.setattr(ctypes, "WinError", lambda error: OSError(error, "synthetic Windows failure"), raising=False)

    def transfer(handle, flags):
        assert handle == native_handle and flags == 0x8000
        if failure == "crt":
            raise OSError("synthetic transfer failure")
        return 7

    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(open_osfhandle=transfer))
    stream = object()

    def open_stream(fd, mode):
        assert (fd, mode) == (7, "rb")
        if failure == "stream":
            raise OSError("synthetic stream failure")
        return stream

    monkeypatch.setattr(codex, "os", SimpleNamespace(name="nt", O_RDONLY=0, O_BINARY=0x8000,
                        fdopen=open_stream, close=lambda fd: closed.append(("crt", fd))))
    if failure:
        with pytest.raises(OSError) as raised:
            codex._open_runtime_rollout(path)
        if failure == "invalid":
            assert raised.value.errno == 5 and closed == []
        else:
            assert closed == [("native", native_handle)] if failure == "crt" else closed == [("crt", 7)]
    else:
        assert codex._open_runtime_rollout(path) is stream
        assert closed == []
    assert calls == [(str(path), 0x80000000, 0x1 | 0x2 | 0x4, None, 3, 0x80, None)]
    assert kernel.CreateFileW.restype is wintypes.HANDLE
    assert kernel.CreateFileW.argtypes[-1] is wintypes.HANDLE


@pytest.mark.parametrize("exact", [False, True])
@pytest.mark.parametrize("selected_first", [False, True])
def test_known_turn_does_not_retain_dense_other_turn_payloads(tmp_path, monkeypatch, exact, selected_first):
    selected = records(tmp_path)
    others = []
    for number in range(256):
        turn = f"33333333-3333-4333-8333-{number:012d}"
        context, completion = records(tmp_path, turn=turn)[1:]
        context["payload"]["history"] = "別の履歴" * 128
        completion["payload"]["last_agent_message"] = "other completion " * 128
        others.extend((context, completion))
    rows = selected + others if selected_first else selected[:1] + others + selected[1:]
    raw = encode(rows)
    path = fixture(tmp_path, raw)
    original = codex.json.loads
    live, observed = {}, {"created": 0, "peak": 0}

    class TrackedPayload(dict):
        __slots__ = ("__weakref__",)

    def tracked(line):
        row = original(line)
        payload = row.get("payload") if isinstance(row, dict) else None
        if isinstance(payload, dict) and payload.get("turn_id") not in (None, TURN):
            payload = TrackedPayload(payload)
            row["payload"] = payload
            identity = id(payload)
            live[identity] = weakref.ref(payload, lambda _, identity=identity: live.pop(identity, None))
            observed["created"] += 1
            observed["peak"] = max(observed["peak"], len(live))
        return row

    monkeypatch.setattr(codex.json, "loads", tracked)
    result = resolve(tmp_path, **({"exact_record": (path, raw)} if exact else {}))
    assert result["turn_id"] == TURN and result["completed_output"] == '{"answer":"日本語😀"}'
    assert observed["created"] == 512  # Every nonselected record was still parsed.
    assert observed["peak"] <= 2  # Current decoder result and the preceding loop payload.
    assert live == {}


@pytest.mark.parametrize("identity", ["event_thread", "session_meta"])
def test_nonselected_turn_identity_after_selected_completion_is_still_checked(tmp_path, identity):
    rows = records(tmp_path)
    if identity == "event_thread":
        rows.append({"type": "turn_context", "payload": {"turn_id": OTHER_TURN,
                     "thread_id": "44444444-4444-4444-8444-444444444444"}})
    else:
        rows.append({"type": "session_meta", "payload": {"turn_id": OTHER_TURN,
                     "id": "44444444-4444-4444-8444-444444444444"}})
    fixture(tmp_path, encode(rows))
    with pytest.raises(codex._RuntimeResolutionError) as raised:
        resolve(tmp_path)
    assert raised.value.code == "runtime_thread_mismatch"


@pytest.mark.parametrize("mode", ["append", "cancel", "stale_session"])
def test_nonselected_tail_cannot_bypass_final_checks(tmp_path, monkeypatch, mode):
    rows = records(tmp_path)
    if mode == "stale_session":
        rows[0]["payload"]["timestamp"] = "2020-01-01T00:00:00Z"
    tail = records(tmp_path, turn=OTHER_TURN)[1:]
    path = fixture(tmp_path, encode(rows + tail))
    original = codex.json.loads
    seen_tail = False

    def decode(line):
        nonlocal seen_tail
        row = original(line)
        if row.get("payload", {}).get("turn_id") == OTHER_TURN and not seen_tail:
            seen_tail = True
            if mode == "append":
                with path.open("ab") as stream:
                    stream.write(b"\n{}\n")
        return row

    def cancelled():
        if mode == "cancel" and seen_tail:
            raise codex.BackendError("cancelled", "synthetic owner cancellation", retryable=False)

    monkeypatch.setattr(codex.json, "loads", decode)
    options = {"check_cancelled": cancelled}
    if mode == "stale_session":
        options["started_unix"] = datetime.fromisoformat("2026-10-10T00:00:00+00:00").timestamp()
    with pytest.raises((codex._RuntimeResolutionError, codex.BackendError)) as raised:
        resolve(tmp_path, **options)
    assert seen_tail
    assert raised.value.code == {"append": "runtime_rollout_changed", "cancel": "cancelled",
                                 "stale_session": "runtime_not_fresh"}[mode]


@pytest.mark.parametrize("change", ["cwd", "timestamp"])
def test_nonselected_session_metadata_still_updates_binding(tmp_path, change):
    rows = records(tmp_path)
    metadata = dict(rows[0]["payload"], turn_id=OTHER_TURN)
    metadata[change] = str(tmp_path / "other-work") if change == "cwd" else "2020-01-01T00:00:00Z"
    rows.append({"type": "session_meta", "payload": metadata})
    fixture(tmp_path, encode(rows))
    with pytest.raises(codex._RuntimeResolutionError) as raised:
        resolve(tmp_path, started_unix=datetime.fromisoformat("2026-10-10T00:00:00+00:00").timestamp())
    assert raised.value.code == {"cwd": "runtime_cwd_invalid", "timestamp": "runtime_not_fresh"}[change]


def test_known_turn_keeps_later_correction_failure_cwd_and_first_valid_path(tmp_path):
    first = fixture(tmp_path, encode(records(tmp_path)[:1]))
    middle = records(tmp_path)
    middle[1]["payload"]["cwd"] = str(tmp_path / "old-work")
    (tmp_path / f"m-{THREAD}.jsonl").write_bytes(encode(middle))
    later = records(tmp_path)
    later[1]["payload"].update(effort="last-context", cwd=str(tmp_path))
    without_cwd = {"type": "turn_context", "payload": {"turn_id": TURN, "model": codex.MODEL,
                   "effort": "corrected-context", "sandbox_policy": {"type": "read-only"}}}
    failure = {"type": "event_msg", "payload": {"type": "turn_failed", "turn_id": TURN}}
    correction = {"type": "event_msg", "payload": {"type": "turn_complete", "turn_id": TURN,
                  "completed_at": 99, "last_agent_message": '{"answer":"訂正😀"}'}}
    later += [without_cwd, failure, correction] + records(tmp_path, turn=OTHER_TURN)[1:]
    (tmp_path / f"z-{THREAD}.jsonl").write_bytes(encode(later))
    # Sort order, not creation order, owns the first valid receipt path.
    first.rename(tmp_path / f"a-{THREAD}.jsonl")
    result = resolve(tmp_path)
    assert result["runtime_receipt_path"] == str(tmp_path / f"a-{THREAD}.jsonl")
    assert result["effort"] == "corrected-context" and result["runtime_cwd"] == str(tmp_path)
    assert result["completed_at"] == 99 and result["completed_output"] == '{"answer":"訂正😀"}'
    assert result["turn_failed"] is True
    with pytest.raises(codex._RuntimeResolutionError) as raised:
        codex._runtime_receipt(THREAD, None, tmp_path, tmp_path)
    assert raised.value.code == "runtime_turn_ambiguous"
