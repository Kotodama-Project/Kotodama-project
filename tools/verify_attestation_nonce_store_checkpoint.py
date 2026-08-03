#!/usr/bin/env python3
"""Verify a signed nonce-store checkpoint, immediate parent link, and store match."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from create_attestation_nonce_store_checkpoint import (
    MAX_CHECKPOINT_BYTES,
    NAMESPACE,
    SHA256_HEX,
    hold_store_snapshot,
    validate_checkpoint,
)
from validate_resolved_compose_candidate import load_strict_json_bytes
from verify_protected_compose_evidence_attestation import safe_read, sha256_bytes


SUCCESS_FIELDS = {
    "supplied_current_checkpoint_digest_match_verified",
    "current_checkpoint_signature_verified",
    "allowed_signer_verified",
    "signer_identity_binding_verified",
    "checkpoint_chain_self_digest_verified",
    "store_matches_checkpoint_verified",
    "genesis_parent_binding_verified",
    "supplied_parent_checkpoint_digest_match_verified",
    "immediate_parent_signature_verified",
    "one_link_append_only_extension_verified",
}
ALWAYS_FALSE_FIELDS = {
    "external_anchor_authority_verified",
    "trusted_clock_source_verified",
    "store_continuity_verified",
    "restore_execution_verified",
    "promotion_verified",
    "current_truth_changed",
    "final_human_go",
    "public_beta_go",
}


def verify_signature(
    ssh_keygen: str,
    allowed_signers_bytes: bytes,
    identity: str,
    signature_bytes: bytes,
    checkpoint_bytes: bytes,
    timeout_seconds: float = 30,
) -> bool:
    try:
        with tempfile.TemporaryDirectory(prefix="kotodama-checkpoint-verify-") as directory:
            root = Path(directory)
            allowed_signers = root / "allowed-signers"
            signature = root / "checkpoint.sig"
            allowed_signers.write_bytes(allowed_signers_bytes)
            signature.write_bytes(signature_bytes)
            allowed_signers.chmod(0o600)
            signature.chmod(0o600)
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
                input=checkpoint_bytes,
                capture_output=True,
                check=False,
                timeout=timeout_seconds,
            )
            return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def report(
    status: str,
    errors: list[str],
    bindings: dict[str, str] | None = None,
) -> dict[str, Any]:
    claims = {field: False for field in sorted(SUCCESS_FIELDS | ALWAYS_FALSE_FIELDS)}
    if status == "SIGNED_GENESIS_CHECKPOINT_STORE_MATCH":
        for field in SUCCESS_FIELDS - {
            "supplied_parent_checkpoint_digest_match_verified",
            "immediate_parent_signature_verified",
            "one_link_append_only_extension_verified",
        }:
            claims[field] = True
    elif status == "SIGNED_SUCCESSOR_CHECKPOINT_STORE_MATCH":
        for field in SUCCESS_FIELDS - {"genesis_parent_binding_verified"}:
            claims[field] = True
    return {
        "kind": "attestation_nonce_store_checkpoint_verification",
        "version": "1.0",
        "status": status,
        "errors": errors,
        "verified_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "clock_source": "local_system_utc_untrusted",
        "input_bindings": dict(sorted((bindings or {}).items())),
        "claims": claims,
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 10:
        print(
            "usage: verify_attestation_nonce_store_checkpoint.py CHECKPOINT_JSON "
            "SIGNATURE_FILE NONCE_STORE_DB ALLOWED_SIGNERS_FILE SIGNER_IDENTITY_FILE "
            "EXPECTED_CHECKPOINT_SHA256 PARENT_CHECKPOINT_OR_GENESIS "
            "PARENT_SIGNATURE_OR_GENESIS EXPECTED_PARENT_SHA256_OR_GENESIS",
            file=sys.stderr,
        )
        return 2
    try:
        checkpoint_path = Path(argv[1])
        signature_path = Path(argv[2])
        store_path = Path(argv[3])
        allowed_path = Path(argv[4])
        identity_path = Path(argv[5])
        expected_current = argv[6]
        parent_argument = argv[7]
        parent_signature_argument = argv[8]
        expected_parent = argv[9]
        checkpoint_bytes = safe_read(checkpoint_path, maximum=MAX_CHECKPOINT_BYTES)
        signature_bytes = safe_read(signature_path, maximum=64 * 1024)
        allowed_bytes = safe_read(allowed_path, maximum=MAX_CHECKPOINT_BYTES)
        identity_bytes = safe_read(identity_path, maximum=4096)
        identity = identity_bytes.decode("utf-8")
        if re.fullmatch(r"[A-Za-z0-9._@+-]{1,256}", identity) is None:
            raise ValueError
        checkpoint = load_strict_json_bytes(checkpoint_bytes)
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

    with hold_store_snapshot(store_path) as (store_binding, store_errors):
        if store_errors or store_binding is None:
            print(json.dumps(report("INVALID", ["input is invalid"]), sort_keys=True))
            return 1
        bindings = {
            "allowed_signers_file_sha256": sha256_bytes(allowed_bytes),
            "checkpoint_file_sha256": sha256_bytes(checkpoint_bytes),
            "identity_file_sha256": sha256_bytes(identity_bytes),
            "signature_file_sha256": sha256_bytes(signature_bytes),
            "store_id_sha256": store_binding["store_id_sha256"],
        }
        errors = validate_checkpoint(checkpoint)
        if SHA256_HEX.fullmatch(expected_current) is None or expected_current != sha256_bytes(
            checkpoint_bytes
        ):
            errors.append("supplied current checkpoint digest mismatch")
        signature_binding = checkpoint.get("signature_policy_binding", {})
        if signature_binding.get("allowed_signers_file_sha256") != sha256_bytes(allowed_bytes):
            errors.append("allowed signers binding mismatch")
        if signature_binding.get("signer_identity_sha256") != sha256_bytes(identity_bytes):
            errors.append("signer identity binding mismatch")
        if checkpoint.get("store_binding") != store_binding:
            errors.append("store snapshot does not match checkpoint")
        ssh_keygen = shutil.which("ssh-keygen")
        if ssh_keygen is None:
            errors.append("ssh-keygen is unavailable")
        elif not verify_signature(
            ssh_keygen, allowed_bytes, identity, signature_bytes, checkpoint_bytes
        ):
            errors.append("current checkpoint signature verification failed")

        parent_mode = checkpoint.get("parent_binding", {}).get("mode")
        if parent_argument == parent_signature_argument == expected_parent == "GENESIS":
            if parent_mode != "GENESIS":
                errors.append("checkpoint is not genesis-bound")
            success_status = "SIGNED_GENESIS_CHECKPOINT_STORE_MATCH"
        else:
            success_status = "SIGNED_SUCCESSOR_CHECKPOINT_STORE_MATCH"
            if "GENESIS" in {parent_argument, parent_signature_argument, expected_parent}:
                errors.append("successor parent inputs are incomplete")
            else:
                try:
                    parent_path = Path(parent_argument)
                    parent_signature_path = Path(parent_signature_argument)
                    parent_bytes = safe_read(parent_path, maximum=MAX_CHECKPOINT_BYTES)
                    parent_signature_bytes = safe_read(parent_signature_path, maximum=64 * 1024)
                    parent = load_strict_json_bytes(parent_bytes)
                    errors.extend(validate_checkpoint(parent))
                    bindings["parent_checkpoint_file_sha256"] = sha256_bytes(parent_bytes)
                    bindings["parent_signature_file_sha256"] = sha256_bytes(parent_signature_bytes)
                    if SHA256_HEX.fullmatch(expected_parent) is None or expected_parent != sha256_bytes(
                        parent_bytes
                    ):
                        errors.append("supplied parent checkpoint digest mismatch")
                    if parent_mode != "SUCCESSOR":
                        errors.append("checkpoint is not successor-bound")
                    parent_binding = checkpoint.get("parent_binding", {})
                    if parent_binding.get("parent_checkpoint_file_sha256") != sha256_bytes(
                        parent_bytes
                    ) or parent_binding.get("parent_checkpoint_chain_sha256") != parent.get(
                        "checkpoint_chain_sha256"
                    ):
                        errors.append("immediate parent binding mismatch")
                    if parent.get("store_binding", {}).get("store_id_sha256") != store_binding.get(
                        "store_id_sha256"
                    ):
                        errors.append("parent and current store identity mismatch")
                    parent_reservations = set(
                        parent.get("store_binding", {}).get("reservation_sha256s", [])
                    )
                    current_reservations = set(
                        checkpoint.get("store_binding", {}).get("reservation_sha256s", [])
                    )
                    if not parent_reservations.issubset(current_reservations):
                        errors.append("current checkpoint is not an append-only extension")
                    parent_signature_binding = parent.get("signature_policy_binding", {})
                    if parent_signature_binding.get("allowed_signers_file_sha256") != sha256_bytes(
                        allowed_bytes
                    ) or parent_signature_binding.get("signer_identity_sha256") != sha256_bytes(
                        identity_bytes
                    ):
                        errors.append("parent signer binding mismatch")
                    if ssh_keygen is not None and not verify_signature(
                        ssh_keygen,
                        allowed_bytes,
                        identity,
                        parent_signature_bytes,
                        parent_bytes,
                    ):
                        errors.append("parent checkpoint signature verification failed")
                except (
                    OSError,
                    UnicodeError,
                    json.JSONDecodeError,
                    RecursionError,
                    TypeError,
                    ValueError,
                ):
                    errors.append("parent checkpoint input is invalid")
        errors = sorted(set(errors))
        if errors:
            print(json.dumps(report("INVALID", errors, bindings), sort_keys=True))
            return 1
        print(json.dumps(report(success_status, [], bindings), sort_keys=True))
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
