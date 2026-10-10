"""Optional, disposable SQLite candidate index; Markdown owns all decisions."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any

from .foundation import Bundle, KnowledgeBaseError, _assert_current, _normalized_text, _require_valid_bundle
from .retrieve import _search_haystacks, query_bundle

SCHEMA_VERSION = 1
EXTRACTION = "lexical-nfkc-casefold-checksum-v1"
FIELDS = ("id_text", "title", "description", "tags", "refs", "body")
BACKENDS = {"fts5-trigram", "substring"}


def _scope(bundle: Bundle) -> str:
    # Bind a cache to its explicit root without returning a private absolute path.
    value = [str(bundle.root), bundle.profile["bundle_id"]]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


def _path(path: Path) -> Path:
    path = Path(path).resolve()
    if path.suffix not in {".sqlite", ".db"}:
        raise KnowledgeBaseError("INDEX_PATH_REQUIRES_SQLITE_OR_DB_SUFFIX")
    return path


def _connect(path: Path, *, write: bool = False) -> sqlite3.Connection:
    uri = path.as_uri() + ("?mode=rw" if write else "?mode=ro")
    return sqlite3.connect(uri, uri=True, timeout=1.0)


def _metadata(connection: sqlite3.Connection, bundle: Bundle, *, current: bool) -> dict[str, Any]:
    row = connection.execute("SELECT value FROM metadata WHERE key = 'contract'").fetchone()
    if row is None:
        raise KnowledgeBaseError("INDEX_CONTRACT_INVALID")
    try:
        value = json.loads(row[0])
        compatible = (set(value) == {"schema", "extraction", "backend", "scope", "source_digest"}
                      and value["schema"] == SCHEMA_VERSION and value["extraction"] == EXTRACTION
                      and value["backend"] in BACKENDS and value["scope"] == _scope(bundle))
    except (TypeError, ValueError, KeyError):
        compatible = False
    if not compatible:
        raise KnowledgeBaseError("INDEX_CONTRACT_MISMATCH_REBUILD_REQUIRED")
    if current and value["source_digest"] != bundle.source_digest:
        raise KnowledgeBaseError("INDEX_STALE_REBUILD_REQUIRED")
    return value


def _create_schema(connection: sqlite3.Connection) -> str:
    connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    fields = ", ".join(f"{name} TEXT NOT NULL" for name in FIELDS)
    connection.execute("CREATE TABLE documents (concept_id TEXT UNIQUE NOT NULL, "
                       f"content_sha256 TEXT NOT NULL, search_sha256 TEXT NOT NULL, {fields})")
    try:
        connection.execute("CREATE VIRTUAL TABLE search USING fts5("
                           f"{', '.join(FIELDS)}, content='documents', content_rowid='rowid', "
                           "tokenize='trigram case_sensitive 1')")
    except sqlite3.OperationalError as exc:
        # Older/system SQLite builds may lack FTS5 or its trigram tokenizer.
        if not any(marker in str(exc).lower() for marker in ("no such module", "no such tokenizer", "error in tokenizer constructor")):
            raise
        return "substring"
    new_fields = ", ".join(f"new.{name}" for name in FIELDS)
    old_fields = ", ".join(f"old.{name}" for name in FIELDS)
    names = ", ".join(FIELDS)
    triggers = (
        f"CREATE TRIGGER documents_ai AFTER INSERT ON documents BEGIN "
        f"INSERT INTO search(rowid, {names}) VALUES (new.rowid, {new_fields}); END;",
        f"CREATE TRIGGER documents_ad AFTER DELETE ON documents BEGIN "
        f"INSERT INTO search(search, rowid, {names}) VALUES ('delete', old.rowid, {old_fields}); END;",
        f"CREATE TRIGGER documents_au AFTER UPDATE ON documents BEGIN "
        f"INSERT INTO search(search, rowid, {names}) VALUES ('delete', old.rowid, {old_fields}); "
        f"INSERT INTO search(rowid, {names}) VALUES (new.rowid, {new_fields}); END;"
    )
    for trigger in triggers:
        connection.execute(trigger)
    return "fts5-trigram"


def _search_digest(values: tuple[str, ...]) -> str:
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _check_rows(connection: sqlite3.Connection, bundle: Bundle, *, full: bool = False) -> None:
    expected = bundle.by_id
    seen = set()
    # Inspect every row, including rows a damaged candidate index might omit.
    # Stream normalized text rather than materializing a second complete corpus.
    columns = "concept_id, content_sha256, search_sha256, " + ", ".join(FIELDS)
    for concept_id, source_digest, search_digest, *values in connection.execute(f"SELECT {columns} FROM documents"):
        if not all(isinstance(value, str) for value in (concept_id, source_digest, search_digest, *values)):
            raise KnowledgeBaseError("INDEX_CONTENT_MISMATCH_REBUILD_REQUIRED")
        concept = expected.get(concept_id)
        if (concept is None or concept_id in seen or source_digest != concept.content_sha256
                or search_digest != _search_digest(tuple(values))
                or (full and tuple(values) != tuple(_search_haystacks(concept).values()))):
            raise KnowledgeBaseError("INDEX_CONTENT_MISMATCH_REBUILD_REQUIRED")
        seen.add(concept_id)
    if seen != expected.keys():
        raise KnowledgeBaseError("INDEX_CONTENT_MISMATCH_REBUILD_REQUIRED")


def _check_postings(connection: sqlite3.Connection, metadata: dict[str, Any]) -> None:
    if metadata["backend"] == "fts5-trigram":
        # FTS's external-content comparison requires a write-capable connection,
        # even though this command only checks. Callers commit no audit writes.
        try:
            connection.execute("INSERT INTO search(search, rank) VALUES ('integrity-check', 1)")
        except sqlite3.Error as exc:
            raise KnowledgeBaseError("INDEX_POSTINGS_INVALID_OR_UNAVAILABLE") from exc


def _report(metadata: dict[str, Any], *, changed: int = 0, removed: int = 0,
            postings_checked: bool = False) -> dict[str, Any]:
    return {"schema": metadata["schema"], "backend": metadata["backend"],
            "source_digest": metadata["source_digest"], "changed": changed,
            "removed": removed, "authority": "projection_only",
            "postings_trust": "same_operator_cache",
            "postings_audit": ("not_applicable" if metadata["backend"] == "substring"
                               else "performed" if postings_checked else "not_performed")}


def build_index(bundle: Bundle, path: Path) -> dict[str, Any]:
    """Commit changed rows and their source generation in one SQLite transaction."""
    _require_valid_bundle(bundle)
    path = _path(path)
    try:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        except FileExistsError:
            pass
        with contextlib.closing(_connect(path, write=True)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            exists = connection.execute("SELECT 1 FROM sqlite_master WHERE name = 'metadata'").fetchone()
            if exists:
                metadata = _metadata(connection, bundle, current=False)
            else:
                tables = connection.execute("SELECT name FROM sqlite_master").fetchall()
                if tables:
                    raise KnowledgeBaseError("INDEX_CONTRACT_INVALID")
                backend = _create_schema(connection)
                metadata = {"schema": SCHEMA_VERSION, "extraction": EXTRACTION, "backend": backend,
                            "scope": _scope(bundle), "source_digest": ""}
            before = dict(connection.execute("SELECT concept_id, content_sha256 FROM documents"))
            desired = {concept.concept_id: concept for concept in bundle.concepts}
            removed = sorted(before.keys() - desired.keys())
            connection.executemany("DELETE FROM documents WHERE concept_id = ?", ((item,) for item in removed))
            changed = 0
            names = "concept_id, content_sha256, search_sha256, " + ", ".join(FIELDS)
            update = ", ".join(f"{name}=excluded.{name}" for name in ("content_sha256", "search_sha256", *FIELDS))
            for concept_id, concept in desired.items():
                if before.get(concept_id) == concept.content_sha256:
                    continue
                search = tuple(_search_haystacks(concept).values())
                values = (concept_id, concept.content_sha256, _search_digest(search), *search)
                connection.execute(f"INSERT INTO documents ({names}) VALUES ({', '.join('?' for _ in values)}) "
                                   f"ON CONFLICT(concept_id) DO UPDATE SET {update}", values)
                changed += 1
            if changed or removed or metadata["source_digest"] != bundle.source_digest:
                metadata["source_digest"] = bundle.source_digest
                connection.execute("INSERT OR REPLACE INTO metadata VALUES ('contract', ?)",
                                   (json.dumps(metadata, sort_keys=True),))
            _check_rows(connection, bundle, full=True)
            _check_postings(connection, metadata)
            _assert_current(bundle)
            connection.commit()
            return _report(metadata, changed=changed, removed=len(removed), postings_checked=True)
    except (OSError, sqlite3.Error) as exc:
        raise KnowledgeBaseError("INDEX_WRITE_UNAVAILABLE") from exc


def verify_index(bundle: Bundle, path: Path) -> dict[str, Any]:
    _require_valid_bundle(bundle)
    try:
        with contextlib.closing(_connect(_path(path), write=True)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            metadata = _metadata(connection, bundle, current=True)
            if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise KnowledgeBaseError("INDEX_INTEGRITY_FAILED")
            _check_rows(connection, bundle, full=True)
            _check_postings(connection, metadata)
            _assert_current(bundle)
            connection.rollback()
            return _report(metadata, postings_checked=True)
    except (OSError, sqlite3.Error) as exc:
        raise KnowledgeBaseError("INDEX_READ_UNAVAILABLE") from exc


def _candidates(connection: sqlite3.Connection, query: str, backend: str) -> tuple[list[str], str]:
    normalized = _normalized_text(query.strip())
    tokens = re.findall(r"[\w-]+", normalized)
    if not normalized:
        raise KnowledgeBaseError("query must not be empty")
    if len(normalized) > 4096 or len(tokens) > 64:
        raise KnowledgeBaseError("INDEX_QUERY_BUDGET")
    terms = sorted(set([normalized, *tokens]))
    long = [term for term in terms if len(term) >= 3 and "\x00" not in term] if backend == "fts5-trigram" else []
    short = [term for term in terms if term not in long]
    queries, parameters = [], []
    if long:
        queries.append("SELECT rowid FROM search WHERE search MATCH ?")
        parameters.append(" OR ".join('"' + term.replace('"', '""') + '"' for term in long))
    if short:
        conditions = []
        for term in short:
            conditions.extend(f"instr({field}, ?) > 0" for field in FIELDS)
            parameters.extend([term] * len(FIELDS))
        queries.append("SELECT rowid FROM documents WHERE " + " OR ".join(conditions))
    sql = "SELECT concept_id FROM documents WHERE rowid IN (" + " UNION ".join(queries) + ")"
    mode = "fts5-trigram+substring" if long and short else "fts5-trigram" if long else "substring"
    return [row[0] for row in connection.execute(sql, parameters)], mode


def query_index(bundle: Bundle, path: Path, query: str, **filters: Any):
    """Shortlist only: current source, admission, filters and ranking stay canonical."""
    _require_valid_bundle(bundle)
    try:
        with contextlib.closing(_connect(_path(path))) as connection:
            connection.execute("BEGIN")
            metadata = _metadata(connection, bundle, current=True)
            _check_rows(connection, bundle)
            candidates, mode = _candidates(connection, query, metadata["backend"])
            by_id = bundle.by_id
            results = query_bundle(bundle, query, _candidates=(by_id[item] for item in candidates), **filters)
            _assert_current(bundle)
            report = _report(metadata)
            report.update({"mode": mode, "candidate_count": len(candidates)})
            return results, report
    except (OSError, sqlite3.Error) as exc:
        raise KnowledgeBaseError("INDEX_READ_UNAVAILABLE") from exc
