"""Read-only preflight for the public route-binding candidate contract.

The public repository only records an opaque comparison shape.  This tool does
not resolve a task, inspect a private workspace, spawn an agent, call Codex,
send a message, open a provider/device route, write a receipt, or grant an
authority.  A successful result means that the candidate is structurally
closed and its unverified preview window is internally ordered.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # pragma: no cover - exercised only in dependency-free installs
    Draft202012Validator = None  # type: ignore[assignment,misc]
    FormatChecker = None  # type: ignore[assignment,misc]


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "company-pack-agent-orchestration-route-binding-candidate.schema.json"
MAX_INPUT_BYTES = 1_048_576
MAX_BINDING_BYTES = 16_777_216

TOP_LEVEL_FIELDS = {
    "kind",
    "version",
    "status",
    "route_state",
    "route_id_ref",
    "operation_id_ref",
    "source_task",
    "target_task",
    "resource_binding",
    "route_policy",
    "preview",
    "confirmation",
    "failure_and_rollback",
    "recorded_at",
    "expires_at",
    "review_trigger",
    "claims",
    "public_beta",
}
TASK_FIELDS = {
    "task_ref",
    "thread_ref",
    "host_ref",
    "title_ref",
    "workspace_ref",
    "workspace_binding",
}
RESOURCE_FIELDS = {
    "repository_ref",
    "public_revision",
    "candidate_manifest_binding",
    "resource_scope_ref",
    "verification_status",
}
ROUTE_POLICY_FIELDS = {
    "allowed_action",
    "effect_class",
    "expected_effects",
    "source_target_correlation_ref",
    "route_policy_ref",
    "route_policy_binding",
    "external_effects_allowed",
    "provider_effects_allowed",
    "device_effects_allowed",
    "public_effects_allowed",
    "verification_status",
}
PREVIEW_FIELDS = {
    "preview_binding",
    "observed_at",
    "expires_at",
    "preview_status",
    "confirmation_required",
    "verification_status",
}
CONFIRMATION_FIELDS = {
    "confirmation_ref",
    "confirmation_binding",
    "confirmation_status",
    "human_gate",
    "verification_status",
}
FAILURE_FIELDS = {
    "stop_conditions",
    "rollback_policy_ref",
    "rollback_policy_binding",
    "rollback_receipt_ref",
    "rollback_receipt_binding",
    "failure_state",
    "no_external_effects_expected",
    "execution_receipt_ref",
    "verification_status",
}
CLAIM_FIELDS = {
    "route_verified",
    "source_target_correlated",
    "workspace_binding_verified",
    "revision_current_verified",
    "candidate_manifest_verified",
    "preview_verified",
    "confirmation_verified",
    "reobserve_verified",
    "replay_prevented",
    "dispatch_executed",
    "external_effect_authorized",
    "external_effect_executed",
    "human_decision_verified",
    "work_order_authority_granted",
    "promotion_verified",
    "current_truth_changed",
    "final_human_go",
    "public_beta_go",
}
STOP_CONDITIONS = [
    "source_target_mismatch",
    "workspace_or_revision_drift",
    "route_policy_drift",
    "preview_stale_or_expired",
    "confirmation_missing_or_mismatch",
    "external_effect_detected",
    "operation_replay_conflict",
]
REVIEW_TRIGGERS = [
    "source_or_target_identity_change",
    "workspace_or_revision_change",
    "route_policy_or_allowed_action_change",
    "candidate_manifest_or_preview_change",
    "clock_or_expiry_change",
    "rollback_or_stop_condition_change",
    "confirmation_or_authority_change",
    "schema_change",
    "request_expiry",
]
OPAQUE_REF = re.compile(r"^ref/[a-z0-9][a-z0-9/_-]{1,510}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SHA1 = re.compile(r"^[0-9a-f]{40}$")


class DuplicateKeyError(ValueError):
    pass


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError
        result[key] = value
    return result


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _is_dict(value: Any) -> bool:
    return isinstance(value, dict)


def _exact_fields(value: Any, expected: set[str]) -> bool:
    return _is_dict(value) and set(value) == expected


def _opaque_ref(value: Any) -> bool:
    return isinstance(value, str) and OPAQUE_REF.fullmatch(value) is not None


def _binding(value: Any) -> bool:
    if not _exact_fields(value, {"sha256", "bytes"}):
        return False
    return (
        isinstance(value["sha256"], str)
        and SHA256.fullmatch(value["sha256"]) is not None
        and isinstance(value["bytes"], int)
        and not isinstance(value["bytes"], bool)
        and 0 <= value["bytes"] <= MAX_BINDING_BYTES
    )


def _task_identity(value: Any) -> bool:
    if not _exact_fields(value, TASK_FIELDS):
        return False
    return all(
        _opaque_ref(value[field])
        for field in ("task_ref", "thread_ref", "host_ref", "title_ref", "workspace_ref")
    ) and _binding(value["workspace_binding"])


def _shape_valid(candidate: Any) -> bool:
    if not _exact_fields(candidate, TOP_LEVEL_FIELDS):
        return False
    if (
        candidate["kind"] != "company_pack_agent_orchestration_route_binding_candidate"
        or candidate["version"] != "1.0"
        or candidate["status"] != "CANDIDATE_ONLY"
        or candidate["route_state"] not in {"ROUTE_DEFINED_UNVERIFIED", "REFUSED_UNVERIFIED"}
        or not _opaque_ref(candidate["route_id_ref"])
        or not _opaque_ref(candidate["operation_id_ref"])
        or not _task_identity(candidate["source_task"])
        or not _task_identity(candidate["target_task"])
    ):
        return False

    resource = candidate["resource_binding"]
    if not _exact_fields(resource, RESOURCE_FIELDS):
        return False
    if not (
        _opaque_ref(resource["repository_ref"])
        and isinstance(resource["public_revision"], str)
        and SHA1.fullmatch(resource["public_revision"]) is not None
        and _binding(resource["candidate_manifest_binding"])
        and _opaque_ref(resource["resource_scope_ref"])
        and resource["verification_status"] == "NOT_VERIFIED"
    ):
        return False

    policy = candidate["route_policy"]
    if not _exact_fields(policy, ROUTE_POLICY_FIELDS):
        return False
    if not (
        policy["allowed_action"] == "INTERNAL_AGENT_HANDOFF"
        and policy["effect_class"] == "INTERNAL_CANDIDATE_ONLY"
        and policy["expected_effects"] == ["INTERNAL_CANDIDATE_RECORD_ONLY"]
        and _opaque_ref(policy["source_target_correlation_ref"])
        and _opaque_ref(policy["route_policy_ref"])
        and _binding(policy["route_policy_binding"])
        and policy["external_effects_allowed"] is False
        and policy["provider_effects_allowed"] is False
        and policy["device_effects_allowed"] is False
        and policy["public_effects_allowed"] is False
        and policy["verification_status"] == "NOT_VERIFIED"
    ):
        return False

    preview = candidate["preview"]
    if not _exact_fields(preview, PREVIEW_FIELDS):
        return False
    if not (
        _binding(preview["preview_binding"])
        and parse_timestamp(preview["observed_at"]) is not None
        and parse_timestamp(preview["expires_at"]) is not None
        and preview["preview_status"] == "PREVIEW_RECORDED_UNVERIFIED"
        and preview["confirmation_required"] is True
        and preview["verification_status"] == "NOT_VERIFIED"
    ):
        return False

    confirmation = candidate["confirmation"]
    if not _exact_fields(confirmation, CONFIRMATION_FIELDS):
        return False
    if not (
        confirmation["confirmation_ref"] is None
        and confirmation["confirmation_binding"] is None
        and confirmation["confirmation_status"] == "NOT_CONFIRMED"
        and confirmation["human_gate"] is False
        and confirmation["verification_status"] == "NOT_VERIFIED"
    ):
        return False

    failure = candidate["failure_and_rollback"]
    if not _exact_fields(failure, FAILURE_FIELDS):
        return False
    if not (
        failure["stop_conditions"] == STOP_CONDITIONS
        and _opaque_ref(failure["rollback_policy_ref"])
        and _binding(failure["rollback_policy_binding"])
        and failure["rollback_receipt_ref"] is None
        and failure["rollback_receipt_binding"] is None
        and failure["failure_state"] in {"NOT_EXECUTED", "REFUSED_UNVERIFIED"}
        and failure["no_external_effects_expected"] is True
        and failure["execution_receipt_ref"] is None
        and failure["verification_status"] == "NOT_VERIFIED"
    ):
        return False

    if (
        parse_timestamp(candidate["recorded_at"]) is None
        or parse_timestamp(candidate["expires_at"]) is None
        or candidate["review_trigger"] != REVIEW_TRIGGERS
        or not _exact_fields(candidate["claims"], CLAIM_FIELDS)
        or any(value is not False for value in candidate["claims"].values())
        or candidate["public_beta"] != "NO_GO_UNPUBLISHED"
    ):
        return False
    return True


def _semantic_reasons(candidate: dict[str, Any]) -> list[str]:
    reasons: list[str] = []

    source = candidate["source_task"]
    target = candidate["target_task"]
    if source["task_ref"] == target["task_ref"] or source["thread_ref"] == target["thread_ref"]:
        reasons.append("SOURCE_TARGET_IDENTITY_COLLISION")
    if candidate["route_id_ref"] == candidate["operation_id_ref"]:
        reasons.append("ROUTE_OPERATION_ID_COLLISION")

    recorded_at = parse_timestamp(candidate["recorded_at"])
    observed_at = parse_timestamp(candidate["preview"]["observed_at"])
    preview_expires_at = parse_timestamp(candidate["preview"]["expires_at"])
    expires_at = parse_timestamp(candidate["expires_at"])
    if None in (recorded_at, observed_at, preview_expires_at, expires_at):
        return ["TIMESTAMP_INVALID"]
    if not (recorded_at <= observed_at < preview_expires_at <= expires_at):
        reasons.append("PREVIEW_WINDOW_ORDER_INVALID")
    if (preview_expires_at - observed_at).total_seconds() > 86_400:
        reasons.append("PREVIEW_WINDOW_UNBOUNDED")
    return reasons


CLAIMS_FALSE = {name: False for name in sorted(CLAIM_FIELDS)}


def _payload(*, result: str, reason_codes: list[str], matched: bool) -> dict[str, Any]:
    return {
        "kind": "company_pack_agent_orchestration_route_binding_candidate_preflight",
        "version": "1.0",
        "status": "CANDIDATE_ONLY",
        "result": result,
        "reason_codes": reason_codes,
        "checks": {
            "schema": "MATCH" if matched else "REFUSED",
            "identity_shape": "MATCH_UNVERIFIED" if matched else "REFUSED",
            "resource_binding": "MATCH_UNVERIFIED" if matched else "REFUSED",
            "window_order": "MATCH_UNVERIFIED" if matched else "REFUSED",
            "no_external_effects": "MATCH" if matched else "REFUSED",
            "confirmation_unverified": "MATCH" if matched else "REFUSED",
        },
        "claims": CLAIMS_FALSE,
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def reject(reason_codes: list[str]) -> int:
    unique = list(dict.fromkeys(reason_codes)) or ["INPUT_INVALID"]
    print(json.dumps(_payload(result="REFUSED", reason_codes=unique, matched=False), indent=2, sort_keys=True))
    return 2


def success() -> int:
    print(
        json.dumps(
            _payload(
                result="PRECONDITIONS_MATCH_UNVERIFIED",
                reason_codes=[],
                matched=True,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {Path(argv[0]).name} CANDIDATE_JSON", file=sys.stderr)
        return 2

    candidate_path = Path(argv[1])
    try:
        raw = candidate_path.read_bytes()
        if len(raw) > MAX_INPUT_BYTES:
            return reject(["INPUT_TOO_LARGE"])
        candidate = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        if not isinstance(schema, dict):
            raise ValueError
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, DuplicateKeyError, ValueError):
        return reject(["INPUT_INVALID"])

    if Draft202012Validator is None or FormatChecker is None:
        return reject(["VALIDATOR_UNAVAILABLE"])
    try:
        schema_errors = list(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(candidate)
        )
    except (TypeError, ValueError):
        return reject(["VALIDATOR_UNAVAILABLE"])
    if schema_errors:
        return reject(["SCHEMA_INVALID"])
    if not _shape_valid(candidate):
        return reject(["SCHEMA_INVALID"])
    if candidate["route_state"] == "REFUSED_UNVERIFIED":
        return reject(["CANDIDATE_MARKED_REFUSED"])
    reasons = _semantic_reasons(candidate)
    return reject(reasons) if reasons else success()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
