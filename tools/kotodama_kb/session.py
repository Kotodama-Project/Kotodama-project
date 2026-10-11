"""Finite, explicit stdio reads reusing one source-checked parsed bundle."""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import datetime as dt
import io
import json
from pathlib import Path
import re
import sys
from typing import BinaryIO

from . import cli
from .foundation import Bundle, Issue, KnowledgeBaseError, _parse_datetime

MAX_REQUEST_BYTES = 16 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
MAX_REQUESTS = 256


class _BoundedOutput(io.StringIO):
    def __init__(self, limit: int):
        super().__init__()
        self.limit, self.used = limit, 0

    def write(self, value: str) -> int:
        self.used += len(value.encode("utf-8"))
        if self.used > self.limit:
            raise KnowledgeBaseError("SESSION_RESPONSE_BYTE_BUDGET")
        return super().write(value)


def _error(request_id: str | None, code: str) -> dict:
    # Existing parser errors may contain paths or caller text. Return only a
    # bounded diagnostic code, never a traceback or captured argparse output.
    match = re.match(r"([A-Z][A-Z0-9_]{1,96})(?::|$)", code)
    code = match.group(1) if match else "SESSION_REQUEST_REFUSED"
    return {"id": request_id, "ok": False, "exit_code": 2, "error": code}


def _decode(raw: bytes) -> dict:
    if len(raw) > MAX_REQUEST_BYTES:
        raise KnowledgeBaseError("SESSION_REQUEST_BYTE_BUDGET")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise KnowledgeBaseError("SESSION_REQUEST_INVALID")
            result[key] = value
        return result
    def nonfinite(_):
        raise KnowledgeBaseError("SESSION_REQUEST_INVALID")
    try:
        request = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=nonfinite)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise KnowledgeBaseError("SESSION_REQUEST_INVALID") from exc
    if (not isinstance(request, dict) or set(request) != {"id", "args"}
            or not isinstance(request["id"], str) or not 1 <= len(request["id"]) <= 64
            or not isinstance(request["args"], list) or not 1 <= len(request["args"]) <= 64
            or any(not isinstance(value, str) or len(value) > 4096 for value in request["args"])):
        raise KnowledgeBaseError("SESSION_REQUEST_INVALID")
    try:
        for value in [request["id"], *request["args"]]:
            value.encode("utf-8")
    except UnicodeError as exc:
        raise KnowledgeBaseError("SESSION_REQUEST_INVALID") from exc
    return request


def _at_time(bundle: Bundle, as_of: dt.datetime) -> Bundle:
    """Re-evaluate expiry from admitted metadata, without retaining old views."""
    concepts, issues = [], [issue for issue in bundle.issues if issue.code != "STALE_CONCEPT"]
    critical = set(bundle.profile["quality"].get("critical_tags", []))
    for concept in bundle.concepts:
        path = concept.document.path.relative_to(bundle.root).as_posix()
        stale = (concept.stale_after is not None and as_of >= _parse_datetime(
            concept.stale_after, field="stale_after", path=path))
        concepts.append(dataclasses.replace(concept, is_stale=stale))
        if stale:
            marker = "critical " if set(concept.metadata.get("tags", [])) & critical else ""
            issues.append(Issue("warning", "STALE_CONCEPT", path,
                                f"{marker}concept is stale at {as_of.isoformat()}"))
    return dataclasses.replace(bundle, concepts=tuple(concepts), issues=tuple(issues), as_of=as_of)


class KnowledgeSession:
    """One sequential caller, one parsed generation, no background work."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self._bundle: Bundle | None = None
        self._parser = cli._parser()
        # Request options may not abbreviate --root and escape the pinned root.
        for action in self._parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for parser in action.choices.values():
                    parser.allow_abbrev = False

    def _snapshot(self, as_of: dt.datetime) -> Bundle:
        if self._bundle is not None:
            try:
                cli._assert_current(self._bundle)
            except KnowledgeBaseError:
                self._bundle = None
        if self._bundle is None:
            bundle = cli.load_bundle(self.root, as_of=as_of)
            cli._require_valid_bundle(bundle)
            self._bundle = bundle
        self._bundle = _at_time(self._bundle, as_of)
        return self._bundle

    def handle(self, raw: bytes) -> bytes:
        request_id = None
        try:
            request = _decode(raw)
            request_id, arguments = request["id"], request["args"]
            if arguments[0] not in {"query", "show"}:
                raise KnowledgeBaseError("SESSION_COMMAND_NOT_READ_ONLY")
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    args = self._parser.parse_args([arguments[0], "--root", str(self.root),
                                                   "--json", *arguments[1:]])
            except SystemExit as exc:
                raise KnowledgeBaseError("SESSION_ARGUMENTS_INVALID") from exc
            try:
                same_root = args.root.resolve() == self.root
            except (OSError, RuntimeError, ValueError) as exc:
                raise KnowledgeBaseError("SESSION_ROOT_IS_PINNED") from exc
            if not same_root:
                raise KnowledgeBaseError("SESSION_ROOT_IS_PINNED")
            as_of = cli._parse_as_of(args.as_of)
            bundle = self._snapshot(as_of)
            output = _BoundedOutput(MAX_RESPONSE_BYTES)
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                code = cli._execute(args, bundle, as_of)
            if code:
                raise KnowledgeBaseError("SESSION_REQUEST_REFUSED")
            response = {"id": request_id, "ok": True, "exit_code": 0,
                        "result": json.loads(output.getvalue())}
            frame = (json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            if len(frame) > MAX_RESPONSE_BYTES:
                raise KnowledgeBaseError("SESSION_RESPONSE_BYTE_BUDGET")
            # Complete serialization first, just as the single-shot CLI does.
            cli._assert_current(bundle)
            return frame
        except (KnowledgeBaseError, UnicodeError) as exc:
            self._bundle = None
            code = "SESSION_RESPONSE_ENCODING" if isinstance(exc, UnicodeError) else str(exc)
            return (json.dumps(_error(request_id, code), ensure_ascii=False,
                               separators=(",", ":")) + "\n").encode("utf-8")


def run(root: Path, source: BinaryIO, sink: BinaryIO, *, max_requests: int = MAX_REQUESTS) -> int:
    if type(max_requests) is not int or not 1 <= max_requests <= MAX_REQUESTS:
        raise KnowledgeBaseError("SESSION_REQUEST_COUNT_BUDGET")
    session = KnowledgeSession(root)
    for _ in range(max_requests):
        # Admit/parse one line at a time. Finite OS/Python raw byte buffers may
        # contain later lines, but there is no queue of admitted requests.
        raw = source.readline(MAX_REQUEST_BYTES + 1)
        if not raw:
            return 0
        frame = session.handle(raw)
        sink.write(frame)
        sink.flush()
        if len(raw) > MAX_REQUEST_BYTES:
            return 2  # No unbounded drain to find the end of an oversized line.
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="one explicit source root for this process")
    parser.add_argument("--max-requests", type=int, default=MAX_REQUESTS, help="1..256; EOF also stops the loop")
    args = parser.parse_args(argv)
    try:
        return run(args.root, sys.stdin.buffer, sys.stdout.buffer, max_requests=args.max_requests)
    except KnowledgeBaseError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 1
