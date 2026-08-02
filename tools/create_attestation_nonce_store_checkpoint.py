#!/usr/bin/env python3
"""Create a privacy-safe signed-checkpoint candidate from a private nonce store."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluate_compose_attestation_once import inspect_store
from initialize_attestation_nonce_store import METADATA_TABLE_SQL, NONCE_TABLE_SQL
from validate_resolved_compose_candidate import canonical_sha256, load_strict_json_bytes
from verify_protected_compose_evidence_attestation import parse_time, safe_read, sha256_bytes


NAMESPACE = "kotodama-nonce-store-checkpoint"
MAX_CHECKPOINT_BYTES = 2 * 1024 * 1024
MAX_RESERVATIONS = 10_000
MAX_NONCE_STORE_BYTES = 64 * 1024 * 1024
MAX_STORE_QUERY_SECONDS = 30
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
CHECKPOINT_FIELDS = {
    "kind",
    "version",
    "status",
    "created_at",
    "clock_source",
    "store_binding",
    "signature_policy_binding",
    "parent_binding",
    "claims",
    "checkpoint_chain_sha256",
    "public_beta",
}
STORE_FIELDS = {
    "store_id_sha256",
    "schema_contract_sha256",
    "reservation_count",
    "reservation_sha256s",
    "reservation_set_sha256",
}
SIGNATURE_FIELDS = {
    "namespace",
    "allowed_signers_file_sha256",
    "signer_identity_sha256",
    "signer_role",
}
PARENT_FIELDS = {
    "mode",
    "parent_checkpoint_file_sha256",
    "parent_checkpoint_chain_sha256",
}
CHECKPOINT_FALSE_FIELDS = {
    "checkpoint_signature_verified",
    "supplied_checkpoint_digest_match_verified",
    "supplied_parent_digest_match_verified",
    "immediate_parent_signature_verified",
    "one_link_append_only_extension_verified",
    "store_matches_checkpoint_verified",
    "external_anchor_authority_verified",
    "trusted_clock_source_verified",
    "store_continuity_verified",
    "restore_execution_verified",
    "promotion_verified",
    "current_truth_changed",
    "final_human_go",
    "public_beta_go",
}
SCHEMA_CONTRACT_SHA256 = hashlib.sha256(
    (
        METADATA_TABLE_SQL
        + "\n"
        + NONCE_TABLE_SQL
        + "\nuser_version=1\njournal_mode=delete\nmax_reservations=10000"
    ).encode("utf-8")
).hexdigest()


def require_exact_fields(
    value: object, expected: set[str], location: str, errors: list[str]
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        errors.append(f"{location} must be an object")
        return None
    if expected - value.keys():
        errors.append(f"{location} is missing required fields")
    if value.keys() - expected:
        errors.append(f"{location} contains unknown fields")
    return value


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and SHA256_HEX.fullmatch(value) is not None


def reservation_set_sha256(values: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(values, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def checkpoint_chain_sha256(checkpoint: dict[str, Any]) -> str:
    projection = dict(checkpoint)
    projection.pop("checkpoint_chain_sha256", None)
    return canonical_sha256(projection)


def _snapshot_from_connection(
    connection: sqlite3.Connection,
) -> tuple[dict[str, Any] | None, list[str]]:
    metadata = connection.execute(
        "SELECT store_id_sha256 FROM store_metadata WHERE singleton=1"
    ).fetchmany(2)
    if len(metadata) != 1 or not is_sha256(metadata[0][0]):
        return None, ["nonce store identity is invalid"]
    store_id = metadata[0][0]
    errors = inspect_store(connection, store_id)
    rows = connection.execute(
        "SELECT nonce_sha256, attestation_sha256, policy_sha256, evidence_sha256, "
        "signature_sha256, allowed_signers_sha256, identity_file_sha256, "
        "evaluated_at, reservation_sha256 FROM nonce_reservations"
    ).fetchmany(MAX_RESERVATIONS + 1)
    if len(rows) > MAX_RESERVATIONS:
        errors.append("nonce store exceeds checkpoint reservation limit")
    reservations: list[str] = []
    for row in rows:
        if len(row) != 9 or any(not isinstance(value, str) for value in row):
            errors.append("nonce reservation row is invalid")
            continue
        hashes = list(row[:7]) + [row[8]]
        if any(not is_sha256(value) for value in hashes):
            errors.append("nonce reservation hash is invalid")
            continue
        time_errors: list[str] = []
        parse_time(row[7], "reservation evaluated_at", time_errors)
        errors.extend(time_errors)
        recomputed = hashlib.sha256("\n".join(row[:8]).encode("utf-8")).hexdigest()
        if recomputed != row[8]:
            errors.append("nonce reservation digest mismatch")
            continue
        reservations.append(row[8])
    reservations.sort()
    if len(reservations) != len(set(reservations)):
        errors.append("nonce reservation digests must be unique")
    if errors:
        return None, sorted(set(errors))
    return (
        {
            "store_id_sha256": store_id,
            "schema_contract_sha256": SCHEMA_CONTRACT_SHA256,
            "reservation_count": len(reservations),
            "reservation_sha256s": reservations,
            "reservation_set_sha256": reservation_set_sha256(reservations),
        },
        [],
    )


@contextmanager
def hold_store_snapshot(path: Path):
    """Hold a DELETE-journal read transaction until the caller emits its verdict."""
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    try:
        for component in absolute.parts[1:]:
            current /= component
            component_stat = os.stat(current, follow_symlinks=False)
            if stat.S_ISLNK(component_stat.st_mode) or (
                hasattr(current, "is_junction") and current.is_junction()
            ):
                raise OSError
        before = os.stat(absolute, follow_symlinks=False)
    except OSError:
        before = None
    if (
        before is None
        or path.is_symlink()
        or not path.is_file()
        or not stat.S_ISREG(before.st_mode)
        or before.st_size <= 0
        or before.st_size > MAX_NONCE_STORE_BYTES
    ):
        yield None, ["nonce store input is invalid"]
        return
    connection: sqlite3.Connection | None = None
    guard_descriptor: int | None = None
    try:
        guard_descriptor = os.open(
            absolute,
            os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        guarded = os.fstat(guard_descriptor)
        if (guarded.st_dev, guarded.st_ino) != (before.st_dev, before.st_ino):
            raise OSError
        connection = sqlite3.connect(
            absolute.as_uri() + "?mode=ro",
            timeout=30,
            isolation_level=None,
            uri=True,
        )
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA query_only=ON")
        query_deadline = time.monotonic() + MAX_STORE_QUERY_SECONDS
        connection.set_progress_handler(
            lambda: 1 if time.monotonic() > query_deadline else 0,
            1000,
        )
        connection.execute("BEGIN")
        snapshot = _snapshot_from_connection(connection)
        after = os.stat(absolute, follow_symlinks=False)
        stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
        if any(
            getattr(after, field) != getattr(before, field)
            for field in stable_fields
        ):
            snapshot = (None, ["nonce store input changed during open"])
    except (OSError, sqlite3.Error):
        snapshot = (None, ["nonce store snapshot failed"])
    try:
        yield snapshot
    finally:
        if connection is not None:
            if connection.in_transaction:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            connection.close()
        if guard_descriptor is not None:
            os.close(guard_descriptor)


def read_store_snapshot(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    with hold_store_snapshot(path) as snapshot:
        return snapshot


def validate_checkpoint(checkpoint: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    require_exact_fields(checkpoint, CHECKPOINT_FIELDS, "checkpoint", errors)
    if checkpoint.get("kind") != "attestation_nonce_store_checkpoint":
        errors.append("checkpoint kind is invalid")
    if checkpoint.get("version") != "1.0":
        errors.append("checkpoint version must be 1.0")
    if checkpoint.get("status") != "CHECKPOINT_CANDIDATE":
        errors.append("checkpoint status must remain CHECKPOINT_CANDIDATE")
    parse_time(checkpoint.get("created_at"), "created_at", errors)
    if checkpoint.get("clock_source") != "local_system_utc_untrusted":
        errors.append("clock_source must remain local_system_utc_untrusted")

    store = require_exact_fields(checkpoint.get("store_binding"), STORE_FIELDS, "store_binding", errors)
    if store is not None:
        for field in ("store_id_sha256", "schema_contract_sha256", "reservation_set_sha256"):
            if not is_sha256(store.get(field)):
                errors.append(f"store_binding.{field} must be lowercase SHA-256")
        if store.get("schema_contract_sha256") != SCHEMA_CONTRACT_SHA256:
            errors.append("store schema contract mismatch")
        reservations = store.get("reservation_sha256s")
        count = store.get("reservation_count")
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= MAX_RESERVATIONS:
            errors.append("reservation_count is invalid")
        if not isinstance(reservations, list) or any(not is_sha256(value) for value in reservations):
            errors.append("reservation_sha256s is invalid")
        else:
            if reservations != sorted(set(reservations)):
                errors.append("reservation_sha256s must be sorted and unique")
            if count != len(reservations):
                errors.append("reservation_count mismatch")
            if store.get("reservation_set_sha256") != reservation_set_sha256(reservations):
                errors.append("reservation set digest mismatch")

    signature = require_exact_fields(
        checkpoint.get("signature_policy_binding"),
        SIGNATURE_FIELDS,
        "signature_policy_binding",
        errors,
    )
    if signature is not None:
        if signature.get("namespace") != NAMESPACE:
            errors.append(f"signature namespace must be {NAMESPACE}")
        if not is_sha256(signature.get("allowed_signers_file_sha256")):
            errors.append("allowed signers binding must be lowercase SHA-256")
        if not is_sha256(signature.get("signer_identity_sha256")):
            errors.append("signer identity binding must be lowercase SHA-256")
        if signature.get("signer_role") != "independent_reviewer":
            errors.append("signer role must be independent_reviewer")

    parent = require_exact_fields(
        checkpoint.get("parent_binding"), PARENT_FIELDS, "parent_binding", errors
    )
    if parent is not None:
        mode = parent.get("mode")
        if mode == "GENESIS":
            if parent.get("parent_checkpoint_file_sha256") is not None or parent.get(
                "parent_checkpoint_chain_sha256"
            ) is not None:
                errors.append("genesis parent bindings must be null")
        elif mode == "SUCCESSOR":
            if not is_sha256(parent.get("parent_checkpoint_file_sha256")) or not is_sha256(
                parent.get("parent_checkpoint_chain_sha256")
            ):
                errors.append("successor parent bindings must be lowercase SHA-256")
        else:
            errors.append("parent mode is invalid")

    claims = require_exact_fields(
        checkpoint.get("claims"), CHECKPOINT_FALSE_FIELDS, "claims", errors
    )
    if claims is not None:
        for field in CHECKPOINT_FALSE_FIELDS:
            if claims.get(field) is not False:
                errors.append(f"claim {field} must remain false")
    if not is_sha256(checkpoint.get("checkpoint_chain_sha256")):
        errors.append("checkpoint_chain_sha256 must be lowercase SHA-256")
    elif checkpoint.get("checkpoint_chain_sha256") != checkpoint_chain_sha256(checkpoint):
        errors.append("checkpoint chain self-digest mismatch")
    if checkpoint.get("public_beta") != "NO_GO_UNPUBLISHED":
        errors.append("public_beta must remain NO_GO_UNPUBLISHED")
    return sorted(set(errors))


def creation_report(
    status: str, errors: list[str], checkpoint_bytes: bytes | None = None
) -> dict[str, Any]:
    return {
        "kind": "attestation_nonce_store_checkpoint_creation",
        "version": "1.0",
        "status": status,
        "errors": errors,
        "checkpoint_file_sha256": sha256_bytes(checkpoint_bytes) if checkpoint_bytes else None,
        "claims": {
            "private_checkpoint_candidate_created": status == "CHECKPOINT_CREATED",
            "checkpoint_signature_verified": False,
            "external_anchor_authority_verified": False,
            "trusted_clock_source_verified": False,
            "store_continuity_verified": False,
            "restore_execution_verified": False,
            "public_beta_go": False,
        },
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def write_new_file(path: Path, value: bytes) -> None:
    if path.exists() or path.is_symlink() or not path.parent.is_dir() or path.parent.is_symlink():
        raise OSError
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            path.unlink()
        except OSError:
            pass
        raise


def main(argv: list[str]) -> int:
    if len(argv) != 7 or argv[5] != "--output":
        print(
            "usage: create_attestation_nonce_store_checkpoint.py NONCE_STORE_DB "
            "PARENT_CHECKPOINT_OR_GENESIS ALLOWED_SIGNERS_FILE SIGNER_IDENTITY_FILE "
            "--output CHECKPOINT_JSON",
            file=sys.stderr,
        )
        return 2
    try:
        store_path = Path(argv[1])
        parent_argument = argv[2]
        allowed_bytes = safe_read(Path(argv[3]), maximum=MAX_CHECKPOINT_BYTES)
        identity_bytes = safe_read(Path(argv[4]), maximum=4096)
        identity = identity_bytes.decode("utf-8")
        if re.fullmatch(r"[A-Za-z0-9._@+-]{1,256}", identity) is None:
            raise ValueError
        output_path = Path(argv[6])
        store_binding, store_errors = read_store_snapshot(store_path)
        if store_errors or store_binding is None:
            raise ValueError("store invalid")
        if parent_argument == "GENESIS":
            parent_binding = {
                "mode": "GENESIS",
                "parent_checkpoint_file_sha256": None,
                "parent_checkpoint_chain_sha256": None,
            }
        else:
            parent_bytes = safe_read(Path(parent_argument), maximum=MAX_CHECKPOINT_BYTES)
            parent = load_strict_json_bytes(parent_bytes)
            parent_errors = validate_checkpoint(parent)
            if parent_errors:
                raise ValueError("parent invalid")
            if parent["store_binding"]["store_id_sha256"] != store_binding["store_id_sha256"]:
                raise ValueError("parent store mismatch")
            if not set(parent["store_binding"]["reservation_sha256s"]).issubset(
                store_binding["reservation_sha256s"]
            ):
                raise ValueError("parent reservations missing")
            parent_binding = {
                "mode": "SUCCESSOR",
                "parent_checkpoint_file_sha256": sha256_bytes(parent_bytes),
                "parent_checkpoint_chain_sha256": parent["checkpoint_chain_sha256"],
            }
        checkpoint = {
            "kind": "attestation_nonce_store_checkpoint",
            "version": "1.0",
            "status": "CHECKPOINT_CANDIDATE",
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "clock_source": "local_system_utc_untrusted",
            "store_binding": store_binding,
            "signature_policy_binding": {
                "namespace": NAMESPACE,
                "allowed_signers_file_sha256": sha256_bytes(allowed_bytes),
                "signer_identity_sha256": sha256_bytes(identity_bytes),
                "signer_role": "independent_reviewer",
            },
            "parent_binding": parent_binding,
            "claims": {field: False for field in sorted(CHECKPOINT_FALSE_FIELDS)},
            "checkpoint_chain_sha256": "",
            "public_beta": "NO_GO_UNPUBLISHED",
        }
        checkpoint["checkpoint_chain_sha256"] = checkpoint_chain_sha256(checkpoint)
        errors = validate_checkpoint(checkpoint)
        if errors:
            raise ValueError("generated checkpoint invalid")
        checkpoint_bytes = (
            json.dumps(checkpoint, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        write_new_file(output_path, checkpoint_bytes)
    except (OSError, UnicodeError, json.JSONDecodeError, sqlite3.Error, TypeError, ValueError):
        print(json.dumps(creation_report("INVALID", ["checkpoint creation failed"]), sort_keys=True))
        return 1
    print(json.dumps(creation_report("CHECKPOINT_CREATED", [], checkpoint_bytes), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
