"""Local Codex subprocess backend for one bounded Task swarm attempt.

The backend starts one explicitly supplied executable with a fixed read-only
worker policy, captures only redacted artifacts below a fresh attempt
directory, and refuses completion until the child process can be connected to
local runtime metadata by its stdout thread UUID and a completed turn.
"""

from __future__ import annotations

import json
import hashlib
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, Callable
import uuid

from .owner_file import OwnerFile, OwnerFileError
from .mcp_server import EXACT_TOOLS
from .protocol import SwarmError, ref
from .privacy import TOKEN_PATTERN

try:  # Declared in the task runtime, but keep import errors typed.
    import psutil
except ImportError:  # pragma: no cover - exercised only in a reduced runtime
    psutil = None  # type: ignore[assignment]


MODEL = "gpt-5.6-luna"
EFFORT = "max"
SANDBOX = "read-only"
APPROVAL_POLICY = "never"
MAX_TIMEOUT = 3600.0
_READ_TOOLS = frozenset({"peer_list", "peer_receive", "peer_status"})


class BackendError(RuntimeError):
    """Safe, typed local execution failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        paths: Mapping[str, str] | None = None,
        diagnostics: Mapping[str, Any] | None = None,
        receipt: Mapping[str, Any] | None = None,
    ) -> None:
        self.code = str(code)
        self.message = str(message)
        self.retryable = bool(retryable)
        self.paths = dict(paths or {})
        self.diagnostics = dict(diagnostics or {})
        self.receipt = dict(receipt or {})
        super().__init__(f"{self.code}: {self.message}")


class _RuntimeResolutionError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        self.code = code
        self.details = dict(details or {})
        super().__init__(message)


_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9._-]{10,}\.[A-Za-z0-9._-]{8,}\b")
_TOKEN_RE = TOKEN_PATTERN
_AUTH_RE = re.compile(r"(?i)(\b(?:authorization|proxy-authorization)\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:access_token|api[_-]?key|apikey|auth|authorization|key|secret|refresh_token|token)=)[^&#\s]+"
)
_KEY_VALUE_SECRET_RE = re.compile(
    r'''(?i)(["']?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|token|password|passwd|secret|authorization)["']?\s*[:=\s]+)("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^,\s;}\]]+)'''
)
_SENSITIVE_KEYS = {
    "authorization",
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "password",
    "refresh_token",
    "secret",
    "token",
}
_ID_RE = re.compile(r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")


def _utc_iso(value: float | None = None) -> str:
    stamp = time.time() if value is None else float(value)
    return datetime.fromtimestamp(stamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_text(value: Any) -> str:
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    text = _JWT_RE.sub("[REDACTED_JWT]", text)
    text = _TOKEN_RE.sub("[REDACTED_TOKEN]", text)
    text = _AUTH_RE.sub(r"\1[REDACTED]", text)
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _QUERY_SECRET_RE.sub(r"\1[REDACTED]", text)

    def hide(match: re.Match[str]) -> str:
        value = match.group(2)
        quote = value[0] if value and value[0] in ('"', "'") else ""
        return match.group(1) + quote + "[REDACTED]" + quote

    return _KEY_VALUE_SECRET_RE.sub(hide, text)


def _sensitive_key(key: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9_]", "", str(key).lower())
    return normalized in {re.sub(r"[^a-z0-9_]", "", item) for item in _SENSITIVE_KEYS}


def _redact(value: Any, *, key: Any = None) -> Any:
    if key is not None and _sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(k): _redact(v, key=k) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _safe_text(value)
    return value


def _json_dump(value: Any) -> str:
    try:
        return json.dumps(_redact(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        return json.dumps({"redacted": "unserializable"}, separators=(",", ":"))


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _write_json(path: Path, value: Any) -> None:
    _atomic_write(path, (_json_dump(value) + "\n").encode("utf-8"))


def _load_schema(value: Mapping[str, Any] | str | os.PathLike[str]) -> dict[str, Any]:
    if isinstance(value, Mapping):
        schema = dict(value)
    else:
        try:
            schema = json.loads(Path(value).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise BackendError("schema_invalid", "output schema cannot be read", retryable=False) from exc
    if not isinstance(schema, dict):
        raise BackendError("schema_invalid", "output schema must be an object", retryable=False)
    return schema


def _validate_schema(value: Any, schema: Mapping[str, Any], *, path: str = "$", root: Mapping[str, Any] | None = None) -> None:
    """Strict standard-library JSON Schema subset used for worker results."""

    root = schema if root is None else root
    reference = schema.get("$ref")
    if isinstance(reference, str):
        for prefix in ("#/$defs/", "#/definitions/"):
            if reference.startswith(prefix):
                target = root.get("$defs" if prefix == "#/$defs/" else "definitions")
                name = reference[len(prefix) :]
                if not isinstance(target, Mapping) or not isinstance(target.get(name), Mapping):
                    raise ValueError(f"unresolved $ref at {path}")
                _validate_schema(value, target[name], path=path, root=root)
                return
        raise ValueError(f"unsupported $ref at {path}")
    for composite in ("allOf",):
        if composite in schema:
            items = schema[composite]
            if not isinstance(items, list):
                raise ValueError(f"invalid {composite} at {path}")
            for child in items:
                if not isinstance(child, Mapping):
                    raise ValueError(f"invalid {composite} at {path}")
                _validate_schema(value, child, path=path, root=root)
    for composite in ("anyOf", "oneOf"):
        if composite in schema:
            items = schema[composite]
            if not isinstance(items, list):
                raise ValueError(f"invalid {composite} at {path}")
            matches = 0
            for child in items:
                if not isinstance(child, Mapping):
                    continue
                try:
                    _validate_schema(value, child, path=path, root=root)
                except ValueError:
                    continue
                matches += 1
            if matches < 1 or composite == "oneOf" and matches != 1:
                raise ValueError(f"{composite} mismatch at {path}")
    expected = schema.get("type")
    types = expected if isinstance(expected, list) else [expected] if expected is not None else []

    def type_matches(kind: Any) -> bool:
        if kind == "object":
            return isinstance(value, dict)
        if kind == "array":
            return isinstance(value, list)
        if kind == "string":
            return isinstance(value, str)
        if kind == "boolean":
            return isinstance(value, bool)
        if kind == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if kind == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))
        if kind == "null":
            return value is None
        return False

    if types and not any(type_matches(item) for item in types):
        raise ValueError(f"type mismatch at {path}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"enum mismatch at {path}")
    if "const" in schema and value != schema["const"]:
        raise ValueError(f"const mismatch at {path}")
    if isinstance(value, dict):
        required = schema.get("required", [])
        if not isinstance(required, list):
            raise ValueError(f"invalid required at {path}")
        for name in required:
            if name not in value:
                raise ValueError(f"required property missing at {path}")
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            raise ValueError(f"invalid properties at {path}")
        for name, child in properties.items():
            if name in value and isinstance(child, Mapping):
                _validate_schema(value[name], child, path=f"{path}.{name}", root=root)
        if schema.get("additionalProperties") is False:
            for name in value:
                if name not in properties:
                    raise ValueError(f"additional property at {path}")
        elif isinstance(schema.get("additionalProperties"), Mapping):
            for name in value:
                if name not in properties:
                    _validate_schema(value[name], schema["additionalProperties"], path=f"{path}.{name}", root=root)
    elif isinstance(value, list):
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            raise ValueError(f"minItems mismatch at {path}")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise ValueError(f"maxItems mismatch at {path}")
        items = schema.get("items")
        if isinstance(items, Mapping):
            for index, item in enumerate(value):
                _validate_schema(item, items, path=f"{path}[{index}]", root=root)
    elif isinstance(value, str):
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            raise ValueError(f"minLength mismatch at {path}")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            raise ValueError(f"maxLength mismatch at {path}")
        if "pattern" in schema and re.search(str(schema["pattern"]), value) is None:
            raise ValueError(f"pattern mismatch at {path}")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ValueError(f"minimum mismatch at {path}")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValueError(f"maximum mismatch at {path}")


def _prepare_attempt(attempt_dir: str | os.PathLike[str]) -> Path:
    base = Path(attempt_dir).expanduser().resolve(strict=False)
    if base.exists() and not base.is_dir():
        raise BackendError("attempt_dir_invalid", "attempt_dir is not a directory", retryable=False)
    try:
        base.mkdir(parents=True, exist_ok=True)
        run = base / f"attempt-{uuid.uuid4().hex}"
        run.mkdir()
    except OSError as exc:
        raise BackendError("attempt_dir_invalid", "attempt directory cannot be created", retryable=False) from exc
    return run


def _paths(run: Path) -> dict[str, Path]:
    return {
        "attempt_dir": run,
        "schema": run / "schema.json",
        "events": run / "stdout-events.jsonl",
        "stderr": run / "stderr.log",
        "last_message": run / "last-message.json",
        "result": run / "result.json",
        "receipt": run / "receipt.json",
        "process": run / "process.json",
        "diagnostics": run / "diagnostics.json",
        "command": run / "command.json",
    }


def _public_paths(paths: Mapping[str, Path]) -> dict[str, str]:
    return {key: str(path) for key, path in paths.items()}


def _decode(value: bytes | str | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def _parse_events(stdout: str) -> tuple[list[dict[str, Any]], int, str | None]:
    records: list[dict[str, Any]] = []
    malformed = 0
    last_error: str | None = None
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            malformed += 1
            last_error = f"line {exc.lineno} column {exc.colno}"
            continue
        if isinstance(value, dict):
            records.append(value)
        else:
            malformed += 1
            last_error = "non-object JSON event"
    return records, malformed, last_error


def _outer_payload(record: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    payload = record.get("payload")
    return record, payload if isinstance(payload, Mapping) else record


def _event_identity(records: Sequence[Mapping[str, Any]]) -> tuple[str | None, str | None]:
    threads: set[str] = set()
    turns: set[str] = set()
    for record in records:
        outer, payload = _outer_payload(record)
        for source in (outer, payload):
            candidate = source.get("thread_id") or source.get("session_id")
            if isinstance(candidate, str) and candidate:
                if _ID_RE.fullmatch(candidate) is None:
                    raise BackendError("stdout_identity_invalid", "stdout thread is not a UUID", retryable=False)
                threads.add(candidate)
            candidate = source.get("turn_id")
            if isinstance(candidate, str) and candidate:
                if _ID_RE.fullmatch(candidate) is None:
                    raise BackendError("stdout_identity_invalid", "stdout turn is not a UUID", retryable=False)
                turns.add(candidate)
    if len(threads) > 1 or len(turns) > 1:
        raise BackendError("stdout_identity_ambiguous", "stdout contains conflicting runtime identities", retryable=False)
    return next(iter(threads), None), next(iter(turns), None)


def _runtime_roots(explicit: Path | None) -> list[Path]:
    roots: list[Path] = []
    if explicit is not None:
        roots.append(explicit)
    override = os.environ.get("CODEX_SESSIONS_DIR")
    if explicit is None and override:
        roots.append(Path(override))
    elif explicit is None:
        home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        roots.append(home / "sessions")
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            resolved = root.expanduser().resolve(strict=False)
        except (OSError, RuntimeError):
            continue
        marker = os.path.normcase(str(resolved))
        if marker not in seen:
            seen.add(marker)
            unique.append(resolved)
    return unique


def _runtime_receipt(thread_id: str, turn_id: str | None, session_root: Path | None, expected_cwd: Path,
                     started_unix: float | None = None) -> dict[str, Any] | None:
    if not isinstance(thread_id, str) or _ID_RE.fullmatch(thread_id) is None:
        raise _RuntimeResolutionError("runtime_thread_invalid", "stdout thread identity is invalid")
    candidates: list[Path] = []
    for root in _runtime_roots(session_root):
        if not root.is_dir():
            continue
        try:
            for candidate in root.rglob(f"*{thread_id}*.jsonl"):
                if candidate.is_file() and thread_id in candidate.name:
                    try:
                        resolved = candidate.resolve(strict=True)
                        resolved.relative_to(root)
                    except (OSError, RuntimeError, ValueError):
                        continue
                    candidates.append(resolved)
        except OSError:
            continue
    unique = sorted({os.path.normcase(str(path)): path for path in candidates}.values())
    if not unique:
        return None
    contexts: dict[str, Mapping[str, Any]] = {}
    completions: dict[str, Mapping[str, Any]] = {}
    failures: set[str] = set()
    runtime_cwds: dict[str, str] = {}
    valid_paths: list[Path] = []
    mismatch = False
    for path in unique:
        session_identity: str | None = None
        session_cwd: str | None = None
        session_started: float | None = None
        file_contexts: dict[str, Mapping[str, Any]] = {}
        file_completions: dict[str, Mapping[str, Any]] = {}
        file_failures: set[str] = set()
        file_cwds: dict[str, str] = {}
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                record = json.loads(line)
            except (TypeError, ValueError):
                continue
            if not isinstance(record, Mapping):
                continue
            outer, payload = _outer_payload(record)
            record_type = str(outer.get("type", "")).lower()
            identity = payload.get("id") or payload.get("session_id")
            if record_type == "session_meta" and isinstance(identity, str) and identity:
                session_identity = identity
                if isinstance(payload.get("cwd"), str):
                    session_cwd = payload["cwd"]
                stamp = payload.get("timestamp") or outer.get("timestamp")
                if isinstance(stamp, str):
                    try:
                        parsed_stamp = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                        if parsed_stamp.tzinfo is not None:
                            session_started = parsed_stamp.timestamp()
                    except (ValueError, OverflowError):
                        pass
                if identity != thread_id:
                    mismatch = True
                    break
            event_thread = payload.get("thread_id") or outer.get("thread_id")
            if isinstance(event_thread, str) and event_thread != thread_id:
                mismatch = True
                break
            event_turn = payload.get("turn_id") or outer.get("turn_id")
            if not isinstance(event_turn, str) or not event_turn:
                continue
            if record_type == "turn_context":
                file_contexts[event_turn] = payload
                for key in ("cwd", "working_directory", "workdir", "runtime_cwd"):
                    value = payload.get(key)
                    if isinstance(value, str) and value:
                        file_cwds[event_turn] = value
                        break
            event_kind = str(payload.get("type", "")).lower()
            if record_type in {"event_msg", "event.message"} and event_kind in {"task_complete", "turn.completed", "turn_complete"}:
                file_completions[event_turn] = payload
            elif record_type in {"turn.completed", "turn_complete"}:
                file_completions[event_turn] = payload
            elif record_type in {"event_msg", "event.message"} and event_kind in {"task_failed", "turn_failed", "turn.failed", "turn_error"}:
                file_failures.add(event_turn)
        if mismatch:
            continue
        if session_identity != thread_id:
            continue
        if started_unix is not None and (session_started is None or session_started < started_unix - 2
                                         or session_started > time.time() + 2):
            raise _RuntimeResolutionError("runtime_not_fresh", "runtime session is not bound to this process start")
        if session_cwd:
            for context_turn in file_contexts:
                file_cwds.setdefault(context_turn, session_cwd)
        valid_paths.append(path)
        contexts.update(file_contexts)
        completions.update(file_completions)
        failures.update(file_failures)
        runtime_cwds.update(file_cwds)
    if not valid_paths:
        if mismatch:
            raise _RuntimeResolutionError("runtime_thread_mismatch", "rollout metadata belongs to another thread")
        return None
    completed_ids = sorted(completions)
    if turn_id is None:
        if not completed_ids:
            raise _RuntimeResolutionError("runtime_turn_missing", "matching thread has no completed turn")
        if len(completed_ids) != 1:
            raise _RuntimeResolutionError("runtime_turn_ambiguous", "stdout omitted turn_id for multiple completed turns")
        selected = completed_ids[0]
    else:
        selected = turn_id
        if selected not in completions:
            raise _RuntimeResolutionError("runtime_turn_mismatch", "stdout turn_id has no completed local turn")
    context = contexts.get(selected)
    completion = completions.get(selected)
    if context is None or completion is None:
        raise _RuntimeResolutionError("runtime_turn_missing", "completed turn context is unavailable")
    observed_cwd = runtime_cwds.get(selected)
    expected = expected_cwd.resolve(strict=False)
    if not observed_cwd:
        raise _RuntimeResolutionError("runtime_cwd_missing", "runtime did not record its working directory")
    if observed_cwd:
        try:
            if Path(observed_cwd).expanduser().resolve(strict=False) != expected:
                raise _RuntimeResolutionError("runtime_cwd_mismatch", "runtime cwd does not match owned attempt cwd")
        except (OSError, RuntimeError) as exc:
            raise _RuntimeResolutionError("runtime_cwd_invalid", "runtime cwd cannot resolve") from exc
    collaboration = context.get("collaboration_mode")
    settings = collaboration.get("settings") if isinstance(collaboration, Mapping) else {}
    settings = settings if isinstance(settings, Mapping) else {}
    return {
        "thread_id": thread_id,
        "turn_id": selected,
        "model": context.get("model") or settings.get("model"),
        "effort": context.get("effort") or settings.get("reasoning_effort"),
        "model_context": context.get("model"),
        "model_settings": settings.get("model"),
        "effort_context": context.get("effort"),
        "effort_settings": settings.get("reasoning_effort"),
        "sandbox": (context.get("sandbox_policy") or {}).get("type") if isinstance(context.get("sandbox_policy"), Mapping) else None,
        "approval_policy": context.get("approval_policy"),
        "completed": True,
        "turn_failed": selected in failures,
        "runtime_receipt_path": str(valid_paths[0]),
        "runtime_cwd": str(expected),
        "completed_at": completion.get("completed_at"),
        "completed_output": completion.get("last_agent_message"),
    }


def _final_message(records: Sequence[Mapping[str, Any]]) -> str:
    candidate = ""
    for record in records:
        _, payload = _outer_payload(record)
        item = payload.get("item")
        if not isinstance(item, Mapping):
            continue
        if str(item.get("type", "")).lower() not in {"agent_message", "agentmessage", "message"}:
            continue
        if isinstance(item.get("text"), str):
            candidate = item["text"]
        elif isinstance(item.get("content"), list):
            parts = [part.get("text") for part in item["content"] if isinstance(part, Mapping) and isinstance(part.get("text"), str)]
            if parts:
                candidate = "".join(parts)
    return candidate


def _resolve_executable(value: str | os.PathLike[str]) -> tuple[list[str], Path]:
    supplied = Path(value).expanduser()
    candidate: Path | None = None
    if supplied.is_absolute() or supplied.parent != Path("."):
        candidate = supplied
    else:
        found = shutil.which(str(supplied))
        if found:
            candidate = Path(found)
    if candidate is None:
        raise BackendError("executable_missing", "the supplied executable was not found", retryable=False)
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise BackendError("executable_missing", "the supplied executable was not found", retryable=False) from exc
    if not resolved.is_file():
        raise BackendError("executable_missing", "the supplied executable is not a file", retryable=False)
    if resolved.suffix.lower() == ".py":
        return [sys.executable, "-u", str(resolved)], resolved
    return [str(resolved)], resolved


def _process_created(process: subprocess.Popen[bytes]) -> float | None:
    if psutil is None:
        return None
    try:
        return float(psutil.Process(process.pid).create_time())
    except (psutil.Error, OSError, ValueError):
        return None


def _same_process(pid: int, created: float) -> bool:
    if psutil is None:
        return False
    try:
        process = psutil.Process(pid)
        return process.is_running() and math.isclose(float(process.create_time()), created, rel_tol=0.0, abs_tol=0.001)
    except (psutil.Error, OSError, ValueError):
        return False


def _terminate_owned(process: subprocess.Popen[bytes], pid: int, created: float) -> str:
    if process.poll() is not None:
        return "already_exited"
    if not _same_process(pid, created):
        return "identity_not_confirmed"
    try:
        process.terminate()
        process.wait(timeout=2.0)
        return "terminated"
    except subprocess.TimeoutExpired:
        if _same_process(pid, created):
            try:
                process.kill()
                process.wait(timeout=2.0)
                return "killed_after_terminate_timeout"
            except (OSError, subprocess.TimeoutExpired):
                return "kill_failed"
        return "identity_changed_after_terminate"
    except OSError:
        return "terminate_failed"


def _write_events(path: Path, stdout: str, records: Sequence[Mapping[str, Any]]) -> None:
    lines: list[str] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except (TypeError, ValueError):
            lines.append(_safe_text(line))
            continue
        lines.append(_json_dump(value) if isinstance(value, Mapping) else _safe_text(line))
    _atomic_write(path, ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8"))


def _artifact_digests(paths: Mapping[str, Path]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, path in paths.items():
        if name in {"receipt", "diagnostics"} or not path.is_file():
            continue
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
        result[name] = digest
    return result


def _scrub_last_message(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except (FileNotFoundError, OSError):
        return ""
    text = _safe_text(raw)
    try:
        _atomic_write(path, text.encode("utf-8"))
    except OSError:
        pass
    return text


def _peer_config(peer: Mapping[str, Any], *, authorize_peer_writes: bool) -> dict[str, Any]:
    if set(peer) != {"binding", "actor", "epoch", "invocation"}:
        raise BackendError("peer_invalid", "peer configuration has an unexpected shape", retryable=False)
    binding = Path(peer["binding"]).expanduser().resolve(strict=False)
    actor = peer["actor"]
    invocation = peer["invocation"]
    epoch = peer["epoch"]
    if not isinstance(actor, str) or not actor or not isinstance(invocation, str) or not invocation:
        raise BackendError("peer_invalid", "peer actor and invocation are required", retryable=False)
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 1:
        raise BackendError("peer_invalid", "peer epoch is invalid", retryable=False)
    try:
        owner = OwnerFile(binding)
        current = owner.read_binding(owner.task_id, actor)
        if current["epoch"] != epoch or current["invocation_ref"] != invocation:
            raise BackendError("peer_stale", "peer startup identity is stale", retryable=False)
        storage = owner.storage()
        if authorize_peer_writes:
            try:
                peers = owner.peers(actor)
            except (OwnerFileError, SwarmError) as exc:
                raise BackendError("peer_write_unauthorized", "peer write grant is unavailable", retryable=False) from exc
            if not peers or any(
                not any(owner.authorize(current, actor, item["actor_ref"], action) for item in peers)
                for action in ("send", "ack", "reply")
            ):
                raise BackendError("peer_write_unauthorized", "owner did not grant all peer write actions", retryable=False)
    except (OwnerFileError, SwarmError) as exc:
        raise BackendError("peer_invalid", "peer owner input is unavailable", retryable=False) from exc
    package_root = Path(__file__).resolve().parents[1]
    server_path = Path(__file__).resolve().with_name("mcp_server.py")
    python_env = os.environ.get("TASK_SWARM_PYTHON")
    if python_env:
        peer_python = Path(python_env).expanduser().resolve(strict=False)
    else:
        candidate = package_root.parent / "venv-peer" / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
        peer_python = candidate if candidate.is_file() else Path(sys.executable).resolve()
    args = [
        "-u",
        str(server_path),
        "--binding",
        str(binding),
        "--actor",
        actor,
        "--epoch",
        str(epoch),
        "--invocation",
        invocation,
    ]
    return {
        "command": str(peer_python),
        "args": args,
        "binding": str(binding),
        "storage": {key: str(value) for key, value in storage.items()},
        "actor": actor,
        "epoch": epoch,
        "invocation": invocation,
        "tools": list(EXACT_TOOLS),
        "write_authorized": bool(authorize_peer_writes),
    }


def _build_command(
    executable_command: Sequence[str],
    *,
    schema_path: Path,
    last_message_path: Path,
    model: str = MODEL,
    effort: str = EFFORT,
    peer_config: Mapping[str, Any] | None = None,
    authorize_peer_writes: bool = False,
) -> list[str]:
    if model != MODEL or effort != EFFORT:
        raise BackendError("policy_invalid", "this backend accepts only the fixed Luna/max worker", retryable=False)
    command = [
        *executable_command,
        "exec",
        "--json",
        "-s",
        SANDBOX,
        "-m",
        model,
        "-c",
        f'model_reasoning_effort="{effort}"',
        "-c",
        f'approval_policy="{APPROVAL_POLICY}"',
        "-c",
        "agents.enabled=false",
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(last_message_path),
    ]
    if peer_config is not None:
        command.extend(
            [
                "-c",
                "mcp_servers.task_swarm.command=" + json.dumps(str(peer_config["command"])),
                "-c",
                "mcp_servers.task_swarm.args=" + json.dumps(list(peer_config["args"])),
                "-c",
                "mcp_servers.task_swarm.enabled_tools=" + json.dumps(list(EXACT_TOOLS)),
                "-c",
                "mcp_servers.task_swarm.required=true",
                "-c",
                "mcp_servers.task_swarm.startup_timeout_sec=30",
                "-c",
                "mcp_servers.task_swarm.tool_timeout_sec=30",
            ]
        )
        # Read-only tools are preauthorized for this process.  Write tool
        # preauthorization is added only after the caller explicitly opts in;
        # no global approval or sandbox setting is changed.
        for name in (EXACT_TOOLS if authorize_peer_writes else tuple(_READ_TOOLS)):
            command.extend(["-c", f'mcp_servers.task_swarm.tools.{name}.approval_mode="approve"'])
    command.extend(["--skip-git-repo-check", "-"])
    return command


def _result_from_message(text: str) -> dict[str, Any]:
    if not text.strip():
        raise BackendError("result_missing", "the Codex completed turn returned no JSON result", retryable=True)
    try:
        value = json.loads(text.lstrip("\ufeff"))
    except (TypeError, ValueError) as exc:
        raise BackendError("malformed_json", "the completed result is not valid JSON", retryable=True) from exc
    if not isinstance(value, dict):
        raise BackendError("malformed_json", "the completed result must be a JSON object", retryable=True)
    return value


class CodexBackend:
    def __init__(self, executable: str | os.PathLike[str], session_root: str | os.PathLike[str] | None = None) -> None:
        self.executable = executable
        self.session_root = Path(session_root).expanduser().resolve(strict=False) if session_root is not None else None

    def invoke(
        self,
        prompt: str,
        schema: Mapping[str, Any] | str | os.PathLike[str],
        attempt_dir: str | os.PathLike[str],
        *,
        timeout: float = 360,
        model: str = MODEL,
        effort: str = EFFORT,
        peer: Mapping[str, Any] | None = None,
        authorize_peer_writes: bool = False,
        on_process: Callable[[int, float], Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(prompt, str):
            raise BackendError("prompt_invalid", "prompt must be text", retryable=False)
        try:
            timeout_value = float(timeout)
        except (TypeError, ValueError) as exc:
            raise BackendError("timeout_invalid", "timeout must be finite and positive", retryable=False) from exc
        if not math.isfinite(timeout_value) or timeout_value <= 0 or timeout_value > MAX_TIMEOUT:
            raise BackendError("timeout_invalid", "timeout is outside the bounded range", retryable=False)
        if not isinstance(authorize_peer_writes, bool):
            raise BackendError("peer_invalid", "authorize_peer_writes must be boolean", retryable=False)
        schema_object = _load_schema(schema)
        run_dir = _prepare_attempt(attempt_dir)
        paths = _paths(run_dir)
        started_unix = time.time()
        diagnostics: dict[str, Any] = {
            "status": "started",
            "started_at": _utc_iso(started_unix),
            "timeout": timeout_value,
            "model_requested": model,
            "effort_requested": effort,
            "sandbox_requested": SANDBOX,
            "approval_policy_requested": APPROVAL_POLICY,
        }
        stdout = ""
        stderr = ""
        records: list[dict[str, Any]] = []
        process: subprocess.Popen[bytes] | None = None
        pid: int | None = None
        created_at: float | None = None
        exit_code: int | None = None
        peer_cfg: dict[str, Any] | None = None

        try:
            _write_json(paths["schema"], schema_object)
            if peer is not None:
                peer_cfg = _peer_config(peer, authorize_peer_writes=authorize_peer_writes)
                diagnostics["peer_write_authorized"] = bool(authorize_peer_writes)
            executable_command, executable_path = _resolve_executable(self.executable)
            command = _build_command(
                executable_command,
                schema_path=paths["schema"],
                last_message_path=paths["last_message"],
                model=model,
                effort=effort,
                peer_config=peer_cfg,
                authorize_peer_writes=authorize_peer_writes,
            )
            _write_json(paths["command"], {"argv": command, "shell": False, "cwd": str(run_dir)})
            diagnostics["executable"] = str(executable_path)
            process = subprocess.Popen(
                command,
                cwd=str(run_dir),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )
            pid = int(process.pid)
            created_at = _process_created(process)
            if created_at is None:
                try:
                    process.kill()
                    process.wait(timeout=2.0)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                raise BackendError("process_identity", "child process creation time was unavailable", retryable=True)
            _write_json(
                paths["process"],
                {
                    "pid": pid,
                    "created_at": created_at,
                    "cwd": str(run_dir),
                    "started_at": _utc_iso(started_unix),
                    "owner": f"codex-backend:{run_dir.name}",
                },
            )
            diagnostics.update({"pid": pid, "created_at": created_at})
            if on_process is not None:
                try:
                    on_process(pid, created_at)
                except Exception as exc:
                    cleanup = _terminate_owned(process, pid, created_at)
                    try:
                        process.communicate(timeout=2.0)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                    raise BackendError("process_callback", "process ownership callback failed", retryable=True) from exc
            try:
                stdout_bytes, stderr_bytes = process.communicate(input=prompt.encode("utf-8"), timeout=timeout_value)
            except subprocess.TimeoutExpired as exc:
                cleanup = _terminate_owned(process, pid, created_at)
                try:
                    tail_out, tail_err = process.communicate(timeout=2.0)
                except (OSError, subprocess.TimeoutExpired):
                    tail_out, tail_err = b"", b""
                stdout = _decode(exc.output) + _decode(tail_out)
                stderr = _decode(exc.stderr) + _decode(tail_err)
                diagnostics.update({"status": "timeout", "cleanup": cleanup})
                raise BackendError("timeout", "the Codex child exceeded timeout", retryable=True) from exc
            stdout = _decode(stdout_bytes)
            stderr = _decode(stderr_bytes)
            exit_code = process.returncode
            records, malformed, parse_error = _parse_events(stdout)
            diagnostics.update({"exit_code": exit_code, "stdout_event_count": len(records), "stdout_malformed_lines": malformed})
            if parse_error:
                diagnostics["last_stdout_parse_error"] = parse_error
            if exit_code != 0:
                raise BackendError("nonzero_exit", "the Codex child exited unsuccessfully", retryable=True)
            thread_id, stdout_turn = _event_identity(records)
            if not thread_id:
                raise BackendError("completion_identity_missing", "stdout did not identify a thread UUID", retryable=True)
            try:
                runtime = _runtime_receipt(thread_id, stdout_turn, self.session_root, run_dir, started_unix)
            except _RuntimeResolutionError as exc:
                raise BackendError(exc.code, str(exc), retryable=False) from exc
            if runtime is None:
                raise BackendError("runtime_receipt_missing", "matching local rollout metadata was not found", retryable=True)
            if runtime.get("turn_failed"):
                raise BackendError("turn_failed", "the matching local turn reported failure", retryable=True)
            observed_model = runtime.get("model")
            observed_effort = runtime.get("effort")
            observed_sandbox = runtime.get("sandbox")
            if (
                observed_model != model
                or observed_effort != effort
                or observed_sandbox != SANDBOX
                or runtime.get("model_context") not in (None, model)
                or runtime.get("model_settings") not in (None, model)
                or runtime.get("effort_context") not in (None, effort)
                or runtime.get("effort_settings") not in (None, effort)
                or runtime.get("approval_policy") not in (None, APPROVAL_POLICY)
            ):
                raise BackendError("runtime_mismatch", "completed runtime settings do not match the fixed worker policy", retryable=False)
            final_text = _scrub_last_message(paths["last_message"])
            if not final_text:
                final_text = _final_message(records)
            result = _result_from_message(final_text)
            try:
                _validate_schema(result, schema_object)
            except ValueError as exc:
                raise BackendError("schema_mismatch", "completed result does not satisfy output schema", retryable=True) from exc
            completed_output = runtime.get("completed_output")
            if not isinstance(completed_output, str) or not completed_output:
                raise BackendError("runtime_output_missing", "completed runtime output is unavailable", retryable=False)
            if _redact(_result_from_message(completed_output)) != _redact(result):
                raise BackendError("runtime_output_mismatch", "result file differs from the completed model output", retryable=False)
            finished = time.time()
            receipt = {
                "thread_id": thread_id,
                "turn_id": runtime["turn_id"],
                "pid": pid,
                "created_at": created_at,
                "exit_code": exit_code,
                "model_requested": model,
                "model_observed": observed_model,
                "model": observed_model,
                "effort_requested": effort,
                "effort_observed": observed_effort,
                "effort": observed_effort,
                "sandbox_requested": SANDBOX,
                "sandbox_observed": observed_sandbox,
                "sandbox": observed_sandbox,
                "approval_policy": runtime.get("approval_policy"),
                "runtime_cwd": runtime.get("runtime_cwd"),
                "runtime_receipt_path": runtime.get("runtime_receipt_path"),
                "completed": True,
                "completed_output_matches": True,
                "started_at": _utc_iso(started_unix),
                "finished_at": _utc_iso(finished),
                "duration_s": max(0.0, finished - started_unix),
                "peer_tools": list(EXACT_TOOLS) if peer_cfg else [],
                "peer_write_authorized": bool(authorize_peer_writes) if peer_cfg else False,
            }
            redacted_result = _redact(result)
            _write_json(paths["result"], redacted_result)
            # Materialize the redacted stream artifacts before returning so
            # the in-memory receipt and receipt.json carry the same digest
            # evidence.  ``finally`` repeats these writes defensively for
            # failures and late exceptions.
            _write_events(paths["events"], stdout, records)
            _atomic_write(paths["stderr"], _safe_text(stderr).encode("utf-8"))
            _scrub_last_message(paths["last_message"])
            receipt["artifact_digests"] = _artifact_digests(paths)
            _write_json(paths["receipt"], receipt)
            diagnostics.update({"status": "completed", "thread_id": thread_id, "turn_id": runtime["turn_id"], "finished_at": _utc_iso(finished)})
            return {"result": redacted_result, "receipt": _redact(receipt), "paths": _public_paths(paths)}
        except BackendError as exc:
            exc.paths = _public_paths(paths)
            diagnostics["status"] = "failed"
            exc.diagnostics = dict(diagnostics)
            raise
        except _RuntimeResolutionError as exc:
            diagnostics.update({"status": "failed", **exc.details})
            error = BackendError(
                exc.code,
                str(exc),
                retryable=exc.code not in {"runtime_thread_invalid", "runtime_cwd_mismatch", "runtime_cwd_invalid"},
                paths=_public_paths(paths),
                diagnostics=diagnostics,
            )
            raise error from exc
        except (OwnerFileError, SwarmError) as exc:
            error = BackendError("peer_invalid", "peer owner input was refused", retryable=False, paths=_public_paths(paths))
            diagnostics.update({"status": "failed", "error_code": exc.code})
            error.diagnostics = dict(diagnostics)
            raise error from exc
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            error = BackendError("backend_internal", "the local backend failed safely", retryable=True, paths=_public_paths(paths))
            diagnostics.update({"status": "failed", "exception_type": type(exc).__name__})
            error.diagnostics = dict(diagnostics)
            raise error from exc
        finally:
            try:
                if not records and stdout:
                    records, _, _ = _parse_events(stdout)
                _write_events(paths["events"], stdout, records)
                _atomic_write(paths["stderr"], _safe_text(stderr).encode("utf-8"))
                _scrub_last_message(paths["last_message"])
                artifact_digests = _artifact_digests(paths)
                if paths["receipt"].is_file():
                    try:
                        receipt_document = json.loads(paths["receipt"].read_text(encoding="utf-8"))
                    except (OSError, UnicodeError, json.JSONDecodeError):
                        receipt_document = {}
                    if isinstance(receipt_document, dict):
                        receipt_document["artifact_digests"] = artifact_digests
                        _write_json(paths["receipt"], receipt_document)
                diagnostics["artifact_digests"] = artifact_digests
                diagnostics.setdefault("finished_at", _utc_iso())
                _write_json(paths["diagnostics"], diagnostics)
            except OSError:
                pass


def invoke(
    prompt: str,
    schema: Mapping[str, Any] | str | os.PathLike[str],
    attempt_dir: str | os.PathLike[str],
    *,
    executable: str | os.PathLike[str],
    session_root: str | os.PathLike[str] | None = None,
    timeout: float = 360,
    model: str = MODEL,
    effort: str = EFFORT,
    peer: Mapping[str, Any] | None = None,
    authorize_peer_writes: bool = False,
    on_process: Callable[[int, float], Any] | None = None,
) -> dict[str, Any]:
    return CodexBackend(executable, session_root=session_root).invoke(
        prompt,
        schema,
        attempt_dir,
        timeout=timeout,
        model=model,
        effort=effort,
        peer=peer,
        authorize_peer_writes=authorize_peer_writes,
        on_process=on_process,
    )


__all__ = ["BackendError", "CodexBackend", "invoke", "MODEL", "EFFORT", "SANDBOX"]
