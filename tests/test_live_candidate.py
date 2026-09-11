"""Synthetic contract tests only; these do not establish Discord/Live deployment."""
import asyncio
import base64
from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from runtime.live.control import (
    BotLeases, Busy, Denied, Grant, Intent, Ledger, PlaybackGate, Receipt,
    RoomController, RoomHub, RoomKey,
)
from runtime.live.openai_live import LiveSession


ROOM = RoomKey("discord", "example-guild", "example-room")
OTHER = RoomKey("discord", "example-guild", "other-room")


class ControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.ledger = Ledger(self.root / "work.sqlite")
        self.calls = []
        self.now = 100.0

        async def runner(intent, workspace, check):
            check()
            self.calls.append((intent, workspace))
            return Receipt("succeeded", "local-test-receipt")

        self.runner = runner
        self.room = RoomController(ROOM, self.root, self.ledger, runner, lambda: self.now)
        self.room.consent.add("alice")
        self.grant = Grant("grant-1", ROOM, "alice", frozenset({"code.edit"}), 200)
        self.room.grants[self.grant.grant_id] = self.grant
        self.intent = Intent(ROOM, "alice", "source-1", 1, "変更を実装して", "code.edit", True, True)

    async def asyncTearDown(self):
        self.room.stop()
        await self.room.drain()
        self.ledger.close()
        self.temp.cleanup()

    async def test_addressed_work_runs_and_returns_receipt(self):
        receipt = await self.room.submit(self.intent, self.grant)
        self.assertEqual(receipt.status, "succeeded")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.ledger.state(self.intent.key), "succeeded")

    async def test_unauthorized_variants_never_execute(self):
        cases = [replace(self.intent, addressed=False), replace(self.intent, complete=False),
                 replace(self.intent, room=OTHER), replace(self.intent, actor="bob"),
                 replace(self.intent, operation="shell"), replace(self.intent, operation="deploy"),
                 replace(self.intent, operation="code.test"), replace(self.intent, addressed=1)]
        for intent in cases:
            with self.subTest(intent=intent), self.assertRaises(Denied):
                self.room.submit(intent, self.grant)
        self.assertEqual(self.calls, [])

    async def test_missing_consent(self):
        self.room.consent.clear()
        with self.assertRaises(Denied):
            self.room.submit(self.intent, self.grant)

    async def test_revoked_expired_or_wrong_grant(self):
        for grant in [replace(self.grant, expires_at=99), replace(self.grant, actor="bob"),
                      replace(self.grant, room=OTHER), replace(self.grant, grant_id="forged")]:
            with self.subTest(grant=grant), self.assertRaises(Denied):
                self.room.submit(self.intent, grant)
        self.room.grants.clear()
        with self.assertRaises(Denied):
            self.room.submit(self.intent, self.grant)

    async def test_expiry_rechecked_after_scheduling(self):
        task = self.room.submit(self.intent, self.grant)
        self.now = 201
        self.assertIsNone(await task)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.ledger.state(self.intent.key), "rejected")

    async def test_replay_during_work_and_after_restart(self):
        task = self.room.submit(self.intent, self.grant)
        self.assertIsNone(self.room.submit(self.intent, self.grant))
        await task
        reopened = Ledger(self.root / "work.sqlite")
        try:
            self.assertFalse(reopened.claim(self.intent))
        finally:
            reopened.close()
        self.assertEqual(len(self.calls), 1)

    async def test_same_revision_cannot_change_task(self):
        await self.room.submit(self.intent, self.grant)
        with self.assertRaises(Denied):
            self.room.submit(replace(self.intent, text="別の変更"), self.grant)

    async def test_different_revision_allowed_after_receipt(self):
        await self.room.submit(self.intent, self.grant)
        await self.room.submit(replace(self.intent, revision=2, text="訂正した変更"), self.grant)
        self.assertEqual(len(self.calls), 2)

    async def test_single_writer_room_lock_across_connections(self):
        self.ledger.claim(self.intent)
        reopened = Ledger(self.root / "work.sqlite")
        try:
            with self.assertRaises(Busy):
                reopened.claim(replace(self.intent, source_id="source-2"))
            self.assertTrue(reopened.claim(replace(self.intent, room=OTHER)))
        finally:
            reopened.close()

    async def test_runner_exception_is_uncertain_not_success_or_retry(self):
        async def fail(*args):
            raise OSError("private diagnostic")
        self.room.runner = fail
        self.assertIsNone(await self.room.submit(self.intent, self.grant))
        self.assertEqual(self.ledger.state(self.intent.key), "uncertain")
        with self.assertRaises(Busy):
            self.room.submit(replace(self.intent, source_id="new"), self.grant)

    async def test_no_receipt_is_not_a_success(self):
        async def invalid(*args):
            return Receipt("succeeded", "")
        self.room.runner = invalid
        self.assertIsNone(await self.room.submit(self.intent, self.grant))
        self.assertEqual(self.ledger.state(self.intent.key), "uncertain")

    async def test_stop_before_dispatch_fences_future_work(self):
        task = self.room.submit(self.intent, self.grant)
        self.room.stop()
        await self.room.drain()
        self.assertTrue(task.cancelled())
        self.assertEqual(self.calls, [])
        self.assertEqual(self.ledger.state(self.intent.key), "uncertain")
        with self.assertRaises(Denied):
            self.room.submit(self.intent, self.grant)

    async def test_tool_step_can_recheck_revocation(self):
        entered, proceed = asyncio.Event(), asyncio.Event()
        async def checking(intent, workspace, check):
            entered.set()
            await proceed.wait()
            check()
            self.calls.append((intent, workspace))
            return Receipt("succeeded", "receipt")
        self.room.runner = checking
        task = self.room.submit(self.intent, self.grant)
        await entered.wait()
        self.room.grants.clear()
        proceed.set()
        self.assertIsNone(await task)
        self.assertEqual(self.calls, [])

    async def test_room_work_does_not_block_another_room(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def slow(intent, workspace, check):
            entered.set()
            await release.wait()
            check()
            return Receipt("succeeded", "slow-receipt")
        self.room.runner = slow
        first = self.room.submit(self.intent, self.grant)
        await entered.wait()
        other = RoomController(OTHER, self.root, self.ledger, self.runner, lambda: 100)
        other.consent.add("bob")
        grant = replace(self.grant, room=OTHER, actor="bob")
        other.grants[grant.grant_id] = grant
        await other.submit(replace(self.intent, room=OTHER, actor="bob"), grant)
        self.assertFalse(first.done())
        release.set()
        await first

    async def test_hub_creates_and_reuses_only_allowlisted_workspaces(self):
        hub = RoomHub(frozenset({ROOM, OTHER}), self.root, self.ledger, self.runner)
        first = hub.join(ROOM)
        self.assertIs(first, hub.join(ROOM))
        self.assertNotEqual(first.workspace, hub.join(OTHER).workspace)
        with self.assertRaises(Denied):
            hub.join(RoomKey("slack", ROOM.tenant, ROOM.channel))
        await hub.leave(ROOM)
        self.assertTrue(first.stopped)
        self.assertIsNot(first, hub.join(ROOM))
        await hub.leave(ROOM)
        await hub.leave(OTHER)

    async def test_workspace_symlink_rejected(self):
        (self.root / OTHER.key).symlink_to(self.room.workspace, target_is_directory=True)
        with self.assertRaises(Denied):
            RoomController(OTHER, self.root, self.ledger, self.runner)


class IdentityAndPlaybackTests(unittest.TestCase):
    def test_namespaced_room_keys_are_unambiguous(self):
        keys = [ROOM, OTHER, RoomKey("teams", ROOM.tenant, ROOM.channel),
                RoomKey("discord", "other-guild", ROOM.channel),
                RoomKey("discord", "a:b", "c"), RoomKey("discord", "a", "b:c")]
        self.assertEqual(len({r.key for r in keys}), len(keys))
        self.assertNotIn("/", RoomKey("discord", "..", "../../etc").key)

    def test_invalid_identities_and_expiry(self):
        for args in [("unsupported", "g", "c"), ("discord", "", "c")]:
            with self.assertRaises(Denied):
                RoomKey(*args)
        with self.assertRaises(Denied):
            Grant("grant", ROOM, "alice", frozenset(), float("nan"))

    def test_bot_pool_does_not_steal_other_channel(self):
        pool = BotLeases(("bot-a", "bot-b"))
        self.assertEqual(pool.acquire(ROOM), pool.acquire(ROOM))
        self.assertNotEqual(pool.acquire(ROOM), pool.acquire(OTHER))
        with self.assertRaises(Busy):
            pool.acquire(RoomKey("discord", ROOM.tenant, "third-room"))
        self.assertEqual(pool.acquire(RoomKey("discord", "other-guild", "room")), "bot-a")
        pool.release(ROOM)
        self.assertEqual(pool.acquire(RoomKey("discord", ROOM.tenant, "third-room")), "bot-a")

    def test_invalid_pool(self):
        for bots in [(), ("a", "a"), ("",)]:
            with self.assertRaises(Denied):
                BotLeases(bots)
        with self.assertRaises(Denied):
            BotLeases(("a",)).acquire(RoomKey("slack", "t", "c"))

    def test_silent_by_default_bounded_and_fresh_session_only(self):
        now = [0.0]
        gate = PlaybackGate(lambda: now[0])
        self.assertEqual(gate.filter("listen", b"00"), b"")
        with self.assertRaises(Denied):
            gate.open("reply", addressed=False)
        gate.open("reply", addressed=True, seconds=2)
        self.assertEqual(gate.filter("listen", b"00"), b"")
        self.assertEqual(gate.filter("reply", b"00"), b"00")
        with self.assertRaises(Busy):
            gate.open("reply-2", addressed=True)
        now[0] = 2.0
        self.assertEqual(gate.filter("reply", b"00"), b"")
        with self.assertRaises(Denied):
            gate.open("reply", addressed=True)
        gate.open("reply-2", addressed=True)
        self.assertEqual(gate.filter("reply", b"00"), b"")
        gate.revoke()
        self.assertEqual(gate.filter("reply-2", b"00"), b"")


class FakeConnection:
    def __init__(self):
        self.events = asyncio.Queue()
        self.sent = []
        self.terminated = False
        async def start(**kwargs):
            self.sent.append(("start", kwargs))
            await self.events.put({"type": "session.started", "session": {"id": "live-1"}})
        async def append(**kwargs):
            self.sent.append(("audio", kwargs))
        async def thinking(**kwargs):
            self.sent.append(("thinking", kwargs))
        async def close():
            self.sent.append(("close", {}))
            await self.events.put({"type": "session.closed", "usage": {"example": 1}})
        self.session = SimpleNamespace(start=start, input_audio=SimpleNamespace(append=append),
                                       thinking=SimpleNamespace(append=thinking), close=close)
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        return False
    def __aiter__(self):
        return self
    async def __anext__(self):
        event = await self.events.get()
        if event is None:
            raise StopAsyncIteration
        return event
    async def close(self):
        self.terminated = True
        await self.events.put(None)


class LiveProtocolTests(unittest.IsolatedAsyncioTestCase):
    def make(self, **options):
        self.fragments, self.delegations, self.audio, self.usage = [], [], [], []
        return LiveSession(ROOM, "alice", self.fragments.append,
                           lambda *x: self.delegations.append(x),
                           lambda *x: self.audio.append(x), self.usage.append,
                           consented=True, **options)

    def start(self, session):
        session.handle({"type": "session.started", "session": {"id": "live-1"}})

    async def test_official_sdk_contract_and_graceful_finalization(self):
        session, conn = self.make(), FakeConnection()
        client = SimpleNamespace(live=SimpleNamespace(connect=lambda: conn))
        task = asyncio.create_task(session.serve(client))
        await session.started.wait()
        config = conn.sent[0][1]["session"]
        self.assertEqual(config["model"], "gpt-live-1")
        self.assertEqual(config["delegation"], {"type": "client"})
        self.assertFalse(config["store"])
        await session.audio(b"\x00\x00" * 240)
        session.handle({"type": "session.delegation.created", "offset_ms": 10,
                        "delegation": {"id": "opaque-id", "target": "client"}})
        await session.quiet_result("opaque-id", "Verified local test finished.")
        self.assertEqual(conn.sent[-1][0], "thinking")
        self.assertEqual(conn.sent[-1][1]["delegation_id"], "opaque-id")
        await session.close()
        await task
        self.assertTrue(session.finalized)
        self.assertEqual(self.usage, [{"example": 1}])
        self.assertIsNone(session.connection)

    async def test_requires_cloud_consent(self):
        with self.assertRaises(Denied):
            LiveSession(ROOM, "alice", lambda _: None, lambda *_: None,
                        lambda *_: None, lambda _: None)

    async def test_audio_requires_started_and_correct_pcm_samples(self):
        session = self.make()
        with self.assertRaises(Denied):
            await session.audio(b"00")
        self.start(session)
        session.connection = FakeConnection()
        for bad in [b"", b"0", b"0" * 48002]:
            with self.assertRaises(Denied):
                await session.audio(bad)

    async def test_transcripts_preserve_text_times_and_source_not_bot_identity(self):
        session = self.make()
        self.start(session)
        for i, text in enumerate([" こと", "だま", "、変更して"]):
            session.handle({"type": "session.input_transcript.delta", "event_id": str(i),
                            "delta": text, "start_ms": i * 100, "end_ms": (i + 1) * 100})
        self.assertEqual("".join(f.text for f in self.fragments), " ことだま、変更して")
        self.assertTrue(all(f.actor == "alice" and f.room == ROOM for f in self.fragments))
        self.assertEqual(self.delegations, [])
        session.handle({"type": "session.output_transcript.delta", "delta": "ok",
                        "start_ms": 250, "end_ms": 400})
        self.assertIsNone(self.fragments[-1].actor)
        self.assertTrue(self.fragments[-1].assistant)

    async def test_metadata_only_delegation_is_not_task_text_and_is_deduplicated(self):
        session = self.make()
        self.start(session)
        event = {"type": "session.delegation.created", "offset_ms": 4,
                 "delegation": {"id": "opaque", "target": "client"}}
        session.handle(event)
        session.handle(event)
        self.assertEqual(self.delegations, [("opaque", 4)])

    async def test_default_adapter_never_plays_generated_audio(self):
        session = self.make()
        self.start(session)
        session.handle({"type": "session.output_audio.delta", "delta": "AAA="})
        self.assertEqual(self.audio, [])

    async def test_only_fresh_permitted_reply_session_can_play(self):
        gate = PlaybackGate()
        session = self.make(playback_gate=gate)
        self.start(session)
        event = {"type": "session.output_audio.delta", "delta": "AAA="}
        session.handle(event)
        self.assertEqual(self.audio, [])
        gate.open("live-1", addressed=True)
        session.handle(event)
        self.assertEqual(self.audio, [("live-1", b"\x00\x00")])
        session.revoke_consent()
        session.handle(event)
        self.assertEqual(len(self.audio), 1)
        session.handle({"type": "session.input_transcript.delta", "delta": "private",
                        "start_ms": 0, "end_ms": 1})
        self.assertEqual(self.fragments, [])

    async def test_rejects_unknown_delegation_and_oversized_result(self):
        session = self.make()
        self.start(session)
        session.connection = FakeConnection()
        with self.assertRaises(Denied):
            await session.quiet_result("unknown", "text")
        session.delegations.add("known")
        with self.assertRaises(Denied):
            await session.quiet_result("known", "あ" * 167)

    async def test_transport_failure_is_not_final_usage(self):
        session, conn = self.make(), FakeConnection()
        task = asyncio.create_task(session.serve(SimpleNamespace(
            live=SimpleNamespace(connect=lambda: conn))))
        await session.started.wait()
        await conn.events.put(None)
        with self.assertRaises(RuntimeError):
            await task
        self.assertFalse(session.finalized)
        self.assertEqual(self.usage, [])

    async def test_close_timeout_terminates_transport_without_claiming_usage(self):
        session, conn = self.make(), FakeConnection()
        async def no_ack():
            return None
        conn.session.close = no_ack
        task = asyncio.create_task(session.serve(SimpleNamespace(
            live=SimpleNamespace(connect=lambda: conn))))
        await session.started.wait()
        with self.assertRaises(TimeoutError):
            await session.close(timeout=0.01)
        with self.assertRaises(RuntimeError):
            await task
        self.assertTrue(conn.terminated)
        self.assertFalse(session.finalized)

    async def test_shared_context_uses_null_delegation_and_remains_quiet(self):
        session = self.make()
        self.start(session)
        session.connection = FakeConnection()
        await session.quiet_context("Bob is discussing the same workspace; no new action was approved.")
        self.assertEqual(session.connection.sent[-1][0], "thinking")
        self.assertIsNone(session.connection.sent[-1][1]["delegation_id"])

    async def test_concurrent_serve_is_rejected_and_close_is_idempotent(self):
        session, conn = self.make(), FakeConnection()
        client = SimpleNamespace(live=SimpleNamespace(connect=lambda: conn))
        task = asyncio.create_task(session.serve(client))
        await session.started.wait()
        with self.assertRaises(Denied):
            await session.serve(client)
        await asyncio.gather(session.close(), session.close())
        await task
        self.assertEqual(sum(kind == "close" for kind, _ in conn.sent), 1)

    async def test_missing_start_event_times_out_without_sending_audio(self):
        session, conn = self.make(), FakeConnection()
        async def no_start(**kwargs):
            return None
        conn.session.start = no_start
        with self.assertRaises(TimeoutError):
            await session.serve(SimpleNamespace(live=SimpleNamespace(connect=lambda: conn)),
                                start_timeout=0.01)
        self.assertFalse(session.started.is_set())
        self.assertFalse(session.finalized)
        self.assertIsNone(session.connection)

    async def test_unsupported_sdk_does_not_silently_fall_back_to_realtime(self):
        with self.assertRaises(RuntimeError):
            await self.make().serve(SimpleNamespace(realtime=object()))

    async def test_invalid_event_order_interval_and_provider_error(self):
        session = self.make()
        with self.assertRaises(Denied):
            session.handle({"type": "session.output_audio.delta", "delta": "AAA="})
        self.start(session)
        with self.assertRaises(Denied):
            session.handle({"type": "session.input_transcript.delta", "delta": "x",
                            "start_ms": 2, "end_ms": 1})
        with self.assertRaises(RuntimeError):
            session.handle({"type": "error", "error": {"message": "not copied"}})


if __name__ == "__main__":
    unittest.main()
