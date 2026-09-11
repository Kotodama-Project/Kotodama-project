"""Offline-testable Live control plane; no shell, credentials, or transport owner.

Only trusted, authenticated ingress may construct Intent/Grant objects. Model
transcript fragments and delegation events are NOT authorizations. The runner
must enforce the workspace sandbox and return an actual verification receipt.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time
from typing import Awaitable, Callable


class Denied(ValueError):
    """An admission or playback boundary rejected the request."""


class Busy(Denied):
    """Room or Discord bot capacity is already occupied."""


@dataclass(frozen=True)
class RoomKey:
    surface: str
    tenant: str
    channel: str

    def __post_init__(self) -> None:
        if self.surface not in {"discord", "slack", "teams"}:
            raise Denied("unsupported surface")
        if any(not isinstance(v, str) or not v or len(v) > 256
               for v in (self.tenant, self.channel)):
            raise Denied("invalid room identity")

    @property
    def key(self) -> str:
        raw = json.dumps([self.surface, self.tenant, self.channel], ensure_ascii=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Intent:
    """App-finalized semantic intent; never instantiate from a Live delta alone."""
    room: RoomKey
    actor: str
    source_id: str
    revision: int
    text: str
    operation: str
    addressed: bool
    complete: bool

    def __post_init__(self) -> None:
        if not self.actor or not self.source_id or not self.text.strip():
            raise Denied("missing source evidence")
        if type(self.revision) is not int or self.revision < 1:
            raise Denied("invalid source revision")
        if len(self.text) > 16000 or len(self.source_id) > 256:
            raise Denied("intent exceeds bounded input")

    @property
    def key(self) -> str:
        raw = json.dumps([self.room.key, self.actor, self.source_id, self.revision])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Grant:
    """Issued by the host policy service, not the voice model or a display name."""
    grant_id: str
    room: RoomKey
    actor: str
    operations: frozenset[str]
    expires_at: float

    def __post_init__(self) -> None:
        if not self.grant_id or not self.actor or not math.isfinite(self.expires_at):
            raise Denied("invalid grant identity or expiry")


class Ledger:
    """Durable replay fence and single-writer room lock, not a job queue.

    Interrupted/unknown outcomes retain their lock until operator reconciliation.
    Only hashes/status are retained, not conversations or secret tool output.
    """
    def __init__(self, path: Path) -> None:
        self.db = sqlite3.connect(path, timeout=5)
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.execute("""CREATE TABLE IF NOT EXISTS live_work (
            id TEXT PRIMARY KEY, room TEXT NOT NULL, digest TEXT NOT NULL,
            state TEXT NOT NULL, receipt TEXT)""")
        self.db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS live_room_writer
            ON live_work(room) WHERE state IN ('running', 'uncertain')""")
        self.db.commit()

    def claim(self, intent: Intent) -> bool:
        digest = hashlib.sha256(json.dumps(
            [intent.operation, intent.text], ensure_ascii=True
        ).encode("utf-8")).hexdigest()
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            old = self.db.execute(
                "SELECT digest FROM live_work WHERE id=?", (intent.key,)
            ).fetchone()
            if old:
                if old[0] != digest:
                    raise Denied("source revision reused with different content")
                return False
            try:
                self.db.execute("INSERT INTO live_work VALUES (?, ?, ?, 'running', NULL)",
                                (intent.key, intent.room.key, digest))
            except sqlite3.IntegrityError as exc:
                raise Busy("room has running or unreconciled work") from exc
        return True

    def finish(self, key: str, state: str, receipt: str | None = None) -> None:
        if state not in {"succeeded", "failed", "rejected", "uncertain"}:
            raise Denied("invalid work state")
        with self.db:
            self.db.execute("UPDATE live_work SET state=?, receipt=? WHERE id=? AND state='running'",
                            (state, receipt, key))

    def state(self, key: str) -> str | None:
        row = self.db.execute("SELECT state FROM live_work WHERE id=?", (key,)).fetchone()
        return row[0] if row else None

    def close(self) -> None:
        self.db.close()


@dataclass(frozen=True)
class Receipt:
    status: str
    reference: str


Runner = Callable[[Intent, Path, Callable[[], None]], Awaitable[Receipt]]


class RoomController:
    """One instance per room. Safe-code work is automatic within an owner grant.

    No voice command grants capabilities or approves deployments. A directory
    is not a sandbox; execution adapters must enforce OS/process isolation.
    """
    SAFE_OPERATIONS = frozenset({"code.inspect", "code.edit", "code.test"})

    def __init__(self, room: RoomKey, workspace_root: Path, ledger: Ledger,
                 runner: Runner, clock: Callable[[], float] = time.time) -> None:
        root = workspace_root.resolve(strict=True)
        workspace = root / room.key
        if workspace.is_symlink():
            raise Denied("workspace symlink")
        workspace.mkdir(mode=0o700, exist_ok=True)
        if workspace.resolve() != workspace or not workspace.is_dir():
            raise Denied("invalid workspace")
        self.room, self.workspace = room, workspace
        self.ledger, self.runner, self.clock = ledger, runner, clock
        self.consent: set[str] = set()
        self.grants: dict[str, Grant] = {}
        self.stopped = False
        self.tasks: dict[str, asyncio.Task[Receipt | None]] = {}

    def _authorize(self, intent: Intent, grant: Grant) -> None:
        if self.stopped or intent.room != self.room or grant.room != self.room:
            raise Denied("inactive or wrong room")
        if intent.actor not in self.consent or grant.actor != intent.actor:
            raise Denied("unconsented or mismatched speaker")
        if self.grants.get(grant.grant_id) != grant or grant.expires_at <= self.clock():
            raise Denied("missing, revoked, or expired grant")
        if intent.addressed is not True or intent.complete is not True:
            raise Denied("not a complete addressed request")
        if intent.operation not in self.SAFE_OPERATIONS or intent.operation not in grant.operations:
            raise Denied("operation not authorized for automatic execution")

    def submit(self, intent: Intent, grant: Grant) -> asyncio.Task[Receipt | None] | None:
        self._authorize(intent, grant)
        # Fail before claiming when called outside an event loop.
        loop = asyncio.get_running_loop()
        if not self.ledger.claim(intent):
            return None
        task = loop.create_task(self._run(intent, grant))
        self.tasks[intent.key] = task
        task.add_done_callback(lambda _: self.tasks.pop(intent.key, None))
        return task

    async def _run(self, intent: Intent, grant: Grant) -> Receipt | None:
        try:
            self._authorize(intent, grant)  # Recheck after admission/scheduling.
        except Denied:
            self.ledger.finish(intent.key, "rejected")
            return None
        try:
            receipt = await self.runner(intent, self.workspace,
                                        lambda: self._authorize(intent, grant))
            if receipt.status not in {"succeeded", "failed"} or not receipt.reference:
                raise Denied("runner returned no verified receipt")
            # A receipt proves the outcome, not that it is still appropriate to speak.
            self.ledger.finish(intent.key, receipt.status, receipt.reference)
            self._authorize(intent, grant)
            return receipt
        except asyncio.CancelledError:
            # Coroutine cancellation is not proof that a child process was stopped.
            self.ledger.finish(intent.key, "uncertain")
            raise
        except Exception:
            self.ledger.finish(intent.key, "uncertain")
            return None

    def stop(self) -> None:
        self.stopped = True
        self.consent.clear()
        self.grants.clear()
        for key, task in tuple(self.tasks.items()):
            # Also covers cancellation before the coroutine first runs.
            self.ledger.finish(key, "uncertain")
            task.cancel()

    async def drain(self) -> None:
        await asyncio.gather(*tuple(self.tasks.values()), return_exceptions=True)


class BotLeases:
    """Single-process Discord bot-pool admission. Shards are not extra bot IDs."""
    def __init__(self, identities: tuple[str, ...]) -> None:
        if (not identities or any(not isinstance(i, str) or not i for i in identities)
                or len(set(identities)) != len(identities)):
            raise Denied("bot identities must be nonempty and unique")
        self.identities = identities
        self.owners: dict[tuple[str, str], RoomKey] = {}

    def acquire(self, room: RoomKey) -> str:
        if room.surface != "discord":
            raise Denied("Discord bot lease requested for another surface")
        for bot in self.identities:
            if self.owners.get((room.tenant, bot)) == room:
                return bot
        for bot in self.identities:
            key = (room.tenant, bot)
            if key not in self.owners:
                self.owners[key] = room
                return bot
        raise Busy("no bot capacity; do not move another room's connection")

    def release(self, room: RoomKey) -> None:
        for key, owner in tuple(self.owners.items()):
            if owner == room:
                del self.owners[key]


class PlaybackGate:
    """Default-deny output, bound to a fresh reply session and an expiry.

    Listening sessions must NEVER receive a playback permit. Since Live output
    has no response ID/done event, a revoked session cannot be reopened. Start a
    fresh reply session; drop (never buffer) audio outside its permit. The media
    adapter must also flush/recheck its queued frames on revoke/expiry.
    """
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.used: set[str] = set()
        self.session: str | None = None
        self.deadline = 0.0

    def open(self, fresh_session_id: str, *, addressed: bool, seconds: float = 15) -> None:
        if addressed is not True or not fresh_session_id or fresh_session_id in self.used:
            raise Denied("requires a fresh, addressed reply session")
        if not 0 < seconds <= 30:
            raise Denied("reply permit must be bounded")
        if self.session is not None and self.clock() < self.deadline:
            raise Busy("another speaker owns the room reply permit")
        if len(self.used) >= 4096:
            raise Denied("playback session budget exhausted")
        self.used.add(fresh_session_id)
        self.session = fresh_session_id
        self.deadline = self.clock() + seconds

    def filter(self, session_id: str, pcm: bytes) -> bytes:
        if session_id != self.session or self.clock() >= self.deadline:
            return b""
        return pcm

    def revoke(self) -> None:
        self.session = None
        self.deadline = 0.0


class RoomHub:
    """Create/reuse a room workspace only for an operator-allowlisted room.

    Call from one event loop. A production fleet must additionally lease media
    ownership across processes; this registry intentionally claims no such lease.
    """
    def __init__(self, allowed: frozenset[RoomKey], root: Path, ledger: Ledger,
                 runner: Runner) -> None:
        self.allowed, self.root, self.ledger, self.runner = allowed, root, ledger, runner
        self.rooms: dict[RoomKey, RoomController] = {}

    def join(self, room: RoomKey) -> RoomController:
        if room not in self.allowed:
            raise Denied("room is not allowlisted")
        if room not in self.rooms:
            self.rooms[room] = RoomController(room, self.root, self.ledger, self.runner)
        if self.rooms[room].stopped:
            raise Denied("room is stopping; drain and detach before rejoining")
        return self.rooms[room]

    async def leave(self, room: RoomKey) -> None:
        controller = self.rooms.get(room)
        if controller is not None:
            controller.stop()
            await controller.drain()
            del self.rooms[room]
