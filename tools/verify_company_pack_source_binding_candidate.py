#!/usr/bin/env python3
"""Create a non-reflective, read-only Source binding verification candidate."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from safe_json_output import emit_json


sys.dont_write_bytecode = True

MAX_RECORD_BYTES = 1024 * 1024
MAX_EVIDENCE_BYTES = 1024 * 1024
MAX_CONTENT_BYTES = 16 * 1024 * 1024
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 20_000
USES = ("capture", "read", "analyze", "store", "transfer", "reuse")
ELIGIBLE_STATES = {
    "CONTENT_BINDING_RECORDED_UNVERIFIED",
    "DERIVED_CONTENT_BINDING_RECORDED_UNVERIFIED",
}
KNOWN_STATES = ELIGIBLE_STATES | {
    "REFERENCE_DECLARED_UNVERIFIED",
    "WITHDRAWAL_RECORDED_UNVERIFIED",
}
REF = re.compile(r"^ref/[a-z0-9][a-z0-9_-]*(?:/[a-z0-9][a-z0-9_-]*)*$")
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
MEDIA_TYPE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,62}/"
    r"[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,62}$"
)

RECORD_FIELDS = {
    "kind",
    "version",
    "status",
    "source_state",
    "source_record_id",
    "record_revision",
    "source_item_kind",
    "source_locator_ref",
    "source_revision",
    "source_observed_at",
    "acquisition_mode",
    "content_observation",
    "acquisition_provenance",
    "lineage",
    "attribution_candidate",
    "access_or_consent",
    "retention",
    "redaction",
    "r30_binding_handoff",
    "content_handling",
    "recorded_at",
    "expires_at",
    "review_trigger",
    "claims",
    "public_beta",
}
R31_REVIEW_TRIGGERS = (
    "source_locator_kind_or_revision_change",
    "content_digest_size_or_observation_change",
    "media_type_or_encoding_change",
    "acquisition_mode_or_provenance_change",
    "lineage_kind_parent_or_segmentation_change",
    "attribution_candidate_or_evidence_change",
    "access_consent_use_scope_or_revocation_change",
    "retention_scope_deadline_or_deletion_change",
    "redaction_policy_scope_or_status_change",
    "record_revision_r30_binding_or_replay_conflict",
    "private_storage_parser_or_retrieval_policy_change",
    "candidate_or_authority_expiry",
)
R31_REQUIRED_FALSE_CLAIMS = {
    "source_locator_resolved",
    "source_item_kind_verified",
    "source_revision_verified",
    "source_record_schema_verified",
    "source_record_bytes_current_verified",
    "source_record_external_binding_verified",
    "source_content_bytes_current_verified",
    "source_authenticity_verified",
    "source_completeness_verified",
    "source_lineage_verified",
    "source_media_type_verified",
    "source_encoding_verified",
    "acquisition_actor_verified",
    "acquisition_tool_verified",
    "acquisition_runtime_verified",
    "acquisition_receipt_verified",
    "acquisition_provenance_verified",
    "subject_identity_verified",
    "subject_attribution_verified",
    "speaker_identity_verified",
    "channel_session_attribution_verified",
    "attribution_entry_identity_verified",
    "attribution_entry_authority_verified",
    "attribution_entry_authenticity_verified",
    "access_or_consent_verified",
    "capture_authorized",
    "read_authorized",
    "analyze_authorized",
    "storage_authorized",
    "transfer_authorized",
    "reuse_authorized",
    "revocation_verified",
    "retention_scope_verified",
    "retention_enforced",
    "deletion_verified",
    "withdrawal_recorded_verified",
    "prompt_injection_cleared",
    "sensitive_content_reviewed",
    "redaction_verified",
    "record_id_uniqueness_verified",
    "replay_prevented",
    "human_identity_verified",
    "human_authority_verified",
    "human_confirmation_authenticity_verified",
    "human_intent_confirmed",
    "candidate_bound_human_decision_verified",
    "execution_authority_granted",
    "work_order_authority_granted",
    "promotion_verified",
    "current_truth_changed",
    "runtime_ready",
    "voice_runtime_verified",
    "discord_runtime_verified",
    "provider_transfer_authorized",
    "external_transfer_authorized",
    "final_human_go",
    "public_beta_go",
}
CONTENT_FIELDS = {
    "storage_locator_ref",
    "content_binding",
    "declared_media_type",
    "declared_encoding_ref",
    "declared_source_revision",
    "observed_at",
    "observation_status",
}
PROVENANCE_FIELDS = {
    "actor_ref",
    "tool_ref",
    "tool_version_ref",
    "config_ref",
    "runtime_ref",
    "execution_receipt_ref",
    "input_locator_ref",
    "output_binding",
    "started_at",
    "completed_at",
    "verification_status",
}
LINEAGE_FIELDS = {
    "lineage_kind",
    "parent_source_record_refs",
    "transformation_refs",
    "segmentation_ref",
    "verification_status",
}
ACCESS_FIELDS = {
    "basis_ref",
    "basis_binding",
    "use_declarations",
    "verification_status",
}
USE_DECLARATION_FIELDS = {
    "declaration_status",
    "evidence_ref",
    "evidence_binding",
    "purpose_scope_ref",
    "subject_scope_ref",
    "scope_expires_at",
    "revocation_evidence_ref",
    "verification_status",
}
RETENTION_FIELDS = {
    "policy_ref",
    "policy_binding",
    "covered_artifacts",
    "retain_until",
    "deletion_trigger",
    "deletion_receipt_ref",
    "enforcement_status",
}
REDACTION_FIELDS = {
    "policy_ref",
    "policy_binding",
    "covered_artifacts",
    "verification_status",
}
HANDOFF_FIELDS = {
    "target_contract",
    "serialized_record_locator",
    "serialized_record_binding",
    "binding_status",
    "mapping_status",
}
HANDLING_FIELDS = {
    "source_content_embedded",
    "candidate_visibility",
    "prompt_treatment",
    "disclosure_review_status",
}
EVIDENCE_FIELDS = {
    "kind",
    "version",
    "status",
    "source_record_id_sha256",
    "source_record_binding",
    "source_content_binding",
    "common_purpose_scope_ref",
    "declared_permitted_uses",
    "subject_scope_ref",
    "scope_expires_at",
    "revocation_evidence_ref",
    "basis_ref",
    "basis_binding",
    "use_evidence_bindings",
    "recorded_at",
    "expires_at",
    "claims",
    "public_beta",
}
EVIDENCE_CLAIMS = {
    "access_or_consent_verified",
    "evidence_authenticity_verified",
    "human_authority_verified",
    "retention_enforced",
    "source_authenticity_verified",
}
CHECKS = (
    "input_read_set",
    "strict_parsing",
    "record_projection_contract",
    "source_content_binding",
    "access_projection_evidence",
    "r30_projection",
    "terminal_reread",
)
NARROW_CLAIMS = {
    "access_projection_evidence_contract_matched",
    "r30_projection_digest_computed",
    "record_projection_contract_matched",
    "source_content_binding_matched",
    "source_record_file_binding_matched",
    "stable_read_set_reread_matched",
    "strict_input_parsing_matched",
}
ALWAYS_FALSE_CLAIMS = {
    "access_evidence_locator_resolution_verified",
    "access_or_consent_verified",
    "atomic_multi_file_snapshot_verified",
    "current_truth_changed",
    "deletion_enforced",
    "discord_runtime_verified",
    "external_transfer_authorized",
    "final_human_go",
    "full_r31_schema_verified",
    "human_decision_verified",
    "human_intent_confirmed",
    "identity_or_attribution_verified",
    "promotion_verified",
    "provider_transfer_authorized",
    "public_beta_go",
    "redaction_verified",
    "replay_prevented",
    "retention_enforced",
    "source_authenticity_verified",
    "source_completeness_verified",
    "source_lineage_verified",
    "source_record_locator_resolution_verified",
    "trusted_time_verified",
    "voice_runtime_verified",
    "work_order_authority_granted",
}


class StrictInputError(ValueError):
    """Internal closed failure; its text is never returned."""


class ProjectionIneligible(StrictInputError):
    """The supplied R31 state cannot be losslessly projected."""


@dataclass(frozen=True)
class FileSnapshot:
    content: bytes
    identity: tuple[int, int, int, int]


def fail() -> None:
    raise StrictInputError("closed")


def binding(content: bytes) -> dict[str, object]:
    return {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}


def exact_object(value: object, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        fail()
    return value


def require_string(value: object, pattern: re.Pattern[str], maximum: int = 512) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        fail()
    if pattern.fullmatch(value) is None:
        fail()
    return value


def require_choice(value: object, choices: set[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        fail()
    return value


def require_ref(value: object) -> str:
    return require_string(value, REF)


def require_nullable_ref(value: object) -> str | None:
    return None if value is None else require_ref(value)


def parse_timestamp(value: object) -> datetime:
    text = require_string(value, TIMESTAMP, 64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        fail()
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        fail()
    return parsed


def require_binding(value: object, maximum: int = MAX_CONTENT_BYTES) -> dict[str, object]:
    item = exact_object(value, {"sha256", "bytes"})
    require_string(item["sha256"], SHA256, 64)
    if type(item["bytes"]) is not int or not 1 <= item["bytes"] <= maximum:
        fail()
    return item


def require_ref_list(value: object, maximum: int = 64) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        fail()
    result = [require_ref(item) for item in value]
    if len(result) != len(set(result)):
        fail()
    return result


def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail()
        result[key] = value
    return result


def reject_non_finite(_value: str) -> None:
    fail()


def check_json_limits(root: object) -> None:
    nodes = 0
    stack: list[tuple[object, int]] = [(root, 1)]
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            fail()
        if isinstance(value, str):
            if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
                fail()
        elif isinstance(value, dict):
            stack.extend((key, depth + 1) for key in value)
            stack.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            stack.extend((item, depth + 1) for item in value)
        elif type(value) is float and not math.isfinite(value):
            fail()


def load_strict_json(content: bytes) -> dict[str, Any]:
    if not content or content.startswith(b"\xef\xbb\xbf"):
        fail()
    try:
        text = content.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=reject_duplicate_pairs,
            parse_constant=reject_non_finite,
        )
    except (UnicodeError, ValueError, RecursionError):
        fail()
    if not isinstance(value, dict):
        fail()
    check_json_limits(value)
    return value


def is_reparse(component: Path, component_stat: os.stat_result) -> bool:
    attributes = getattr(component_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if attributes & reparse_flag:
        return True
    try:
        return hasattr(component, "is_junction") and component.is_junction()
    except OSError:
        return True


def stable_read(path: Path, maximum: int) -> FileSnapshot:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    descriptor: int | None = None
    try:
        for component_name in absolute.parts[1:]:
            current /= component_name
            component_stat = os.stat(current, follow_symlinks=False)
            if stat.S_ISLNK(component_stat.st_mode) or is_reparse(current, component_stat):
                fail()
        before = os.stat(absolute, follow_symlinks=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size <= 0
            or before.st_size > maximum
        ):
            fail()
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(absolute, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            before.st_dev,
            before.st_ino,
        ):
            fail()
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                fail()
        after_descriptor = os.fstat(descriptor)
        after_path = os.stat(absolute, follow_symlinks=False)
        stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
        if any(
            getattr(before, field) != getattr(after_descriptor, field)
            or getattr(before, field) != getattr(after_path, field)
            for field in stable_fields
        ):
            fail()
        content = b"".join(chunks)
        if not content or len(content) != before.st_size:
            fail()
        return FileSnapshot(
            content=content,
            identity=(before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns),
        )
    except (OSError, ValueError):
        fail()
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def read_set(paths: tuple[Path, Path, Path]) -> tuple[FileSnapshot, FileSnapshot, FileSnapshot]:
    return (
        stable_read(paths[0], MAX_RECORD_BYTES),
        stable_read(paths[1], MAX_CONTENT_BYTES),
        stable_read(paths[2], MAX_EVIDENCE_BYTES),
    )


def snapshots_equal(
    left: tuple[FileSnapshot, FileSnapshot, FileSnapshot],
    right: tuple[FileSnapshot, FileSnapshot, FileSnapshot],
) -> bool:
    return all(a == b for a, b in zip(left, right, strict=True))


def validate_record(record: dict[str, Any], content_bytes: bytes) -> dict[str, Any]:
    exact_object(record, RECORD_FIELDS)
    if (
        record["kind"] != "company_pack_source_record_instance"
        or record["version"] != "1.0"
        or record["status"] != "CANDIDATE_ONLY"
        or record["public_beta"] != "NO_GO_UNPUBLISHED"
    ):
        fail()
    require_string(record["source_record_id"], IDENTIFIER, 63)
    for field in ("record_revision", "source_locator_ref", "source_revision"):
        require_ref(record[field])
    source_observed_at = parse_timestamp(record["source_observed_at"])
    recorded_at = parse_timestamp(record["recorded_at"])
    if parse_timestamp(record["expires_at"]) <= recorded_at:
        fail()
    require_choice(record["source_state"], KNOWN_STATES)
    if record["source_state"] not in ELIGIBLE_STATES:
        raise ProjectionIneligible("closed")
    derived_state = record["source_state"] == "DERIVED_CONTENT_BINDING_RECORDED_UNVERIFIED"
    allowed_modes = {"derived"} if derived_state else {"capture", "import", "synthetic"}
    require_choice(record["acquisition_mode"], allowed_modes)

    content = exact_object(record["content_observation"], CONTENT_FIELDS)
    require_ref(content["storage_locator_ref"])
    declared_binding = require_binding(content["content_binding"])
    if declared_binding != binding(content_bytes):
        fail()
    require_string(content["declared_media_type"], MEDIA_TYPE, 127)
    require_ref(content["declared_encoding_ref"])
    require_ref(content["declared_source_revision"])
    content_observed_at = parse_timestamp(content["observed_at"])
    if content["observation_status"] != "NOT_VERIFIED":
        fail()
    if record["source_revision"] != content["declared_source_revision"]:
        fail()

    provenance = exact_object(record["acquisition_provenance"], PROVENANCE_FIELDS)
    for field in (
        "actor_ref",
        "tool_ref",
        "tool_version_ref",
        "config_ref",
        "runtime_ref",
        "execution_receipt_ref",
        "input_locator_ref",
    ):
        require_ref(provenance[field])
    if require_binding(provenance["output_binding"]) != declared_binding:
        fail()
    started_at = parse_timestamp(provenance["started_at"])
    completed_at = parse_timestamp(provenance["completed_at"])
    if not started_at <= completed_at <= content_observed_at <= recorded_at:
        fail()
    if source_observed_at > recorded_at:
        fail()
    if provenance["verification_status"] != "NOT_VERIFIED":
        fail()

    lineage = exact_object(record["lineage"], LINEAGE_FIELDS)
    parents = require_ref_list(lineage["parent_source_record_refs"], 16)
    transformations = require_ref_list(lineage["transformation_refs"], 16)
    segmentation = require_nullable_ref(lineage["segmentation_ref"])
    if lineage["verification_status"] != "NOT_VERIFIED":
        fail()
    if not derived_state:
        if (
            lineage["lineage_kind"] != "DECLARED_ORIGINAL"
            or parents
            or transformations
            or segmentation is not None
        ):
            fail()
    elif (
        lineage["lineage_kind"] != "DECLARED_DERIVED"
        or not parents
        or not transformations
    ):
        fail()

    access = exact_object(record["access_or_consent"], ACCESS_FIELDS)
    require_ref(access["basis_ref"])
    require_binding(access["basis_binding"])
    if access["verification_status"] != "NOT_VERIFIED":
        fail()
    declarations = exact_object(access["use_declarations"], set(USES))
    permitted: list[tuple[str, dict[str, Any]]] = []
    for use in USES:
        declaration = exact_object(declarations[use], USE_DECLARATION_FIELDS)
        require_choice(
            declaration["declaration_status"],
            {
                "DECLARED_NOT_PERMITTED",
                "DECLARED_PERMITTED_UNVERIFIED",
                "WITHDRAWAL_ENTERED_UNVERIFIED",
            },
        )
        for field in ("evidence_ref", "purpose_scope_ref", "subject_scope_ref"):
            require_ref(declaration[field])
        require_binding(declaration["evidence_binding"])
        parse_timestamp(declaration["scope_expires_at"])
        require_nullable_ref(declaration["revocation_evidence_ref"])
        if declaration["verification_status"] != "NOT_VERIFIED":
            fail()
        if declaration["declaration_status"] == "WITHDRAWAL_ENTERED_UNVERIFIED":
            raise ProjectionIneligible("closed")
        if declaration["declaration_status"] == "DECLARED_PERMITTED_UNVERIFIED":
            permitted.append((use, declaration))
    if not permitted:
        raise ProjectionIneligible("closed")
    common_fields = (
        "purpose_scope_ref",
        "subject_scope_ref",
        "scope_expires_at",
        "revocation_evidence_ref",
    )
    if any(len({json.dumps(item[field], sort_keys=True) for _, item in permitted}) != 1 for field in common_fields):
        raise ProjectionIneligible("closed")

    retention = exact_object(record["retention"], RETENTION_FIELDS)
    require_ref(retention["policy_ref"])
    require_binding(retention["policy_binding"])
    covered = retention["covered_artifacts"]
    allowed_coverage = {
        "source_record_serialized_bytes",
        "source_content_bytes",
        "storage_metadata",
    }
    if (
        not isinstance(covered, list)
        or not 1 <= len(covered) <= 3
        or not all(isinstance(item, str) and item in allowed_coverage for item in covered)
    ):
        fail()
    if len(covered) != len(set(covered)) or not {
        "source_record_serialized_bytes",
        "source_content_bytes",
    }.issubset(covered):
        raise ProjectionIneligible("closed")
    parse_timestamp(retention["retain_until"])
    require_choice(
        retention["deletion_trigger"],
        {"expiry", "withdrawal", "expiry_or_withdrawal"},
    )
    require_nullable_ref(retention["deletion_receipt_ref"])
    if retention["enforcement_status"] != "NOT_VERIFIED":
        fail()

    redaction = exact_object(record["redaction"], REDACTION_FIELDS)
    require_ref(redaction["policy_ref"])
    require_binding(redaction["policy_binding"])
    if (
        not isinstance(redaction["covered_artifacts"], list)
        or not all(isinstance(item, str) for item in redaction["covered_artifacts"])
        or redaction["verification_status"] != "NOT_VERIFIED"
    ):
        fail()

    handoff = exact_object(record["r30_binding_handoff"], HANDOFF_FIELDS)
    if handoff != {
        "target_contract": "R30_SOURCE_RECORD_BINDING",
        "serialized_record_locator": None,
        "serialized_record_binding": None,
        "binding_status": "EXTERNAL_BINDING_REQUIRED",
        "mapping_status": "NOT_VERIFIED",
    }:
        fail()
    handling = exact_object(record["content_handling"], HANDLING_FIELDS)
    if handling != {
        "source_content_embedded": False,
        "candidate_visibility": "PRIVATE_GOVERNED_ONLY",
        "prompt_treatment": "UNTRUSTED_DATA_ONLY",
        "disclosure_review_status": "NOT_REVIEWED",
    }:
        fail()
    if record["review_trigger"] != list(R31_REVIEW_TRIGGERS):
        fail()
    claims = exact_object(record["claims"], R31_REQUIRED_FALSE_CLAIMS)
    if any(value is not False for value in claims.values()):
        fail()

    first = permitted[0][1]
    return {
        "content": content,
        "lineage": lineage,
        "access": access,
        "permitted": permitted,
        "common": {field: first[field] for field in common_fields},
        "retention": retention,
    }


def validate_access_evidence(
    evidence: dict[str, Any],
    record: dict[str, Any],
    record_view: dict[str, Any],
    record_bytes: bytes,
    content_bytes: bytes,
) -> None:
    exact_object(evidence, EVIDENCE_FIELDS)
    if (
        evidence["kind"] != "company_pack_source_access_projection_evidence"
        or evidence["version"] != "1.0"
        or evidence["status"] != "CANDIDATE_ONLY"
        or evidence["public_beta"] != "NO_GO_UNPUBLISHED"
    ):
        fail()
    expected_id_digest = hashlib.sha256(record["source_record_id"].encode("utf-8")).hexdigest()
    if evidence["source_record_id_sha256"] != expected_id_digest:
        fail()
    require_string(evidence["source_record_id_sha256"], SHA256, 64)
    if require_binding(evidence["source_record_binding"], MAX_RECORD_BYTES) != binding(record_bytes):
        fail()
    if require_binding(evidence["source_content_binding"]) != binding(content_bytes):
        fail()

    permitted = record_view["permitted"]
    uses = [name for name, _ in permitted]
    if evidence["declared_permitted_uses"] != uses:
        fail()
    common = record_view["common"]
    if (
        require_ref(evidence["common_purpose_scope_ref"]) != common["purpose_scope_ref"]
        or require_ref(evidence["subject_scope_ref"]) != common["subject_scope_ref"]
        or evidence["scope_expires_at"] != common["scope_expires_at"]
        or evidence["revocation_evidence_ref"] != common["revocation_evidence_ref"]
    ):
        fail()
    scope_expires_at = parse_timestamp(evidence["scope_expires_at"])
    require_nullable_ref(evidence["revocation_evidence_ref"])
    access = record_view["access"]
    if evidence["basis_ref"] != access["basis_ref"]:
        fail()
    require_ref(evidence["basis_ref"])
    if require_binding(evidence["basis_binding"]) != access["basis_binding"]:
        fail()

    use_bindings = exact_object(evidence["use_evidence_bindings"], set(uses))
    for use, declaration in permitted:
        item = exact_object(use_bindings[use], {"evidence_ref", "evidence_binding"})
        if require_ref(item["evidence_ref"]) != declaration["evidence_ref"]:
            fail()
        if require_binding(item["evidence_binding"]) != declaration["evidence_binding"]:
            fail()
    recorded_at = parse_timestamp(evidence["recorded_at"])
    expires_at = parse_timestamp(evidence["expires_at"])
    retain_until = parse_timestamp(record_view["retention"]["retain_until"])
    if (
        recorded_at < parse_timestamp(record["recorded_at"])
        or expires_at <= recorded_at
        or scope_expires_at <= recorded_at
        or retain_until <= recorded_at
        or evidence["expires_at"] != record["expires_at"]
    ):
        fail()
    claims = exact_object(evidence["claims"], EVIDENCE_CLAIMS)
    if any(value is not False for value in claims.values()):
        fail()


def canonical_projection(
    record: dict[str, Any],
    view: dict[str, Any],
    record_bytes: bytes,
    evidence_bytes: bytes,
    record_locator: str,
    evidence_locator: str,
) -> bytes:
    lineage = view["lineage"]
    parents = (
        []
        if lineage["lineage_kind"] == "DECLARED_ORIGINAL"
        else lineage["parent_source_record_refs"]
    )
    permitted = view["permitted"]
    common = view["common"]
    content = view["content"]
    retention = view["retention"]
    projection = {
        "source_record_locator": record_locator,
        "source_record_binding": binding(record_bytes),
        "source_content_locator": content["storage_locator_ref"],
        "source_content_binding": content["content_binding"],
        "declared_media_type": content["declared_media_type"],
        "source_revision": record["source_revision"],
        "observed_at": content["observed_at"],
        "source_record_schema_status": "NOT_VERIFIED",
        "derived_from_refs": parents,
        "lineage_status": "NOT_VERIFIED",
        "access_or_consent": {
            "evidence_ref": evidence_locator,
            "evidence_binding": binding(evidence_bytes),
            "declared_permitted_uses": [name for name, _ in permitted],
            "subject_scope_ref": common["subject_scope_ref"],
            "scope_expires_at": common["scope_expires_at"],
            "revocation_evidence_ref": common["revocation_evidence_ref"],
            "verification_status": "NOT_VERIFIED",
        },
        "retention": {
            field: retention[field]
            for field in (
                "policy_ref",
                "policy_binding",
                "retain_until",
                "deletion_trigger",
                "deletion_receipt_ref",
                "enforcement_status",
            )
        },
    }
    return json.dumps(
        projection,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def empty_report() -> dict[str, Any]:
    claims = {name: False for name in sorted(ALWAYS_FALSE_CLAIMS | NARROW_CLAIMS)}
    return {
        "kind": "company_pack_source_binding_verification_candidate",
        "version": "1.0",
        "status": "CANDIDATE_ONLY",
        "result": "REFUSED",
        "r31_input_status": "NOT_EVALUATED",
        "read_set_status": "NOT_EVALUATED",
        "r30_projection_eligibility": "NOT_EVALUATED",
        "reason_codes": [],
        "evaluated_inputs": {
            "source_record": None,
            "source_content": None,
            "access_projection_evidence": None,
        },
        "checks": {name: "NOT_EVALUATED" for name in CHECKS},
        "r30_projection_digest_candidate": None,
        "claims": claims,
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def clear_narrow_claims(report: dict[str, Any]) -> None:
    for name in NARROW_CLAIMS:
        report["claims"][name] = False


def evaluate(
    record_path: Path,
    content_path: Path,
    evidence_path: Path,
    record_locator: str,
    evidence_locator: str,
) -> dict[str, Any]:
    report = empty_report()
    paths = (record_path, content_path, evidence_path)
    try:
        require_ref(record_locator)
        require_ref(evidence_locator)
        if record_locator == evidence_locator:
            fail()
        normalized_paths = {
            os.path.normcase(os.path.abspath(path))
            for path in paths
        }
        if len(normalized_paths) != 3:
            fail()
        first = read_set(paths)
        if len({snapshot.identity[:2] for snapshot in first}) != 3:
            fail()
    except StrictInputError:
        report["reason_codes"] = ["INPUT_INVALID"]
        report["checks"]["input_read_set"] = "MISMATCH"
        return report
    report["checks"]["input_read_set"] = "MATCH"
    for key, snapshot in zip(
        ("source_record", "source_content", "access_projection_evidence"),
        first,
        strict=True,
    ):
        report["evaluated_inputs"][key] = binding(snapshot.content)

    try:
        record = load_strict_json(first[0].content)
    except StrictInputError:
        clear_narrow_claims(report)
        report["r31_input_status"] = "REJECTED"
        report["reason_codes"] = ["STRICT_JSON_INVALID"]
        report["checks"]["strict_parsing"] = "MISMATCH"
        return report
    report["r31_input_status"] = "STRICTLY_PARSED_UNVERIFIED"
    try:
        evidence = load_strict_json(first[2].content)
    except StrictInputError:
        clear_narrow_claims(report)
        report["reason_codes"] = ["STRICT_JSON_INVALID"]
        report["checks"]["strict_parsing"] = "MISMATCH"
        return report
    report["checks"]["strict_parsing"] = "MATCH"
    report["claims"]["strict_input_parsing_matched"] = True

    try:
        view = validate_record(record, first[1].content)
    except ProjectionIneligible:
        clear_narrow_claims(report)
        report["r31_input_status"] = "REJECTED"
        report["r30_projection_eligibility"] = "INELIGIBLE"
        report["reason_codes"] = ["R30_PROJECTION_INELIGIBLE"]
        report["checks"]["record_projection_contract"] = "MISMATCH"
        report["checks"]["r30_projection"] = "MISMATCH"
        return report
    except StrictInputError:
        clear_narrow_claims(report)
        report["r31_input_status"] = "REJECTED"
        report["reason_codes"] = ["RECORD_CONTRACT_MISMATCH"]
        report["checks"]["record_projection_contract"] = "MISMATCH"
        report["checks"]["source_content_binding"] = "MISMATCH"
        return report
    report["checks"]["record_projection_contract"] = "MATCH"
    report["checks"]["source_content_binding"] = "MATCH"
    report["claims"]["record_projection_contract_matched"] = True
    report["claims"]["source_content_binding_matched"] = True
    report["r31_input_status"] = "PARSED_PROJECTION_CONTRACT_MATCHED_UNVERIFIED"

    artifact_locators = {
        record_locator,
        evidence_locator,
        record["source_locator_ref"],
        view["content"]["storage_locator_ref"],
    }
    if len(artifact_locators) != 4:
        clear_narrow_claims(report)
        report["r30_projection_eligibility"] = "INELIGIBLE"
        report["reason_codes"] = ["R30_PROJECTION_INELIGIBLE"]
        report["checks"]["r30_projection"] = "MISMATCH"
        return report

    try:
        validate_access_evidence(
            evidence,
            record,
            view,
            first[0].content,
            first[1].content,
        )
    except StrictInputError:
        clear_narrow_claims(report)
        report["r30_projection_eligibility"] = "INELIGIBLE"
        report["reason_codes"] = ["ACCESS_EVIDENCE_CONTRACT_MISMATCH"]
        report["checks"]["access_projection_evidence"] = "MISMATCH"
        return report
    report["checks"]["access_projection_evidence"] = "MATCH"
    report["claims"]["access_projection_evidence_contract_matched"] = True
    report["claims"]["source_record_file_binding_matched"] = True

    try:
        projection = canonical_projection(
            record,
            view,
            first[0].content,
            first[2].content,
            record_locator,
            evidence_locator,
        )
    except (TypeError, ValueError, UnicodeError):
        clear_narrow_claims(report)
        report["r30_projection_eligibility"] = "INELIGIBLE"
        report["reason_codes"] = ["R30_PROJECTION_INELIGIBLE"]
        report["checks"]["r30_projection"] = "MISMATCH"
        return report
    report["r30_projection_digest_candidate"] = binding(projection)
    report["checks"]["r30_projection"] = "MATCH"
    report["claims"]["r30_projection_digest_computed"] = True
    report["r30_projection_eligibility"] = "ELIGIBLE_UNVERIFIED"

    try:
        second = read_set(paths)
        third = read_set(paths)
    except StrictInputError:
        clear_narrow_claims(report)
        report["read_set_status"] = "LATE_DRIFT_DETECTED"
        report["r30_projection_eligibility"] = "INELIGIBLE"
        report["reason_codes"] = ["SOURCE_DRIFT_DETECTED"]
        report["checks"]["terminal_reread"] = "MISMATCH"
        report["r30_projection_digest_candidate"] = None
        report["claims"]["r30_projection_digest_computed"] = False
        return report
    if not snapshots_equal(first, second) or not snapshots_equal(second, third):
        clear_narrow_claims(report)
        report["read_set_status"] = "LATE_DRIFT_DETECTED"
        report["r30_projection_eligibility"] = "INELIGIBLE"
        report["reason_codes"] = ["SOURCE_DRIFT_DETECTED"]
        report["checks"]["terminal_reread"] = "MISMATCH"
        report["r30_projection_digest_candidate"] = None
        report["claims"]["r30_projection_digest_computed"] = False
        return report
    report["checks"]["terminal_reread"] = "MATCH"
    report["claims"]["stable_read_set_reread_matched"] = True
    report["read_set_status"] = "STABLE_POSTCHECK_UNVERIFIED"
    report["result"] = "SOURCE_BINDING_MATCH_POINT_IN_TIME"
    return report


def main(argv: list[str]) -> int:
    if len(argv) != 6:
        print(
            "usage: verify_company_pack_source_binding_candidate.py "
            "SOURCE_RECORD_JSON SOURCE_CONTENT_FILE ACCESS_EVIDENCE_JSON "
            "SOURCE_RECORD_LOCATOR_REF ACCESS_EVIDENCE_LOCATOR_REF",
            file=sys.stderr,
        )
        return 2
    report = evaluate(
        Path(argv[1]),
        Path(argv[2]),
        Path(argv[3]),
        argv[4],
        argv[5],
    )
    if not emit_json(report, None):
        return 1
    return 0 if report["result"] == "SOURCE_BINDING_MATCH_POINT_IN_TIME" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
