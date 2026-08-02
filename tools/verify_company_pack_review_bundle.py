#!/usr/bin/env python3
"""Verify saved Company pack bindings without approving or promoting them."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from build_company_pack_review_bundle import (
    CANONICALIZATION,
    build_review_bundle,
    empty_claims,
)
from validate_template_pack import ID_PATTERN, is_safe_relative_json_path


HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
BUNDLE_KEYS = {
    "kind",
    "version",
    "status",
    "reason",
    "pack_id",
    "source_checks",
    "bindings",
    "binding_count",
    "bundle_digest",
    "claims",
    "public_beta",
}
COUNT_KEYS = {
    "replacement_required",
    "review_required",
    "evidence_required",
}
METADATA_KEYS = {
    "kind",
    "version",
    "status",
    "reason",
    "pack_id",
    "source_checks",
    "binding_count",
    "claims",
    "public_beta",
}


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and HEX_SHA256.fullmatch(value) is not None


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_non_finite_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")


def saved_bundle_summary(
    data: bytes | None, bundle_digest: str | None
) -> dict[str, Any]:
    return {
        "sha256": hashlib.sha256(data).hexdigest() if data is not None else None,
        "bytes": len(data) if data is not None else 0,
        "bundle_digest": bundle_digest,
    }


def verification_report(
    *,
    status: str,
    reason: str | None,
    pack_id: str | None,
    saved_data: bytes | None,
    saved_digest: str | None,
    actual_digest: str | None,
    binding_count: int,
    matched_bindings: int,
    mismatched_paths: list[str],
) -> dict[str, Any]:
    return {
        "kind": "company_pack_review_bundle_verification",
        "version": "1.0",
        "status": status,
        "reason": reason,
        "pack_id": pack_id,
        "saved_bundle": saved_bundle_summary(saved_data, saved_digest),
        "actual_bundle_digest": actual_digest,
        "binding_count": binding_count,
        "matched_bindings": matched_bindings,
        "mismatched_paths": mismatched_paths,
        "claims": empty_claims(),
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def validate_saved_bundle(bundle: object) -> tuple[str | None, str | None]:
    """Return (error reason, trusted bundle digest)."""
    if not isinstance(bundle, dict) or set(bundle) != BUNDLE_KEYS:
        return "INVALID_BUNDLE_FORMAT", None
    if (
        bundle.get("kind") != "company_pack_review_bundle"
        or bundle.get("version") != "1.0"
        or bundle.get("status") != "CANDIDATE_FOR_GOVERNED_REVIEW"
        or bundle.get("reason") is not None
        or bundle.get("public_beta") != "NO_GO_UNPUBLISHED"
    ):
        return "INVALID_BUNDLE_FORMAT", None
    pack_id = bundle.get("pack_id")
    if not isinstance(pack_id, str) or ID_PATTERN.fullmatch(pack_id) is None:
        return "INVALID_BUNDLE_FORMAT", None
    if bundle.get("claims") != empty_claims():
        return "INVALID_BUNDLE_FORMAT", None

    checks = bundle.get("source_checks")
    if not isinstance(checks, dict) or set(checks) != {
        "structural_validation",
        "customization",
    }:
        return "INVALID_BUNDLE_FORMAT", None
    structural = checks.get("structural_validation")
    if (
        not isinstance(structural, dict)
        or set(structural) != {"status", "validated_files"}
        or structural.get("status") != "PASS"
        or not isinstance(structural.get("validated_files"), int)
        or isinstance(structural.get("validated_files"), bool)
        or structural["validated_files"] < 1
    ):
        return "INVALID_BUNDLE_FORMAT", None
    customization = checks.get("customization")
    if (
        not isinstance(customization, dict)
        or set(customization) != {"status", "counts"}
        or customization.get("status") != "READY_FOR_GOVERNED_REVIEW"
    ):
        return "INVALID_BUNDLE_FORMAT", None
    counts = customization.get("counts")
    if (
        not isinstance(counts, dict)
        or set(counts) != COUNT_KEYS
        or any(
            not isinstance(counts[key], int)
            or isinstance(counts[key], bool)
            or counts[key] < 0
            for key in COUNT_KEYS
        )
        or counts["replacement_required"] != 0
    ):
        return "INVALID_BUNDLE_FORMAT", None

    bindings = bundle.get("bindings")
    if not isinstance(bindings, list) or not bindings:
        return "INVALID_BUNDLE_FORMAT", None
    paths: list[str] = []
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding) != {"path", "sha256", "bytes"}:
            return "INVALID_BUNDLE_FORMAT", None
        path = binding.get("path")
        size = binding.get("bytes")
        if (
            not is_safe_relative_json_path(path)
            or not is_sha256(binding.get("sha256"))
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 1
        ):
            return "INVALID_BUNDLE_FORMAT", None
        paths.append(path)
    if (
        len(paths) != len(set(paths))
        or paths[0] != "manifest.json"
        or paths[1:] != sorted(paths[1:])
        or bundle.get("binding_count") != len(bindings)
    ):
        return "INVALID_BUNDLE_FORMAT", None

    digest = bundle.get("bundle_digest")
    if (
        not isinstance(digest, dict)
        or set(digest) != {"algorithm", "canonicalization", "value"}
        or digest.get("algorithm") != "SHA-256"
        or digest.get("canonicalization") != CANONICALIZATION
        or not is_sha256(digest.get("value"))
    ):
        return "INVALID_BUNDLE_FORMAT", None
    canonical = json.dumps(
        bindings,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    expected_digest = hashlib.sha256(canonical).hexdigest()
    if digest["value"] != expected_digest:
        return "INVALID_BUNDLE_DIGEST", None
    return None, expected_digest


def verify_saved_bundle(bundle_path: Path, pack_dir: Path) -> dict[str, Any]:
    try:
        saved_data = bundle_path.read_bytes()
    except OSError:
        return verification_report(
            status="MISMATCH",
            reason="BUNDLE_READ_FAILED",
            pack_id=None,
            saved_data=None,
            saved_digest=None,
            actual_digest=None,
            binding_count=0,
            matched_bindings=0,
            mismatched_paths=[],
        )
    try:
        saved = json.loads(
            saved_data.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_non_finite_constant,
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return verification_report(
            status="MISMATCH",
            reason="INVALID_BUNDLE_FORMAT",
            pack_id=None,
            saved_data=saved_data,
            saved_digest=None,
            actual_digest=None,
            binding_count=0,
            matched_bindings=0,
            mismatched_paths=[],
        )

    invalid_reason, saved_digest = validate_saved_bundle(saved)
    if invalid_reason is not None:
        return verification_report(
            status="MISMATCH",
            reason=invalid_reason,
            pack_id=None,
            saved_data=saved_data,
            saved_digest=None,
            actual_digest=None,
            binding_count=0,
            matched_bindings=0,
            mismatched_paths=[],
        )

    actual = build_review_bundle(pack_dir)
    if actual.get("status") != "CANDIDATE_FOR_GOVERNED_REVIEW":
        return verification_report(
            status="MISMATCH",
            reason="PACK_NOT_REVIEW_READY",
            pack_id=saved["pack_id"],
            saved_data=saved_data,
            saved_digest=saved_digest,
            actual_digest=None,
            binding_count=len(saved["bindings"]),
            matched_bindings=0,
            mismatched_paths=[],
        )
    actual_digest = actual["bundle_digest"]["value"]
    if actual.get("pack_id") != saved.get("pack_id"):
        return verification_report(
            status="MISMATCH",
            reason="PACK_ID_MISMATCH",
            pack_id=saved["pack_id"],
            saved_data=saved_data,
            saved_digest=saved_digest,
            actual_digest=actual_digest,
            binding_count=len(saved["bindings"]),
            matched_bindings=0,
            mismatched_paths=[],
        )

    if any(saved[key] != actual[key] for key in METADATA_KEYS):
        return verification_report(
            status="MISMATCH",
            reason="BUNDLE_METADATA_MISMATCH",
            pack_id=saved["pack_id"],
            saved_data=saved_data,
            saved_digest=saved_digest,
            actual_digest=actual_digest,
            binding_count=len(saved["bindings"]),
            matched_bindings=sum(
                saved_binding == actual_binding
                for saved_binding, actual_binding in zip(
                    saved["bindings"], actual["bindings"]
                )
            ),
            mismatched_paths=[],
        )

    saved_by_path = {binding["path"]: binding for binding in saved["bindings"]}
    actual_by_path = {binding["path"]: binding for binding in actual["bindings"]}
    all_paths = sorted(set(saved_by_path) | set(actual_by_path))
    mismatched_paths = [
        path for path in all_paths if saved_by_path.get(path) != actual_by_path.get(path)
    ]
    matched_bindings = len(all_paths) - len(mismatched_paths)
    if mismatched_paths or actual_digest != saved_digest:
        return verification_report(
            status="MISMATCH",
            reason="BINDINGS_MISMATCH",
            pack_id=saved["pack_id"],
            saved_data=saved_data,
            saved_digest=saved_digest,
            actual_digest=actual_digest,
            binding_count=len(saved["bindings"]),
            matched_bindings=matched_bindings,
            mismatched_paths=mismatched_paths,
        )
    return verification_report(
        status="MATCH",
        reason=None,
        pack_id=saved["pack_id"],
        saved_data=saved_data,
        saved_digest=saved_digest,
        actual_digest=actual_digest,
        binding_count=len(saved["bindings"]),
        matched_bindings=len(saved["bindings"]),
        mismatched_paths=[],
    )


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            "usage: verify_company_pack_review_bundle.py BUNDLE_JSON PACK_DIRECTORY",
            file=sys.stderr,
        )
        return 2
    report = verify_saved_bundle(Path(argv[1]), Path(argv[2]))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "MATCH" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
