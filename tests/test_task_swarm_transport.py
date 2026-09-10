import concurrent.futures
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))

from task_swarm.protocol import SwarmError, digest
from task_swarm.transport import PeerTransport


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.now = [100.0]
        self.actors = {}
        for actor, capability in (("sender", "grant-s"), ("receiver", "grant-r")):
            self.actors[actor] = self._binding(actor, capability)
        temporary_root = Path(__file__).resolve().parents[1] / "work"
        temporary_root.mkdir(exist_ok=True)
        self._temp = tempfile.TemporaryDirectory(dir=temporary_root)
        self.db_path = Path(self._temp.name) / "swarm.db"

    def tearDown(self):
        self._temp.cleanup()

    def _binding(self, actor, capability, *, epoch=1, invocation=None, status="active", expires=200.0):
        return {
            "task_id": "task-1",
            "revision": 1,
            "context_digest": "a" * 64,
            "owner_ref": "owner-1",
            "active_home": "home-1",
            "authority_ref": "authority-1",
            "capability_ref": capability,
            "expires_at": expires,
            "status": "active",
            "actor_ref": actor,
            "epoch": epoch,
            "invocation_ref": invocation or f"inv-{actor}-{epoch}",
            "actor_status": status,
        }

    def _reader(self, task_id, actor_ref):
        binding = self.actors[actor_ref]
        if binding["task_id"] != task_id:
            raise KeyError(task_id)
        return dict(binding)

    @staticmethod
    def _authorize(binding, actor_ref, peer_ref, action):
        return actor_ref != peer_ref and action in {"send", "receive", "ack", "reply", "status"}

    def _transport(self, **kwargs):
        return PeerTransport(
            self.db_path,
            self._reader,
            self._authorize,
            clock=lambda: self.now[0],
            **kwargs,
        )

    def _request(self, **changes):
        request = {
            "message_id": "m-1",
            "idempotency_key": "key-1",
            "task_id": "task-1",
            "revision": 1,
            "context_digest": "a" * 64,
            "owner_ref": "owner-1",
            "active_home": "home-1",
            "authority_ref": "authority-1",
            "capability_ref": "grant-s",
            "sender_ref": "sender",
            "recipient_ref": "receiver",
            "sender_epoch": 1,
            "invocation_ref": "inv-sender-1",
            "parent_message_id": None,
            "payload_ref": "payload/m-1",
            "payload_digest": digest({"body": "hello"}),
            "expires_at": 180.0,
        }
        request.update(changes)
        return request

    def test_restart_ack_reply_and_status_are_durable(self):
        transport = self._transport()
        sent = transport.send(self._request())
        self.assertEqual(transport.receive("task-1", "receiver")[0]["message_id"], "m-1")
        self.actors["receiver"]["invocation_ref"] = "inv-receiver-2"
        self.actors["receiver"]["epoch"] = 2
        self.assertEqual(
            transport.ack("task-1", "receiver", "m-1", sent["payload_digest"], 2, "inv-receiver-2")["ack"],
            True,
        )
        # The new PeerTransport has no inherited connection or in-memory state.
        restarted = self._transport()
        self.assertEqual(restarted.status("task-1", "sender", "m-1")["state"], "acked")
        reply_request = self._request(
            message_id="r-1",
            idempotency_key="reply-key-1",
            capability_ref="grant-r",
            sender_ref="receiver",
            recipient_ref="sender",
            sender_epoch=2,
            invocation_ref="inv-receiver-2",
            parent_message_id="m-1",
            payload_ref="payload/r-1",
            payload_digest=digest({"body": "reply"}),
            expires_at=175.0,
        )
        reply = restarted.reply(reply_request)
        self.assertEqual(reply["parent_message_id"], "m-1")
        self.assertEqual(restarted.status("task-1", "sender", "m-1")["state"], "replied")
        restarted.ack("task-1", "sender", "r-1", reply["payload_digest"], 1, "inv-sender-1")
        self.assertEqual(restarted.status("task-1", "sender", "m-1")["state"], "reply_acked")

    def test_duplicate_retry_preserves_original_provenance_and_conflicts(self):
        transport = self._transport()
        first = transport.send(self._request())
        original_stored_at = first["stored_at"]
        self.actors["sender"].update(epoch=2, invocation_ref="inv-sender-2")
        replay = transport.send(self._request(sender_epoch=2, invocation_ref="inv-sender-2"))
        self.assertEqual(replay["stored_at"], original_stored_at)
        self.assertEqual(replay["sender_epoch"], 1)
        with self.assertRaisesRegex(SwarmError, "IDEMPOTENCY_CONFLICT"):
            transport.send(self._request(sender_epoch=2, invocation_ref="inv-sender-2", payload_ref="other"))
        # The old worker cannot replay merely because its key exists.
        with self.assertRaisesRegex(SwarmError, "STALE_EPOCH"):
            transport.send(self._request(sender_epoch=1, invocation_ref="inv-sender-1"))
        # A new authorized invocation can observe its logical predecessor's
        # receipt; only a stale invocation trying to write is fenced.
        self.assertEqual(transport.status("task-1", "sender", "m-1")["state"], "stored")

    def test_atomic_pending_quota_under_concurrent_senders(self):
        self.actors["receiver"]["actor_status"] = "idle"
        for index in range(8):
            actor = f"sender-{index}"
            self.actors[actor] = self._binding(actor, f"grant-{actor}")
        transport = self._transport(max_messages=64, max_pending=3)

        def send_one(index):
            actor = f"sender-{index}"
            return transport.send(self._request(
                message_id=f"m-{index}",
                idempotency_key=f"key-{index}",
                capability_ref=f"grant-{actor}",
                sender_ref=actor,
                invocation_ref=f"inv-{actor}-1",
                payload_ref=f"payload/{index}",
            ))

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = []
            failures = []
            for future in [pool.submit(send_one, index) for index in range(8)]:
                try:
                    outcomes.append(future.result())
                except SwarmError as exc:
                    failures.append(exc.code)
        self.assertEqual(len(outcomes), 3)
        self.assertEqual(len(failures), 5)
        self.assertTrue(all(code == "BACKPRESSURE" for code in failures))
        self.assertEqual(len(transport.receive("task-1", "receiver", limit=20)), 3)

    def test_simultaneous_empty_store_initialization_is_bounded(self):
        def construct(_):
            return PeerTransport(self.db_path, self._reader, self._authorize, clock=lambda: self.now[0])

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            transports = list(pool.map(construct, range(8)))
        self.assertEqual(len(transports), 8)
        transports[0].send(self._request())
        self.assertEqual(transports[-1].receive("task-1", "receiver")[0]["message_id"], "m-1")

    def test_expired_backlog_does_not_hide_fresh_traffic(self):
        transport = self._transport(max_messages=2, max_pending=2)
        transport.send(self._request(message_id="old-1", idempotency_key="old-1", expires_at=101.0))
        transport.send(self._request(message_id="old-2", idempotency_key="old-2", expires_at=101.0))
        self.now[0] = 102.0
        fresh = transport.send(self._request(message_id="fresh", idempotency_key="fresh", expires_at=190.0))
        self.assertEqual(fresh["message_id"], "fresh")
        self.assertEqual([m["message_id"] for m in transport.receive("task-1", "receiver")], ["fresh"])
        self.assertEqual(transport.status("task-1", "sender", "old-1")["state"], "expired")

    def test_wrong_recipient_digest_missing_ack_and_nonfinite_limit_refuse(self):
        transport = self._transport()
        transport.send(self._request())
        with self.assertRaisesRegex(SwarmError, "MESSAGE_NOT_FOUND"):
            transport.read_message("task-1", "sender", "m-1")
        with self.assertRaisesRegex(SwarmError, "DIGEST_MISMATCH"):
            transport.ack("task-1", "receiver", "m-1", digest("tampered"), 1, "inv-receiver-1")
        reply_request = self._request(
            message_id="r-1",
            idempotency_key="r-key",
            capability_ref="grant-r",
            sender_ref="receiver",
            recipient_ref="sender",
            sender_epoch=1,
            invocation_ref="inv-receiver-1",
            parent_message_id="m-1",
            payload_ref="payload/r-1",
            payload_digest=digest("reply"),
        )
        with self.assertRaisesRegex(SwarmError, "MISSING_ACK"):
            transport.reply(reply_request)
        with self.assertRaisesRegex(SwarmError, "INVALID_LIMIT"):
            transport.receive("task-1", "receiver", float("nan"))

    def test_receive_skips_forbidden_peer_and_status_hides_foreign_actor(self):
        revoked = [False]
        def deny_sender(binding, actor_ref, peer_ref, action):
            return not (revoked[0] and action == "receive" and peer_ref == "blocked")

        self.actors["blocked"] = self._binding("blocked", "grant-blocked")
        transport = PeerTransport(self.db_path, self._reader, deny_sender, clock=lambda: self.now[0])
        transport.send(self._request())
        blocked_request = self._request(
            message_id="blocked-msg", idempotency_key="blocked-key",
            capability_ref="grant-blocked", sender_ref="blocked",
            invocation_ref="inv-blocked-1", payload_ref="payload/blocked",
        )
        # The receiver's directed grant decides whether the sender is visible.
        self.actors["receiver"]["actor_status"] = "idle"
        transport.send(blocked_request)
        revoked[0] = True
        self.assertEqual([m["sender_ref"] for m in transport.receive("task-1", "receiver")], ["sender"])
        with self.assertRaisesRegex(SwarmError, "FORBIDDEN"):
            transport.status("task-1", "blocked", "m-1")

    def test_schema_contains_closed_fields(self):
        schema_path = Path(__file__).resolve().parents[1] / "schemas" / "task-swarm-message.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertTrue(schema["additionalProperties"] is False)
        self.assertIn("parent_message_id", schema["required"])
        self.assertEqual(schema["properties"]["state"]["enum"][-1], "stale")


if __name__ == "__main__":
    unittest.main()
