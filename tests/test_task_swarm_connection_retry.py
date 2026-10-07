"""Connection setup contention must use the same finite transaction retry."""
import sqlite3
import unittest
from unittest import mock

import tests.test_task_swarm_transport as fixtures
from task_swarm.protocol import SwarmError


class ConnectionRetryTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.TransportTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        self._transport = fixture._transport
        self._request = fixture._request

    def test_send_retries_a_transient_connect_lock_before_running_the_transaction(self):
        transport = self._transport()
        original = sqlite3.connect
        attempts = []

        def connect(*args, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                raise sqlite3.OperationalError('database is locked')
            return original(*args, **kwargs)

        with mock.patch('task_swarm.transport.sqlite3.connect', side_effect=connect):
            sent = transport.send(self._request())
        self.assertEqual('m-1', sent['message_id'])
        self.assertGreaterEqual(len(attempts), 2)
        self.assertEqual(1, len(transport.receive('task-1', 'receiver')))

    def test_read_retries_transient_connect_busy(self):
        transport = self._transport(); transport.send(self._request())
        original = sqlite3.connect
        attempts = []

        def connect(*args, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                raise sqlite3.OperationalError('database is busy')
            return original(*args, **kwargs)

        with mock.patch('task_swarm.transport.sqlite3.connect', side_effect=connect):
            result = transport.status('task-1', 'sender', 'm-1')
        self.assertEqual('stored', result['state']); self.assertEqual(2, len(attempts))

    def test_setup_failure_closes_the_partial_connection_before_retry(self):
        transport = self._transport()
        partial = mock.MagicMock()
        partial.execute.side_effect = sqlite3.OperationalError('database is locked')
        original = sqlite3.connect
        attempts = []

        def connect(*args, **kwargs):
            attempts.append(1)
            return partial if len(attempts) == 1 else original(*args, **kwargs)

        with mock.patch('task_swarm.transport.sqlite3.connect', side_effect=connect):
            transport.send(self._request())
        partial.close.assert_called_once()

    def test_connection_contention_stops_at_the_existing_deadline(self):
        transport = self._transport()
        for operation in (lambda: transport.send(self._request()), lambda: transport._read(lambda db: 1)):
            with mock.patch('task_swarm.transport.sqlite3.connect', side_effect=sqlite3.OperationalError('database is locked')) as connect:
                with mock.patch('task_swarm.transport.time.monotonic', side_effect=[0.0, 3.0]):
                    with self.assertRaises(SwarmError) as caught:
                        operation()
            self.assertEqual('STORE_UNAVAILABLE', caught.exception.code)
            self.assertEqual(1, connect.call_count)

    def test_non_contention_setup_failure_is_not_retried_or_reflected(self):
        transport = self._transport()
        partial = mock.MagicMock()
        partial.execute.side_effect = sqlite3.OperationalError('synthetic private path cannot open')
        with mock.patch('task_swarm.transport.sqlite3.connect', return_value=partial) as connect:
            with self.assertRaises(SwarmError) as caught:
                transport.send(self._request())
        self.assertEqual('STORE_UNAVAILABLE', caught.exception.code)
        self.assertNotIn('private path', str(caught.exception))
        self.assertEqual(1, connect.call_count)
        partial.close.assert_called_once()
