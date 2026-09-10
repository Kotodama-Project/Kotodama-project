"""Task-bound MCP stdio adapter around the shared PeerTransport.

Only six bounded peer tools are registered.  The owner JSON remains the
authority for the current Task/actor lease; MCP arguments never select a new
actor, storage root, or permission.  The MCP package is imported only when a
server is actually created, keeping the core adapter importable in minimal
Python environments.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
import math
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable, Mapping, Sequence
import uuid

if __package__ in {None, ""}:  # pragma: no cover - exercised by stdio subprocesses
    _RUNTIME_ROOT = Path(__file__).resolve().parents[1]
    if str(_RUNTIME_ROOT) not in sys.path:
        sys.path.insert(0, str(_RUNTIME_ROOT))
    from task_swarm.owner_file import OwnerFile, OwnerFileError
    from task_swarm.payloads import PayloadError, PayloadStore
    from task_swarm.protocol import SwarmError, digest_ref, finite, integer, ref, timestamp
else:
    from .owner_file import OwnerFile, OwnerFileError
    from .payloads import PayloadError, PayloadStore
    from .protocol import SwarmError, digest_ref, finite, integer, ref, timestamp


EXACT_TOOLS = (
    "peer_list",
    "peer_send",
    "peer_receive",
    "peer_ack",
    "peer_reply",
    "peer_status",
)
_READ_TOOLS = frozenset({"peer_list", "peer_receive", "peer_status"})
_MAX_IDEMPOTENCY = 256
_MAX_MESSAGE_ID = 256


class PeerAdapterError(SwarmError):
    """Typed refusal exposed by direct calls and MCP tool errors."""


def _raise(code: str, detail: str) -> None:
    raise PeerAdapterError(code, detail)


def _text(value: Any, name: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        _raise("INVALID_INPUT", f"invalid {name}")
    return value


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _component_error(exc: BaseException) -> PeerAdapterError:
    if isinstance(exc, PeerAdapterError):
        return exc
    code = getattr(exc, "code", None)
    detail = getattr(exc, "detail", None)
    if isinstance(code, str) and code:
        # Shared protocol errors have already bounded their detail.  Unknown
        # implementation exceptions are intentionally reduced to a generic
        # refusal so internals and accidental payload text cannot escape.
        if not isinstance(detail, str) or not detail:
            detail = "shared peer operation refused"
        return PeerAdapterError(code, detail[:512])
    return PeerAdapterError("PEER_OPERATION_REFUSED", "shared peer operation refused")


def _transport_class() -> type[Any]:
    try:
        if __package__ in {None, ""}:
            from task_swarm.transport import PeerTransport
        else:
            from .transport import PeerTransport
    except (ImportError, ModuleNotFoundError) as exc:
        raise PeerAdapterError("TRANSPORT_UNAVAILABLE", "PeerTransport is unavailable") from exc
    if not isinstance(PeerTransport, type):
        _raise("TRANSPORT_UNAVAILABLE", "PeerTransport is invalid")
    return PeerTransport


def _extract_messages(result: Any) -> list[dict[str, Any]]:
    value = _jsonable(result)
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        messages = value.get("messages")
        if isinstance(messages, list):
            return [dict(item) for item in messages if isinstance(item, Mapping)]
        if "message_id" in value:
            return [dict(value)]
    return []


def _one_receipt(result: Any, **defaults: Any) -> dict[str, Any]:
    value = _jsonable(result)
    output = dict(value) if isinstance(value, Mapping) else {"receipt": value}
    for key, item in defaults.items():
        output.setdefault(key, item)
    return output


class PeerTools:
    """Fixed-identity facade used by both MCP and root offline fixtures."""

    def __init__(
        self,
        binding_path: str | os.PathLike[str],
        actor: str,
        epoch: int,
        invocation: str,
        *,
        clock: Callable[[], float] = time.time,
        transport: Any | None = None,
        payload_store: PayloadStore | None = None,
        owner: OwnerFile | None = None,
    ) -> None:
        self.clock = clock
        self.owner = owner or OwnerFile(binding_path, clock=clock)
        self.actor = _text(actor, "actor", maximum=256)
        if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 1 or epoch > 2**53 - 1:
            _raise("INVALID_INPUT", "epoch must be a bounded integer")
        self.epoch = epoch
        self.invocation = _text(invocation, "invocation", maximum=512)
        try:
            self.task_id = self.owner.task_id
            self._storage_selection = self.owner.storage()
            initial = self.owner.read_binding(self.task_id, self.actor)
        except (OwnerFileError, SwarmError) as exc:
            raise PeerAdapterError(exc.code, exc.detail) from exc
        self._assert_startup_identity(initial)
        self._startup_scope = tuple(initial[key] for key in
            ("task_id", "revision", "context_digest", "owner_ref", "active_home", "authority_ref", "capability_ref"))
        try:
            mailbox_parent = self._storage_selection["mailbox"].parent
            if mailbox_parent.exists() and mailbox_parent.is_symlink():
                _raise("STORAGE_ESCAPE", "mailbox parent cannot be a symlink")
            mailbox_parent.mkdir(parents=True, exist_ok=True)
            if mailbox_parent.is_symlink():
                _raise("STORAGE_ESCAPE", "mailbox parent cannot be a symlink")
        except PeerAdapterError:
            raise
        except OSError as exc:
            raise PeerAdapterError("STORAGE_INVALID", "mailbox parent cannot be created") from exc
        self.payloads = payload_store or PayloadStore(self._storage_selection["payloads"])
        if transport is None:
            transport_type = _transport_class()
            mailbox = self._storage_selection["mailbox"]
            try:
                transport = transport_type(
                    str(mailbox),
                    self.owner.read_binding,
                    self.owner.authorize,
                    clock=clock,
                )
            except Exception as exc:
                raise _component_error(exc) from exc
        self.transport = transport

    def _assert_startup_identity(self, binding: Mapping[str, Any]) -> None:
        if binding.get("actor_ref") != self.actor or binding.get("epoch") != self.epoch:
            _raise("STALE_ACTOR", "startup actor epoch does not match current owner lease")
        if binding.get("invocation_ref") != self.invocation:
            _raise("STALE_INVOCATION", "startup invocation does not match current owner lease")
        if binding.get("actor_status") != "active":
            _raise("INACTIVE_ACTOR", "startup actor has no active execution lease")

    def _current_binding(self) -> dict[str, Any]:
        try:
            current_storage = self.owner.storage()
            if current_storage != self._storage_selection:
                _raise("STORAGE_CHANGED", "owner storage changed after adapter startup")
            binding = self.owner.read_binding(self.task_id, self.actor)
        except (OwnerFileError, SwarmError) as exc:
            raise PeerAdapterError(exc.code, exc.detail) from exc
        self._assert_startup_identity(binding)
        current_scope = tuple(binding[key] for key in
            ("task_id", "revision", "context_digest", "owner_ref", "active_home", "authority_ref", "capability_ref"))
        if current_scope != self._startup_scope:
            _raise("STALE_CONTEXT", "Task context or capability changed after adapter startup")
        return binding

    def _peer(self, binding: Mapping[str, Any], peer_ref: Any, action: str) -> str:
        peer = _text(peer_ref, "peer_ref", maximum=256)
        try:
            known = {item["actor_ref"] for item in self.owner.peers(self.actor)}
        except (OwnerFileError, SwarmError) as exc:
            raise PeerAdapterError(exc.code, exc.detail) from exc
        if peer not in known or peer == self.actor:
            _raise("DESTINATION_UNKNOWN", "peer is not an authorized directed peer")
        if not self.owner.authorize(binding, self.actor, peer, action):
            _raise("AUTHORIZATION_DENIED", "peer action is not currently authorized")
        return peer

    @staticmethod
    def _message_id(*parts: str) -> str:
        return "msg/" + uuid.uuid5(uuid.NAMESPACE_URL, "\x1f".join(parts)).hex

    def _request(
        self,
        binding: Mapping[str, Any],
        *,
        message_id: str,
        recipient: str,
        idempotency_key: str,
        payload_ref: str,
        payload_digest: str,
        parent_message_id: str | None,
    ) -> dict[str, Any]:
        return {
            "message_id": message_id,
            "idempotency_key": idempotency_key,
            "task_id": binding["task_id"],
            "revision": binding["revision"],
            "context_digest": binding["context_digest"],
            "owner_ref": binding["owner_ref"],
            "active_home": binding["active_home"],
            "authority_ref": binding["authority_ref"],
            "capability_ref": binding["capability_ref"],
            "sender_ref": self.actor,
            "recipient_ref": recipient,
            "sender_epoch": self.epoch,
            "invocation_ref": self.invocation,
            "parent_message_id": parent_message_id,
            "payload_ref": payload_ref,
            "payload_digest": payload_digest,
            "expires_at": binding["expires_at"],
        }

    def peer_list(self) -> dict[str, Any]:
        binding = self._current_binding()
        result: list[dict[str, Any]] = []
        try:
            peers = self.owner.peers(self.actor)
        except (OwnerFileError, SwarmError) as exc:
            raise PeerAdapterError(exc.code, exc.detail) from exc
        for peer in peers:
            peer_ref = peer["actor_ref"]
            if any(self.owner.authorize(binding, self.actor, peer_ref, action) for action in ("send", "receive", "status")):
                result.append(dict(peer))
        return {"peers": result}

    def peer_send(
        self,
        recipient: str,
        text: str,
        idempotency_key: str,
        evidence_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        binding = self._current_binding()
        target = self._peer(binding, recipient, "send")
        idem = _text(idempotency_key, "idempotency_key", maximum=_MAX_IDEMPOTENCY)
        payload_ref, payload_digest = self.payloads.put(text, [] if evidence_refs is None else evidence_refs)
        message_id = self._message_id(binding["task_id"], self.actor, idem)
        request = self._request(
            binding,
            message_id=message_id,
            recipient=target,
            idempotency_key=idem,
            payload_ref=payload_ref,
            payload_digest=payload_digest,
            parent_message_id=None,
        )
        try:
            result = self.transport.send(request)
        except Exception as exc:
            raise _component_error(exc) from exc
        return _one_receipt(result, message_id=message_id, payload_ref=payload_ref, payload_digest=payload_digest)

    def _validated_message(self, binding: Mapping[str, Any], envelope: Mapping[str, Any]) -> dict[str, Any]:
        message = dict(_jsonable(envelope))
        required = (
            "message_id",
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
        if any(field not in message for field in required):
            _raise("PEER_OPERATION_REFUSED", "message envelope is incomplete")
        if message["task_id"] != binding["task_id"] or message["recipient_ref"] != self.actor:
            _raise("PEER_SCOPE_MISMATCH", "message Task or recipient does not match")
        for field in ("revision", "context_digest", "owner_ref", "active_home", "authority_ref"):
            if message[field] != binding[field]:
                _raise("PEER_SCOPE_MISMATCH", "message binding fields are stale")
        try:
            ref(message["sender_ref"], "sender_ref")
            ref(message["invocation_ref"], "invocation_ref")
            ref(message["capability_ref"], "capability_ref")
            if message["parent_message_id"] is not None:
                ref(message["parent_message_id"], "parent_message_id")
            integer(message["sender_epoch"], "sender epoch", maximum=2**53 - 1)
            if timestamp(message["expires_at"]) <= float(self.clock()):
                _raise("EXPIRED_BINDING", "message has expired")
            digest_ref(message["payload_digest"], "payload digest")
        except SwarmError as exc:
            raise PeerAdapterError(exc.code, exc.detail) from exc
        self._peer(binding, message["sender_ref"], "receive")
        try:
            payload = self.payloads.get(message["payload_ref"], message["payload_digest"])
        except (PayloadError, SwarmError) as exc:
            raise PeerAdapterError(exc.code, exc.detail) from exc
        message["text"] = payload["text"]
        message["evidence_refs"] = payload["evidence_refs"]
        return message

    def _receive_once(self, binding: Mapping[str, Any]) -> list[dict[str, Any]]:
        try:
            result = self.transport.receive(binding["task_id"], self.actor, limit=20)
        except Exception as exc:
            raise _component_error(exc) from exc
        return [self._validated_message(binding, envelope) for envelope in _extract_messages(result)]

    def peer_receive(self, wait_seconds: float = 0) -> dict[str, Any]:
        try:
            wait = finite(wait_seconds, "wait_seconds", maximum=20)
        except SwarmError as exc:
            raise PeerAdapterError(exc.code, exc.detail) from exc
        started = time.monotonic()
        while True:
            binding = self._current_binding()
            messages = self._receive_once(binding)
            if messages or wait == 0:
                return {"messages": messages}
            remaining = wait - (time.monotonic() - started)
            if remaining <= 0:
                return {"messages": []}
            time.sleep(min(0.25, remaining))

    def peer_ack(self, message_id: str, payload_digest: str) -> dict[str, Any]:
        binding = self._current_binding()
        message = _text(message_id, "message_id", maximum=_MAX_MESSAGE_ID)
        try:
            digest = digest_ref(payload_digest, "payload digest")
        except SwarmError as exc:
            raise PeerAdapterError(exc.code, exc.detail) from exc
        try:
            result = self.transport.ack(binding["task_id"], self.actor, message, digest, self.epoch, self.invocation)
        except Exception as exc:
            raise _component_error(exc) from exc
        return _one_receipt(result, message_id=message, payload_digest=digest)

    def _parent(self, binding: Mapping[str, Any], parent_message_id: str) -> dict[str, Any]:
        reader = getattr(self.transport, "read_message", None)
        if not callable(reader):
            _raise("REPLY_PARENT_MISMATCH", "shared transport cannot read an acknowledged parent")
        try:
            result = reader(binding["task_id"], self.actor, parent_message_id)
        except Exception as exc:
            raise _component_error(exc) from exc
        candidates = _extract_messages(result)
        if not candidates:
            _raise("REPLY_PARENT_MISMATCH", "parent message is unavailable or not addressed to actor")
        for envelope in candidates:
            if envelope.get("message_id") == parent_message_id:
                return self._validated_message(binding, envelope)
        _raise("REPLY_PARENT_MISMATCH", "parent message is unavailable or not addressed to actor")

    def peer_reply(
        self,
        parent_message_id: str,
        text: str,
        idempotency_key: str,
        evidence_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        binding = self._current_binding()
        parent_id = _text(parent_message_id, "parent_message_id", maximum=_MAX_MESSAGE_ID)
        parent = self._parent(binding, parent_id)
        target = self._peer(binding, parent["sender_ref"], "reply")
        idem = _text(idempotency_key, "idempotency_key", maximum=_MAX_IDEMPOTENCY)
        payload_ref, payload_digest = self.payloads.put(text, [] if evidence_refs is None else evidence_refs)
        message_id = self._message_id(binding["task_id"], self.actor, parent_id, idem)
        request = self._request(
            binding,
            message_id=message_id,
            recipient=target,
            idempotency_key=idem,
            payload_ref=payload_ref,
            payload_digest=payload_digest,
            parent_message_id=parent_id,
        )
        try:
            result = self.transport.reply(request)
        except Exception as exc:
            raise _component_error(exc) from exc
        return _one_receipt(
            result,
            message_id=message_id,
            parent_message_id=parent_id,
            payload_ref=payload_ref,
            payload_digest=payload_digest,
        )

    def peer_status(self, message_id: str) -> dict[str, Any]:
        binding = self._current_binding()
        message = _text(message_id, "message_id", maximum=_MAX_MESSAGE_ID)
        try:
            result = self.transport.status(binding["task_id"], self.actor, message)
        except Exception as exc:
            raise _component_error(exc) from exc
        return _one_receipt(result, message_id=message)

    # Short method names are useful to a local caller while the peer_* names
    # remain the stable MCP/root facade surface.
    send = peer_send
    receive = peer_receive
    ack = peer_ack
    reply = peer_reply
    status = peer_status


def create_mcp_server(peer: PeerTools) -> Any:
    """Create an SDK 2.x server lazily, with exactly six tool registrations."""

    try:
        from mcp.server import MCPServer
        from mcp.types import ToolAnnotations
    except ImportError as exc:  # pragma: no cover - depends on optional SDK
        raise PeerAdapterError("MCP_UNAVAILABLE", "the MCP SDK is unavailable") from exc

    server = MCPServer(
        name="task-swarm-peer-adapter",
        version="0.1.0",
        instructions="Task-bound local peer communication only.",
    )

    def annotation(name: str) -> Any:
        return ToolAnnotations(
            readOnlyHint=name in _READ_TOOLS,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )

    @server.tool(name="peer_list", description="List current directed peer addresses.", annotations=annotation("peer_list"))
    def peer_list() -> dict[str, Any]:
        return peer.peer_list()

    @server.tool(name="peer_send", description="Send one bounded Task-scoped peer payload.", annotations=annotation("peer_send"))
    def peer_send(
        recipient: str,
        text: str,
        idempotency_key: str,
        evidence_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        return peer.peer_send(recipient, text, idempotency_key, evidence_refs)

    @server.tool(name="peer_receive", description="Read current unacknowledged peer payloads.", annotations=annotation("peer_receive"))
    def peer_receive(wait_seconds: float = 0) -> dict[str, Any]:
        return peer.peer_receive(wait_seconds)

    @server.tool(name="peer_ack", description="Acknowledge one received peer payload.", annotations=annotation("peer_ack"))
    def peer_ack(message_id: str, payload_digest: str) -> dict[str, Any]:
        return peer.peer_ack(message_id, payload_digest)

    @server.tool(name="peer_reply", description="Reply to one acknowledged peer payload.", annotations=annotation("peer_reply"))
    def peer_reply(
        parent_message_id: str,
        text: str,
        idempotency_key: str,
        evidence_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        return peer.peer_reply(parent_message_id, text, idempotency_key, evidence_refs)

    @server.tool(name="peer_status", description="Read delivery, ACK, and reply status for one message.", annotations=annotation("peer_status"))
    def peer_status(message_id: str) -> dict[str, Any]:
        return peer.peer_status(message_id)

    return server


def build_peer_tools(
    binding_path: str | os.PathLike[str],
    actor: str,
    epoch: int,
    invocation: str,
    *,
    clock: Callable[[], float] = time.time,
    transport: Any | None = None,
    payload_store: PayloadStore | None = None,
) -> PeerTools:
    return PeerTools(
        binding_path,
        actor,
        epoch,
        invocation,
        clock=clock,
        transport=transport,
        payload_store=payload_store,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Task-bound local peer MCP stdio adapter")
    parser.add_argument("--binding", required=True, help="owner supplied binding JSON")
    parser.add_argument("--actor", required=True, help="fixed startup actor reference")
    parser.add_argument("--epoch", required=True, type=int, help="fixed startup actor epoch")
    parser.add_argument("--invocation", required=True, help="fixed startup invocation reference")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        peer = build_peer_tools(args.binding, args.actor, args.epoch, args.invocation)
        create_mcp_server(peer).run(transport="stdio")
    except (PeerAdapterError, OwnerFileError, PayloadError, SwarmError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by MCP client tests
    raise SystemExit(main())


__all__ = [
    "EXACT_TOOLS",
    "PeerAdapterError",
    "PeerTools",
    "build_peer_tools",
    "create_mcp_server",
    "main",
]
