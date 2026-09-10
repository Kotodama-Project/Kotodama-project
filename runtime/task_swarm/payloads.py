"""Immutable, digest addressed peer payload storage."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import uuid
from typing import Any, Iterable

from .protocol import SwarmError, digest_ref
from .privacy import TOKEN_PATTERN, KEY_PATTERN


MAX_PAYLOAD_BYTES = 16 * 1024
MAX_EVIDENCE_REFS = 16
MAX_EVIDENCE_REF_BYTES = 2048
PAYLOAD_PREFIX = "ref/peer-payload/"
_REF_RE = re.compile(r"^ref/peer-payload/([a-f0-9]{64})$")


class PayloadError(SwarmError):
    """Typed local refusal that never includes rejected secret text."""


_SECRET_PATTERNS = (
    TOKEN_PATTERN,
    KEY_PATTERN,
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.IGNORECASE),
    re.compile(
        r"\b(?:api[_ -]?key|access[_ -]?token|auth[_ -]?token|password|passwd|secret|credential)\b\s*[:=]",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9._-]{8,}\b"),
)


def _reject(code: str, detail: str) -> None:
    raise PayloadError(code, detail)


def _clean_text(value: Any, name: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8", errors="ignore")) > maximum:
        _reject("PAYLOAD_REJECTED", f"invalid {name}")
    if "\x00" in value or any(ord(char) < 32 and char not in "\r\n\t" for char in value):
        _reject("PAYLOAD_REJECTED", f"invalid {name}")
    return value


def _credential_free(value: str) -> None:
    for pattern in _SECRET_PATTERNS:
        if pattern.search(value):
            _reject("PAYLOAD_REJECTED", "credential-shaped content is not allowed")


def _validate_payload_values(text: Any, evidence_refs: Any) -> tuple[str, list[str]]:
    message = _clean_text(text, "text", maximum=MAX_PAYLOAD_BYTES)
    if not message.strip():
        _reject("PAYLOAD_REJECTED", "text must be non-empty")
    _credential_free(message)
    if evidence_refs is None:
        evidence_refs = []
    if not isinstance(evidence_refs, list) or len(evidence_refs) > MAX_EVIDENCE_REFS:
        _reject("PAYLOAD_REJECTED", "evidence_refs must be a bounded list")
    refs: list[str] = []
    for item in evidence_refs:
        reference = _clean_text(item, "evidence reference", maximum=MAX_EVIDENCE_REF_BYTES)
        if len(reference.encode("utf-8")) > MAX_EVIDENCE_REF_BYTES:
            _reject("PAYLOAD_REJECTED", "evidence reference is too large")
        _credential_free(reference)
        refs.append(reference)
    return message, refs


def _canonical_bytes(text: Any, evidence_refs: Any) -> tuple[bytes, str]:
    message, refs = _validate_payload_values(text, evidence_refs)
    try:
        raw = json.dumps(
            {"text": message, "evidence_refs": refs},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise PayloadError("PAYLOAD_REJECTED", "payload is not finite UTF-8 JSON") from exc
    if len(raw) > MAX_PAYLOAD_BYTES:
        _reject("PAYLOAD_REJECTED", "payload JSON is too large")
    return raw, hashlib.sha256(raw).hexdigest()


class PayloadStore:
    """Store immutable UTF-8 JSON beneath one exact operator-selected root."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        raw = Path(root)
        try:
            self.root = raw.expanduser().resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise PayloadError("PAYLOAD_STORAGE_ERROR", "payload root cannot resolve") from exc
        if self.root.exists() and self.root.is_symlink():
            _reject("PAYLOAD_STORAGE_ERROR", "payload root cannot be a symlink")
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PayloadError("PAYLOAD_STORAGE_ERROR", "payload root cannot be created") from exc
        self.payload_root = self.root / "ref" / "peer-payload"
        try:
            self.payload_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PayloadError("PAYLOAD_STORAGE_ERROR", "payload directory cannot be created") from exc
        self._check_path(self.payload_root, allow_root=True)

    def _check_path(self, path: Path, *, allow_root: bool = False) -> Path:
        try:
            resolved = path.resolve(strict=False)
            resolved.relative_to(self.root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PayloadError("PAYLOAD_STORAGE_ERROR", "payload path escapes its root") from exc
        if not allow_root and resolved == self.root:
            _reject("PAYLOAD_STORAGE_ERROR", "payload path must be below its root")
        current = resolved
        while True:
            try:
                if current.exists() and current.is_symlink():
                    _reject("PAYLOAD_STORAGE_ERROR", "payload path contains a symlink")
            except OSError as exc:
                raise PayloadError("PAYLOAD_STORAGE_ERROR", "payload path cannot be inspected") from exc
            if current == self.root or current.parent == current:
                break
            current = current.parent
        return resolved

    @staticmethod
    def canonical_bytes(text: Any, evidence_refs: Any = None) -> tuple[bytes, str]:
        return _canonical_bytes(text, evidence_refs)

    @staticmethod
    def _ref(digest: str) -> str:
        return f"{PAYLOAD_PREFIX}{digest}"

    def _path_for_digest(self, digest: Any) -> Path:
        try:
            value = digest_ref(digest, "payload digest")
        except SwarmError as exc:
            raise PayloadError(exc.code, exc.detail) from exc
        return self._check_path(self.payload_root / f"{value}.json")

    def put(self, text: Any, evidence_refs: Any = None) -> tuple[str, str]:
        raw, digest = _canonical_bytes(text, evidence_refs)
        path = self._path_for_digest(digest)
        try:
            with path.open("xb") as handle:
                handle.write(raw)
        except FileExistsError:
            try:
                if path.is_symlink() or path.read_bytes() != raw:
                    _reject("PAYLOAD_IMMUTABLE_CONFLICT", "payload digest path is not immutable")
            except OSError as exc:
                raise PayloadError("PAYLOAD_STORAGE_ERROR", "existing payload cannot be read") from exc
        except OSError as exc:
            raise PayloadError("PAYLOAD_STORAGE_ERROR", "payload cannot be stored") from exc
        return self._ref(digest), digest

    def get(self, payload_ref: Any, payload_digest: Any) -> dict[str, Any]:
        try:
            digest = digest_ref(payload_digest, "payload digest")
        except SwarmError as exc:
            raise PayloadError(exc.code, exc.detail) from exc
        if not isinstance(payload_ref, str) or _REF_RE.fullmatch(payload_ref) is None:
            _reject("PAYLOAD_DIGEST_MISMATCH", "payload reference is invalid")
        match = _REF_RE.fullmatch(payload_ref)
        assert match is not None
        if match.group(1) != digest:
            _reject("PAYLOAD_DIGEST_MISMATCH", "payload reference and digest differ")
        path = self._path_for_digest(digest)
        try:
            if path.is_symlink():
                _reject("PAYLOAD_STORAGE_ERROR", "payload path contains a symlink")
            raw = path.read_bytes()
        except FileNotFoundError as exc:
            raise PayloadError("PAYLOAD_UNAVAILABLE", "payload is unavailable") from exc
        except OSError as exc:
            raise PayloadError("PAYLOAD_STORAGE_ERROR", "payload cannot be read") from exc
        if hashlib.sha256(raw).hexdigest() != digest:
            _reject("PAYLOAD_DIGEST_MISMATCH", "payload bytes do not match digest")
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PayloadError("PAYLOAD_DIGEST_MISMATCH", "payload JSON is invalid") from exc
        if not isinstance(document, dict) or set(document) != {"text", "evidence_refs"}:
            _reject("PAYLOAD_DIGEST_MISMATCH", "payload JSON shape is invalid")
        canonical, _ = _canonical_bytes(document.get("text"), document.get("evidence_refs"))
        if canonical != raw:
            _reject("PAYLOAD_DIGEST_MISMATCH", "payload JSON is not canonical")
        return {"text": document["text"], "evidence_refs": list(document["evidence_refs"])}

    def load(self, payload_ref: Any, payload_digest: Any) -> dict[str, Any]:
        """Named alias useful at integration seams; it performs the same check."""

        return self.get(payload_ref, payload_digest)


__all__ = [
    "MAX_EVIDENCE_REFS",
    "MAX_PAYLOAD_BYTES",
    "PAYLOAD_PREFIX",
    "PayloadError",
    "PayloadStore",
]
