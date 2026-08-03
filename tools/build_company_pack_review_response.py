#!/usr/bin/env python3
"""Create an editable, non-authorizing response for one saved review request."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from verify_company_pack_review_bundle import (
    reject_duplicate_keys,
    reject_non_finite_constant,
)


PERMITTED_OUTCOMES = ["accept", "request_changes", "reject"]
MAX_JSON_BYTES = 1024 * 1024
MAX_JSON_DEPTH = 64
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PACK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
REQUEST_KEYS = {
    "kind",
    "version",
    "status",
    "reason",
    "pack_id",
    "candidate_binding",
    "source_checks",
    "review_request",
    "unresolved_evidence",
    "claims",
    "public_beta",
}
REQUEST_CLAIM_KEYS = {
    "human_intent_authenticated",
    "human_approval_verified",
    "authority_assignment_verified",
    "retention_policy_verified",
    "candidate_bound_human_decision_verified",
    "promotion_verified",
    "current_truth_changed",
    "runtime_ready",
    "final_human_go",
    "public_beta_go",
}


class SourceDriftError(Exception):
    """The evaluated file changed between bounded reads."""


def empty_claims() -> dict[str, bool]:
    return {
        "reviewer_identity_verified": False,
        "reviewer_authority_verified": False,
        "reviewer_independence_verified": False,
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


def exceeds_json_depth(value: Any) -> bool:
    stack = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > MAX_JSON_DEPTH:
            return True
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
    return False


def exact_dict(value: Any, keys: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == keys


def valid_item_path(value: Any) -> bool:
    if not isinstance(value, str) or not 1 <= len(value) <= 512:
        return False
    if "\x00" in value or "\\" in value or value.startswith(("/", "~")):
        return False
    document_path = value.split("#", 1)[0]
    if re.match(r"^[A-Za-z]:", document_path):
        return False
    return all(part not in {"", ".", ".."} for part in document_path.split("/"))


def valid_review_item(item: Any, category: str) -> bool:
    return (
        exact_dict(item, {"id", "category", "path", "reason"})
        and isinstance(item["id"], str)
        and 1 <= len(item["id"]) <= 512
        and item["category"] == category
        and valid_item_path(item["path"])
        and isinstance(item["reason"], str)
        and 1 <= len(item["reason"]) <= 2000
    )


def valid_candidate_binding(value: Any) -> bool:
    if not exact_dict(value, {"saved_bundle", "bundle_digest", "binding_count"}):
        return False
    saved = value["saved_bundle"]
    digest = value["bundle_digest"]
    return (
        exact_dict(saved, {"sha256", "bytes"})
        and isinstance(saved["sha256"], str)
        and SHA256_RE.fullmatch(saved["sha256"]) is not None
        and type(saved["bytes"]) is int
        and saved["bytes"] > 0
        and exact_dict(digest, {"algorithm", "canonicalization", "value"})
        and digest["algorithm"] == "SHA-256"
        and digest["canonicalization"] == "utf8-json-sort-keys-no-whitespace-v1"
        and isinstance(digest["value"], str)
        and SHA256_RE.fullmatch(digest["value"]) is not None
        and value["binding_count"] == 22
    )


def valid_request(request: Any) -> bool:
    if not exact_dict(request, REQUEST_KEYS):
        return False
    pack_id = request["pack_id"]
    source_checks = request["source_checks"]
    review = request["review_request"]
    evidence = request["unresolved_evidence"]
    claims = request["claims"]
    if (
        request["kind"] != "company_pack_review_request"
        or request["version"] != "1.0"
        or request["status"] != "CANDIDATE_REVIEW_REQUEST"
        or request["reason"] is not None
        or not isinstance(pack_id, str)
        or PACK_ID_RE.fullmatch(pack_id) is None
        or not valid_candidate_binding(request["candidate_binding"])
        or not exact_dict(source_checks, {"bundle_verification", "customization"})
        or not exact_dict(
            source_checks["bundle_verification"], {"status", "matched_bindings"}
        )
        or source_checks["bundle_verification"]
        != {"status": "MATCH", "matched_bindings": 22}
        or not exact_dict(source_checks["customization"], {"status", "counts"})
        or source_checks["customization"]["status"] != "READY_FOR_GOVERNED_REVIEW"
        or source_checks["customization"]["counts"]
        != {
            "replacement_required": 0,
            "review_required": 46,
            "evidence_required": 5,
        }
        or not exact_dict(
            review,
            {"state", "item_count", "items", "permitted_outcomes", "selected_outcome"},
        )
        or review["state"] != "PENDING_AUTHORIZED_REVIEW"
        or review["item_count"] != 46
        or not isinstance(review["items"], list)
        or len(review["items"]) != 46
        or review["permitted_outcomes"] != PERMITTED_OUTCOMES
        or review["selected_outcome"] is not None
        or not exact_dict(evidence, {"state", "item_count", "items"})
        or evidence["state"] != "EVIDENCE_REQUIRED"
        or evidence["item_count"] != 5
        or not isinstance(evidence["items"], list)
        or len(evidence["items"]) != 5
        or not exact_dict(claims, REQUEST_CLAIM_KEYS)
        or any(value is not False for value in claims.values())
        or request["public_beta"] != "NO_GO_UNPUBLISHED"
    ):
        return False
    if not all(valid_review_item(item, "review_required") for item in review["items"]):
        return False
    if not all(valid_review_item(item, "evidence_required") for item in evidence["items"]):
        return False
    review_ids = [item["id"] for item in review["items"]]
    review_paths = [item["path"] for item in review["items"]]
    evidence_ids = [item["id"] for item in evidence["items"]]
    evidence_paths = [item["path"] for item in evidence["items"]]
    return (
        len(set(review_ids)) == len(review_ids)
        and len(set(review_paths)) == len(review_paths)
        and len(set(evidence_ids)) == len(evidence_ids)
        and len(set(evidence_paths)) == len(evidence_paths)
        and not set(review_ids).intersection(evidence_ids)
    )


def load_request(path: Path) -> tuple[dict[str, Any], bytes] | None:
    try:
        first = path.read_bytes()
        if not first or len(first) > MAX_JSON_BYTES:
            return None
        request = json.loads(
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
    if exceeds_json_depth(request) or not valid_request(request):
        return None
    return request, first


def build_response_candidate(request_path: Path) -> dict[str, Any]:
    try:
        loaded = load_request(request_path)
    except SourceDriftError:
        return refusal("SOURCE_DRIFT_DETECTED")
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
