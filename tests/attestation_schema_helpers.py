"""Small synthetic contract fixtures; no key generation or signature claims."""

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


DIGEST = hashlib.sha256(b"synthetic-contract-input").hexdigest()
OTHER_DIGEST = hashlib.sha256(b"different-synthetic-contract-input").hexdigest()
WHEN = datetime(2026, 8, 3, 1, 5, tzinfo=timezone.utc)


def bindings(names: str) -> dict[str, str]:
    return {name: DIGEST for name in names.split()}


def assert_contract(test, schema_path: Path, good_documents, bad_documents) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for label, document in good_documents:
        with test.subTest(schema=schema_path.name, accepted=label):
            test.assertEqual(list(validator.iter_errors(document)), [])
    for label, document in bad_documents:
        with test.subTest(schema=schema_path.name, refused=label):
            test.assertTrue(list(validator.iter_errors(document)))


def changed(document, path: str, value):
    result = copy.deepcopy(document)
    target = result
    parts = path.split(".")
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value
    return result


def checkpoint(tool, *, successor: bool = False):
    result = {
        "kind": "attestation_nonce_store_checkpoint", "version": "1.0",
        "status": "CHECKPOINT_CANDIDATE", "created_at": "2026-08-03T01:00:00Z",
        "clock_source": "local_system_utc_untrusted",
        "store_binding": {
            "store_id_sha256": DIGEST,
            "schema_contract_sha256": tool.SCHEMA_CONTRACT_SHA256,
            "reservation_count": 0, "reservation_sha256s": [],
            "reservation_set_sha256": tool.reservation_set_sha256([]),
        },
        "signature_policy_binding": {
            "namespace": "kotodama-nonce-store-checkpoint",
            "allowed_signers_file_sha256": DIGEST,
            "signer_identity_sha256": DIGEST,
            "signer_role": "independent_reviewer",
        },
        "parent_binding": {
            "mode": "SUCCESSOR" if successor else "GENESIS",
            "parent_checkpoint_file_sha256": DIGEST if successor else None,
            "parent_checkpoint_chain_sha256": DIGEST if successor else None,
        },
        "claims": {name: False for name in tool.CHECKPOINT_FALSE_FIELDS},
        "public_beta": "NO_GO_UNPUBLISHED",
    }
    result["checkpoint_chain_sha256"] = tool.checkpoint_chain_sha256(result)
    return result


def anchor(false_claims):
    return {
        "kind": "attestation_nonce_store_checkpoint_head_anchor", "version": "1.0",
        "status": "CHECKPOINT_HEAD_ANCHOR_CANDIDATE",
        "namespace": "kotodama-nonce-store-checkpoint-head",
        "anchor_id_sha256": DIGEST, "issued_at": "2026-08-03T01:00:00Z",
        "expires_at": "2026-08-03T01:10:00Z",
        "bundle_binding": {
            **bindings("bundle_file_sha256 current_checkpoint_sha256 store_id_sha256"),
            "checkpoint_count": 1,
        },
        "signature_policy_binding": {
            **bindings("allowed_signers_file_sha256 signer_identity_file_sha256"),
            "signer_role": "independent_anchor_reviewer",
        },
        "claims": {name: False for name in false_claims},
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def transition(false_claims, mode="KEY_ROTATION_SEGMENT"):
    return {
        "kind": "attestation_nonce_store_checkpoint_segment_transition", "version": "1.0",
        "status": "SEGMENT_TRANSITION_CANDIDATE",
        "namespace": "kotodama-nonce-store-checkpoint-segment-transition",
        "transition_id_sha256": DIGEST, "transition_mode": mode,
        "issued_at": "2026-08-03T01:00:00Z", "expires_at": "2026-08-03T01:10:00Z",
        "prior_segment_binding": {
            **bindings("bundle_file_sha256 current_checkpoint_sha256 "
                       "current_checkpoint_chain_sha256 store_id_sha256 "
                       "allowed_signers_file_sha256 signer_identity_file_sha256"),
            "checkpoint_count": 1,
        },
        "successor_checkpoint_binding": {
            **bindings("checkpoint_file_sha256 checkpoint_signature_file_sha256 "
                       "checkpoint_chain_sha256 store_id_sha256 "
                       "allowed_signers_file_sha256 signer_identity_file_sha256"),
            "reservation_count": 0,
        },
        "reviewer_policy_binding": {
            **bindings("allowed_signers_file_sha256 signer_identity_file_sha256"),
            "signer_role": "independent_transition_reviewer",
        },
        "claims": {name: False for name in false_claims},
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def restore_evidence(false_claims, reported_checks):
    chain_binding = {
        **bindings("report_file_sha256 bundle_file_sha256 "
                   "current_checkpoint_sha256 store_id_sha256"),
        "checkpoints_verified": 1, "reservations_at_current": 0,
    }
    return {
        "kind": "attestation_nonce_store_restore_drill_evidence", "version": "1.0",
        "status": "RESTORE_DRILL_EVIDENCE_CANDIDATE",
        "namespace": "kotodama-nonce-store-restore-drill", "drill_id_sha256": DIGEST,
        "reported_started_at": "2026-08-03T01:00:00Z",
        "reported_completed_at": "2026-08-03T01:02:00Z",
        "issued_at": "2026-08-03T01:03:00Z", "expires_at": "2026-08-03T01:10:00Z",
        "anchor_binding": {
            **bindings("report_file_sha256 anchor_id_sha256 anchor_file_sha256 "
                       "bundle_file_sha256 current_checkpoint_sha256 store_id_sha256"),
            "checkpoint_count": 1,
        },
        "source_verification_binding": chain_binding,
        "restored_verification_binding": {
            **chain_binding, "report_file_sha256": OTHER_DIGEST,
        },
        "operation_receipts": {
            **bindings("backup_receipt_file_sha256 backup_artifact_sha256"),
            "restore_receipt_file_sha256": OTHER_DIGEST,
        },
        "reported_checks": {name: True for name in reported_checks},
        "signature_policy_binding": {
            **bindings("allowed_signers_file_sha256 signer_identity_file_sha256"),
            "signer_role": "independent_restore_reviewer",
        },
        "runner_identity_sha256": OTHER_DIGEST, "identities_distinct": True,
        "claims": {name: False for name in false_claims},
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def chain_bundle(checkpoint_tool, chain_tool):
    import base64

    document = checkpoint(checkpoint_tool)
    raw = json.dumps(document, sort_keys=True).encode("utf-8")
    raw_digest = hashlib.sha256(raw).hexdigest()
    signature = b"synthetic-schema-signature"
    entry = {
        "sequence": 0, "checkpoint_locator": "checkpoint-000000.json",
        "signature_locator": "checkpoint-000000.json.sig",
        "checkpoint_file_sha256": raw_digest,
        "signature_file_sha256": hashlib.sha256(signature).hexdigest(),
        "checkpoint_bytes_base64": base64.b64encode(raw).decode("ascii"),
        "signature_bytes_base64": base64.b64encode(signature).decode("ascii"),
    }
    return {
        "kind": "attestation_nonce_store_checkpoint_chain_bundle", "version": "1.0",
        "status": "CHAIN_BUNDLE_CANDIDATE", "checkpoint_count": 1,
        "genesis_checkpoint_sha256": raw_digest, "current_checkpoint_sha256": raw_digest,
        "ordered_chain_sha256": chain_tool.ordered_chain_sha256([entry]),
        "signature_policy_binding": document["signature_policy_binding"],
        "entries": [entry],
        "claims": {name: False for name in chain_tool.BUNDLE_FALSE_FIELDS},
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def readable_parse_companions(directory: Path):
    """Files read before a malformed primary document, never crypto fixtures."""
    result = {}
    for name, payload in {
        "json": b"{}", "signature": b"synthetic-unused-signature",
        "allowed": b"synthetic-unused-policy", "identity": b"synthetic-reviewer",
        "receipt": b"synthetic-unused-receipt", "store": b"",
    }.items():
        path = directory / name
        path.write_bytes(payload)
        result[name] = path
    return result
