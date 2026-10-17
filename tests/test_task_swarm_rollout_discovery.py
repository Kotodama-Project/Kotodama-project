"""Discovery keeps receipt ordering while allowing cancellation between entries."""
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


def receipt_file(root, relative, output="first"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {"type": "session_meta", "payload": {"id": THREAD, "cwd": str(root)}},
        {"type": "turn_context", "payload": {"turn_id": TURN, "model": "test", "effort": output}},
        {"type": "event_msg", "payload": {"turn_id": TURN, "type": "task_complete", "last_agent_message": output}},
    ]
    path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
    return path


def resolve(root, **kwargs):
    return codex._runtime_receipt(THREAD, TURN, root, root, **kwargs)


def legacy_paths(root):
    paths = {}
    for path in root.rglob(f"*{THREAD}*.jsonl"):
        if path.is_file() and THREAD in path.name:
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(root)
            except (OSError, RuntimeError, ValueError):
                continue
            paths[os.path.normcase(str(resolved))] = resolved
    return sorted(paths.values())


class Scans:
    def __init__(self, monkeypatch, fail_directory=None, fail_after=None, fail_once=False):
        self.original = os.scandir
        self.active = self.peak = self.entries = 0
        self.paths = []
        self.fail_directory = fail_directory
        self.fail_after = fail_after
        self.fail_once = fail_once
        self.failed = False
        monkeypatch.setattr(codex.os, "scandir", self.open)

    def open(self, directory):
        self.paths.append(Path(directory))
        if (Path(directory) == self.fail_directory and self.fail_after is None
                and (not self.fail_once or not self.failed)):
            self.failed = True
            raise PermissionError("synthetic unreadable directory")
        iterator = self.original(directory)
        owner = self
        owner.active += 1
        owner.peak = max(owner.peak, owner.active)

        class Scan:
            seen = 0
            def __enter__(self): return self
            def __exit__(self, *args):
                iterator.close()
                owner.active -= 1
            def __iter__(self): return self
            def __next__(self):
                if (Path(directory) == owner.fail_directory and self.seen == owner.fail_after
                        and (not owner.fail_once or not owner.failed)):
                    owner.failed = True
                    raise OSError("synthetic enumeration failure")
                entry = next(iterator)
                self.seen += 1
                owner.entries += 1
                return entry
        return Scan()


@pytest.mark.parametrize("files", [0, 20])
def test_already_cancelled_without_a_matching_file_is_not_a_missing_receipt(tmp_path, monkeypatch, files):
    for number in range(files):
        (tmp_path / f"unrelated-{number}.jsonl").touch()
    scans = Scans(monkeypatch)
    def cancelled():
        raise codex.BackendError("cancelled", "test owner cancellation", retryable=False)
    with pytest.raises(codex.BackendError) as raised:
        resolve(tmp_path, check_cancelled=cancelled)
    assert raised.value.code == "cancelled"
    assert scans.paths == [] and scans.active == 0


def test_cancellation_during_nonmatching_entries_closes_the_only_handle(tmp_path, monkeypatch):
    for number in range(100):
        (tmp_path / f"unrelated-{number}.jsonl").touch()
    scans = Scans(monkeypatch)
    checks = 0
    def cancelled():
        nonlocal checks
        checks += 1
        if checks == 12:
            raise codex.BackendError("cancelled", "test owner cancellation", retryable=False)
    with pytest.raises(codex.BackendError):
        resolve(tmp_path, check_cancelled=cancelled)
    assert scans.entries == 10 and scans.active == 0 and scans.peak == 1


def test_nested_sort_order_still_selects_last_completion_and_first_receipt_path(tmp_path, monkeypatch):
    receipt_file(tmp_path, f"z-{THREAD}.jsonl", "last")
    first = receipt_file(tmp_path, f"a/nested-{THREAD}.jsonl", "first")
    receipt_file(tmp_path, f"b-{THREAD}.jsonl", "middle")
    expected = legacy_paths(tmp_path)
    scans = Scans(monkeypatch)
    result = resolve(tmp_path)
    assert result["runtime_receipt_path"] == str(first)
    assert result["completed_output"] == result["effort"] == "last"
    assert expected[0] == first
    assert scans.peak == 1 and scans.active == 0
    assert len(scans.paths) == len(set(scans.paths)) == 2


def test_filename_matching_keeps_platform_case_and_exact_thread_filter(tmp_path):
    receipt_file(tmp_path, f"upper-{THREAD}.JSONL")
    receipt_file(tmp_path, f"normal-{THREAD}.jsonl")
    # pathlib uses re.IGNORECASE on Windows, which also matches Unicode long s.
    receipt_file(tmp_path, f"unicode-{THREAD}.jſonl")
    receipt_file(tmp_path, f"suffix-{THREAD}.jsonl.bak")
    expected = legacy_paths(tmp_path)
    actual = sorted(codex._runtime_candidates(tmp_path, THREAD, None))
    assert actual == expected


def test_file_aliases_deduplicate_inside_root_and_directory_alias_is_not_followed(tmp_path):
    original = receipt_file(tmp_path, f"real/source-{THREAD}.jsonl")
    outside = tmp_path.parent / f"outside-{THREAD}.jsonl"
    outside.write_bytes(original.read_bytes())
    try:
        (tmp_path / f"alias-{THREAD}.jsonl").symlink_to(original)
        (tmp_path / f"escape-{THREAD}.jsonl").symlink_to(outside)
        (tmp_path / "loop").symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("native symlink creation is unavailable")
    expected = legacy_paths(tmp_path)
    assert expected == [original]
    assert resolve(tmp_path)["runtime_receipt_path"] == str(original)


def test_unreadable_directory_cannot_publish_only_a_readable_sibling(tmp_path, monkeypatch):
    receipt_file(tmp_path, f"unreadable/hidden-{THREAD}.jsonl", "hidden")
    visible = receipt_file(tmp_path, f"visible/{THREAD}.jsonl", "visible")
    scans = Scans(monkeypatch, tmp_path / "unreadable")
    with pytest.raises(codex._RuntimeResolutionError) as raised:
        resolve(tmp_path)
    assert raised.value.code == "runtime_discovery_failed"
    assert scans.active == 0 and scans.peak == 1


def test_interrupted_directory_enumeration_does_not_publish_partial_candidates(tmp_path, monkeypatch):
    receipt_file(tmp_path, f"{THREAD}.jsonl")
    (tmp_path / "ignored").touch()
    scans = Scans(monkeypatch, tmp_path, fail_after=1)
    with pytest.raises(codex._RuntimeResolutionError) as raised:
        resolve(tmp_path)
    assert raised.value.code == "runtime_discovery_failed"
    assert scans.active == 0


def test_deep_tree_has_one_open_handle_and_exact_record_never_scans(tmp_path, monkeypatch):
    directory = tmp_path
    # This tests handle ownership, not Windows long-path opt-in.
    depth = 20 if os.name == "nt" else 80
    for _ in range(depth):
        directory /= "d"
    path = receipt_file(tmp_path, str(directory.relative_to(tmp_path) / f"{THREAD}.jsonl"))
    data = path.read_bytes()
    scans = Scans(monkeypatch)
    assert resolve(tmp_path)["runtime_receipt_path"] == str(path)
    assert scans.peak == 1 and scans.active == 0 and len(scans.paths) == depth + 1
    scans.paths.clear()
    assert resolve(tmp_path, exact_record=(path, data))["runtime_receipt_path"] == str(path)
    assert scans.paths == []


@pytest.mark.parametrize("fail_after", [None, 1])
def test_transient_failure_refuses_instead_of_returning_stale_completion(tmp_path, monkeypatch, fail_after):
    old = receipt_file(tmp_path, f"a-{THREAD}.jsonl", "old")
    new = receipt_file(tmp_path, f"z/nested/z-{THREAD}.jsonl", "new")
    # Legacy glob's second pass can recover descendants after the first pass
    # failed; a one-pass walker must not silently lose their later completion.
    with monkeypatch.context() as probe:
        Scans(probe, tmp_path / "z", fail_after=fail_after, fail_once=True)
        assert legacy_paths(tmp_path) == [old, new]
    scans = Scans(monkeypatch, tmp_path / "z", fail_after=fail_after, fail_once=True)
    with pytest.raises(codex._RuntimeResolutionError) as raised:
        resolve(tmp_path)
    assert raised.value.code == "runtime_discovery_failed"
    assert scans.active == 0


def test_directory_gone_before_scan_keeps_existing_skip_semantics(tmp_path, monkeypatch):
    gone = tmp_path / "gone"
    gone.mkdir()
    visible = receipt_file(tmp_path, f"{THREAD}.jsonl")
    original = os.scandir
    def scan(path):
        if Path(path) == gone:
            gone.rmdir()
            raise FileNotFoundError("synthetic vanished directory")
        return original(path)
    monkeypatch.setattr(codex.os, "scandir", scan)
    assert resolve(tmp_path)["runtime_receipt_path"] == str(visible)


def test_backend_records_incomplete_discovery_as_nonretryable_refusal(tmp_path, monkeypatch):
    from test_task_swarm_codex import _fake_codex, SCHEMA
    fake = _fake_codex(tmp_path)
    sessions = tmp_path / "sessions"
    monkeypatch.setenv("FIXTURE_SESSIONS", str(sessions))
    original = os.scandir
    def scan(path):
        if Path(path) == sessions:
            raise PermissionError("synthetic discovery failure")
        return original(path)
    monkeypatch.setattr(codex.os, "scandir", scan)
    with pytest.raises(codex.BackendError) as raised:
        codex.CodexBackend(fake, session_root=sessions).invoke(
            "synthetic fixture", SCHEMA, tmp_path / "attempt", timeout=2)
    assert raised.value.code == "runtime_discovery_failed" and raised.value.retryable is False
    assert not Path(raised.value.paths["receipt"]).exists()
    diagnostics = json.loads(Path(raised.value.paths["diagnostics"]).read_text(encoding="utf-8"))
    assert diagnostics["error_code"] == "runtime_discovery_failed"
