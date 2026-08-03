#!/usr/bin/env python3
"""Verify item-response structure without verifying reviewer authority or approval."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from build_company_pack_review_response import (
    PERMITTED_OUTCOMES,
    MAX_JSON_BYTES,
    SourceDriftError,
    empty_claims,
    exceeds_json_depth,
    exact_dict,
    load_request,
    write_stdout_utf8,
)


RESPONSE_KEYS = {
    "kind",
    "version",
    "status",
    "reason",
    "pack_id",
    "request_binding",
    "candidate_binding",
    "review_response",
    "unresolved_evidence",
    "claims",
    "public_beta",
}
SECRET_NOTE_RE = re.compile(
    r"(?i)(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|"
    r"AIza[0-9A-Za-z_-]{20,}|xox[baprs]-[0-9A-Za-z-]{10,}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
LOCAL_PATH_RE = re.compile(r"(?i)(?:[A-Za-z]:\\|/home/|/Users/|AppData\\)")
from verify_company_pack_review_bundle import (
    reject_duplicate_keys,
    reject_non_finite_constant,
)


def mismatch(reason: str) -> dict[str, Any]:
    return {
        "kind": "company_pack_review_response_verification",
        "version": "1.0",
        "status": "RESPONSE_MISMATCH",
        "reason": reason,
        "pack_id": None,
        "request_binding": None,
        "response_binding": None,
        "candidate_binding": None,
        "review_summary": {
            "state": "UNKNOWN",
            "expected_items": 0,
            "completed_items": 0,
            "outcome_counts": {
                "accept": 0,
                "request_changes": 0,
                "reject": 0,
            },
            "selected_outcome": None,
        },
        "unresolved_evidence": {"state": "UNKNOWN", "item_count": 0},
        "claims": empty_claims(),
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def load_response(path: Path) -> tuple[dict[str, Any], bytes] | None:
    try:
        first = path.read_bytes()
        if not first or len(first) > MAX_JSON_BYTES:
            return None
        response = json.loads(
            first.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_non_finite_constant,
        )
        second = path.read_bytes()
    except (
        OSError,
        UnicodeDecodeError,
        ValueError,
        TypeError,
        RecursionError,
        json.JSONDecodeError,
    ):
        return None
    if first != second:
        raise SourceDriftError
    if exceeds_json_depth(response) or not isinstance(response, dict):
        return None
    return response, first


def response_problem(response: dict[str, Any], request: dict[str, Any]) -> str | None:
    if not exact_dict(response, RESPONSE_KEYS):
        return "RESPONSE_INVALID"
    review = response.get("review_response")
    if (
        response.get("kind") != "company_pack_review_response"
        or response.get("version") != "1.0"
        or response.get("status") != "REVIEW_RESPONSE_CANDIDATE"
        or response.get("reason") is not None
        or not isinstance(review, dict)
        or review.get("state") != "ITEM_RESPONSES_PENDING"
        or review.get("permitted_outcomes") != PERMITTED_OUTCOMES
        or review.get("selected_outcome") is not None
        or not isinstance(review.get("items"), list)
        or not isinstance(response.get("claims"), dict)
        or response["claims"] != empty_claims()
        or response.get("public_beta") != "NO_GO_UNPUBLISHED"
    ):
        return "RESPONSE_INVALID"
    if (
        response.get("pack_id") != request["pack_id"]
        or response.get("candidate_binding") != request["candidate_binding"]
        or review.get("item_count") != request["review_request"]["item_count"]
        or len(review["items"]) != review["item_count"]
        or response.get("unresolved_evidence") != request["unresolved_evidence"]
    ):
        return "ITEM_BINDING_MISMATCH"
    expected_keys = {"id", "category", "path", "reason", "outcome", "reviewer_note"}
    for original, item in zip(
        request["review_request"]["items"], review["items"], strict=True
    ):
        if not isinstance(item, dict) or set(item) != expected_keys:
            return "RESPONSE_INVALID"
        if {key: item.get(key) for key in original} != original:
            return "ITEM_BINDING_MISMATCH"
        if item.get("outcome") is None:
            return "INCOMPLETE_ITEM_RESPONSES"
        if item.get("outcome") not in PERMITTED_OUTCOMES:
            return "RESPONSE_INVALID"
        note = item.get("reviewer_note")
        if note is not None and (
            not isinstance(note, str)
            or len(note) > 2000
            or SECRET_NOTE_RE.search(note) is not None
            or LOCAL_PATH_RE.search(note) is not None
        ):
            return "RESPONSE_INVALID"
        if item["outcome"] in {"request_changes", "reject"} and (
            not isinstance(note, str) or not note.strip()
        ):
            return "INCOMPLETE_ITEM_RESPONSES"
    return None


def verify_response(request_path: Path, response_path: Path) -> dict[str, Any]:
    try:
        loaded_request = load_request(request_path)
    except SourceDriftError:
        return mismatch("SOURCE_DRIFT_DETECTED")
    if loaded_request is None:
        return mismatch("REQUEST_INVALID")
    request, request_bytes = loaded_request
    try:
        loaded_response = load_response(response_path)
    except SourceDriftError:
        return mismatch("SOURCE_DRIFT_DETECTED")
    if loaded_response is None:
        return mismatch("RESPONSE_INVALID")
    response, response_bytes = loaded_response
    problem = response_problem(response, request)
    if problem == "RESPONSE_INVALID":
        return mismatch(problem)
    expected_request_binding = {
        "sha256": hashlib.sha256(request_bytes).hexdigest(),
        "bytes": len(request_bytes),
    }
    if response.get("request_binding") != expected_request_binding:
        return mismatch("ITEM_BINDING_MISMATCH")
    if problem is not None:
        return mismatch(problem)

    counts = {outcome: 0 for outcome in PERMITTED_OUTCOMES}
    for item in response["review_response"]["items"]:
        counts[item["outcome"]] += 1
    try:
        final_request_bytes = request_path.read_bytes()
        final_response_bytes = response_path.read_bytes()
    except OSError:
        return mismatch("SOURCE_DRIFT_DETECTED")
    if final_request_bytes != request_bytes or final_response_bytes != response_bytes:
        return mismatch("SOURCE_DRIFT_DETECTED")
    return {
        "kind": "company_pack_review_response_verification",
        "version": "1.0",
        "status": "ITEM_RESPONSES_MATCH_REQUEST",
        "reason": None,
        "pack_id": request["pack_id"],
        "request_binding": expected_request_binding,
        "response_binding": {
            "sha256": hashlib.sha256(response_bytes).hexdigest(),
            "bytes": len(response_bytes),
        },
        "candidate_binding": request["candidate_binding"],
        "review_summary": {
            "state": "ALL_ITEM_RESPONSES_PRESENT",
            "expected_items": request["review_request"]["item_count"],
            "completed_items": len(response["review_response"]["items"]),
            "outcome_counts": counts,
            "selected_outcome": None,
        },
        "unresolved_evidence": {
            "state": "EVIDENCE_REQUIRED",
            "item_count": request["unresolved_evidence"]["item_count"],
        },
        "claims": empty_claims(),
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            "usage: verify_company_pack_review_response.py REQUEST_JSON RESPONSE_JSON",
            file=sys.stderr,
        )
        return 2
    report = verify_response(Path(argv[1]), Path(argv[2]))
    write_stdout_utf8(report)
    return 0 if report["status"] == "ITEM_RESPONSES_MATCH_REQUEST" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
