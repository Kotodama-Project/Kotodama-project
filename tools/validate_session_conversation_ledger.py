"""Dependency-free validator and projector for the public Session ledger candidate.

The module deliberately accepts metadata only.  It never resolves a connector,
opens a payload vault, reads a transcript or audio object, writes a receipt, or
changes a remote system.  A valid result is local structural evidence, not
DEVICE_PASS, PROVIDER_PASS, PUBLIC_PASS, or HUMAN_GO.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


GENESIS_HASH = "0" * 64
MAX_INPUT_BYTES = 8_388_608
EVENT_KIND = "kotodama.conversation-event"
PROJECTION_KIND = "kotodama.session-knowledge-projection"

EVENT_REQUIRED = {
    "kind", "schema_revision", "event_id", "sequence", "session", "source",
    "content", "causation", "context", "ownership", "event", "decision",
    "policy_deviation", "retention", "provenance", "public_safety", "integrity",
    "previous_event_hash", "event_hash",
}
EVENT_ALLOWED = EVENT_REQUIRED | {"egress"}
SESSION_KEYS = {"state", "session_ref", "revision_ref", "binding_event_ref", "governance"}
GOVERNANCE_KEYS = {
    "creation_mode", "task_ssot_ref", "plan_ref", "requirement_refs", "invocation_ref", "model_ref",
    "capability_grant_refs", "knowledge_grant_refs", "mcp_tool_grant_refs", "delegation_ref",
    "dependency_refs", "parallel_status_ref", "evidence_refs", "invalidation_refs",
}
SOURCE_KEYS = {
    "type", "occurred_at", "ingested_at", "locator_ref", "source_revision_ref",
    "actor_ref", "identity_verification", "speaker_track_ref", "authority", "thread_ref", "channel_ref", "document_ref",
    "repository_ref", "evidence_ref", "consent_ref",
}
AUTHORITY_KEYS = {"role", "authority_ref"}
CONTENT_KEYS = {
    "payload_vault_ref", "vault_manifest_ref", "content_hash", "span_ref", "storage", "raw_content_embedded",
    "artifact_stage", "derived_from_event_refs",
}
CAUSATION_KEYS = {
    "caused_by_event_refs", "correlation_ref", "idempotency_key_ref", "cursor_ref",
    "replay_of_event_ref",
}
CONTEXT_KEYS = {"background_ref", "knowledge_scope_ref", "context_pack_refs", "omission_refs"}
OWNERSHIP_KEYS = {"owner_ref", "assignee_ref"}
EVENT_KEYS = {
    "kind", "state", "summary_ref", "correction_of_event_ref", "withdrawal_of_event_ref",
    "confirmation_of_event_ref", "invalidation_kind", "invalidation_refs", "binding",
}
EGRESS_KEYS = {
    "destination_binding", "consent_binding", "reply_artifact_ref", "delivery_receipt_ref",
    "delivery_state", "raw_content_embedded",
}
BINDING_KEYS = {"target_event_refs", "destination_session_ref", "destination_revision_ref"}
DECISION_KEYS = {
    "status", "candidate_ref", "human_evidence_ref", "human_decision_ref",
    "human_actor_ref", "current_truth_ref", "execution_authority_granted",
}
DEVIATION_KEYS = {"status", "rule_ref", "reason_ref", "approver_ref", "expires_at", "remediation_ref"}
RETENTION_KEYS = {
    "policy_ref", "policy_revision_ref", "storage_class", "encryption_ref", "encryption_status",
    "retain_until", "archive_target_kind", "archive_target_ref", "archive_target_uri_ref", "archive_package_digest", "snapshot_receipt_ref",
    "archive_status", "archive_receipt_ref", "restore_status", "restore_receipt_ref",
    "deletion_trigger", "deletion_state", "deletion_receipt_ref", "deletion_readback",
}
PROVENANCE_KEYS = {"adapter_contract_ref", "ingested_by_ref", "ingest_mode", "connector_ref", "extraction", "recovery"}
EXTRACTION_KEYS = {"kind", "candidate_binding", "model_ref", "confirmation_required"}
RECOVERY_KEYS = {"status", "cursor_ref", "receipt_ref"}
PUBLIC_SAFETY_KEYS = {
    "record_visibility", "raw_payload_embedded", "protected_payload_ref", "knowledge_scope_ref", "acl_state",
}
INTEGRITY_KEYS = {"marker", "marker_ref"}

SOURCE_TYPES = {"discord_text", "discord_voice", "notion", "github", "codex", "claude", "google_drive", "n8n", "system"}
ACTOR_AUTHORITY_ROLES = {
    "actor": {"HUMAN", "OWNER"},
    "speaker": {"HUMAN", "OWNER"},
    "agent": {"AGENT", "SYSTEM"},
    "connector": {"CONNECTOR", "SYSTEM"},
    "system": {"SYSTEM"},
}
EVENT_KINDS = {
    "session_open", "human_message", "voice_segment", "voice_reply", "tool_action", "agent_action",
    "decision_candidate", "decision_confirmed", "correction", "withdrawal", "confirmation",
    "source_update", "source_delete", "acl_loss", "invalidation", "pre_compact",
    "session_end", "session_seal", "session_binding", "recovery_marker", "integrity_marker",
}
EVENT_STATES = {"OBSERVED", "CANDIDATE", "CONFIRMED", "CORRECTED", "WITHDRAWN", "INVALIDATED", "PROJECTION_ONLY", "RECOVERY"}
DECISION_STATES = {"NONE", "LLM_CANDIDATE", "HUMAN_CONFIRMED", "HUMAN_CORRECTED", "HUMAN_WITHDRAWN"}
DEVIATION_STATES = {"NONE", "APPROVED", "EXPIRED", "REMEDIATED"}
INVALIDATION_KINDS = {"SOURCE_UPDATED", "SOURCE_DELETED", "ACL_LOST"}
ARTIFACT_STAGE_PARENTS = {
    "RAW_AUDIO": frozenset(),
    "RAW_SOURCE_JSON": frozenset(),
    "RAW_ASR": frozenset({"RAW_AUDIO", "RAW_SOURCE_JSON"}),
    "ALIGNED_TRANSCRIPT": frozenset({"RAW_ASR"}),
    "SPEAKER_ATTRIBUTED_TRANSCRIPT": frozenset({"RAW_ASR", "ALIGNED_TRANSCRIPT"}),
    "CORRECTED_TRANSCRIPT": frozenset({"SPEAKER_ATTRIBUTED_TRANSCRIPT"}),
    "MINUTES": frozenset({"SPEAKER_ATTRIBUTED_TRANSCRIPT", "CORRECTED_TRANSCRIPT"}),
    "SOURCE_EVIDENCE": frozenset(
        {"RAW_ASR", "ALIGNED_TRANSCRIPT", "SPEAKER_ATTRIBUTED_TRANSCRIPT", "CORRECTED_TRANSCRIPT", "MINUTES"}
    ),
}
PROJECTION_ARRAY_LIMITS = {
    "source_event_refs": 4096,
    "source_timeline": 4096,
    "evidence_refs": 4096,
    "unresolved_questions": 4096,
    "omissions": 4096,
    "confirmed_intent": 256,
    "decisions": 256,
    "corrections": 256,
    "action_items": 256,
    "policy_deviations": 256,
    "invalidation_refs": 4096,
}


class LedgerValidationError(ValueError):
    """Raised by append/project APIs when the current candidate is invalid."""

    def __init__(self, reason_codes: list[str]):
        self.reason_codes = list(dict.fromkeys(reason_codes))
        super().__init__(", ".join(self.reason_codes))


class DuplicateKeyError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise DuplicateKeyError(key)
        value[key] = item
    return value


def canonical_event_hash(event: dict[str, Any]) -> str:
    """Hash an event without its derived event_hash field."""
    payload = {key: value for key, value in event.items() if key != "event_hash"}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_projection_digest(projection: dict[str, Any]) -> str:
    payload = {key: value for key, value in projection.items() if key != "projection_digest"}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def seal_event(event: dict[str, Any], *, sequence: int, previous_hash: str) -> dict[str, Any]:
    result = copy.deepcopy(event)
    result["sequence"] = sequence
    result["previous_event_hash"] = previous_hash
    result["event_hash"] = "0" * 64
    result["event_hash"] = canonical_event_hash(result)
    return result


def _keys(value: Any, required: set[str], allowed: set[str], label: str, reasons: list[str]) -> bool:
    if not isinstance(value, dict):
        reasons.append("SCHEMA_INVALID")
        return False
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown or missing:
        reasons.append("SCHEMA_INVALID")
    return not unknown and not missing


def _string(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _is_integer_number(value: Any) -> bool:
    """Match JSON Schema's integer semantics, including integral JSON floats."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value) and value.is_integer()


def _integer_value(value: Any) -> int:
    return int(value)


def _sequence_is_not_earlier(record: Any, current_sequence: int) -> bool:
    if not isinstance(record, dict) or not _is_integer_number(record.get("sequence")):
        return True
    return _integer_value(record["sequence"]) >= current_sequence


def _same_session(left: Any, right: Any) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    if left.get("state") != right.get("state"):
        return False
    return left.get("state") != "BOUND" or left.get("session_ref") == right.get("session_ref")


def _integrity_marker(record: Any) -> str | None:
    if not isinstance(record, dict) or not isinstance(record.get("integrity"), dict):
        return None
    marker = record["integrity"].get("marker")
    return marker if isinstance(marker, str) else None


def _match(value: Any, pattern: str) -> bool:
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def _public_ref_is_safe(value: Any) -> bool:
    """Reject direct identifiers and credential-like values from public refs."""
    if not isinstance(value, str):
        return True
    lowered = value.casefold()
    if re.search(r"\d{17,20}", value):
        return False
    if re.search(
        r"(?:sk-|pk-|rk-|ghp_|gho_|github_pat_|xox[baprs]-|aiza|akia|eyj|bearer-)",
        lowered,
    ):
        return False
    if re.search(r"[@\s\\:]", value):
        return False
    if value.startswith(("/", "\\\\")) or re.match(r"^[A-Za-z]:[\\/]", value):
        return False
    if re.search(r"(?:^|/)(?:\d{1,3}\.){3}\d{1,3}(?:/|$)", value):
        return False
    if re.search(r"(?:^|/)(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/|$)", lowered):
        return False
    return True


def _ref(value: Any, reasons: list[str], *, pattern: str = r"^ref/[a-z0-9][a-z0-9/_-]{1,510}$", nullable: bool = False) -> bool:
    if value is None and nullable:
        return True
    if not _public_ref_is_safe(value):
        reasons.append("PUBLIC_METADATA_UNSAFE_REF")
    bounds = {
        r"^ref/[a-z0-9][a-z0-9/_-]{1,510}$": (7, 512),
        r"^ref/event/[a-z0-9][a-z0-9/_-]{1,500}$": (10, 512),
        r"^ref/session/[a-z0-9][a-z0-9/_-]{1,244}$": (12, 256),
        r"^ref/session-revision/[1-9][0-9]*$": (21, 256),
    }.get(pattern)
    if not _match(value, pattern) or (bounds is not None and not (bounds[0] <= len(value) <= bounds[1])):
        reasons.append("SCHEMA_INVALID")
        return False
    return True


def _actor_kind(actor_ref: Any) -> str | None:
    if not isinstance(actor_ref, str):
        return None
    match = re.fullmatch(r"ref/(actor|speaker|agent|connector|system)/[a-z0-9][a-z0-9/_-]{1,240}", actor_ref)
    return match.group(1) if match else None


def _actor_authority_is_consistent(actor_ref: Any, role: Any) -> bool:
    kind = _actor_kind(actor_ref)
    return kind is not None and role in ACTOR_AUTHORITY_ROLES.get(kind, set())


def _sha(value: Any, reasons: list[str]) -> bool:
    if not _match(value, r"^[0-9a-f]{64}$"):
        reasons.append("SCHEMA_INVALID")
        return False
    return True


def _timestamp(value: Any, reasons: list[str]) -> bool:
    if not _match(value, r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})$"):
        reasons.append("SCHEMA_INVALID")
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        reasons.append("SCHEMA_INVALID")
        return False
    return True


def _timestamp_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _ref_list(value: Any, reasons: list[str], *, events: bool = False) -> bool:
    if not isinstance(value, list) or len(value) > 64:
        reasons.append("SCHEMA_INVALID")
        return False
    seen: list[Any] = []
    pattern = r"^ref/event/[a-z0-9][a-z0-9/_-]{1,500}$" if events else r"^ref/[a-z0-9][a-z0-9/_-]{1,510}$"
    for item in value:
        if not isinstance(item, str):
            reasons.append("SCHEMA_INVALID")
            continue
        if item in seen:
            reasons.append("SCHEMA_INVALID")
        seen.append(item)
        _ref(item, reasons, pattern=pattern)
    return True


def _validate_event_shape(record: Any) -> list[str]:
    reasons: list[str] = []
    if not _keys(record, EVENT_REQUIRED, EVENT_ALLOWED, "event", reasons):
        return list(dict.fromkeys(reasons))
    if record.get("kind") != EVENT_KIND or record.get("schema_revision") != "v1":
        reasons.append("SCHEMA_INVALID")
    if not _ref(record.get("event_id"), reasons, pattern=r"^ref/event/[a-z0-9][a-z0-9/_-]{1,500}$"):
        return list(dict.fromkeys(reasons))
    if not _is_integer_number(record.get("sequence")) or record["sequence"] < 1:
        reasons.append("SCHEMA_INVALID")

    session = record["session"]
    if _keys(session, SESSION_KEYS, SESSION_KEYS, "session", reasons):
        state = session.get("state")
        if state not in {"BOUND", "UNASSIGNED_INBOX"}:
            reasons.append("SCHEMA_INVALID")
        _ref(session.get("session_ref"), reasons, pattern=r"^ref/session/[a-z0-9][a-z0-9/_-]{1,244}$", nullable=True)
        _ref(session.get("revision_ref"), reasons, pattern=r"^ref/session-revision/[1-9][0-9]*$", nullable=True)
        _ref(session.get("binding_event_ref"), reasons, pattern=r"^ref/event/[a-z0-9][a-z0-9/_-]{1,500}$", nullable=True)
        governance = session.get("governance")
        if _keys(governance, GOVERNANCE_KEYS, GOVERNANCE_KEYS, "session_governance", reasons):
            if governance.get("creation_mode") not in {"UNASSIGNED_INBOX", "AUTO_CREATED", "EXPLICIT"}:
                reasons.append("SCHEMA_INVALID")
            for key in ("task_ssot_ref", "plan_ref", "invocation_ref", "model_ref", "delegation_ref", "parallel_status_ref"):
                _ref(governance.get(key), reasons, nullable=True)
            for key in ("requirement_refs", "capability_grant_refs", "knowledge_grant_refs", "mcp_tool_grant_refs", "dependency_refs", "evidence_refs", "invalidation_refs"):
                _ref_list(governance.get(key), reasons)
            if state == "UNASSIGNED_INBOX":
                if governance.get("creation_mode") != "UNASSIGNED_INBOX" or governance.get("task_ssot_ref") is not None or governance.get("invocation_ref") is not None or governance.get("model_ref") is not None or governance.get("delegation_ref") is not None:
                    reasons.append("UNASSIGNED_GOVERNANCE_INVALID")
                if any(governance.get(key) for key in ("capability_grant_refs", "knowledge_grant_refs", "mcp_tool_grant_refs")):
                    reasons.append("UNASSIGNED_GOVERNANCE_INVALID")
            elif state == "BOUND":
                required_refs = ("task_ssot_ref", "plan_ref", "invocation_ref", "model_ref", "delegation_ref", "parallel_status_ref")
                required_lists = ("requirement_refs", "capability_grant_refs", "knowledge_grant_refs", "mcp_tool_grant_refs", "evidence_refs")
                if governance.get("creation_mode") not in {"AUTO_CREATED", "EXPLICIT"} or any(governance.get(key) is None for key in required_refs) or any(not governance.get(key) for key in required_lists):
                    reasons.append("SESSION_GOVERNANCE_INCOMPLETE")
        if state == "UNASSIGNED_INBOX" and any(session.get(key) is not None for key in ("session_ref", "revision_ref", "binding_event_ref")):
            reasons.append("UNASSIGNED_SESSION_HAS_BINDING")
        if state == "BOUND" and (session.get("session_ref") is None or session.get("revision_ref") is None):
            reasons.append("SCHEMA_INVALID")

    source = record["source"]
    if _keys(source, SOURCE_KEYS, SOURCE_KEYS, "source", reasons):
        if source.get("type") not in SOURCE_TYPES:
            reasons.append("SCHEMA_INVALID")
        _timestamp(source.get("occurred_at"), reasons)
        _timestamp(source.get("ingested_at"), reasons)
        _ref(source.get("locator_ref"), reasons)
        _ref(source.get("source_revision_ref"), reasons)
        actor = source.get("actor_ref")
        if not _ref(actor, reasons, pattern=r"^ref/(actor|speaker|agent|connector|system)/[a-z0-9][a-z0-9/_-]{1,240}$"):
            reasons.append("ACTOR_AUTHORITY_CONFUSION")
        authority = source.get("authority")
        if _keys(authority, AUTHORITY_KEYS, AUTHORITY_KEYS, "authority", reasons):
            if authority.get("role") not in {"HUMAN", "OWNER", "AGENT", "CONNECTOR", "SYSTEM"}:
                reasons.append("SCHEMA_INVALID")
            _ref(authority.get("authority_ref"), reasons, pattern=r"^ref/authority/[a-z0-9][a-z0-9/_-]{1,240}$")
            if actor == authority.get("authority_ref") or (isinstance(actor, str) and actor.startswith("ref/authority/")):
                reasons.append("ACTOR_AUTHORITY_CONFUSION")
            if not _actor_authority_is_consistent(actor, authority.get("role")):
                reasons.append("ACTOR_AUTHORITY_ROLE_MISMATCH")
        expected_identity_state = (
            "UNVERIFIED_PUBLIC_CLAIM"
            if _actor_kind(actor) in {"actor", "speaker"}
            else "NOT_APPLICABLE"
        )
        if source.get("identity_verification") != expected_identity_state:
            reasons.append("IDENTITY_VERIFICATION_STATE_INVALID")
        _ref(source.get("speaker_track_ref"), reasons, pattern=r"^ref/track/[a-z0-9][a-z0-9/_-]{1,240}$", nullable=True)
        if source.get("type") == "discord_voice" and source.get("speaker_track_ref") is None:
            reasons.append("VOICE_TRACK_REF_MISSING")
        for key in ("thread_ref", "channel_ref", "document_ref", "repository_ref"):
            _ref(source.get(key), reasons, nullable=True)
        _ref(source.get("evidence_ref"), reasons)
        _ref(source.get("consent_ref"), reasons, nullable=True)
        if source.get("type") != "system" and source.get("consent_ref") is None:
            reasons.append("CONSENT_REF_MISSING")

    content = record["content"]
    if _keys(content, CONTENT_KEYS, CONTENT_KEYS, "content", reasons):
        _ref(content.get("payload_vault_ref"), reasons, pattern=r"^ref/vault/[a-z0-9][a-z0-9/_-]{1,240}$")
        _ref(content.get("vault_manifest_ref"), reasons, pattern=r"^ref/vault-manifest/[a-z0-9][a-z0-9/_-]{1,240}$")
        _sha(content.get("content_hash"), reasons)
        _ref(content.get("span_ref"), reasons, nullable=True)
        if content.get("storage") != "PROTECTED_PAYLOAD_VAULT" or content.get("raw_content_embedded") is not False:
            reasons.append("RAW_PRIVATE_CONTENT")
        if content.get("artifact_stage") not in ARTIFACT_STAGE_PARENTS:
            reasons.append("SCHEMA_INVALID")
        _ref_list(content.get("derived_from_event_refs"), reasons, events=True)

    causation = record["causation"]
    if _keys(causation, CAUSATION_KEYS, CAUSATION_KEYS, "causation", reasons):
        _ref_list(causation.get("caused_by_event_refs"), reasons, events=True)
        _ref(causation.get("correlation_ref"), reasons)
        _ref(causation.get("idempotency_key_ref"), reasons, pattern=r"^ref/idempotency/[a-z0-9][a-z0-9/_-]{1,240}$")
        _ref(causation.get("cursor_ref"), reasons, nullable=True)
        _ref(causation.get("replay_of_event_ref"), reasons, pattern=r"^ref/event/[a-z0-9][a-z0-9/_-]{1,500}$", nullable=True)

    context = record["context"]
    if _keys(context, CONTEXT_KEYS, CONTEXT_KEYS, "context", reasons):
        _ref(context.get("background_ref"), reasons, nullable=True)
        _ref(context.get("knowledge_scope_ref"), reasons)
        _ref_list(context.get("context_pack_refs"), reasons)
        _ref_list(context.get("omission_refs"), reasons)

    ownership = record["ownership"]
    if _keys(ownership, OWNERSHIP_KEYS, OWNERSHIP_KEYS, "ownership", reasons):
        _ref(ownership.get("owner_ref"), reasons, pattern=r"^ref/owner/[a-z0-9][a-z0-9/_-]{1,240}$")
        _ref(ownership.get("assignee_ref"), reasons, pattern=r"^ref/assignee/[a-z0-9][a-z0-9/_-]{1,240}$", nullable=True)

    detail = record["event"]
    detail_kind = detail.get("kind") if isinstance(detail, dict) else None
    if _keys(detail, EVENT_KEYS, EVENT_KEYS, "event_detail", reasons):
        if detail.get("kind") not in EVENT_KINDS or detail.get("state") not in EVENT_STATES:
            reasons.append("SCHEMA_INVALID")
        _ref(detail.get("summary_ref"), reasons)
        for key in ("correction_of_event_ref", "withdrawal_of_event_ref", "confirmation_of_event_ref"):
            _ref(detail.get(key), reasons, pattern=r"^ref/event/[a-z0-9][a-z0-9/_-]{1,500}$", nullable=True)
        if detail.get("invalidation_kind") not in INVALIDATION_KINDS and detail.get("invalidation_kind") is not None:
            reasons.append("SCHEMA_INVALID")
        _ref_list(detail.get("invalidation_refs"), reasons)
        binding = detail.get("binding")
        if _keys(binding, BINDING_KEYS, BINDING_KEYS, "binding", reasons):
            _ref_list(binding.get("target_event_refs"), reasons, events=True)
            _ref(binding.get("destination_session_ref"), reasons, pattern=r"^ref/session/[a-z0-9][a-z0-9/_-]{1,244}$", nullable=True)
            _ref(binding.get("destination_revision_ref"), reasons, pattern=r"^ref/session-revision/[1-9][0-9]*$", nullable=True)

    egress = record.get("egress")
    if detail_kind == "voice_reply":
        if record.get("source", {}).get("channel_ref") is None:
            reasons.append("VOICE_REPLY_SOURCE_CHANNEL_REQUIRED")
        if _keys(egress, EGRESS_KEYS, EGRESS_KEYS, "egress", reasons):
            for key in ("reply_artifact_ref", "delivery_receipt_ref"):
                _ref(egress.get(key), reasons)
            if (
                egress.get("destination_binding") != "SOURCE_CHANNEL"
                or egress.get("consent_binding") != "SOURCE_CONSENT"
                or egress.get("delivery_state") != "VERIFIED"
                or egress.get("raw_content_embedded") is not False
            ):
                reasons.append("VOICE_REPLY_EGRESS_INVALID")
    elif egress is not None:
        reasons.append("VOICE_REPLY_EGRESS_INVALID")
    if detail_kind in {"voice_segment", "voice_reply"} and record.get("source", {}).get("type") != "discord_voice":
        reasons.append("VOICE_SOURCE_TYPE_INVALID")

    decision = record["decision"]
    if _keys(decision, DECISION_KEYS, DECISION_KEYS, "decision", reasons):
        if decision.get("status") not in DECISION_STATES:
            reasons.append("SCHEMA_INVALID")
        _ref(decision.get("candidate_ref"), reasons, pattern=r"^ref/candidate/[a-z0-9][a-z0-9/_-]{1,240}$", nullable=True)
        _ref(decision.get("human_evidence_ref"), reasons, nullable=True)
        _ref(decision.get("human_decision_ref"), reasons, nullable=True)
        _ref(decision.get("human_actor_ref"), reasons, pattern=r"^ref/person/[a-z0-9][a-z0-9/_-]{1,240}$", nullable=True)
        if decision.get("current_truth_ref") is not None or decision.get("execution_authority_granted") is not False:
            reasons.append("DECISION_OVERCLAIM")

    deviation = record["policy_deviation"]
    if _keys(deviation, DEVIATION_KEYS, DEVIATION_KEYS, "policy_deviation", reasons):
        if deviation.get("status") not in DEVIATION_STATES:
            reasons.append("SCHEMA_INVALID")
        for key in ("rule_ref", "reason_ref", "approver_ref", "remediation_ref"):
            _ref(deviation.get(key), reasons, nullable=True)
        _timestamp(deviation.get("expires_at"), reasons) if deviation.get("expires_at") is not None else None
        if deviation.get("status") != "NONE" and any(deviation.get(key) is None for key in ("rule_ref", "reason_ref", "approver_ref", "expires_at", "remediation_ref")):
            reasons.append("DEVIATION_FIELDS_INCOMPLETE")

    retention = record["retention"]
    if _keys(retention, RETENTION_KEYS, RETENTION_KEYS, "retention", reasons):
        _ref(retention.get("policy_ref"), reasons)
        _ref(retention.get("policy_revision_ref"), reasons)
        if retention.get("storage_class") not in {"PROTECTED_HOT", "ENCRYPTED_COLD_ARCHIVE", "DERIVED_SEARCH_INDEX"}:
            reasons.append("SCHEMA_INVALID")
        _ref(retention.get("encryption_ref"), reasons)
        if retention.get("encryption_status") not in {"DECLARED_UNVERIFIED", "NOT_APPLICABLE"}:
            reasons.append("SCHEMA_INVALID")
        _timestamp(retention.get("retain_until"), reasons)
        if retention.get("archive_target_kind") not in {"NONE", "SESSION_ARCHIVE_VAULT", "ARCHIVE_TARGET"}:
            reasons.append("SCHEMA_INVALID")
        for key in ("archive_target_ref", "archive_target_uri_ref", "snapshot_receipt_ref"):
            _ref(retention.get(key), reasons, nullable=True)
        if retention.get("archive_package_digest") is not None:
            _sha(retention.get("archive_package_digest"), reasons)
        if retention.get("archive_target_kind") == "NONE" and any(retention.get(key) is not None for key in ("archive_target_ref", "archive_target_uri_ref", "archive_package_digest")):
            reasons.append("ARCHIVE_TARGET_INVALID")
        if retention.get("archive_target_kind") == "NONE" and any(retention.get(key) is not None for key in ("snapshot_receipt_ref", "archive_receipt_ref", "restore_receipt_ref")):
            reasons.append("ARCHIVE_TARGET_INVALID")
        if retention.get("archive_target_kind") == "NONE" and (retention.get("archive_status") != "NOT_REQUESTED" or retention.get("restore_status") != "NOT_REQUESTED"):
            reasons.append("ARCHIVE_STATUS_INCOMPLETE")
        if retention.get("storage_class") == "ENCRYPTED_COLD_ARCHIVE" and retention.get("archive_target_kind") == "NONE":
            reasons.append("COLD_ARCHIVE_TARGET_REQUIRED")
        if retention.get("archive_target_kind") != "NONE" and any(retention.get(key) is None for key in ("archive_target_ref", "archive_target_uri_ref", "archive_package_digest")):
            reasons.append("ARCHIVE_TARGET_INCOMPLETE")
        if retention.get("archive_status") not in {"NOT_REQUESTED", "DECLARED", "RESTORE_PENDING", "RESTORED", "DELETED", "FAILED"}:
            reasons.append("SCHEMA_INVALID")
        _ref(retention.get("archive_receipt_ref"), reasons, nullable=True)
        if retention.get("restore_status") not in {"NOT_REQUESTED", "PENDING", "RESTORED", "FAILED"}:
            reasons.append("SCHEMA_INVALID")
        _ref(retention.get("restore_receipt_ref"), reasons, nullable=True)
        if retention.get("archive_status") in {"DECLARED", "RESTORED", "DELETED"} and retention.get("archive_receipt_ref") is None:
            reasons.append("ARCHIVE_RECEIPT_INVALID")
        if retention.get("archive_target_kind") != "NONE" and retention.get("archive_status") == "NOT_REQUESTED":
            reasons.append("ARCHIVE_STATUS_INCOMPLETE")
        if retention.get("archive_status") == "RESTORE_PENDING" and retention.get("restore_status") != "PENDING":
            reasons.append("ARCHIVE_RESTORE_STATE_INVALID")
        if retention.get("restore_status") == "PENDING" and retention.get("archive_status") != "RESTORE_PENDING":
            reasons.append("ARCHIVE_RESTORE_STATE_INVALID")
        if retention.get("archive_status") == "RESTORED" and retention.get("restore_status") != "RESTORED":
            reasons.append("ARCHIVE_RESTORE_STATE_INVALID")
        if retention.get("restore_status") == "RESTORED" and retention.get("archive_status") not in {"RESTORED", "DELETED"}:
            reasons.append("ARCHIVE_RESTORE_STATE_INVALID")
        if retention.get("restore_status") == "RESTORED" and retention.get("restore_receipt_ref") is None:
            reasons.append("RESTORE_RECEIPT_INVALID")
        if retention.get("restore_status") == "NOT_REQUESTED" and retention.get("restore_receipt_ref") is not None:
            reasons.append("RESTORE_RECEIPT_INVALID")
        if retention.get("archive_status") == "DELETED":
            if retention.get("deletion_state") != "CONFIRMED" or retention.get("deletion_readback") != "CONFIRMED" or retention.get("deletion_receipt_ref") is None:
                reasons.append("ARCHIVE_DELETION_STATE_INVALID")
            if retention.get("restore_status") not in {"NOT_REQUESTED", "RESTORED"}:
                reasons.append("ARCHIVE_RESTORE_STATE_INVALID")
        if retention.get("archive_target_kind") != "NONE" and (
            retention.get("deletion_state") == "CONFIRMED"
            or retention.get("deletion_readback") == "CONFIRMED"
            or retention.get("deletion_receipt_ref") is not None
        ) and retention.get("archive_status") != "DELETED":
            reasons.append("ARCHIVE_DELETION_STATE_INVALID")
        if retention.get("storage_class") == "ENCRYPTED_COLD_ARCHIVE" and retention.get("encryption_status") == "NOT_APPLICABLE":
            reasons.append("COLD_ARCHIVE_ENCRYPTION_REQUIRED")
        if retention.get("deletion_trigger") not in {"expiry", "withdrawal", "source_delete", "expiry_or_withdrawal"}:
            reasons.append("SCHEMA_INVALID")
        if retention.get("deletion_state") not in {"NOT_REQUESTED", "PENDING", "CONFIRMED", "FAILED"} or retention.get("deletion_readback") not in {"NOT_REQUESTED", "PENDING", "CONFIRMED", "FAILED"}:
            reasons.append("SCHEMA_INVALID")
        _ref(retention.get("deletion_receipt_ref"), reasons, pattern=r"^ref/deletion-receipt/[a-z0-9][a-z0-9/_-]{1,240}$", nullable=True)
        if retention.get("deletion_readback") == "CONFIRMED" and (retention.get("deletion_receipt_ref") is None or retention.get("deletion_state") != "CONFIRMED"):
            reasons.append("DELETION_READBACK_RECEIPT_INVALID")
        if retention.get("deletion_state") == "CONFIRMED" and (retention.get("deletion_readback") != "CONFIRMED" or retention.get("deletion_receipt_ref") is None):
            reasons.append("DELETION_STATE_RECEIPT_INVALID")
        if record.get("content", {}).get("artifact_stage") in {
            "RAW_AUDIO",
            "RAW_SOURCE_JSON",
            "RAW_ASR",
            "ALIGNED_TRANSCRIPT",
            "SPEAKER_ATTRIBUTED_TRANSCRIPT",
            "SOURCE_EVIDENCE",
        } and retention.get("storage_class") == "DERIVED_SEARCH_INDEX":
            reasons.append("RAW_EVIDENCE_STORAGE_CLASS_INVALID")

    provenance = record["provenance"]
    if _keys(provenance, PROVENANCE_KEYS, PROVENANCE_KEYS, "provenance", reasons):
        _ref(provenance.get("adapter_contract_ref"), reasons)
        _ref(provenance.get("ingested_by_ref"), reasons)
        if provenance.get("ingest_mode") not in {"ONLINE", "OFFLINE_RECOVERY"}:
            reasons.append("SCHEMA_INVALID")
        _ref(provenance.get("connector_ref"), reasons)
        extraction = provenance.get("extraction")
        if _keys(extraction, EXTRACTION_KEYS, EXTRACTION_KEYS, "extraction", reasons):
            if extraction.get("kind") not in {"NONE", "LLM_CANDIDATE"} or extraction.get("confirmation_required") is not True:
                reasons.append("SCHEMA_INVALID")
            _ref(extraction.get("model_ref"), reasons, nullable=True)
            expected_binding = "DECISION_CANDIDATE" if extraction.get("kind") == "LLM_CANDIDATE" else "NOT_APPLICABLE"
            if extraction.get("candidate_binding") != expected_binding:
                reasons.append("EXTRACTION_CANDIDATE_BINDING_INVALID")
            if extraction.get("kind") == "LLM_CANDIDATE" and extraction.get("model_ref") is None:
                reasons.append("LLM_MODEL_PROVENANCE_MISSING")
        recovery = provenance.get("recovery")
        if _keys(recovery, RECOVERY_KEYS, RECOVERY_KEYS, "recovery", reasons):
            if recovery.get("status") not in {"NOT_APPLICABLE", "PENDING", "RECOVERED", "FAILED"}:
                reasons.append("SCHEMA_INVALID")
            _ref(recovery.get("cursor_ref"), reasons, nullable=True)
            _ref(recovery.get("receipt_ref"), reasons, nullable=True)
            if provenance.get("ingest_mode") == "OFFLINE_RECOVERY" and (recovery.get("cursor_ref") is None or recovery.get("receipt_ref") is None or recovery.get("status") != "RECOVERED"):
                reasons.append("OFFLINE_RECOVERY_INCOMPLETE")
            if provenance.get("ingest_mode") == "ONLINE" and (
                recovery.get("status") != "NOT_APPLICABLE"
                or recovery.get("cursor_ref") is not None
                or recovery.get("receipt_ref") is not None
            ):
                reasons.append("SCHEMA_INVALID")

    safety = record["public_safety"]
    if _keys(safety, PUBLIC_SAFETY_KEYS, PUBLIC_SAFETY_KEYS, "public_safety", reasons):
        if safety.get("record_visibility") != "PUBLIC_SANITIZED_METADATA" or safety.get("raw_payload_embedded") is not False:
            reasons.append("RAW_PRIVATE_CONTENT")
        _ref(safety.get("protected_payload_ref"), reasons, pattern=r"^ref/vault/[a-z0-9][a-z0-9/_-]{1,240}$")
        _ref(safety.get("knowledge_scope_ref"), reasons)
        if safety.get("acl_state") not in {"AVAILABLE", "UNKNOWN", "LOST", "REVOKED"}:
            reasons.append("SCHEMA_INVALID")

    integrity = record["integrity"]
    if _keys(integrity, INTEGRITY_KEYS, INTEGRITY_KEYS, "integrity", reasons):
        marker = integrity.get("marker")
        if not isinstance(marker, str) or marker not in {"NONE", "GAP", "CORRUPT", "RECOVERY"}:
            reasons.append("SCHEMA_INVALID")
        _ref(integrity.get("marker_ref"), reasons, nullable=True)
        if integrity.get("marker") != "NONE" and integrity.get("marker_ref") is None:
            reasons.append("INTEGRITY_MARKER_UNBOUND")
        if integrity.get("marker") == "NONE" and any(
            integrity.get(key) is not None
            for key in ("marker_ref",)
        ):
            reasons.append("INTEGRITY_MARKER_UNBOUND")
    _sha(record.get("previous_event_hash"), reasons)
    _sha(record.get("event_hash"), reasons)
    return list(dict.fromkeys(reasons))


def _semantic_reasons(records: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    seen_event_ids: set[str] = set()
    seen_idempotency: set[str] = set()
    previous_sequence = 0
    previous_ingested: datetime | None = None
    expected_previous = GENESIS_HASH
    known = {
        record["event_id"]: record
        for record in records
        if isinstance(record, dict) and isinstance(record.get("event_id"), str)
    }
    latest_revision: dict[str, int] = {}
    seen_content_artifacts = {"payload_vault_ref": set(), "vault_manifest_ref": set(), "content_hash": set()}
    candidate_states: dict[str, str] = {}
    restored_archive_receipts: dict[tuple[str, str, str, str, str, str], set[str]] = {}
    for record in records:
        shape_reasons = _validate_event_shape(record)
        reasons.extend(shape_reasons)
        if shape_reasons:
            continue
        sequence = record["sequence"]
        sequence_number = _integer_value(sequence)
        if sequence_number != previous_sequence + 1:
            reasons.append("SEQUENCE_NOT_CONTIGUOUS")
        previous_sequence = sequence_number
        event_id = record["event_id"]
        if event_id in seen_event_ids:
            reasons.append("DUPLICATE_EVENT_ID")
        seen_event_ids.add(event_id)
        idem = record["causation"]["idempotency_key_ref"]
        if idem in seen_idempotency:
            reasons.append("DUPLICATE_IDEMPOTENCY_KEY")
        seen_idempotency.add(idem)
        if record["previous_event_hash"] != expected_previous or record["event_hash"] != canonical_event_hash(record):
            reasons.append("HASH_CHAIN_BROKEN" if record["previous_event_hash"] != expected_previous else "CONTENT_DIGEST_DRIFT")
        expected_previous = record["event_hash"]
        ingested = _timestamp_instant(record["source"]["ingested_at"])
        if previous_ingested is not None and ingested < previous_ingested:
            reasons.append("INGESTED_AT_NOT_MONOTONIC")
        previous_ingested = ingested
        for causal_ref in record["causation"]["caused_by_event_refs"]:
            causal_record = known.get(causal_ref)
            if causal_record is None:
                reasons.append("CAUSATION_REF_MISSING")
            elif causal_ref == event_id or _sequence_is_not_earlier(causal_record, sequence_number):
                reasons.append("CAUSATION_ORDER_INVALID")
        replay_ref = record["causation"]["replay_of_event_ref"]
        if replay_ref is not None:
            replay_target = known.get(replay_ref)
            if replay_target is None:
                reasons.append("REPLAY_TARGET_MISSING")
            elif replay_ref == event_id:
                reasons.append("REPLAY_TARGET_SELF_REFERENCE")
            elif not _same_session(record.get("session"), replay_target.get("session")):
                reasons.append("REPLAY_SESSION_INVALID")
            elif _sequence_is_not_earlier(replay_target, sequence_number):
                reasons.append("REPLAY_TARGET_ORDER_INVALID")

        session = record["session"]
        retention = record["retention"]
        if retention["archive_target_kind"] != "NONE":
            archive_history_key = (
                session["state"],
                session.get("session_ref") or "",
                retention["archive_target_kind"],
                retention["archive_target_ref"],
                retention["archive_target_uri_ref"],
                retention["archive_package_digest"],
            )
            prior_restore_receipts = restored_archive_receipts.get(archive_history_key, set())
            if prior_restore_receipts and retention["archive_status"] == "DELETED" and (
                retention["restore_status"] != "RESTORED"
                or retention["restore_receipt_ref"] not in prior_restore_receipts
            ):
                reasons.append("ARCHIVE_RESTORE_HISTORY_LOST")
            if retention["restore_status"] == "RESTORED" and isinstance(retention["restore_receipt_ref"], str):
                restored_archive_receipts.setdefault(archive_history_key, set()).add(retention["restore_receipt_ref"])
        content = record["content"]
        for artifact_field, seen in seen_content_artifacts.items():
            artifact_value = content[artifact_field]
            if artifact_value in seen:
                reasons.append("CONTENT_ARTIFACT_ALIAS")
            seen.add(artifact_value)
        stage = content["artifact_stage"]
        parents = content["derived_from_event_refs"]
        if stage in {"RAW_AUDIO", "RAW_SOURCE_JSON"} and parents:
            reasons.append("RAW_ARTIFACT_HAS_PARENT")
        if stage not in {"RAW_AUDIO", "RAW_SOURCE_JSON"} and not parents:
            reasons.append("CONTENT_LINEAGE_PARENT_REQUIRED")
        for parent_ref in parents:
            parent = known.get(parent_ref)
            if parent is None:
                reasons.append("CONTENT_LINEAGE_PARENT_MISSING")
                continue
            if parent_ref == event_id or _sequence_is_not_earlier(parent, sequence_number):
                reasons.append("CONTENT_LINEAGE_ORDER_INVALID")
            parent_content = parent.get("content", {})
            if not isinstance(parent_content, dict):
                reasons.append("CONTENT_LINEAGE_STAGE_INVALID")
                continue
            if parent.get("session", {}).get("state") != session.get("state") or (
                session.get("state") == "BOUND"
                and parent.get("session", {}).get("session_ref") != session.get("session_ref")
            ):
                reasons.append("CONTENT_LINEAGE_SESSION_INVALID")
            if parent_content.get("artifact_stage") not in ARTIFACT_STAGE_PARENTS.get(stage, frozenset()):
                reasons.append("CONTENT_LINEAGE_STAGE_INVALID")
            if any(content.get(key) == parent_content.get(key) for key in ("payload_vault_ref", "vault_manifest_ref", "content_hash")):
                reasons.append("CONTENT_LINEAGE_REUSE")

        if session["state"] == "BOUND":
            session_name = session["session_ref"]
            revision_match = re.fullmatch(r"ref/session-revision/([1-9][0-9]*)", session["revision_ref"])
            revision = int(revision_match.group(1)) if revision_match else -1
            if revision < latest_revision.get(session_name, -1):
                reasons.append("STALE_SESSION_REVISION")
            latest_revision[session_name] = max(revision, latest_revision.get(session_name, -1))

        detail = record["event"]
        binding = detail["binding"]
        if detail["kind"] == "session_binding":
            if session["state"] != "BOUND" or not binding["target_event_refs"] or binding["destination_session_ref"] != session["session_ref"] or binding["destination_revision_ref"] != session["revision_ref"]:
                reasons.append("SESSION_BINDING_INVALID")
            for target_ref in binding["target_event_refs"]:
                target = known.get(target_ref)
                if target is None or target.get("session", {}).get("state") != "UNASSIGNED_INBOX":
                    reasons.append("SESSION_BINDING_TARGET_INVALID")
                elif target_ref == event_id or _sequence_is_not_earlier(target, sequence_number):
                    reasons.append("SESSION_BINDING_TARGET_ORDER_INVALID")
        elif binding["target_event_refs"] or binding["destination_session_ref"] is not None or binding["destination_revision_ref"] is not None:
            reasons.append("NON_BINDING_EVENT_HAS_BINDING")

        lifecycle_target_fields = {
            "correction": "correction_of_event_ref",
            "withdrawal": "withdrawal_of_event_ref",
            "confirmation": "confirmation_of_event_ref",
            "decision_confirmed": "confirmation_of_event_ref",
        }
        if detail["kind"] in lifecycle_target_fields:
            target_ref = detail[lifecycle_target_fields[detail["kind"]]]
            if target_ref is None:
                reasons.append("LIFECYCLE_TARGET_REQUIRED")
            else:
                target = known.get(target_ref)
                if target is None:
                    reasons.append("LIFECYCLE_TARGET_MISSING")
                elif target_ref == event_id:
                    reasons.append("LIFECYCLE_TARGET_SELF_REFERENCE")
                elif _sequence_is_not_earlier(target, sequence_number):
                    reasons.append("LIFECYCLE_TARGET_ORDER_INVALID")
                elif target.get("event", {}).get("kind") not in {"decision_candidate", "correction", "withdrawal", "confirmation", "decision_confirmed"}:
                    reasons.append("LIFECYCLE_TARGET_RELATION_INVALID")
                elif not _same_session(session, target.get("session")):
                    reasons.append("LIFECYCLE_TARGET_SESSION_INVALID")
                elif target.get("decision", {}).get("candidate_ref") is not None and record["decision"].get("candidate_ref") != target["decision"].get("candidate_ref"):
                    reasons.append("LIFECYCLE_TARGET_RELATION_INVALID")
                elif detail["kind"] == "decision_confirmed" and (
                    target.get("event", {}).get("kind") != "decision_candidate"
                    or target.get("decision", {}).get("status") != "LLM_CANDIDATE"
                    or target.get("decision", {}).get("candidate_ref") is None
                ):
                    reasons.append("LIFECYCLE_TARGET_RELATION_INVALID")

        decision = record["decision"]
        candidate_ref = decision.get("candidate_ref")
        if candidate_ref is not None:
            candidate_status = decision["status"]
            previous_status = candidate_states.get(candidate_ref)
            if candidate_status == "LLM_CANDIDATE":
                if previous_status not in (None, "CANDIDATE"):
                    reasons.append("CANDIDATE_LIFECYCLE_REGRESSION")
                candidate_states.setdefault(candidate_ref, "CANDIDATE")
            elif candidate_status in {"HUMAN_CONFIRMED", "HUMAN_CORRECTED", "HUMAN_WITHDRAWN"}:
                allowed = {
                    "CANDIDATE": {"HUMAN_CONFIRMED", "HUMAN_CORRECTED", "HUMAN_WITHDRAWN"},
                    "HUMAN_CONFIRMED": {"HUMAN_CORRECTED", "HUMAN_WITHDRAWN"},
                    "HUMAN_CORRECTED": {"HUMAN_CORRECTED", "HUMAN_WITHDRAWN"},
                    "HUMAN_WITHDRAWN": set(),
                }
                if candidate_status not in allowed.get(previous_status, set()):
                    reasons.append("CANDIDATE_LIFECYCLE_REGRESSION")
                else:
                    candidate_states[candidate_ref] = candidate_status
        if decision["status"] in {"HUMAN_CONFIRMED", "HUMAN_CORRECTED", "HUMAN_WITHDRAWN"}:
            if decision["human_evidence_ref"] is None or decision["human_decision_ref"] is None:
                reasons.append("CONFIRMED_DECISION_NEEDS_HUMAN_EVIDENCE")
            human_actor_ref = decision.get("human_actor_ref")
            if human_actor_ref is None:
                reasons.append("HUMAN_DECISION_PERSON_REF_MISSING")
            actor_kind = _actor_kind(record["source"].get("actor_ref"))
            if actor_kind not in {"actor", "speaker"} or record["source"]["authority"].get("role") not in {"HUMAN", "OWNER"}:
                reasons.append("HUMAN_CONFIRMATION_REQUIRES_PERSON")
            if isinstance(human_actor_ref, str):
                person_id = human_actor_ref.rsplit("/", 1)[-1]
                actor_id = record["source"]["actor_ref"].rsplit("/", 1)[-1]
                authority_id = record["source"]["authority"]["authority_ref"].rsplit("/", 1)[-1]
                if person_id != actor_id or person_id != authority_id:
                    reasons.append("HUMAN_DECISION_PERSON_BINDING_INVALID")
        elif decision.get("human_actor_ref") is not None:
            reasons.append("HUMAN_ACTOR_REF_NOT_APPLICABLE")
        if decision["status"] == "LLM_CANDIDATE":
            if decision["candidate_ref"] is None or decision["human_evidence_ref"] is not None or decision["human_decision_ref"] is not None:
                reasons.append("LLM_RESULT_NOT_CANDIDATE")
        if detail["kind"] == "decision_confirmed" and decision["status"] not in {"HUMAN_CONFIRMED", "HUMAN_CORRECTED"}:
            reasons.append("CONFIRMED_EVENT_STATE_INVALID")
        if detail["kind"] == "correction" and decision["status"] != "HUMAN_CORRECTED":
            reasons.append("CORRECTION_STATE_INVALID")
        if detail["kind"] == "withdrawal" and decision["status"] != "HUMAN_WITHDRAWN":
            reasons.append("WITHDRAWAL_STATE_INVALID")
        if detail["kind"] == "confirmation" and decision["status"] not in {"HUMAN_CONFIRMED", "HUMAN_CORRECTED"}:
            reasons.append("CONFIRMATION_STATE_INVALID")

        if detail["kind"] == "pre_compact" and (detail["state"] != "PROJECTION_ONLY" or record["source"]["type"] != "system"):
            reasons.append("COMPACTION_NOT_SOURCE")
        if detail["kind"] == "pre_compact" and decision["status"] in {"HUMAN_CONFIRMED", "HUMAN_CORRECTED"}:
            reasons.append("COMPACTION_NOT_SOURCE")

        invalidation_kind = detail["invalidation_kind"]
        if detail["kind"] in {"source_update", "source_delete", "acl_loss", "invalidation"}:
            if invalidation_kind is None or not detail["invalidation_refs"]:
                reasons.append("INVALIDATION_EVENT_INCOMPLETE")
        if record["public_safety"]["acl_state"] in {"LOST", "REVOKED"} and detail["kind"] not in {"acl_loss", "invalidation"}:
            reasons.append("ACL_LOSS_NOT_INVALIDATED")
        if detail["kind"] == "acl_loss" and invalidation_kind != "ACL_LOST":
            reasons.append("INVALIDATION_EVENT_INCOMPLETE")
        if detail["kind"] == "source_delete" and invalidation_kind != "SOURCE_DELETED":
            reasons.append("INVALIDATION_EVENT_INCOMPLETE")
        if detail["kind"] == "source_delete" and record["retention"]["deletion_readback"] != "CONFIRMED":
            reasons.append("SOURCE_DELETE_READBACK_REQUIRED")

    if records and isinstance(records[0], dict) and records[0].get("previous_event_hash") != GENESIS_HASH:
        reasons.append("HASH_CHAIN_BROKEN")
    return list(dict.fromkeys(reasons))


def validate_ledger(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a machine-readable local validation result without external I/O."""
    if not isinstance(records, list) or not records:
        return {"result": "REFUSED", "reason_codes": ["INPUT_INVALID"], "record_count": 0}
    reasons = _semantic_reasons(records)
    markers = sorted({marker for record in records if (marker := _integrity_marker(record)) not in (None, "NONE")})
    result: dict[str, Any] = {
        "result": "LEDGER_VALID" if not reasons else "REFUSED",
        "reason_codes": reasons,
        "record_count": len(records),
        "integrity_markers": markers,
        "replay_detected": "DUPLICATE_IDEMPOTENCY_KEY" in reasons,
        "human_identity_authentication": "UNVERIFIED_PUBLIC_CLAIM",
        "promotion_eligible": False,
    }
    if records and isinstance(records[-1], dict):
        sequence = records[-1].get("sequence")
        result["head"] = {
            "sequence": _integer_value(sequence) if _is_integer_number(sequence) else sequence,
            "event_hash": records[-1].get("event_hash"),
        }
    return result


def append_event(records: list[dict[str, Any]], event: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """Append one sealed event, returning ``IDEMPOTENT_REPLAY`` for an exact retry."""
    existing_report = validate_ledger(records)
    if existing_report["result"] != "LEDGER_VALID":
        raise LedgerValidationError(existing_report["reason_codes"])
    event_id = event.get("event_id") if isinstance(event, dict) else None
    idem = event.get("causation", {}).get("idempotency_key_ref") if isinstance(event, dict) else None
    for old in records:
        if old.get("event_id") == event_id or old.get("causation", {}).get("idempotency_key_ref") == idem:
            old_identity = {key: value for key, value in old.items() if key not in {"sequence", "previous_event_hash", "event_hash"}}
            new_identity = {key: value for key, value in event.items() if key not in {"sequence", "previous_event_hash", "event_hash"}}
            if old_identity == new_identity:
                return copy.deepcopy(records), "IDEMPOTENT_REPLAY"
            raise LedgerValidationError(["DUPLICATE_EVENT_ID"] if old.get("event_id") == event_id else ["DUPLICATE_IDEMPOTENCY_KEY"])
    candidate = seal_event(event, sequence=_integer_value(records[-1]["sequence"]) + 1, previous_hash=records[-1]["event_hash"])
    result = copy.deepcopy(records) + [candidate]
    report = validate_ledger(result)
    if report["result"] != "LEDGER_VALID":
        raise LedgerValidationError(report["reason_codes"])
    return result, "APPENDED"


def _projection_exceeds_bounds(projection: dict[str, Any]) -> bool:
    for field, limit in PROJECTION_ARRAY_LIMITS.items():
        value = projection.get(field)
        if isinstance(value, list) and len(value) > limit:
            return True
    for field in ("confirmed_intent", "decisions"):
        value = projection.get(field)
        if isinstance(value, list) and any(
            isinstance(item, dict) and isinstance(item.get("source_event_refs"), list) and len(item["source_event_refs"]) > 4096
            for item in value
        ):
            return True
    integrity = projection.get("integrity")
    if isinstance(integrity, dict) and isinstance(integrity.get("invalidation_refs"), list) and len(integrity["invalidation_refs"]) > 4096:
        return True
    return False


def project_session(records: list[dict[str, Any]], session_ref: str) -> dict[str, Any]:
    """Rebuild one Session projection from direct and later-binding events."""
    report = validate_ledger(records)
    if report["result"] != "LEDGER_VALID":
        raise LedgerValidationError(report["reason_codes"])
    by_id = {record["event_id"]: record for record in records}
    selected: dict[str, dict[str, Any]] = {
        record["event_id"]: record
        for record in records
        if record["session"]["state"] == "BOUND" and record["session"]["session_ref"] == session_ref
    }
    for record in records:
        binding = record["event"]["binding"]
        if record["event"]["kind"] == "session_binding" and binding["destination_session_ref"] == session_ref:
            selected[record["event_id"]] = record
            for target_ref in binding["target_event_refs"]:
                if target_ref in by_id:
                    selected[target_ref] = by_id[target_ref]
    if not selected:
        raise LedgerValidationError(["SESSION_NOT_FOUND"])
    ordered = sorted(selected.values(), key=lambda record: record["sequence"])
    event_refs = [record["event_id"] for record in ordered]
    evidence_refs = list(dict.fromkeys(record["source"]["evidence_ref"] for record in ordered))
    timeline = [
        {
            "event_ref": record["event_id"],
            "source_type": record["source"]["type"],
            "occurred_at": record["source"]["occurred_at"],
            "actor_ref": record["source"]["actor_ref"],
            "authority_role": record["source"]["authority"]["role"],
            "event_kind": record["event"]["kind"],
            "state": record["event"]["state"],
            "summary_ref": record["event"]["summary_ref"],
            "evidence_refs": [record["source"]["evidence_ref"]],
        }
        for record in ordered
    ]
    intent_by_candidate: dict[str, dict[str, Any]] = {}
    decisions: list[dict[str, Any]] = []
    corrections: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    deviations: list[dict[str, Any]] = []
    omissions: list[str] = []
    invalidation_refs: list[str] = []
    next_action = {"kind": "NONE", "source_event_ref": None, "action_ref": None}
    for record in ordered:
        decision = record["decision"]
        if decision["status"] == "LLM_CANDIDATE" and decision["candidate_ref"]:
            item = intent_by_candidate.setdefault(decision["candidate_ref"], {
                "candidate_ref": decision["candidate_ref"], "source_event_refs": [],
                "confirmation_event_ref": None, "human_evidence_ref": None, "status": "CANDIDATE_ONLY",
            })
            item["source_event_refs"] = list(dict.fromkeys(item["source_event_refs"] + [record["event_id"]]))
        elif decision["status"] in {"HUMAN_CONFIRMED", "HUMAN_CORRECTED", "HUMAN_WITHDRAWN"} and decision["candidate_ref"]:
            intent_status = {
                "HUMAN_CONFIRMED": "HUMAN_CONFIRMED",
                "HUMAN_CORRECTED": "HUMAN_CORRECTED",
                "HUMAN_WITHDRAWN": "WITHDRAWN",
            }[decision["status"]]
            item = intent_by_candidate.setdefault(decision["candidate_ref"], {
                "candidate_ref": decision["candidate_ref"], "source_event_refs": [],
                "confirmation_event_ref": None, "human_evidence_ref": None, "status": intent_status,
            })
            item["source_event_refs"] = list(dict.fromkeys(item["source_event_refs"] + [record["event_id"]]))
            item["confirmation_event_ref"] = record["event_id"]
            item["human_evidence_ref"] = decision["human_evidence_ref"]
            item["status"] = intent_status
            decisions.append({
                "decision_ref": decision["human_decision_ref"], "source_event_refs": [record["event_id"]],
                "status": decision["status"], "human_evidence_ref": decision["human_evidence_ref"],
            })
        if record["event"]["kind"] == "correction" and record["event"]["correction_of_event_ref"]:
            corrections.append({
                "event_ref": record["event_id"], "corrects_event_ref": record["event"]["correction_of_event_ref"],
                "evidence_ref": record["source"]["evidence_ref"],
            })
        if record["event"]["kind"] in {"tool_action", "agent_action"} and record["ownership"]["assignee_ref"]:
            actions.append({
                "action_ref": record["event"]["summary_ref"], "owner_ref": record["ownership"]["assignee_ref"],
                "source_event_ref": record["event_id"], "status": "OPEN",
            })
        deviation = record["policy_deviation"]
        if deviation["status"] != "NONE":
            deviations.append({
                "event_ref": record["event_id"], "rule_ref": deviation["rule_ref"], "reason_ref": deviation["reason_ref"],
                "approver_ref": deviation["approver_ref"], "expires_at": deviation["expires_at"],
                "remediation_ref": deviation["remediation_ref"], "status": deviation["status"],
            })
        omissions.extend(record["context"]["omission_refs"])
        if record["event"]["invalidation_refs"]:
            invalidation_refs.extend(record["event"]["invalidation_refs"])
            next_action = {"kind": "REVIEW_INVALIDATION", "source_event_ref": record["event_id"], "action_ref": None}
    intents = list(intent_by_candidate.values())
    if any(item["status"] == "CANDIDATE_ONLY" for item in intents) and next_action["kind"] == "NONE":
        candidate = next(item for item in intents if item["status"] == "CANDIDATE_ONLY")
        next_action = {"kind": "REQUEST_HUMAN_CONFIRMATION", "source_event_ref": candidate["source_event_refs"][0], "action_ref": None}
    invalidation_refs = list(dict.fromkeys(invalidation_refs))
    omissions = list(dict.fromkeys(omissions))
    markers = report.get("integrity_markers", [])
    projection_arrays = {
        "source_event_refs": event_refs,
        "source_timeline": timeline,
        "confirmed_intent": intents,
        "decisions": decisions,
        "corrections": corrections,
        "action_items": actions,
        "evidence_refs": evidence_refs,
        "policy_deviations": deviations,
        "unresolved_questions": omissions,
        "omissions": omissions,
        "invalidation_refs": invalidation_refs,
    }
    if _projection_exceeds_bounds(projection_arrays):
        raise LedgerValidationError(["PROJECTION_LIMIT_EXCEEDED"])
    status = "INVALIDATED" if invalidation_refs else ("INCOMPLETE" if set(markers) & {"GAP", "CORRUPT"} else "REBUILDABLE")
    latest = ordered[-1] if ordered else records[-1]
    acl_states = [record["public_safety"]["acl_state"] for record in ordered]
    acl_fail_closed = any(
        state in {"UNKNOWN", "LOST", "REVOKED"} for state in acl_states
    ) or any(
        record["event"]["invalidation_kind"] == "ACL_LOST" or record["event"]["kind"] == "acl_loss"
        for record in ordered
    )
    acl_state = next((state for state in ("REVOKED", "LOST", "UNKNOWN") if state in acl_states), latest["public_safety"]["acl_state"])
    latest_sequence = _integer_value(records[-1]["sequence"])
    projection = {
        "kind": PROJECTION_KIND,
        "schema_revision": "v1",
        "projection_id": _projection_ref(session_ref, latest_sequence),
        "session_ref": session_ref,
        "projection_revision_ref": f"ref/projection-revision/{latest_sequence}",
        "projection_digest": "0" * 64,
        "generated_at": latest["source"]["ingested_at"],
        "status": status,
        "source_ledger_head": {"sequence": latest_sequence, "event_hash": records[-1]["event_hash"]},
        "session_governance": {
            **latest["session"]["governance"],
            "authority_status": "INVALIDATED" if invalidation_refs else "BOUND_UNVERIFIED",
        },
        "knowledge_representation": {
            "format": "GOOGLE_CLOUD_OKF_V0_2",
            "document_ref": _projection_ref(session_ref, latest_sequence) + "-knowledge",
            "profile_requirements_ref": "ref/okf-profile-requirements/v0-2-candidate",
            "contract_status": "CANDIDATE_UNVERIFIED",
            "derivation": "GENERATED_PROJECTION",
            "source_authority": False,
            "raw_archive_authority": False,
            "acl_authority": False,
            "audit_authority": False,
        },
        "source_event_refs": event_refs,
        "source_timeline": timeline,
        "confirmed_intent": intents,
        "decisions": decisions,
        "corrections": corrections,
        "action_items": actions,
        "evidence_refs": evidence_refs,
        "policy_deviations": deviations,
        "unresolved_questions": omissions,
        "omissions": omissions,
        "next_safe_action": next_action,
        "knowledge_scope": {
            "scope_ref": latest["public_safety"]["knowledge_scope_ref"],
            "acl_state": acl_state,
            "projection_access": "FAIL_CLOSED" if acl_fail_closed else "ALLOWED_UNVERIFIED",
        },
        "integrity": {
            "ledger_valid": True,
            "complete_sequence": not bool(set(markers) & {"GAP", "CORRUPT"}),
            "replay_detected": False,
            "integrity_markers": markers,
            "invalidation_refs": invalidation_refs,
        },
        "authority": {
            "projection_is_source_authority": False,
            "compaction_summary_is_source": False,
            "human_decision_requires_evidence": True,
            "human_identity_authentication": "UNVERIFIED_PUBLIC_CLAIM",
            "promotion_eligible": False,
            "current_truth_changed": False,
        },
        "public_beta": "NO_GO_UNPUBLISHED",
    }
    projection["projection_digest"] = canonical_projection_digest(projection)
    return projection


def _projection_ref(session_ref: str, sequence: int) -> str:
    safe = session_ref.removeprefix("ref/").replace("/", "-")
    return f"ref/projection/{safe}-{_integer_value(sequence)}"


def validate_projection(projection: dict[str, Any], records: list[dict[str, Any]], session_ref: str) -> dict[str, Any]:
    """Verify a saved projection against a fresh local rebuild and ledger head."""
    if not isinstance(projection, dict):
        raise LedgerValidationError(["PROJECTION_SCHEMA_INVALID"])
    if _projection_exceeds_bounds(projection):
        raise LedgerValidationError(["PROJECTION_LIMIT_EXCEEDED"])
    expected = project_session(records, session_ref)
    if projection.get("projection_digest") != canonical_projection_digest(projection):
        raise LedgerValidationError(["PROJECTION_DIGEST_MISMATCH"])
    if projection.get("projection_digest") != expected.get("projection_digest"):
        raise LedgerValidationError(["PROJECTION_DIGEST_MISMATCH"])
    if projection.get("source_ledger_head") != expected.get("source_ledger_head"):
        raise LedgerValidationError(["PROJECTION_LEDGER_HEAD_MISMATCH"])
    return {"result": "PROJECTION_VALID", "projection_digest": projection["projection_digest"], "source_event_count": len(projection.get("source_event_refs", []))}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    raw = path.read_bytes()
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("input too large")
    text = raw.decode("utf-8")
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            raise ValueError("blank line")
        record = json.loads(line, object_pairs_hook=_reject_duplicate_keys)
        if not isinstance(record, dict):
            raise ValueError("event is not an object")
        records.append(record)
    if not records:
        raise ValueError("empty ledger")
    return records


def _cli(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in {"validate", "project"}:
        print(json.dumps({"result": "REFUSED", "reason_codes": ["USAGE"]}, separators=(",", ":")))
        return 2
    expected_arity = 3 if argv[1] == "validate" else 4
    if len(argv) != expected_arity:
        print(json.dumps({"result": "REFUSED", "reason_codes": ["USAGE"]}, separators=(",", ":")))
        return 2
    try:
        records = read_jsonl(Path(argv[2]))
    except (OSError, UnicodeError, ValueError, RecursionError, json.JSONDecodeError, DuplicateKeyError):
        print(json.dumps({"result": "REFUSED", "reason_codes": ["INPUT_INVALID"]}, separators=(",", ":")))
        return 2
    if argv[1] == "validate":
        result = validate_ledger(records)
    else:
        try:
            result = project_session(records, argv[3])
        except LedgerValidationError as error:
            result = {"result": "REFUSED", "reason_codes": error.reason_codes}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    success = result.get("result") == "LEDGER_VALID" or result.get("status") in {"REBUILDABLE", "INVALIDATED", "INCOMPLETE"}
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv))
