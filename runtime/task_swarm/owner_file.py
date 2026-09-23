"""Fail-closed reader for the local Task swarm owner document.

The JSON document is an operator supplied execution input.  It is deliberately
small: the owner supplies the Task binding, the actor leases, the directed
peer graph, and exact local storage.  This module never issues a grant or
mutates a Task.  Every public read re-reads the document and its source
digests, so a changed owner file or source is observed at the next action.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from typing import Any, Callable, Mapping

from .protocol import (
    ACTOR_FIELDS,
    TASK_FIELDS,
    SwarmError,
    digest_ref,
    integer,
    ref,
    timestamp,
    validate_binding,
)


_DIGEST_RE = re.compile(r"^[a-f0-9]{64}$")
_ACTIONS = frozenset({"send", "receive", "ack", "reply", "status"})
_ACTOR_STATES = frozenset({"active", "idle", "closed", "revoked"})
_MAX_ACTORS = 256
_MAX_PEERS = 256
_MAX_PATH = 4096


class OwnerFileError(SwarmError):
    """Typed refusal raised when the owner input is unavailable or unsafe."""


@dataclass(frozen=True)
class OwnerSnapshot:
    task: dict[str, Any]
    actors: dict[str, dict[str, Any]]
    storage: dict[str, Path]
    allowed_actions: frozenset[str]


def _error(code: str, detail: str) -> None:
    raise OwnerFileError(code, detail)


def _text(value: Any, name: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        _error("BINDING_UNAVAILABLE", f"invalid {name}")
    return value


def _digest(value: Any, name: str) -> str:
    try:
        return digest_ref(value, name)
    except SwarmError as exc:
        raise OwnerFileError(exc.code, exc.detail) from exc


def _has_parent_part(raw: str) -> bool:
    # Path.parts is platform aware.  The extra slash checks reject a foreign
    # separator on Windows before it can be normalized by Path.resolve().
    return any(part == ".." for part in Path(raw.replace("/", "\\")).parts)


def _safe_resolve(raw: Any, *, base: Path, name: str, must_be_below: Path | None = None) -> Path:
    value = _text(raw, name, maximum=_MAX_PATH)
    if _has_parent_part(value):
        _error("PATH_ESCAPE", f"{name} contains traversal")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = base / candidate
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise OwnerFileError("PATH_ESCAPE", f"{name} cannot resolve") from exc
    if must_be_below is not None:
        try:
            relative = resolved.relative_to(must_be_below)
        except ValueError as exc:
            raise OwnerFileError("STORAGE_ESCAPE", f"{name} is outside the selected storage root") from exc
        if not relative.parts:
            _error("STORAGE_ESCAPE", f"{name} must be below the selected storage root")
    return resolved


def _reject_symlink_components(path: Path, *, stop: Path | None = None, field: str) -> None:
    """Reject a symlink/junction anywhere in an owner controlled path.

    ``Path.resolve`` alone would make a link to an outside directory appear
    safe after the fact.  Checking the existing components first makes that
    escape explicit and also prevents later replacement of a child directory
    with a link from silently widening the grant.
    """

    resolved_stop = stop.resolve(strict=False) if stop is not None else None
    current = path
    components: list[Path] = []
    while True:
        components.append(current)
        if resolved_stop is not None:
            try:
                current.relative_to(resolved_stop)
                if current == resolved_stop:
                    break
            except ValueError:
                pass
        if current.parent == current:
            break
        current = current.parent
    for component in reversed(components):
        try:
            if component.exists() and component.is_symlink():
                _error("PATH_ESCAPE", f"{field} contains a symlink")
        except OSError as exc:
            raise OwnerFileError("PATH_ESCAPE", f"{field} cannot be inspected") from exc


def _validate_actor(actor_ref: Any, value: Any) -> tuple[str, dict[str, Any]]:
    actor = _text(actor_ref, "actor_ref", maximum=256)
    if not isinstance(value, Mapping):
        _error("BINDING_UNAVAILABLE", "actor entry is not an object")
    actor_data = dict(value)
    for key in ("epoch", "invocation_ref", "actor_status", "capability_ref", "peers"):
        if key not in actor_data:
            _error("BINDING_UNAVAILABLE", f"actor {actor} is missing {key}")
    try:
        integer(actor_data["epoch"], "actor epoch", maximum=2**53 - 1)
    except SwarmError as exc:
        raise OwnerFileError(exc.code, exc.detail) from exc
    _text(actor_data["invocation_ref"], "invocation_ref")
    _text(actor_data["capability_ref"], "capability_ref")
    status = actor_data["actor_status"]
    if status not in _ACTOR_STATES:
        _error("INVALID_ACTOR_STATE", "unknown actor state")
    peers = actor_data["peers"]
    if not isinstance(peers, list) or len(peers) > _MAX_PEERS:
        _error("BINDING_UNAVAILABLE", "actor peers must be a bounded list")
    normalized_peers: list[str] = []
    for peer in peers:
        normalized_peers.append(_text(peer, "peer_ref", maximum=256))
    if len(normalized_peers) != len(set(normalized_peers)):
        _error("BINDING_UNAVAILABLE", "actor peers must be unique")
    actor_data["epoch"] = int(actor_data["epoch"])
    actor_data["peers"] = normalized_peers
    return actor, actor_data


class OwnerFile:
    """Read and validate one operator-selected owner JSON file."""

    def __init__(self, path: str | os.PathLike[str], *, clock: Callable[[], float] = time.time) -> None:
        raw = Path(path)
        try:
            self.path = raw.expanduser().resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise OwnerFileError("BINDING_UNAVAILABLE", "owner path cannot resolve") from exc
        if not self.path.is_absolute():  # defensive; resolve normally guarantees this
            _error("BINDING_UNAVAILABLE", "owner path must be absolute")
        self.clock = clock
        self._selected_root: Path | None = None

    def _read_json(self) -> Mapping[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8")
            document = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OwnerFileError("BINDING_UNAVAILABLE", "owner file cannot be read") from exc
        if not isinstance(document, Mapping):
            _error("BINDING_UNAVAILABLE", "owner file must be a JSON object")
        return document

    def _source_checks(self, document: Mapping[str, Any]) -> None:
        checks = document.get("source_checks")
        if not isinstance(checks, list):
            _error("SOURCE_BINDING_INVALID", "source_checks must be a list")
        for check in checks:
            if not isinstance(check, Mapping):
                _error("SOURCE_BINDING_INVALID", "source check is not an object")
            source = _safe_resolve(check.get("path"), base=self.path.parent, name="source path")
            expected = _digest(check.get("sha256"), "source sha256")
            _reject_symlink_components(source, stop=self.path.parent, field="source path")
            if not source.is_file():
                _error("SOURCE_BINDING_INVALID", "source file is unavailable")
            try:
                actual = hashlib.sha256(source.read_bytes()).hexdigest()
            except OSError as exc:
                raise OwnerFileError("SOURCE_BINDING_INVALID", "source file cannot be read") from exc
            if actual != expected:
                _error("SOURCE_BINDING_INVALID", "source digest changed")

    def _storage(self, document: Mapping[str, Any]) -> dict[str, Path]:
        raw_storage = document.get("storage")
        if not isinstance(raw_storage, Mapping):
            _error("STORAGE_INVALID", "storage is missing")
        root = _safe_resolve(raw_storage.get("root"), base=self.path.parent, name="storage root")
        _reject_symlink_components(root, stop=self.path.parent, field="storage root")
        if self._selected_root is None:
            self._selected_root = root
        elif root != self._selected_root:
            _error("STORAGE_CHANGED", "operator selected storage root changed")
        values: dict[str, Path] = {"root": root}
        for key in ("mailbox", "payloads"):
            path = _safe_resolve(raw_storage.get(key), base=root, name=f"storage {key}", must_be_below=root)
            _reject_symlink_components(path, stop=root, field=f"storage {key}")
            values[key] = path
        return values

    def _snapshot(self) -> OwnerSnapshot:
        document = self._read_json()
        raw_task = document.get("binding")
        if not isinstance(raw_task, Mapping):
            _error("BINDING_UNAVAILABLE", "binding is missing")
        try:
            task = validate_binding(dict(raw_task), now=float(self.clock()), actor=None)
        except (SwarmError, TypeError, ValueError) as exc:
            if isinstance(exc, OwnerFileError):
                raise
            if isinstance(exc, SwarmError):
                raise OwnerFileError(exc.code, exc.detail) from exc
            raise OwnerFileError("BINDING_UNAVAILABLE", "owner binding is invalid") from exc

        raw_actors = document.get("actors")
        if not isinstance(raw_actors, Mapping) or not raw_actors or len(raw_actors) > _MAX_ACTORS:
            _error("BINDING_UNAVAILABLE", "actors are missing or unbounded")
        actors: dict[str, dict[str, Any]] = {}
        for key, value in raw_actors.items():
            actor, normalized = _validate_actor(key, value)
            actors[actor] = normalized
        for actor, actor_data in actors.items():
            if any(peer not in actors for peer in actor_data["peers"]):
                _error("BINDING_UNAVAILABLE", f"actor {actor} references an unknown peer")

        raw_allowed = document.get("allowed_actions")
        if not isinstance(raw_allowed, list):
            _error("BINDING_UNAVAILABLE", "allowed_actions must be a list")
        allowed = frozenset(_text(item, "allowed action", maximum=32) for item in raw_allowed)
        if not allowed.issubset(_ACTIONS):
            _error("BINDING_UNAVAILABLE", "unknown allowed action")

        self._source_checks(document)
        storage = self._storage(document)
        return OwnerSnapshot(task=dict(task), actors=actors, storage=storage, allowed_actions=allowed)

    @property
    def task_id(self) -> str:
        """Return the current Task ID after a full owner/source check."""

        return str(self._snapshot().task["task_id"])

    def read_task(self, task_id: str | None = None) -> dict[str, Any]:
        snapshot = self._snapshot()
        if task_id is not None and snapshot.task["task_id"] != task_id:
            _error("WRONG_TASK", "owner binding belongs to another Task")
        return dict(snapshot.task)

    def read_binding(self, task_id: str, actor_ref: str) -> dict[str, Any]:
        snapshot = self._snapshot()
        if snapshot.task["task_id"] != task_id:
            _error("WRONG_TASK", "owner binding belongs to another Task")
        actor = _text(actor_ref, "actor_ref", maximum=256)
        current = snapshot.actors.get(actor)
        if current is None:
            _error("ACTOR_UNKNOWN", "actor is not present in owner input")
        if current["actor_status"] in {"closed", "revoked"}:
            _error("ACTOR_REVOKED", "actor lease is revoked")
        combined = dict(snapshot.task)
        combined.update(
            {
                "actor_ref": actor,
                "epoch": current["epoch"],
                "invocation_ref": current["invocation_ref"],
                "actor_status": current["actor_status"],
                "capability_ref": current["capability_ref"],
            }
        )
        try:
            # Transport needs to inspect an idle recipient binding so queued
            # accepted work remains receivable after its sender becomes idle.
            # The invoking adapter separately requires its own actor to be
            # active before any tool call.
            return validate_binding(combined, now=float(self.clock()), actor=actor, require_active_actor=False)
        except SwarmError as exc:
            raise OwnerFileError(exc.code, exc.detail) from exc

    def authorize(self, binding: Mapping[str, Any], actor_ref: str, peer_ref: str, action: str) -> bool:
        """Return a current directed grant without trusting request content."""

        try:
            actor = _text(actor_ref, "actor_ref", maximum=256)
            peer = _text(peer_ref, "peer_ref", maximum=256)
            operation = _text(action, "action", maximum=32)
            if operation not in _ACTIONS:
                return False
            task_id = binding.get("task_id")
            current = self.read_binding(task_id, actor)
            if dict(current) != dict(binding):
                return False
            # Permission and execution liveness are separate. The tool facade
            # and transport write paths fence the invoking active lease. An
            # idle recipient can still have a valid future receive grant.
            snapshot = self._snapshot()
            actor_doc = snapshot.actors.get(actor)
            peer_doc = snapshot.actors.get(peer)
            if actor_doc is None or peer_doc is None:
                return False
            if operation not in snapshot.allowed_actions:
                return False
            if peer == actor or peer not in actor_doc["peers"]:
                return False
            if peer_doc["actor_status"] in {"closed", "revoked"}:
                return False
            return True
        except (OwnerFileError, SwarmError, TypeError, ValueError):
            return False

    def peers(self, actor_ref: str) -> list[dict[str, Any]]:
        snapshot = self._snapshot()
        actor = _text(actor_ref, "actor_ref", maximum=256)
        current = snapshot.actors.get(actor)
        if current is None:
            _error("ACTOR_UNKNOWN", "actor is not present in owner input")
        result: list[dict[str, Any]] = []
        for peer in current["peers"]:
            peer_doc = snapshot.actors.get(peer)
            if peer_doc is None or peer_doc["actor_status"] in {"closed", "revoked"}:
                continue
            result.append(
                {
                    "actor_ref": peer,
                    "actor_status": peer_doc["actor_status"],
                    "capability_ref": peer_doc["capability_ref"],
                }
            )
        return result

    def storage(self) -> dict[str, Path]:
        """Return the current exact storage paths after all integrity checks."""

        return dict(self._snapshot().storage)


__all__ = ["OwnerFile", "OwnerFileError", "OwnerSnapshot"]
