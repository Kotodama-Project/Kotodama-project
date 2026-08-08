"""Project content-free Cloudflare OS Gatekeeper events into Kotodama candidates.

This module never executes a Gatekeeper action. It validates a closed event
envelope and keeps execution, Promotion, and Current Truth authority false.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import re
from typing import Any


EVENT_SCHEMA = "kotodama/cloudflare-os-gatekeeper-event/v1"
PROJECTION_SCHEMA = "kotodama/cloudflare-os-gatekeeper-projection/v1"
REDACTION_PROFILE = "metadata-only-v1"
EDGE_RETENTION = "none"
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
EVENT_KINDS = {
    "observation",
    "action_submitted",
    "action_simulated",
    "action_rejected",
    "action_applied",
}
DATA_CLASSES = {"public_metadata", "protected_context_metadata"}
EVENT_KEYS = {
    "schema",
    "event_kind",
    "data_class",
    "actor_binding_sha256",
    "resource_scope_sha256",
    "request_binding_sha256",
    "candidate_sha256",
    "gatekeeper_revision",
    "observed_at",
    "approval_state",
    "effect_state",
    "effect_count",
    "work_order_sha256",
    "capability_grant_sha256",
    "human_decision_sha256",
    "external_action_receipt_sha256",
    "context_admission_sha256",
    "corpus_scope_sha256",
    "redaction_profile",
    "edge_retention",
    "private_body_included",
}
PROJECTION_KEYS = {
    "schema",
    "record_kind",
    "source_event_sha256",
    "event_kind",
    "gatekeeper_revision",
    "actor_binding_sha256",
    "resource_scope_sha256",
    "request_binding_sha256",
    "candidate_sha256",
    "work_order_sha256",
    "capability_grant_sha256",
    "human_decision_sha256",
    "external_action_receipt_sha256",
    "context_admission_sha256",
    "corpus_scope_sha256",
    "redaction_profile",
    "effect_state",
    "effect_count",
    "private_body_included",
    "source_evidence_candidate",
    "change_candidate",
    "verification_receipt_candidate",
    "cloudflare_approval_is_kotodama_decision",
    "execution_authorized",
    "promotion_authorized",
    "current_truth_changed",
}
RECORD_KIND_BY_EVENT = {
    "observation": "source_evidence_candidate",
    "action_submitted": "change_candidate",
    "action_simulated": "change_candidate",
    "action_rejected": "decision_evidence_candidate",
    "action_applied": "verification_receipt_candidate",
}


class GatekeeperAdapterViolation(ValueError):
    """A Gatekeeper event failed the Kotodama projection contract."""


def canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise GatekeeperAdapterViolation("invalid_json") from exc


def _sha_object(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("ascii")).hexdigest()


def _closed(value: object, expected: set[str], reason: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise GatekeeperAdapterViolation(reason)
    return value


def _digest(value: object, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not DIGEST_RE.fullmatch(value):
        raise GatekeeperAdapterViolation("invalid_digest")
    return value


def _utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise GatekeeperAdapterViolation("invalid_observed_at")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise GatekeeperAdapterViolation("invalid_observed_at") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise GatekeeperAdapterViolation("invalid_observed_at")
    return parsed


def _require_present(event: dict[str, Any], fields: tuple[str, ...]) -> None:
    for field in fields:
        if _digest(event[field], optional=True) is None:
            raise GatekeeperAdapterViolation(f"missing_{field}")


def _require_absent(event: dict[str, Any], fields: tuple[str, ...]) -> None:
    for field in fields:
        if event[field] is not None:
            raise GatekeeperAdapterViolation(f"unexpected_{field}")


def validate_event(event: object, *, expected_gatekeeper_revision: str) -> dict[str, Any]:
    envelope = _closed(event, EVENT_KEYS, "invalid_event_shape")
    if envelope["schema"] != EVENT_SCHEMA:
        raise GatekeeperAdapterViolation("invalid_event_schema")
    if envelope["event_kind"] not in EVENT_KINDS:
        raise GatekeeperAdapterViolation("invalid_event_kind")
    if envelope["data_class"] not in DATA_CLASSES:
        raise GatekeeperAdapterViolation("invalid_data_class")
    if not isinstance(expected_gatekeeper_revision, str) or not REVISION_RE.fullmatch(
        expected_gatekeeper_revision
    ):
        raise GatekeeperAdapterViolation("invalid_expected_revision")
    if envelope["gatekeeper_revision"] != expected_gatekeeper_revision:
        raise GatekeeperAdapterViolation("gatekeeper_revision_mismatch")
    _utc(envelope["observed_at"])
    for field in ("actor_binding_sha256", "resource_scope_sha256", "request_binding_sha256"):
        _digest(envelope[field])
    for field in (
        "candidate_sha256",
        "work_order_sha256",
        "capability_grant_sha256",
        "human_decision_sha256",
        "external_action_receipt_sha256",
        "context_admission_sha256",
        "corpus_scope_sha256",
    ):
        _digest(envelope[field], optional=True)
    if envelope["redaction_profile"] != REDACTION_PROFILE:
        raise GatekeeperAdapterViolation("invalid_redaction_profile")
    if envelope["edge_retention"] != EDGE_RETENTION:
        raise GatekeeperAdapterViolation("invalid_edge_retention")
    if envelope["private_body_included"] is not False:
        raise GatekeeperAdapterViolation("private_body_forbidden")
    if isinstance(envelope["effect_count"], bool) or not isinstance(envelope["effect_count"], int):
        raise GatekeeperAdapterViolation("invalid_effect_count")

    if envelope["data_class"] == "protected_context_metadata":
        _require_present(envelope, ("context_admission_sha256", "corpus_scope_sha256"))
    else:
        _require_absent(envelope, ("context_admission_sha256", "corpus_scope_sha256"))

    action_bindings = ("candidate_sha256", "work_order_sha256", "capability_grant_sha256")
    kind = envelope["event_kind"]
    if kind == "observation":
        if (envelope["approval_state"], envelope["effect_state"], envelope["effect_count"]) != (
            "not_required",
            "none",
            0,
        ):
            raise GatekeeperAdapterViolation("invalid_observation_state")
        _require_absent(
            envelope,
            action_bindings + ("human_decision_sha256", "external_action_receipt_sha256"),
        )
    elif kind == "action_submitted":
        if (envelope["approval_state"], envelope["effect_state"], envelope["effect_count"]) != (
            "pending",
            "none",
            0,
        ):
            raise GatekeeperAdapterViolation("invalid_submitted_action_state")
        _require_present(envelope, action_bindings)
        _require_absent(envelope, ("human_decision_sha256", "external_action_receipt_sha256"))
    elif kind == "action_simulated":
        if (envelope["approval_state"], envelope["effect_state"], envelope["effect_count"]) != (
            "pending",
            "simulated",
            0,
        ):
            raise GatekeeperAdapterViolation("invalid_simulated_action_state")
        _require_present(envelope, action_bindings)
        _require_absent(envelope, ("human_decision_sha256", "external_action_receipt_sha256"))
    elif kind == "action_rejected":
        if (envelope["approval_state"], envelope["effect_state"], envelope["effect_count"]) != (
            "rejected",
            "none",
            0,
        ):
            raise GatekeeperAdapterViolation("invalid_rejected_action_state")
        _require_present(envelope, action_bindings + ("human_decision_sha256",))
        _require_absent(envelope, ("external_action_receipt_sha256",))
    elif kind == "action_applied":
        if (envelope["approval_state"], envelope["effect_state"], envelope["effect_count"]) != (
            "approved",
            "applied",
            1,
        ):
            raise GatekeeperAdapterViolation("invalid_applied_action_state")
        _require_present(
            envelope,
            action_bindings + ("human_decision_sha256", "external_action_receipt_sha256"),
        )
    return envelope


def project_event(event: object, *, expected_gatekeeper_revision: str) -> dict[str, Any]:
    envelope = validate_event(event, expected_gatekeeper_revision=expected_gatekeeper_revision)
    kind = envelope["event_kind"]
    projection = {
        "schema": PROJECTION_SCHEMA,
        "record_kind": RECORD_KIND_BY_EVENT[kind],
        "source_event_sha256": _sha_object(envelope),
        "event_kind": kind,
        "gatekeeper_revision": envelope["gatekeeper_revision"],
        "actor_binding_sha256": envelope["actor_binding_sha256"],
        "resource_scope_sha256": envelope["resource_scope_sha256"],
        "request_binding_sha256": envelope["request_binding_sha256"],
        "candidate_sha256": envelope["candidate_sha256"],
        "work_order_sha256": envelope["work_order_sha256"],
        "capability_grant_sha256": envelope["capability_grant_sha256"],
        "human_decision_sha256": envelope["human_decision_sha256"],
        "external_action_receipt_sha256": envelope["external_action_receipt_sha256"],
        "context_admission_sha256": envelope["context_admission_sha256"],
        "corpus_scope_sha256": envelope["corpus_scope_sha256"],
        "redaction_profile": envelope["redaction_profile"],
        "effect_state": envelope["effect_state"],
        "effect_count": envelope["effect_count"],
        "private_body_included": False,
        "source_evidence_candidate": kind == "observation",
        "change_candidate": kind in {"action_submitted", "action_simulated"},
        "verification_receipt_candidate": kind == "action_applied",
        "cloudflare_approval_is_kotodama_decision": False,
        "execution_authorized": False,
        "promotion_authorized": False,
        "current_truth_changed": False,
    }
    return validate_projection(projection)


def validate_projection(projection: object) -> dict[str, Any]:
    current = _closed(projection, PROJECTION_KEYS, "invalid_projection_shape")
    if current["schema"] != PROJECTION_SCHEMA:
        raise GatekeeperAdapterViolation("invalid_projection_schema")
    kind = current["event_kind"]
    if kind not in EVENT_KINDS:
        raise GatekeeperAdapterViolation("invalid_projection_event_kind")
    if current["record_kind"] != RECORD_KIND_BY_EVENT[kind]:
        raise GatekeeperAdapterViolation("invalid_projection_record_kind")
    if not isinstance(current["gatekeeper_revision"], str) or not REVISION_RE.fullmatch(
        current["gatekeeper_revision"]
    ):
        raise GatekeeperAdapterViolation("invalid_projection_revision")
    for field in (
        "source_event_sha256",
        "actor_binding_sha256",
        "resource_scope_sha256",
        "request_binding_sha256",
    ):
        _digest(current[field])
    for field in (
        "candidate_sha256",
        "work_order_sha256",
        "capability_grant_sha256",
        "human_decision_sha256",
        "external_action_receipt_sha256",
        "context_admission_sha256",
        "corpus_scope_sha256",
    ):
        _digest(current[field], optional=True)
    if current["redaction_profile"] != REDACTION_PROFILE:
        raise GatekeeperAdapterViolation("invalid_projection_redaction_profile")
    if isinstance(current["effect_count"], bool) or not isinstance(current["effect_count"], int):
        raise GatekeeperAdapterViolation("invalid_projection_effect_count")
    for field in (
        "private_body_included",
        "cloudflare_approval_is_kotodama_decision",
        "execution_authorized",
        "promotion_authorized",
        "current_truth_changed",
    ):
        if current[field] is not False:
            raise GatekeeperAdapterViolation(f"unsafe_projection_{field}")
    expected_candidates = {
        "source_evidence_candidate": kind == "observation",
        "change_candidate": kind in {"action_submitted", "action_simulated"},
        "verification_receipt_candidate": kind == "action_applied",
    }
    if any(not isinstance(current[field], bool) for field in expected_candidates):
        raise GatekeeperAdapterViolation("invalid_candidate_classification")
    if any(current[field] is not expected for field, expected in expected_candidates.items()):
        raise GatekeeperAdapterViolation("invalid_candidate_classification")
    expected_effect = {
        "observation": ("none", 0),
        "action_submitted": ("none", 0),
        "action_simulated": ("simulated", 0),
        "action_rejected": ("none", 0),
        "action_applied": ("applied", 1),
    }[kind]
    if (current["effect_state"], current["effect_count"]) != expected_effect:
        raise GatekeeperAdapterViolation("invalid_projection_effect_state")
    context_bindings = ("context_admission_sha256", "corpus_scope_sha256")
    context_presence = tuple(current[field] is not None for field in context_bindings)
    if context_presence not in {(False, False), (True, True)}:
        raise GatekeeperAdapterViolation("invalid_projection_context_binding")
    action_bindings = ("candidate_sha256", "work_order_sha256", "capability_grant_sha256")
    if kind == "observation":
        _require_absent(
            current,
            action_bindings + ("human_decision_sha256", "external_action_receipt_sha256"),
        )
    elif kind in {"action_submitted", "action_simulated"}:
        _require_present(current, action_bindings)
        _require_absent(current, ("human_decision_sha256", "external_action_receipt_sha256"))
    elif kind == "action_rejected":
        _require_present(current, action_bindings + ("human_decision_sha256",))
        _require_absent(current, ("external_action_receipt_sha256",))
    elif kind == "action_applied":
        _require_present(
            current,
            action_bindings + ("human_decision_sha256", "external_action_receipt_sha256"),
        )
    return current
