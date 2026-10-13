"""Stable private copies survive finite WAL churn and refuse corrupt scalars."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import queue
import sqlite3
import subprocess
import sys

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest environment")

from test_task_swarm_learning_readonly import files, origin_case
from task_swarm import learning_reuse, repair_planning
from task_swarm.learning_reuse import propose_learning
from task_swarm.protocol import SwarmError


@contextmanager
def concurrent_wal(database, mode):
    """Only this owned worker connects the original; production copies bytes."""
    commands, answers = queue.Queue(), queue.Queue()
    def worker():
        db = None
        try:
            if mode != "reader":
                db = sqlite3.connect(database)
                db.execute("PRAGMA wal_autocheckpoint=0")
                db.execute("CREATE TABLE copy_race_marker(value INTEGER)")
                db.execute("INSERT INTO copy_race_marker VALUES (0)")
                db.commit()
            answers.put(None)
            while True:
                command = commands.get()
                if command == "stop":
                    return
                try:
                    if mode == "reader":
                        assert db is None
                        db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
                        assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
                    elif mode == "checkpoint":
                        assert db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0
                    elif mode == "close":
                        db.close()
                        db = None
                    elif mode == "semantic":
                        db.execute("UPDATE jobs SET reason='changed during copy'")
                        db.commit()
                    else:
                        db.execute("INSERT INTO copy_race_marker VALUES (1)")
                        db.commit()
                    answers.put(None)
                except BaseException as error:
                    answers.put(error)
        finally:
            if db is not None:
                db.close()
    def receive():
        result = answers.get(timeout=10)
        if result is not None:
            raise result
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(worker)
        receive()
        def change():
            commands.put("change")
            receive()
        try:
            yield change
        finally:
            commands.put("stop")
            future.result(timeout=10)


def during_copy(monkeypatch, database, action, *, repeat=False, enabled=lambda: True):
    """Run a real concurrent SQLite action after sidecars were enumerated."""
    original_open, original_cut = Path.open, repair_planning._inspection_cut
    active, actions, cuts, failures = [], [], [], []
    def cut(path, destination, **kwargs):
        armed = [True]
        active.append(armed)
        cuts.append(destination)
        try:
            return original_cut(path, destination, **kwargs)
        except (SwarmError, FileNotFoundError) as error:
            failures.append(error)
            raise
        finally:
            active.pop()
    class Stream:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            self.stream.__enter__()
            return self
        def __exit__(self, *args):
            return self.stream.__exit__(*args)
        def __getattr__(self, name):
            return getattr(self.stream, name)
        def read(self, size=-1):
            if active and active[-1][0] and enabled() and (repeat or not actions):
                active[-1][0] = False
                actions.append(True)
                action()
            return self.stream.read(size)
    def opened(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return Stream(stream) if path == database and args == ("rb",) else stream
    monkeypatch.setattr(Path, "open", opened)
    monkeypatch.setattr(repair_planning, "_inspection_cut", cut)
    return actions, cuts, failures


@pytest.mark.parametrize("mode", ["reader", "checkpoint", "close"])
def test_copy_retries_real_concurrent_wal_lifecycle_without_original_writes(tmp_path, monkeypatch, mode):
    owner, file, anchor, index, run = origin_case(tmp_path)
    database = run / "execution.sqlite"
    post_change = []
    with concurrent_wal(database, mode) as mutate:
        before_main = database.read_bytes()
        def action():
            mutate()
            # Last-close unlink can be delayed by a Windows read handle.
            # Its committed checkpoint still changes the original main DB.
            if mode in {"checkpoint", "close"}:
                assert database.read_bytes() != before_main
            post_change.append(files(tmp_path))
        actions, cuts, failures = during_copy(monkeypatch, database, action)
        result = propose_learning(owner, file, anchor, index)
        assert result["origin_receipt_sha256"] == anchor
        assert len(actions) == len(failures) == 1 and len(cuts) >= 2
        assert files(tmp_path) == post_change[0]
    assert all(not path.exists() for path in cuts)


def test_continuous_copy_churn_is_bounded_and_cleans_every_private_trial(tmp_path, monkeypatch):
    owner, file, anchor, index, run = origin_case(tmp_path)
    database = run / "execution.sqlite"
    post_change = []
    with concurrent_wal(database, "churn") as mutate:
        def action():
            mutate()
            post_change.append(files(tmp_path))
        actions, cuts, failures = during_copy(monkeypatch, database, action, repeat=True)
        with pytest.raises(SwarmError, match="RUN_ARTIFACT_CHANGED"):
            propose_learning(owner, file, anchor, index)
        assert len(actions) == len(cuts) == len(failures) == 3
        assert len(set(cuts)) == 3
        assert files(tmp_path) == post_change[-1]
    assert all(not path.exists() for path in cuts)


def test_retry_does_not_admit_changed_execution_rows(tmp_path, monkeypatch):
    owner, file, anchor, index, run = origin_case(tmp_path)
    ready, post_change = [], []
    original_proposal = learning_reuse._proposal
    def proposal(*args):
        result = original_proposal(*args)
        ready.append(True)
        return result
    monkeypatch.setattr(learning_reuse, "_proposal", proposal)
    with concurrent_wal(run / "execution.sqlite", "semantic") as mutate:
        def action():
            mutate()
            post_change.append(files(tmp_path))
        actions, cuts, failures = during_copy(monkeypatch, run / "execution.sqlite", action, enabled=lambda: bool(ready))
        with pytest.raises(SwarmError, match="FINALIZATION_STATE_CHANGED"):
            propose_learning(owner, file, anchor, index)
        assert ready and len(actions) == len(failures) == 1
        assert files(tmp_path) == post_change[0]
    assert all(not path.exists() for path in cuts)


@pytest.mark.parametrize("column,value", [
    ("deadline", None), ("deadline", "not a number"), ("deadline", float("inf")),
    ("attempt_budget", None), ("attempt_budget", 2.5),
    ("concurrency", None), ("concurrency", -1), ("created_at", None),
])
@pytest.mark.parametrize("cli", [False, True])
def test_invalid_core_scalars_are_typed_before_private_state_use(tmp_path, column, value, cli):
    owner, file, anchor, index, run = origin_case(tmp_path)
    database = run / "execution.sqlite"
    with closing(sqlite3.connect(database)) as db:
        db.execute("CREATE TABLE unconstrained_runs AS SELECT * FROM runs")
        db.execute("DROP TABLE runs")
        db.execute("ALTER TABLE unconstrained_runs RENAME TO runs")
        db.execute("UPDATE runs SET " + column + "=?", (value,))
        db.commit()
        assert db.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        assert len(db.execute("PRAGMA table_info(runs)").fetchall()) == 8
    before = files(tmp_path)
    if cli:
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "runtime"))
        result = subprocess.run([sys.executable, "-B", "-m", "task_swarm.learning_reuse", "propose",
            "--owner", str(owner), "--input", str(file), "--anchor", anchor, "--claim-index", str(index)],
            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 2 and result.stdout == "" and "Traceback" not in result.stderr
        assert json.loads(result.stderr)["error"] == "LOOP_REPAIR_STATE"
    else:
        with pytest.raises(SwarmError, match="LOOP_REPAIR_STATE"):
            propose_learning(owner, file, anchor, index)
    assert files(tmp_path) == before
