"""The declared fixture bytes, including a swapped launch path, own execution."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import time

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest environment")

import test_task_swarm_loop_executor_contract as contract
from task_swarm.loop_executor import check_current_executor_policy, loop_schema, verify_loop_response
from task_swarm.loop_executor_runtime import select_executor_policy
from task_swarm.owner_file import OwnerFile
from task_swarm.protocol import SwarmError
from task_swarm.codex import BackendError
from task_swarm.task_backend import TaskBackend


def atomic_replace(path, raw):
    path.chmod(0o600)
    replacement = path.with_name("replacement.py")
    replacement.write_bytes(raw)
    os.replace(replacement, path)


def marked_case(root, monkeypatch):
    approved, substituted = root/"approved-start", root/"substituted-start"
    body = contract.CHILD
    def script(marker):
        return ("import pathlib\npathlib.Path(" + repr(str(marker)) + ").write_text('opened')\n").encode() + body
    trusted, changed = script(approved), script(substituted)
    monkeypatch.setattr(contract, "CHILD", trusted)
    return contract.case(root), trusted, changed, approved, substituted


def produce(case, directory, observed):
    payload, specification, policy, delivered, dispatch, owner_path, document = case
    owner = OwnerFile(owner_path, clock=lambda: 1000)
    check_current_executor_policy(policy, payload, specification, owner_path=owner_path, owner_document=document)
    result = TaskBackend(owner_path.parent/"worker.py", loop_mode="local_executable_fixture").produce_loop(
        delivered, directory, policy=policy, dispatch_identity=dispatch, actor_ref="worker",
        timeout=10, cancel_event=None,
        on_process=lambda pid, created: observed.append({"kind": "process", "pid": pid, "created_at": created}))
    options = dict(policy=policy, delivered=delivered, dispatch_identity=dispatch,
        expected_attempt={**dispatch, "worker_ref": "worker", "identity": observed[0]},
        expected_schema=loop_schema(delivered),
        current_guard=lambda: owner.read_binding(payload["task_id"], "worker"), attempt_directory=directory)
    return result, options


def test_restored_declared_path_cannot_hide_different_executed_bytes(tmp_path, monkeypatch):
    case, trusted, changed, approved, substituted = marked_case(tmp_path, monkeypatch)
    declared, original = tmp_path/"worker.py", subprocess.Popen
    started = []
    def swap(command, *args, **kwargs):
        atomic_replace(declared, changed)
        try:
            process = original(command, *args, **kwargs)
            started.append(process)
            deadline = time.monotonic() + 5
            while not approved.exists() and not substituted.exists():
                assert process.poll() is None and time.monotonic() < deadline
                time.sleep(.001)
        finally:
            atomic_replace(declared, trusted)
        return process
    monkeypatch.setattr(subprocess, "Popen", swap)
    result, options = produce(case, tmp_path/"attempts", [])
    verify_loop_response(result, **options, freeze=True)
    assert hashlib.sha256(declared.read_bytes()).hexdigest() == case[2]["executable"]["sha256"]
    assert started and all(process.poll() == 0 for process in started)
    assert not substituted.exists(), "restoring the declared path must not bless replacement code"
    assert approved.exists()


@pytest.mark.parametrize("before_read", [True, False])
def test_snapshot_replacement_cannot_change_compiled_bytes(tmp_path, monkeypatch, before_read):
    case, trusted, changed, approved, substituted = marked_case(tmp_path, monkeypatch)
    original, started, snapshots = subprocess.Popen, [], []
    def swap(command, *args, **kwargs):
        snapshot = Path(command[4])
        assert snapshot.name == "executable.py" and snapshot.read_bytes() == trusted
        snapshots.append(snapshot)
        if before_read:
            atomic_replace(snapshot, changed)
        process = original(command, *args, **kwargs)
        started.append(process)
        deadline = time.monotonic() + 5
        if before_read:
            # Waiting for interpreter exit makes the failing hash check happen
            # before restoration, without relying on process-start timing.
            process.wait(timeout=5)
            assert process.returncode == 73
        else:
            while not approved.exists():
                assert process.poll() is None and time.monotonic() < deadline
                time.sleep(.001)
            atomic_replace(snapshot, changed)
        atomic_replace(snapshot, trusted)
        return process
    monkeypatch.setattr(subprocess, "Popen", swap)
    if before_read:
        with pytest.raises(BackendError):
            produce(case, tmp_path/"attempts", [])
        assert not approved.exists()
        assert not list((tmp_path/"attempts").rglob("receipt.json"))
    else:
        result, options = produce(case, tmp_path/"attempts", [])
        verify_loop_response(result, **options, freeze=True)
        assert approved.exists()
    assert snapshots and not substituted.exists()
    assert all(process.poll() is not None for process in started)
    assert not list((tmp_path/"attempts").rglob(".stdout.raw"))
    assert not list((tmp_path/"attempts").rglob(".stderr.raw"))


def test_path_only_eight_artifact_receipt_is_not_a_snapshot_proof(tmp_path):
    value, options, _ = contract.response(tmp_path, snapshot=False)
    assert len(value["receipt"]["runtime"]["receipt"]["artifact_digests"]) == 8
    with pytest.raises(SwarmError, match="RUN_RUNTIME_PATH_CHANGED"):
        verify_loop_response(value, **options, freeze=True)


@pytest.mark.parametrize("prefix", [
    b"marker = 1\nimport __main__\nassert __main__.marker == marker\n"
    b"assert not {'raw', 'snapshot', 'namespace', 'launch'} & globals().keys()\n",
    b"from __future__ import annotations\nfrom dataclasses import dataclass, fields\n"
    b"from typing import ClassVar\n@dataclass\nclass Example:\n"
    b"    marker: ClassVar[int] = 1\n    value: int = 7\n"
    b"assert [field.name for field in fields(Example)] == ['value']\n",
], ids=["main-module", "dataclass-annotations"])
def test_snapshot_keeps_normal_script_main_module(tmp_path, monkeypatch, prefix):
    monkeypatch.setattr(contract, "CHILD", prefix + contract.CHILD)
    result, options = produce(contract.case(tmp_path), tmp_path/"attempts", [])
    verify_loop_response(result, **options, freeze=True)
    assert result["result"]["claims"][0]["text"] == "5"


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_policy_uses_the_same_resolved_owner_base_as_source_checks(tmp_path, kind):
    real, links = tmp_path/"real", tmp_path/"links"
    links.mkdir()
    payload, specification, expected, _, _, owner_path, document = contract.case(real)
    alias = links/("owner.json" if kind == "file" else "owner-home")
    try:
        alias.symlink_to(owner_path if kind == "file" else real, target_is_directory=kind == "directory")
    except OSError:
        pytest.skip("owner symlink creation is not available")
    selected = alias if kind == "file" else alias/"owner.json"
    owner = OwnerFile(selected, clock=lambda: 1000)
    owner.read_task()
    actual = select_executor_policy(payload, specification, selected)
    assert actual == expected and actual["owner_base"] == str(owner.path.parent)
    check_current_executor_policy(actual, payload, specification, owner_path=selected, owner_document=document)


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_owner_alias_keeps_repair_inspection_and_cancellation(tmp_path, kind):
    from test_task_swarm_loop_executor_runtime import setup_executor, interrupted
    from task_swarm.closed_loop_cancellation import cancel_closed_loop
    from task_swarm.repair_planning import inspect_repair
    real, links = tmp_path/"real", tmp_path/"links"
    links.mkdir()
    setup = setup_executor(real)
    alias = links/("owner.json" if kind == "file" else "owner-home")
    try:
        alias.symlink_to(setup[0] if kind == "file" else real, target_is_directory=kind == "directory")
    except OSError:
        pytest.skip("owner symlink creation is not available")
    selected = alias if kind == "file" else alias/"owner.json"
    interrupted(setup)
    assert inspect_repair(selected, setup[1], clock=lambda: 1000) == inspect_repair(setup[0], setup[1], clock=lambda: 1000)
    cancelled = cancel_closed_loop(selected, setup[1], clock=lambda: 1000)
    assert cancelled == cancel_closed_loop(setup[0], setup[1], clock=lambda: 1000)
