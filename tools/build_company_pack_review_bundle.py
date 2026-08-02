#!/usr/bin/env python3
"""Bind a review-ready Company pack to exact bytes without approving it."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from check_company_pack_customization import check_customization
from validate_template_pack import validate_pack


CANONICALIZATION = "utf8-json-sort-keys-no-whitespace-v1"


def empty_claims() -> dict[str, bool]:
    return {
        "human_intent_authenticated": False,
        "human_approval_verified": False,
        "authority_assignment_verified": False,
        "retention_policy_verified": False,
        "candidate_bound_human_decision_verified": False,
        "promotion_verified": False,
        "current_truth_changed": False,
        "runtime_ready": False,
        "final_human_go": False,
        "public_beta_go": False,
    }


def safe_pack_id(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def structural_summary(validation: dict[str, Any]) -> dict[str, Any]:
    count = validation.get("validated_files", 0)
    return {
        "status": "PASS" if validation.get("status") == "PASS" else "FAIL",
        "validated_files": count if isinstance(count, int) and count >= 0 else 0,
    }


def customization_summary(report: dict[str, Any]) -> dict[str, Any]:
    counts = report.get("counts", {})
    return {
        "status": report["status"],
        "counts": {
            key: int(counts.get(key, 0))
            for key in (
                "replacement_required",
                "review_required",
                "evidence_required",
            )
        },
    }


def refusal(
    reason: str,
    pack_id: object,
    structural: dict[str, Any],
    customization: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "kind": "company_pack_review_bundle",
        "version": "1.0",
        "status": "BUNDLE_REFUSED",
        "reason": reason,
        "pack_id": safe_pack_id(pack_id),
        "source_checks": {
            "structural_validation": structural,
            "customization": customization,
        },
        "bindings": [],
        "binding_count": 0,
        "bundle_digest": None,
        "claims": empty_claims(),
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def referenced_paths(pack_dir: Path) -> list[str]:
    manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    paths = [
        *manifest.get("blocks", []),
        *manifest.get("mocs", []),
        *manifest.get("records", []),
    ]
    return ["manifest.json", *sorted(paths)]


def capture_bindings(pack_dir: Path, paths: list[str]) -> list[dict[str, Any]]:
    pack_root = pack_dir.resolve()
    bindings: list[dict[str, Any]] = []
    for relative in paths:
        resolved = (pack_root / relative).resolve(strict=True)
        if resolved == pack_root or pack_root not in resolved.parents:
            raise ValueError("referenced path resolves outside the pack")
        data = resolved.read_bytes()
        bindings.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
            }
        )
    return bindings


def build_review_bundle(pack_dir: Path) -> dict[str, Any]:
    pack_dir = pack_dir.resolve()
    first_validation = validate_pack(pack_dir)
    first_structural = structural_summary(first_validation)
    pack_id = first_validation.get("pack_id")
    if first_validation.get("status") != "PASS":
        return refusal(
            "STRUCTURAL_VALIDATION_FAILED",
            pack_id,
            first_structural,
            None,
        )

    try:
        first_customization = check_customization(pack_dir)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return refusal(
            "SOURCE_DRIFT_DETECTED",
            pack_id,
            first_structural,
            None,
        )
    first_customization_status = first_customization.get("status")
    if first_customization_status not in {
        "CUSTOMIZATION_REQUIRED",
        "READY_FOR_GOVERNED_REVIEW",
    }:
        return refusal(
            "SOURCE_DRIFT_DETECTED",
            pack_id,
            first_structural,
            None,
        )
    if first_customization.get("pack_id") != pack_id:
        return refusal(
            "SOURCE_DRIFT_DETECTED",
            pack_id,
            first_structural,
            None,
        )
    first_customization_summary = customization_summary(first_customization)
    if first_customization_status == "CUSTOMIZATION_REQUIRED":
        return refusal(
            "CUSTOMIZATION_REQUIRED",
            pack_id,
            first_structural,
            first_customization_summary,
        )

    try:
        paths = referenced_paths(pack_dir)
        first_bindings = capture_bindings(pack_dir, paths)
        second_validation = validate_pack(pack_dir)
        second_customization = check_customization(pack_dir)
        second_bindings = capture_bindings(pack_dir, paths)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return refusal(
            "SOURCE_DRIFT_DETECTED",
            pack_id,
            first_structural,
            first_customization_summary,
        )

    second_structural = structural_summary(second_validation)
    second_customization_status = second_customization.get("status")
    if second_customization_status not in {
        "CUSTOMIZATION_REQUIRED",
        "READY_FOR_GOVERNED_REVIEW",
    }:
        return refusal(
            "SOURCE_DRIFT_DETECTED",
            pack_id,
            second_structural,
            None,
        )
    if (
        second_validation.get("pack_id") != pack_id
        or second_customization.get("pack_id") != pack_id
    ):
        return refusal(
            "SOURCE_DRIFT_DETECTED",
            pack_id,
            second_structural,
            None,
        )
    second_customization_summary = customization_summary(second_customization)
    if (
        second_validation.get("status") != "PASS"
        or second_customization.get("status") != "READY_FOR_GOVERNED_REVIEW"
        or first_bindings != second_bindings
    ):
        return refusal(
            "SOURCE_DRIFT_DETECTED",
            pack_id,
            second_structural,
            second_customization_summary,
        )

    canonical = json.dumps(
        second_bindings,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "kind": "company_pack_review_bundle",
        "version": "1.0",
        "status": "CANDIDATE_FOR_GOVERNED_REVIEW",
        "reason": None,
        "pack_id": safe_pack_id(pack_id),
        "source_checks": {
            "structural_validation": second_structural,
            "customization": second_customization_summary,
        },
        "bindings": second_bindings,
        "binding_count": len(second_bindings),
        "bundle_digest": {
            "algorithm": "SHA-256",
            "canonicalization": CANONICALIZATION,
            "value": hashlib.sha256(canonical).hexdigest(),
        },
        "claims": empty_claims(),
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "usage: build_company_pack_review_bundle.py PACK_DIRECTORY",
            file=sys.stderr,
        )
        return 2
    bundle = build_review_bundle(Path(argv[1]))
    print(json.dumps(bundle, ensure_ascii=False, sort_keys=True))
    return 0 if bundle["status"] == "CANDIDATE_FOR_GOVERNED_REVIEW" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
