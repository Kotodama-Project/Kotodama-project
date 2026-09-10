"""Bounded, Task-scoped peer transport.

The transport is deliberately a small persistence layer.  It does not mint a
Task or an authority grant and it never stores peer payload text.  The owner
adapter supplies the current Task/actor binding and the directed authorization
callback on every operation.
"""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .protocol import (
    SwarmError,
    canonical,
    digest,
    digest_ref,
    finite,
    integer,
    ref,
    scope_key,
    timestamp,
    validate_binding,
)


_REQUEST_FIELDS = (
    "message_id",
    "idempotency_key",
    "task_id",
    "revision",
    "context_digest",
    "owner_ref",
    "active_home",
    "authority_ref",
    "capability_ref",
    "sender_ref",
    "recipient_ref",
    "sender_epoch",
    "invocation_ref",
    "parent_message_id",
    "payload_ref",
    "payload_digest",
    "expires_at",
)

_SCOPE_COLUMNS = (
    "task_id",
    "revision",
    "context_digest",
    "owner_ref",
    "active_home",
    "authority_ref",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL UNIQUE,
    idempotency_key TEXT NOT NULL,
    task_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    context_digest TEXT NOT NULL,
    owner_ref TEXT NOT NULL,
    active_home TEXT NOT NULL,
    authority_ref TEXT NOT NULL,
    capability_ref TEXT NOT NULL,
    sender_ref TEXT NOT NULL,
    recipient_ref TEXT NOT NULL,
    sender_epoch INTEGER NOT NULL,
    invocation_ref TEXT NOT NULL,
    parent_message_id TEXT,
    payload_ref TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    expires_at REAL NOT NULL,
    stored_at REAL NOT NULL,
    FOREIGN KEY(parent_message_id) REFERENCES messages(message_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_message_idempotency
    ON messages(task_id, revision, context_digest, sender_ref, idempotency_key);
CREATE INDEX IF NOT EXISTS ix_messages_recipient
    ON messages(task_id, revision, context_digest, recipient_ref, expires_at, row_id);
CREATE INDEX IF NOT EXISTS ix_messages_scope
    ON messages(task_id, revision, context_digest, expires_at, row_id);
CREATE INDEX IF NOT EXISTS ix_messages_parent
    ON messages(parent_message_id, row_id);
CREATE TABLE IF NOT EXISTS acknowledgements (
    message_id TEXT PRIMARY KEY REFERENCES messages(message_id),
    actor_ref TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    epoch INTEGER NOT NULL,
    invocation_ref TEXT NOT NULL,
    acked_at REAL NOT NULL
);
"""


class PeerTransport:
    """SQLite backed directed transport for one local Task swarm.

    ``binding_reader`` and ``authorize`` are intentionally callbacks rather
    than stored authority.  A callback exception is treated as a denied or
    unavailable binding, and only literal ``True`` from ``authorize`` grants
    an operation.
    """

    def __init__(
        self,
        db_path: str | Path,
        binding_reader: Callable[[str, str], Mapping[str, Any]],
        authorize: Callable[[Mapping[str, Any], str, str, str], bool],
        clock: Callable[[], float] = time.time,
        max_messages: int = 512,
        max_pending: int = 16,
    ) -> None:
        if not callable(binding_reader) or not callable(authorize):
            raise SwarmError("INVALID_BINDING", "binding and authorization callbacks are required")
        self.db_path = str(db_path)
        self._sqlite_uri = False
        self._memory_keeper: sqlite3.Connection | None = None
        if self.db_path == ":memory:":
            # A normal ``:memory:`` database is private to each SQLite
            # connection, while this class intentionally opens short-lived
            # connections per operation.  Keep one private anchor and expose
            # a unique shared-memory URI so test callers still get durable
            # behavior for the lifetime of this transport instance.
            self._sqlite_uri = True
            self._sqlite_target = f"file:task_swarm_{uuid.uuid4().hex}?mode=memory&cache=shared"
            self._memory_keeper = sqlite3.connect(
                self._sqlite_target, uri=True, isolation_level=None, check_same_thread=False
            )
        else:
            self._sqlite_target = self.db_path
        self.binding_reader = binding_reader
        self.authorize = authorize
        self.clock = clock
        self.max_messages = integer(max_messages, "max_messages", minimum=1, maximum=100000)
        self.max_pending = integer(max_pending, "max_pending", minimum=1, maximum=100000)
        self._init_guard = threading.RLock()
        self._init_schema()

    # ------------------------------------------------------------------
    # SQLite lifecycle and bounded retry helpers
    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(
                self._sqlite_target,
                timeout=2.0,
                isolation_level=None,
                check_same_thread=False,
                uri=self._sqlite_uri,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 2000")
            # WAL is persistent and permits readers while a writer is active.
            # It can fail for an in-memory database, which is still usable.
            try:
                connection.execute("PRAGMA journal_mode = WAL")
            except sqlite3.DatabaseError:
                pass
            return connection
        except sqlite3.DatabaseError as exc:
            raise SwarmError("STORE_UNAVAILABLE", "cannot open transport store") from exc

    @staticmethod
    def _locked(exc: BaseException) -> bool:
        text = str(exc).lower()
        return "locked" in text or "busy" in text

    def _retry_transaction(self, operation: Callable[[sqlite3.Connection], Any]) -> Any:
        """Run a short transaction with a bounded busy retry budget."""
        deadline = time.monotonic() + 2.5
        delay = 0.01
        last: BaseException | None = None
        while True:
            connection: sqlite3.Connection | None = None
            try:
                connection = self._connect()
                connection.execute("BEGIN IMMEDIATE")
                result = operation(connection)
                connection.execute("COMMIT")
                return result
            except sqlite3.IntegrityError as exc:
                if connection is not None:
                    try:
                        connection.execute("ROLLBACK")
                    except sqlite3.DatabaseError:
                        pass
                raise SwarmError("STORE_CONFLICT", "transport store constraint refused the write") from exc
            except sqlite3.OperationalError as exc:
                if connection is not None:
                    try:
                        connection.execute("ROLLBACK")
                    except sqlite3.DatabaseError:
                        pass
                last = exc
                if not self._locked(exc) or time.monotonic() >= deadline:
                    raise SwarmError("STORE_UNAVAILABLE", "transport store write was not available") from exc
                time.sleep(delay)
                delay = min(delay * 1.7, 0.15)
            except sqlite3.DatabaseError as exc:
                if connection is not None:
                    try:
                        connection.execute("ROLLBACK")
                    except sqlite3.DatabaseError:
                        pass
                raise SwarmError("CORRUPT_STORE", "transport store rejected the transaction") from exc
            finally:
                if connection is not None:
                    connection.close()
            if last is not None and time.monotonic() >= deadline:
                raise SwarmError("STORE_UNAVAILABLE", "transport store remained busy") from last

    def _read(self, operation: Callable[[sqlite3.Connection], Any]) -> Any:
        deadline = time.monotonic() + 2.5
        delay = 0.01
        while True:
            connection: sqlite3.Connection | None = None
            try:
                connection = self._connect()
                return operation(connection)
            except sqlite3.OperationalError as exc:
                if not self._locked(exc) or time.monotonic() >= deadline:
                    raise SwarmError("STORE_UNAVAILABLE", "transport store read was not available") from exc
                time.sleep(delay)
                delay = min(delay * 1.7, 0.15)
            except sqlite3.DatabaseError as exc:
                raise SwarmError("CORRUPT_STORE", "transport store rejected the read") from exc
            finally:
                if connection is not None:
                    connection.close()

    def _init_schema(self) -> None:
        # Multiple processes may construct this class at the same time.  The
        # schema itself is idempotent, and the transaction gives each process a
        # bounded, serialized bootstrap.
        with self._init_guard:
            def initialize(connection: sqlite3.Connection) -> None:
                # ``executescript`` performs an implicit COMMIT, which would
                # defeat the BEGIN IMMEDIATE used by ``_retry_transaction``.
                # Execute each idempotent DDL statement inside that bounded
                # transaction instead.
                for statement in _SCHEMA.split(";"):
                    statement = statement.strip()
                    if statement:
                        connection.execute(statement)

            self._retry_transaction(initialize)

    def _now(self) -> float:
        try:
            return finite(self.clock(), "host clock")
        except SwarmError:
            raise
        except Exception as exc:
            raise SwarmError("INVALID_LIMIT", "host clock is unavailable") from exc

    # ------------------------------------------------------------------
    # Binding, authorization and validation
    # ------------------------------------------------------------------
    def _binding(self, task_id: str, actor_ref: str, *, active: bool) -> dict[str, Any]:
        ref(task_id, "task_id")
        ref(actor_ref, "actor")
        try:
            raw = self.binding_reader(task_id, actor_ref)
        except SwarmError:
            raise
        except Exception as exc:
            raise SwarmError("BINDING_UNAVAILABLE", "owner binding could not be read") from exc
        try:
            result = validate_binding(raw, now=self._now(), actor=actor_ref, require_active_actor=active)
        except SwarmError:
            raise
        except Exception as exc:
            raise SwarmError("BINDING_UNAVAILABLE", "owner binding is malformed") from exc
        if result["task_id"] != task_id:
            raise SwarmError("BINDING_UNAVAILABLE", "binding belongs to another Task")
        return result

    def _allowed(self, binding: Mapping[str, Any], actor: str, peer: str, action: str) -> None:
        try:
            result = self.authorize(binding, actor, peer, action)
        except Exception as exc:
            raise SwarmError("FORBIDDEN", f"{action} is not authorized") from exc
        if result is not True:
            raise SwarmError("FORBIDDEN", f"{action} is not authorized")

    @staticmethod
    def _check_scope(request: Mapping[str, Any], binding: Mapping[str, Any], *, name: str) -> None:
        if tuple(request[key] for key in _SCOPE_COLUMNS) != scope_key(binding):
            raise SwarmError("SCOPE_MISMATCH", f"{name} binding does not match Task scope")

    @staticmethod
    def _check_row_scope(row: sqlite3.Row, binding: Mapping[str, Any]) -> None:
        if tuple(row[key] for key in _SCOPE_COLUMNS) != scope_key(binding):
            raise SwarmError("STALE_MESSAGE", "message belongs to a stale Task scope")

    def _request(self, request: Mapping[str, Any], now: float) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            raise SwarmError("INVALID_MESSAGE", "message request must be an object")
        missing = [key for key in _REQUEST_FIELDS if key not in request]
        if missing:
            raise SwarmError("INVALID_MESSAGE", "message request is incomplete")
        unknown = set(request) - set(_REQUEST_FIELDS)
        if unknown:
            raise SwarmError("INVALID_MESSAGE", "message request contains unknown fields")
        result = dict(request)
        for key in ("message_id", "idempotency_key", "task_id", "owner_ref", "active_home",
                    "authority_ref", "capability_ref", "sender_ref", "recipient_ref",
                    "invocation_ref", "payload_ref"):
            ref(result[key], key)
        integer(result["revision"], "Task revision", maximum=2**53 - 1)
        digest_ref(result["context_digest"], "context digest")
        integer(result["sender_epoch"], "sender epoch", maximum=2**53 - 1)
        if result["parent_message_id"] is not None:
            ref(result["parent_message_id"], "parent message")
        digest_ref(result["payload_digest"], "payload digest")
        result["expires_at"] = timestamp(result["expires_at"])
        if result["expires_at"] <= now:
            raise SwarmError("EXPIRED_MESSAGE", "message expiry is not in the future")
        return result

    def _validate_sender_and_recipient(
        self, request: Mapping[str, Any], *, action: str, now: float
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        sender = self._binding(request["task_id"], request["sender_ref"], active=True)
        recipient = self._binding(request["task_id"], request["recipient_ref"], active=False)
        self._check_scope(request, sender, name="sender")
        self._check_scope(request, recipient, name="recipient")
        if request["capability_ref"] != sender["capability_ref"]:
            raise SwarmError("GRANT_MISMATCH", "sender capability does not match current grant")
        if request["sender_epoch"] != sender["epoch"] or request["invocation_ref"] != sender["invocation_ref"]:
            raise SwarmError("STALE_EPOCH", "sender epoch or invocation is stale")
        if request["expires_at"] > sender["expires_at"] or request["expires_at"] > recipient["expires_at"]:
            raise SwarmError("INVALID_DEADLINE", "message expiry exceeds a current binding")
        self._allowed(sender, request["sender_ref"], request["recipient_ref"], action)
        self._allowed(recipient, request["recipient_ref"], request["sender_ref"], "receive")
        return sender, recipient

    # ------------------------------------------------------------------
    # Row encoding and corruption checks
    # ------------------------------------------------------------------
    @staticmethod
    def _envelope(row: sqlite3.Row) -> dict[str, Any]:
        try:
            result: dict[str, Any] = {
                "message_id": ref(row["message_id"], "message_id"),
                "idempotency_key": ref(row["idempotency_key"], "idempotency_key"),
                "task_id": ref(row["task_id"], "task_id"),
                "revision": integer(row["revision"], "Task revision", maximum=2**53 - 1),
                "context_digest": digest_ref(row["context_digest"], "context digest"),
                "owner_ref": ref(row["owner_ref"], "owner_ref"),
                "active_home": ref(row["active_home"], "active_home"),
                "authority_ref": ref(row["authority_ref"], "authority_ref"),
                "capability_ref": ref(row["capability_ref"], "capability_ref"),
                "sender_ref": ref(row["sender_ref"], "sender_ref"),
                "recipient_ref": ref(row["recipient_ref"], "recipient_ref"),
                "sender_epoch": integer(row["sender_epoch"], "sender epoch", maximum=2**53 - 1),
                "invocation_ref": ref(row["invocation_ref"], "invocation_ref"),
                "parent_message_id": row["parent_message_id"],
                "payload_ref": ref(row["payload_ref"], "payload_ref"),
                "payload_digest": digest_ref(row["payload_digest"], "payload_digest"),
                "expires_at": finite(row["expires_at"], "expires_at"),
                "stored_at": finite(row["stored_at"], "stored_at"),
            }
            if result["parent_message_id"] is not None:
                ref(result["parent_message_id"], "parent_message_id")
            return result
        except SwarmError as exc:
            raise SwarmError("CORRUPT_STORE", "transport store contains an invalid message") from exc

    @staticmethod
    def _request_matches(row: sqlite3.Row, request: Mapping[str, Any]) -> bool:
        # Sender epoch and invocation are provenance, not idempotency identity:
        # an authorized new invocation can replay an already accepted logical
        # message while the original provenance remains in the row.
        for key in (
            "message_id", "idempotency_key", "task_id", "revision", "context_digest",
            "owner_ref", "active_home", "authority_ref", "capability_ref", "sender_ref",
            "recipient_ref", "parent_message_id", "payload_ref", "payload_digest", "expires_at",
        ):
            left = row[key]
            right = request[key]
            if key == "expires_at":
                if float(left) != float(right):
                    return False
            elif left != right:
                return False
        return True

    @staticmethod
    def _scope_params(request: Mapping[str, Any]) -> tuple[Any, ...]:
        return tuple(request[key] for key in _SCOPE_COLUMNS)

    def _find_by_key(self, connection: sqlite3.Connection, request: Mapping[str, Any]) -> sqlite3.Row | None:
        return connection.execute(
            """SELECT * FROM messages
               WHERE task_id=? AND revision=? AND context_digest=? AND sender_ref=? AND idempotency_key=?
               ORDER BY row_id LIMIT 1""",
            (request["task_id"], request["revision"], request["context_digest"], request["sender_ref"], request["idempotency_key"]),
        ).fetchone()

    def _find_by_id(self, connection: sqlite3.Connection, message_id: str) -> sqlite3.Row | None:
        return connection.execute("SELECT * FROM messages WHERE message_id=?", (message_id,)).fetchone()

    def _ack_record(self, connection: sqlite3.Connection, message: sqlite3.Row) -> dict[str, Any] | None:
        row = connection.execute("SELECT * FROM acknowledgements WHERE message_id=?", (message["message_id"],)).fetchone()
        if row is None:
            return None
        try:
            value = dict(row)
            ref(value["actor_ref"], "ACK actor")
            digest_ref(value["payload_digest"], "ACK digest")
            integer(value["epoch"], "ACK epoch", maximum=2**53-1)
            ref(value["invocation_ref"], "ACK invocation")
            finite(value["acked_at"], "ACK timestamp")
            if (value["actor_ref"] != message["recipient_ref"] or value["payload_digest"] != message["payload_digest"]
                    or not message["stored_at"] <= value["acked_at"] <= message["expires_at"]):
                raise ValueError("ACK binding mismatch")
            return value
        except (SwarmError, ValueError, TypeError, KeyError) as exc:
            raise SwarmError("CORRUPT_STORE", "stored ACK is invalid") from exc

    def _pending_count(self, connection: sqlite3.Connection, request: Mapping[str, Any], now: float) -> int:
        recipient = self._binding(request["task_id"], request["recipient_ref"], active=False)
        rows = connection.execute(
            """SELECT * FROM messages WHERE task_id=? AND revision=? AND context_digest=?
               AND owner_ref=? AND active_home=? AND authority_ref=? AND recipient_ref=? AND expires_at>?
               ORDER BY row_id LIMIT ?""",
            (*self._scope_params(request), request["recipient_ref"], now, self.max_messages + 1),
        ).fetchall()
        count = 0
        for row in rows:
            self._envelope(row)
            if self._ack_record(connection, row) is not None:
                continue
            try:
                self._allowed(recipient, request["recipient_ref"], row["sender_ref"], "receive")
            except SwarmError as exc:
                if exc.code == "FORBIDDEN":
                    continue
                raise
            count += 1
        return count

    # ------------------------------------------------------------------
    # Public send/retrieve/ack/reply API
    # ------------------------------------------------------------------
    def send(self, request: Mapping[str, Any]) -> dict[str, Any]:
        now = self._now()
        parsed = self._request(request, now)
        if parsed["parent_message_id"] is not None:
            raise SwarmError("INVALID_MESSAGE", "send requests cannot carry a parent")
        self._validate_sender_and_recipient(parsed, action="send", now=now)

        def write(connection: sqlite3.Connection) -> dict[str, Any]:
            now = self._now()
            if parsed["expires_at"] <= now:
                raise SwarmError("EXPIRED_MESSAGE", "message expired while waiting for the store")
            self._validate_sender_and_recipient(parsed, action="send", now=now)
            existing = self._find_by_key(connection, parsed)
            if existing is not None:
                self._envelope(existing)
                if not self._request_matches(existing, parsed):
                    raise SwarmError("IDEMPOTENCY_CONFLICT", "idempotency key identifies another message")
                return {**self._envelope(existing), "stored_at": float(existing["stored_at"])}
            by_id = self._find_by_id(connection, parsed["message_id"])
            if by_id is not None:
                self._envelope(by_id)
                raise SwarmError("MESSAGE_CONFLICT", "message_id already identifies another message")
            scope = self._scope_params(parsed)
            active_total = connection.execute(
                """SELECT COUNT(*) FROM messages
                   WHERE task_id=? AND revision=? AND context_digest=?
                     AND owner_ref=? AND active_home=? AND authority_ref=?
                     AND expires_at>?""",
                (*scope, now),
            ).fetchone()[0]
            if active_total >= self.max_messages:
                raise SwarmError("QUOTA_EXCEEDED", "Task message quota is full")
            pending = self._pending_count(connection, parsed, now)
            if pending >= self.max_pending:
                raise SwarmError("BACKPRESSURE", "recipient pending-message quota is full")
            connection.execute(
                """INSERT INTO messages(
                    message_id,idempotency_key,task_id,revision,context_digest,owner_ref,
                    active_home,authority_ref,capability_ref,sender_ref,recipient_ref,
                    sender_epoch,invocation_ref,parent_message_id,payload_ref,payload_digest,
                    expires_at,stored_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    parsed["message_id"], parsed["idempotency_key"], parsed["task_id"], parsed["revision"],
                    parsed["context_digest"], parsed["owner_ref"], parsed["active_home"],
                    parsed["authority_ref"], parsed["capability_ref"], parsed["sender_ref"],
                    parsed["recipient_ref"], parsed["sender_epoch"], parsed["invocation_ref"],
                    parsed["parent_message_id"], parsed["payload_ref"], parsed["payload_digest"],
                    parsed["expires_at"], now,
                ),
            )
            row = self._find_by_id(connection, parsed["message_id"])
            if row is None:
                raise SwarmError("CORRUPT_STORE", "inserted message cannot be read back")
            return self._envelope(row)

        return self._retry_transaction(write)

    def receive(self, task_id: str, actor_ref: str, limit: int = 20) -> list[dict[str, Any]]:
        ref(task_id, "task_id")
        ref(actor_ref, "actor")
        # A caller may ask for the contract default (20) even when the
        # configured total-message quota is smaller.  The scan and returned
        # rows remain bounded by ``max_messages`` below.
        limit = integer(limit, "limit", minimum=1, maximum=100000)
        now = self._now()
        binding = self._binding(task_id, actor_ref, active=False)
        # The scan is deliberately finite.  Expired rows are filtered in SQL,
        # so a stale backlog cannot force unbounded reads before live traffic.
        scan_limit = self.max_messages

        def read(connection: sqlite3.Connection) -> list[dict[str, Any]]:
            rows = connection.execute(
                """SELECT m.* FROM messages AS m
                   WHERE m.task_id=? AND m.revision=? AND m.context_digest=?
                     AND m.owner_ref=? AND m.active_home=? AND m.authority_ref=?
                     AND m.recipient_ref=? AND m.expires_at>?
                     AND NOT EXISTS (SELECT 1 FROM acknowledgements a WHERE a.message_id=m.message_id)
                   ORDER BY m.row_id LIMIT ?""",
                (*scope_key(binding), actor_ref, now, scan_limit),
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                # An owner can revoke a particular directed peer without
                # invalidating other messages addressed to this actor.
                try:
                    self._allowed(binding, actor_ref, row["sender_ref"], "receive")
                except SwarmError as exc:
                    if exc.code == "FORBIDDEN":
                        continue
                    raise
                result.append(self._envelope(row))
                if len(result) >= limit:
                    break
            return result

        return self._read(read)

    def read_message(self, task_id: str, actor_ref: str, message_id: str) -> dict[str, Any]:
        ref(task_id, "task_id")
        ref(actor_ref, "actor")
        ref(message_id, "message_id")
        binding = self._binding(task_id, actor_ref, active=False)

        def read(connection: sqlite3.Connection) -> dict[str, Any]:
            row = connection.execute(
                "SELECT * FROM messages WHERE task_id=? AND message_id=? AND recipient_ref=?",
                (task_id, message_id, actor_ref),
            ).fetchone()
            if row is None:
                raise SwarmError("MESSAGE_NOT_FOUND", "message is not addressed to this actor")
            self._envelope(row)
            self._check_row_scope(row, binding)
            if row["expires_at"] <= self._now():
                raise SwarmError("EXPIRED_MESSAGE", "message expired")
            self._allowed(binding, actor_ref, row["sender_ref"], "receive")
            return self._envelope(row)

        return self._read(read)

    def ack(
        self,
        task_id: str,
        actor_ref: str,
        message_id: str,
        payload_digest: str,
        epoch: int,
        invocation_ref: str,
    ) -> dict[str, Any]:
        ref(task_id, "task_id")
        ref(actor_ref, "actor")
        ref(message_id, "message_id")
        digest_ref(payload_digest, "payload digest")
        integer(epoch, "actor epoch", maximum=2**53 - 1)
        ref(invocation_ref, "invocation")
        now = self._now()
        binding = self._binding(task_id, actor_ref, active=True)
        if binding["epoch"] != epoch or binding["invocation_ref"] != invocation_ref:
            raise SwarmError("STALE_EPOCH", "acknowledging actor epoch or invocation is stale")

        def write(connection: sqlite3.Connection) -> dict[str, Any]:
            now = self._now()
            binding = self._binding(task_id, actor_ref, active=True)
            if binding["epoch"] != epoch or binding["invocation_ref"] != invocation_ref:
                raise SwarmError("STALE_EPOCH", "acknowledging actor changed while waiting for the store")
            row = connection.execute(
                "SELECT * FROM messages WHERE task_id=? AND message_id=? AND recipient_ref=?",
                (task_id, message_id, actor_ref),
            ).fetchone()
            if row is None:
                raise SwarmError("MESSAGE_NOT_FOUND", "message is not addressed to this actor")
            self._envelope(row)
            self._check_row_scope(row, binding)
            if row["expires_at"] <= now:
                raise SwarmError("EXPIRED_MESSAGE", "expired messages cannot be acknowledged")
            if row["payload_digest"] != payload_digest:
                raise SwarmError("DIGEST_MISMATCH", "ack payload digest does not match message")
            self._allowed(binding, actor_ref, row["sender_ref"], "ack")
            existing = self._ack_record(connection, row)
            if existing is not None:
                if existing["actor_ref"] != actor_ref or existing["payload_digest"] != payload_digest:
                    raise SwarmError("CORRUPT_STORE", "ack receipt conflicts with destination")
                return {
                    "message_id": message_id,
                    "payload_digest": existing["payload_digest"],
                    "ack": True,
                    "acked_at": float(existing["acked_at"]),
                }
            if float(row["expires_at"]) <= now:
                raise SwarmError("EXPIRED_MESSAGE", "expired messages cannot be acknowledged")
            connection.execute(
                """INSERT INTO acknowledgements(message_id,actor_ref,payload_digest,epoch,invocation_ref,acked_at)
                   VALUES(?,?,?,?,?,?)""",
                (message_id, actor_ref, payload_digest, epoch, invocation_ref, now),
            )
            return {
                "message_id": message_id,
                "payload_digest": payload_digest,
                "ack": True,
                "acked_at": now,
            }

        return self._retry_transaction(write)

    def reply(self, request: Mapping[str, Any]) -> dict[str, Any]:
        now = self._now()
        parsed = self._request(request, now)
        if parsed["parent_message_id"] is None:
            raise SwarmError("INVALID_MESSAGE", "reply requests require a parent")
        sender, recipient = self._validate_sender_and_recipient(parsed, action="reply", now=now)

        def write(connection: sqlite3.Connection) -> dict[str, Any]:
            now = self._now()
            sender, recipient = self._validate_sender_and_recipient(parsed, action="reply", now=now)
            parent = self._find_by_id(connection, parsed["parent_message_id"])
            if parent is None:
                raise SwarmError("MESSAGE_NOT_FOUND", "reply parent does not exist")
            self._envelope(parent)
            self._check_row_scope(parent, sender)
            if parent["recipient_ref"] != parsed["sender_ref"]:
                raise SwarmError("WRONG_RECIPIENT", "reply parent is addressed to another actor")
            if parent["sender_ref"] != parsed["recipient_ref"]:
                raise SwarmError("WRONG_RECIPIENT", "reply recipient is not the original sender")
            if parent["context_digest"] != parsed["context_digest"] or parent["revision"] != parsed["revision"]:
                raise SwarmError("SCOPE_MISMATCH", "reply parent is outside the current Task scope")
            if float(parent["expires_at"]) <= now or parsed["expires_at"] > float(parent["expires_at"]):
                raise SwarmError("EXPIRED_MESSAGE", "reply must remain within the parent expiry")
            ack_row = self._ack_record(connection, parent)
            if ack_row is None or ack_row["actor_ref"] != parsed["sender_ref"]:
                raise SwarmError("MISSING_ACK", "reply parent has not been acknowledged by its recipient")
            existing = self._find_by_key(connection, parsed)
            if existing is not None:
                self._envelope(existing)
                if not self._request_matches(existing, parsed):
                    raise SwarmError("IDEMPOTENCY_CONFLICT", "idempotency key identifies another reply")
                return self._envelope(existing)
            by_id = self._find_by_id(connection, parsed["message_id"])
            if by_id is not None:
                self._envelope(by_id)
                raise SwarmError("MESSAGE_CONFLICT", "message_id already identifies another message")
            scope = self._scope_params(parsed)
            active_total = connection.execute(
                """SELECT COUNT(*) FROM messages
                   WHERE task_id=? AND revision=? AND context_digest=?
                     AND owner_ref=? AND active_home=? AND authority_ref=?
                     AND expires_at>?""",
                (*scope, now),
            ).fetchone()[0]
            if active_total >= self.max_messages:
                raise SwarmError("QUOTA_EXCEEDED", "Task message quota is full")
            pending = self._pending_count(connection, parsed, now)
            if pending >= self.max_pending:
                raise SwarmError("BACKPRESSURE", "recipient pending-message quota is full")
            connection.execute(
                """INSERT INTO messages(
                    message_id,idempotency_key,task_id,revision,context_digest,owner_ref,
                    active_home,authority_ref,capability_ref,sender_ref,recipient_ref,
                    sender_epoch,invocation_ref,parent_message_id,payload_ref,payload_digest,
                    expires_at,stored_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    parsed["message_id"], parsed["idempotency_key"], parsed["task_id"], parsed["revision"],
                    parsed["context_digest"], parsed["owner_ref"], parsed["active_home"],
                    parsed["authority_ref"], parsed["capability_ref"], parsed["sender_ref"],
                    parsed["recipient_ref"], parsed["sender_epoch"], parsed["invocation_ref"],
                    parsed["parent_message_id"], parsed["payload_ref"], parsed["payload_digest"],
                    parsed["expires_at"], now,
                ),
            )
            row = self._find_by_id(connection, parsed["message_id"])
            if row is None:
                raise SwarmError("CORRUPT_STORE", "inserted reply cannot be read back")
            return self._envelope(row)

        return self._retry_transaction(write)

    def status(self, task_id: str, actor_ref: str, message_id: str) -> dict[str, Any]:
        ref(task_id, "task_id")
        ref(actor_ref, "actor")
        ref(message_id, "message_id")
        now = self._now()
        binding = self._binding(task_id, actor_ref, active=False)

        def read(connection: sqlite3.Connection) -> dict[str, Any]:
            row = self._find_by_id(connection, message_id)
            if row is None or row["task_id"] != task_id:
                raise SwarmError("MESSAGE_NOT_FOUND", "message is not in this Task")
            self._envelope(row)
            if actor_ref == row["sender_ref"]:
                peer = row["recipient_ref"]
            elif actor_ref == row["recipient_ref"]:
                peer = row["sender_ref"]
            else:
                raise SwarmError("FORBIDDEN", "message is not visible to this actor")
            self._allowed(binding, actor_ref, peer, "status")
            scope_stale = tuple(row[key] for key in _SCOPE_COLUMNS) != scope_key(binding)
            ack_row = self._ack_record(connection, row)
            replies = connection.execute(
                "SELECT * FROM messages WHERE parent_message_id=? ORDER BY row_id", (message_id,)
            ).fetchall()
            reply_ids: list[str] = []
            unacked_reply_ids: list[str] = []
            for reply in replies:
                reply_envelope = self._envelope(reply)
                if (tuple(reply[key] for key in _SCOPE_COLUMNS) != tuple(row[key] for key in _SCOPE_COLUMNS)
                        or reply["sender_ref"] != row["recipient_ref"] or reply["recipient_ref"] != row["sender_ref"]):
                    raise SwarmError("CORRUPT_STORE", "reply crosses its parent Task or actor scope")
                reply_ids.append(reply_envelope["message_id"])
                reply_ack = self._ack_record(connection, reply)
                if reply_ack is None:
                    unacked_reply_ids.append(reply_envelope["message_id"])
            # A status read is the one place where a retained row may be
            # reported as stale rather than exposing its old Task scope.  A
            # sender epoch rollover fences old ingress while leaving the
            # immutable receipt and recipient inbox intact.
            if scope_stale:
                state = "stale"
                reply_ids = []
                unacked_reply_ids = []
            elif float(row["expires_at"]) <= now:
                state = "expired"
            elif ack_row is None:
                state = "stored"
            elif not reply_ids:
                state = "acked"
            elif unacked_reply_ids:
                state = "replied"
            else:
                state = "reply_acked"
            return {
                "message_id": message_id,
                "state": state,
                "ack": ack_row is not None,
                "reply_ids": reply_ids,
                "unacked_reply_ids": unacked_reply_ids,
            }

        return self._read(read)


__all__ = ["PeerTransport"]
