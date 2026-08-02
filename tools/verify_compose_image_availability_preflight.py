#!/usr/bin/env python3
"""Verify a saved image-availability snapshot and its candidate binding."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from preflight_compose_image_availability import (
    FALSE_CLAIMS,
    SAFE_RUNTIME_VALUE,
    claims as expected_snapshot_claims,
    snapshot_digest,
)
from validate_resolved_compose_candidate import (
    PROJECT_PATTERN,
    load_strict_json_bytes,
    validate_candidate,
)


TOP_FIELDS = {
    "kind",
    "version",
    "status",
    "observed_at",
    "candidate_binding",
    "host_binding",
    "image_observation",
    "effects",
    "claims",
    "preflight_sha256",
    "public_beta",
}
CANDIDATE_FIELDS = {
    "candidate_file_sha256",
    "project_name",
    "resolved_contract_sha256",
    "image_manifest_digest",
}
HOST_FIELDS = {
    "daemon_id_sha256",
    "docker_cli_sha256",
    "server_version",
    "os_type",
    "architecture",
    "raw_identity_emitted",
}
IMAGE_FIELDS = {
    "available_locally",
    "repo_digest_match_observed",
    "image_manifest_digest",
    "local_image_id_digest",
    "size_bytes",
    "os_type",
    "architecture",
    "rootfs_fingerprint_sha256",
    "repository_names_emitted",
    "layer_digests_emitted",
}
EFFECT_FIELDS = {
    "daemon_info_query",
    "image_list_query",
    "image_inspect_query",
    "image_pull",
    "image_tag",
    "image_remove",
    "container_create",
    "container_start",
    "daemon_configuration_change",
}
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def require_exact_fields(
    value: object, expected: set[str], location: str, errors: list[str]
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        errors.append(f"{location} must be an object")
        return None
    for field in sorted(expected - value.keys()):
        errors.append(f"{location} missing required field: {field}")
    for field in sorted(value.keys() - expected):
        errors.append(f"{location} contains unknown field: {field}")
    return value


def valid_time(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def validate_snapshot(
    snapshot: dict[str, Any], candidate: dict[str, Any], candidate_bytes: bytes
) -> list[str]:
    errors: list[str] = []
    require_exact_fields(snapshot, TOP_FIELDS, "snapshot", errors)
    if snapshot.get("kind") != "compose_image_availability_preflight":
        errors.append("kind must be compose_image_availability_preflight")
    if snapshot.get("version") != "1.0":
        errors.append("version must be 1.0")
    if snapshot.get("status") != "LOCAL_IMAGE_AVAILABLE":
        errors.append("status must remain LOCAL_IMAGE_AVAILABLE")
    if not valid_time(snapshot.get("observed_at")):
        errors.append("observed_at must be timezone-aware ISO-8601")

    candidate_binding = require_exact_fields(
        snapshot.get("candidate_binding"), CANDIDATE_FIELDS, "candidate_binding", errors
    )
    expected_digest = candidate["resolved"]["services"][0]["image_digest"]
    if candidate_binding is not None:
        if candidate_binding.get("candidate_file_sha256") != hashlib.sha256(candidate_bytes).hexdigest():
            errors.append("candidate file digest mismatch")
        if candidate_binding.get("project_name") != candidate.get("project_name"):
            errors.append("candidate project binding mismatch")
        if candidate_binding.get("resolved_contract_sha256") != candidate["resolved"].get("resolved_contract_sha256"):
            errors.append("candidate resolved contract binding mismatch")
        if candidate_binding.get("image_manifest_digest") != expected_digest:
            errors.append("candidate image digest binding mismatch")
        project_name = candidate_binding.get("project_name")
        if not isinstance(project_name, str) or PROJECT_PATTERN.fullmatch(project_name) is None:
            errors.append("candidate_binding.project_name is unsafe")

    host = require_exact_fields(snapshot.get("host_binding"), HOST_FIELDS, "host_binding", errors)
    if host is not None:
        for field in ("daemon_id_sha256", "docker_cli_sha256"):
            value = host.get(field)
            if not isinstance(value, str) or SHA256_HEX.fullmatch(value) is None:
                errors.append(f"host_binding.{field} must be lowercase SHA-256")
        for field in ("server_version", "os_type", "architecture"):
            value = host.get(field)
            if not isinstance(value, str) or SAFE_RUNTIME_VALUE.fullmatch(value) is None:
                errors.append(f"host_binding.{field} is unsafe")
        if host.get("raw_identity_emitted") is not False:
            errors.append("host_binding.raw_identity_emitted must remain false")

    image = require_exact_fields(
        snapshot.get("image_observation"), IMAGE_FIELDS, "image_observation", errors
    )
    if image is not None:
        if image.get("available_locally") is not True:
            errors.append("image_observation.available_locally must be true")
        if image.get("repo_digest_match_observed") is not True:
            errors.append("image_observation.repo_digest_match_observed must be true")
        if image.get("image_manifest_digest") != expected_digest:
            errors.append("image observation manifest digest mismatch")
        local_id = image.get("local_image_id_digest")
        if not isinstance(local_id, str) or SHA256_DIGEST.fullmatch(local_id) is None:
            errors.append("image_observation.local_image_id_digest must be SHA-256 pinned")
        size = image.get("size_bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            errors.append("image_observation.size_bytes must be a non-negative integer")
        for field in ("os_type", "architecture"):
            value = image.get(field)
            if not isinstance(value, str) or SAFE_RUNTIME_VALUE.fullmatch(value) is None:
                errors.append(f"image_observation.{field} is unsafe")
        rootfs = image.get("rootfs_fingerprint_sha256")
        if not isinstance(rootfs, str) or SHA256_HEX.fullmatch(rootfs) is None:
            errors.append("image_observation.rootfs_fingerprint_sha256 must be lowercase SHA-256")
        if image.get("repository_names_emitted") is not False:
            errors.append("image_observation.repository_names_emitted must remain false")
        if image.get("layer_digests_emitted") is not False:
            errors.append("image_observation.layer_digests_emitted must remain false")

    effects = require_exact_fields(snapshot.get("effects"), EFFECT_FIELDS, "effects", errors)
    expected_effects = {
        "daemon_info_query": True,
        "image_list_query": True,
        "image_inspect_query": True,
        "image_pull": False,
        "image_tag": False,
        "image_remove": False,
        "container_create": False,
        "container_start": False,
        "daemon_configuration_change": False,
    }
    if effects is not None and effects != expected_effects:
        errors.append("effects must remain the exact read-only observation contract")
    snapshot_claims = require_exact_fields(
        snapshot.get("claims"), set(expected_snapshot_claims()), "claims", errors
    )
    if snapshot_claims is not None and snapshot_claims != expected_snapshot_claims():
        errors.append("claims do not match the bounded availability observation")
    digest = snapshot.get("preflight_sha256")
    if not isinstance(digest, str) or SHA256_HEX.fullmatch(digest) is None:
        errors.append("preflight_sha256 must be lowercase SHA-256")
    elif digest != snapshot_digest(snapshot):
        errors.append("preflight digest mismatch")
    if snapshot.get("public_beta") != "NO_GO_UNPUBLISHED":
        errors.append("public_beta must remain NO_GO_UNPUBLISHED")
    return sorted(set(errors))


def report(errors: list[str]) -> dict[str, Any]:
    valid = not errors
    report_claims = {claim: False for claim in sorted(FALSE_CLAIMS)}
    report_claims.update(
        {
            "snapshot_self_digest_verified": valid,
            "candidate_binding_verified": valid,
            "snapshot_authenticity_verified": False,
            "observation_freshness_verified": False,
            "observation_atomicity_verified": False,
            "current_daemon_reachable_verified": False,
            "current_local_image_available_verified": False,
        }
    )
    return {
        "kind": "compose_image_availability_preflight_validation",
        "version": "1.1",
        "status": "HISTORICAL_BINDING_ONLY" if valid else "INVALID",
        "errors": errors,
        "claims": dict(sorted(report_claims.items())),
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            "usage: verify_compose_image_availability_preflight.py PREFLIGHT_JSON RESOLVED_CANDIDATE_JSON",
            file=sys.stderr,
        )
        return 2
    try:
        snapshot_bytes = Path(argv[1]).read_bytes()
        snapshot = load_strict_json_bytes(snapshot_bytes)
        candidate_path = Path(argv[2])
        candidate_bytes = candidate_path.read_bytes()
        candidate = load_strict_json_bytes(candidate_bytes)
        candidate_errors = validate_candidate(candidate)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        print(json.dumps(report(["input JSON is invalid"]), sort_keys=True))
        return 1
    if candidate_errors:
        errors = ["resolved candidate is invalid"]
    else:
        errors = validate_snapshot(snapshot, candidate, candidate_bytes)
    print(json.dumps(report(errors), sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
