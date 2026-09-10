"""Shared validation for owner-supplied bindings, never a grant issuer."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from typing import Any, Mapping


class SwarmError(RuntimeError):
    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


def finite(value: Any, name: str, minimum: float = 0, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SwarmError("INVALID_LIMIT", f"{name} must be finite")
    number = float(value)
    if number < minimum or (maximum is not None and number > maximum):
        raise SwarmError("INVALID_LIMIT", f"{name} is outside its allowed range")
    return number


def integer(value: Any, name: str, minimum: int = 1, maximum: int = 10000) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise SwarmError("INVALID_LIMIT", f"{name} must be a bounded integer")
    return value


def ref(value: Any, name: str = "reference", maximum: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise SwarmError("INVALID_REFERENCE", f"invalid {name}")
    return value


def digest_ref(value: Any, name: str = "digest") -> str:
    if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise SwarmError("INVALID_DIGEST", f"invalid {name}")
    return value


def canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise SwarmError("INVALID_DOCUMENT", "document must be finite JSON") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def timestamp(value: Any) -> float:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("timezone required")
            value = parsed.timestamp()
        except (ValueError, OverflowError) as exc:
            raise SwarmError("INVALID_DEADLINE", "deadline needs an explicit UTC offset") from exc
    return finite(value, "deadline")


TASK_FIELDS = ("task_id", "revision", "context_digest", "owner_ref", "active_home",
               "authority_ref", "capability_ref", "expires_at", "status")
ACTOR_FIELDS = ("actor_ref", "epoch", "invocation_ref", "actor_status")
SCOPE_FIELDS = ("task_id", "revision", "context_digest", "owner_ref", "active_home", "authority_ref")


def validate_binding(value: Mapping[str, Any], *, now: float, actor: str | None = None,
                     require_active_actor: bool = True) -> dict[str, Any]:
    finite(now, "host clock")
    required = TASK_FIELDS + (ACTOR_FIELDS if actor is not None else ())
    if not isinstance(value, Mapping) or any(key not in value for key in required):
        raise SwarmError("BINDING_UNAVAILABLE", "owner supplied binding is incomplete")
    result = {key: value[key] for key in required}
    for key in ("task_id", "owner_ref", "active_home", "authority_ref", "capability_ref"):
        ref(result[key], key)
    integer(result["revision"], "Task revision", maximum=2**53-1)
    digest_ref(result["context_digest"], "context digest")
    result["expires_at"] = timestamp(result["expires_at"])
    if result["expires_at"] <= now:
        raise SwarmError("EXPIRED_BINDING", "owner binding expired")
    if result["status"] not in ("active", "validating"):
        raise SwarmError("INACTIVE_TASK", "Task does not permit active work")
    if actor is not None:
        if result["actor_ref"] != actor:
            raise SwarmError("WRONG_ACTOR", "binding belongs to another actor")
        ref(actor, "actor")
        ref(result["invocation_ref"], "invocation")
        integer(result["epoch"], "actor epoch", maximum=2**53-1)
        if result["actor_status"] not in ("active", "idle", "closed"):
            raise SwarmError("INVALID_ACTOR_STATE", "unknown actor state")
        if require_active_actor and result["actor_status"] != "active":
            raise SwarmError("INACTIVE_ACTOR", "actor has no active execution lease")
    return result


def scope_key(binding: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(binding[key] for key in SCOPE_FIELDS)
