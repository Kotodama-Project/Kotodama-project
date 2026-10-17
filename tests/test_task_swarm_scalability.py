"""Deterministic work bounds for retained local swarm history."""
from __future__ import annotations

import copy
import sqlite3
import re
import unittest
from contextlib import closing

import test_task_swarm_state as state_fixtures
import test_task_swarm_transport as transport_fixtures
from task_swarm.protocol import SwarmError
from task_swarm.sqlite_work import attempt_history_select, global_job_select, normalized_select, selected_tables


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
        attempt_queries = [sql for sql in statements if attempt_history_select(sql)]
        self.assertEqual(len(attempt_queries), 1, "snapshot must not issue one history query per job")
        # Also count aggregate reads: per-job COUNT queries must not evade the
        # history class by returning the same eventual snapshot.
        self.assertLessEqual(sum("attempts" in selected_tables(sql) for sql in statements), 3)
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
        lease_queries = [sql for sql in statements if global_job_select(sql)]
        self.assertEqual(len(lease_queries), 1)
        self.assertEqual(state.snapshot("second-run")["budget"]["attempts_used"], 0)

    def test_query_accounting_observes_projection_alias_and_repeated_reads(self):
        state = self.state()
        state.create_run(self.plan())
        statements = self.trace(state)
        with closing(state._connect()) as connection:
            for query in (
                'select a.token from "attempts" as a where a.run_id=?',
                'SELECT token FROM main.attempts WHERE run_id=?',
                'SELECT COUNT(*) FROM attempts WHERE run_id=?',
                "SELECT j.state FROM jobs AS j WHERE j.state='leased'",
                "select exclusive_keys_json from jobs where state='leased'",
                "SELECT j.run_id FROM jobs j WHERE j.state='leased'",
                "SELECT j.state FROM jobs j WHERE j.run_id IS NOT NULL",
                "SELECT j.exclusive_keys_json FROM jobs j WHERE j.run_id=?",
            ):
                connection.execute(query, () if "?" not in query else ("run-demo",)).fetchall()
        self.assertEqual(sum(attempt_history_select(sql) for sql in statements), 2)
        self.assertEqual(sum(global_job_select(sql) for sql in statements), 4)
        self.assertEqual(sum("attempts" in selected_tables(sql) for sql in statements), 3)

    def test_retained_jobs_do_not_require_a_full_scan_for_global_leases(self):
        state = self.state()
        state.create_run(self.plan([self.job("held", keys=["shared-resource"])]))
        state.claim("run-demo", "holder")

        def query_work():
            connection = state._connect()
            try:
                steps = [0]
                connection.set_progress_handler(lambda: steps.__setitem__(0, steps[0] + 1) or 0, 1)
                self.assertEqual(state._leased_exclusive_keys(connection), {"shared-resource"})
                cold = steps[0]
                steps[0] = 0
                self.assertEqual(state._leased_exclusive_keys(connection), {"shared-resource"})
                return cold, steps[0]
            finally:
                connection.close()

        empty_history = query_work()
        for number in range(10):
            retained = self.plan([self.job(f"job-{job:03}") for job in range(1_000)], budget=0)
            retained["run_id"] = f"retained-run-{number}"
            state.create_run(retained)
        retained_history = query_work()
        # A fresh connection also loads schema metadata. Compare that overhead
        # for this same schema, and bound the actual lookup separately so adding
        # an unrelated table cannot masquerade as a retained-history scan.
        self.assertEqual(retained_history, empty_history, "cold and warm lookup work must ignore retained jobs")
        self.assertLess(retained_history[1], 100, "warm lease lookup work must be bounded")


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
        ack_queries = [sql for sql in statements if "acknowledgements" in selected_tables(sql)]
        self.assertEqual(len(ack_queries), 1, "ACK admission must issue one batched join, not zero observed reads or N+1")
        # SQLite's context manager commits a transaction but does not close it.
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
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

            @staticmethod
            def label(row):
                return row["message_id"] if "message_id" in row.keys() else "<message projection>"

            def __iter__(self):
                for row in self.cursor:
                    materialized.append(self.label(row))
                    yield row

            def fetchone(self):
                row = self.cursor.fetchone()
                if row is not None:
                    materialized.append(self.label(row))
                return row

            def fetchmany(self, *args):
                rows = self.cursor.fetchmany(*args)
                materialized.extend(self.label(row) for row in rows)
                return rows

            def fetchall(self):
                rows = self.cursor.fetchall()
                materialized.extend(self.label(row) for row in rows)
                return rows

        class TrackingConnection:
            def __init__(self, connection):
                self.connection = connection

            def execute(self, sql, parameters=()):
                cursor = self.connection.execute(sql, parameters)
                aggregate = re.search(r"\b(?:count|max|min|sum|avg|total|group_concat)\s*\(", normalized_select(sql))
                return TrackingCursor(cursor) if "messages" in selected_tables(sql) and not aggregate else cursor

            def close(self):
                self.connection.close()

        transport._connect = lambda: TrackingConnection(original())
        received = transport.receive("task-1", "receiver", limit=1)
        self.assertEqual([row["message_id"] for row in received], ["message-0"])
        self.assertEqual(len(materialized), 1)
        self.assertEqual(materialized, ["message-0"])

    def test_reopened_store_quota_work_skips_expired_and_prior_owner_history(self):
        transport = self._transport()
        transport.send(self._request())
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
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
