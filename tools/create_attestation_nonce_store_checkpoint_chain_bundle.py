#!/usr/bin/env python3
"""Create a deterministic self-contained private checkpoint-chain bundle."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

from create_attestation_nonce_store_checkpoint import (
    MAX_CHECKPOINT_BYTES,
    NAMESPACE,
    SIGNATURE_FIELDS,
    is_sha256,
    validate_checkpoint,
    write_new_file,
)
from validate_resolved_compose_candidate import canonical_sha256, load_strict_json_bytes
from verify_protected_compose_evidence_attestation import safe_read, sha256_bytes


MAX_CHAIN_CHECKPOINTS = 1024
MAX_BUNDLE_BYTES = 24 * 1024 * 1024
MAX_CHAIN_TOTAL_BYTES = 16 * 1024 * 1024
CHECKPOINT_NAME = re.compile(r"^checkpoint-([0-9]{6})\.json$")
BUNDLE_FIELDS = {
    "kind",
    "version",
    "status",
    "checkpoint_count",
    "genesis_checkpoint_sha256",
    "current_checkpoint_sha256",
    "ordered_chain_sha256",
    "signature_policy_binding",
    "entries",
    "claims",
    "public_beta",
}
ENTRY_FIELDS = {
    "sequence",
    "checkpoint_locator",
    "signature_locator",
    "checkpoint_file_sha256",
    "signature_file_sha256",
    "checkpoint_bytes_base64",
    "signature_bytes_base64",
}
BUNDLE_FALSE_FIELDS = {
    "checkpoint_signatures_verified",
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


def ordered_chain_sha256(entries: list[dict[str, Any]]) -> str:
    return canonical_sha256(entries)


def decode_canonical_base64(
    value: object, maximum: int, location: str, errors: list[str]
) -> bytes | None:
    if not isinstance(value, str) or len(value) > 4 * ((maximum + 2) // 3):
        errors.append(f"{location} is invalid")
        return None
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        errors.append(f"{location} is invalid")
        return None
    if (
        not decoded
        or len(decoded) > maximum
        or base64.b64encode(decoded).decode("ascii") != value
    ):
        errors.append(f"{location} is invalid")
        return None
    return decoded


def validate_chain_bundle(bundle: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(bundle, dict):
        return ["bundle must be an object"]
    require_exact_fields(bundle, BUNDLE_FIELDS, "bundle", errors)
    if bundle.get("kind") != "attestation_nonce_store_checkpoint_chain_bundle":
        errors.append("bundle kind is invalid")
    if bundle.get("version") != "1.0":
        errors.append("bundle version must be 1.0")
    if bundle.get("status") != "CHAIN_BUNDLE_CANDIDATE":
        errors.append("bundle status must remain CHAIN_BUNDLE_CANDIDATE")
    count = bundle.get("checkpoint_count")
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or not 1 <= count <= MAX_CHAIN_CHECKPOINTS
    ):
        errors.append("checkpoint_count is invalid")
    entries = bundle.get("entries")
    if not isinstance(entries, list):
        errors.append("entries must be an array")
        entries = []
    elif count != len(entries):
        errors.append("checkpoint_count mismatch")
    validated_entries: list[dict[str, Any]] = []
    aggregate_bytes = 0
    for index, value in enumerate(entries):
        entry = require_exact_fields(value, ENTRY_FIELDS, f"entry {index}", errors)
        if entry is None:
            continue
        expected_checkpoint = f"checkpoint-{index:06d}.json"
        sequence = entry.get("sequence")
        if (
            isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence != index
        ):
            errors.append(f"entry {index} sequence mismatch")
        if entry.get("checkpoint_locator") != expected_checkpoint:
            errors.append(f"entry {index} checkpoint locator mismatch")
        if entry.get("signature_locator") != expected_checkpoint + ".sig":
            errors.append(f"entry {index} signature locator mismatch")
        if not is_sha256(entry.get("checkpoint_file_sha256")):
            errors.append(f"entry {index} checkpoint digest is invalid")
        if not is_sha256(entry.get("signature_file_sha256")):
            errors.append(f"entry {index} signature digest is invalid")
        checkpoint_bytes = decode_canonical_base64(
            entry.get("checkpoint_bytes_base64"),
            MAX_CHECKPOINT_BYTES,
            f"entry {index} checkpoint bytes",
            errors,
        )
        signature_bytes = decode_canonical_base64(
            entry.get("signature_bytes_base64"),
            64 * 1024,
            f"entry {index} signature bytes",
            errors,
        )
        if checkpoint_bytes is not None:
            aggregate_bytes += len(checkpoint_bytes)
            if entry.get("checkpoint_file_sha256") != sha256_bytes(checkpoint_bytes):
                errors.append(f"entry {index} checkpoint digest mismatch")
        if signature_bytes is not None:
            aggregate_bytes += len(signature_bytes)
            if entry.get("signature_file_sha256") != sha256_bytes(signature_bytes):
                errors.append(f"entry {index} signature digest mismatch")
        validated_entries.append(entry)
    if aggregate_bytes > MAX_CHAIN_TOTAL_BYTES:
        errors.append("bundle exceeds aggregate byte limit")
    if entries and len(validated_entries) == len(entries):
        if bundle.get("genesis_checkpoint_sha256") != validated_entries[0].get(
            "checkpoint_file_sha256"
        ):
            errors.append("genesis checkpoint digest mismatch")
        if bundle.get("current_checkpoint_sha256") != validated_entries[-1].get(
            "checkpoint_file_sha256"
        ):
            errors.append("current checkpoint digest mismatch")
    else:
        if not is_sha256(bundle.get("genesis_checkpoint_sha256")):
            errors.append("genesis checkpoint digest is invalid")
        if not is_sha256(bundle.get("current_checkpoint_sha256")):
            errors.append("current checkpoint digest is invalid")
    if not is_sha256(bundle.get("ordered_chain_sha256")):
        errors.append("ordered_chain_sha256 is invalid")
    elif bundle.get("ordered_chain_sha256") != ordered_chain_sha256(validated_entries):
        errors.append("ordered chain digest mismatch")

    signature = require_exact_fields(
        bundle.get("signature_policy_binding"),
        SIGNATURE_FIELDS,
        "signature_policy_binding",
        errors,
    )
    if signature is not None:
        if signature.get("namespace") != NAMESPACE:
            errors.append("signature namespace is invalid")
        if not is_sha256(signature.get("allowed_signers_file_sha256")):
            errors.append("allowed signers binding is invalid")
        if not is_sha256(signature.get("signer_identity_sha256")):
            errors.append("signer identity binding is invalid")
        if signature.get("signer_role") != "independent_reviewer":
            errors.append("signer role is invalid")
    claims = require_exact_fields(
        bundle.get("claims"), BUNDLE_FALSE_FIELDS, "claims", errors
    )
    if claims is not None:
        for field in BUNDLE_FALSE_FIELDS:
            if claims.get(field) is not False:
                errors.append(f"claim {field} must remain false")
    if bundle.get("public_beta") != "NO_GO_UNPUBLISHED":
        errors.append("public_beta must remain NO_GO_UNPUBLISHED")
    return sorted(set(errors))


def read_chain_directory(
    root: Path,
) -> tuple[list[dict[str, Any]] | None, list[str]]:
    try:
        root_resolved = root.resolve(strict=True)
        root_before = os.stat(root_resolved, follow_symlinks=False)
    except OSError:
        return None, ["chain directory is invalid"]
    if root.is_symlink() or not stat.S_ISDIR(root_before.st_mode):
        return None, ["chain directory is invalid"]
    children: list[Path] = []
    declared_total_bytes = 0
    try:
        for child in root.iterdir():
            children.append(child)
            if len(children) > MAX_CHAIN_CHECKPOINTS * 2:
                return None, ["chain directory exceeds entry limit"]
            child_stat = child.stat(follow_symlinks=False)
            declared_total_bytes += child_stat.st_size
            if declared_total_bytes > MAX_CHAIN_TOTAL_BYTES:
                return None, ["chain directory exceeds aggregate byte limit"]
    except OSError:
        return None, ["chain directory is invalid"]
    checkpoint_sequences: set[int] = set()
    signature_sequences: set[int] = set()
    for child in children:
        try:
            child_resolved = child.resolve(strict=True)
        except OSError:
            return None, ["chain directory contains an invalid entry"]
        if (
            child.is_symlink()
            or not child.is_file()
            or child_resolved.parent != root_resolved
        ):
            return None, ["chain directory contains an invalid entry"]
        match = CHECKPOINT_NAME.fullmatch(child.name)
        if match is not None:
            checkpoint_sequences.add(int(match.group(1)))
            continue
        if child.name.endswith(".sig"):
            match = CHECKPOINT_NAME.fullmatch(child.name[:-4])
            if match is not None:
                signature_sequences.add(int(match.group(1)))
                continue
        return None, ["chain directory contains an unknown entry"]
    if (
        not checkpoint_sequences
        or checkpoint_sequences != signature_sequences
        or len(checkpoint_sequences) > MAX_CHAIN_CHECKPOINTS
        or checkpoint_sequences != set(range(len(checkpoint_sequences)))
    ):
        return None, ["checkpoint and signature sequence is invalid"]

    chain: list[dict[str, Any]] = []
    errors: list[str] = []
    actual_total_bytes = 0
    for sequence in range(len(checkpoint_sequences)):
        checkpoint_name = f"checkpoint-{sequence:06d}.json"
        try:
            checkpoint_bytes = safe_read(
                root / checkpoint_name, maximum=MAX_CHECKPOINT_BYTES
            )
            signature_bytes = safe_read(
                root / (checkpoint_name + ".sig"), maximum=64 * 1024
            )
            actual_total_bytes += len(checkpoint_bytes) + len(signature_bytes)
            if actual_total_bytes > MAX_CHAIN_TOTAL_BYTES:
                raise ValueError
            checkpoint = load_strict_json_bytes(checkpoint_bytes)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            errors.append(f"checkpoint {sequence} input is invalid")
            continue
        if not isinstance(checkpoint, dict):
            errors.append(f"checkpoint {sequence} structure is invalid")
            continue
        checkpoint_errors = validate_checkpoint(checkpoint)
        if checkpoint_errors:
            errors.append(f"checkpoint {sequence} structure is invalid")
        chain.append(
            {
                "sequence": sequence,
                "checkpoint_locator": checkpoint_name,
                "signature_locator": checkpoint_name + ".sig",
                "checkpoint_file_sha256": sha256_bytes(checkpoint_bytes),
                "signature_file_sha256": sha256_bytes(signature_bytes),
                "checkpoint_bytes": checkpoint_bytes,
                "signature_bytes": signature_bytes,
                "checkpoint": checkpoint,
            }
        )
    if errors or len(chain) != len(checkpoint_sequences):
        return None, sorted(set(errors or ["checkpoint chain could not be read"]))

    try:
        root_after = os.stat(root_resolved, follow_symlinks=False)
    except OSError:
        return None, ["chain directory changed during read"]
    stable_fields = ("st_dev", "st_ino", "st_mtime_ns", "st_ctime_ns")
    if any(
        getattr(root_before, field) != getattr(root_after, field)
        for field in stable_fields
    ):
        return None, ["chain directory changed during read"]

    errors.extend(validate_chain_relationships(chain))
    if errors:
        return None, sorted(set(errors))
    return chain, []


def validate_chain_relationships(chain: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    if not chain:
        return ["checkpoint chain is empty"]
    first = chain[0]["checkpoint"]
    if first.get("parent_binding", {}).get("mode") != "GENESIS":
        errors.append("checkpoint 0 must be Genesis")
    signature_policy = first.get("signature_policy_binding")
    store_id = first.get("store_binding", {}).get("store_id_sha256")
    for sequence, item in enumerate(chain):
        checkpoint = item["checkpoint"]
        if checkpoint.get("signature_policy_binding") != signature_policy:
            errors.append("checkpoint signer policy changed within the chain")
        if checkpoint.get("store_binding", {}).get("store_id_sha256") != store_id:
            errors.append("checkpoint store identity changed within the chain")
        if sequence == 0:
            continue
        previous = chain[sequence - 1]
        parent = checkpoint.get("parent_binding", {})
        if parent.get("mode") != "SUCCESSOR":
            errors.append(f"checkpoint {sequence} is not successor-bound")
        if parent.get("parent_checkpoint_file_sha256") != previous.get(
            "checkpoint_file_sha256"
        ) or parent.get("parent_checkpoint_chain_sha256") != previous[
            "checkpoint"
        ].get("checkpoint_chain_sha256"):
            errors.append(f"checkpoint {sequence} parent binding mismatch")
        previous_reservations = set(
            previous["checkpoint"].get("store_binding", {}).get(
                "reservation_sha256s", []
            )
        )
        current_reservations = set(
            checkpoint.get("store_binding", {}).get("reservation_sha256s", [])
        )
        if not previous_reservations.issubset(current_reservations):
            errors.append(f"checkpoint {sequence} is not an append-only extension")
    return sorted(set(errors))


def bundle_entries(chain: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "sequence": item["sequence"],
            "checkpoint_locator": item["checkpoint_locator"],
            "signature_locator": item["signature_locator"],
            "checkpoint_file_sha256": item["checkpoint_file_sha256"],
            "signature_file_sha256": item["signature_file_sha256"],
            "checkpoint_bytes_base64": base64.b64encode(
                item["checkpoint_bytes"]
            ).decode("ascii"),
            "signature_bytes_base64": base64.b64encode(
                item["signature_bytes"]
            ).decode("ascii"),
        }
        for item in chain
    ]


def chain_from_bundle(
    bundle: object,
) -> tuple[list[dict[str, Any]] | None, list[str]]:
    errors = validate_chain_bundle(bundle)
    if errors or not isinstance(bundle, dict):
        return None, sorted(set(errors))
    entries = bundle.get("entries")
    if not isinstance(entries, list):
        return None, ["entries must be an array"]
    chain: list[dict[str, Any]] = []
    for sequence, value in enumerate(entries):
        if not isinstance(value, dict):
            return None, [f"checkpoint {sequence} structure is invalid"]
        checkpoint_bytes = decode_canonical_base64(
            value.get("checkpoint_bytes_base64"),
            MAX_CHECKPOINT_BYTES,
            f"entry {sequence} checkpoint bytes",
            errors,
        )
        signature_bytes = decode_canonical_base64(
            value.get("signature_bytes_base64"),
            64 * 1024,
            f"entry {sequence} signature bytes",
            errors,
        )
        if checkpoint_bytes is None or signature_bytes is None:
            continue
        try:
            checkpoint = load_strict_json_bytes(checkpoint_bytes)
        except (
            UnicodeError,
            json.JSONDecodeError,
            RecursionError,
            TypeError,
            ValueError,
        ):
            errors.append(f"checkpoint {sequence} input is invalid")
            continue
        if not isinstance(checkpoint, dict) or validate_checkpoint(checkpoint):
            errors.append(f"checkpoint {sequence} structure is invalid")
            continue
        chain.append(
            {
                "sequence": sequence,
                "checkpoint_locator": value["checkpoint_locator"],
                "signature_locator": value["signature_locator"],
                "checkpoint_file_sha256": value["checkpoint_file_sha256"],
                "signature_file_sha256": value["signature_file_sha256"],
                "checkpoint_bytes": checkpoint_bytes,
                "signature_bytes": signature_bytes,
                "checkpoint": checkpoint,
            }
        )
    if errors or len(chain) != len(entries):
        return None, sorted(set(errors or ["checkpoint bundle is invalid"]))
    errors.extend(validate_chain_relationships(chain))
    if bundle.get("signature_policy_binding") != chain[0]["checkpoint"].get(
        "signature_policy_binding"
    ):
        errors.append("bundle signer policy does not match checkpoint chain")
    if errors:
        return None, sorted(set(errors))
    return chain, []


def creation_report(
    status: str,
    errors: list[str],
    *,
    bundle_bytes: bytes | None = None,
    checkpoint_count: int | None = None,
) -> dict[str, Any]:
    return {
        "kind": "attestation_nonce_store_checkpoint_chain_bundle_creation",
        "version": "1.0",
        "status": status,
        "errors": errors,
        "bundle_file_sha256": (
            sha256_bytes(bundle_bytes) if bundle_bytes is not None else None
        ),
        "checkpoint_count": checkpoint_count,
        "claims": {
            "private_bundle_candidate_created": status == "CHAIN_BUNDLE_CREATED",
            "checkpoint_signatures_verified": False,
            "external_anchor_authority_verified": False,
            "trusted_clock_source_verified": False,
            "authoritative_complete_history_verified": False,
            "parallel_branch_absence_verified": False,
            "key_rotation_verified": False,
            "store_continuity_verified": False,
            "backup_creation_verified": False,
            "restore_execution_verified": False,
            "public_beta_go": False,
        },
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 4 or argv[2] != "--output":
        print(
            "usage: create_attestation_nonce_store_checkpoint_chain_bundle.py "
            "CHAIN_DIRECTORY --output PRIVATE_CHAIN_BUNDLE_JSON",
            file=sys.stderr,
        )
        return 2
    try:
        root = Path(argv[1])
        output = Path(argv[3])
        if root.is_symlink() or not root.is_dir():
            raise ValueError
        root_resolved = root.resolve()
        output_parent = output.parent.resolve()
        if output_parent == root_resolved or output_parent.is_relative_to(root_resolved):
            raise ValueError
        chain, chain_errors = read_chain_directory(root)
        if chain_errors or chain is None:
            raise ValueError
        entries = bundle_entries(chain)
        bundle = {
            "kind": "attestation_nonce_store_checkpoint_chain_bundle",
            "version": "1.0",
            "status": "CHAIN_BUNDLE_CANDIDATE",
            "checkpoint_count": len(entries),
            "genesis_checkpoint_sha256": entries[0]["checkpoint_file_sha256"],
            "current_checkpoint_sha256": entries[-1]["checkpoint_file_sha256"],
            "ordered_chain_sha256": ordered_chain_sha256(entries),
            "signature_policy_binding": chain[0]["checkpoint"][
                "signature_policy_binding"
            ],
            "entries": entries,
            "claims": {field: False for field in sorted(BUNDLE_FALSE_FIELDS)},
            "public_beta": "NO_GO_UNPUBLISHED",
        }
        if validate_chain_bundle(bundle):
            raise ValueError
        bundle_bytes = (
            json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        if len(bundle_bytes) > MAX_BUNDLE_BYTES:
            raise ValueError
        write_new_file(output, bundle_bytes)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        print(
            json.dumps(
                creation_report("INVALID", ["chain bundle creation failed"]),
                sort_keys=True,
            )
        )
        return 1
    print(
        json.dumps(
            creation_report(
                "CHAIN_BUNDLE_CREATED",
                [],
                bundle_bytes=bundle_bytes,
                checkpoint_count=len(entries),
            ),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
