#!/usr/bin/env python3
"""Validate, project, query, and assemble context from the Kotodama OKF bundle.

The bundle is deliberately a rebuildable, public-safe read model. This tool does
not grant access, promote Current Truth, execute retrieved instructions, or
claim that a runtime agent is active.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import math
import os
import re
import stat
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from referencing.exceptions import Unresolvable


RESERVED_INDEX = "index.md"
RESERVED_LOG = "log.md"
FRONTMATTER_DELIMITER = "---"
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
FOOTNOTE_RE = re.compile(r"\[\^([A-Za-z0-9._-]+)\]")
FENCE_RE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
MAX_FILE_BYTES = 1024 * 1024
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_INPUT_FILES = 256

class DuplicateKeyError(ValueError):
    """Raised when YAML contains duplicate mapping keys."""


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe loader that refuses duplicate YAML keys."""


def _construct_mapping(
    loader: UniqueKeyLoader, node: yaml.nodes.MappingNode, deep: bool = False
) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise DuplicateKeyError("frontmatter keys must be strings")
        if key in mapping:
            raise DuplicateKeyError(f"duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


@dataclasses.dataclass(frozen=True, order=True)
class Issue:
    level: str
    code: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class MarkdownDocument:
    path: Path
    relative_path: str
    frontmatter: dict[str, Any]
    body: str
    raw: str


@dataclasses.dataclass(frozen=True)
class Concept:
    document: MarkdownDocument
    concept_id: str
    links: tuple[str, ...]
    resolved_concept_links: tuple[str, ...]
    source_resources: tuple[str, ...]
    content_sha256: str
    trust_tier: str
    stale_after: str | None
    is_stale: bool

    @property
    def metadata(self) -> dict[str, Any]:
        return self.document.frontmatter

    @property
    def extension(self) -> dict[str, Any]:
        value = self.metadata.get("kotodama")
        return value if isinstance(value, dict) else {}


@dataclasses.dataclass(frozen=True)
class Bundle:
    root: Path
    bundle_root: Path
    profile: dict[str, Any]
    concepts: tuple[Concept, ...]
    issues: tuple[Issue, ...]
    index_links: tuple[str, ...]
    as_of: dt.datetime
    input_bindings: tuple[tuple[str, str], ...] = ()

    @property
    def by_id(self) -> dict[str, Concept]:
        return {concept.concept_id: concept for concept in self.concepts}

    @property
    def source_digest(self) -> str:
        # Bind the admitted bytes, including cited local sources and schemas.
        # Reading mutable files here would attach a new digest to old concepts.
        raw = json.dumps(self.input_bindings, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclasses.dataclass(frozen=True)
class SearchResult:
    concept: Concept
    score: float
    reasons: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class ContextSelection:
    selected: tuple[Concept, ...]
    omitted_ids: tuple[str, ...]
    unresolved_ids: tuple[str, ...]
    filters: Mapping[str, tuple[str, ...]]
    source_digest: str
    source_root: Path
    as_of: dt.datetime


class KnowledgeBaseError(RuntimeError):
    """Expected user-facing failure."""


def _read_bytes(path: Path) -> bytes:
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_FILE_BYTES:
            raise KnowledgeBaseError("INPUT_NOT_BOUNDED_REGULAR_FILE")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(path, flags), "rb") as stream:
            opened = os.fstat(stream.fileno())
            raw = stream.read(MAX_FILE_BYTES + 1)
            finished = os.fstat(stream.fileno())
        after = path.lstat()
        # Windows path-stat ctime can denote creation time while descriptor
        # fstat denotes change time. Bind portable cross-API identity/state and
        # compare ctime only between snapshots of the same open descriptor.
        signature = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_nlink, value.st_size, value.st_mtime_ns)
        if len(raw) > MAX_FILE_BYTES or len(raw) != opened.st_size or opened.st_ctime_ns != finished.st_ctime_ns or not (signature(before) == signature(opened) == signature(finished) == signature(after)):
            raise KnowledgeBaseError("INPUT_CHANGED_DURING_READ")
        return raw
    except OSError as exc:
        raise KnowledgeBaseError("INPUT_UNREADABLE") from exc


def _read_text(path: Path) -> str:
    try:
        return _read_bytes(path).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise KnowledgeBaseError("INPUT_NOT_UTF8") from exc


def _knowledge_inputs(bundle_root: Path) -> tuple[Path, ...]:
    paths = tuple(sorted(path for path in bundle_root.rglob("*")
                         if "_generated" not in path.parts and path.suffix.lower() in {".md", ".yaml", ".yml"}))
    if len(paths) > MAX_INPUT_FILES:
        raise KnowledgeBaseError("INPUT_FILE_BUDGET")
    return paths


def _capture_inputs(root: Path, paths: Iterable[Path]) -> tuple[tuple[str, str], ...]:
    # Path ordering case-folds on Windows. Hash the same path order on every OS.
    selected = sorted(set(paths), key=lambda path: path.as_posix())
    if len(selected) > MAX_INPUT_FILES:
        raise KnowledgeBaseError("INPUT_FILE_BUDGET")
    total = 0
    bindings = []
    for path in selected:
        try:
            relative = path.relative_to(root).as_posix()
            path.resolve().relative_to(root)
        except (ValueError, OSError) as exc:
            raise KnowledgeBaseError("INPUT_OUTSIDE_REPOSITORY") from exc
        raw = _read_bytes(path)
        total += len(raw)
        if total > MAX_INPUT_BYTES:
            raise KnowledgeBaseError("INPUT_BYTE_BUDGET")
        bindings.append((relative, hashlib.sha256(raw).hexdigest()))
    return tuple(bindings)


def _assert_current(bundle: Bundle) -> None:
    expected = dict(bundle.input_bindings)
    current_paths = set(_knowledge_inputs(bundle.bundle_root))
    current_paths.update(bundle.root / relative for relative in expected)
    if _capture_inputs(bundle.root, current_paths) != bundle.input_bindings:
        raise KnowledgeBaseError("SOURCE_CHANGED_RELOAD_REQUIRED")


def _require_valid_bundle(bundle: Bundle) -> None:
    if any(issue.level == "error" for issue in bundle.issues):
        raise KnowledgeBaseError("INVALID_BUNDLE")
    _assert_current(bundle)


def _bounded_tree(value: Any) -> None:
    active: set[int] = set()
    count = 0
    def visit(node: Any, depth: int) -> None:
        nonlocal count
        count += 1
        if depth > 32 or count > 20000:
            raise KnowledgeBaseError("INPUT_STRUCTURE_BUDGET")
        if isinstance(node, float) and not math.isfinite(node):
            raise KnowledgeBaseError("INPUT_NONFINITE")
        if isinstance(node, (dict, list)):
            if id(node) in active:
                raise KnowledgeBaseError("INPUT_CYCLE")
            active.add(id(node))
            for child in (node.values() if isinstance(node, dict) else node):
                visit(child, depth + 1)
            active.remove(id(node))
    visit(value, 0)


OKF_RESERVED_CONFORMANCE_CODES = frozenset(
    {
        "NESTED_INDEX_FRONTMATTER",
        "LOG_FRONTMATTER",
        "LOG_DATE",
    }
)


def _normalize_yaml(value: Any) -> Any:
    """Convert PyYAML timestamp objects into JSON-schema-compatible strings."""
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            return value.isoformat()
        text = value.isoformat()
        return text.replace("+00:00", "Z")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, list):
        return [_normalize_yaml(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize_yaml(item) for key, item in value.items()}
    return value


def _load_yaml(text: str, *, path: Path) -> dict[str, Any]:
    try:
        value = yaml.load(text, Loader=UniqueKeyLoader)
    except (yaml.YAMLError, ValueError, RecursionError) as exc:
        raise KnowledgeBaseError("INVALID_YAML") from exc
    _bounded_tree(value)
    value = _normalize_yaml(value)
    if not isinstance(value, dict):
        raise KnowledgeBaseError("YAML_ROOT_NOT_OBJECT")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    """Admit a bounded local schema before constructing its validator."""
    try:
        def pairs(items):
            result = {}
            for key, child in items:
                if key in result:
                    raise KnowledgeBaseError("DUPLICATE_JSON_KEY")
                result[key] = child
            return result
        value = json.loads(_read_text(path), object_pairs_hook=pairs)
        _bounded_tree(value)
    except (ValueError, RecursionError) as exc:
        raise KnowledgeBaseError("INVALID_JSON") from exc
    if not isinstance(value, dict):
        raise KnowledgeBaseError("JSON_ROOT_NOT_OBJECT")
    def local_refs(node):
        if isinstance(node, dict):
            for key, child in node.items():
                if key in {"$ref", "$dynamicRef", "$recursiveRef"} and (not isinstance(child, str) or not child.startswith("#")):
                    raise KnowledgeBaseError("EXTERNAL_SCHEMA_REFERENCE")
                local_refs(child)
        elif isinstance(node, list):
            for child in node:
                local_refs(child)
    local_refs(value)
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise KnowledgeBaseError("INVALID_SCHEMA") from exc
    return value


def _parse_datetime(value: str, *, field: str, path: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise KnowledgeBaseError(f"{path}: {field} is not an ISO 8601 datetime") from exc
    if parsed.tzinfo is None:
        raise KnowledgeBaseError(f"{path}: {field} must contain an explicit UTC offset")
    return parsed.astimezone(dt.timezone.utc)


def _parse_as_of(value: str | None) -> dt.datetime:
    if value is None:
        return dt.datetime.now(dt.timezone.utc)
    return _parse_datetime(value, field="--as-of", path="command line")


def _parse_frontmatter(path: Path, bundle_root: Path) -> MarkdownDocument:
    try:
        raw = _read_text(path)
    except (OSError, UnicodeDecodeError) as exc:
        raise KnowledgeBaseError(f"{path}: cannot read UTF-8 Markdown: {exc}") from exc

    relative = path.relative_to(bundle_root).as_posix()
    lines = raw.splitlines(keepends=True)
    if not lines or lines[0].strip() != FRONTMATTER_DELIMITER:
        raise KnowledgeBaseError(f"{relative}: concept must start with YAML frontmatter")

    closing = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == FRONTMATTER_DELIMITER:
            closing = index
            break
    if closing is None:
        raise KnowledgeBaseError(f"{relative}: frontmatter has no closing delimiter")

    yaml_text = "".join(lines[1:closing])
    body = "".join(lines[closing + 1 :])
    frontmatter = _load_yaml(yaml_text, path=path)
    return MarkdownDocument(
        path=path,
        relative_path=relative,
        frontmatter=frontmatter,
        body=body,
        raw=raw,
    )


def _frontmatter_from_root_index(path: Path) -> dict[str, Any]:
    raw = _read_text(path)
    if not raw.startswith("---"):
        return {}
    lines = raw.splitlines(keepends=True)
    closing = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if closing is None:
        raise KnowledgeBaseError("knowledge/index.md: frontmatter has no closing delimiter")
    return _load_yaml("".join(lines[1:closing]), path=path)


def _normalized_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _without_code_fences(body: str) -> str:
    return FENCE_RE.sub("", body)


def _markdown_targets(body: str) -> tuple[str, ...]:
    cleaned = _without_code_fences(body)
    targets: list[str] = []
    for match in MARKDOWN_LINK_RE.finditer(cleaned):
        target = match.group(1).strip()
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1].strip()
        if " " in target and not target.startswith(("http://", "https://")):
            # CommonMark destinations with titles are out of scope; retain only path.
            target = target.split(" ", 1)[0]
        targets.append(target)
    return tuple(targets)


def _is_external(resource: str) -> bool:
    parsed = urlparse(resource)
    return parsed.scheme in {"http", "https", "urn", "mailto"}


def _strip_fragment_and_query(target: str) -> str:
    target = target.split("#", 1)[0]
    target = target.split("?", 1)[0]
    return target


def _resolve_markdown_target(
    *,
    source_path: Path,
    target: str,
    repository_root: Path,
    bundle_root: Path,
) -> Path | None:
    clean = _strip_fragment_and_query(target)
    if not clean or _is_external(clean):
        return None
    if clean.startswith("/"):
        candidate = bundle_root / clean.lstrip("/")
    else:
        candidate = source_path.parent / clean
    try:
        if any(parent.is_symlink() for parent in (candidate, *candidate.parents) if parent.is_relative_to(repository_root)):
            return Path("/__OUTSIDE_REPOSITORY__")
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(repository_root)
    except (OSError, ValueError):
        return Path("/__OUTSIDE_REPOSITORY__")
    if resolved.is_dir():
        resolved = resolved / RESERVED_INDEX
    return resolved


def _resolve_source_resource(
    *, source_path: Path, resource: str, repository_root: Path, bundle_root: Path
) -> Path | None:
    if _is_external(resource):
        return None
    # OKF permits scope descriptors. Treat strings with whitespace and no path
    # markers as non-followable descriptors rather than repository paths.
    if any(character.isspace() for character in resource) and not resource.startswith(("./", "../", "/")):
        return None
    return _resolve_markdown_target(
        source_path=source_path,
        target=resource,
        repository_root=repository_root,
        bundle_root=bundle_root,
    )


def _trust_tier(metadata: Mapping[str, Any]) -> str:
    verified = metadata.get("verified")
    if not verified:
        return "unverified"
    entries = verified if isinstance(verified, list) else [verified]
    actors = [entry.get("by", "") for entry in entries if isinstance(entry, dict)]
    if any(str(actor).startswith("human:") for actor in actors):
        return "human-reviewed"
    return "machine-confirmed"


def _verification_entries(metadata: Mapping[str, Any]) -> list[dict[str, Any]]:
    verified = metadata.get("verified")
    if not verified:
        return []
    if isinstance(verified, list):
        return [item for item in verified if isinstance(item, dict)]
    if isinstance(verified, dict):
        return [verified]
    return []


def _schema_issues(
    *, validator: Draft202012Validator, value: Mapping[str, Any], path: str, code: str
) -> list[Issue]:
    issues: list[Issue] = []
    try:
        errors = sorted(validator.iter_errors(value), key=lambda item: tuple(str(part) for part in item.absolute_path))
    except RecursionError as exc:
        # Local references may recurse without advancing through the instance.
        # Keep terminating recursive schemas valid and refuse exhausted ones.
        raise KnowledgeBaseError("SCHEMA_RECURSION_LIMIT") from exc
    except Unresolvable as exc:
        raise KnowledgeBaseError("SCHEMA_REFERENCE_UNRESOLVABLE") from exc
    for error in errors:
        location = ".".join(str(part) for part in error.absolute_path)
        suffix = f" at {location}" if location else ""
        issues.append(Issue("error", code, path, f"invalid {error.validator}{suffix}"))
    return issues


def _concept_id_for_path(path: Path, bundle_root: Path) -> str:
    return path.relative_to(bundle_root).with_suffix("").as_posix()



__all__ = [name for name in globals() if not name.startswith("__")]
