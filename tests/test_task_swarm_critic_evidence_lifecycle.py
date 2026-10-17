"""The real new writer pins contract 2 across finalization and readback."""
import copy
import json
from pathlib import Path
import sqlite3
import sys

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest job")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from task_swarm import closed_loop as coordinator
from task_swarm.closed_loop_contract import evidence_version
from task_swarm.protocol import SwarmError, canonical, digest
from task_swarm.task_runner import read_json
from test_task_swarm_closed_loop import MeasuredBackend, execute, setup_loop
from test_task_swarm_learning_reuse import ReadingBackend, allow, run, setup_reuse


def run_directory(setup):
    return Path(setup[2]["storage"]["root"]) / (
        "task-run-" + digest([setup[3]["task_id"], setup[3]["revision"]])[:32])


def test_new_writer_pins_v2_and_completed_readback_keeps_it(tmp_path):
    setup = setup_loop(tmp_path)
    backend = MeasuredBackend(setup[3], setup[6])
    result = execute(setup, backend)
    directory = run_directory(setup)
    template = read_json(directory / "r0-critic-template.json")
    plan = read_json(directory / "plan.json")
    assert evidence_version(plan, template) == 2
    assert template["required_evidence_jobs"]["A1"] == ["r0-speed"]
    assert set(template["required_evidence_jobs"]["I"]) == {"r0-speed", "r0-uncertainty"}
    assert result["receipt"]["version"] == 2
    assert result["receipt"]["coordinator"] == "closed_loop_v2"
    with sqlite3.connect(directory / "execution.sqlite") as db:
        checkpoint = json.loads(db.execute("SELECT checkpoint_json FROM run_finalizations").fetchone()[0])
    assert checkpoint["version"] == 2
    calls = len(backend.inputs)
    replay = execute(setup, backend, expected_receipt_sha256=result["receipt_sha256"])
    assert replay["duplicate"] and replay["receipt_sha256"] == result["receipt_sha256"]
    assert len(backend.inputs) == calls


def test_wrong_leaf_is_rejected_even_with_valid_report_hashes(tmp_path):
    setup = setup_loop(tmp_path)

    class WrongLeaf(MeasuredBackend):
        def review(self, delivered, *args, **kwargs):
            result = super().review(delivered, *args, **kwargs)
            target = next(v for v in result["result"]["validations"] if v["criterion_id"] == "A1")
            target.update(status="passed", gap_reason=None, source_spans=[],
                          evidence=[{"job_id": "r0-uncertainty", "claim_index": 0}])
            return result

    with pytest.raises(SwarmError, match="LOOP_CRITIC_ASSIGNMENT"):
        execute(setup, WrongLeaf(setup[3], setup[6]))
    assert not (run_directory(setup) / "receipt.json").exists()
    with sqlite3.connect(run_directory(setup) / "execution.sqlite") as db:
        assert db.execute("SELECT count(*) FROM jobs WHERE state='accepted'").fetchone()[0] == 0


def test_missing_common_assignment_refuses_before_claiming_run(tmp_path):
    setup = setup_loop(tmp_path)
    setup[4]["jobs"][1]["criterion_ids"].remove("R")
    with pytest.raises(SwarmError, match="LOOP_COMMON_CRITERIA_COVERAGE"):
        execute(setup, MeasuredBackend(setup[3], setup[6]))
    assert not run_directory(setup).exists()


def test_v2_checkpoint_cannot_opt_into_v1_finalization(tmp_path, monkeypatch):
    setup = setup_loop(tmp_path)
    original = coordinator.make_checkpoint

    def pause(*args, **kwargs):
        original(*args, **kwargs)
        raise SwarmError("TEST_CHECKPOINT_PAUSE", "test fixture interruption")

    monkeypatch.setattr(coordinator, "make_checkpoint", pause)
    backend = MeasuredBackend(setup[3], setup[6])
    with pytest.raises(SwarmError, match="TEST_CHECKPOINT_PAUSE"):
        execute(setup, backend)
    directory = run_directory(setup)
    # A checkpoint is generic stored JSON. Its policy label must agree with the
    # independently pinned runtime plan/template, not select a weaker branch.
    with sqlite3.connect(directory / "execution.sqlite") as db:
        row = db.execute("SELECT checkpoint_json FROM run_finalizations").fetchone()[0]
        checkpoint = json.loads(row)
        checkpoint["version"] = 1
        db.execute("UPDATE run_finalizations SET checkpoint_json=?", (canonical(checkpoint),))
    calls = len(backend.inputs)
    with pytest.raises(SwarmError, match="LOOP_EVIDENCE_POLICY"):
        execute(setup, backend, resume_finalization=True)
    assert len(backend.inputs) == calls and not (directory / "receipt.json").exists()
    with sqlite3.connect(directory / "execution.sqlite") as db:
        assert db.execute("SELECT count(*) FROM jobs WHERE state='accepted'").fetchone()[0] == 0


def test_learning_origin_and_consumer_both_keep_v2(tmp_path):
    reuse, arguments, plan, payload, document, origin = setup_reuse(tmp_path)
    origin_receipt = read_json(run_directory(origin) / "receipt.json")
    assert origin_receipt["version"] == 2
    result = run(reuse, plan, ReadingBackend(), allow(reuse))
    assert result["receipt"]["version"] == 2
    assert result["candidate"]["claims"][0]["claim"]["text"] == "Use measured memory budget 8."
