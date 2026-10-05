#!/usr/bin/env python3
"""Verify an unattested saved Compose clean-install evidence candidate."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from validate_resolved_compose_candidate import (
    canonical_sha256,
    load_strict_json_bytes,
    validate_candidate,
)
from verify_compose_image_availability_preflight import validate_snapshot


TOP_FIELDS = {
    "kind",
    "version",
    "status",
    "reported_at",
    "candidate_binding",
    "preflight_binding",
    "authorization_binding",
    "reported_effects",
    "service_reports",
    "claims",
    "evidence_candidate_sha256",
    "public_beta",
}
CANDIDATE_FIELDS = {
    "candidate_file_sha256",
    "project_name",
    "resolved_contract_sha256",
    "image_manifest_digest",
}
PREFLIGHT_FIELDS = {
    "preflight_file_sha256",
    "preflight_sha256",
    "daemon_id_sha256",
    "local_image_id_digest",
    "status",
}
AUTHORIZATION_FIELDS = {
    "work_order_sha256",
    "target_locator_sha256",
    "before_state_receipt_sha256",
    "executor_identity_sha256",
    "reviewer_identity_sha256",
    "identities_distinct",
    "protected_attestation_verified",
}
EFFECT_FIELDS = {
    "container_create_reported",
    "container_start_reported",
    "migration_execution_reported",
    "database_smoke_write_reported",
    "image_pull_reported",
    "image_mutation_reported",
    "daemon_configuration_change_reported",
    "credential_values_emitted",
    "raw_command_output_emitted",
    "raw_host_identity_emitted",
    "irreversible_delete_reported",
    "provider_transfer_reported",
}
SERVICE_FIELDS = {
    "service_id",
    "migration_path",
    "migration_sha256",
    "evidence_sha256",
    "positive_checks",
    "negative_checks",
}
POSITIVE_FIELDS = {
    "migration_digest_match_reported",
    "required_tables_present_reported",
    "expected_roles_present_reported",
    "health_query_passed_reported",
    "transaction_write_read_rollback_reported",
}
NEGATIVE_FIELDS = {
    "wrong_role_ddl_denied_reported",
    "wrong_role_write_denied_reported",
    "cross_store_access_denied_reported",
    "public_network_access_denied_reported",
    "dirty_schema_rejected_reported",
}
CLAIM_FIELDS = {
    "execution_authenticity_verified",
    "observation_freshness_verified",
    "observation_atomicity_verified",
    "current_daemon_reachable_verified",
    "current_local_image_available_verified",
    "clean_install_verified",
    "services_started_verified",
    "migrations_verified",
    "database_positive_checks_verified",
    "database_negative_checks_verified",
    "application_least_privilege_verified",
    "restart_verified",
    "rollback_verified",
    "backup_verified",
    "restore_verified",
    "promotion_verified",
    "current_truth_changed",
    "final_human_go",
    "public_beta_go",
}
OUTPUT_TRUE_FIELDS = {
    "evidence_candidate_self_digest_verified",
    "candidate_binding_verified",
    "preflight_binding_verified",
    "reported_check_completeness_verified",
    "role_separation_structure_verified",
}
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
MAX_INPUT_BYTES = 1_048_576
MAX_TOTAL_INPUT_BYTES = 2_097_152


def _plain_metadata(path: Path):
    for component in (path, *path.parents):
        metadata = component.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or getattr(metadata, "st_file_attributes", 0) & 0x400
            or getattr(metadata, "st_reparse_tag", 0)
            or (component != path and not stat.S_ISDIR(metadata.st_mode))
        ):
            raise ValueError("input file is invalid")
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ValueError("input file is invalid")
    return metadata


def _file_snapshot(metadata):
    # Windows pathname ctime can mean creation time. Compare ctime only between
    # snapshots of the same descriptor, not between lstat and fstat.
    return (
        metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_nlink,
        metadata.st_size, metadata.st_mtime_ns,
        getattr(metadata, "st_file_attributes", 0),
        getattr(metadata, "st_reparse_tag", 0),
    )


def read_bounded(path: Path, limit: int) -> bytes:
    """Read a stable selected regular file, at most its remaining byte budget.

    Three local snapshots do not constitute an atomic multi-file observation or
    a hostile-writer sandbox. No execution/freshness claim follows from reading.
    """
    path = path.absolute()
    before = _plain_metadata(path)
    if before.st_size > limit:
        raise ValueError("input file is too large")
    flags = (os.O_RDONLY | getattr(os, "O_BINARY", 0)
             | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if _file_snapshot(before) != _file_snapshot(opened):
            raise ValueError("input file changed")
        chunks, size = [], 0
        while size <= limit:
            chunk = os.read(descriptor, min(65_536, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    final = _plain_metadata(path)
    if (
        size > limit
        or size != opened.st_size
        or opened.st_ctime_ns != after.st_ctime_ns
        or _file_snapshot(opened) != _file_snapshot(after)
        or _file_snapshot(after) != _file_snapshot(final)
    ):
        raise ValueError("input file changed")
    return b"".join(chunks)


def require_exact_fields(
    value: object, expected: set[str], location: str, errors: list[str]
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        errors.append(f"{location} must be an object")
        return None
    for field in sorted(expected - value.keys()):
        errors.append(f"{location} missing required field: {field}")
    if value.keys() - expected:
        errors.append(f"{location} contains unknown fields")
    return value


def valid_time(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def require_sha256(value: object, location: str, errors: list[str]) -> None:
    if not isinstance(value, str) or SHA256_HEX.fullmatch(value) is None:
        errors.append(f"{location} must be lowercase SHA-256")


def evidence_digest(evidence: dict[str, Any]) -> str:
    projection = dict(evidence)
    projection.pop("evidence_candidate_sha256", None)
    return canonical_sha256(projection)


def validate_evidence(
    evidence: dict[str, Any],
    candidate: dict[str, Any],
    candidate_bytes: bytes,
    preflight: dict[str, Any],
    preflight_bytes: bytes,
) -> list[str]:
    errors: list[str] = []
    require_exact_fields(evidence, TOP_FIELDS, "evidence", errors)
    if evidence.get("kind") != "compose_clean_install_migration_evidence_candidate":
        errors.append("kind must be compose_clean_install_migration_evidence_candidate")
    if evidence.get("version") != "1.0":
        errors.append("version must be 1.0")
    if evidence.get("status") != "UNATTESTED_EVIDENCE_CANDIDATE":
        errors.append("status must remain UNATTESTED_EVIDENCE_CANDIDATE")
    if not valid_time(evidence.get("reported_at")):
        errors.append("reported_at must be timezone-aware ISO-8601")

    candidate_binding = require_exact_fields(
        evidence.get("candidate_binding"), CANDIDATE_FIELDS, "candidate_binding", errors
    )
    expected_image = candidate["resolved"]["services"][0]["image_digest"]
    if candidate_binding is not None:
        expected = {
            "candidate_file_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
            "project_name": candidate["project_name"],
            "resolved_contract_sha256": candidate["resolved"]["resolved_contract_sha256"],
            "image_manifest_digest": expected_image,
        }
        if candidate_binding != expected:
            errors.append("candidate binding mismatch")

    preflight_binding = require_exact_fields(
        evidence.get("preflight_binding"), PREFLIGHT_FIELDS, "preflight_binding", errors
    )
    if preflight_binding is not None:
        expected = {
            "preflight_file_sha256": hashlib.sha256(preflight_bytes).hexdigest(),
            "preflight_sha256": preflight["preflight_sha256"],
            "daemon_id_sha256": preflight["host_binding"]["daemon_id_sha256"],
            "local_image_id_digest": preflight["image_observation"]["local_image_id_digest"],
            "status": "LOCAL_IMAGE_AVAILABLE",
        }
        if preflight_binding != expected:
            errors.append("preflight binding mismatch")

    authorization = require_exact_fields(
        evidence.get("authorization_binding"),
        AUTHORIZATION_FIELDS,
        "authorization_binding",
        errors,
    )
    if authorization is not None:
        for field in AUTHORIZATION_FIELDS - {
            "identities_distinct",
            "protected_attestation_verified",
        }:
            require_sha256(authorization.get(field), f"authorization_binding.{field}", errors)
        executor = authorization.get("executor_identity_sha256")
        reviewer = authorization.get("reviewer_identity_sha256")
        if authorization.get("identities_distinct") is not True or executor == reviewer:
            errors.append("executor and reviewer identity bindings must be distinct")
        if authorization.get("protected_attestation_verified") is not False:
            errors.append("protected_attestation_verified must remain false")

    effects = require_exact_fields(
        evidence.get("reported_effects"), EFFECT_FIELDS, "reported_effects", errors
    )
    expected_effects = {
        "container_create_reported": True,
        "container_start_reported": True,
        "migration_execution_reported": True,
        "database_smoke_write_reported": True,
        "image_pull_reported": False,
        "image_mutation_reported": False,
        "daemon_configuration_change_reported": False,
        "credential_values_emitted": False,
        "raw_command_output_emitted": False,
        "raw_host_identity_emitted": False,
        "irreversible_delete_reported": False,
        "provider_transfer_reported": False,
    }
    if effects is not None and effects != expected_effects:
        errors.append("reported effects do not match the bounded evidence-candidate contract")

    service_reports = evidence.get("service_reports")
    services = candidate["resolved"]["services"]
    if not isinstance(service_reports, list) or len(service_reports) != 2:
        errors.append("service_reports must contain exactly two ordered services")
    else:
        evidence_digests: list[object] = []
        for index, report in enumerate(service_reports):
            item = require_exact_fields(report, SERVICE_FIELDS, f"service_reports[{index}]", errors)
            if item is None:
                continue
            service = services[index]
            if item.get("service_id") != service["id"]:
                errors.append(f"service_reports[{index}].service_id is not role bound")
            if item.get("migration_path") != service["migration"]:
                errors.append(f"service_reports[{index}].migration_path is not candidate bound")
            if item.get("migration_sha256") != service["migration_sha256"]:
                errors.append(f"service_reports[{index}].migration_sha256 is not candidate bound")
            require_sha256(
                item.get("evidence_sha256"),
                f"service_reports[{index}].evidence_sha256",
                errors,
            )
            evidence_digests.append(item.get("evidence_sha256"))
            positive = require_exact_fields(
                item.get("positive_checks"), POSITIVE_FIELDS, f"service_reports[{index}].positive_checks", errors
            )
            if positive is not None and any(
                positive.get(field) is not True for field in POSITIVE_FIELDS
            ):
                errors.append(f"service_reports[{index}] positive checks must all be reported true")
            negative = require_exact_fields(
                item.get("negative_checks"), NEGATIVE_FIELDS, f"service_reports[{index}].negative_checks", errors
            )
            if negative is not None and any(
                negative.get(field) is not True for field in NEGATIVE_FIELDS
            ):
                errors.append(f"service_reports[{index}] negative checks must all be reported true")
        if len(evidence_digests) == 2 and evidence_digests[0] == evidence_digests[1]:
            errors.append("service evidence digests must be distinct")

    claims = require_exact_fields(evidence.get("claims"), CLAIM_FIELDS, "claims", errors)
    if claims is not None:
        for field in CLAIM_FIELDS:
            if claims.get(field) is not False:
                errors.append(f"claim {field} must remain false")
    digest = evidence.get("evidence_candidate_sha256")
    require_sha256(digest, "evidence_candidate_sha256", errors)
    if isinstance(digest, str) and SHA256_HEX.fullmatch(digest) and digest != evidence_digest(evidence):
        errors.append("evidence candidate self-digest mismatch")
    if evidence.get("public_beta") != "NO_GO_UNPUBLISHED":
        errors.append("public_beta must remain NO_GO_UNPUBLISHED")
    return sorted(set(errors))


def validation_report(errors: list[str]) -> dict[str, Any]:
    valid = not errors
    claims = {field: False for field in sorted(CLAIM_FIELDS)}
    claims.update({field: valid for field in sorted(OUTPUT_TRUE_FIELDS)})
    return {
        "kind": "compose_clean_install_migration_evidence_validation",
        "version": "1.0",
        "status": "UNATTESTED_EVIDENCE_BINDING_ONLY" if valid else "INVALID",
        "errors": errors,
        "claims": dict(sorted(claims.items())),
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(
            "usage: verify_compose_clean_install_migration_evidence_candidate.py "
            "EVIDENCE_JSON RESOLVED_CANDIDATE_JSON IMAGE_PREFLIGHT_JSON",
            file=sys.stderr,
        )
        return 2
    try:
        inputs = []
        remaining = MAX_TOTAL_INPUT_BYTES
        for argument in argv[1:]:
            raw = read_bounded(Path(argument), min(MAX_INPUT_BYTES, remaining))
            inputs.append(raw)
            remaining -= len(raw)
        evidence_bytes, candidate_bytes, preflight_bytes = inputs
        evidence = load_strict_json_bytes(evidence_bytes)
        candidate = load_strict_json_bytes(candidate_bytes)
        preflight = load_strict_json_bytes(preflight_bytes)
        candidate_errors = validate_candidate(candidate)
        snapshot_errors = (
            ["resolved candidate is invalid"]
            if candidate_errors
            else validate_snapshot(preflight, candidate, candidate_bytes)
        )
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        print(json.dumps(validation_report(["input JSON is invalid"]), sort_keys=True))
        return 1
    if candidate_errors:
        errors = ["resolved candidate is invalid"]
    elif snapshot_errors:
        errors = ["image preflight is invalid"]
    else:
        errors = validate_evidence(
            evidence, candidate, candidate_bytes, preflight, preflight_bytes
        )
    print(json.dumps(validation_report(errors), sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
