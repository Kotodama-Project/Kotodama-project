#!/usr/bin/env python3
"""Verify a complete supplied checkpoint path and a supplied store snapshot."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from create_attestation_nonce_store_checkpoint import (
    MAX_CHECKPOINT_BYTES,
    SHA256_HEX,
    hold_store_snapshot,
)
from create_attestation_nonce_store_checkpoint_chain_bundle import (
    MAX_BUNDLE_BYTES,
    chain_from_bundle,
)
from validate_resolved_compose_candidate import load_strict_json_bytes
from verify_attestation_nonce_store_checkpoint import verify_signature
from verify_protected_compose_evidence_attestation import safe_read, sha256_bytes


SUCCESS_FIELDS = {
    "supplied_bundle_digest_match_verified",
    "bundle_structure_verified",
    "all_checkpoint_digests_verified",
    "all_signature_digests_verified",
    "all_checkpoint_signatures_verified",
    "allowed_signer_verified",
    "signer_identity_binding_verified",
    "genesis_binding_verified",
    "recursive_parent_links_verified",
    "append_only_reservation_path_verified",
    "single_store_identity_verified",
    "supplied_store_logical_equivalence_verified",
    "ssh_keygen_binary_binding_verified",
}
ALWAYS_FALSE_FIELDS = {
    "external_anchor_authority_verified",
    "trusted_clock_source_verified",
    "authoritative_complete_history_verified",
    "parallel_branch_absence_verified",
    "key_rotation_verified",
    "store_continuity_verified",
    "backup_creation_verified",
    "restore_execution_verified",
    "promotion_verified",
    "current_truth_changed",
    "final_human_go",
    "public_beta_go",
    "ssh_keygen_vendor_authority_verified",
}
MAX_CHAIN_SIGNATURE_SECONDS = 120
MAX_SINGLE_SIGNATURE_SECONDS = 30
MAX_SSH_KEYGEN_BYTES = 16 * 1024 * 1024


def report(
    status: str,
    errors: list[str],
    *,
    bindings: dict[str, str] | None = None,
    checkpoints: int = 0,
    links: int = 0,
    reservations: int = 0,
) -> dict[str, Any]:
    claims = {field: False for field in sorted(SUCCESS_FIELDS | ALWAYS_FALSE_FIELDS)}
    if status == "SIGNED_RECURSIVE_CHAIN_AND_STORE_EQUIVALENCE":
        for field in SUCCESS_FIELDS:
            claims[field] = True
    return {
        "kind": "attestation_nonce_store_checkpoint_chain_verification",
        "version": "1.0",
        "status": status,
        "errors": errors,
        "verified_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "clock_source": "local_system_utc_untrusted",
        "input_bindings": dict(sorted((bindings or {}).items())),
        "counts": {
            "checkpoints_verified": checkpoints,
            "parent_links_verified": links,
            "reservations_at_current": reservations,
        },
        "claims": claims,
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 7:
        print(
            "usage: verify_attestation_nonce_store_checkpoint_chain.py "
            "PRIVATE_CHAIN_BUNDLE_JSON EXPECTED_BUNDLE_SHA256 SUPPLIED_STORE_DB "
            "ALLOWED_SIGNERS_FILE SIGNER_IDENTITY_FILE "
            "EXPECTED_SSH_KEYGEN_SHA256",
            file=sys.stderr,
        )
        return 2
    try:
        bundle_path = Path(argv[1])
        expected_bundle = argv[2]
        store_path = Path(argv[3])
        allowed_path = Path(argv[4])
        identity_path = Path(argv[5])
        expected_ssh_keygen = argv[6]
        bundle_bytes = safe_read(bundle_path, maximum=MAX_BUNDLE_BYTES)
        allowed_bytes = safe_read(allowed_path, maximum=MAX_CHECKPOINT_BYTES)
        identity_bytes = safe_read(identity_path, maximum=4096)
        identity = identity_bytes.decode("utf-8")
        if re.fullmatch(r"[A-Za-z0-9._@+-]{1,256}", identity) is None:
            raise ValueError
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

    with hold_store_snapshot(store_path) as (store_binding, store_errors):
        if store_errors or store_binding is None:
            print(json.dumps(report("INVALID", ["input is invalid"]), sort_keys=True))
            return 1
        bindings = {
            "allowed_signers_file_sha256": sha256_bytes(allowed_bytes),
            "bundle_file_sha256": sha256_bytes(bundle_bytes),
            "identity_file_sha256": sha256_bytes(identity_bytes),
            "store_id_sha256": store_binding["store_id_sha256"],
        }
        errors: list[str] = []
        bundle_object = bundle if isinstance(bundle, dict) else {}
        if (
            SHA256_HEX.fullmatch(expected_bundle) is None
            or expected_bundle != sha256_bytes(bundle_bytes)
        ):
            errors.append("supplied bundle digest mismatch")
        entries = bundle_object.get("entries")
        if not isinstance(entries, list):
            errors.append("bundle entries are invalid")
            entries = []
        if entries:
            bindings["genesis_checkpoint_sha256"] = entries[0][
                "checkpoint_file_sha256"
            ]
            bindings["current_checkpoint_sha256"] = entries[-1][
                "checkpoint_file_sha256"
            ]
        signature_policy_value = bundle_object.get("signature_policy_binding", {})
        signature_policy = (
            signature_policy_value if isinstance(signature_policy_value, dict) else {}
        )
        if signature_policy != chain[0]["checkpoint"].get(
            "signature_policy_binding"
        ):
            errors.append("bundle signer policy does not match checkpoint chain")
        if signature_policy.get("allowed_signers_file_sha256") != sha256_bytes(
            allowed_bytes
        ):
            errors.append("allowed signers binding mismatch")
        if signature_policy.get("signer_identity_sha256") != sha256_bytes(identity_bytes):
            errors.append("signer identity binding mismatch")
        ssh_keygen = shutil.which("ssh-keygen")
        if ssh_keygen is None:
            errors.append("ssh-keygen is unavailable")
        else:
            try:
                ssh_keygen_bytes = safe_read(
                    Path(ssh_keygen), maximum=MAX_SSH_KEYGEN_BYTES
                )
            except OSError:
                ssh_keygen_bytes = b""
                errors.append("ssh-keygen executable is invalid")
            ssh_keygen_sha256 = (
                sha256_bytes(ssh_keygen_bytes) if ssh_keygen_bytes else ""
            )
            if (
                SHA256_HEX.fullmatch(expected_ssh_keygen) is None
                or expected_ssh_keygen != ssh_keygen_sha256
            ):
                errors.append("ssh-keygen executable binding mismatch")
            else:
                bindings["ssh_keygen_executable_sha256"] = ssh_keygen_sha256
                with tempfile.TemporaryDirectory(
                    prefix="kotodama-pinned-ssh-keygen-"
                ) as directory:
                    executable = Path(directory) / (
                        "ssh-keygen.exe" if os.name == "nt" else "ssh-keygen"
                    )
                    executable.write_bytes(ssh_keygen_bytes)
                    executable.chmod(0o700)
                    signature_deadline = (
                        time.monotonic() + MAX_CHAIN_SIGNATURE_SECONDS
                    )
                    for sequence, item in enumerate(chain):
                        remaining = signature_deadline - time.monotonic()
                        if remaining <= 0:
                            errors.append(
                                "checkpoint chain signature verification timed out"
                            )
                            break
                        if not verify_signature(
                            str(executable),
                            allowed_bytes,
                            identity,
                            item["signature_bytes"],
                            item["checkpoint_bytes"],
                            timeout_seconds=min(MAX_SINGLE_SIGNATURE_SECONDS, remaining),
                        ):
                            errors.append(
                                f"checkpoint {sequence} signature verification failed"
                            )
        current_checkpoint = chain[-1]["checkpoint"]
        if current_checkpoint.get("store_binding") != store_binding:
            errors.append("supplied store does not match current checkpoint")
        errors = sorted(set(errors))
        if errors:
            print(json.dumps(report("INVALID", errors, bindings=bindings), sort_keys=True))
            return 1
        reservations = current_checkpoint["store_binding"]["reservation_count"]
        print(
            json.dumps(
                report(
                    "SIGNED_RECURSIVE_CHAIN_AND_STORE_EQUIVALENCE",
                    [],
                    bindings=bindings,
                    checkpoints=len(chain),
                    links=len(chain) - 1,
                    reservations=reservations,
                ),
                sort_keys=True,
            )
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
