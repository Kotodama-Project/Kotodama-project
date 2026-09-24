"""Regressions for the independent review of the swarm scheduler (#67/#85)."""
from __future__ import annotations

import copy
import sqlite3
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from task_swarm.protocol import SwarmError, digest, validate_binding
from task_swarm.state import SwarmState
import test_task_swarm_state as fixtures


class SchedulerReviewRegressions(unittest.TestCase):
    # Reuse the scheduler fixture without re-running its own tests.
    setUp = fixtures.SwarmStateTests.setUp
    tearDown = fixtures.SwarmStateTests.tearDown
    state = fixtures.SwarmStateTests.state
    plan = fixtures.SwarmStateTests.plan
    job = staticmethod(fixtures.SwarmStateTests.job)

    def test_owner_read_runs_outside_the_write_lock(self) -> None:
        self.state().create_run(self.plan())
        observed: list[bool] = []

        def reader(task_id: str) -> dict:
            # While the owner is being read, another writer must still be able
            # to take the scheduler's write lock.
            probe = sqlite3.connect(self.db, timeout=0.2, isolation_level=None)
            try:
                probe.execute("BEGIN IMMEDIATE")
                probe.execute("ROLLBACK")
                observed.append(True)
            except sqlite3.OperationalError:
                observed.append(False)
            finally:
                probe.close()
            return copy.deepcopy(self.binding)

        lease = SwarmState(self.db, reader, self.clock).claim("run-demo", "worker-a")
        self.assertIsNotNone(lease)
        self.assertTrue(observed)
        self.assertTrue(all(observed), "the owner reader ran while the write lock was held")

    def test_exclusive_keys_conflict_across_runs_of_the_same_store(self) -> None:
        state = self.state()
        first = self.plan([self.job("work", keys=["worktree:/repo/src"])])
        second = copy.deepcopy(first)
        second["run_id"] = "run-second"
        state.create_run(first)
        state.create_run(second)
        self.assertIsNotNone(state.claim("run-demo", "worker-a"))
        self.assertIsNone(state.claim("run-second", "worker-b"), "two writers must not hold one resource")

    def test_an_expired_lease_of_a_live_worker_can_be_given_up_or_revoked(self) -> None:
        state = self.state()
        state.create_run(self.plan([self.job("a"), self.job("b")]))
        first = state.claim("run-demo", "worker-a", lease_seconds=10)
        second = state.claim("run-demo", "worker-b", lease_seconds=10)
        state.attach_identity(second["token"], {"kind": "native", "thread_id": "thread-b"})
        self.clock.value += 11
        with self.assertRaises(SwarmError) as ctx:
            state.report(first["token"], "result", "c" * 64, "candidate", "runtime")
        self.assertEqual(ctx.exception.code, "LEASE_EXPIRED")
        # The token holder can still give the lease up and free its slot.
        receipt = state.fail(first["token"], "lease-expired", retryable=True)
        self.assertEqual(receipt["job_state"], "pending")
        # Before the deadline a live worker keeps its lease...
        self.assertEqual(state.recover("run-demo", lambda identity: True)["alive"], [second["token"]])
        # ...but past the run deadline it can never report, so recovery frees it.
        self.clock.value = 1_950
        recovered = state.recover("run-demo", lambda identity: True)
        self.assertEqual(recovered["revoked"], [second["token"]])
        self.assertEqual(state.snapshot("run-demo")["counts"]["running"], 0)

if __name__ == "__main__":
    unittest.main()
