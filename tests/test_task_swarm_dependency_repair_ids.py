"""Dependency repair names remain bound across planning, claims, and restart."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest job")

from test_task_swarm_dependency_loop import setup_dependency, Calculation
from test_task_swarm_closed_loop import execute
from task_swarm.closed_loop import execute_closed_loop
from task_swarm.owner_file import OwnerFile
from task_swarm.protocol import SwarmError, digest
from task_swarm.state import SwarmState
from task_swarm.task_runner import read_json


def named_setup(root, length, prefix, reverse):
    setup = setup_dependency(root)
    setup[4]["jobs"][1]["job_id"] = prefix * length
    if reverse:
        setup[4]["jobs"].reverse()
    return setup


def expected_repair(length, prefix):
    # The prerequisite is named "speed". Its lexical position determines B's
    # full initial-work ordinal, even though only B is selected for repair.
    return "r1-repair-" + (prefix * length if length <= 49 else "0" if prefix == "a" else "1")


def state_for(owner_path, input_path):
    owner = OwnerFile(owner_path, clock=lambda: 1000)
    payload = read_json(Path(input_path))
    run = "task-run-" + digest([payload["task_id"], payload["revision"]])[:32]
    directory = owner.storage()["root"] / run
    return run, directory, SwarmState(directory / "execution.sqlite", owner.read_task, clock=lambda: 1000)


def assert_repaired(result, inputs, claims, name, directory):
    assert result["receipt"]["review_passed"]
    assert result["receipt"]["budget"]["attempts_used"] == 6
    assert result["receipt"]["budget"]["remaining_attempts"] == 0
    repair = next(value for value in inputs if value.get("job_id") == name)
    original = next(value for value in inputs if "prerequisite" in value and value["round"] == 0)
    assert repair["prerequisite"] == original["prerequisite"]
    assert repair["prerequisite"]["report"]["claims"][0]["text"] == "speed=42"
    lease = next(value for value in claims if value["job_id"] == name)
    assert lease["delivered_input_digest"] == lease["payload_digest"] == digest(repair)
    assert lease["dependencies"] == ["r0-speed"]
    assert read_json(directory / "repair-proposal.json")["jobs"][0]["job_id"] == name[3:]
    assert read_json(directory / "repair-impact.json")["assignments"][0]["origin_job_id"] == original["job_id"]


@pytest.mark.parametrize("length", [49, 50, 56])
@pytest.mark.parametrize("prefix", ["a", "z"])
@pytest.mark.parametrize("reverse", [False, True])
def test_dependency_repair_id_and_claim_keep_delivery_evidence(tmp_path, monkeypatch, length, prefix, reverse):
    setup = named_setup(tmp_path, length, prefix, reverse)
    original_claim, claims = SwarmState.claim, []
    def capture(*args, **kwargs):
        lease = original_claim(*args, **kwargs)
        if lease is not None:
            claims.append(copy.deepcopy(lease))
        return lease
    monkeypatch.setattr(SwarmState, "claim", capture)
    backend = Calculation(setup[3], setup[6], wrong=True)
    result = execute(setup, backend)
    run, directory, state = state_for(setup[0], setup[1])
    assert_repaired(result, backend.inputs, claims, expected_repair(length, prefix), directory)
    before = state.snapshot(run)
    assert len(backend.inputs) == 6
    assert all(job["attempt_count"] == 1 for job in before["jobs"].values())
    assert execute(setup, backend, expected_receipt_sha256=result["receipt_sha256"])["duplicate"]
    assert state.snapshot(run) == before and len(backend.inputs) == 6


@pytest.mark.parametrize("bad_name", ["r1-repair-0", "r1-repair-speed", "r1-repair-2"])
def test_dependency_extension_refuses_wrong_initial_origin_or_ordinal(tmp_path, monkeypatch, bad_name):
    setup = named_setup(tmp_path, 56, "z", True)
    original_extend, cuts = SwarmState.extend_run, []
    def wrong_origin(state, run, extension):
        altered = copy.deepcopy(extension)
        correct = next(job["job_id"] for job in altered["jobs"] if job["kind"] == "work")
        for job in altered["jobs"]:
            if job["job_id"] == correct:
                job["job_id"] = bad_name
            job["dependencies"] = [bad_name if name == correct else name for name in job["dependencies"]]
        before = state.snapshot(run)
        with pytest.raises(SwarmError, match="LOOP_RELEASE_INVALID"):
            original_extend(state, run, altered)
        assert state.snapshot(run) == before
        cuts.append(before)
        return original_extend(state, run, extension)
    monkeypatch.setattr(SwarmState, "extend_run", wrong_origin)
    backend = Calculation(setup[3], setup[6], wrong=True)
    assert execute(setup, backend)["receipt"]["review_passed"]
    assert len(cuts) == 1 and len(backend.inputs) == 6


def child(root, mode):
    return subprocess.run([sys.executable, str(Path(__file__).resolve()), str(root), mode],
                          capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize("length,prefix", [(49, "z"), (50, "a"), (56, "z")])
def test_fresh_process_repair_keeps_release_and_anchored_replay(tmp_path, length, prefix):
    setup = named_setup(tmp_path, length, prefix, True)
    config = {"owner": str(setup[0]), "input": str(setup[1]), "plan": setup[4],
              "actors": setup[5], "measure": setup[6]}
    (tmp_path / "control.json").write_text(json.dumps(config), encoding="utf-8")
    stopped = child(tmp_path, "release")
    assert stopped.returncode == 73, stopped.stderr
    run, directory, state = state_for(setup[0], setup[1])
    before = state.snapshot(run)
    assert before["jobs"]["r0-" + prefix * length]["attempt_count"] == 0
    resumed = child(tmp_path, "resume")
    assert resumed.returncode == 0, resumed.stderr
    output = read_json(tmp_path / "result.json", 1024 * 1024)
    assert_repaired(output["result"], output["inputs"], output["claims"],
                    expected_repair(length, prefix), directory)
    assert len(output["inputs"]) == 4
    after = state.snapshot(run)
    assert after["jobs"]["r0-speed"]["accepted"] == before["jobs"]["r0-speed"]["accepted"]
    assert all(job["attempt_count"] == 1 for job in after["jobs"].values())
    replay = child(tmp_path, "replay")
    assert replay.returncode == 0, replay.stderr
    output = read_json(tmp_path / "result.json", 1024 * 1024)
    assert output["result"]["duplicate"] and output["inputs"] == output["claims"] == []
    assert state.snapshot(run) == after


def _child(root, mode):
    config = read_json(root / "control.json")
    payload = read_json(Path(config["input"]))
    backend = Calculation(payload, config["measure"], wrong=True)
    claims, original_claim = [], SwarmState.claim
    def capture(*args, **kwargs):
        lease = original_claim(*args, **kwargs)
        if lease is not None:
            claims.append(lease)
        return lease
    SwarmState.claim = capture
    if mode == "release":
        original_commit = SwarmState.commit_dependency_stage
        def stop(*args, **kwargs):
            original_commit(*args, **kwargs)
            os._exit(73)
        SwarmState.commit_dependency_stage = stop
    options = {"resume_finalization": True} if mode == "resume" else {}
    if mode == "replay":
        options["expected_receipt_sha256"] = read_json(root / "result.json", 1024 * 1024)["result"]["receipt_sha256"]
    result = execute_closed_loop(config["owner"], config["input"], config["plan"], backend,
        worker_actors=config["actors"], clock=lambda: 1000, **options)
    (root / "result.json").write_text(json.dumps({"result": result, "inputs": backend.inputs,
                                                 "claims": claims}), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(_child(Path(sys.argv[1]), sys.argv[2]))
