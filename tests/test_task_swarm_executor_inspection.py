"""The executable reader checks live state while keeping original DBs unopened."""
from pathlib import Path
import sqlite3
import sys

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest job")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))

from task_swarm import loop_executor, loop_executor_runtime
from task_swarm.closed_loop_cancellation import cancel_closed_loop
from task_swarm.protocol import SwarmError
from task_swarm.repair_planning import inspect_repair
from task_swarm.task_runner import read_json
from test_task_swarm_loop_executor_runtime import setup_executor, interrupted, run_directory
from test_task_swarm_repair_planning import inspection_files


def test_executor_inspection_opens_only_private_sqlite_copies(tmp_path, monkeypatch):
    setup = setup_executor(tmp_path)
    interrupted(setup)
    directory = run_directory(setup)
    before = inspection_files(directory)
    connected = []
    original = sqlite3.connect

    def connect(database, *args, **kwargs):
        connected.append(str(database))
        assert str(directory) not in str(database)
        return original(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    value = inspect_repair(setup[0], setup[1], clock=lambda: 1000)
    assert value["admitted"] is False and connected
    assert inspection_files(directory) == before


@pytest.mark.parametrize("change", ["cancel", "deadline", "runtime_input"])
def test_executor_last_policy_is_followed_by_live_cut_and_proof_checks(tmp_path, monkeypatch, change):
    setup = setup_executor(tmp_path)
    interrupted(setup)
    directory = run_directory(setup)
    now = [1000]
    calls = []
    real = loop_executor_runtime.check_current_executor_policy

    def observed(*args, **kwargs):
        value = real(*args, **kwargs)
        calls.append(1)
        return value

    monkeypatch.setattr(loop_executor_runtime, "check_current_executor_policy", observed)
    monkeypatch.setattr(loop_executor, "check_current_executor_policy", observed)
    inspect_repair(setup[0], setup[1], clock=lambda: now[0])
    last = len(calls)
    assert last > 0
    calls.clear()
    changed_files = []

    def mutate(*args, **kwargs):
        value = observed(*args, **kwargs)
        if len(calls) == last:
            if change == "cancel":
                cancel_closed_loop(setup[0], setup[1], clock=lambda: now[0])
            elif change == "deadline":
                now[0] = setup[3]["objective"]["budget"]["deadline"] + 1
                assert now[0] < setup[2]["binding"]["expires_at"]
            else:
                response = read_json(directory / "r0-doc-a-result.json")
                target = Path(response["receipt"]["runtime"]["paths"]["input"])
                target.write_bytes(target.read_bytes() + b"\n")
            changed_files.append(inspection_files(directory))
        return value

    monkeypatch.setattr(loop_executor_runtime, "check_current_executor_policy", mutate)
    monkeypatch.setattr(loop_executor, "check_current_executor_policy", mutate)
    expected = {"cancel": "RUN_CANCELLED", "deadline": "OBJECTIVE_DEADLINE_INVALID|DEADLINE_EXPIRED",
                "runtime_input": "RUN_RUNTIME_ARTIFACT_CHANGED"}[change]
    with pytest.raises(SwarmError, match=expected):
        inspect_repair(setup[0], setup[1], clock=lambda: now[0])
    assert len(calls) == last and len(changed_files) == 1
    assert inspection_files(directory) == changed_files[0]
