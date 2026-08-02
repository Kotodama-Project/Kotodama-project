#!/usr/bin/env python3
"""Initialize a new-file-only SQLite nonce store for protected attestation evaluation."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path


SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
METADATA_TABLE_SQL = (
    "CREATE TABLE store_metadata ("
    "singleton INTEGER PRIMARY KEY CHECK(singleton = 1), "
    "schema_version INTEGER NOT NULL CHECK(schema_version = 1), "
    "store_id_sha256 TEXT NOT NULL CHECK(length(store_id_sha256) = 64))"
)
NONCE_TABLE_SQL = (
    "CREATE TABLE nonce_reservations ("
    "nonce_sha256 TEXT PRIMARY KEY CHECK(length(nonce_sha256) = 64), "
    "attestation_sha256 TEXT NOT NULL CHECK(length(attestation_sha256) = 64), "
    "policy_sha256 TEXT NOT NULL CHECK(length(policy_sha256) = 64), "
    "evidence_sha256 TEXT NOT NULL CHECK(length(evidence_sha256) = 64), "
    "signature_sha256 TEXT NOT NULL CHECK(length(signature_sha256) = 64), "
    "allowed_signers_sha256 TEXT NOT NULL CHECK(length(allowed_signers_sha256) = 64), "
    "identity_file_sha256 TEXT NOT NULL CHECK(length(identity_file_sha256) = 64), "
    "evaluated_at TEXT NOT NULL, "
    "reservation_sha256 TEXT NOT NULL UNIQUE CHECK(length(reservation_sha256) = 64))"
)


def report(status: str, errors: list[str], store_id: str | None = None) -> dict[str, object]:
    return {
        "kind": "attestation_nonce_store_initialization",
        "version": "1.0",
        "status": status,
        "errors": errors,
        "store_id_sha256": store_id,
        "schema_version": 1 if status == "INITIALIZED" else None,
        "claims": {
            "new_file_created": status == "INITIALIZED",
            "nonce_store_schema_initialized": status == "INITIALIZED",
            "nonce_store_continuity_verified": False,
            "canonical_adoption_verified": False,
            "public_beta_go": False,
        },
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            "usage: initialize_attestation_nonce_store.py NONCE_STORE_DB STORE_ID_SHA256",
            file=sys.stderr,
        )
        return 2
    target = Path(argv[1])
    store_id = argv[2]
    created = False
    if SHA256_HEX.fullmatch(store_id) is None:
        print(json.dumps(report("INVALID", ["store ID must be lowercase SHA-256"]), sort_keys=True))
        return 1
    try:
        if target.exists() or target.is_symlink():
            raise FileExistsError
        if not target.parent.is_dir() or target.parent.is_symlink():
            raise OSError
        descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(descriptor)
        created = True
        connection = sqlite3.connect(str(target), timeout=30, isolation_level=None)
        try:
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(METADATA_TABLE_SQL)
            connection.execute(
                "INSERT INTO store_metadata(singleton, schema_version, store_id_sha256) "
                "VALUES(1, 1, ?)",
                (store_id,),
            )
            connection.execute(NONCE_TABLE_SQL)
            connection.execute("PRAGMA user_version=1")
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
    except FileExistsError:
        print(json.dumps(report("REFUSED", ["target already exists"]), sort_keys=True))
        return 1
    except (OSError, sqlite3.Error):
        if created and target.exists() and target.is_file() and not target.is_symlink():
            try:
                target.unlink()
            except OSError:
                pass
        print(json.dumps(report("INVALID", ["nonce store initialization failed"]), sort_keys=True))
        return 1
    print(json.dumps(report("INITIALIZED", [], store_id), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
