#!/usr/bin/env python3
"""Validate a secret-free Compose resolution candidate against shipped bytes."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import validate_compose_minimum_skeleton as skeleton_validator


ROOT = Path(__file__).resolve().parents[1]
SKELETON_ROOT = ROOT / "runtime" / "compose-minimum"
TOP_FIELDS = {
    "kind",
    "version",
    "status",
    "project_name",
    "source",
    "resolved",
    "claims",
    "public_beta",
}
SOURCE_FIELDS = {
    "skeleton_id",
    "skeleton_spec_version",
    "skeleton_manifest_sha256",
    "bindings",
}
RESOLVED_FIELDS = {
    "credential_contract",
    "networks",
    "services",
    "resolved_contract_sha256",
}
CREDENTIAL_FIELDS = {
    "source",
    "both_present_observed",
    "distinct_values_observed",
    "values_emitted",
    "password_derived_digest",
}
BINDING_FIELDS = {"path", "sha256", "bytes"}
NETWORK_FIELDS = {"id", "internal"}
SERVICE_FIELDS = {
    "id",
    "role",
    "image_digest",
    "network",
    "volume",
    "migration",
    "migration_sha256",
    "healthcheck_sha256",
}
CLAIM_FIELDS = {
    "clean_install_verified",
    "services_started",
    "migrations_applied",
    "health_verified",
    "restart_verified",
    "backup_verified",
    "restore_verified",
    "application_least_privilege_verified",
    "promotion_verified",
    "current_truth_changed",
    "final_human_go",
    "public_beta_go",
}
PROJECT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
IMAGE_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
EXPECTED_BINDING_PATHS = [
    "README.md",
    "company-db/001-company-core.sql",
    "compose.yaml",
    "evidence-store/001-evidence-core.sql",
]
EXPECTED_NETWORKS = [
    {"id": "company-data", "internal": True},
    {"id": "evidence-data", "internal": True},
]
EXPECTED_SERVICE_BASE = {
    "company-db": {
        "role": "company_db",
        "network": "company-data",
        "volume": "company-db-data",
        "migration": "company-db/001-company-core.sql",
        "healthcheck": "pg_isready -U kotodama_company_owner -d kotodama_company",
    },
    "evidence-store": {
        "role": "evidence_metadata_store",
        "network": "evidence-data",
        "volume": "evidence-store-data",
        "migration": "evidence-store/001-evidence-core.sql",
        "healthcheck": "pg_isready -U kotodama_evidence_owner -d kotodama_evidence",
    },
}


class StrictJsonError(ValueError):
    """Raised for unsafe depth, duplicate keys, non-finite numbers, or a non-object root."""


MAX_JSON_NESTING_DEPTH = 64


def reject_excessive_json_nesting(text: str) -> None:
    """Reject deep JSON before the platform's decoder stack becomes evidence."""

    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > MAX_JSON_NESTING_DEPTH:
                raise StrictJsonError("JSON nesting exceeds the explicit limit")
        elif character in "]}":
            depth -= 1


def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StrictJsonError("duplicate key")
        result[key] = value
    return result


def reject_non_finite(_value: str) -> None:
    raise StrictJsonError("non-finite number")


def loads_strict_json(text: str) -> dict[str, Any]:
    reject_excessive_json_nesting(text)
    value = json.loads(
        text,
        object_pairs_hook=reject_duplicate_pairs,
        parse_constant=reject_non_finite,
    )
    if not isinstance(value, dict):
        raise StrictJsonError("top-level value must be an object")
    return value


def load_strict_json_bytes(content: bytes) -> dict[str, Any]:
    return loads_strict_json(content.decode("utf-8"))


def load_strict_json(path: Path) -> dict[str, Any]:
    return load_strict_json_bytes(path.read_bytes())


def is_non_negative_integer(value: object) -> bool:
    """Match JSON Schema integer semantics without treating booleans as sizes."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value >= 0
    return (
        isinstance(value, float)
        and math.isfinite(value)
        and value.is_integer()
        and value >= 0
    )


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def matches_json_value(actual: object, expected: object) -> bool:
    """Compare JSON values with Draft 2020-12 boolean type semantics."""
    if isinstance(expected, bool):
        return type(actual) is bool and actual is expected
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and actual.keys() == expected.keys()
            and all(matches_json_value(actual[key], expected[key]) for key in expected)
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(matches_json_value(left, right) for left, right in zip(actual, expected))
        )
    return actual == expected


def false_claims() -> dict[str, bool]:
    return {claim: False for claim in sorted(CLAIM_FIELDS)}


def require_exact_fields(
    value: object, allowed: set[str], location: str, errors: list[str]
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        errors.append(f"{location} must be an object")
        return None
    for field in sorted(allowed - value.keys()):
        errors.append(f"{location} missing required field: {field}")
    for field in sorted(value.keys() - allowed):
        errors.append(f"{location} contains unknown field: {field}")
    return value


def shipped_source(skeleton_root: Path = SKELETON_ROOT) -> dict[str, Any]:
    manifest_path = skeleton_root / "skeleton.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = skeleton_validator.load_strict_json(manifest_path)
    skeleton_errors, _ = skeleton_validator.validate_manifest(skeleton_root, manifest)
    if skeleton_errors:
        raise StrictJsonError("shipped skeleton validation failed")
    return {
        "skeleton_id": manifest["id"],
        "skeleton_spec_version": manifest["spec_version"],
        "skeleton_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "bindings": manifest["bindings"],
    }


def safe_contract_projection(candidate: dict[str, Any]) -> dict[str, Any]:
    resolved = candidate.get("resolved")
    if not isinstance(resolved, dict):
        return {}
    return {
        "project_name": candidate.get("project_name"),
        "networks": resolved.get("networks"),
        "services": resolved.get("services"),
    }


def validate_candidate(candidate: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    require_exact_fields(candidate, TOP_FIELDS, "candidate", errors)
    if candidate.get("kind") != "resolved_compose_candidate":
        errors.append("kind must be resolved_compose_candidate")
    if candidate.get("version") != "1.0":
        errors.append("version must be 1.0")
    if candidate.get("status") != "CANDIDATE_READY_FOR_RUNTIME_PREFLIGHT":
        errors.append("status must remain CANDIDATE_READY_FOR_RUNTIME_PREFLIGHT")
    project_name = candidate.get("project_name")
    if not isinstance(project_name, str) or PROJECT_PATTERN.fullmatch(project_name) is None:
        errors.append("project_name must use the safe bounded form")

    source = require_exact_fields(candidate.get("source"), SOURCE_FIELDS, "source", errors)
    if source is not None:
        try:
            expected_source = shipped_source()
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
            expected_source = None
            errors.append("shipped skeleton source is unavailable")
        if expected_source is not None and source != expected_source:
            errors.append("source does not match the shipped skeleton revision")
        bindings = source.get("bindings")
        if not isinstance(bindings, list):
            errors.append("source.bindings must be an array")
        else:
            paths: list[object] = []
            for index, binding in enumerate(bindings):
                item = require_exact_fields(
                    binding, BINDING_FIELDS, f"source.bindings[{index}]", errors
                )
                if item is None:
                    continue
                paths.append(item.get("path"))
                if not isinstance(item.get("sha256"), str) or SHA256_PATTERN.fullmatch(item["sha256"]) is None:
                    errors.append(f"source.bindings[{index}].sha256 must be lowercase SHA-256")
                byte_count = item.get("bytes")
                if not is_non_negative_integer(byte_count):
                    errors.append(f"source.bindings[{index}].bytes must be a non-negative integer")
            if paths != EXPECTED_BINDING_PATHS:
                errors.append("source bindings must use the exact shipped order")

    resolved = require_exact_fields(candidate.get("resolved"), RESOLVED_FIELDS, "resolved", errors)
    if resolved is not None:
        credential = require_exact_fields(
            resolved.get("credential_contract"),
            CREDENTIAL_FIELDS,
            "resolved.credential_contract",
            errors,
        )
        if credential is not None and not matches_json_value(credential, {
            "source": "process_environment",
            "both_present_observed": True,
            "distinct_values_observed": True,
            "values_emitted": False,
            "password_derived_digest": False,
        }):
            errors.append("credential contract must remain non-disclosing and distinct")
        networks = resolved.get("networks")
        if not matches_json_value(networks, EXPECTED_NETWORKS):
            errors.append("resolved networks must remain internal, separate, and ordered")
        if isinstance(networks, list):
            for index, network in enumerate(networks):
                require_exact_fields(network, NETWORK_FIELDS, f"resolved.networks[{index}]", errors)
        services = resolved.get("services")
        binding_hashes = {}
        if source is not None and isinstance(source.get("bindings"), list):
            binding_hashes = {
                item.get("path"): item.get("sha256")
                for item in source["bindings"]
                if isinstance(item, dict)
            }
        if not isinstance(services, list) or len(services) != 2:
            errors.append("resolved services must contain exactly two ordered services")
        else:
            image_digests: list[object] = []
            for index, service in enumerate(services):
                item = require_exact_fields(
                    service, SERVICE_FIELDS, f"resolved.services[{index}]", errors
                )
                if item is None:
                    continue
                expected_id = ["company-db", "evidence-store"][index]
                expected = EXPECTED_SERVICE_BASE[expected_id]
                if item.get("id") != expected_id:
                    errors.append(f"resolved.services[{index}].id is not role bound")
                for field in ("role", "network", "volume", "migration"):
                    if item.get(field) != expected[field]:
                        errors.append(f"resolved.services[{index}].{field} is not role bound")
                image_digest = item.get("image_digest")
                image_digests.append(image_digest)
                if not isinstance(image_digest, str) or IMAGE_DIGEST_PATTERN.fullmatch(image_digest) is None:
                    errors.append(f"resolved.services[{index}].image_digest must be SHA-256 pinned")
                if item.get("migration_sha256") != binding_hashes.get(expected["migration"]):
                    errors.append(f"resolved.services[{index}].migration_sha256 is not source bound")
                if item.get("healthcheck_sha256") != hashlib.sha256(expected["healthcheck"].encode("utf-8")).hexdigest():
                    errors.append(f"resolved.services[{index}].healthcheck_sha256 is not role bound")
            if len(image_digests) == 2 and image_digests[0] != image_digests[1]:
                errors.append("resolved service image digests must match")
        digest = resolved.get("resolved_contract_sha256")
        if not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
            errors.append("resolved_contract_sha256 must be lowercase SHA-256")
        elif digest != canonical_sha256(safe_contract_projection(candidate)):
            errors.append("resolved contract digest mismatch")

    claims = require_exact_fields(candidate.get("claims"), CLAIM_FIELDS, "claims", errors)
    if claims is not None:
        for claim in sorted(CLAIM_FIELDS):
            if claims.get(claim) is not False:
                errors.append(f"claim {claim} must remain false")
    if candidate.get("public_beta") != "NO_GO_UNPUBLISHED":
        errors.append("public_beta must remain NO_GO_UNPUBLISHED")
    return sorted(set(errors))


def validation_report(errors: list[str]) -> dict[str, Any]:
    return {
        "kind": "resolved_compose_candidate_validation",
        "version": "1.0",
        "status": "FAIL" if errors else "PASS",
        "errors": errors,
        "claims": false_claims(),
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: validate_resolved_compose_candidate.py CANDIDATE_JSON", file=sys.stderr)
        return 2
    try:
        candidate = load_strict_json(Path(argv[1]))
    except (OSError, UnicodeError, json.JSONDecodeError, StrictJsonError, ValueError):
        print(json.dumps(validation_report(["candidate JSON is invalid"]), sort_keys=True))
        return 1
    errors = validate_candidate(candidate)
    print(json.dumps(validation_report(errors), sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
