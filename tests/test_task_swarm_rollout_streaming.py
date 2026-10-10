"""Bounded rollout reads preserve runtime identity and completion semantics."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

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

    def load(value, *args, **kwargs):
        nonlocal changed
        result = original(value, *args, **kwargs)
        if not changed:
            changed = True
            if change == "append":
                with path.open("ab") as out:
                    out.write(b"\n{}")
            elif change == "replace":
                replacement = tmp_path / "replacement"
                replacement.write_bytes(path.read_bytes())
                os.replace(replacement, path)
            elif change == "unlink":
                path.unlink()
            else:
                with path.open("r+b") as out:
                    out.write(b" ")
                info = path.stat()
                os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
        return result

    monkeypatch.setattr(codex.json, "loads", load)
    with pytest.raises(codex._RuntimeResolutionError) as raised:
        resolve(tmp_path)
    assert raised.value.code == "runtime_rollout_changed"


def test_disappearance_before_open_preserves_missing_receipt_result(tmp_path, monkeypatch):
    path = fixture(tmp_path)
    original = Path.open

    def open_file(self, *args, **kwargs):
        if self == path and args == ("rb",):
            raise FileNotFoundError("synthetic disappearance")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_file)
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
    original = Path.open

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

    def opened(self, *args, **kwargs):
        file = original(self, *args, **kwargs)
        return NoPayloadRead(file) if self == path else file

    monkeypatch.setattr(Path, "open", opened)
    with pytest.raises(codex._RuntimeResolutionError) as raised:
        resolve(tmp_path)
    assert raised.value.code == "runtime_rollout_limit"
