"""State-only cancellation boundaries; no public cancellation adapter is implied.

The private writer below exercises the SQLite part of #363. A future public
adapter must also hold the finalization OS lock and check receipt publication.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))

from task_swarm.protocol import SwarmError, canonical, digest, validate_binding
from task_swarm.state import SwarmState


class SwarmCancellationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "execution.sqlite"
        self.now = 1000.0
        self.binding = {
            "task_id": "task-cancel", "revision": 1, "context_digest": "a" * 64,
            "owner_ref": "owner", "active_home": "local", "authority_ref": "authority",
            "capability_ref": "capability", "expires_at": 2000, "status": "active",
        }
        self.state = self.reopen()
        self.plan = self.state.create_run(self.make_plan())

    def reopen(self):
        return SwarmState(self.db, lambda _task: copy.deepcopy(self.binding), clock=lambda: self.now)

    @staticmethod
    def job(name, *, kind="work", dependencies=(), keys=()):
        return {"job_id": name, "kind": kind, "dependencies": list(dependencies),
                "exclusive_keys": list(keys), "payload_ref": "ref/input/" + name,
                "payload_digest": "b" * 64}

    def make_plan(self, *, run_id="run-cancel", jobs=None):
        return {"run_id": run_id, "task_id": self.binding["task_id"],
                "binding_digest": digest(validate_binding(self.binding, now=self.now)),
                "budget": {"attempt_budget": 8, "concurrency": 2, "deadline": 1900,
                           "verifier_reserve": 1},
                "jobs": jobs if jobs is not None else [self.job("a-work", keys=["shared"]),
                    self.job("z-review", kind="review", dependencies=["a-work"])]}

    def cancel(self, state=None, **changes):
        arguments = {"expected_binding_digest": self.plan["binding_digest"],
                     "expected_initial_execution_plan_digest": digest(self.plan),
                     "owner_ref": "owner"}
        arguments.update(changes)
        return (state or self.state)._record_cancellation("run-cancel", **arguments)

    def rows(self):
        # Cancellation adds its own row; these execution rows must not change.
        with sqlite3.connect(self.db) as conn:
            return {table: list(conn.execute("SELECT * FROM " + table + " ORDER BY 1,2"))
                    for table in ("runs", "jobs", "attempts", "run_extensions", "run_finalizations")}

    def assert_error(self, code, operation):
        with self.assertRaises(SwarmError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)

    def reports(self):
        first = self.state.claim("run-cancel", "worker")
        self.state.attach_identity(first["token"], {"kind": "native", "thread_id": "work-thread"})
        self.state.report(first["token"], "ref/result/work", "c" * 64, "candidate", "ref/receipt/work")
        review = self.state.claim("run-cancel", "critic")
        self.state.attach_identity(review["token"], {"kind": "native", "thread_id": "critic-thread"})
        self.state.report(review["token"], "ref/result/review", "d" * 64, "candidate", "ref/receipt/review")
        return first, review

    def checkpoint(self):
        return {"run_id": "run-cancel", "binding_digest": self.plan["binding_digest"],
                "owner_ref": "owner", "state_digest": self.state.finalization_evidence_digest("run-cancel"),
                "accepts": {"a-work": "c" * 64, "z-review": "d" * 64},
                "verification_ref": "ref/verification"}

    def extension(self):
        return {"round": 1, "initial_plan_digest": digest(self.plan), "critic_job_id": "z-review",
                "critic_result_digest": "d" * 64, "proposal_digest": "e" * 64,
                "jobs": [self.job("repair"), self.job("zz-review", kind="review",
                                                     dependencies=["a-work", "repair"])]}

    def test_record_is_bound_idempotent_and_does_not_rewrite_execution(self):
        self.state.claim("run-cancel", "worker")
        before, budget = self.rows(), self.state.snapshot("run-cancel")["budget"]
        record = self.cancel()
        self.assertEqual(self.rows(), before)
        self.assertEqual(record["initial_execution_plan_digest"], digest(self.plan))
        self.assertEqual(record["binding_digest"], self.plan["binding_digest"])
        self.now += 1
        self.assertEqual(self.cancel(self.reopen()), record)
        record["owner_ref"] = "mutated-return-value"
        restarted = self.reopen()
        snapshot = restarted.snapshot("run-cancel")
        self.assertEqual(snapshot["cancellation"]["owner_ref"], "owner")
        self.assertEqual(snapshot["cancellation"]["requested_at"], 1000)
        self.assertEqual(snapshot["run_state"], "cancelled")
        self.assertEqual(snapshot["running"], 1)
        self.assertEqual(snapshot["budget"], budget)
        self.assertEqual(self.rows(), before)

    def test_fresh_process_observes_cancellation_and_cannot_claim(self):
        record = self.cancel()
        script = (
            "import copy,json,sys;sys.path.insert(0,sys.argv[1]);"
            "from task_swarm.state import SwarmState;"
            "from task_swarm.protocol import SwarmError;"
            "binding=json.loads(sys.argv[3]);"
            "state=SwarmState(sys.argv[2],lambda _:copy.deepcopy(binding),clock=lambda:1000)\n"
            "try: state.claim('run-cancel','fresh-worker')\n"
            "except SwarmError as error: print(json.dumps({'error':error.code,'record':state.cancellation('run-cancel')}))\n"
            "else: raise AssertionError('cancelled run became claimable')\n"
        )
        result = subprocess.run([sys.executable, "-c", script,
            str(Path(__file__).resolve().parents[1] / "runtime"), str(self.db), canonical(self.binding)],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"error": "RUN_CANCELLED", "record": record})
        self.assertEqual(self.state.snapshot("run-cancel")["budget"]["attempts_used"], 0)

    def test_mismatched_owner_binding_plan_and_unknown_run_do_not_write(self):
        before = self.rows()
        for change, code in [({"owner_ref": "other-owner"}, "WRONG_OWNER"),
                             ({"expected_binding_digest": "0" * 64}, "CANCELLATION_CONFLICT"),
                             ({"expected_initial_execution_plan_digest": "0" * 64}, "CANCELLATION_CONFLICT")]:
            with self.subTest(change=change):
                self.assert_error(code, lambda: self.cancel(**change))
                self.assertIsNone(self.state.cancellation("run-cancel"))
                self.assertEqual(self.rows(), before)
        self.assert_error("UNKNOWN_RUN", lambda: self.state._record_cancellation("missing-run",
            expected_binding_digest=self.plan["binding_digest"],
            expected_initial_execution_plan_digest=digest(self.plan), owner_ref="owner"))
        self.assertEqual(self.rows(), before)

    def test_owner_change_and_expiry_are_not_exempted_for_cancellation(self):
        before = self.rows()
        self.binding["revision"] = 2
        self.assert_error("STALE_BINDING", self.cancel)
        self.binding["revision"] = 1
        self.now = 1900
        self.assert_error("DEADLINE_EXPIRED", self.cancel)
        self.now = 2000
        self.assert_error("EXPIRED_BINDING", self.cancel)
        self.assertIsNone(self.state.cancellation("run-cancel"))
        self.assertEqual(self.rows(), before)

    def test_same_cancellation_replays_after_run_deadline_with_live_owner(self):
        other = self.state.create_run(self.make_plan(run_id="other-expired-run"))
        record = self.cancel()
        before = self.rows()
        self.now = 1901
        self.assertEqual(self.cancel(self.reopen()), record)
        self.assert_error("CANCELLATION_CONFLICT", lambda: self.cancel(
            expected_initial_execution_plan_digest="0" * 64))
        self.assert_error("DEADLINE_EXPIRED", lambda: self.state._record_cancellation("other-expired-run",
            expected_binding_digest=other["binding_digest"],
            expected_initial_execution_plan_digest=digest(other), owner_ref="owner"))
        self.assertIsNone(self.state.cancellation("other-expired-run"))
        self.assertEqual(self.rows(), before)
        self.now = 2001
        self.assert_error("EXPIRED_BINDING", self.cancel)
        self.assertEqual(self.state.cancellation("run-cancel"), record)
        self.assertEqual(self.rows(), before)

    def test_cancelled_mutators_refuse_before_any_execution_update(self):
        lease = self.state.claim("run-cancel", "worker", lease_seconds=1)
        self.cancel()
        before = self.rows()
        operations = {
            "claim": lambda: self.state.claim("run-cancel", "worker-b"),
            "create": lambda: self.state.create_run(self.plan),
            "extend": lambda: self.state.extend_run("run-cancel", self.extension()),
            "identity": lambda: self.state.attach_identity(lease["token"], {"kind": "native", "thread_id": "late"}),
            "report": lambda: self.state.report(lease["token"], "ref/result", "c" * 64, "candidate", "ref/receipt"),
            "accept": lambda: self.state.accept("run-cancel", "a-work", "c" * 64, "ref/verification", "owner"),
            "checkpoint": lambda: self.state.prepare_finalization("run-cancel", self.checkpoint()),
            "finalization": lambda: self.state.finalization("run-cancel"),
            "pin": lambda: self.state.pin_final_receipt("run-cancel", "f" * 64, {}),
            "recover": lambda: self.state.recover("run-cancel", lambda _identity: False),
        }
        for name, operation in operations.items():
            with self.subTest(operation=name):
                self.assert_error("RUN_CANCELLED", operation)
                self.assertEqual(self.rows(), before)

    def test_both_fail_modes_remain_fenced_even_after_lease_and_run_deadline(self):
        lease = self.state.claim("run-cancel", "worker", lease_seconds=1)
        self.cancel()
        before = self.rows()
        for now in (1000, 1002, 1901, 2001):
            self.now = now
            for retryable in (True, False):
                with self.subTest(now=now, retryable=retryable):
                    self.assert_error("RUN_CANCELLED", lambda: self.reopen().fail(
                        lease["token"], "backend stopped", retryable=retryable))
                    self.assertEqual(self.rows(), before)
        self.assertEqual(self.state.cancellation("run-cancel")["requested_at"], 1000)

    def test_cancelled_lease_keeps_cross_run_exclusive_key(self):
        lease = self.state.claim("run-cancel", "worker")
        self.cancel()
        other = self.make_plan(run_id="run-other", jobs=[self.job("other", keys=["shared"])])
        self.state.create_run(other)
        for retryable in (True, False):
            self.assert_error("RUN_CANCELLED", lambda: self.state.fail(
                lease["token"], "stopped without proof", retryable=retryable))
        self.assertIsNone(self.state.claim("run-other", "other-worker"))
        self.assertEqual(self.state.snapshot("run-cancel")["running"], 1)
        self.assertEqual(self.state.snapshot("run-other")["budget"]["attempts_used"], 0)

    def test_cancel_between_owner_prefetch_and_claim_or_fail_is_seen_in_transaction(self):
        lease = self.state.claim("run-cancel", "worker")
        before = self.rows()
        original = copy.deepcopy(self.binding)

        def reader(_task):
            self.cancel()
            return copy.deepcopy(original)

        raced = SwarmState(self.db, reader, clock=lambda: self.now)
        self.assert_error("RUN_CANCELLED", lambda: raced.fail(lease["token"], "retry", retryable=True))
        self.assert_error("RUN_CANCELLED", lambda: raced.claim("run-cancel", "later"))
        self.assertEqual(self.rows(), before)

    def committed_order(self, first):
        """Hold a real writer transaction while the second connection queues."""
        ready, release, prefetched = threading.Event(), threading.Event(), threading.Event()
        other = self.reopen()
        finish = self.state._finish
        binding_reader = other.binding_reader
        results = {}

        def hold(conn, ok):
            try:
                if ok:
                    ready.set()
                    self.assertTrue(release.wait(10), "first writer was not released")
            finally:
                finish(conn, ok)

        def read(task):
            value = binding_reader(task)
            prefetched.set()
            return value

        self.state._finish = hold
        other.binding_reader = read
        operations = {
            "cancel": lambda writer: self.cancel(writer),
            "claim": lambda writer: writer.claim("run-cancel", "worker"),
        }
        second = "claim" if first == "cancel" else "cancel"

        def invoke(name, writer):
            try:
                results[name] = operations[name](writer)
            except BaseException as error:
                results[name] = error

        a = threading.Thread(target=invoke, args=(first, self.state))
        b = threading.Thread(target=invoke, args=(second, other))
        a.start()
        try:
            self.assertTrue(ready.wait(10), "first writer did not hold its transaction")
            b.start()
            self.assertTrue(prefetched.wait(10), "second writer did not read its owner")
        finally:
            release.set()
            a.join(timeout=10)
            if b.ident is not None:
                b.join(timeout=10)
            self.state._finish = finish
        self.assertFalse(a.is_alive() or b.is_alive(), "writer thread remained active")
        return results

    def test_cancel_commit_wins_against_separate_connection_claim(self):
        before = self.rows()
        results = self.committed_order("cancel")
        self.assertIsInstance(results["cancel"], dict)
        self.assertIsInstance(results["claim"], SwarmError)
        self.assertEqual(results["claim"].code, "RUN_CANCELLED")
        self.assertEqual(self.rows(), before)

    def test_claim_commit_before_cancel_keeps_its_lease_and_attempt(self):
        results = self.committed_order("claim")
        self.assertIsInstance(results["claim"], dict)
        self.assertIsInstance(results["cancel"], dict)
        before = self.rows()
        snapshot = self.state.snapshot("run-cancel")
        self.assertEqual(snapshot["running"], 1)
        self.assertEqual(snapshot["budget"]["attempts_used"], 1)
        self.assert_error("RUN_CANCELLED", lambda: self.state.claim("run-cancel", "next-worker"))
        self.assertEqual(self.rows(), before)

    def test_cancellation_insert_failure_rolls_back_without_partial_record(self):
        before = self.rows()
        with sqlite3.connect(self.db) as conn:
            conn.execute("CREATE TRIGGER refuse_cancel BEFORE INSERT ON run_cancellations "
                         "BEGIN SELECT RAISE(ABORT, 'controlled insert refusal'); END")
        with self.assertRaises(SwarmError) as caught:
            self.cancel()
        self.assertEqual(caught.exception.code, "STATE_WRITE_FAILED")
        self.assertIsInstance(caught.exception.__cause__, sqlite3.IntegrityError)
        self.assertIsNone(self.reopen().cancellation("run-cancel"))
        self.assertEqual(self.rows(), before)
        with sqlite3.connect(self.db) as conn:
            conn.execute("DROP TRIGGER refuse_cancel")
        self.assertEqual(self.cancel()["requested_at"], 1000)
        self.assertEqual(self.rows(), before)

    def test_cancel_during_recover_liveness_callback_is_seen_before_revocation(self):
        lease = self.state.claim("run-cancel", "worker", lease_seconds=1)
        self.state.attach_identity(lease["token"], {"kind": "process", "pid": 42, "created_at": 1000})
        self.now = 1002
        before = self.rows()

        def dead(_identity):
            self.cancel(self.reopen())
            return False

        self.assert_error("RUN_CANCELLED", lambda: self.state.recover("run-cancel", dead))
        self.assertEqual(self.rows(), before)
        self.assertEqual(self.state.snapshot("run-cancel")["running"], 1)

    def test_cancelled_snapshot_does_not_recompute_pending_dependents(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE jobs SET state='failed' WHERE job_id='a-work'")
        self.cancel()
        before = self.rows()
        for _ in range(2):
            snapshot = self.reopen().snapshot("run-cancel")
            self.assertEqual(snapshot["jobs"]["z-review"]["state"], "pending")
            self.assertEqual(snapshot["failed"], 1)
            self.assertEqual(snapshot["run_state"], "cancelled")
            self.assertEqual(self.rows(), before)

    def test_existing_extension_idempotency_cannot_bypass_cancellation(self):
        self.reports()
        extension = self.state.extend_run("run-cancel", self.extension())
        self.cancel()
        before = self.rows()
        self.assert_error("RUN_CANCELLED", lambda: self.reopen().extend_run("run-cancel", extension))
        self.assertEqual(self.state.extension("run-cancel"), extension)
        self.assertEqual(self.rows(), before)

    def test_checkpoint_and_accepted_idempotency_cannot_bypass_cancellation(self):
        first, _review = self.reports()
        checkpoint = self.checkpoint()
        self.state.prepare_finalization("run-cancel", checkpoint)
        self.state.accept("run-cancel", "a-work", "c" * 64, "ref/verification", "owner")
        self.cancel()
        before = self.rows()
        operations = [lambda: self.state.prepare_finalization("run-cancel", checkpoint),
                      lambda: self.state.finalization("run-cancel"),
                      lambda: self.state.accept("run-cancel", "a-work", "c" * 64, "ref/verification", "owner"),
                      lambda: self.state.attach_identity(first["token"], {"kind": "native", "thread_id": "work-thread"})]
        for operation in operations:
            self.assert_error("RUN_CANCELLED", operation)
            self.assertEqual(self.rows(), before)

    def test_corrupt_cancellation_never_becomes_an_uncancelled_run(self):
        original = self.cancel()
        corrupt = ["{", canonical({**original, "version": True}),
                   canonical({**original, "binding_digest": "0" * 64}),
                   canonical({**original, "initial_execution_plan_digest": "0" * 64}),
                   canonical({**original, "requested_at": 10 ** 1000}),
                   canonical({**original, "unexpected": True})]
        for encoded in corrupt:
            with self.subTest(encoded=encoded):
                with sqlite3.connect(self.db) as conn:
                    conn.execute("UPDATE run_cancellations SET cancellation_json=?", (encoded,))
                before = self.rows()
                self.assert_error("CORRUPT_STATE", lambda: self.state.cancellation("run-cancel"))
                self.assert_error("CORRUPT_STATE", lambda: self.state.claim("run-cancel", "worker"))
                self.assert_error("CORRUPT_STATE", lambda: self.state.snapshot("run-cancel"))
                self.assertEqual(self.rows(), before)

    def test_uncancelled_run_retains_snapshot_shape_and_finalization(self):
        before = self.state.snapshot("run-cancel")
        self.assertNotIn("cancellation", before)
        self.assertIsNone(self.state.cancellation("run-cancel"))
        self.assertEqual(self.state.create_run(self.plan), self.plan)
        self.reports()
        checkpoint = self.checkpoint()
        self.state.prepare_finalization("run-cancel", checkpoint)
        for job, result in checkpoint["accepts"].items():
            self.state.accept("run-cancel", job, result, "ref/verification", "owner")
        receipt = {"run_id": "run-cancel", "binding_digest": self.plan["binding_digest"],
                   "finalization_checkpoint_digest": digest(checkpoint)}
        self.state.pin_final_receipt("run-cancel", digest(checkpoint), receipt)
        self.assertEqual(self.reopen().finalization("run-cancel")["receipt"], receipt)
        final = self.state.snapshot("run-cancel")
        self.assertEqual(set(final), set(before))
        self.assertEqual(final["accepted"], 2)
        self.assertEqual(final["budget"]["attempts_used"], 2)


if __name__ == "__main__":
    unittest.main()
