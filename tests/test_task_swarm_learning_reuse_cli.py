"""Real CLI regressions for single-owner initialization and current refusals."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from test_task_swarm_learning_reuse import (
    ReadingBackend, allow, save, setup_reuse,
)
import pytest
from task_swarm.owner_file import OwnerFile
from task_swarm.closed_loop_context import derive_child_view
from task_swarm.closed_loop_contract import loop_criteria
from task_swarm.protocol import digest
from task_swarm.state import SwarmState

REPO = Path(__file__).resolve().parents[1]


def prepare(tmp_path, *, now=None, grant_lifetime=100):
    reuse, context, plan, payload, owner, origin = setup_reuse(
        tmp_path, now=time.time() if now is None else now, grant_lifetime=grant_lifetime)
    decision = allow(reuse)
    view = derive_child_view(payload, "r0-apply-memory", plan["jobs"][0]["selected_spans"],
                             plan_digest=digest(plan))
    backend = ReadingBackend()
    work = backend.produce({"job_id": "r0-apply-memory", "role": "work", "view": view},
                           None, actor_ref="worker-a")["result"]
    critic = backend.review({"job_id": "r0-critic", "role": "critic", "round": 0, "view": view,
        "reports": {"r0-apply-memory": work}, "criteria": loop_criteria(payload)},
        None, actor_ref="verifier")["result"]
    context_path, plan_path, scenario_path = [tmp_path / name for name in
                                            ("context.json", "plan.json", "scenario.json")]
    save(context_path, context)
    save(plan_path, plan)
    save(scenario_path, {"work": {"r0-apply-memory": work}, "critics": {"0": critic}, "repair_plan": None})
    args = ["run", "--context", str(context_path), "--decision-digest", digest(decision),
            "--plan", str(plan_path), "--simulation", str(scenario_path), "--worker", "worker-a"]
    return reuse, context, payload, owner, origin, context_path, args


def cli(args, *, cwd, diagnostic=False, env=None):
    command = ([str(REPO / "tools/measure_learning_reuse_cli.py"), "--child"] if diagnostic
               else ["-m", "task_swarm.learning_reuse"])
    return subprocess.run([sys.executable, "-B", *command, *args], cwd=cwd,
        env={**os.environ, "PYTHONPATH": str(REPO / "runtime"), **(env or {})},
        capture_output=True, text=True, timeout=20)


def snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def test_cli_constructs_only_the_coordinator_owner_on_run_and_replay(tmp_path):
    _, _, _, _, _, _, args = prepare(tmp_path)
    first = cli(args, cwd=tmp_path, diagnostic=True)
    assert first.returncode == 0, first.stderr
    result = json.loads(first.stdout)
    assert result["receipt"]["review_passed"]
    replay = cli([*args, "--receipt-sha256", result["receipt_sha256"]], cwd=tmp_path, diagnostic=True)
    assert replay.returncode == 0, replay.stderr
    assert json.loads(replay.stdout)["duplicate"]
    for response in (first, replay):
        lines = [json.loads(line.removeprefix("KOTODAMA_REUSE_MEASUREMENT "))
                 for line in response.stderr.splitlines() if line.startswith("KOTODAMA_REUSE_MEASUREMENT ")]
        summary = next(item for item in lines if "constructors" in item)
        assert [item["caller"] for item in summary["constructors"]] == ["_execute_closed_loop"]


@pytest.mark.parametrize("path_kind", ["relative", "home"])
def test_cli_normalizes_owner_paths_and_replays_from_another_cwd(tmp_path, path_kind):
    reuse, context, payload, _, _, context_path, args = prepare(tmp_path)
    expected_origin = str(Path(context["origin_owner"]).resolve())
    for key in ("origin_owner", "target_owner"):
        relative = Path(context[key]).relative_to(tmp_path).as_posix()
        context[key] = relative if path_kind == "relative" else "~/" + relative
    save(context_path, context)
    env = {"HOME": str(tmp_path), "USERPROFILE": str(tmp_path)}
    result = cli(args, cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stderr
    result = json.loads(result.stdout)
    run_id = "task-run-" + digest([payload["task_id"], payload["revision"]])[:32]
    state = SwarmState(tmp_path / "b" / "operations" / run_id / "execution.sqlite", OwnerFile(tmp_path / "b" / "owner.json").read_task)
    saved = state.finalization(run_id)["checkpoint"]["reuse_context"]
    assert saved["origin_owner"] == expected_origin
    # Match the normalized owner references retained by the existing API.
    context["origin_owner"] = saved["origin_owner"]
    context["target_owner"] = str((tmp_path / "b" / "owner.json").resolve())
    save(context_path, context)
    other = tmp_path / "other"; other.mkdir()
    replay = cli([*args, "--receipt-sha256", result["receipt_sha256"]], cwd=other, env=env)
    assert replay.returncode == 0, replay.stderr
    assert json.loads(replay.stdout)["duplicate"]


@pytest.mark.parametrize("mutation", ["context", "proposal", "source", "receipt", "grant", "revoke", "decision"])
def test_cli_refuses_changed_evidence_before_target_execution(tmp_path, mutation):
    reuse, context, _, owner, origin, context_path, args = prepare(tmp_path)
    if mutation == "context":
        context["unchecked"] = True
    elif mutation == "proposal":
        context["proposal"]["selected"]["claim"]["text"] = "memory=999"
    elif mutation == "source":
        origin[1].write_text(origin[1].read_text() + " ", encoding="utf-8")
    elif mutation == "receipt":
        path = reuse.directory / "receipt.json"
        path.write_bytes(path.read_bytes() + b" ")
    elif mutation == "grant":
        owner["learning_reuse"]["expires_at"] = time.time() - 1
        save(Path(context["target_owner"]), owner)
    elif mutation == "revoke":
        reuse.decide("ref/owner/fixture", "ref/review/one-learning", "revoke",
                     "ref/decision/stop", expected_generation=1)
    else:
        args[args.index("--decision-digest") + 1] = "0" * 64
    save(context_path, context)
    root = tmp_path / "b" / "operations"
    before = snapshot(root)
    response = cli(args, cwd=tmp_path)
    assert response.returncode == 2, response.stderr
    expected = {"context": "REUSE_CONTEXT_INVALID", "proposal": "REUSE_PROPOSAL_CHANGED",
                "source": "SOURCE_BINDING_INVALID", "receipt": "REUSE_ORIGIN_ANCHOR_MISMATCH",
                "grant": "REUSE_GRANT_EXPIRED", "revoke": "REUSE_DECISION_STALE",
                "decision": "REUSE_DECISION_STALE"}
    assert json.loads(response.stderr)["error"] == expected[mutation]
    assert snapshot(root) == before
    assert not list(root.rglob("execution.sqlite"))


def test_cli_expired_objective_replay_still_checks_current_revocation(tmp_path):
    reuse, _, _, _, _, _, args = prepare(tmp_path, now=time.time() - 101, grant_lifetime=190)
    from task_swarm.closed_loop import ScriptedSimulation
    plan = json.loads(Path(args[args.index("--plan") + 1]).read_text())
    scenario = json.loads(Path(args[args.index("--simulation") + 1]).read_text())
    decision_digest = args[args.index("--decision-digest") + 1]
    completed = reuse.execute(decision_digest, plan, ScriptedSimulation(scenario), worker_actors=["worker-a"])
    replay_args = [*args, "--receipt-sha256", completed["receipt_sha256"]]
    replay = cli(replay_args, cwd=tmp_path)
    assert replay.returncode == 0, replay.stderr
    assert json.loads(replay.stdout)["duplicate"]
    expired = cli(args, cwd=tmp_path)
    assert expired.returncode == 2
    assert json.loads(expired.stderr)["error"] == "OBJECTIVE_DEADLINE_INVALID"
    reuse.decide("ref/owner/fixture", "ref/review/one-learning", "revoke",
                 "ref/decision/stop", expected_generation=1)
    root = tmp_path / "b" / "operations"
    before = snapshot(root)
    revoked = cli(replay_args, cwd=tmp_path)
    assert revoked.returncode == 2
    assert json.loads(revoked.stderr)["error"] == "REUSE_DECISION_STALE"
    assert snapshot(root) == before
