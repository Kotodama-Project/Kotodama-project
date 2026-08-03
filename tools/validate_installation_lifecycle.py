#!/usr/bin/env python3
"""Validate a sanitized installation lifecycle profile using only the stdlib."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


PHASE_ORDER = (
    "preflight",
    "stage_candidate",
    "apply",
    "verify",
    "rollback",
    "restore_rehearsal",
)
PHASE_EFFECTS = {
    "preflight": "read_only",
    "stage_candidate": "local_reversible",
    "apply": "external_mutation",
    "verify": "read_only",
    "rollback": "external_mutation",
    "restore_rehearsal": "isolated_mutation",
}
MATERIAL_PHASES = {"apply", "rollback", "restore_rehearsal"}
PHASE_EVIDENCE = {
    "preflight": {
        "target_inventory",
        "host_capabilities",
        "current_revision",
        "privacy_scan",
    },
    "stage_candidate": {
        "candidate_revision",
        "configuration_digest",
        "offline_validation",
    },
    "apply": {"bounded_work_order", "before_state_receipt", "change_journal"},
    "verify": {
        "candidate_digest",
        "service_health",
        "negative_test_results",
        "network_boundary_checks",
    },
    "rollback": {
        "rollback_work_order",
        "last_known_good_revision",
        "rollback_verification",
    },
    "restore_rehearsal": {
        "restore_work_order",
        "backup_digest",
        "isolated_restore_result",
        "recovery_verification",
    },
}
PROFILE_EVIDENCE = {
    "compose_minimum": {
        "compose_runtime_version",
        "project_namespace",
        "compose_config_digest",
        "volume_inventory",
        "network_boundary",
        "service_health",
        "negative_test_results",
        "backup_digest",
        "isolated_restore_result",
    },
    "proxmox_segmented": {
        "role_map_locator",
        "guest_revision_digests",
        "segmentation_matrix",
        "firewall_rule_digest",
        "service_identity_matrix",
        "storage_inventory",
        "service_health",
        "negative_test_results",
        "backup_digest",
        "isolated_restore_result",
    },
}
CLAIM_FIELDS = {
    "live_installation_verified",
    "deployment_verified",
    "restart_verified",
    "restore_verified",
    "provider_e2e_verified",
    "promotion_verified",
    "current_truth_changed",
    "final_human_go",
    "public_beta_go",
}
TOP_LEVEL_FIELDS = {
    "kind",
    "spec_version",
    "id",
    "status",
    "profile",
    "purpose",
    "scope",
    "privacy",
    "governance",
    "profile_evidence",
    "phases",
    "claims",
    "public_beta",
}
SCOPE_FIELDS = {"mode", "live_mutation_allowed", "runtime_values"}
PRIVACY_FIELDS = {
    "secret_values",
    "private_infrastructure_identifiers",
    "public_examples",
}
GOVERNANCE_FIELDS = {
    "material_phases_require_work_order",
    "candidate_digest_required",
    "receipt_required",
    "promotion_is_separate",
}
PHASE_FIELDS = {
    "id",
    "effect",
    "requires_work_order",
    "required_evidence",
    "stop_conditions",
    "receipt_required",
    "rollback_ref",
}
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
EVIDENCE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,62}$")
IPV4_PATTERN = re.compile(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])")
SECRET_KEY_MARKERS = {
    "apikey",
    "accesskey",
    "token",
    "secret",
    "password",
    "cookie",
    "webhookurl",
    "privatekey",
    "credential",
}
PRIVATE_INFRASTRUCTURE_KEYS = {
    "hostip",
    "ipaddress",
    "hostname",
    "nodehostname",
    "nodename",
    "vmid",
    "guestid",
    "storageid",
    "macaddress",
}
SAFE_POLICY_KEYS = {"secretvalues", "privateinfrastructureidentifiers"}
SECRET_VALUE_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/", re.I),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


class StrictJsonError(ValueError):
    """Raised when JSON is ambiguous or non-standard."""


def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StrictJsonError("duplicate key")
        result[key] = value
    return result


def reject_non_finite(_value: str) -> None:
    raise StrictJsonError("non-finite number")


def load_strict_json(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_pairs,
        parse_constant=reject_non_finite,
    )
    if not isinstance(value, dict):
        raise StrictJsonError("top-level value must be an object")
    return value


def normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def scan_sensitive_values(value: object, location: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_location = f"{location}.{key}"
            normalized = normalized_key(key)
            is_locator = normalized.endswith(("ref", "reference", "locator"))
            if (
                not is_locator
                and normalized not in SAFE_POLICY_KEYS
                and any(marker in normalized for marker in SECRET_KEY_MARKERS)
            ):
                errors.append(f"secret-bearing key is forbidden: {child_location}")
            if not is_locator and normalized in PRIVATE_INFRASTRUCTURE_KEYS:
                errors.append(f"private infrastructure key is forbidden: {child_location}")
            errors.extend(scan_sensitive_values(child, child_location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(scan_sensitive_values(child, f"{location}[{index}]"))
    elif isinstance(value, str):
        if IPV4_PATTERN.search(value):
            errors.append(f"private infrastructure literal is forbidden: {location}")
        if any(pattern.search(value) for pattern in SECRET_VALUE_PATTERNS):
            errors.append(f"secret-like value is forbidden: {location}")
    return errors


def reject_unknown(
    value: dict[str, Any], allowed: set[str], location: str, errors: list[str]
) -> None:
    for field in sorted(value.keys() - allowed):
        errors.append(f"{location} contains unknown field: {field}")


def require_fields(
    value: dict[str, Any], required: set[str], location: str, errors: list[str]
) -> None:
    for field in sorted(required - value.keys()):
        errors.append(f"{location} missing required field: {field}")


def require_object(
    parent: dict[str, Any], field: str, location: str, errors: list[str]
) -> dict[str, Any]:
    value = parent.get(field)
    if not isinstance(value, dict):
        errors.append(f"{location} field {field} must be an object")
        return {}
    return value


def string_set(
    value: object, location: str, errors: list[str], *, minimum: int = 1
) -> set[str]:
    if not isinstance(value, list):
        errors.append(f"{location} must be an array")
        return set()
    if not all(isinstance(item, str) and item for item in value):
        errors.append(f"{location} must contain only non-empty strings")
    valid = [item for item in value if isinstance(item, str) and item]
    if len(valid) < minimum:
        errors.append(f"{location} must contain at least {minimum} item(s)")
    if len(valid) != len(set(valid)):
        errors.append(f"{location} must contain unique items")
    return set(valid)


def validate_fixed_object(
    parent: dict[str, Any],
    field: str,
    allowed: set[str],
    expected: dict[str, object],
    errors: list[str],
) -> dict[str, Any]:
    value = require_object(parent, field, "profile", errors)
    require_fields(value, allowed, field, errors)
    reject_unknown(value, allowed, field, errors)
    for key, expected_value in expected.items():
        actual_value = value.get(key)
        if isinstance(expected_value, bool):
            matches = type(actual_value) is bool and actual_value is expected_value
        else:
            matches = actual_value == expected_value
        if not matches:
            errors.append(f"{field}.{key} must be {json.dumps(expected_value, separators=(',', ':'))}")
    return value


def validate_phases(document: dict[str, Any], errors: list[str]) -> int:
    phases = document.get("phases")
    if not isinstance(phases, list):
        errors.append("profile field phases must be an array")
        return 0
    phase_ids = [phase.get("id") if isinstance(phase, dict) else None for phase in phases]
    if phase_ids != list(PHASE_ORDER):
        errors.append("phases must use the required lifecycle order")

    for index, phase in enumerate(phases):
        expected_id = PHASE_ORDER[index] if index < len(PHASE_ORDER) else None
        if not isinstance(phase, dict):
            errors.append(f"phase[{index}] must be an object")
            continue
        actual_id = phase.get("id")
        location_id = actual_id if isinstance(actual_id, str) and actual_id else f"[{index}]"
        location = f"phase {location_id}"
        require_fields(phase, PHASE_FIELDS, location, errors)
        reject_unknown(phase, PHASE_FIELDS, location, errors)
        if expected_id is None or actual_id != expected_id:
            continue
        if phase.get("effect") != PHASE_EFFECTS[expected_id]:
            errors.append(f"{location} effect must be {PHASE_EFFECTS[expected_id]}")
        required_work_order = expected_id in MATERIAL_PHASES
        if phase.get("requires_work_order") is not required_work_order:
            errors.append(
                f"{location} requires_work_order must be {str(required_work_order).lower()}"
            )
        if phase.get("receipt_required") is not True:
            errors.append(f"{location} receipt_required must be true")
        expected_rollback_ref = "phase:rollback" if expected_id == "apply" else None
        if phase.get("rollback_ref") != expected_rollback_ref:
            rendered = expected_rollback_ref if expected_rollback_ref is not None else "null"
            errors.append(f"{location} rollback_ref must be {rendered}")
        evidence = string_set(
            phase.get("required_evidence"), f"{location} required_evidence", errors
        )
        for missing in sorted(PHASE_EVIDENCE[expected_id] - evidence):
            errors.append(f"{location} missing required evidence: {missing}")
        for item in sorted(evidence):
            if EVIDENCE_PATTERN.fullmatch(item) is None:
                errors.append(f"{location} required evidence must use snake_case")
        string_set(phase.get("stop_conditions"), f"{location} stop_conditions", errors)
    return len(phases)


def validate_profile(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    require_fields(document, TOP_LEVEL_FIELDS, "profile", errors)
    reject_unknown(document, TOP_LEVEL_FIELDS, "profile", errors)
    errors.extend(scan_sensitive_values(document))

    if document.get("kind") != "installation_lifecycle_profile":
        errors.append("kind must be installation_lifecycle_profile")
    if document.get("spec_version") != "0.1":
        errors.append("spec_version must be 0.1")
    identifier = document.get("id")
    if not isinstance(identifier, str) or ID_PATTERN.fullmatch(identifier) is None:
        errors.append("id must use lowercase kebab-case")
    if document.get("status") not in {"example", "candidate_only"}:
        errors.append("status must be example or candidate_only")
    if not isinstance(document.get("purpose"), str) or not document["purpose"].strip():
        errors.append("purpose must be a non-empty string")

    validate_fixed_object(
        document,
        "scope",
        SCOPE_FIELDS,
        {
            "mode": "planning_and_evidence_contract",
            "live_mutation_allowed": False,
            "runtime_values": "locator_only",
        },
        errors,
    )
    validate_fixed_object(
        document,
        "privacy",
        PRIVACY_FIELDS,
        {
            "secret_values": "forbidden",
            "private_infrastructure_identifiers": "locator_only",
            "public_examples": "sanitized",
        },
        errors,
    )
    validate_fixed_object(
        document,
        "governance",
        GOVERNANCE_FIELDS,
        {
            "material_phases_require_work_order": list(PHASE_ORDER[index] for index in (2, 4, 5)),
            "candidate_digest_required": True,
            "receipt_required": True,
            "promotion_is_separate": True,
        },
        errors,
    )

    profile = document.get("profile")
    evidence = string_set(document.get("profile_evidence"), "profile_evidence", errors)
    for item in sorted(evidence):
        if EVIDENCE_PATTERN.fullmatch(item) is None:
            errors.append("profile_evidence items must use snake_case")
    if profile not in PROFILE_EVIDENCE:
        errors.append("profile must be compose_minimum or proxmox_segmented")
    else:
        for missing in sorted(PROFILE_EVIDENCE[profile] - evidence):
            errors.append(f"{profile} missing profile evidence: {missing}")

    validate_phases(document, errors)

    claims = require_object(document, "claims", "profile", errors)
    require_fields(claims, CLAIM_FIELDS, "claims", errors)
    reject_unknown(claims, CLAIM_FIELDS, "claims", errors)
    for field in sorted(CLAIM_FIELDS):
        if claims.get(field) is not False:
            errors.append(f"claim {field} must remain false")
    if document.get("public_beta") != "NO_GO_UNPUBLISHED":
        errors.append("public_beta must remain NO_GO_UNPUBLISHED")
    return sorted(set(errors))


def empty_claims() -> dict[str, bool]:
    return {field: False for field in sorted(CLAIM_FIELDS)}


def report_for(document: dict[str, Any] | None, errors: list[str]) -> dict[str, Any]:
    profile = document.get("profile") if isinstance(document, dict) else None
    identifier = document.get("id") if isinstance(document, dict) else None
    phases = document.get("phases") if isinstance(document, dict) else None
    return {
        "kind": "installation_lifecycle_validation",
        "version": "1.0",
        "status": "FAIL" if errors else "PASS",
        "profile_id": identifier if isinstance(identifier, str) else None,
        "profile": profile if profile in PROFILE_EVIDENCE else None,
        "phase_count": len(phases) if isinstance(phases, list) else 0,
        "errors": errors,
        "claims": empty_claims(),
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: validate_installation_lifecycle.py PROFILE_JSON", file=sys.stderr)
        return 2
    try:
        document = load_strict_json(Path(argv[1]))
    except (OSError, UnicodeError, json.JSONDecodeError, StrictJsonError, ValueError):
        print(json.dumps(report_for(None, ["profile JSON is invalid"]), sort_keys=True))
        return 1
    errors = validate_profile(document)
    print(json.dumps(report_for(document, errors), sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
