#!/usr/bin/env python3
"""Create one private checkpoint segment-transition candidate without signing it."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from create_attestation_nonce_store_checkpoint import (
    MAX_CHECKPOINT_BYTES,
    validate_checkpoint,
    write_new_file,
)
from create_attestation_nonce_store_checkpoint_chain_bundle import (
    MAX_BUNDLE_BYTES,
    chain_from_bundle,
)
from validate_resolved_compose_candidate import load_strict_json_bytes
from verify_attestation_nonce_store_checkpoint_segment_transition import (
    ALWAYS_FALSE_FIELDS,
    IDENTITY,
    MAX_ALLOWED_SIGNERS_BYTES,
    MAX_IDENTITY_BYTES,
    MAX_SIGNATURE_BYTES,
    MAX_SIGNED_WINDOW_SECONDS,
    NAMESPACE,
    SHA256_HEX,
    SegmentPolicyInputs,
    TRANSITION_MODES,
    expected_prior_binding,
    expected_successor_binding,
    parse_time,
    validate_segment_boundary,
    validate_transition,
)
from verify_protected_compose_evidence_attestation import safe_read, sha256_bytes


def creation_report(
    status: str,
    errors: list[str],
    transition_bytes: bytes | None = None,
) -> dict[str, Any]:
    created = status == "SEGMENT_TRANSITION_CANDIDATE_CREATED"
    return {
        "kind": "attestation_nonce_store_checkpoint_segment_transition_creation",
        "version": "1.0",
        "status": status,
        "errors": errors,
        "transition_file_sha256": (
            sha256_bytes(transition_bytes) if transition_bytes is not None else None
        ),
        "claims": {
            "private_transition_candidate_created": created,
            "source_bindings_structurally_validated": created,
            "transition_signature_created": False,
            "transition_signature_verified": False,
            "successor_checkpoint_signature_verified": False,
            "actual_key_rotation_executed": False,
            "old_key_revocation_verified": False,
            "protected_runner_execution_verified": False,
            "promotion_verified": False,
            "current_truth_changed": False,
            "final_human_go": False,
            "public_beta_go": False,
        },
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 18 or argv[16] != "--output":
        print(
            "usage: create_attestation_nonce_store_checkpoint_segment_transition.py "
            "PRIOR_BUNDLE_JSON EXPECTED_PRIOR_BUNDLE_SHA256 "
            "SUCCESSOR_CHECKPOINT_JSON SUCCESSOR_SIGNATURE "
            "EXPECTED_SUCCESSOR_SHA256 PRIOR_ALLOWED_SIGNERS PRIOR_IDENTITY_FILE "
            "SUCCESSOR_ALLOWED_SIGNERS SUCCESSOR_IDENTITY_FILE "
            "REVIEWER_ALLOWED_SIGNERS REVIEWER_IDENTITY_FILE TRANSITION_MODE "
            "TRANSITION_ID_SHA256 ISSUED_AT EXPIRES_AT --output TRANSITION_JSON",
            file=sys.stderr,
        )
        return 2
    try:
        bundle_bytes = safe_read(Path(argv[1]), maximum=MAX_BUNDLE_BYTES)
        successor_bytes = safe_read(Path(argv[3]), maximum=MAX_CHECKPOINT_BYTES)
        successor_signature_bytes = safe_read(
            Path(argv[4]), maximum=MAX_SIGNATURE_BYTES
        )
        prior_allowed_bytes = safe_read(
            Path(argv[6]), maximum=MAX_ALLOWED_SIGNERS_BYTES
        )
        prior_identity_bytes = safe_read(Path(argv[7]), maximum=MAX_IDENTITY_BYTES)
        successor_allowed_bytes = safe_read(
            Path(argv[8]), maximum=MAX_ALLOWED_SIGNERS_BYTES
        )
        successor_identity_bytes = safe_read(
            Path(argv[9]), maximum=MAX_IDENTITY_BYTES
        )
        reviewer_allowed_bytes = safe_read(
            Path(argv[10]), maximum=MAX_ALLOWED_SIGNERS_BYTES
        )
        reviewer_identity_bytes = safe_read(
            Path(argv[11]), maximum=MAX_IDENTITY_BYTES
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
        if SHA256_HEX.fullmatch(argv[2]) is None or argv[2] != sha256_bytes(
            bundle_bytes
        ):
            raise ValueError
        if SHA256_HEX.fullmatch(argv[5]) is None or argv[5] != sha256_bytes(
            successor_bytes
        ):
            raise ValueError
        if argv[12] not in TRANSITION_MODES or SHA256_HEX.fullmatch(argv[13]) is None:
            raise ValueError
        time_errors: list[str] = []
        issued_at = parse_time(argv[14], "issued_at", time_errors)
        expires_at = parse_time(argv[15], "expires_at", time_errors)
        if issued_at is None or expires_at is None or time_errors:
            raise ValueError
        duration = (expires_at - issued_at).total_seconds()
        if duration <= 0 or duration > MAX_SIGNED_WINDOW_SECONDS:
            raise ValueError

        bundle = load_strict_json_bytes(bundle_bytes)
        successor = load_strict_json_bytes(successor_bytes)
        chain, chain_errors = chain_from_bundle(bundle)
        successor_errors = (
            validate_checkpoint(successor)
            if isinstance(successor, dict)
            else ["successor checkpoint must be an object"]
        )
        if (
            not isinstance(bundle, dict)
            or chain is None
            or chain_errors
            or not isinstance(successor, dict)
            or successor_errors
        ):
            raise ValueError
        boundary_errors = validate_segment_boundary(
            bundle=bundle,
            chain=chain,
            successor=successor,
            policies=policy_inputs,
            mode=argv[12],
        )
        if boundary_errors:
            raise ValueError

        candidate = {
            "kind": "attestation_nonce_store_checkpoint_segment_transition",
            "version": "1.0",
            "status": "SEGMENT_TRANSITION_CANDIDATE",
            "namespace": NAMESPACE,
            "transition_id_sha256": argv[13],
            "transition_mode": argv[12],
            "issued_at": argv[14],
            "expires_at": argv[15],
            "prior_segment_binding": expected_prior_binding(
                bundle_bytes, chain, prior_allowed_bytes, prior_identity_bytes
            ),
            "successor_checkpoint_binding": expected_successor_binding(
                successor_bytes,
                successor_signature_bytes,
                successor,
                successor_allowed_bytes,
                successor_identity_bytes,
            ),
            "reviewer_policy_binding": {
                "allowed_signers_file_sha256": sha256_bytes(
                    reviewer_allowed_bytes
                ),
                "signer_identity_file_sha256": sha256_bytes(
                    reviewer_identity_bytes
                ),
                "signer_role": "independent_transition_reviewer",
            },
            "claims": {field: False for field in sorted(ALWAYS_FALSE_FIELDS)},
            "public_beta": "NO_GO_UNPUBLISHED",
        }
        transition_bytes = (
            json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        validation_errors = validate_transition(
            candidate,
            transition_bytes=transition_bytes,
            expected_transition_sha256=sha256_bytes(transition_bytes),
            bundle_bytes=bundle_bytes,
            expected_bundle_sha256=argv[2],
            chain=chain,
            successor_bytes=successor_bytes,
            successor_signature_bytes=successor_signature_bytes,
            expected_successor_sha256=argv[5],
            successor=successor,
            policies=policy_inputs,
            evaluated_at=issued_at,
        )
        if validation_errors:
            raise ValueError
        write_new_file(Path(argv[17]), transition_bytes)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        RecursionError,
        TypeError,
        ValueError,
    ):
        print(
            json.dumps(
                creation_report("INVALID", ["transition creation failed"]),
                sort_keys=True,
            )
        )
        return 1
    print(
        json.dumps(
            creation_report(
                "SEGMENT_TRANSITION_CANDIDATE_CREATED", [], transition_bytes
            ),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
