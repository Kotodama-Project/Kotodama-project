from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))

from task_swarm.protocol import SwarmError, digest, validate_binding
from task_swarm.state import SwarmState


class FakeClock:
    def __init__(self, value: float = 1_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class SwarmStateTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_root = Path(__file__).resolve().parents[1] / "work"
        temporary_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temporary_root)
        self.clock = FakeClock()
        self.binding = {
            "task_id": "task-demo",
            "revision": 1,
            "context_digest": "a" * 64,
            "owner_ref": "owner",
            "active_home": "local",
            "authority_ref": "authority",
            "capability_ref": "capability",
            "expires_at": 2_000,
            "status": "active",
        }
        self.db = Path(self.temp.name) / "swarm.sqlite"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def state(self) -> SwarmState:
        return SwarmState(self.db, lambda task_id: copy.deepcopy(self.binding), self.clock)

    def plan(self, jobs: list[dict] | None = None, *, deadline: object = 1_900, budget: int = 10) -> dict:
        return {
            "run_id": "run-demo",
            "task_id": "task-demo",
            "binding_digest": digest(validate_binding(self.binding, now=self.clock())),
            "budget": {"attempt_budget": budget, "concurrency": 2, "deadline": deadline},
            "jobs": jobs if jobs is not None else [self.job("work")],
        }

    @staticmethod
    def job(job_id: str, *, kind: str = "work", deps: list[str] | None = None, keys: list[str] | None = None) -> dict:
        return {
            "job_id": job_id,
            "kind": kind,
            "dependencies": deps or [],
            "exclusive_keys": keys or [],
            "payload_ref": f"payload-{job_id}",
            "payload_digest": "b" * 64,
        }

    def test_create_is_idempotent_and_dag_is_immutable(self) -> None:
        state = self.state()
        plan = self.plan([self.job("a"), self.job("b", deps=["a"])])
        self.assertEqual(state.create_run(plan), state.create_run(copy.deepcopy(plan)))

        changed = copy.deepcopy(plan)
        changed["jobs"][0]["payload_ref"] = "different"
        with self.assertRaises(SwarmError) as ctx:
            state.create_run(changed)
        self.assertEqual(ctx.exception.code, "RUN_IMMUTABLE")

    def test_work_retries_cannot_spend_verifier_reserve(self) -> None:
        state = self.state()
        plan = self.plan([self.job("a"), self.job("b"), self.job("z-review", kind="review", deps=["a"])], budget=4)
        plan["budget"]["verifier_reserve"] = 2
        state.create_run(plan)
        first = state.claim("run-demo", "worker-a")
        state.report(first["token"], "result-a", "c"*64, "candidate", "runtime-a")
        second = state.claim("run-demo", "worker-b")
        self.assertEqual(second["job_id"], "b")
        state.fail(second["token"], "retryable fixture failure", retryable=True)
        review = state.claim("run-demo", "independent-reviewer")
        self.assertEqual(review["kind"], "review")
        snapshot = state.snapshot("run-demo")
        self.assertEqual(snapshot["budget"]["remaining_work_attempts"], 0)
        self.assertEqual(snapshot["budget"]["verifier_reserve"], 2)
        self.assertEqual(snapshot["jobs"]["b"]["state"], "pending")

    def test_rejects_missing_dependencies_cycles_and_unknown_fields(self) -> None:
        plan = self.plan()
        for invalid in (
            self.plan([self.job("a", deps=["missing"])]),
            self.plan([self.job("a", deps=["b"]), self.job("b", deps=["a"])]),
            {**plan, "unexpected": True},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(SwarmError):
                SwarmState(self.db.with_name("invalid.sqlite"), lambda task_id: self.binding, self.clock).create_run(invalid)

    def test_concurrent_claim_serializes_intersecting_exclusive_keys(self) -> None:
        jobs = [self.job("a", keys=["shared"]), self.job("b", keys=["shared"])]
        state = self.state()
        state.create_run(self.plan(jobs))

        def claim(worker: str):
            return state.claim("run-demo", worker, lease_seconds=60)

        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(claim, ["worker-a", "worker-b"]))
        self.assertEqual(sum(claim is not None for claim in claims), 1)
        snapshot = state.snapshot("run-demo")
        self.assertEqual(snapshot["running"], 1)
        self.assertEqual(snapshot["budget"]["attempts_used"], 1)

    def test_report_waits_for_owner_and_survives_restart(self) -> None:
        state = self.state()
        state.create_run(self.plan())
        claim = state.claim("run-demo", "worker")
        assert claim is not None
        state.attach_identity(claim["token"], {"kind": "native", "thread_id": "thread-1"})
        state.report(claim["token"], "result", "c" * 64, "candidate", "receipt")
        self.assertEqual(state.snapshot("run-demo")["run_state"], "waiting_owner")

        restarted = self.state()
        self.assertEqual(restarted.snapshot("run-demo")["jobs"]["work"]["state"], "reported")
        self.assertIsNone(restarted.claim("run-demo", "another-worker"))
        with self.assertRaises(SwarmError):
            restarted.accept("run-demo", "work", "d" * 64, "verification", "owner")
        accepted = restarted.accept("run-demo", "work", "c" * 64, "verification", "owner")
        self.assertEqual(accepted["state"], "accepted")
        self.assertEqual(restarted.snapshot("run-demo")["accepted"], 1)

    def test_failed_dependency_blocks_only_its_descendants(self) -> None:
        jobs = [
            self.job("root"),
            self.job("dependent", deps=["root"]),
            self.job("independent"),
        ]
        state = self.state()
        state.create_run(self.plan(jobs))
        first = state.claim("run-demo", "worker")
        assert first is not None
        self.assertEqual(first["job_id"], "independent")  # deterministic id ordering
        state.fail(first["token"], "startup failed", retryable=False)
        second = state.claim("run-demo", "worker-2")
        assert second is not None
        self.assertEqual(second["job_id"], "root")
        state.fail(second["token"], "peer unavailable", retryable=False)
        snapshot = state.snapshot("run-demo")
        self.assertEqual(snapshot["jobs"]["dependent"]["state"], "blocked")
        self.assertEqual(snapshot["jobs"]["independent"]["state"], "failed")

    def test_dead_peer_recovery_fences_old_token_and_increments_epoch(self) -> None:
        state = self.state()
        state.create_run(self.plan())
        first = state.claim("run-demo", "worker", lease_seconds=1)
        assert first is not None
        state.attach_identity(first["token"], {"kind": "process", "pid": 42, "created_at": 1_000})
        self.clock.value = 1_002
        self.assertEqual(state.recover("run-demo", lambda identity: True)["alive"], [first["token"]])
        self.assertEqual(state.snapshot("run-demo")["running"], 1)
        self.assertEqual(state.recover("run-demo", lambda identity: False)["revoked"], [first["token"]])
        second = state.claim("run-demo", "worker-2", lease_seconds=60)
        assert second is not None
        self.assertEqual(second["attempt"], 2)
        self.assertEqual(second["epoch"], 2)
        with self.assertRaises(SwarmError) as ctx:
            state.report(first["token"], "late", "c" * 64, "candidate", "receipt")
        self.assertIn(ctx.exception.code, {"STALE_ATTEMPT", "LEASE_EXPIRED", "DEADLINE_EXPIRED"})

    def test_unknown_identity_is_not_assumed_dead(self) -> None:
        state = self.state()
        state.create_run(self.plan())
        claim = state.claim("run-demo", "worker", lease_seconds=1)
        assert claim is not None
        self.clock.value = 1_002
        result = state.recover("run-demo", lambda identity: False)
        self.assertEqual(result["revoked"], [])
        self.assertEqual(result["unknown"], [claim["token"]])
        self.assertEqual(state.snapshot("run-demo")["running"], 1)

    def test_deadline_uses_host_clock_and_finite_values(self) -> None:
        state = self.state()
        # The display date is next day in JST, but the explicit offset is still
        # a future host-clock instant.
        plan = self.plan(deadline="1970-01-01T09:31:00+09:00")
        self.clock.value = 0
        self.binding["expires_at"] = 3_600
        plan["binding_digest"] = digest(validate_binding(self.binding, now=self.clock()))
        state.create_run(plan)
        self.clock.value = 1_860  # 1970-01-01T09:31:00+09:00 is 1800 seconds
        self.assertIsNone(state.claim("run-demo", "worker"))

        with self.assertRaises(SwarmError):
            self.state().create_run(self.plan(deadline=float("nan")))

    def test_zero_work_run_is_restartable_and_quiescent(self) -> None:
        state = self.state()
        state.create_run(self.plan([]))
        self.assertEqual(state.snapshot("run-demo")["run_state"], "quiescent")
        self.assertIsNone(state.claim("run-demo", "worker"))
        self.assertEqual(self.state().snapshot("run-demo")["budget"]["attempts_used"], 0)

    def test_zero_attempt_budget_is_a_valid_owner_resume_plan(self) -> None:
        state = self.state()
        state.create_run(self.plan([self.job("work")], budget=0))
        self.assertIsNone(state.claim("run-demo", "worker"))
        self.assertEqual(state.snapshot("run-demo")["run_state"], "budget_exhausted")

    def test_review_cannot_be_claimed_by_its_work_reporter(self) -> None:
        jobs = [self.job("work"), self.job("review", kind="review", deps=["work"])]
        state = self.state()
        state.create_run(self.plan(jobs))
        work = state.claim("run-demo", "same-worker")
        assert work is not None
        state.report(work["token"], "result", "c" * 64, "candidate", "receipt")
        state.accept("run-demo", "work", "c" * 64, "verification", "owner")
        self.assertIsNone(state.claim("run-demo", "same-worker"))
        review = state.claim("run-demo", "independent-reviewer")
        self.assertIsNotNone(review)
        assert review is not None
        self.assertEqual(review["job_id"], "review")


if __name__ == "__main__":
    unittest.main()
