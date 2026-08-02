#!/usr/bin/env python3
"""Verify one signed checkpoint-head anchor against one exact R20 bundle."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from create_attestation_nonce_store_checkpoint_chain_bundle import (
    MAX_BUNDLE_BYTES,
    chain_from_bundle,
)
from validate_resolved_compose_candidate import load_strict_json_bytes
from verify_protected_compose_evidence_attestation import safe_read, sha256_bytes


NAMESPACE = "kotodama-nonce-store-checkpoint-head"
MAX_AUXILIARY_BYTES = 1024 * 1024
MAX_SIGNATURE_BYTES = 64 * 1024
MAX_IDENTITY_BYTES = 4096
MAX_SSH_KEYGEN_BYTES = 16 * 1024 * 1024
MAX_SIGNED_WINDOW_SECONDS = 900
MAX_SIGNATURE_SECONDS = 30
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
ANCHOR_FIELDS = {
    "kind",
    "version",
    "status",
    "namespace",
    "anchor_id_sha256",
    "issued_at",
    "expires_at",
    "bundle_binding",
    "signature_policy_binding",
    "claims",
    "public_beta",
}
BUNDLE_BINDING_FIELDS = {
    "bundle_file_sha256",
    "current_checkpoint_sha256",
    "store_id_sha256",
    "checkpoint_count",
}
SIGNATURE_POLICY_FIELDS = {
    "allowed_signers_file_sha256",
    "signer_identity_file_sha256",
    "signer_role",
}
SUCCESS_FIELDS = {
    "anchor_file_digest_match_verified",
    "supplied_bundle_digest_match_verified",
    "bundle_structure_verified",
    "bundle_head_binding_verified",
    "store_identity_binding_verified",
    "checkpoint_count_binding_verified",
    "anchor_signature_verified",
    "allowed_signer_verified",
    "signer_identity_binding_verified",
    "signer_role_policy_verified",
    "signed_evaluation_window_verified",
    "ssh_keygen_binary_binding_verified",
}
ALWAYS_FALSE_FIELDS = {
    "external_anchor_authority_verified",
    "trusted_clock_source_verified",
    "authoritative_complete_history_verified",
    "parallel_branch_absence_verified",
    "store_continuity_verified",
    "backup_execution_verified",
    "restore_execution_verified",
    "protected_runner_execution_verified",
    "signer_person_independence_verified",
    "promotion_verified",
    "current_truth_changed",
    "final_human_go",
    "public_beta_go",
    "ssh_keygen_vendor_authority_verified",
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


def require_sha256(value: object, location: str, errors: list[str]) -> None:
    if not isinstance(value, str) or SHA256_HEX.fullmatch(value) is None:
        errors.append(f"{location} must be lowercase SHA-256")


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


def validate_anchor(
    anchor: object,
    *,
    anchor_bytes: bytes,
    expected_anchor_sha256: str,
    bundle_bytes: bytes,
    expected_bundle_sha256: str,
    chain: list[dict[str, Any]],
    allowed_signers_bytes: bytes,
    identity_bytes: bytes,
    evaluated_at: datetime,
) -> list[str]:
    errors: list[str] = []
    value = require_exact_fields(anchor, ANCHOR_FIELDS, "anchor", errors)
    if value is None:
        return sorted(set(errors))
    if value.get("kind") != "attestation_nonce_store_checkpoint_head_anchor":
        errors.append("anchor kind is invalid")
    if value.get("version") != "1.0":
        errors.append("anchor version must be 1.0")
    if value.get("status") != "CHECKPOINT_HEAD_ANCHOR_CANDIDATE":
        errors.append("anchor status must remain CHECKPOINT_HEAD_ANCHOR_CANDIDATE")
    if value.get("namespace") != NAMESPACE:
        errors.append(f"namespace must be {NAMESPACE}")
    require_sha256(value.get("anchor_id_sha256"), "anchor_id_sha256", errors)
    if (
        SHA256_HEX.fullmatch(expected_anchor_sha256) is None
        or expected_anchor_sha256 != sha256_bytes(anchor_bytes)
    ):
        errors.append("supplied anchor digest mismatch")
    if (
        SHA256_HEX.fullmatch(expected_bundle_sha256) is None
        or expected_bundle_sha256 != sha256_bytes(bundle_bytes)
    ):
        errors.append("supplied bundle digest mismatch")

    binding = require_exact_fields(
        value.get("bundle_binding"),
        BUNDLE_BINDING_FIELDS,
        "bundle_binding",
        errors,
    )
    current = chain[-1]["checkpoint"]
    if binding is not None:
        for field in BUNDLE_BINDING_FIELDS - {"checkpoint_count"}:
            require_sha256(binding.get(field), f"bundle_binding.{field}", errors)
        count = binding.get("checkpoint_count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            errors.append("bundle_binding.checkpoint_count must be a positive integer")
        expected_binding = {
            "bundle_file_sha256": sha256_bytes(bundle_bytes),
            "current_checkpoint_sha256": chain[-1]["checkpoint_file_sha256"],
            "store_id_sha256": current["store_binding"]["store_id_sha256"],
            "checkpoint_count": len(chain),
        }
        if binding != expected_binding:
            errors.append("anchor bundle binding mismatch")

    policy = require_exact_fields(
        value.get("signature_policy_binding"),
        SIGNATURE_POLICY_FIELDS,
        "signature_policy_binding",
        errors,
    )
    if policy is not None:
        require_sha256(
            policy.get("allowed_signers_file_sha256"),
            "signature_policy_binding.allowed_signers_file_sha256",
            errors,
        )
        require_sha256(
            policy.get("signer_identity_file_sha256"),
            "signature_policy_binding.signer_identity_file_sha256",
            errors,
        )
        if policy.get("allowed_signers_file_sha256") != sha256_bytes(
            allowed_signers_bytes
        ):
            errors.append("allowed signers binding mismatch")
        if policy.get("signer_identity_file_sha256") != sha256_bytes(identity_bytes):
            errors.append("signer identity binding mismatch")
        if policy.get("signer_role") != "independent_anchor_reviewer":
            errors.append("signer role must be independent_anchor_reviewer")

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
        window = (expires_at - issued_at).total_seconds()
        if window <= 0:
            errors.append("signed window must have positive duration")
        if window > MAX_SIGNED_WINDOW_SECONDS:
            errors.append("signed window exceeds 900 seconds")
        if not issued_at <= evaluated_at <= expires_at:
            errors.append("evaluation time is outside the signed window")
    return sorted(set(errors))


def verify_signature_with_pinned_binary(
    *,
    expected_ssh_keygen_sha256: str,
    allowed_signers_bytes: bytes,
    identity: str,
    signature_bytes: bytes,
    document_bytes: bytes,
    namespace: str = NAMESPACE,
    error_label: str = "anchor signature verification failed",
) -> tuple[str | None, bool, list[str]]:
    ssh_keygen = shutil.which("ssh-keygen")
    if ssh_keygen is None:
        return None, False, ["ssh-keygen is unavailable"]
    try:
        executable_bytes = safe_read(
            Path(ssh_keygen), maximum=MAX_SSH_KEYGEN_BYTES
        )
    except OSError:
        return None, False, ["ssh-keygen executable is invalid"]
    executable_sha256 = sha256_bytes(executable_bytes)
    if (
        SHA256_HEX.fullmatch(expected_ssh_keygen_sha256) is None
        or expected_ssh_keygen_sha256 != executable_sha256
    ):
        return None, False, ["ssh-keygen executable binding mismatch"]
    try:
        with tempfile.TemporaryDirectory(prefix="kotodama-r21-pinned-ssh-") as directory:
            root = Path(directory)
            executable = root / ("ssh-keygen.exe" if os.name == "nt" else "ssh-keygen")
            allowed_signers = root / "allowed-signers"
            signature = root / "document.sig"
            executable.write_bytes(executable_bytes)
            allowed_signers.write_bytes(allowed_signers_bytes)
            signature.write_bytes(signature_bytes)
            executable.chmod(0o700)
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
                capture_output=True,
                check=False,
                timeout=MAX_SIGNATURE_SECONDS,
            )
    except (OSError, subprocess.SubprocessError):
        return executable_sha256, False, [error_label]
    return (
        executable_sha256,
        result.returncode == 0,
        [] if result.returncode == 0 else [error_label],
    )


def report(
    status: str,
    errors: list[str],
    *,
    evaluated_at: datetime | None = None,
    bindings: dict[str, str] | None = None,
    checkpoints: int = 0,
) -> dict[str, Any]:
    claims = {field: False for field in sorted(SUCCESS_FIELDS | ALWAYS_FALSE_FIELDS)}
    if status == "SIGNED_CHECKPOINT_HEAD_ANCHOR_MATCH":
        for field in SUCCESS_FIELDS:
            claims[field] = True
    return {
        "kind": "attestation_nonce_store_checkpoint_head_anchor_verification",
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
        "counts": {"checkpoints_bound": checkpoints},
        "claims": claims,
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 10:
        print(
            "usage: verify_attestation_nonce_store_checkpoint_head_anchor.py "
            "ANCHOR_JSON ANCHOR_SIGNATURE EXPECTED_ANCHOR_SHA256 "
            "PRIVATE_CHAIN_BUNDLE_JSON EXPECTED_BUNDLE_SHA256 "
            "ALLOWED_SIGNERS_FILE SIGNER_IDENTITY_FILE "
            "EXPECTED_SSH_KEYGEN_SHA256 EVALUATED_AT_ISO8601",
            file=sys.stderr,
        )
        return 2
    try:
        anchor_bytes = safe_read(Path(argv[1]), maximum=MAX_AUXILIARY_BYTES)
        signature_bytes = safe_read(Path(argv[2]), maximum=MAX_SIGNATURE_BYTES)
        bundle_bytes = safe_read(Path(argv[4]), maximum=MAX_BUNDLE_BYTES)
        allowed_signers_bytes = safe_read(Path(argv[6]), maximum=MAX_AUXILIARY_BYTES)
        identity_bytes = safe_read(Path(argv[7]), maximum=MAX_IDENTITY_BYTES)
        identity = identity_bytes.decode("utf-8")
        if re.fullmatch(r"[A-Za-z0-9._@+-]{1,256}", identity) is None:
            raise ValueError
        time_errors: list[str] = []
        evaluated_at = parse_time(argv[9], "evaluated_at", time_errors)
        if time_errors or evaluated_at is None:
            raise ValueError
        anchor = load_strict_json_bytes(anchor_bytes)
        bundle = load_strict_json_bytes(bundle_bytes)
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
    if chain_errors or chain is None:
        print(json.dumps(report("INVALID", chain_errors), sort_keys=True))
        return 1
    errors = validate_anchor(
        anchor,
        anchor_bytes=anchor_bytes,
        expected_anchor_sha256=argv[3],
        bundle_bytes=bundle_bytes,
        expected_bundle_sha256=argv[5],
        chain=chain,
        allowed_signers_bytes=allowed_signers_bytes,
        identity_bytes=identity_bytes,
        evaluated_at=evaluated_at,
    )
    executable_sha256, signature_valid, signature_errors = (
        verify_signature_with_pinned_binary(
            expected_ssh_keygen_sha256=argv[8],
            allowed_signers_bytes=allowed_signers_bytes,
            identity=identity,
            signature_bytes=signature_bytes,
            document_bytes=anchor_bytes,
        )
    )
    errors.extend(signature_errors)
    errors = sorted(set(errors))
    bindings = {
        "allowed_signers_file_sha256": sha256_bytes(allowed_signers_bytes),
        "anchor_file_sha256": sha256_bytes(anchor_bytes),
        "anchor_signature_file_sha256": sha256_bytes(signature_bytes),
        "bundle_file_sha256": sha256_bytes(bundle_bytes),
        "current_checkpoint_sha256": chain[-1]["checkpoint_file_sha256"],
        "identity_file_sha256": sha256_bytes(identity_bytes),
        "store_id_sha256": chain[-1]["checkpoint"]["store_binding"][
            "store_id_sha256"
        ],
    }
    if executable_sha256 is not None:
        bindings["ssh_keygen_executable_sha256"] = executable_sha256
    if isinstance(anchor, dict):
        anchor_id = anchor.get("anchor_id_sha256")
        if isinstance(anchor_id, str) and SHA256_HEX.fullmatch(anchor_id):
            bindings["anchor_id_sha256"] = anchor_id
    if errors or not signature_valid:
        print(
            json.dumps(
                report(
                    "INVALID", errors or ["anchor signature verification failed"],
                    evaluated_at=evaluated_at,
                    bindings=bindings,
                ),
                sort_keys=True,
            )
        )
        return 1
    print(
        json.dumps(
            report(
                "SIGNED_CHECKPOINT_HEAD_ANCHOR_MATCH",
                [],
                evaluated_at=evaluated_at,
                bindings=bindings,
                checkpoints=len(chain),
            ),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
