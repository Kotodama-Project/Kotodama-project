"""Deterministic work bounds for retained local swarm history."""
from __future__ import annotations

import copy
import sqlite3
import unittest

import test_task_swarm_state as state_fixtures
import test_task_swarm_transport as transport_fixtures
from task_swarm.protocol import SwarmError


class SchedulerScalabilityTests(unittest.TestCase):
    setUp = state_fixtures.SwarmStateTests.setUp
    tearDown = state_fixtures.SwarmStateTests.tearDown
    state = state_fixtures.SwarmStateTests.state
    plan = state_fixtures.SwarmStateTests.plan
    job = staticmethod(state_fixtures.SwarmStateTests.job)

    def trace(self, state):
        statements = []
        original = state._connect

        def connect():
            connection = original()
            connection.set_trace_callback(statements.append)
            return connection

        state._connect = connect
        return statements

    def test_large_snapshot_batches_attempts_and_keeps_order_and_acceptance(self):
        state = self.state()
        state.create_run(self.plan([self.job(f"job-{n:03}") for n in range(100)], budget=150))
        first = state.claim("run-demo", "worker-a")
        state.fail(first["token"], "retry", retryable=True)
        second = state.claim("run-demo", "worker-b")
        state.report(second["token"], "result", "c" * 64, "candidate", "runtime")
        state.accept("run-demo", second["job_id"], "c" * 64, "verification", "owner")
        statements = self.trace(state)

        snapshot = state.snapshot("run-demo")
        attempt_queries = [sql for sql in statements if sql.startswith("SELECT * FROM attempts")]
        self.assertEqual(len(attempt_queries), 1, "snapshot must not issue one history query per job")
        self.assertEqual(len(snapshot["jobs"]), 100)
        job = snapshot["jobs"]["job-000"]
        self.assertEqual([attempt["attempt"] for attempt in job["attempts"]], [1, 2])
        self.assertEqual([attempt["state"] for attempt in job["attempts"]], ["failed", "accepted"])
        self.assertEqual(job["current_attempt"]["token"], second["token"])
        self.assertEqual(job["accepted"]["verification_ref"], "verification")
        self.assertEqual(snapshot["budget"]["attempts_used"], 2)
        self.assertEqual(snapshot["jobs"]["job-099"]["attempts"], [])

    def test_many_conflicting_candidates_read_global_leases_once(self):
        state = self.state()
        state.create_run(self.plan([self.job("held", keys=["shared-resource"])]))
        state.claim("run-demo", "holder")
        second = self.plan([self.job(f"job-{n:03}", keys=["shared-resource"]) for n in range(100)])
        second["run_id"] = "second-run"
        state.create_run(second)
        statements = self.trace(state)

        self.assertIsNone(state.claim("second-run", "worker"))
        lease_queries = [sql for sql in statements if sql.startswith("SELECT exclusive_keys_json FROM jobs")]
        self.assertEqual(len(lease_queries), 1)
        self.assertEqual(state.snapshot("second-run")["budget"]["attempts_used"], 0)

    def test_retained_jobs_do_not_require_a_full_scan_for_global_leases(self):
        state = self.state()
        state.create_run(self.plan([self.job("held", keys=["shared-resource"])]))
        state.claim("run-demo", "holder")
        for number in range(10):
            retained = self.plan([self.job(f"job-{job:03}") for job in range(1_000)], budget=0)
            retained["run_id"] = f"retained-run-{number}"
            state.create_run(retained)
        connection = state._connect()
        try:
            steps = [0]
            connection.set_progress_handler(lambda: steps.__setitem__(0, steps[0] + 1) or 0, 1)
            self.assertEqual(state._leased_exclusive_keys(connection), {"shared-resource"})
            self.assertLess(steps[0], 100, "lease lookup work must be independent of retained jobs")
        finally:
            connection.close()


class TransportScalabilityTests(unittest.TestCase):
    setUp = transport_fixtures.TransportTests.setUp
    tearDown = transport_fixtures.TransportTests.tearDown
    _binding = transport_fixtures.TransportTests._binding
    _reader = transport_fixtures.TransportTests._reader
    _authorize = staticmethod(transport_fixtures.TransportTests._authorize)
    _transport = transport_fixtures.TransportTests._transport
    _request = transport_fixtures.TransportTests._request

    def test_pending_ack_checks_use_one_query_and_still_refuse_corrupt_ack(self):
        transport = self._transport()
        for number in range(40):
            message_id = f"acked-{number}"
            sent = transport.send(self._request(message_id=message_id, idempotency_key=message_id))
            transport.ack("task-1", "receiver", message_id, sent["payload_digest"], 1, "inv-receiver-1")
        statements = []
        original = transport._connect

        def connect():
            connection = original()
            connection.set_trace_callback(statements.append)
            return connection

        transport._connect = connect
        transport.max_pending = 1
        transport.send(self._request())
        self.assertFalse(any(sql.startswith("SELECT * FROM acknowledgements") for sql in statements))
        with sqlite3.connect(self.db_path) as connection:
            connection.execute("UPDATE acknowledgements SET actor_ref='foreign' WHERE message_id='acked-39'")
        with self.assertRaisesRegex(SwarmError, "CORRUPT_STORE"):
            transport.send(self._request(message_id="second", idempotency_key="second"))

    def test_receive_materializes_only_the_requested_authorized_rows(self):
        transport = self._transport(max_pending=100)
        for number in range(100):
            transport.send(self._request(message_id=f"message-{number}", idempotency_key=f"key-{number}"))
        materialized = []
        original = transport._connect

        class TrackingCursor:
            def __init__(self, cursor):
                self.cursor = cursor

            def __iter__(self):
                for row in self.cursor:
                    materialized.append(row["message_id"])
                    yield row

            def fetchall(self):
                rows = self.cursor.fetchall()
                materialized.extend(row["message_id"] for row in rows)
                return rows

        class TrackingConnection:
            def __init__(self, connection):
                self.connection = connection

            def execute(self, sql, parameters=()):
                cursor = self.connection.execute(sql, parameters)
                return TrackingCursor(cursor) if sql.lstrip().startswith("SELECT m.* FROM messages AS m") else cursor

            def close(self):
                self.connection.close()

        transport._connect = lambda: TrackingConnection(original())
        received = transport.receive("task-1", "receiver", limit=1)
        self.assertEqual([row["message_id"] for row in received], ["message-0"])
        self.assertEqual(materialized, ["message-0"])

    def test_reopened_store_quota_work_skips_expired_and_prior_owner_history(self):
        transport = self._transport()
        transport.send(self._request())
        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            row = dict(connection.execute("SELECT * FROM messages LIMIT 1").fetchone())
            columns = [key for key in row if key != "row_id"]
            insert = f"INSERT INTO messages ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})"
            retained = []
            for number in range(10_000):
                value = copy.deepcopy(row)
                value.update(message_id=f"retained-{number}", idempotency_key=f"retained-{number}", stored_at=90)
                if number % 2:
                    value["expires_at"] = 99
                else:
                    value["owner_ref"] = "prior-owner"
                retained.append(tuple(value[key] for key in columns))
            connection.executemany(insert, retained)
            # Simulate a store created by the earlier schema. Construction
            # upgrades its indexes without changing messages or receipts.
            connection.execute("DROP INDEX ix_messages_live_scope")
            connection.execute("DROP INDEX ix_messages_live_recipient")
        transport = self._transport()
        steps = [0]
        original = transport._connect

        def connect():
            connection = original()
            connection.set_progress_handler(lambda: steps.__setitem__(0, steps[0] + 1) or 0, 1)
            return connection

        transport._connect = connect
        sent = transport.send(self._request(message_id="fresh", idempotency_key="fresh"))
        self.assertEqual(sent["message_id"], "fresh")
        self.assertLess(steps[0], 2_000, "quota admission must not scan retained Task scopes")
        self.assertEqual([row["message_id"] for row in transport.receive("task-1", "receiver")], ["m-1", "fresh"])


if __name__ == "__main__":
    unittest.main()
