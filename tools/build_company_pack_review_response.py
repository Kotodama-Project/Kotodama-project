#!/usr/bin/env python3
"""Create an editable, non-authorizing response for one saved review request."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import hashlib
import json
from pathlib import Path
from typing import Any

from verify_company_pack_review_bundle import (
    reject_duplicate_keys,
    reject_non_finite_constant,
)


PERMITTED_OUTCOMES = ["accept", "request_changes", "reject"]


def empty_claims() -> dict[str, bool]:
    return {
        "reviewer_identity_verified": False,
        "reviewer_authority_verified": False,
        "reviewer_independence_verified": False,
        "item_responses_structurally_verified": False,
        "human_approval_verified": False,
        "candidate_bound_human_decision_verified": False,
        "external_evidence_verified": False,
        "promotion_verified": False,
        "current_truth_changed": False,
        "runtime_ready": False,
        "final_human_go": False,
        "public_beta_go": False,
    }


def refusal(reason: str) -> dict[str, Any]:
    return {
        "kind": "company_pack_review_response",
        "version": "1.0",
        "status": "RESPONSE_BUILD_REFUSED",
        "reason": reason,
        "pack_id": None,
        "request_binding": None,
        "candidate_binding": None,
        "review_response": {
            "state": "NOT_CREATED",
            "item_count": 0,
            "items": [],
            "permitted_outcomes": PERMITTED_OUTCOMES,
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


def load_request(path: Path) -> tuple[dict[str, Any], bytes] | None:
    try:
        first = path.read_bytes()
        request = json.loads(
            first.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_non_finite_constant,
        )
        second = path.read_bytes()
    except (OSError, UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if first != second or not isinstance(request, dict):
        return None
    review = request.get("review_request")
    evidence = request.get("unresolved_evidence")
    if (
        request.get("kind") != "company_pack_review_request"
        or request.get("version") != "1.0"
        or request.get("status") != "CANDIDATE_REVIEW_REQUEST"
        or request.get("reason") is not None
        or not isinstance(request.get("pack_id"), str)
        or not isinstance(request.get("candidate_binding"), dict)
        or not isinstance(review, dict)
        or review.get("state") != "PENDING_AUTHORIZED_REVIEW"
        or review.get("permitted_outcomes") != PERMITTED_OUTCOMES
        or review.get("selected_outcome") is not None
        or not isinstance(review.get("items"), list)
        or review.get("item_count") != len(review["items"])
        or not isinstance(evidence, dict)
        or evidence.get("state") != "EVIDENCE_REQUIRED"
        or not isinstance(evidence.get("items"), list)
        or evidence.get("item_count") != len(evidence["items"])
        or not isinstance(request.get("claims"), dict)
        or not request["claims"]
        or any(value is not False for value in request["claims"].values())
        or request.get("public_beta") != "NO_GO_UNPUBLISHED"
    ):
        return None
    return request, first


def build_response_candidate(request_path: Path) -> dict[str, Any]:
    loaded = load_request(request_path)
    if loaded is None:
        return refusal("REQUEST_INVALID")
    request, request_bytes = loaded
    review = request["review_request"]
    return {
        "kind": "company_pack_review_response",
        "version": "1.0",
        "status": "REVIEW_RESPONSE_CANDIDATE",
        "reason": None,
        "pack_id": request["pack_id"],
        "request_binding": {
            "sha256": hashlib.sha256(request_bytes).hexdigest(),
            "bytes": len(request_bytes),
        },
        "candidate_binding": request["candidate_binding"],
        "review_response": {
            "state": "ITEM_RESPONSES_PENDING",
            "item_count": review["item_count"],
            "items": [
                {**item, "outcome": None, "reviewer_note": None}
                for item in review["items"]
            ],
            "permitted_outcomes": PERMITTED_OUTCOMES,
            "selected_outcome": None,
        },
        "unresolved_evidence": request["unresolved_evidence"],
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
    if len(argv) != 2:
        print(
            "usage: build_company_pack_review_response.py REQUEST_JSON",
            file=sys.stderr,
        )
        return 2
    response = build_response_candidate(Path(argv[1]))
    write_stdout_utf8(response)
    return 0 if response["status"] == "REVIEW_RESPONSE_CANDIDATE" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
