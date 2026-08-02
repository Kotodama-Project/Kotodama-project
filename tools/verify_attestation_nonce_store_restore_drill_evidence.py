#!/usr/bin/env python3
"""Verify signed reported restore-drill evidence against exact private reports."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from validate_resolved_compose_candidate import load_strict_json_bytes
from verify_attestation_nonce_store_checkpoint_chain import (
    ALWAYS_FALSE_FIELDS as CHAIN_FALSE_FIELDS,
    SUCCESS_FIELDS as CHAIN_SUCCESS_FIELDS,
)
from verify_attestation_nonce_store_checkpoint_head_anchor import (
    ALWAYS_FALSE_FIELDS as ANCHOR_FALSE_FIELDS,
    SUCCESS_FIELDS as ANCHOR_SUCCESS_FIELDS,
    parse_time,
    require_exact_fields,
    require_sha256,
    verify_signature_with_pinned_binary,
)
from verify_protected_compose_evidence_attestation import safe_read, sha256_bytes


NAMESPACE = "kotodama-nonce-store-restore-drill"
MAX_INPUT_BYTES = 1024 * 1024
MAX_SIGNATURE_BYTES = 64 * 1024
MAX_IDENTITY_BYTES = 4096
MAX_SIGNED_WINDOW_SECONDS = 900
MAX_REPORT_LAG_SECONDS = 300
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
EVIDENCE_FIELDS = {
    "kind",
    "version",
    "status",
    "namespace",
    "drill_id_sha256",
    "reported_started_at",
    "reported_completed_at",
    "issued_at",
    "expires_at",
    "anchor_binding",
    "source_verification_binding",
    "restored_verification_binding",
    "operation_receipts",
    "reported_checks",
    "signature_policy_binding",
    "runner_identity_sha256",
    "identities_distinct",
    "claims",
    "public_beta",
}
ANCHOR_BINDING_FIELDS = {
    "report_file_sha256",
    "anchor_id_sha256",
    "anchor_file_sha256",
    "bundle_file_sha256",
    "current_checkpoint_sha256",
    "store_id_sha256",
    "checkpoint_count",
}
CHAIN_BINDING_FIELDS = {
    "report_file_sha256",
    "bundle_file_sha256",
    "current_checkpoint_sha256",
    "store_id_sha256",
    "checkpoints_verified",
    "reservations_at_current",
}
OPERATION_RECEIPT_FIELDS = {
    "backup_receipt_file_sha256",
    "restore_receipt_file_sha256",
    "backup_artifact_sha256",
}
REPORTED_CHECK_FIELDS = {
    "backup_command_completed_reported",
    "backup_artifact_digest_match_reported",
    "restore_command_completed_reported",
    "restored_store_opened_reported",
    "restored_store_chain_equivalence_reported",
    "source_store_remained_unmodified_reported",
    "private_data_not_published_reported",
}
SIGNATURE_POLICY_FIELDS = {
    "allowed_signers_file_sha256",
    "signer_identity_file_sha256",
    "signer_role",
}
SUCCESS_FIELDS = {
    "evidence_file_digest_match_verified",
    "anchor_verification_report_shape_verified",
    "source_chain_verification_report_shape_verified",
    "restored_chain_verification_report_shape_verified",
    "same_checkpoint_state_verified",
    "distinct_report_files_verified",
    "operation_receipt_digests_verified",
    "reported_check_completeness_verified",
    "runner_reviewer_hash_distinct_verified",
    "evidence_signature_verified",
    "allowed_signer_verified",
    "signer_identity_binding_verified",
    "signer_role_policy_verified",
    "signed_evaluation_window_verified",
    "ssh_keygen_binary_binding_verified",
}
ALWAYS_FALSE_FIELDS = {
    "anchor_report_authenticity_verified",
    "chain_report_authenticity_verified",
    "external_anchor_authority_verified",
    "trusted_clock_source_verified",
    "authoritative_complete_history_verified",
    "parallel_branch_absence_verified",
    "backup_artifact_verified",
    "backup_execution_verified",
    "restore_execution_verified",
    "physical_store_lineage_verified",
    "protected_runner_execution_verified",
    "runner_reviewer_person_separation_verified",
    "store_continuity_verified",
    "promotion_verified",
    "current_truth_changed",
    "final_human_go",
    "public_beta_go",
    "ssh_keygen_vendor_authority_verified",
}
ANCHOR_REPORT_FIELDS = {
    "kind",
    "version",
    "status",
    "errors",
    "evaluated_at",
    "clock_source",
    "input_bindings",
    "counts",
    "claims",
    "public_beta",
}
ANCHOR_REPORT_BINDINGS = {
    "allowed_signers_file_sha256",
    "anchor_file_sha256",
    "anchor_id_sha256",
    "anchor_signature_file_sha256",
    "bundle_file_sha256",
    "current_checkpoint_sha256",
    "identity_file_sha256",
    "ssh_keygen_executable_sha256",
    "store_id_sha256",
}
CHAIN_REPORT_FIELDS = {
    "kind",
    "version",
    "status",
    "errors",
    "verified_at",
    "clock_source",
    "input_bindings",
    "counts",
    "claims",
    "public_beta",
}
CHAIN_REPORT_BINDINGS = {
    "allowed_signers_file_sha256",
    "bundle_file_sha256",
    "identity_file_sha256",
    "store_id_sha256",
    "genesis_checkpoint_sha256",
    "current_checkpoint_sha256",
    "ssh_keygen_executable_sha256",
}


def strict_positive_int(
    value: object,
    location: str,
    errors: list[str],
    *,
    maximum: int | None = None,
) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        errors.append(f"{location} must be a positive integer")
        return None
    if maximum is not None and value > maximum:
        errors.append(f"{location} exceeds maximum {maximum}")
        return None
    return value


def strict_nonnegative_int(
    value: object,
    location: str,
    errors: list[str],
    *,
    maximum: int | None = None,
) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        errors.append(f"{location} must be a nonnegative integer")
        return None
    if maximum is not None and value > maximum:
        errors.append(f"{location} exceeds maximum {maximum}")
        return None
    return value


def sha_value(value: object) -> str | None:
    return value if isinstance(value, str) and SHA256_HEX.fullmatch(value) else None


def validate_anchor_report(report_value: object, errors: list[str]) -> dict[str, Any]:
    report = require_exact_fields(
        report_value, ANCHOR_REPORT_FIELDS, "anchor report", errors
    )
    if report is None:
        return {}
    if report.get("kind") != "attestation_nonce_store_checkpoint_head_anchor_verification":
        errors.append("anchor report kind is invalid")
    if report.get("version") != "1.0":
        errors.append("anchor report version must be 1.0")
    if report.get("status") != "SIGNED_CHECKPOINT_HEAD_ANCHOR_MATCH":
        errors.append("anchor report status is not successful")
    if report.get("errors") != []:
        errors.append("anchor report errors must be empty")
    parse_time(report.get("evaluated_at"), "anchor report evaluated_at", errors)
    if report.get("clock_source") != "supplied_evaluation_time_untrusted":
        errors.append("anchor report clock source is invalid")
    bindings = require_exact_fields(
        report.get("input_bindings"),
        ANCHOR_REPORT_BINDINGS,
        "anchor report input_bindings",
        errors,
    )
    safe_bindings: dict[str, str] = {}
    if bindings is not None:
        for field in ANCHOR_REPORT_BINDINGS:
            require_sha256(
                bindings.get(field), f"anchor report input_bindings.{field}", errors
            )
            value = sha_value(bindings.get(field))
            if value is not None:
                safe_bindings[field] = value
    counts = require_exact_fields(
        report.get("counts"),
        {"checkpoints_bound"},
        "anchor report counts",
        errors,
    )
    checkpoint_count = None
    if counts is not None:
        checkpoint_count = strict_positive_int(
            counts.get("checkpoints_bound"),
            "anchor report counts.checkpoints_bound",
            errors,
            maximum=1024,
        )
    claims = require_exact_fields(
        report.get("claims"),
        ANCHOR_SUCCESS_FIELDS | ANCHOR_FALSE_FIELDS,
        "anchor report claims",
        errors,
    )
    if claims is not None:
        for field in ANCHOR_SUCCESS_FIELDS:
            if claims.get(field) is not True:
                errors.append(f"anchor report claim {field} must be true")
        for field in ANCHOR_FALSE_FIELDS:
            if claims.get(field) is not False:
                errors.append(f"anchor report claim {field} must be false")
    if report.get("public_beta") != "NO_GO_UNPUBLISHED":
        errors.append("anchor report public_beta must remain NO_GO_UNPUBLISHED")
    if checkpoint_count is not None:
        safe_bindings["checkpoint_count"] = checkpoint_count
    return safe_bindings


def validate_chain_report(
    report_value: object, location: str, errors: list[str]
) -> dict[str, Any]:
    report = require_exact_fields(report_value, CHAIN_REPORT_FIELDS, location, errors)
    if report is None:
        return {}
    if report.get("kind") != "attestation_nonce_store_checkpoint_chain_verification":
        errors.append(f"{location} kind is invalid")
    if report.get("version") != "1.0":
        errors.append(f"{location} version must be 1.0")
    if report.get("status") != "SIGNED_RECURSIVE_CHAIN_AND_STORE_EQUIVALENCE":
        errors.append(f"{location} status is not successful")
    if report.get("errors") != []:
        errors.append(f"{location} errors must be empty")
    parse_time(report.get("verified_at"), f"{location} verified_at", errors)
    if report.get("clock_source") != "local_system_utc_untrusted":
        errors.append(f"{location} clock source is invalid")
    bindings = require_exact_fields(
        report.get("input_bindings"),
        CHAIN_REPORT_BINDINGS,
        f"{location} input_bindings",
        errors,
    )
    safe_bindings: dict[str, Any] = {}
    if bindings is not None:
        for field in CHAIN_REPORT_BINDINGS:
            require_sha256(bindings.get(field), f"{location}.{field}", errors)
            value = sha_value(bindings.get(field))
            if value is not None:
                safe_bindings[field] = value
    counts = require_exact_fields(
        report.get("counts"),
        {
            "checkpoints_verified",
            "parent_links_verified",
            "reservations_at_current",
        },
        f"{location} counts",
        errors,
    )
    if counts is not None:
        checkpoints = strict_positive_int(
            counts.get("checkpoints_verified"),
            f"{location} counts.checkpoints_verified",
            errors,
            maximum=1024,
        )
        links = strict_nonnegative_int(
            counts.get("parent_links_verified"),
            f"{location} counts.parent_links_verified",
            errors,
            maximum=1023,
        )
        reservations = strict_nonnegative_int(
            counts.get("reservations_at_current"),
            f"{location} counts.reservations_at_current",
            errors,
            maximum=10000,
        )
        if checkpoints is not None:
            safe_bindings["checkpoints_verified"] = checkpoints
        if reservations is not None:
            safe_bindings["reservations_at_current"] = reservations
        if checkpoints is not None and links is not None and links != checkpoints - 1:
            errors.append(f"{location} parent link count is inconsistent")
    claims = require_exact_fields(
        report.get("claims"),
        CHAIN_SUCCESS_FIELDS | CHAIN_FALSE_FIELDS,
        f"{location} claims",
        errors,
    )
    if claims is not None:
        for field in CHAIN_SUCCESS_FIELDS:
            if claims.get(field) is not True:
                errors.append(f"{location} claim {field} must be true")
        for field in CHAIN_FALSE_FIELDS:
            if claims.get(field) is not False:
                errors.append(f"{location} claim {field} must be false")
    if report.get("public_beta") != "NO_GO_UNPUBLISHED":
        errors.append(f"{location} public_beta must remain NO_GO_UNPUBLISHED")
    return safe_bindings


def validate_evidence(
    evidence_value: object,
    *,
    evidence_bytes: bytes,
    expected_evidence_sha256: str,
    anchor_report_sha256: str,
    source_report_sha256: str,
    restored_report_sha256: str,
    backup_receipt_sha256: str,
    restore_receipt_sha256: str,
    allowed_signers_bytes: bytes,
    identity_bytes: bytes,
    evaluated_at: datetime,
    anchor_info: dict[str, Any],
    source_info: dict[str, Any],
    restored_info: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    evidence = require_exact_fields(
        evidence_value, EVIDENCE_FIELDS, "evidence", errors
    )
    if evidence is None:
        return errors
    if evidence.get("kind") != "attestation_nonce_store_restore_drill_evidence":
        errors.append("evidence kind is invalid")
    if evidence.get("version") != "1.0":
        errors.append("evidence version must be 1.0")
    if evidence.get("status") != "RESTORE_DRILL_EVIDENCE_CANDIDATE":
        errors.append("evidence status must remain RESTORE_DRILL_EVIDENCE_CANDIDATE")
    if evidence.get("namespace") != NAMESPACE:
        errors.append(f"namespace must be {NAMESPACE}")
    require_sha256(evidence.get("drill_id_sha256"), "drill_id_sha256", errors)
    if (
        SHA256_HEX.fullmatch(expected_evidence_sha256) is None
        or expected_evidence_sha256 != sha256_bytes(evidence_bytes)
    ):
        errors.append("supplied evidence digest mismatch")

    anchor_binding = require_exact_fields(
        evidence.get("anchor_binding"),
        ANCHOR_BINDING_FIELDS,
        "anchor_binding",
        errors,
    )
    if anchor_binding is not None:
        for field in ANCHOR_BINDING_FIELDS - {"checkpoint_count"}:
            require_sha256(anchor_binding.get(field), f"anchor_binding.{field}", errors)
        strict_positive_int(
            anchor_binding.get("checkpoint_count"),
            "anchor_binding.checkpoint_count",
            errors,
            maximum=1024,
        )
        expected_anchor = {
            "report_file_sha256": anchor_report_sha256,
            "anchor_id_sha256": anchor_info.get("anchor_id_sha256"),
            "anchor_file_sha256": anchor_info.get("anchor_file_sha256"),
            "bundle_file_sha256": anchor_info.get("bundle_file_sha256"),
            "current_checkpoint_sha256": anchor_info.get(
                "current_checkpoint_sha256"
            ),
            "store_id_sha256": anchor_info.get("store_id_sha256"),
            "checkpoint_count": anchor_info.get("checkpoint_count"),
        }
        if anchor_binding != expected_anchor:
            errors.append("anchor report binding mismatch")

    def check_chain_binding(
        field: str,
        report_sha256: str,
        report_info: dict[str, Any],
    ) -> dict[str, Any] | None:
        binding = require_exact_fields(
            evidence.get(field), CHAIN_BINDING_FIELDS, field, errors
        )
        if binding is None:
            return None
        for name in CHAIN_BINDING_FIELDS - {
            "checkpoints_verified",
            "reservations_at_current",
        }:
            require_sha256(binding.get(name), f"{field}.{name}", errors)
        strict_positive_int(
            binding.get("checkpoints_verified"),
            f"{field}.checkpoints_verified",
            errors,
            maximum=1024,
        )
        strict_nonnegative_int(
            binding.get("reservations_at_current"),
            f"{field}.reservations_at_current",
            errors,
            maximum=10000,
        )
        expected = {
            "report_file_sha256": report_sha256,
            "bundle_file_sha256": report_info.get("bundle_file_sha256"),
            "current_checkpoint_sha256": report_info.get(
                "current_checkpoint_sha256"
            ),
            "store_id_sha256": report_info.get("store_id_sha256"),
            "checkpoints_verified": report_info.get("checkpoints_verified"),
            "reservations_at_current": report_info.get("reservations_at_current"),
        }
        if binding != expected:
            errors.append(f"{field} does not match its report")
        return binding

    source_binding = check_chain_binding(
        "source_verification_binding", source_report_sha256, source_info
    )
    restored_binding = check_chain_binding(
        "restored_verification_binding", restored_report_sha256, restored_info
    )
    if source_report_sha256 == restored_report_sha256:
        errors.append("source and restored report files must be distinct")
    if source_binding is not None and restored_binding is not None:
        state_fields = CHAIN_BINDING_FIELDS - {"report_file_sha256"}
        if any(source_binding.get(name) != restored_binding.get(name) for name in state_fields):
            errors.append("source and restored checkpoint state mismatch")
        if anchor_binding is not None:
            for name in (
                "bundle_file_sha256",
                "current_checkpoint_sha256",
                "store_id_sha256",
            ):
                if anchor_binding.get(name) != source_binding.get(name):
                    errors.append("anchor and chain report state mismatch")
            if anchor_binding.get("checkpoint_count") != source_binding.get(
                "checkpoints_verified"
            ):
                errors.append("anchor and chain checkpoint count mismatch")

    receipts = require_exact_fields(
        evidence.get("operation_receipts"),
        OPERATION_RECEIPT_FIELDS,
        "operation_receipts",
        errors,
    )
    if receipts is not None:
        for field in OPERATION_RECEIPT_FIELDS:
            require_sha256(receipts.get(field), f"operation_receipts.{field}", errors)
        if receipts.get("backup_receipt_file_sha256") != backup_receipt_sha256:
            errors.append("backup receipt digest mismatch")
        if receipts.get("restore_receipt_file_sha256") != restore_receipt_sha256:
            errors.append("restore receipt digest mismatch")
        if backup_receipt_sha256 == restore_receipt_sha256:
            errors.append("backup and restore receipts must be distinct")

    checks = require_exact_fields(
        evidence.get("reported_checks"),
        REPORTED_CHECK_FIELDS,
        "reported_checks",
        errors,
    )
    if checks is not None:
        for field in REPORTED_CHECK_FIELDS:
            if checks.get(field) is not True:
                errors.append(f"reported check {field} must be true")

    policy = require_exact_fields(
        evidence.get("signature_policy_binding"),
        SIGNATURE_POLICY_FIELDS,
        "signature_policy_binding",
        errors,
    )
    reviewer_identity_sha256 = sha256_bytes(identity_bytes)
    if policy is not None:
        for field in (
            "allowed_signers_file_sha256",
            "signer_identity_file_sha256",
        ):
            require_sha256(policy.get(field), f"signature_policy_binding.{field}", errors)
        if policy.get("allowed_signers_file_sha256") != sha256_bytes(
            allowed_signers_bytes
        ):
            errors.append("allowed signers binding mismatch")
        if policy.get("signer_identity_file_sha256") != reviewer_identity_sha256:
            errors.append("signer identity binding mismatch")
        if policy.get("signer_role") != "independent_restore_reviewer":
            errors.append("signer role must be independent_restore_reviewer")
    runner_identity = evidence.get("runner_identity_sha256")
    require_sha256(runner_identity, "runner_identity_sha256", errors)
    if evidence.get("identities_distinct") is not True:
        errors.append("identities_distinct must be true")
    if runner_identity == reviewer_identity_sha256:
        errors.append("runner and reviewer identity hashes must be distinct")

    claims = require_exact_fields(
        evidence.get("claims"), ALWAYS_FALSE_FIELDS, "claims", errors
    )
    if claims is not None:
        for field in ALWAYS_FALSE_FIELDS:
            if claims.get(field) is not False:
                errors.append(f"claim {field} must remain false")
    if evidence.get("public_beta") != "NO_GO_UNPUBLISHED":
        errors.append("public_beta must remain NO_GO_UNPUBLISHED")

    started_at = parse_time(
        evidence.get("reported_started_at"), "reported_started_at", errors
    )
    completed_at = parse_time(
        evidence.get("reported_completed_at"), "reported_completed_at", errors
    )
    issued_at = parse_time(evidence.get("issued_at"), "issued_at", errors)
    expires_at = parse_time(evidence.get("expires_at"), "expires_at", errors)
    if started_at is not None and completed_at is not None and completed_at < started_at:
        errors.append("reported completion precedes reported start")
    if completed_at is not None and issued_at is not None:
        lag = (issued_at - completed_at).total_seconds()
        if lag < 0:
            errors.append("evidence was issued before reported completion")
        if lag > MAX_REPORT_LAG_SECONDS:
            errors.append("evidence issuance exceeds 300 seconds after completion")
    if issued_at is not None and expires_at is not None:
        window = (expires_at - issued_at).total_seconds()
        if window <= 0:
            errors.append("signed window must have positive duration")
        if window > MAX_SIGNED_WINDOW_SECONDS:
            errors.append("signed window exceeds 900 seconds")
        if not issued_at <= evaluated_at <= expires_at:
            errors.append("evaluation time is outside the signed window")
    return sorted(set(errors))


def make_report(
    status: str,
    errors: list[str],
    *,
    evaluated_at: datetime | None = None,
    bindings: dict[str, str] | None = None,
    checkpoints: int = 0,
    reservations: int = 0,
    reported_checks: int = 0,
) -> dict[str, Any]:
    claims = {name: False for name in sorted(SUCCESS_FIELDS | ALWAYS_FALSE_FIELDS)}
    if status == "SIGNED_RESTORE_DRILL_REPORT_BINDING":
        for name in SUCCESS_FIELDS:
            claims[name] = True
    return {
        "kind": "attestation_nonce_store_restore_drill_evidence_verification",
        "version": "1.0",
        "status": status,
        "errors": errors,
        "evaluated_at": (
            evaluated_at.isoformat().replace("+00:00", "Z")
            if evaluated_at is not None
            else None
        ),
        "clock_source": "supplied_evaluation_time_untrusted",
        "input_bindings": dict(sorted((bindings or {}).items())),
        "counts": {
            "checkpoints_bound": checkpoints,
            "reservations_bound": reservations,
            "reported_checks_bound": reported_checks,
        },
        "claims": claims,
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 13:
        print(
            "usage: verify_attestation_nonce_store_restore_drill_evidence.py "
            "EVIDENCE_JSON EVIDENCE_SIGNATURE EXPECTED_EVIDENCE_SHA256 "
            "ANCHOR_REPORT_JSON SOURCE_CHAIN_REPORT_JSON "
            "RESTORED_CHAIN_REPORT_JSON BACKUP_RECEIPT RESTORE_RECEIPT "
            "ALLOWED_SIGNERS_FILE SIGNER_IDENTITY_FILE "
            "EXPECTED_SSH_KEYGEN_SHA256 EVALUATED_AT_ISO8601",
            file=sys.stderr,
        )
        return 2
    try:
        evidence_bytes = safe_read(Path(argv[1]), maximum=MAX_INPUT_BYTES)
        signature_bytes = safe_read(Path(argv[2]), maximum=MAX_SIGNATURE_BYTES)
        anchor_report_bytes = safe_read(Path(argv[4]), maximum=MAX_INPUT_BYTES)
        source_report_bytes = safe_read(Path(argv[5]), maximum=MAX_INPUT_BYTES)
        restored_report_bytes = safe_read(Path(argv[6]), maximum=MAX_INPUT_BYTES)
        backup_receipt_bytes = safe_read(Path(argv[7]), maximum=MAX_INPUT_BYTES)
        restore_receipt_bytes = safe_read(Path(argv[8]), maximum=MAX_INPUT_BYTES)
        allowed_signers_bytes = safe_read(Path(argv[9]), maximum=MAX_INPUT_BYTES)
        identity_bytes = safe_read(Path(argv[10]), maximum=MAX_IDENTITY_BYTES)
        identity = identity_bytes.decode("utf-8")
        if re.fullmatch(r"[A-Za-z0-9._@+-]{1,256}", identity) is None:
            raise ValueError
        time_errors: list[str] = []
        evaluated_at = parse_time(argv[12], "evaluated_at", time_errors)
        if time_errors or evaluated_at is None:
            raise ValueError
        evidence = load_strict_json_bytes(evidence_bytes)
        anchor_report = load_strict_json_bytes(anchor_report_bytes)
        source_report = load_strict_json_bytes(source_report_bytes)
        restored_report = load_strict_json_bytes(restored_report_bytes)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        RecursionError,
        TypeError,
        ValueError,
    ):
        print(json.dumps(make_report("INVALID", ["input is invalid"]), sort_keys=True))
        return 1

    report_errors: list[str] = []
    anchor_info = validate_anchor_report(anchor_report, report_errors)
    source_info = validate_chain_report(source_report, "source report", report_errors)
    restored_info = validate_chain_report(
        restored_report, "restored report", report_errors
    )
    errors = validate_evidence(
        evidence,
        evidence_bytes=evidence_bytes,
        expected_evidence_sha256=argv[3],
        anchor_report_sha256=sha256_bytes(anchor_report_bytes),
        source_report_sha256=sha256_bytes(source_report_bytes),
        restored_report_sha256=sha256_bytes(restored_report_bytes),
        backup_receipt_sha256=sha256_bytes(backup_receipt_bytes),
        restore_receipt_sha256=sha256_bytes(restore_receipt_bytes),
        allowed_signers_bytes=allowed_signers_bytes,
        identity_bytes=identity_bytes,
        evaluated_at=evaluated_at,
        anchor_info=anchor_info,
        source_info=source_info,
        restored_info=restored_info,
    )
    errors.extend(report_errors)
    executable_sha256, signature_valid, signature_errors = (
        verify_signature_with_pinned_binary(
            expected_ssh_keygen_sha256=argv[11],
            allowed_signers_bytes=allowed_signers_bytes,
            identity=identity,
            signature_bytes=signature_bytes,
            document_bytes=evidence_bytes,
            namespace=NAMESPACE,
            error_label="restore evidence signature verification failed",
        )
    )
    errors.extend(signature_errors)
    errors = sorted(set(errors))
    bindings = {
        "allowed_signers_file_sha256": sha256_bytes(allowed_signers_bytes),
        "anchor_report_file_sha256": sha256_bytes(anchor_report_bytes),
        "backup_receipt_file_sha256": sha256_bytes(backup_receipt_bytes),
        "evidence_file_sha256": sha256_bytes(evidence_bytes),
        "evidence_signature_file_sha256": sha256_bytes(signature_bytes),
        "identity_file_sha256": sha256_bytes(identity_bytes),
        "restore_receipt_file_sha256": sha256_bytes(restore_receipt_bytes),
        "restored_report_file_sha256": sha256_bytes(restored_report_bytes),
        "source_report_file_sha256": sha256_bytes(source_report_bytes),
    }
    if executable_sha256 is not None:
        bindings["ssh_keygen_executable_sha256"] = executable_sha256
    evidence_dict = evidence if isinstance(evidence, dict) else {}
    for name in ("drill_id_sha256", "runner_identity_sha256"):
        value = sha_value(evidence_dict.get(name))
        if value is not None:
            bindings[name] = value
    for name in (
        "bundle_file_sha256",
        "current_checkpoint_sha256",
        "store_id_sha256",
    ):
        value = sha_value(source_info.get(name))
        if value is not None:
            bindings[name] = value
    receipts = evidence_dict.get("operation_receipts")
    if isinstance(receipts, dict):
        artifact = sha_value(receipts.get("backup_artifact_sha256"))
        if artifact is not None:
            bindings["backup_artifact_sha256"] = artifact
    if errors or not signature_valid:
        print(
            json.dumps(
                make_report(
                    "INVALID",
                    errors or ["restore evidence signature verification failed"],
                    evaluated_at=evaluated_at,
                    bindings=bindings,
                ),
                sort_keys=True,
            )
        )
        return 1
    print(
        json.dumps(
            make_report(
                "SIGNED_RESTORE_DRILL_REPORT_BINDING",
                [],
                evaluated_at=evaluated_at,
                bindings=bindings,
                checkpoints=source_info["checkpoints_verified"],
                reservations=source_info["reservations_at_current"],
                reported_checks=len(REPORTED_CHECK_FIELDS),
            ),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
