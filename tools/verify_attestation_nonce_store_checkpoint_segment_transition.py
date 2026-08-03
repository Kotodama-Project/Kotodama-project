#!/usr/bin/env python3
"""Verify one signed checkpoint segment boundary and optional key rotation."""

from __future__ import annotations

import base64
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from create_attestation_nonce_store_checkpoint import (
    MAX_CHECKPOINT_BYTES,
    hold_store_snapshot,
    validate_checkpoint,
)
from create_attestation_nonce_store_checkpoint_chain_bundle import (
    MAX_BUNDLE_BYTES,
    chain_from_bundle,
)
from validate_resolved_compose_candidate import load_strict_json_bytes
from verify_protected_compose_evidence_attestation import safe_read, sha256_bytes


NAMESPACE = "kotodama-nonce-store-checkpoint-segment-transition"
CHECKPOINT_NAMESPACE = "kotodama-nonce-store-checkpoint"
MAX_TRANSITION_BYTES = 1024 * 1024
MAX_SIGNATURE_BYTES = 64 * 1024
MAX_ALLOWED_SIGNERS_BYTES = 1024 * 1024
MAX_IDENTITY_BYTES = 4096
MAX_SSH_KEYGEN_BYTES = 16 * 1024 * 1024
MAX_SIGNED_WINDOW_SECONDS = 900
MAX_SIGNATURE_SECONDS = 30
MAX_TOTAL_SIGNATURE_SECONDS = 180
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
IDENTITY = re.compile(r"^[A-Za-z0-9._@+-]{1,256}$")
RFC3339 = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
TRANSITION_MODES = {
    "KEY_ROTATION_SEGMENT",
    "SAME_POLICY_SEGMENT",
}
TRANSITION_FIELDS = {
    "kind",
    "version",
    "status",
    "namespace",
    "transition_id_sha256",
    "transition_mode",
    "issued_at",
    "expires_at",
    "prior_segment_binding",
    "successor_checkpoint_binding",
    "reviewer_policy_binding",
    "claims",
    "public_beta",
}
PRIOR_BINDING_FIELDS = {
    "bundle_file_sha256",
    "current_checkpoint_sha256",
    "current_checkpoint_chain_sha256",
    "store_id_sha256",
    "checkpoint_count",
    "allowed_signers_file_sha256",
    "signer_identity_file_sha256",
}
SUCCESSOR_BINDING_FIELDS = {
    "checkpoint_file_sha256",
    "checkpoint_signature_file_sha256",
    "checkpoint_chain_sha256",
    "store_id_sha256",
    "reservation_count",
    "allowed_signers_file_sha256",
    "signer_identity_file_sha256",
}
REVIEWER_POLICY_FIELDS = {
    "allowed_signers_file_sha256",
    "signer_identity_file_sha256",
    "signer_role",
}
COMMON_SUCCESS_FIELDS = {
    "transition_file_digest_match_verified",
    "prior_bundle_digest_match_verified",
    "prior_bundle_structure_verified",
    "prior_checkpoint_signatures_verified",
    "prior_head_binding_verified",
    "successor_checkpoint_digest_match_verified",
    "successor_checkpoint_signature_verified",
    "parent_link_verified",
    "store_identity_continuity_verified",
    "reservation_append_only_verified",
    "successor_store_match_verified",
    "transition_signature_verified",
    "prior_signer_policy_verified",
    "successor_signer_policy_verified",
    "transition_reviewer_policy_verified",
    "signer_policy_mode_verified",
    "checkpoint_segment_boundary_verified",
    "signed_evaluation_window_verified",
    "ssh_keygen_binary_binding_verified",
}
MODE_SUCCESS_FIELDS = {
    "key_rotation_transition_binding_verified",
    "same_policy_segmentation_binding_verified",
}
ALWAYS_FALSE_FIELDS = {
    "canonical_anchor_authority_verified",
    "trusted_clock_source_verified",
    "authoritative_complete_history_verified",
    "parallel_branch_absence_verified",
    "old_key_revocation_verified",
    "key_compromise_absence_verified",
    "segmentation_policy_adopted",
    "actual_store_continuity_verified",
    "backup_creation_verified",
    "restore_execution_verified",
    "protected_runner_execution_verified",
    "signer_reviewer_person_independence_verified",
    "promotion_verified",
    "current_truth_changed",
    "final_human_go",
    "public_beta_go",
    "ssh_keygen_vendor_authority_verified",
}


@dataclass(frozen=True)
class SegmentPolicyInputs:
    prior_allowed_signers: bytes
    prior_identity: bytes
    successor_allowed_signers: bytes
    successor_identity: bytes
    reviewer_allowed_signers: bytes
    reviewer_identity: bytes


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


def require_sha256(value: object, location: str, errors: list[str]) -> None:
    if not isinstance(value, str) or SHA256_HEX.fullmatch(value) is None:
        errors.append(f"{location} must be lowercase SHA-256")


def require_positive_int(value: object, location: str, errors: list[str]) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        errors.append(f"{location} must be a positive integer")


def require_nonnegative_int(value: object, location: str, errors: list[str]) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        errors.append(f"{location} must be a non-negative integer")


def parse_time(value: object, location: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str):
        errors.append(f"{location} must be timezone-aware ISO-8601")
        return None
    if len(value) > 64:
        errors.append(f"{location} exceeds 64 characters")
        return None
    if RFC3339.fullmatch(value) is None:
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


def expected_prior_binding(
    bundle_bytes: bytes,
    chain: list[dict[str, Any]],
    allowed_signers_bytes: bytes,
    identity_bytes: bytes,
) -> dict[str, object]:
    head = chain[-1]
    checkpoint = head["checkpoint"]
    return {
        "bundle_file_sha256": sha256_bytes(bundle_bytes),
        "current_checkpoint_sha256": head["checkpoint_file_sha256"],
        "current_checkpoint_chain_sha256": checkpoint["checkpoint_chain_sha256"],
        "store_id_sha256": checkpoint["store_binding"]["store_id_sha256"],
        "checkpoint_count": len(chain),
        "allowed_signers_file_sha256": sha256_bytes(allowed_signers_bytes),
        "signer_identity_file_sha256": sha256_bytes(identity_bytes),
    }


def expected_successor_binding(
    checkpoint_bytes: bytes,
    signature_bytes: bytes,
    checkpoint: dict[str, Any],
    allowed_signers_bytes: bytes,
    identity_bytes: bytes,
) -> dict[str, object]:
    return {
        "checkpoint_file_sha256": sha256_bytes(checkpoint_bytes),
        "checkpoint_signature_file_sha256": sha256_bytes(signature_bytes),
        "checkpoint_chain_sha256": checkpoint["checkpoint_chain_sha256"],
        "store_id_sha256": checkpoint["store_binding"]["store_id_sha256"],
        "reservation_count": checkpoint["store_binding"]["reservation_count"],
        "allowed_signers_file_sha256": sha256_bytes(allowed_signers_bytes),
        "signer_identity_file_sha256": sha256_bytes(identity_bytes),
    }


def validate_transition(
    transition: object,
    *,
    transition_bytes: bytes,
    expected_transition_sha256: str,
    bundle_bytes: bytes,
    expected_bundle_sha256: str,
    chain: list[dict[str, Any]],
    successor_bytes: bytes,
    successor_signature_bytes: bytes,
    expected_successor_sha256: str,
    successor: dict[str, Any],
    policies: SegmentPolicyInputs,
    evaluated_at: datetime,
) -> list[str]:
    errors: list[str] = []
    value = require_exact_fields(
        transition, TRANSITION_FIELDS, "transition", errors
    )
    if value is None:
        return sorted(set(errors))
    if value.get("kind") != "attestation_nonce_store_checkpoint_segment_transition":
        errors.append("transition kind is invalid")
    if value.get("version") != "1.0":
        errors.append("transition version must be 1.0")
    if value.get("status") != "SEGMENT_TRANSITION_CANDIDATE":
        errors.append("transition status must remain SEGMENT_TRANSITION_CANDIDATE")
    if value.get("namespace") != NAMESPACE:
        errors.append(f"namespace must be {NAMESPACE}")
    require_sha256(value.get("transition_id_sha256"), "transition_id_sha256", errors)
    mode = value.get("transition_mode")
    if not isinstance(mode, str) or mode not in TRANSITION_MODES:
        errors.append("transition_mode is invalid")
    if (
        SHA256_HEX.fullmatch(expected_transition_sha256) is None
        or expected_transition_sha256 != sha256_bytes(transition_bytes)
    ):
        errors.append("supplied transition digest mismatch")
    if (
        SHA256_HEX.fullmatch(expected_bundle_sha256) is None
        or expected_bundle_sha256 != sha256_bytes(bundle_bytes)
    ):
        errors.append("supplied prior bundle digest mismatch")
    if (
        SHA256_HEX.fullmatch(expected_successor_sha256) is None
        or expected_successor_sha256 != sha256_bytes(successor_bytes)
    ):
        errors.append("supplied successor checkpoint digest mismatch")

    prior_binding = require_exact_fields(
        value.get("prior_segment_binding"),
        PRIOR_BINDING_FIELDS,
        "prior_segment_binding",
        errors,
    )
    if prior_binding is not None:
        for field in PRIOR_BINDING_FIELDS - {"checkpoint_count"}:
            require_sha256(
                prior_binding.get(field), f"prior_segment_binding.{field}", errors
            )
        require_positive_int(
            prior_binding.get("checkpoint_count"),
            "prior_segment_binding.checkpoint_count",
            errors,
        )
        if prior_binding != expected_prior_binding(
            bundle_bytes,
            chain,
            policies.prior_allowed_signers,
            policies.prior_identity,
        ):
            errors.append("prior segment binding mismatch")

    successor_binding = require_exact_fields(
        value.get("successor_checkpoint_binding"),
        SUCCESSOR_BINDING_FIELDS,
        "successor_checkpoint_binding",
        errors,
    )
    if successor_binding is not None:
        for field in SUCCESSOR_BINDING_FIELDS - {"reservation_count"}:
            require_sha256(
                successor_binding.get(field),
                f"successor_checkpoint_binding.{field}",
                errors,
            )
        require_nonnegative_int(
            successor_binding.get("reservation_count"),
            "successor_checkpoint_binding.reservation_count",
            errors,
        )
        if successor_binding != expected_successor_binding(
            successor_bytes,
            successor_signature_bytes,
            successor,
            policies.successor_allowed_signers,
            policies.successor_identity,
        ):
            errors.append("successor checkpoint binding mismatch")

    reviewer_policy = require_exact_fields(
        value.get("reviewer_policy_binding"),
        REVIEWER_POLICY_FIELDS,
        "reviewer_policy_binding",
        errors,
    )
    if reviewer_policy is not None:
        require_sha256(
            reviewer_policy.get("allowed_signers_file_sha256"),
            "reviewer_policy_binding.allowed_signers_file_sha256",
            errors,
        )
        require_sha256(
            reviewer_policy.get("signer_identity_file_sha256"),
            "reviewer_policy_binding.signer_identity_file_sha256",
            errors,
        )
        expected_reviewer_policy = {
            "allowed_signers_file_sha256": sha256_bytes(
                policies.reviewer_allowed_signers
            ),
            "signer_identity_file_sha256": sha256_bytes(policies.reviewer_identity),
            "signer_role": "independent_transition_reviewer",
        }
        if reviewer_policy != expected_reviewer_policy:
            errors.append("transition reviewer policy binding mismatch")

    claims = require_exact_fields(
        value.get("claims"), ALWAYS_FALSE_FIELDS, "claims", errors
    )
    if claims is not None:
        for field in ALWAYS_FALSE_FIELDS:
            if claims.get(field) is not False:
                errors.append(f"claim {field} must remain false")
    if value.get("public_beta") != "NO_GO_UNPUBLISHED":
        errors.append("public_beta must remain NO_GO_UNPUBLISHED")

    issued_at = parse_time(value.get("issued_at"), "issued_at", errors)
    expires_at = parse_time(value.get("expires_at"), "expires_at", errors)
    if issued_at is not None and expires_at is not None:
        duration = (expires_at - issued_at).total_seconds()
        if duration <= 0:
            errors.append("signed window must have positive duration")
        if duration > MAX_SIGNED_WINDOW_SECONDS:
            errors.append("signed window exceeds 900 seconds")
        if not issued_at <= evaluated_at <= expires_at:
            errors.append("evaluation time is outside the signed window")
    return sorted(set(errors))


def verify_signature(
    executable: Path,
    *,
    allowed_signers_bytes: bytes,
    identity: str,
    signature_bytes: bytes,
    document_bytes: bytes,
    namespace: str,
    timeout_seconds: float,
) -> bool:
    try:
        with tempfile.TemporaryDirectory(prefix="kotodama-r22-signature-") as directory:
            root = Path(directory)
            allowed_signers = root / "allowed-signers"
            signature = root / "document.sig"
            allowed_signers.write_bytes(allowed_signers_bytes)
            signature.write_bytes(signature_bytes)
            allowed_signers.chmod(0o600)
            signature.chmod(0o600)
            result = subprocess.run(
                [
                    str(executable),
                    "-Y",
                    "verify",
                    "-f",
                    str(allowed_signers),
                    "-I",
                    identity,
                    "-n",
                    namespace,
                    "-s",
                    str(signature),
                ],
                input=document_bytes,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=timeout_seconds,
            )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def allowed_signer_key_set(allowed_signers_bytes: bytes) -> set[str] | None:
    """Return exact OpenSSH public-key blob digests from an allowed-signers file."""

    try:
        text = allowed_signers_bytes.decode("utf-8")
    except UnicodeError:
        return None
    key_digests: set[str] = set()
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            tokens = shlex.split(line, comments=True, posix=True)
        except ValueError:
            return None
        matches: list[bytes] = []
        for index in range(1, len(tokens) - 1):
            key_type = tokens[index]
            try:
                blob = base64.b64decode(tokens[index + 1], validate=True)
            except (ValueError, TypeError):
                continue
            if len(blob) < 5:
                continue
            type_length = int.from_bytes(blob[:4], "big")
            if not 1 <= type_length <= len(blob) - 4:
                continue
            try:
                embedded_type = blob[4 : 4 + type_length].decode("ascii")
            except UnicodeError:
                continue
            if embedded_type == key_type:
                matches.append(blob)
        if len(matches) != 1:
            return None
        key_digests.add(sha256_bytes(matches[0]))
    return key_digests or None


def expected_checkpoint_policy(
    allowed_signers_bytes: bytes, identity_bytes: bytes
) -> dict[str, str]:
    return {
        "namespace": CHECKPOINT_NAMESPACE,
        "allowed_signers_file_sha256": sha256_bytes(allowed_signers_bytes),
        "signer_identity_sha256": sha256_bytes(identity_bytes),
        "signer_role": "independent_reviewer",
    }


def validate_segment_boundary(
    *,
    bundle: dict[str, Any],
    chain: list[dict[str, Any]],
    successor: dict[str, Any],
    policies: SegmentPolicyInputs,
    mode: object,
) -> list[str]:
    """Validate the shared unsigned boundary contract used by creator and verifier."""

    errors: list[str] = []
    bundle_policy = bundle.get("signature_policy_binding", {})
    prior_policy = chain[0]["checkpoint"].get("signature_policy_binding", {})
    successor_policy = successor.get("signature_policy_binding", {})
    expected_prior_policy = expected_checkpoint_policy(
        policies.prior_allowed_signers, policies.prior_identity
    )
    expected_successor_policy = expected_checkpoint_policy(
        policies.successor_allowed_signers, policies.successor_identity
    )
    if bundle_policy != expected_prior_policy or prior_policy != expected_prior_policy:
        errors.append("prior signer policy mismatch")
    if successor_policy != expected_successor_policy:
        errors.append("successor signer policy mismatch")

    prior_key_set = allowed_signer_key_set(policies.prior_allowed_signers)
    successor_key_set = allowed_signer_key_set(policies.successor_allowed_signers)
    if prior_key_set is None:
        errors.append("prior allowed-signers key set is invalid")
    if successor_key_set is None:
        errors.append("successor allowed-signers key set is invalid")
    if mode == "KEY_ROTATION_SEGMENT":
        if (
            prior_policy == successor_policy
            or sha256_bytes(policies.prior_allowed_signers)
            == sha256_bytes(policies.successor_allowed_signers)
            or prior_key_set is None
            or successor_key_set is None
            or prior_key_set == successor_key_set
        ):
            errors.append("key rotation mode requires a changed signer key set")
    elif mode == "SAME_POLICY_SEGMENT" and prior_policy != successor_policy:
        errors.append("same-policy mode requires an unchanged signer policy")

    reviewer_hashes = {
        sha256_bytes(policies.reviewer_allowed_signers),
        sha256_bytes(policies.reviewer_identity),
    }
    if reviewer_hashes & {
        sha256_bytes(policies.prior_allowed_signers),
        sha256_bytes(policies.prior_identity),
        sha256_bytes(policies.successor_allowed_signers),
        sha256_bytes(policies.successor_identity),
    }:
        errors.append("transition reviewer hashes must be structurally distinct")

    head = chain[-1]
    head_checkpoint = head["checkpoint"]
    parent = successor.get("parent_binding", {})
    if (
        parent.get("mode") != "SUCCESSOR"
        or parent.get("parent_checkpoint_file_sha256")
        != head["checkpoint_file_sha256"]
        or parent.get("parent_checkpoint_chain_sha256")
        != head_checkpoint.get("checkpoint_chain_sha256")
    ):
        errors.append("successor parent binding does not match prior segment head")
    prior_store = head_checkpoint.get("store_binding", {})
    successor_store = successor.get("store_binding", {})
    if prior_store.get("store_id_sha256") != successor_store.get("store_id_sha256"):
        errors.append("store identity changed across segment boundary")
    prior_reservations = set(prior_store.get("reservation_sha256s", []))
    successor_reservations = set(successor_store.get("reservation_sha256s", []))
    if not prior_reservations.issubset(successor_reservations):
        errors.append("successor is not an append-only extension of prior segment")
    return sorted(set(errors))


def report(
    status: str,
    errors: list[str],
    *,
    evaluated_at: datetime | None = None,
    bindings: dict[str, str] | None = None,
    prior_checkpoints: int = 0,
    prior_links: int = 0,
    parent_links: int = 0,
    prior_reservations: int = 0,
    successor_reservations: int = 0,
) -> dict[str, Any]:
    claims = {
        field: False
        for field in sorted(
            COMMON_SUCCESS_FIELDS | MODE_SUCCESS_FIELDS | ALWAYS_FALSE_FIELDS
        )
    }
    if status in {
        "SIGNED_KEY_ROTATION_SEGMENT_TRANSITION",
        "SIGNED_SAME_POLICY_SEGMENT_TRANSITION",
    }:
        for field in COMMON_SUCCESS_FIELDS:
            claims[field] = True
        claims[
            "key_rotation_transition_binding_verified"
            if status == "SIGNED_KEY_ROTATION_SEGMENT_TRANSITION"
            else "same_policy_segmentation_binding_verified"
        ] = True
    return {
        "kind": "attestation_nonce_store_checkpoint_segment_transition_verification",
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
            "prior_checkpoints_verified": prior_checkpoints,
            "prior_links_verified": prior_links,
            "successor_parent_links_verified": parent_links,
            "prior_reservations": prior_reservations,
            "successor_reservations": successor_reservations,
        },
        "claims": claims,
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 18:
        print(
            "usage: verify_attestation_nonce_store_checkpoint_segment_transition.py "
            "TRANSITION_JSON TRANSITION_SIGNATURE EXPECTED_TRANSITION_SHA256 "
            "PRIOR_BUNDLE_JSON EXPECTED_PRIOR_BUNDLE_SHA256 "
            "SUCCESSOR_CHECKPOINT_JSON SUCCESSOR_SIGNATURE "
            "EXPECTED_SUCCESSOR_SHA256 SUPPLIED_STORE_DB "
            "PRIOR_ALLOWED_SIGNERS PRIOR_IDENTITY_FILE "
            "SUCCESSOR_ALLOWED_SIGNERS SUCCESSOR_IDENTITY_FILE "
            "REVIEWER_ALLOWED_SIGNERS REVIEWER_IDENTITY_FILE "
            "EXPECTED_SSH_KEYGEN_SHA256 EVALUATED_AT_ISO8601",
            file=sys.stderr,
        )
        return 2
    try:
        transition_bytes = safe_read(Path(argv[1]), maximum=MAX_TRANSITION_BYTES)
        transition_signature_bytes = safe_read(
            Path(argv[2]), maximum=MAX_SIGNATURE_BYTES
        )
        bundle_bytes = safe_read(Path(argv[4]), maximum=MAX_BUNDLE_BYTES)
        successor_bytes = safe_read(Path(argv[6]), maximum=MAX_CHECKPOINT_BYTES)
        successor_signature_bytes = safe_read(
            Path(argv[7]), maximum=MAX_SIGNATURE_BYTES
        )
        prior_allowed_bytes = safe_read(
            Path(argv[10]), maximum=MAX_ALLOWED_SIGNERS_BYTES
        )
        prior_identity_bytes = safe_read(Path(argv[11]), maximum=MAX_IDENTITY_BYTES)
        successor_allowed_bytes = safe_read(
            Path(argv[12]), maximum=MAX_ALLOWED_SIGNERS_BYTES
        )
        successor_identity_bytes = safe_read(
            Path(argv[13]), maximum=MAX_IDENTITY_BYTES
        )
        reviewer_allowed_bytes = safe_read(
            Path(argv[14]), maximum=MAX_ALLOWED_SIGNERS_BYTES
        )
        reviewer_identity_bytes = safe_read(
            Path(argv[15]), maximum=MAX_IDENTITY_BYTES
        )
        identities = [
            value.decode("utf-8")
            for value in (
                prior_identity_bytes,
                successor_identity_bytes,
                reviewer_identity_bytes,
            )
        ]
        if any(IDENTITY.fullmatch(identity) is None for identity in identities):
            raise ValueError
        policy_inputs = SegmentPolicyInputs(
            prior_allowed_signers=prior_allowed_bytes,
            prior_identity=prior_identity_bytes,
            successor_allowed_signers=successor_allowed_bytes,
            successor_identity=successor_identity_bytes,
            reviewer_allowed_signers=reviewer_allowed_bytes,
            reviewer_identity=reviewer_identity_bytes,
        )
        time_errors: list[str] = []
        evaluated_at = parse_time(argv[17], "evaluated_at", time_errors)
        if time_errors or evaluated_at is None:
            raise ValueError
        transition = load_strict_json_bytes(transition_bytes)
        bundle = load_strict_json_bytes(bundle_bytes)
        successor = load_strict_json_bytes(successor_bytes)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        RecursionError,
        TypeError,
        ValueError,
    ):
        print(json.dumps(report("INVALID", ["input is invalid"]), sort_keys=True))
        return 1

    chain, chain_errors = chain_from_bundle(bundle)
    successor_errors = (
        validate_checkpoint(successor)
        if isinstance(successor, dict)
        else ["successor checkpoint must be an object"]
    )
    if chain_errors or chain is None or successor_errors or not isinstance(
        successor, dict
    ):
        structure_errors = list(chain_errors)
        if successor_errors:
            structure_errors.append("successor checkpoint structure is invalid")
        print(
            json.dumps(
                report("INVALID", sorted(set(structure_errors))),
                sort_keys=True,
            )
        )
        return 1

    validation_errors = validate_transition(
        transition,
        transition_bytes=transition_bytes,
        expected_transition_sha256=argv[3],
        bundle_bytes=bundle_bytes,
        expected_bundle_sha256=argv[5],
        chain=chain,
        successor_bytes=successor_bytes,
        successor_signature_bytes=successor_signature_bytes,
        expected_successor_sha256=argv[8],
        successor=successor,
        policies=policy_inputs,
        evaluated_at=evaluated_at,
    )
    bindings = {
        "transition_file_sha256": sha256_bytes(transition_bytes),
        "transition_signature_file_sha256": sha256_bytes(
            transition_signature_bytes
        ),
        "prior_bundle_file_sha256": sha256_bytes(bundle_bytes),
        "prior_head_checkpoint_sha256": chain[-1]["checkpoint_file_sha256"],
        "successor_checkpoint_file_sha256": sha256_bytes(successor_bytes),
        "successor_checkpoint_signature_file_sha256": sha256_bytes(
            successor_signature_bytes
        ),
        "store_id_sha256": successor["store_binding"]["store_id_sha256"],
        "prior_allowed_signers_file_sha256": sha256_bytes(prior_allowed_bytes),
        "prior_identity_file_sha256": sha256_bytes(prior_identity_bytes),
        "successor_allowed_signers_file_sha256": sha256_bytes(
            successor_allowed_bytes
        ),
        "successor_identity_file_sha256": sha256_bytes(successor_identity_bytes),
        "reviewer_allowed_signers_file_sha256": sha256_bytes(reviewer_allowed_bytes),
        "reviewer_identity_file_sha256": sha256_bytes(reviewer_identity_bytes),
    }
    transition_id = (
        transition.get("transition_id_sha256")
        if isinstance(transition, dict)
        else None
    )
    if isinstance(transition_id, str) and SHA256_HEX.fullmatch(transition_id):
        bindings["transition_id_sha256"] = transition_id

    mode = transition.get("transition_mode") if isinstance(transition, dict) else None
    head = chain[-1]
    head_checkpoint = head["checkpoint"]
    prior_store = head_checkpoint.get("store_binding", {})
    successor_store = successor.get("store_binding", {})
    prior_reservations = set(prior_store.get("reservation_sha256s", []))
    successor_reservations = set(successor_store.get("reservation_sha256s", []))
    errors = list(validation_errors)
    errors.extend(
        validate_segment_boundary(
            bundle=bundle,
            chain=chain,
            successor=successor,
            policies=policy_inputs,
            mode=mode,
        )
    )

    with hold_store_snapshot(Path(argv[9])) as (store_binding, store_errors):
        if store_errors or store_binding is None:
            errors.append("supplied store snapshot is invalid")
        elif successor_store != store_binding:
            errors.append("supplied store does not match successor checkpoint")

        ssh_keygen = shutil.which("ssh-keygen")
        executable_sha256 = None
        executable_bytes = b""
        if ssh_keygen is None:
            errors.append("ssh-keygen is unavailable")
        else:
            try:
                executable_bytes = safe_read(
                    Path(ssh_keygen), maximum=MAX_SSH_KEYGEN_BYTES
                )
            except OSError:
                errors.append("ssh-keygen executable is invalid")
            if executable_bytes:
                executable_sha256 = sha256_bytes(executable_bytes)
                if (
                    SHA256_HEX.fullmatch(argv[16]) is None
                    or argv[16] != executable_sha256
                ):
                    errors.append("ssh-keygen executable binding mismatch")
                else:
                    bindings["ssh_keygen_executable_sha256"] = executable_sha256

        if executable_bytes and executable_sha256 == argv[16]:
            with tempfile.TemporaryDirectory(
                prefix="kotodama-r22-pinned-ssh-"
            ) as directory:
                executable = Path(directory) / (
                    "ssh-keygen.exe" if os.name == "nt" else "ssh-keygen"
                )
                executable.write_bytes(executable_bytes)
                executable.chmod(0o700)
                deadline = time.monotonic() + MAX_TOTAL_SIGNATURE_SECONDS
                for sequence, item in enumerate(chain):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not verify_signature(
                        executable,
                        allowed_signers_bytes=prior_allowed_bytes,
                        identity=identities[0],
                        signature_bytes=item["signature_bytes"],
                        document_bytes=item["checkpoint_bytes"],
                        namespace=CHECKPOINT_NAMESPACE,
                        timeout_seconds=min(MAX_SIGNATURE_SECONDS, max(0.001, remaining)),
                    ):
                        errors.append(
                            f"prior checkpoint {sequence} signature verification failed"
                        )
                        break
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not verify_signature(
                    executable,
                    allowed_signers_bytes=successor_allowed_bytes,
                    identity=identities[1],
                    signature_bytes=successor_signature_bytes,
                    document_bytes=successor_bytes,
                    namespace=CHECKPOINT_NAMESPACE,
                    timeout_seconds=min(MAX_SIGNATURE_SECONDS, max(0.001, remaining)),
                ):
                    errors.append("successor checkpoint signature verification failed")
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not verify_signature(
                    executable,
                    allowed_signers_bytes=reviewer_allowed_bytes,
                    identity=identities[2],
                    signature_bytes=transition_signature_bytes,
                    document_bytes=transition_bytes,
                    namespace=NAMESPACE,
                    timeout_seconds=min(MAX_SIGNATURE_SECONDS, max(0.001, remaining)),
                ):
                    errors.append("transition signature verification failed")

        errors = sorted(set(errors))
        if errors:
            print(
                json.dumps(
                    report(
                        "INVALID",
                        errors,
                        evaluated_at=evaluated_at,
                        bindings=bindings,
                    ),
                    sort_keys=True,
                )
            )
            return 1

        status = (
            "SIGNED_KEY_ROTATION_SEGMENT_TRANSITION"
            if mode == "KEY_ROTATION_SEGMENT"
            else "SIGNED_SAME_POLICY_SEGMENT_TRANSITION"
        )
        print(
            json.dumps(
                report(
                    status,
                    [],
                    evaluated_at=evaluated_at,
                    bindings=bindings,
                    prior_checkpoints=len(chain),
                    prior_links=len(chain) - 1,
                    parent_links=1,
                    prior_reservations=len(prior_reservations),
                    successor_reservations=len(successor_reservations),
                ),
                sort_keys=True,
            )
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
