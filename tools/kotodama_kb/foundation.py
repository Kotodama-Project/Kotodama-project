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
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse

import yaml
from jsonschema import Draft202012Validator, FormatChecker


RESERVED_INDEX = "index.md"
RESERVED_LOG = "log.md"
FRONTMATTER_DELIMITER = "---"
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
FOOTNOTE_RE = re.compile(r"\[\^([A-Za-z0-9._-]+)\]")
FENCE_RE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)

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

    @property
    def by_id(self) -> dict[str, Concept]:
        return {concept.concept_id: concept for concept in self.concepts}

    @property
    def source_digest(self) -> str:
        digest = hashlib.sha256()
        source_files = sorted(
            path
            for path in self.bundle_root.rglob("*")
            if path.is_file()
            and "_generated" not in path.parts
            and path.suffix.lower() in {".md", ".yaml", ".yml"}
        )
        for path in source_files:
            digest.update(path.relative_to(self.bundle_root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()


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


class KnowledgeBaseError(RuntimeError):
    """Expected user-facing failure."""


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
    except (yaml.YAMLError, DuplicateKeyError) as exc:
        raise KnowledgeBaseError(f"{path}: invalid YAML: {exc}") from exc
    value = _normalize_yaml(value)
    if not isinstance(value, dict):
        raise KnowledgeBaseError(f"{path}: YAML root must be an object")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KnowledgeBaseError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise KnowledgeBaseError(f"{path}: JSON root must be an object")
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
        raw = path.read_text(encoding="utf-8")
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
    raw = path.read_text(encoding="utf-8")
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
    for error in sorted(validator.iter_errors(value), key=lambda item: list(item.absolute_path)):
        location = ".".join(str(part) for part in error.absolute_path)
        suffix = f" at {location}" if location else ""
        issues.append(Issue("error", code, path, f"{error.message}{suffix}"))
    return issues


def _concept_id_for_path(path: Path, bundle_root: Path) -> str:
    return path.relative_to(bundle_root).with_suffix("").as_posix()



__all__ = [name for name in globals() if not name.startswith("__")]
