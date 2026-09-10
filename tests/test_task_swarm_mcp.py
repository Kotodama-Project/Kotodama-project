from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import sys
import textwrap

import pytest


RUNTIME = Path(__file__).resolve().parents[1] / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from task_swarm.mcp_server import EXACT_TOOLS, PeerAdapterError, PeerTools, create_mcp_server
from task_swarm.owner_file import OwnerFile, OwnerFileError
from task_swarm.payloads import PayloadError, PayloadStore


def _owner(tmp_path: Path, *, actor_status: str = "active") -> Path:
    source = tmp_path / "source.txt"
    source.write_text("source-v1\n", encoding="utf-8")
    document = {
        "binding": {
            "task_id": "task-1",
            "revision": 1,
            "context_digest": "a" * 64,
            "owner_ref": "owner-1",
            "active_home": "local",
            "authority_ref": "authority-1",
            "capability_ref": "task-capability",
            "expires_at": 4_000_000_000.0,
            "status": "active",
        },
        "actors": {
            "actor-a": {
                "epoch": 1,
                "invocation_ref": "invocation-a",
                "actor_status": actor_status,
                "capability_ref": "cap-a",
                "peers": ["actor-b"],
            },
            "actor-b": {
                "epoch": 1,
                "invocation_ref": "invocation-b",
                "actor_status": "active",
                "capability_ref": "cap-b",
                "peers": ["actor-a"],
            },
        },
        "storage": {
            "root": str(tmp_path / "storage"),
            "mailbox": "mailbox.sqlite",
            "payloads": "payloads",
        },
        "source_checks": [{"path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}],
        "allowed_actions": ["send", "receive", "ack", "reply", "status"],
    }
    path = tmp_path / "owner.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


class FakeTransport:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.acks: set[str] = set()
        self.statuses: dict[str, dict] = {}

    def send(self, request: dict) -> dict:
        existing = next((item for item in self.messages if item["message_id"] == request["message_id"]), None)
        if existing is not None:
            if existing != request:
                raise PeerAdapterError("IDEMPOTENCY_ARGUMENT_MISMATCH", "request differs")
            return dict(existing)
        self.messages.append(dict(request))
        self.statuses[request["message_id"]] = {
            "message_id": request["message_id"],
            "state": "stored",
            "ack": False,
            "reply_ids": [],
            "unacked_reply_ids": [],
        }
        return dict(request)

    def receive(self, task_id: str, actor: str, limit: int = 20) -> list[dict]:
        return [item for item in self.messages if item["task_id"] == task_id and item["recipient_ref"] == actor and item["message_id"] not in self.acks][:limit]

    def read_message(self, task_id: str, actor: str, message_id: str) -> dict:
        for item in self.messages:
            if item["task_id"] == task_id and item["recipient_ref"] == actor and item["message_id"] == message_id:
                return dict(item)
        raise PeerAdapterError("REPLY_PARENT_MISMATCH", "missing parent")

    def ack(self, task_id: str, actor: str, message_id: str, payload_digest: str, epoch: int, invocation: str) -> dict:
        item = self.read_message(task_id, actor, message_id)
        if item["payload_digest"] != payload_digest:
            raise PeerAdapterError("ACK_SCOPE_MISMATCH", "digest differs")
        self.acks.add(message_id)
        self.statuses[message_id].update({"state": "acked", "ack": True})
        return {"message_id": message_id, "payload_digest": payload_digest, "ack": True}

    def reply(self, request: dict) -> dict:
        parent = next(item for item in self.messages if item["message_id"] == request["parent_message_id"])
        if request["parent_message_id"] not in self.acks:
            raise PeerAdapterError("MISSING_ACK", "parent is not acknowledged")
        self.messages.append(dict(request))
        self.statuses[parent["message_id"]]["reply_ids"].append(request["message_id"])
        return dict(request)

    def status(self, task_id: str, actor: str, message_id: str) -> dict:
        return dict(self.statuses[message_id])


def test_owner_file_rechecks_sources_and_directed_peers(tmp_path: Path) -> None:
    path = _owner(tmp_path)
    owner = OwnerFile(path, clock=lambda: 1_700_000_000.0)
    assert owner.read_task("task-1")["task_id"] == "task-1"
    assert owner.read_binding("task-1", "actor-a")["capability_ref"] == "cap-a"
    assert owner.authorize(owner.read_binding("task-1", "actor-a"), "actor-a", "actor-b", "send") is True
    assert owner.authorize(owner.read_binding("task-1", "actor-a"), "actor-a", "actor-a", "send") is False
    (tmp_path / "source.txt").write_text("source-v2\n", encoding="utf-8")
    with pytest.raises(OwnerFileError) as raised:
        owner.read_task("task-1")
    assert raised.value.code == "SOURCE_BINDING_INVALID"


def test_owner_reader_keeps_idle_recipient_binding_readable(tmp_path: Path) -> None:
    path = _owner(tmp_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["actors"]["actor-b"]["actor_status"] = "idle"
    path.write_text(json.dumps(document), encoding="utf-8")
    owner = OwnerFile(path, clock=lambda: 1_700_000_000.0)
    idle = owner.read_binding("task-1", "actor-b")
    active = owner.read_binding("task-1", "actor-a")
    assert idle["actor_status"] == "idle"
    assert owner.authorize(active, "actor-a", "actor-b", "send") is True


def test_payload_store_is_immutable_and_redacts_secret_refusal(tmp_path: Path) -> None:
    store = PayloadStore(tmp_path / "payloads")
    payload_ref, digest = store.put("hello", ["evidence/1"])
    assert store.get(payload_ref, digest) == {"text": "hello", "evidence_refs": ["evidence/1"]}
    assert store.put("hello", ["evidence/1"]) == (payload_ref, digest)
    with pytest.raises(PayloadError) as raised:
        store.put("api_key=super-secret-value", [])
    assert raised.value.code == "PAYLOAD_REJECTED"
    assert "super-secret" not in str(raised.value)


def test_peer_facade_send_receive_ack_reply_and_status(tmp_path: Path) -> None:
    owner_path = _owner(tmp_path)
    transport = FakeTransport()
    clock = lambda: 1_700_000_000.0
    sender = PeerTools(owner_path, "actor-a", 1, "invocation-a", clock=clock, transport=transport)
    receiver = PeerTools(owner_path, "actor-b", 1, "invocation-b", clock=clock, transport=transport, payload_store=sender.payloads)
    sent = sender.peer_send("actor-b", "question", "key-1", ["source/ref"])
    incoming = receiver.peer_receive()["messages"]
    assert incoming[0]["message_id"] == sent["message_id"]
    receiver.peer_ack(sent["message_id"], sent["payload_digest"])
    reply = receiver.peer_reply(sent["message_id"], "answer", "reply-1")
    assert reply["parent_message_id"] == sent["message_id"]
    assert sender.peer_receive()["messages"][0]["message_id"] == reply["message_id"]
    assert sender.peer_status(sent["message_id"])["ack"] is True
    replay = sender.peer_send("actor-b", "question", "key-1", ["source/ref"])
    assert replay["message_id"] == sent["message_id"]


def test_peer_facade_rejects_stale_startup_identity(tmp_path: Path) -> None:
    with pytest.raises(PeerAdapterError) as raised:
        PeerTools(_owner(tmp_path), "actor-a", 2, "invocation-a", transport=FakeTransport())
    assert raised.value.code == "STALE_ACTOR"


def test_mcp_registration_exposes_exact_six_tools(tmp_path: Path) -> None:
    peer = PeerTools(_owner(tmp_path), "actor-a", 1, "invocation-a", transport=FakeTransport())
    server = create_mcp_server(peer)

    async def listed() -> set[str]:
        result = await server.list_tools()
        items = result.tools if hasattr(result, "tools") else result
        return {item.name for item in items}

    assert asyncio.run(listed()) == set(EXACT_TOOLS)


def test_actual_mcp_client_stdio_smoke_against_available_transport(tmp_path: Path) -> None:
    try:
        from mcp import Client, StdioServerParameters
    except ImportError:
        pytest.skip("MCP SDK is not installed in this test interpreter")
    owner_path = _owner(tmp_path)
    codex_runtime = Path(__file__).resolve().parents[1] / "runtime"

    async def smoke() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[str(codex_runtime / "task_swarm" / "mcp_server.py"), "--binding", str(owner_path),
                  "--actor", "actor-a", "--epoch", "1", "--invocation", "invocation-a"],
        )
        async with Client(parameters) as client:
            listed = await client.list_tools()
            items = listed.tools if hasattr(listed, "tools") else listed
            assert {item.name for item in items} == set(EXACT_TOOLS)
            result = await client.call_tool("peer_list", {})
            assert result.is_error is False

    asyncio.run(smoke())


def test_running_tool_cannot_silently_adopt_changed_task_context(tmp_path: Path) -> None:
    owner_path = _owner(tmp_path)
    tools = PeerTools(owner_path, "actor-a", 1, "invocation-a", transport=FakeTransport())
    document = json.loads(owner_path.read_text(encoding="utf-8"))
    document["binding"]["revision"] += 1
    owner_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(PeerAdapterError, match="STALE_CONTEXT"):
        tools.peer_list()


@pytest.mark.parametrize("text", ["xox"+"b-"+"1"*12+"-"+"2"*12+"-"+"a"*16, '{"token":"plain-value"}', '{"password":"plain-value"}'])
def test_shared_credential_shapes_are_rejected(tmp_path, text):
    store = PayloadStore(tmp_path / "payloads")
    with pytest.raises(PayloadError) as raised:
        store.put(text, [])
    assert text not in str(raised.value)
