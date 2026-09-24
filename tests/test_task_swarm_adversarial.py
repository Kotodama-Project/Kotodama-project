"""Regressions for independently found transport counterexamples."""
import json
from contextlib import closing
import sqlite3
import unittest
from pathlib import Path

import test_task_swarm_transport as fixtures
from task_swarm.protocol import SwarmError


class AdversarialTransportTests(unittest.TestCase):
    setUp = fixtures.TransportTests.setUp
    tearDown = fixtures.TransportTests.tearDown
    _binding = fixtures.TransportTests._binding
    _reader = fixtures.TransportTests._reader
    _authorize = staticmethod(fixtures.TransportTests._authorize)
    _transport = fixtures.TransportTests._transport
    _request = fixtures.TransportTests._request

    def test_same_key_is_independent_across_context_revisions(self):
        transport = self._transport()
        transport.send(self._request())
        for binding in self.actors.values():
            binding.update(revision=2, context_digest="b"*64)
        request = self._request(message_id="m-2", revision=2, context_digest="b"*64)
        self.assertEqual(transport.send(request)["message_id"], "m-2")

    def test_revoked_peer_rows_do_not_hide_or_backpressure_authorized_messages(self):
        from task_swarm.transport import PeerTransport
        denied = set()
        def authorize(binding, actor, peer, action):
            return not (action == "receive" and peer in denied)
        transport = PeerTransport(self.db_path, self._reader, authorize, clock=lambda:self.now[0], max_messages=100, max_pending=100)
        for number in range(17):
            actor = f"blocked-{number}"
            self.actors[actor] = self._binding(actor, "grant-"+actor)
            transport.send(self._request(message_id=actor, idempotency_key=actor, sender_ref=actor,
                capability_ref="grant-"+actor, invocation_ref=f"inv-{actor}-1"))
            denied.add(actor)
        # Changing grants after ingress does not consume the live receive
        # window or the remaining authorized pending-message capacity.
        transport.max_pending = 1
        transport.send(self._request(message_id="allowed", idempotency_key="allowed"))
        self.assertEqual([m["message_id"] for m in transport.receive("task-1", "receiver", limit=1)], ["allowed"])
        with self.assertRaisesRegex(SwarmError, "FORBIDDEN"):
            transport.send(self._request(message_id="denied", idempotency_key="denied", sender_ref="blocked-0",
                capability_ref="grant-blocked-0", invocation_ref="inv-blocked-0-1"))

    def test_corrupt_ack_is_refused_by_status_and_replay(self):
        for column, value in (("actor_ref", "foreign"), ("payload_digest", "bad"), ("acked_at", "not-a-number"), ("epoch", 0)):
            with self.subTest(column=column):
                self.db_path = self.db_path.parent / (column + ".sqlite")
                transport = self._transport()
                message_id = "m-"+column
                sent = transport.send(self._request(message_id=message_id, idempotency_key=message_id))
                transport.ack("task-1", "receiver", message_id, sent["payload_digest"], 1, "inv-receiver-1")
                with closing(sqlite3.connect(self.db_path)) as connection:
                    connection.execute(f"UPDATE acknowledgements SET {column}=? WHERE message_id=?", (value, message_id))
                    connection.commit()
                with self.assertRaisesRegex(SwarmError, "CORRUPT_STORE"):
                    transport.status("task-1", "sender", message_id)
                with self.assertRaisesRegex(SwarmError, "CORRUPT_STORE"):
                    transport.ack("task-1", "receiver", message_id, sent["payload_digest"], 1, "inv-receiver-1")

    def test_authorized_new_epoch_retains_the_original_ack_status(self):
        transport = self._transport()
        sent = transport.send(self._request())
        transport.ack("task-1", "receiver", "m-1", sent["payload_digest"], 1, "inv-receiver-1")
        self.actors["sender"].update(epoch=2, invocation_ref="inv-sender-2")
        replay = transport.send(self._request(sender_epoch=2, invocation_ref="inv-sender-2"))
        self.assertEqual(replay["sender_epoch"], 1)
        self.assertEqual(transport.status("task-1", "sender", "m-1")["state"], "acked")
        with self.assertRaisesRegex(SwarmError, "STALE_EPOCH"):
            transport.send(self._request())

    def test_expired_lookup_and_ack_replay_are_refused(self):
        transport = self._transport()
        sent = transport.send(self._request())
        transport.ack("task-1", "receiver", "m-1", sent["payload_digest"], 1, "inv-receiver-1")
        self.now[0] = 181
        with self.assertRaisesRegex(SwarmError, "EXPIRED_MESSAGE"):
            transport.read_message("task-1", "receiver", "m-1")
        with self.assertRaisesRegex(SwarmError, "EXPIRED_MESSAGE"):
            transport.ack("task-1", "receiver", "m-1", sent["payload_digest"], 1, "inv-receiver-1")

    def test_schema_and_runtime_agree_revision_starts_at_one(self):
        import jsonschema
        path = Path(__file__).resolve().parents[1]/"schemas/task-swarm-message.schema.json"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(self._request(revision=0), json.loads(path.read_text(encoding="utf-8")))

    def test_status_refuses_foreign_scope_reply(self):
        transport = self._transport()
        sent = transport.send(self._request())
        transport.ack("task-1", "receiver", "m-1", sent["payload_digest"], 1, "inv-receiver-1")
        transport.reply(self._request(message_id="reply", idempotency_key="reply", parent_message_id="m-1",
            sender_ref="receiver", recipient_ref="sender", capability_ref="grant-r", invocation_ref="inv-receiver-1"))
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute("UPDATE messages SET task_id='foreign-task' WHERE message_id='reply'")
            connection.commit()
        with self.assertRaisesRegex(SwarmError, "CORRUPT_STORE"):
            transport.status("task-1", "sender", "m-1")


if __name__ == "__main__":
    unittest.main()
