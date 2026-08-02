#!/usr/bin/env python3
"""Verify a bounded OpenSSH attestation over saved Compose evidence bytes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_resolved_compose_candidate import load_strict_json_bytes, validate_candidate
from verify_compose_image_availability_preflight import validate_snapshot
from verify_compose_clean_install_migration_evidence_candidate import (
    CLAIM_FIELDS as LIVE_CLAIM_FIELDS,
    validate_evidence,
)


NAMESPACE = "kotodama-compose-evidence"
MAX_SIGNED_WINDOW_SECONDS = 900
MAX_REPORT_TO_SIGNATURE_SECONDS = 300
MAX_NONCE_SNAPSHOT_AGE_SECONDS = 60
MAX_AUXILIARY_FILE_BYTES = 1024 * 1024
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
ATTESTATION_FIELDS = {
    "kind",
    "version",
    "status",
    "namespace",
    "signer_identity_sha256",
    "signer_role",
    "issued_at",
    "expires_at",
    "nonce_sha256",
    "evidence_file_sha256",
    "claims",
    "public_beta",
}
LEDGER_FIELDS = {"kind", "version", "snapshot_at", "used_nonce_sha256s"}
POINT_IN_TIME_TRUE_FIELDS = {
    "underlying_evidence_candidate_verified",
    "attestation_bytes_signature_verified",
    "allowed_signer_verified",
    "signer_identity_binding_verified",
    "signer_role_policy_verified",
    "signed_evidence_binding_verified",
    "signed_evaluation_window_verified",
    "reported_time_proximity_verified",
    "nonce_snapshot_freshness_verified",
    "nonce_absent_in_snapshot_verified",
}
ALWAYS_FALSE_FIELDS = {"atomic_nonce_reservation_verified"} | set(LIVE_CLAIM_FIELDS)
ALWAYS_FALSE_FIELDS.update(
    {
        "canonical_trust_root_pin_verified",
        "evaluation_clock_source_verified",
        "nonce_snapshot_authority_verified",
    }
)


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


def parse_time(value: object, location: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str):
        errors.append(f"{location} must be timezone-aware ISO-8601")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{location} must be timezone-aware ISO-8601")
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        errors.append(f"{location} must be timezone-aware ISO-8601")
        return None
    return parsed.astimezone(timezone.utc)


def require_sha256(value: object, location: str, errors: list[str]) -> None:
    if not isinstance(value, str) or SHA256_HEX.fullmatch(value) is None:
        errors.append(f"{location} must be lowercase SHA-256")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def validate_attestation(
    attestation: dict[str, Any],
    evidence: dict[str, Any],
    evidence_bytes: bytes,
    identity: str,
    evaluated_at: datetime,
) -> list[str]:
    errors: list[str] = []
    require_exact_fields(attestation, ATTESTATION_FIELDS, "attestation", errors)
    if attestation.get("kind") != "protected_compose_evidence_attestation":
        errors.append("attestation kind is invalid")
    if attestation.get("version") != "1.0":
        errors.append("attestation version must be 1.0")
    if attestation.get("status") != "PROTECTED_ATTESTATION_CANDIDATE":
        errors.append("attestation status must remain PROTECTED_ATTESTATION_CANDIDATE")
    if attestation.get("namespace") != NAMESPACE:
        errors.append(f"namespace must be {NAMESPACE}")
    if attestation.get("signer_role") != "independent_reviewer":
        errors.append("signer role must be independent_reviewer")
    identity_digest = sha256_bytes(identity.encode("utf-8"))
    require_sha256(attestation.get("signer_identity_sha256"), "signer_identity_sha256", errors)
    if attestation.get("signer_identity_sha256") != identity_digest:
        errors.append("signer identity binding mismatch")
    require_sha256(attestation.get("nonce_sha256"), "nonce_sha256", errors)
    require_sha256(attestation.get("evidence_file_sha256"), "evidence_file_sha256", errors)
    if attestation.get("evidence_file_sha256") != sha256_bytes(evidence_bytes):
        errors.append("signed evidence file binding mismatch")
    claims = require_exact_fields(attestation.get("claims"), set(LIVE_CLAIM_FIELDS), "claims", errors)
    if claims is not None:
        for field in LIVE_CLAIM_FIELDS:
            if claims.get(field) is not False:
                errors.append(f"claim {field} must remain false")
    if attestation.get("public_beta") != "NO_GO_UNPUBLISHED":
        errors.append("public_beta must remain NO_GO_UNPUBLISHED")

    issued_at = parse_time(attestation.get("issued_at"), "issued_at", errors)
    expires_at = parse_time(attestation.get("expires_at"), "expires_at", errors)
    reported_at = parse_time(evidence.get("reported_at"), "evidence.reported_at", errors)
    if issued_at is not None and expires_at is not None:
        window = (expires_at - issued_at).total_seconds()
        if window <= 0:
            errors.append("signed window must have positive duration")
        if window > MAX_SIGNED_WINDOW_SECONDS:
            errors.append("signed window exceeds 900 seconds")
        if not issued_at <= evaluated_at <= expires_at:
            errors.append("evaluation time is outside the signed window")
    if issued_at is not None and reported_at is not None:
        proximity = (issued_at - reported_at).total_seconds()
        if proximity < 0 or proximity > MAX_REPORT_TO_SIGNATURE_SECONDS:
            errors.append("signed issue time is not within 300 seconds after reported_at")
    return sorted(set(errors))


def validate_nonce_snapshot(
    ledger: dict[str, Any], nonce: object, evaluated_at: datetime
) -> list[str]:
    errors: list[str] = []
    require_exact_fields(ledger, LEDGER_FIELDS, "nonce snapshot", errors)
    if ledger.get("kind") != "nonce_use_snapshot":
        errors.append("nonce snapshot kind is invalid")
    if ledger.get("version") != "1.0":
        errors.append("nonce snapshot version must be 1.0")
    snapshot_at = parse_time(ledger.get("snapshot_at"), "nonce snapshot time", errors)
    used = ledger.get("used_nonce_sha256s")
    if not isinstance(used, list):
        errors.append("used_nonce_sha256s must be an array")
    else:
        if len(used) != len(set(value for value in used if isinstance(value, str))):
            errors.append("used_nonce_sha256s must contain unique values")
        for value in used:
            require_sha256(value, "used nonce", errors)
        if nonce in used:
            errors.append("nonce is already present in supplied snapshot")
    if snapshot_at is not None:
        age = (evaluated_at - snapshot_at).total_seconds()
        if age < 0:
            errors.append("nonce snapshot is later than evaluation time")
        if age > MAX_NONCE_SNAPSHOT_AGE_SECONDS:
            errors.append("nonce snapshot is older than 60 seconds")
    return sorted(set(errors))


def verify_signature(
    ssh_keygen: str,
    allowed_signers: Path,
    identity: str,
    signature: Path,
    attestation_bytes: bytes,
) -> bool:
    result = subprocess.run(
        [
            ssh_keygen,
            "-Y",
            "verify",
            "-f",
            str(allowed_signers),
            "-I",
            identity,
            "-n",
            NAMESPACE,
            "-s",
            str(signature),
        ],
        input=attestation_bytes,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def report(
    errors: list[str],
    bindings: dict[str, str] | None = None,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    valid = not errors
    claims = {field: False for field in sorted(ALWAYS_FALSE_FIELDS | POINT_IN_TIME_TRUE_FIELDS)}
    if valid:
        for field in POINT_IN_TIME_TRUE_FIELDS:
            claims[field] = True
    return {
        "kind": "protected_compose_evidence_attestation_validation",
        "version": "1.0",
        "status": "SIGNATURE_AND_POLICY_MATCH_POINT_IN_TIME" if valid else "INVALID",
        "errors": errors,
        "evaluated_at": (
            evaluated_at.isoformat().replace("+00:00", "Z") if evaluated_at is not None else None
        ),
        "input_bindings": dict(sorted((bindings or {}).items())),
        "claims": dict(sorted(claims.items())),
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def safe_read(path: Path, *, maximum: int | None = None) -> bytes:
    """Read one stable regular file without following path-component links."""
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    try:
        for component in absolute.parts[1:]:
            current /= component
            component_stat = os.stat(current, follow_symlinks=False)
            if stat.S_ISLNK(component_stat.st_mode) or (
                hasattr(current, "is_junction") and current.is_junction()
            ):
                raise OSError("unsafe input")
        before = os.stat(absolute, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise OSError("unsafe input")
        if maximum is not None and (before.st_size <= 0 or before.st_size > maximum):
            raise OSError("unsafe input")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(absolute, flags)
    except (OSError, ValueError):
        raise OSError("unsafe input") from None
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (
            opened.st_dev,
            opened.st_ino,
        ) != (before.st_dev, before.st_ino):
            raise OSError("unsafe input")
        limit = maximum + 1 if maximum is not None else None
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            value = source.read() if limit is None else source.read(limit)
        after_open = os.fstat(descriptor)
        after_path = os.stat(absolute, follow_symlinks=False)
        # Windows reports creation/change time differently for path-stat and
        # descriptor fstat, so bind only fields with cross-interface semantics.
        stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
        if any(
            getattr(before, field) != getattr(after_open, field)
            or getattr(before, field) != getattr(after_path, field)
            for field in stable_fields
        ):
            raise OSError("unsafe input")
        if not value or (maximum is not None and len(value) > maximum):
            raise OSError("unsafe input")
        return value
    except OSError:
        raise OSError("unsafe input") from None
    finally:
        os.close(descriptor)


def main(argv: list[str]) -> int:
    if len(argv) != 10:
        print(
            "usage: verify_protected_compose_evidence_attestation.py "
            "ATTESTATION_JSON SIGNATURE_FILE EVIDENCE_JSON RESOLVED_CANDIDATE_JSON "
            "IMAGE_PREFLIGHT_JSON ALLOWED_SIGNERS_FILE NONCE_SNAPSHOT_JSON "
            "SIGNER_IDENTITY_FILE EVALUATED_AT",
            file=sys.stderr,
        )
        return 2
    try:
        paths = [Path(value) for value in argv[1:9]]
        attestation_bytes = safe_read(paths[0], maximum=MAX_AUXILIARY_FILE_BYTES)
        signature_bytes = safe_read(paths[1], maximum=64 * 1024)
        evidence_bytes = safe_read(paths[2], maximum=MAX_AUXILIARY_FILE_BYTES)
        candidate_bytes = safe_read(paths[3], maximum=MAX_AUXILIARY_FILE_BYTES)
        preflight_bytes = safe_read(paths[4], maximum=MAX_AUXILIARY_FILE_BYTES)
        allowed_signers_bytes = safe_read(paths[5], maximum=MAX_AUXILIARY_FILE_BYTES)
        ledger_bytes = safe_read(paths[6], maximum=MAX_AUXILIARY_FILE_BYTES)
        identity_bytes = safe_read(paths[7], maximum=4096)
        attestation = load_strict_json_bytes(attestation_bytes)
        evidence = load_strict_json_bytes(evidence_bytes)
        candidate = load_strict_json_bytes(candidate_bytes)
        preflight = load_strict_json_bytes(preflight_bytes)
        ledger = load_strict_json_bytes(ledger_bytes)
        evaluated_errors: list[str] = []
        evaluated_at = parse_time(argv[9], "evaluated_at", evaluated_errors)
        if evaluated_at is None:
            raise ValueError("invalid evaluated time")
        identity = identity_bytes.decode("utf-8")
        if re.fullmatch(r"[A-Za-z0-9._@+-]{1,256}", identity) is None:
            raise ValueError("invalid signer identity")
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        print(json.dumps(report(["input is invalid"]), sort_keys=True))
        return 1

    bindings = {
        "allowed_signers_file_sha256": sha256_bytes(allowed_signers_bytes),
        "attestation_file_sha256": sha256_bytes(attestation_bytes),
        "evidence_file_sha256": sha256_bytes(evidence_bytes),
        "identity_file_sha256": sha256_bytes(identity_bytes),
        "nonce_snapshot_file_sha256": sha256_bytes(ledger_bytes),
        "signature_file_sha256": sha256_bytes(signature_bytes),
    }
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
    errors.extend(validate_attestation(attestation, evidence, evidence_bytes, identity, evaluated_at))
    errors.extend(validate_nonce_snapshot(ledger, attestation.get("nonce_sha256"), evaluated_at))
    ssh_keygen = shutil.which("ssh-keygen")
    if ssh_keygen is None:
        errors.append("ssh-keygen is unavailable")
    elif not verify_signature(ssh_keygen, paths[5], identity, paths[1], attestation_bytes):
        errors.append("detached signature verification failed")
    errors = sorted(set(errors))
    print(json.dumps(report(errors, bindings, evaluated_at), sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
