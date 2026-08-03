#!/usr/bin/env python3
"""Prepare an exact, non-authorizing Company Pack review request."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import json
from pathlib import Path
from typing import Any

from build_company_pack_review_bundle import empty_claims
from check_company_pack_customization import check_customization
from verify_company_pack_review_bundle import (
    reject_duplicate_keys,
    reject_non_finite_constant,
    validate_saved_bundle,
    verify_saved_bundle,
)


def empty_counts() -> dict[str, int]:
    return {
        "replacement_required": 0,
        "review_required": 0,
        "evidence_required": 0,
    }


def refusal(reason: str) -> dict[str, Any]:
    return {
        "kind": "company_pack_review_request",
        "version": "1.0",
        "status": "REQUEST_REFUSED",
        "reason": reason,
        "pack_id": None,
        "candidate_binding": None,
        "source_checks": {
            "bundle_verification": {
                "status": "MISMATCH",
                "matched_bindings": 0,
            },
            "customization": {
                "status": None,
                "counts": empty_counts(),
            },
        },
        "review_request": {
            "state": "NOT_CREATED",
            "item_count": 0,
            "items": [],
            "permitted_outcomes": ["accept", "request_changes", "reject"],
            "selected_outcome": None,
        },
        "unresolved_evidence": {
            "state": "UNKNOWN",
            "item_count": 0,
            "items": [],
        },
        "claims": empty_claims(),
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def load_valid_saved_bundle(path: Path) -> tuple[dict[str, Any], bytes] | None:
    try:
        data = path.read_bytes()
        bundle = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_non_finite_constant,
        )
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None
    error, _trusted_digest = validate_saved_bundle(bundle)
    if error is not None:
        return None
    return bundle, data


def build_review_request(bundle_path: Path, pack_dir: Path) -> dict[str, Any]:
    first_verification = verify_saved_bundle(bundle_path, pack_dir)
    if first_verification.get("status") != "MATCH":
        return refusal("BUNDLE_VERIFICATION_FAILED")

    loaded = load_valid_saved_bundle(bundle_path)
    if loaded is None:
        return refusal("SOURCE_DRIFT_DETECTED")
    saved_bundle, saved_bytes = loaded

    try:
        first_customization = check_customization(pack_dir)
        second_verification = verify_saved_bundle(bundle_path, pack_dir)
        second_customization = check_customization(pack_dir)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return refusal("SOURCE_DRIFT_DETECTED")

    expected_counts = saved_bundle["source_checks"]["customization"]["counts"]
    if (
        first_verification != second_verification
        or second_verification.get("status") != "MATCH"
        or first_customization != second_customization
        or second_customization.get("status") != "READY_FOR_GOVERNED_REVIEW"
        or second_customization.get("pack_id") != saved_bundle.get("pack_id")
        or second_customization.get("counts") != expected_counts
    ):
        return refusal("SOURCE_DRIFT_DETECTED")

    review_items = [
        item
        for item in second_customization["items"]
        if item.get("category") == "review_required"
    ]
    evidence_items = [
        item
        for item in second_customization["items"]
        if item.get("category") == "evidence_required"
    ]
    if (
        len(review_items) != expected_counts["review_required"]
        or len(evidence_items) != expected_counts["evidence_required"]
        or expected_counts["replacement_required"] != 0
    ):
        return refusal("SOURCE_DRIFT_DETECTED")

    return {
        "kind": "company_pack_review_request",
        "version": "1.0",
        "status": "CANDIDATE_REVIEW_REQUEST",
        "reason": None,
        "pack_id": saved_bundle["pack_id"],
        "candidate_binding": {
            "saved_bundle": {
                "sha256": first_verification["saved_bundle"]["sha256"],
                "bytes": len(saved_bytes),
            },
            "bundle_digest": saved_bundle["bundle_digest"],
            "binding_count": saved_bundle["binding_count"],
        },
        "source_checks": {
            "bundle_verification": {
                "status": "MATCH",
                "matched_bindings": second_verification["matched_bindings"],
            },
            "customization": {
                "status": second_customization["status"],
                "counts": second_customization["counts"],
            },
        },
        "review_request": {
            "state": "PENDING_AUTHORIZED_REVIEW",
            "item_count": len(review_items),
            "items": review_items,
            "permitted_outcomes": ["accept", "request_changes", "reject"],
            "selected_outcome": None,
        },
        "unresolved_evidence": {
            "state": "EVIDENCE_REQUIRED",
            "item_count": len(evidence_items),
            "items": evidence_items,
        },
        "claims": empty_claims(),
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def write_stdout_utf8(payload: dict[str, Any]) -> None:
    data = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    stream = getattr(sys.stdout, "buffer", None)
    if stream is not None:
        stream.write(data)
        stream.flush()
        return
    sys.stdout.write(data.decode("utf-8"))


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            "usage: build_company_pack_review_request.py BUNDLE_JSON PACK_DIRECTORY",
            file=sys.stderr,
        )
        return 2
    request = build_review_request(Path(argv[1]), Path(argv[2]))
    write_stdout_utf8(request)
    return 0 if request["status"] == "CANDIDATE_REVIEW_REQUEST" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
