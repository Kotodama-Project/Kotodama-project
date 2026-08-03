#!/usr/bin/env python3
"""Bind a complete review chain for a separate Human Decision step."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import hashlib
import json
from pathlib import Path
from typing import Any

from build_company_pack_review_request import build_review_request
from build_company_pack_review_response import (
    MAX_JSON_BYTES,
    exceeds_json_depth,
    read_limited_bytes,
    write_stdout_utf8,
)
from verify_company_pack_review_bundle import (
    reject_duplicate_keys,
    reject_non_finite_constant,
    validate_saved_bundle,
    verify_saved_bundle,
)
from verify_company_pack_review_response import exact_json_equal, verify_response


ARTIFACT_NAMES = (
    "bundle",
    "bundle_verification",
    "request",
    "response",
    "response_verification",
)
PERMITTED_OUTCOMES = ["accept", "request_changes", "reject"]
REQUIRED_DECISION_FIELDS = [
    "decision_id",
    "intent_candidate_ref",
    "reviewer_identity_ref",
    "reviewer_role",
    "reviewer_authority_ref",
    "reviewer_independence_ref",
    "reviewed_at",
    "decision_maker_identity_ref",
    "decision_maker_role",
    "decision_maker_authority_ref",
    "decided_at",
    "selected_outcome",
    "scope",
    "reason",
    "expires_at",
    "review_trigger",
    "unresolved_evidence_refs",
    "artifact_bindings",
    "candidate_binding",
    "retention_policy_ref",
]


def empty_claims() -> dict[str, bool]:
    return {
        "reviewer_identity_verified": False,
        "reviewer_authority_verified": False,
        "reviewer_independence_verified": False,
        "decision_maker_identity_verified": False,
        "decision_maker_authority_verified": False,
        "governed_review_completed": False,
        "human_approval_verified": False,
        "candidate_bound_human_decision_verified": False,
        "external_evidence_verified": False,
        "promotion_verified": False,
        "current_truth_changed": False,
        "runtime_ready": False,
        "final_human_go": False,
        "public_beta_go": False,
    }


def empty_review_summary() -> dict[str, Any]:
    return {
        "state": "UNKNOWN",
        "expected_items": 0,
        "completed_items": 0,
        "outcome_counts": {outcome: 0 for outcome in PERMITTED_OUTCOMES},
        "selected_outcome": None,
    }


def refusal(reason: str) -> dict[str, Any]:
    return {
        "kind": "company_pack_review_decision_handoff",
        "version": "1.0",
        "status": "HANDOFF_BUILD_REFUSED",
        "reason": reason,
        "pack_id": None,
        "artifact_bindings": None,
        "candidate_binding": None,
        "source_checks": {
            "current_bundle": {"status": "UNKNOWN", "matched_bindings": 0},
            "response": {"status": "UNKNOWN"},
        },
        "review_summary": empty_review_summary(),
        "unresolved_evidence": {"state": "UNKNOWN", "item_count": 0},
        "decision_requirements": {
            "state": "NOT_CREATED",
            "required_fields": [],
            "permitted_outcomes": PERMITTED_OUTCOMES,
            "decision": None,
            "selected_outcome": None,
        },
        "claims": empty_claims(),
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def load_strict_json(path: Path) -> tuple[dict[str, Any], bytes] | None:
    data = read_limited_bytes(path)
    if data is None:
        return None
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_non_finite_constant,
        )
    except (
        UnicodeDecodeError,
        ValueError,
        TypeError,
        RecursionError,
        json.JSONDecodeError,
    ):
        return None
    if not isinstance(value, dict) or exceeds_json_depth(value):
        return None
    return value, data


def file_binding(data: bytes) -> dict[str, Any]:
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def build_decision_handoff(
    bundle_path: Path,
    pack_dir: Path,
    bundle_verification_path: Path,
    request_path: Path,
    response_path: Path,
    response_verification_path: Path,
) -> dict[str, Any]:
    paths = {
        "bundle": bundle_path,
        "bundle_verification": bundle_verification_path,
        "request": request_path,
        "response": response_path,
        "response_verification": response_verification_path,
    }
    loaded: dict[str, tuple[dict[str, Any], bytes]] = {}
    for name in ARTIFACT_NAMES:
        artifact = load_strict_json(paths[name])
        if artifact is None:
            return refusal("SOURCE_INVALID")
        loaded[name] = artifact

    bundle, bundle_bytes = loaded["bundle"]
    bundle_error, _bundle_digest = validate_saved_bundle(bundle)
    if bundle_error is not None:
        return refusal("SOURCE_INVALID")

    try:
        current_bundle_report = verify_saved_bundle(bundle_path, pack_dir)
        expected_request = build_review_request(bundle_path, pack_dir)
        expected_response_report = verify_response(request_path, response_path)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return refusal("SOURCE_INVALID")

    bundle_report = loaded["bundle_verification"][0]
    request = loaded["request"][0]
    response_report = loaded["response_verification"][0]
    if (
        current_bundle_report.get("status") != "MATCH"
        or expected_request.get("status") != "CANDIDATE_REVIEW_REQUEST"
        or expected_response_report.get("status")
        != "ITEM_RESPONSES_MATCH_REQUEST"
        or not exact_json_equal(bundle_report, current_bundle_report)
        or not exact_json_equal(request, expected_request)
        or not exact_json_equal(response_report, expected_response_report)
    ):
        return refusal("CHAIN_MISMATCH")

    expected_candidate_binding = {
        "saved_bundle": file_binding(bundle_bytes),
        "bundle_digest": bundle["bundle_digest"],
        "binding_count": bundle["binding_count"],
    }
    if (
        not exact_json_equal(request.get("candidate_binding"), expected_candidate_binding)
        or not exact_json_equal(
            response_report.get("candidate_binding"), expected_candidate_binding
        )
        or response_report.get("pack_id") != bundle.get("pack_id")
        or response_report.get("review_summary", {}).get("expected_items") != 46
        or response_report.get("review_summary", {}).get("completed_items") != 46
        or response_report.get("unresolved_evidence")
        != {"state": "EVIDENCE_REQUIRED", "item_count": 5}
    ):
        return refusal("CHAIN_MISMATCH")

    try:
        final_bundle_report = verify_saved_bundle(bundle_path, pack_dir)
        final_request = build_review_request(bundle_path, pack_dir)
        final_response_report = verify_response(request_path, response_path)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return refusal("SOURCE_DRIFT_DETECTED")
    if (
        not exact_json_equal(final_bundle_report, current_bundle_report)
        or not exact_json_equal(final_request, expected_request)
        or not exact_json_equal(final_response_report, expected_response_report)
    ):
        return refusal("SOURCE_DRIFT_DETECTED")
    for name in ARTIFACT_NAMES:
        final_data = read_limited_bytes(paths[name])
        if final_data is None or final_data != loaded[name][1]:
            return refusal("SOURCE_DRIFT_DETECTED")

    return {
        "kind": "company_pack_review_decision_handoff",
        "version": "1.0",
        "status": "CANDIDATE_DECISION_HANDOFF",
        "reason": None,
        "pack_id": bundle["pack_id"],
        "artifact_bindings": {
            name: file_binding(loaded[name][1]) for name in ARTIFACT_NAMES
        },
        "candidate_binding": expected_candidate_binding,
        "source_checks": {
            "current_bundle": {
                "status": "MATCH",
                "matched_bindings": current_bundle_report["matched_bindings"],
            },
            "response": {"status": "ITEM_RESPONSES_MATCH_REQUEST"},
        },
        "review_summary": response_report["review_summary"],
        "unresolved_evidence": response_report["unresolved_evidence"],
        "decision_requirements": {
            "state": "HUMAN_DECISION_REQUIRED",
            "required_fields": REQUIRED_DECISION_FIELDS,
            "permitted_outcomes": PERMITTED_OUTCOMES,
            "decision": None,
            "selected_outcome": None,
        },
        "claims": empty_claims(),
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 7:
        print(
            "usage: build_company_pack_review_decision_handoff.py "
            "BUNDLE_JSON PACK_DIRECTORY BUNDLE_VERIFICATION_JSON "
            "REQUEST_JSON RESPONSE_JSON RESPONSE_VERIFICATION_JSON",
            file=sys.stderr,
        )
        return 2
    handoff = build_decision_handoff(
        Path(argv[1]),
        Path(argv[2]),
        Path(argv[3]),
        Path(argv[4]),
        Path(argv[5]),
        Path(argv[6]),
    )
    write_stdout_utf8(handoff)
    return 0 if handoff["status"] == "CANDIDATE_DECISION_HANDOFF" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
