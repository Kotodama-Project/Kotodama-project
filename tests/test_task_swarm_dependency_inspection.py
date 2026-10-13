"""Inspect dependency state without silently adding missing original schema."""
from contextlib import closing
from pathlib import Path
import sqlite3
import sys

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest job")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))

from task_swarm.protocol import SwarmError
from task_swarm.repair_planning import inspect_repair
from task_swarm.state import SwarmState
from test_task_swarm_closed_loop import execute, setup_loop, MeasuredBackend
from test_task_swarm_dependency_loop import setup_dependency, Calculation
from test_task_swarm_repair_planning import inspection_files


@pytest.mark.parametrize("damage", ["missing_table", "missing_column"])
def test_dependency_inspection_rejects_missing_original_stage_schema_before_initializer(tmp_path, monkeypatch, damage):
    setup = setup_dependency(tmp_path)
    result = execute(setup, Calculation(setup[3], setup[6], wrong=True))
    directory = setup[0].parent / "operations" / result["receipt"]["run_id"]
    with closing(sqlite3.connect(directory / "execution.sqlite")) as conn:
        conn.execute("DROP TABLE run_dependency_stages")
        if damage == "missing_column":
            conn.execute("CREATE TABLE run_dependency_stages (run_id TEXT PRIMARY KEY)")
        conn.commit()
    before = inspection_files(directory)
    initialized = []
    original = SwarmState.__init__
    def observe(*args, **kwargs):
        initialized.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(SwarmState, "__init__", observe)
    with pytest.raises(SwarmError, match="LOOP_REPAIR_STATE"):
        inspect_repair(setup[0], setup[1], clock=lambda: 1000)
    assert initialized == []
    assert inspection_files(directory) == before


def test_normal_inspection_does_not_require_dependency_schema(tmp_path):
    setup = setup_loop(tmp_path)
    result = execute(setup, MeasuredBackend(setup[3], setup[6]))
    directory = setup[0].parent / "operations" / result["receipt"]["run_id"]
    with closing(sqlite3.connect(directory / "execution.sqlite")) as conn:
        conn.execute("DROP TABLE run_dependency_stages")
        conn.commit()
    before = inspection_files(directory)
    value = inspect_repair(setup[0], setup[1], clock=lambda: 1000)
    assert value["admitted"] is False and value["impact"]["version"] == 1
    assert inspection_files(directory) == before
