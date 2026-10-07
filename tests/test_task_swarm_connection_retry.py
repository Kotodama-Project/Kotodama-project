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
        for operation, clock in ((lambda: transport.send(self._request()), [0.0, 0.0, 3.0]),
                                 (lambda: transport._read(lambda db: 1), [0.0, 3.0])):
            with mock.patch('task_swarm.transport.sqlite3.connect', side_effect=sqlite3.OperationalError('database is locked')) as connect:
                with mock.patch('task_swarm.transport.time.monotonic', side_effect=clock):
                    with self.assertRaises(SwarmError) as caught:
                        operation()
            self.assertEqual('STORE_BUSY', caught.exception.code)
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

    def test_writer_queue_is_bounded_and_does_not_open_another_database_when_full(self):
        transport = self._transport()
        guard = mock.MagicMock(); guard.acquire.return_value = False
        with mock.patch.object(transport, '_write_guard', guard), mock.patch.object(transport, '_connect') as connect:
            with self.assertRaises(SwarmError) as caught:
                transport.send(self._request())
        self.assertEqual('STORE_BUSY', caught.exception.code)
        guard.acquire.assert_called_once_with(timeout=2.5)
        guard.release.assert_not_called(); connect.assert_not_called()

    def test_writer_queue_releases_after_domain_refusal_and_keeps_its_original_deadline(self):
        transport = self._transport()
        guard = mock.MagicMock(); guard.acquire.return_value = True
        with mock.patch.object(transport, '_write_guard', guard), mock.patch.object(transport, '_connect') as connect:
            with mock.patch('task_swarm.transport.time.monotonic', side_effect=[0.0, 3.0]):
                with self.assertRaises(SwarmError): transport.send(self._request())
        guard.release.assert_called_once(); connect.assert_not_called()
        with mock.patch.object(transport, '_write_guard', guard):
            with self.assertRaises(SwarmError):
                transport._retry_transaction(lambda db: (_ for _ in ()).throw(SwarmError('FORBIDDEN', 'synthetic refusal')))
        self.assertEqual(2, guard.release.call_count)
