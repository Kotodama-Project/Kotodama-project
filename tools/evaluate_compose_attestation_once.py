#!/usr/bin/env python3
"""Verify a protected Compose attestation and atomically reserve its nonce once."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_resolved_compose_candidate import load_strict_json_bytes, validate_candidate
from initialize_attestation_nonce_store import METADATA_TABLE_SQL, NONCE_TABLE_SQL
from verify_compose_image_availability_preflight import validate_snapshot
from verify_compose_clean_install_migration_evidence_candidate import validate_evidence
from verify_protected_compose_evidence_attestation import (
    LIVE_CLAIM_FIELDS,
    NAMESPACE,
    parse_time,
    safe_read,
    sha256_bytes,
    validate_attestation,
    verify_signature,
)


MAX_FILE_BYTES = 1024 * 1024
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
POLICY_FIELDS = {
    "kind",
    "version",
    "status",
    "policy_id",
    "allowed_signers_file_sha256",
    "nonce_store_id_sha256",
    "required_namespace",
    "required_signer_role",
    "max_signed_window_seconds",
    "max_report_to_signature_seconds",
    "not_before",
    "expires_at",
    "clock_source",
    "claims",
    "public_beta",
}
POLICY_FALSE_FIELDS = {
    "canonical_trust_policy_verified",
    "trusted_clock_source_verified",
    "nonce_store_continuity_verified",
} | set(LIVE_CLAIM_FIELDS)
SUCCESS_TRUE_FIELDS = {
    "external_policy_digest_match_verified",
    "policy_structure_verified",
    "allowed_signers_file_binding_verified",
    "nonce_store_identity_binding_verified",
    "local_system_clock_used",
    "underlying_evidence_candidate_verified",
    "attestation_bytes_signature_verified",
    "allowed_signer_verified",
    "signer_identity_binding_verified",
    "signer_role_policy_verified",
    "signed_evidence_binding_verified",
    "signed_evaluation_window_verified",
    "reported_time_proximity_verified",
    "atomic_nonce_reservation_verified",
    "one_use_evaluation_recorded",
}
ALL_REPORT_FIELDS = POLICY_FALSE_FIELDS | SUCCESS_TRUE_FIELDS | {
    "replay_detected_in_bound_store"
}


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


def validate_policy(
    policy: dict[str, Any],
    policy_bytes: bytes,
    expected_policy_sha256: str,
    allowed_signers_bytes: bytes,
    evaluated_at: datetime,
) -> list[str]:
    errors: list[str] = []
    require_exact_fields(policy, POLICY_FIELDS, "policy", errors)
    if SHA256_HEX.fullmatch(expected_policy_sha256) is None:
        errors.append("expected policy digest must be lowercase SHA-256")
    if sha256_bytes(policy_bytes) != expected_policy_sha256:
        errors.append("external policy digest mismatch")
    if policy.get("kind") != "compose_attestation_one_use_policy":
        errors.append("policy kind is invalid")
    if policy.get("version") != "1.0":
        errors.append("policy version must be 1.0")
    if policy.get("status") != "POLICY_CANDIDATE":
        errors.append("policy status must remain POLICY_CANDIDATE")
    if not isinstance(policy.get("policy_id"), str) or re.fullmatch(
        r"[a-z][a-z0-9-]{2,63}", policy.get("policy_id", "")
    ) is None:
        errors.append("policy_id is invalid")
    if policy.get("allowed_signers_file_sha256") != sha256_bytes(allowed_signers_bytes):
        errors.append("allowed signers file binding mismatch")
    if not isinstance(policy.get("nonce_store_id_sha256"), str) or SHA256_HEX.fullmatch(
        policy.get("nonce_store_id_sha256", "")
    ) is None:
        errors.append("nonce store ID must be lowercase SHA-256")
    if policy.get("required_namespace") != NAMESPACE:
        errors.append(f"required namespace must be {NAMESPACE}")
    if policy.get("required_signer_role") != "independent_reviewer":
        errors.append("required signer role must be independent_reviewer")
    signed_window = policy.get("max_signed_window_seconds")
    report_window = policy.get("max_report_to_signature_seconds")
    if isinstance(signed_window, bool) or not isinstance(signed_window, int) or not 1 <= signed_window <= 900:
        errors.append("max_signed_window_seconds must be an integer from 1 to 900")
    if isinstance(report_window, bool) or not isinstance(report_window, int) or not 0 <= report_window <= 300:
        errors.append("max_report_to_signature_seconds must be an integer from 0 to 300")
    if policy.get("clock_source") != "local_system_utc_untrusted":
        errors.append("clock_source must remain local_system_utc_untrusted")
    claims = require_exact_fields(policy.get("claims"), POLICY_FALSE_FIELDS, "policy claims", errors)
    if claims is not None:
        for field in POLICY_FALSE_FIELDS:
            if claims.get(field) is not False:
                errors.append(f"policy claim {field} must remain false")
    if policy.get("public_beta") != "NO_GO_UNPUBLISHED":
        errors.append("policy public_beta must remain NO_GO_UNPUBLISHED")
    not_before = parse_time(policy.get("not_before"), "policy.not_before", errors)
    expires_at = parse_time(policy.get("expires_at"), "policy.expires_at", errors)
    if not_before is not None and expires_at is not None:
        if not_before >= expires_at:
            errors.append("policy validity window must have positive duration")
        if not not_before <= evaluated_at <= expires_at:
            errors.append("local evaluation time is outside policy validity")
    return sorted(set(errors))


def validate_policy_attestation_limits(
    policy: dict[str, Any], attestation: dict[str, Any], evidence: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    time_errors: list[str] = []
    issued_at = parse_time(attestation.get("issued_at"), "issued_at", time_errors)
    expires_at = parse_time(attestation.get("expires_at"), "expires_at", time_errors)
    reported_at = parse_time(evidence.get("reported_at"), "evidence.reported_at", time_errors)
    errors.extend(time_errors)
    if issued_at is not None and expires_at is not None and isinstance(
        policy.get("max_signed_window_seconds"), int
    ):
        if (expires_at - issued_at).total_seconds() > policy["max_signed_window_seconds"]:
            errors.append("attestation signed window exceeds policy")
    if issued_at is not None and reported_at is not None and isinstance(
        policy.get("max_report_to_signature_seconds"), int
    ):
        if (issued_at - reported_at).total_seconds() > policy[
            "max_report_to_signature_seconds"
        ]:
            errors.append("report-to-sign interval exceeds policy")
    return sorted(set(errors))


def inspect_store(connection: sqlite3.Connection, expected_store_id: object) -> list[str]:
    errors: list[str] = []
    try:
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        quick_check = connection.execute("PRAGMA quick_check").fetchall()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        metadata = connection.execute(
            "SELECT schema_version, store_id_sha256 FROM store_metadata WHERE singleton=1"
        ).fetchall()
        table_sql = dict(
            connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table' AND name IN "
                "('store_metadata', 'nonce_reservations')"
            ).fetchall()
        )
        nonce_columns = [
            row[1] for row in connection.execute("PRAGMA table_info(nonce_reservations)")
        ]
    except sqlite3.Error:
        return ["nonce store schema is invalid"]
    if user_version != 1 or tables != {"store_metadata", "nonce_reservations"}:
        errors.append("nonce store schema is invalid")
    if str(journal_mode).lower() != "delete":
        errors.append("nonce store journal mode is invalid")
    if quick_check != [("ok",)]:
        errors.append("nonce store integrity check failed")
    if table_sql != {
        "store_metadata": METADATA_TABLE_SQL,
        "nonce_reservations": NONCE_TABLE_SQL,
    }:
        errors.append("nonce store schema is invalid")
    if metadata != [(1, expected_store_id)]:
        errors.append("nonce store identity binding mismatch")
    if nonce_columns != [
        "nonce_sha256",
        "attestation_sha256",
        "policy_sha256",
        "evidence_sha256",
        "signature_sha256",
        "allowed_signers_sha256",
        "identity_file_sha256",
        "evaluated_at",
        "reservation_sha256",
    ]:
        errors.append("nonce store schema is invalid")
    return sorted(set(errors))


def evaluation_report(
    status: str,
    errors: list[str],
    bindings: dict[str, str] | None = None,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    claims = {field: False for field in sorted(ALL_REPORT_FIELDS)}
    if status == "ONE_USE_SIGNATURE_AND_POLICY_MATCH":
        for field in SUCCESS_TRUE_FIELDS:
            claims[field] = True
    elif status == "REPLAY_REFUSED":
        claims["replay_detected_in_bound_store"] = True
    return {
        "kind": "compose_attestation_one_use_evaluation",
        "version": "1.0",
        "status": status,
        "errors": errors,
        "evaluated_at": (
            evaluated_at.isoformat().replace("+00:00", "Z") if evaluated_at else None
        ),
        "input_bindings": dict(sorted((bindings or {}).items())),
        "claims": claims,
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 11:
        print(
            "usage: evaluate_compose_attestation_once.py POLICY_JSON "
            "EXPECTED_POLICY_SHA256 ATTESTATION_JSON SIGNATURE_FILE EVIDENCE_JSON "
            "RESOLVED_CANDIDATE_JSON IMAGE_PREFLIGHT_JSON ALLOWED_SIGNERS_FILE "
            "SIGNER_IDENTITY_FILE NONCE_STORE_DB",
            file=sys.stderr,
        )
        return 2
    try:
        policy_path = Path(argv[1])
        expected_policy_sha256 = argv[2]
        paths = [Path(value) for value in argv[3:11]]
        policy_bytes = safe_read(policy_path, maximum=MAX_FILE_BYTES)
        attestation_bytes = safe_read(paths[0], maximum=MAX_FILE_BYTES)
        signature_bytes = safe_read(paths[1], maximum=64 * 1024)
        evidence_bytes = safe_read(paths[2], maximum=MAX_FILE_BYTES)
        candidate_bytes = safe_read(paths[3], maximum=MAX_FILE_BYTES)
        preflight_bytes = safe_read(paths[4], maximum=MAX_FILE_BYTES)
        allowed_signers_bytes = safe_read(paths[5], maximum=MAX_FILE_BYTES)
        identity_bytes = safe_read(paths[6], maximum=4096)
        store_path = paths[7]
        if store_path.is_symlink() or not store_path.is_file():
            raise OSError
        policy = load_strict_json_bytes(policy_bytes)
        attestation = load_strict_json_bytes(attestation_bytes)
        evidence = load_strict_json_bytes(evidence_bytes)
        candidate = load_strict_json_bytes(candidate_bytes)
        preflight = load_strict_json_bytes(preflight_bytes)
        identity = identity_bytes.decode("utf-8")
        if re.fullmatch(r"[A-Za-z0-9._@+-]{1,256}", identity) is None:
            raise ValueError
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        print(json.dumps(evaluation_report("INVALID", ["input is invalid"]), sort_keys=True))
        return 1

    bindings = {
        "allowed_signers_file_sha256": sha256_bytes(allowed_signers_bytes),
        "attestation_file_sha256": sha256_bytes(attestation_bytes),
        "evidence_file_sha256": sha256_bytes(evidence_bytes),
        "identity_file_sha256": sha256_bytes(identity_bytes),
        "policy_file_sha256": sha256_bytes(policy_bytes),
        "signature_file_sha256": sha256_bytes(signature_bytes),
    }
    if isinstance(policy.get("nonce_store_id_sha256"), str) and SHA256_HEX.fullmatch(
        policy["nonce_store_id_sha256"]
    ):
        bindings["nonce_store_id_sha256"] = policy["nonce_store_id_sha256"]
    errors: list[str] = []
    candidate_errors = validate_candidate(candidate)
    snapshot_errors = (
        ["resolved candidate is invalid"]
        if candidate_errors
        else validate_snapshot(preflight, candidate, candidate_bytes)
    )
    evidence_errors = (
        ["resolved candidate is invalid"]
        if candidate_errors
        else ["image preflight is invalid"]
        if snapshot_errors
        else validate_evidence(evidence, candidate, candidate_bytes, preflight, preflight_bytes)
    )
    if evidence_errors:
        errors.append("underlying evidence candidate is invalid")
    ssh_keygen = shutil.which("ssh-keygen")
    if ssh_keygen is None:
        errors.append("ssh-keygen is unavailable")

    connection: sqlite3.Connection | None = None
    evaluated_at: datetime | None = None
    replay = False
    try:
        connection = sqlite3.connect(
            store_path.resolve().as_uri() + "?mode=rw",
            timeout=30,
            isolation_level=None,
            uri=True,
        )
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("BEGIN IMMEDIATE")
        evaluated_at = datetime.now(timezone.utc)
        errors.extend(
            validate_policy(
                policy,
                policy_bytes,
                expected_policy_sha256,
                allowed_signers_bytes,
                evaluated_at,
            )
        )
        errors.extend(inspect_store(connection, policy.get("nonce_store_id_sha256")))
        errors.extend(validate_attestation(attestation, evidence, evidence_bytes, identity, evaluated_at))
        errors.extend(validate_policy_attestation_limits(policy, attestation, evidence))
        if ssh_keygen is not None and not verify_signature(
            ssh_keygen, paths[5], identity, paths[1], attestation_bytes
        ):
            errors.append("detached signature verification failed")
        errors = sorted(set(errors))
        if errors:
            connection.execute("ROLLBACK")
        else:
            nonce = attestation["nonce_sha256"]
            reservation_input = "\n".join(
                [
                    nonce,
                    bindings["attestation_file_sha256"],
                    bindings["policy_file_sha256"],
                    bindings["evidence_file_sha256"],
                    bindings["signature_file_sha256"],
                    bindings["allowed_signers_file_sha256"],
                    bindings["identity_file_sha256"],
                    evaluated_at.isoformat().replace("+00:00", "Z"),
                ]
            ).encode("utf-8")
            reservation_sha256 = hashlib.sha256(reservation_input).hexdigest()
            bindings["reservation_sha256"] = reservation_sha256
            try:
                connection.execute(
                    "INSERT INTO nonce_reservations("
                    "nonce_sha256, attestation_sha256, policy_sha256, evidence_sha256, "
                    "signature_sha256, allowed_signers_sha256, identity_file_sha256, "
                    "evaluated_at, reservation_sha256) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        nonce,
                        bindings["attestation_file_sha256"],
                        bindings["policy_file_sha256"],
                        bindings["evidence_file_sha256"],
                        bindings["signature_file_sha256"],
                        bindings["allowed_signers_file_sha256"],
                        bindings["identity_file_sha256"],
                        evaluated_at.isoformat().replace("+00:00", "Z"),
                        reservation_sha256,
                    ),
                )
                connection.execute("COMMIT")
            except sqlite3.IntegrityError:
                existing_nonce = connection.execute(
                    "SELECT 1 FROM nonce_reservations WHERE nonce_sha256=?", (nonce,)
                ).fetchone()
                connection.execute("ROLLBACK")
                if existing_nonce is not None:
                    replay = True
                else:
                    errors.append("nonce store reservation failed")
    except sqlite3.Error:
        if connection is not None and connection.in_transaction:
            connection.execute("ROLLBACK")
        errors = sorted(set(errors + ["nonce store transaction failed"]))
    finally:
        if connection is not None:
            connection.close()

    if replay:
        print(
            json.dumps(
                evaluation_report(
                    "REPLAY_REFUSED", ["nonce already reserved in bound store"], bindings, evaluated_at
                ),
                sort_keys=True,
            )
        )
        return 1
    if errors:
        print(json.dumps(evaluation_report("INVALID", errors, bindings, evaluated_at), sort_keys=True))
        return 1
    print(
        json.dumps(
            evaluation_report(
                "ONE_USE_SIGNATURE_AND_POLICY_MATCH", [], bindings, evaluated_at
            ),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
