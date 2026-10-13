"""Dependency refusals settle real executor attempts without releasing DocB."""
from __future__ import annotations

import json
import sqlite3

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest environment")

from test_task_swarm_loop_executor_runtime import execute, run_directory, setup_executor
from task_swarm.codex import _same_process
from task_swarm.protocol import SwarmError


def change_prerequisite(script, statement):
    marker = "output = pathlib.Path"
    assert script.count(marker) == 1
    return script.replace(marker, 'if core["role"] == "prerequisite_review":\n'
                          '    for item in result["validations"]:\n'
                          f"        {statement}\n" + marker)


def attempts(directory):
    with sqlite3.connect(directory / "execution.sqlite") as db:
        db.row_factory = sqlite3.Row
        rows = {row["job_id"]: dict(row) for row in db.execute("SELECT * FROM attempts")}
    assert set(rows) == {"r0-doc-a", "r0-prerequisite"}
    for row in rows.values():
        identity = json.loads(row["identity_json"])
        assert identity["kind"] == "process"
        assert not _same_process(identity["pid"], identity["created_at"])
    assert len(list(directory.rglob("child-input.bin"))) == 2
    assert not (directory / "r0-doc-b-input.json").exists()
    assert not (directory / "receipt.json").exists()
    assert not (directory / "learning.json").exists()
    return rows


def test_invalid_real_prerequisite_evidence_settles_its_lease(tmp_path):
    # This index satisfies the response schema but does not name an actual claim.
    setup = setup_executor(tmp_path, dependency=True,
        child=lambda script: change_prerequisite(script, 'item["evidence"][0]["claim_index"] = 1'))
    owner_before = setup[0].read_bytes()
    with pytest.raises(SwarmError, match="LOOP_PREREQUISITE_EVIDENCE"):
        execute(setup)
    directory = run_directory(setup)
    rows = attempts(directory)
    review = rows["r0-prerequisite"]
    assert review["state"] == "failed"
    assert review["retryable"] == 0
    assert review["reason"] == "LOOP_PREREQUISITE_EVIDENCE"
    with sqlite3.connect(directory / "execution.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM run_dependency_stages").fetchone()[0] == 0
    assert setup[0].read_bytes() == owner_before


def test_real_blocked_stage_never_accepts_a_receipt_anchor(tmp_path):
    setup = setup_executor(tmp_path, dependency=True,
        child=lambda script: change_prerequisite(script, 'item.update(status="failed", evidence=[])'))
    owner_before = setup[0].read_bytes()
    result = execute(setup)
    assert result["status"] == "blocked" and result["receipt"] is None
    directory = run_directory(setup)
    rows = attempts(directory)
    assert rows["r0-prerequisite"]["state"] == "reported"
    before = {str(path.relative_to(directory)): path.read_bytes()
              for path in directory.rglob("child-input.bin")}
    # Neither a current nor an expired objective can turn an absent receipt
    # into an anchored historical result. Owner and actors are still current.
    for now in (1000, setup[3]["objective"]["budget"]["deadline"] + 1):
        with pytest.raises(SwarmError, match="RUN_REPLAY_MISSING"):
            execute(setup, expected_receipt_sha256="0" * 64, clock=lambda: now)
    assert attempts(directory) == rows
    assert before == {str(path.relative_to(directory)): path.read_bytes()
                      for path in directory.rglob("child-input.bin")}
    assert setup[0].read_bytes() == owner_before
