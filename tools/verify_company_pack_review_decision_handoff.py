#!/usr/bin/env python3
"""Verify a review-to-Decision handoff without verifying a Human Decision."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

from pathlib import Path
from typing import Any

from build_company_pack_review_decision_handoff import (
    build_decision_handoff,
    empty_claims,
    empty_review_summary,
    file_binding,
    load_strict_json,
)
from build_company_pack_review_response import read_limited_bytes, write_stdout_utf8
from verify_company_pack_review_response import exact_json_equal


def mismatch(reason: str) -> dict[str, Any]:
    return {
        "kind": "company_pack_review_decision_handoff_verification",
        "version": "1.0",
        "status": "DECISION_HANDOFF_MISMATCH",
        "reason": reason,
        "pack_id": None,
        "artifact_bindings": None,
        "handoff_binding": None,
        "candidate_binding": None,
        "source_checks": {
            "current_bundle": {"status": "UNKNOWN", "matched_bindings": 0},
            "response": {"status": "UNKNOWN"},
        },
        "review_summary": empty_review_summary(),
        "unresolved_evidence": {"state": "UNKNOWN", "item_count": 0},
        "decision_requirements": {
            "state": "UNKNOWN",
            "selected_outcome": None,
        },
        "claims": empty_claims(),
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def verify_decision_handoff(
    bundle_path: Path,
    pack_dir: Path,
    bundle_verification_path: Path,
    request_path: Path,
    response_path: Path,
    response_verification_path: Path,
    handoff_path: Path,
) -> dict[str, Any]:
    loaded_handoff = load_strict_json(handoff_path)
    if loaded_handoff is None:
        return mismatch("HANDOFF_INVALID")
    handoff, handoff_bytes = loaded_handoff

    expected = build_decision_handoff(
        bundle_path,
        pack_dir,
        bundle_verification_path,
        request_path,
        response_path,
        response_verification_path,
    )
    if expected.get("status") != "CANDIDATE_DECISION_HANDOFF":
        return mismatch("SOURCE_INVALID")
    if not exact_json_equal(handoff, expected):
        return mismatch("HANDOFF_MISMATCH")

    final_expected = build_decision_handoff(
        bundle_path,
        pack_dir,
        bundle_verification_path,
        request_path,
        response_path,
        response_verification_path,
    )
    final_handoff_bytes = read_limited_bytes(handoff_path)
    if (
        not exact_json_equal(final_expected, expected)
        or final_handoff_bytes is None
        or final_handoff_bytes != handoff_bytes
    ):
        return mismatch("SOURCE_DRIFT_DETECTED")

    return {
        "kind": "company_pack_review_decision_handoff_verification",
        "version": "1.0",
        "status": "DECISION_HANDOFF_MATCH",
        "reason": None,
        "pack_id": handoff["pack_id"],
        "artifact_bindings": handoff["artifact_bindings"],
        "handoff_binding": file_binding(handoff_bytes),
        "candidate_binding": handoff["candidate_binding"],
        "source_checks": handoff["source_checks"],
        "review_summary": handoff["review_summary"],
        "unresolved_evidence": handoff["unresolved_evidence"],
        "decision_requirements": {
            "state": "HUMAN_DECISION_REQUIRED",
            "selected_outcome": None,
        },
        "claims": empty_claims(),
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 8:
        print(
            "usage: verify_company_pack_review_decision_handoff.py "
            "BUNDLE_JSON PACK_DIRECTORY BUNDLE_VERIFICATION_JSON "
            "REQUEST_JSON RESPONSE_JSON RESPONSE_VERIFICATION_JSON HANDOFF_JSON",
            file=sys.stderr,
        )
        return 2
    report = verify_decision_handoff(
        Path(argv[1]),
        Path(argv[2]),
        Path(argv[3]),
        Path(argv[4]),
        Path(argv[5]),
        Path(argv[6]),
        Path(argv[7]),
    )
    write_stdout_utf8(report)
    return 0 if report["status"] == "DECISION_HANDOFF_MATCH" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
