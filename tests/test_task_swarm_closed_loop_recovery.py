"""Actual process interruption and same-run, no-dispatch finalization."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest job")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from task_swarm import closed_loop_recovery
from task_swarm.closed_loop import execute_closed_loop
from task_swarm.owner_file import OwnerFile
from task_swarm.protocol import SwarmError, canonical, digest
from task_swarm.state import SwarmState
from task_swarm.task_runner import read_json
from test_task_swarm_closed_loop import MeasuredBackend, repair_for, setup_loop


def setup_case(tmp_path, *, unresolved=False):
    setup = setup_loop(tmp_path)
    owner, payload_file, _, payload, plan, actors, measure = setup
    config = {"owner": str(owner), "input": str(payload_file), "plan": plan,
              "actors": actors, "measure": measure, "unresolved": unresolved}
    (tmp_path / "case.json").write_text(canonical(config), encoding="utf-8")
    return config


def directory(config):
    payload = read_json(Path(config["input"]))
    run_id = "task-run-" + digest([payload["task_id"], payload["revision"]])[:32]
    return Path(config["owner"]).parent / "operations" / run_id


def snapshot(config):
    path = directory(config)
    owner = OwnerFile(config["owner"], clock=lambda: 1000)
    return SwarmState(path / "execution.sqlite", owner.read_task, clock=lambda: 1000).snapshot(path.name)


def child(tmp_path, mode, *, now=1000, anchor=None):
    command = [sys.executable, str(Path(__file__).resolve()), "child", str(tmp_path), mode, str(now)]
    if anchor is not None:
        command.append(anchor)
    return subprocess.run(command, capture_output=True, text=True, timeout=30)


def result(tmp_path):
    return read_json(tmp_path / "result.json")


def _child(tmp_path, mode, now, anchor):
    config = read_json(tmp_path / "case.json")
    payload = read_json(Path(config["input"]))
    if config.get("reuse_context"):
        from test_task_swarm_learning_reuse import ReadingBackend
        backend = ReadingBackend()
    else:
        backend = MeasuredBackend(payload, config["measure"])
    if mode in {"resume", "replay", "hold"}:
        class NeverDispatch:
            synthetic = True

            def produce(self, *_args, **_kwargs):
                (tmp_path / "UNAUTHORIZED_CALL").write_text("called")
                raise AssertionError("finalization must never invoke a backend")

            review = produce

        backend = NeverDispatch()
    if mode in {"checkpoint", "hold"}:
        if mode == "checkpoint":
            original = SwarmState.prepare_finalization

            def prepare(*args, **kwargs):
                original(*args, **kwargs)
                os._exit(73)

            SwarmState.prepare_finalization = prepare
        else:
            original = closed_loop_recovery.finalize

            def hold(*args, **kwargs):
                (tmp_path / "LOCK_HELD").write_text("ready")
                while not (tmp_path / "RELEASE").exists():
                    time.sleep(.01)
                return original(*args, **kwargs)

            # execute_closed_loop imports the function directly.
            import task_swarm.closed_loop as coordinator
            coordinator.finalize = hold
    if mode == "accept":
        original = SwarmState.accept

        def accept(*args, **kwargs):
            original(*args, **kwargs)
            os._exit(73)

        SwarmState.accept = accept
    if mode == "preimage":
        original = SwarmState.pin_final_receipt

        def pin(*args, **kwargs):
            original(*args, **kwargs)
            os._exit(73)

        SwarmState.pin_final_receipt = pin
    if mode in {"candidate", "execution", "torn", "staged"}:
        original = closed_loop_recovery.write_json

        def write(path, value):
            target = ".receipt-pending.json" if mode in {"torn", "staged"} else mode + ".json"
            if path.name == target:
                if mode == "torn":
                    # Retain the malformed *published* receipt refusal fixture.
                    (path.parent / "receipt.json").write_bytes(b'{"torn":')
                else:
                    original(path, value)
                os._exit(73)
            return original(path, value)

        closed_loop_recovery.write_json = write
    if mode == "before_checkpoint":
        original = SwarmState.report

        def report(*args, **kwargs):
            value = original(*args, **kwargs)
            if args[2].endswith("r1-critic"):
                os._exit(73)
            return value

        SwarmState.report = report
    if mode == "lease":
        def leased(*args, **kwargs):
            os._exit(73)
        backend.produce = leased
    if mode == "half_extension":
        original = SwarmState.extend_run

        def extend(*args, **kwargs):
            original(*args, **kwargs)
            os._exit(73)

        SwarmState.extend_run = extend
    try:
        completed = execute_closed_loop(config["owner"], config["input"], config["plan"], backend,
            worker_actors=config["actors"], clock=lambda: now,
            repair_planner=None if config["unresolved"] else repair_for(payload),
            expected_receipt_sha256=anchor, resume_finalization=mode in {"resume", "hold"},
            reuse_context=None if mode in {"resume", "hold"} else config.get("reuse_context"))
        (tmp_path / "result.json").write_text(canonical(completed), encoding="utf-8")
        return 0
    except SwarmError as error:
        (tmp_path / "result.json").write_text(canonical({"error": error.code}), encoding="utf-8")
        return 2


@pytest.mark.parametrize("phase", ["checkpoint", "accept", "preimage", "candidate", "execution", "staged"])
def test_real_process_crash_resumes_only_finalization(tmp_path, phase):
    config = setup_case(tmp_path)
    assert child(tmp_path, phase).returncode == 73
    before = snapshot(config)
    assert before["budget"]["attempts_used"] == 5
    started = time.monotonic()
    recovered = child(tmp_path, "resume")
    assert recovered.returncode == 0, recovered.stderr
    output = result(tmp_path)
    assert output["recovered_finalization"] is True
    assert output["candidate"]["status"] == "needs_owner_review"
    assert output["learning_candidate"]["status"] == "unadopted"
    assert output["receipt"]["rounds"] == 2
    assert output["receipt"]["budget"] == before["budget"]
    assert output["receipt"]["timing"]["after_checkpoint_seconds"] is None
    assert not (tmp_path / "UNAUTHORIZED_CALL").exists()
    after = snapshot(config)
    for job, old in before["jobs"].items():
        current = after["jobs"][job]
        for key in ("token", "attempt", "epoch", "identity", "worker_ref", "result_digest", "created_at"):
            assert current["current_attempt"][key] == old["current_attempt"][key]
        if old["state"] == "accepted":
            assert current == old
    assert after["jobs"]["r0-critic"]["state"] == "reported"
    assert time.monotonic() - started < 30
    assert child(tmp_path, "resume").returncode == 2
    assert result(tmp_path)["error"] == "RUN_REPLAY_ANCHOR_REQUIRED"
    assert child(tmp_path, "replay", anchor=output["receipt_sha256"]).returncode == 0
    assert result(tmp_path)["duplicate"] is True


@pytest.mark.parametrize("phase", ["lease", "before_checkpoint", "half_extension", "torn"])
def test_unsupported_crash_prefix_never_dispatches_or_changes_progress(tmp_path, phase):
    config = setup_case(tmp_path)
    assert child(tmp_path, phase).returncode == 73
    before = snapshot(config)
    answer = child(tmp_path, "resume")
    assert answer.returncode == 2, answer.stderr
    assert result(tmp_path)["error"] in {"RUN_RECOVERY_REQUIRED", "RUN_REPLAY_ANCHOR_REQUIRED"}
    assert snapshot(config) == before
    assert not (tmp_path / "UNAUTHORIZED_CALL").exists()
    if phase == "torn":
        assert (directory(config) / "receipt.json").read_bytes() == b'{"torn":'


def test_failed_critic_remains_unresolved_without_learning(tmp_path):
    config = setup_case(tmp_path, unresolved=True)
    assert child(tmp_path, "checkpoint").returncode == 73
    assert child(tmp_path, "resume").returncode == 0
    output = result(tmp_path)
    assert output["candidate"]["status"] == "unresolved"
    assert output["candidate"]["stop_reason"] == "repair_plan_required"
    assert output["learning_candidate"] is None
    assert output["receipt"]["budget"]["attempts_used"] == 3
    assert snapshot(config)["counts"]["accepted"] == 0


@pytest.mark.parametrize("change", ["owner", "actor", "source", "revision", "expired", "cancelled"])
def test_current_scope_is_rechecked_before_accept_or_write(tmp_path, change):
    config = setup_case(tmp_path)
    assert child(tmp_path, "checkpoint").returncode == 73
    path = directory(config)
    with sqlite3.connect(path / "execution.sqlite") as conn:
        before = list(conn.execute("SELECT * FROM attempts ORDER BY token"))
    owner = read_json(Path(config["owner"]))
    if change == "owner":
        owner["binding"]["owner_ref"] += "-changed"
    elif change == "actor":
        owner["actors"]["worker-a"]["epoch"] += 1
    elif change == "revision":
        owner["binding"]["revision"] += 1
    elif change == "source":
        Path(config["input"]).write_text(Path(config["input"]).read_text() + " ")
    if change in {"owner", "actor", "revision"}:
        Path(config["owner"]).write_text(canonical(owner), encoding="utf-8")
    if change == "cancelled":
        import threading
        event = threading.Event()
        event.set()
        with pytest.raises(SwarmError, match="RUN_CANCELLED"):
            execute_closed_loop(config["owner"], config["input"], config["plan"],
                MeasuredBackend(read_json(Path(config["input"])), config["measure"]),
                worker_actors=config["actors"], cancel_event=event, clock=lambda: 1000,
                resume_finalization=True)
    else:
        assert child(tmp_path, "resume", now=1150 if change == "expired" else 1000).returncode == 2
    with sqlite3.connect(path / "execution.sqlite") as conn:
        assert list(conn.execute("SELECT * FROM attempts ORDER BY token")) == before
    assert not (path / "candidate.json").exists()
    assert not (path / "receipt.json").exists()
    assert not (tmp_path / "UNAUTHORIZED_CALL").exists()


@pytest.mark.parametrize("change", ["input", "report", "template", "extension", "token", "epoch", "accepted_at", "partial", "candidate_whitespace"])
def test_changed_evidence_and_progress_are_never_repaired_implicitly(tmp_path, change):
    config = setup_case(tmp_path)
    assert child(tmp_path, "accept" if change == "accepted_at" else "checkpoint").returncode == 73
    path = directory(config)
    if change in {"input", "report", "template", "extension"}:
        target = {"input": "r1-memory-input.json", "report": "r1-memory-result.json",
                  "template": "r1-critic-template.json", "extension": "extension.json"}[change]
        original = (path / target).read_bytes()
        (path / target).write_bytes(original + b" ")
    elif change == "partial":
        (path / "execution.json").write_bytes(b'{"torn":')
    elif change == "candidate_whitespace":
        state = SwarmState(path / "execution.sqlite", OwnerFile(config["owner"], clock=lambda: 1000).read_task,
                           clock=lambda: 1000)
        candidate, *_ = closed_loop_recovery.terminal_evidence(path, read_json(Path(config["input"])),
                                                               state.finalization(path.name)["checkpoint"], state)
        (path / "candidate.json").write_text(canonical(candidate) + " \n")
    else:
        with sqlite3.connect(path / "execution.sqlite") as conn:
            if change == "token":
                conn.execute("UPDATE attempts SET token=token||'changed' WHERE job_id='r0-speed'")
            elif change == "epoch":
                conn.execute("UPDATE attempts SET epoch=epoch+1 WHERE job_id='r0-speed'")
            else:
                conn.execute("UPDATE jobs SET accepted_at=accepted_at+1 WHERE state='accepted'")
    with sqlite3.connect(path / "execution.sqlite") as conn:
        before = list(conn.execute("SELECT * FROM attempts ORDER BY token"))
    assert child(tmp_path, "resume").returncode == 2
    with sqlite3.connect(path / "execution.sqlite") as conn:
        assert list(conn.execute("SELECT * FROM attempts ORDER BY token")) == before
    assert not (path / "receipt.json").exists()


def test_two_finalizers_have_one_os_lock_and_crash_releases_it(tmp_path):
    config = setup_case(tmp_path)
    assert child(tmp_path, "checkpoint").returncode == 73
    command = [sys.executable, str(Path(__file__).resolve()), "child", str(tmp_path), "hold", "1000"]
    held = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        expires = time.monotonic() + 10
        while not (tmp_path / "LOCK_HELD").exists() and time.monotonic() < expires:
            time.sleep(.01)
        assert (tmp_path / "LOCK_HELD").exists()
        assert child(tmp_path, "resume").returncode == 2
        assert result(tmp_path)["error"] == "FINALIZATION_BUSY"
        held.kill()
        held.communicate(timeout=5)
        assert child(tmp_path, "resume").returncode == 0
        assert result(tmp_path)["receipt"]["budget"]["attempts_used"] == 5
    finally:
        if held.poll() is None:
            held.kill()
            held.communicate(timeout=5)
    assert not (tmp_path / "UNAUTHORIZED_CALL").exists()


def test_recovery_cannot_borrow_completed_readback_deadline_exception(tmp_path):
    config = setup_case(tmp_path)
    assert child(tmp_path, "checkpoint").returncode == 73
    with pytest.raises(SwarmError, match="FINALIZATION_OPTIONS_INVALID"):
        execute_closed_loop(config["owner"], config["input"], config["plan"],
            MeasuredBackend(read_json(Path(config["input"])), config["measure"]),
            worker_actors=config["actors"], clock=lambda: 1150,
            resume_finalization=True, expected_receipt_sha256="a" * 64)


def test_finalization_seals_exact_accepts_and_progress_in_one_transaction(tmp_path):
    config = setup_case(tmp_path)
    assert child(tmp_path, "checkpoint").returncode == 73
    path = directory(config)
    state = SwarmState(path / "execution.sqlite", OwnerFile(config["owner"], clock=lambda: 1000).read_task,
                       clock=lambda: 1000)
    record = state.finalization(path.name)
    checkpoint = record["checkpoint"]
    assert state.prepare_finalization(path.name, checkpoint) == checkpoint
    changed = dict(checkpoint, stop_reason="forged")
    with pytest.raises(SwarmError, match="FINALIZATION_CONFLICT"):
        state.prepare_finalization(path.name, changed)
    with pytest.raises(SwarmError, match="FINALIZATION_CONFLICT"):
        state.accept(path.name, "r0-critic", snapshot(config)["jobs"]["r0-critic"]["current_attempt"]["result_digest"],
                     checkpoint["verification_ref"], checkpoint["owner_ref"])
    job, sha = next(iter(checkpoint["accepts"].items()))
    state.accept(path.name, job, sha, checkpoint["verification_ref"], checkpoint["owner_ref"])
    accepted = snapshot(config)["jobs"][job]
    state.accept(path.name, job, sha, checkpoint["verification_ref"], checkpoint["owner_ref"])
    assert snapshot(config)["jobs"][job] == accepted
    assert child(tmp_path, "resume").returncode == 0


def test_work_name_ending_in_critic_is_still_verified_as_work(tmp_path):
    config = setup_case(tmp_path)
    config["plan"]["jobs"][0]["job_id"] = "speed-critic"
    (tmp_path / "case.json").write_text(canonical(config))
    assert child(tmp_path, "checkpoint").returncode == 73
    assert child(tmp_path, "resume").returncode == 0
    assert result(tmp_path)["receipt"]["review_passed"] is True


def test_anchored_replay_also_checks_pinned_checkpoint_and_receipt(tmp_path):
    config = setup_case(tmp_path)
    assert child(tmp_path, "checkpoint").returncode == 73
    assert child(tmp_path, "resume").returncode == 0
    anchor = result(tmp_path)["receipt_sha256"]
    assert child(tmp_path, "replay", now=1150, anchor=anchor).returncode == 0
    with sqlite3.connect(directory(config) / "execution.sqlite") as conn:
        old = json.loads(conn.execute("SELECT checkpoint_json FROM run_finalizations").fetchone()[0])
        old["stop_reason"] = "changed"
        conn.execute("UPDATE run_finalizations SET checkpoint_json=?", (canonical(old),))
    assert child(tmp_path, "replay", anchor=anchor).returncode == 2
    assert result(tmp_path)["error"] == "FINALIZATION_CONFLICT"


def test_cli_resumes_without_a_simulation_or_backend(tmp_path):
    config = setup_case(tmp_path)
    payload = read_json(Path(config["input"]))
    payload["objective"]["budget"]["deadline"] = time.time() + 300
    Path(config["input"]).write_text(canonical(payload))
    owner = read_json(Path(config["owner"]))
    owner["binding"].update(context_digest=digest(payload), expires_at=time.time() + 400)
    owner["source_checks"][0]["sha256"] = hashlib.sha256(Path(config["input"]).read_bytes()).hexdigest()
    Path(config["owner"]).write_text(canonical(owner))
    config["plan"]["parent_input_digest"] = digest(payload)
    (tmp_path / "case.json").write_text(canonical(config))
    assert child(tmp_path, "checkpoint", now=time.time()).returncode == 73
    plan_path = tmp_path / "supplied-plan.json"
    plan_path.write_text(canonical(config["plan"]))
    command = [sys.executable, "-m", "task_swarm.closed_loop", "--owner", config["owner"],
               "--input", config["input"], "--plan", str(plan_path), "--resume-finalization"]
    for actor in config["actors"]:
        command.extend(["--worker", actor])
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "runtime")}
    answer = subprocess.run(command, capture_output=True, text=True, env=env, timeout=15)
    assert answer.returncode == 0, answer.stderr
    assert json.loads(answer.stdout)["recovered_finalization"] is True


@pytest.mark.parametrize("change", ["none", "revoke", "grant_expired", "origin_source"])
def test_recovery_reconstructs_actual_reuse_owner_and_current_decision(tmp_path, change):
    from test_task_swarm_learning_reuse import allow, setup_reuse
    reuse, args, plan, payload, _, origin = setup_reuse(tmp_path)
    decision = allow(reuse)
    config = {"owner": args["target_owner"], "input": args["target_input"], "plan": plan,
              "actors": ["worker-a"], "unresolved": True, "reuse_context": {
                  "origin_owner": args["origin_owner"], "origin_input": args["origin_input"],
                  "anchor": args["anchor"], "proposal": args["proposal"], "decision_digest": digest(decision)}}
    (tmp_path / "case.json").write_text(canonical(config))
    assert child(tmp_path, "checkpoint").returncode == 73
    before = snapshot(config)
    if change == "revoke":
        reuse.decide("ref/owner/fixture", "ref/review/one-learning", "revoke",
                     "ref/decision/revoked", expected_generation=1)
    elif change == "origin_source":
        origin[1].write_bytes(origin[1].read_bytes() + b" ")
    elif change == "grant_expired":
        target = read_json(Path(args["target_owner"]))
        target["learning_reuse"]["expires_at"] = 1020
        Path(args["target_owner"]).write_text(canonical(target))
    answer = child(tmp_path, "resume", now=1030 if change == "grant_expired" else 1000)
    if change == "none":
        assert answer.returncode == 0, answer.stderr
        assert result(tmp_path)["candidate"]["claims"][0]["claim"]["text"] == "Use measured memory budget 8."
    else:
        assert answer.returncode == 2, answer.stderr
        assert snapshot(config) == before
        assert not (directory(config) / "receipt.json").exists()
    assert not (tmp_path / "UNAUTHORIZED_CALL").exists()


if __name__ == "__main__":
    raise SystemExit(_child(Path(sys.argv[2]), sys.argv[3], float(sys.argv[4]), sys.argv[5] if len(sys.argv) > 5 else None))
