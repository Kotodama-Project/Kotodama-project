"""Bound the entire payload root without storing payload text or Task authority.

The SQLite lock serializes filesystem accounting across local processes. Limits
are persistent and immutable through this API. Failed/partial writes still count;
this layer never deletes shared content or frees quota speculatively.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
import stat
from .protocol import SwarmError

DEFAULT_MAX_PAYLOADS = 4096
DEFAULT_MAX_STORAGE_BYTES = 64 * 1024 * 1024


@contextmanager
def payload_budget(root: Path, payload_root: Path, destination: Path, size: int,
                   max_payloads: int | None, max_storage_bytes: int | None):
    for value, maximum in [(max_payloads, 100000), (max_storage_bytes, 2**34)]:
        if value is not None and (type(value) is not int or not 1 <= value <= maximum):
            raise SwarmError("PAYLOAD_LIMIT_INVALID", "payload storage limit is invalid")
    database = root / ".payload-budget.sqlite"
    connection = None
    try:
        if database.is_symlink() or database.exists() and (not database.is_file() or database.stat().st_nlink != 1):
            raise SwarmError("PAYLOAD_STORAGE_ERROR", "payload budget path is not a private regular file")
        connection = sqlite3.connect(database, timeout=2.0, isolation_level=None)
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("CREATE TABLE IF NOT EXISTS limits (id INTEGER PRIMARY KEY CHECK(id=1), files INTEGER NOT NULL, bytes INTEGER NOT NULL)")
        row = connection.execute("SELECT files,bytes FROM limits WHERE id=1").fetchone()
        if row is None:
            row = (max_payloads or DEFAULT_MAX_PAYLOADS, max_storage_bytes or DEFAULT_MAX_STORAGE_BYTES)
            connection.execute("INSERT INTO limits VALUES(1,?,?)", row)
            # Limits survive even the very first failed/partial payload write.
            connection.execute("COMMIT")
            connection.execute("BEGIN IMMEDIATE")
        elif (max_payloads is not None and max_payloads != row[0]) or (max_storage_bytes is not None and max_storage_bytes != row[1]):
            raise SwarmError("PAYLOAD_LIMIT_CHANGED", "existing payload limits require explicit owner migration")
        count = used = 0
        with os.scandir(payload_root) as entries:
            for entry in entries:
                # DirEntry.stat() reports st_nlink as 0 on Windows; a full
                # lstat reads the real link count on every platform.
                info = os.lstat(entry.path)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise SwarmError("PAYLOAD_STORAGE_ERROR", "payload root contains a non-private regular file")
                count += 1
                used += info.st_size
                if count > row[0] or used > row[1]:
                    raise SwarmError("PAYLOAD_STORAGE_QUOTA", "payload root exceeds its persisted limit")
        # Existing content-addressed data is reusable at a full budget; its
        # integrity is still checked by the caller, never overwritten.
        if not destination.exists() and (count + 1 > row[0] or used + size > row[1]):
            raise SwarmError("PAYLOAD_STORAGE_QUOTA", "payload root has no remaining capacity")
        yield
        connection.execute("COMMIT")
    except sqlite3.DatabaseError as exc:
        raise SwarmError("PAYLOAD_STORAGE_ERROR", "payload budget is unavailable") from exc
    except OSError as exc:
        raise SwarmError("PAYLOAD_STORAGE_ERROR", "payload storage cannot be inspected") from exc
    finally:
        if connection is not None:
            connection.close()
