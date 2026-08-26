from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "session-conversation-event-ledger.schema.json"
PROJECTION_SCHEMA = ROOT / "schemas" / "session-knowledge-projection.schema.json"
RUNBOOK = ROOT / "docs" / "SESSION-CONVERSATION-LEDGER.md"
VALIDATOR = ROOT / "tools" / "validate_session_conversation_ledger.py"


def _load_validator():
    spec = importlib.util.spec_from_file_location("session_ledger", VALIDATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("validator import spec unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ledger = _load_validator()


def _rechain(records: list[dict]) -> list[dict]:
    previous = ledger.GENESIS_HASH
    for record in records:
        record["previous_event_hash"] = previous
        record["event_hash"] = "0" * 64
        record["event_hash"] = ledger.canonical_event_hash(record)
        previous = record["event_hash"]
    return records


def _ref(kind: str, name: str) -> str:
    return f"ref/{kind}/{name}"


def _event(
    event_id: str,
    *,
    sequence: int = 1,
    previous_hash: str | None = None,
    event_kind: str = "human_message",
    occurred_at: str | None = None,
    ingested_at: str | None = None,
    session_state: str = "UNASSIGNED_INBOX",
    session_ref: str | None = None,
    revision: str | None = None,
    event_state: str = "OBSERVED",
    source_type: str = "discord_text",
    speaker_track_ref: str | None = None,
    actor_ref: str = "ref/speaker/alice",
    authority_role: str = "HUMAN",
    authority_ref: str = "ref/authority/alice",
    decision_status: str = "NONE",
    candidate_ref: str | None = None,
    human_evidence_ref: str | None = None,
    human_decision_ref: str | None = None,
    human_actor_ref: str | None = None,
    deviation_status: str = "NONE",
    deletion_state: str = "NOT_REQUESTED",
    deletion_receipt_ref: str | None = None,
    deletion_readback: str = "NOT_REQUESTED",
    acl_state: str = "AVAILABLE",
    extraction_kind: str = "NONE",
    caused_by_event_refs: list[str] | None = None,
    correction_of_event_ref: str | None = None,
    withdrawal_of_event_ref: str | None = None,
    confirmation_of_event_ref: str | None = None,
    artifact_stage: str = "RAW_SOURCE_JSON",
    derived_from_event_refs: list[str] | None = None,
    content_hash: str | None = None,
    binding_targets: list[str] | None = None,
    binding_destination: str | None = None,
    binding_revision: str | None = None,
    invalidation_kind: str | None = None,
    invalidation_refs: list[str] | None = None,
    integrity_marker: str = "NONE",
    ingest_mode: str = "ONLINE",
    compaction_state: str | None = None,
) -> dict:
    if previous_hash is None:
        previous_hash = ledger.GENESIS_HASH
    if session_state == "UNASSIGNED_INBOX":
        session_ref = None
        revision = None
    elif session_ref is None:
        session_ref = _ref("session", "demo")
    if revision is None and session_state == "BOUND":
        revision = _ref("session-revision", "1")
    binding_targets = binding_targets or []
    invalidation_refs = invalidation_refs or []
    caused_by_event_refs = caused_by_event_refs or []
    derived_from_event_refs = derived_from_event_refs or []
    if content_hash is None:
        content_hash = hashlib.sha256(event_id.encode("utf-8")).hexdigest()
    if event_kind == "session_binding" and not binding_targets:
        binding_targets = [_ref("event", "inbox-1")]
    if event_kind == "session_binding" and binding_destination is None:
        binding_destination = session_ref
    if event_kind == "session_binding" and binding_revision is None:
        binding_revision = revision
    if decision_status in {"HUMAN_CONFIRMED", "HUMAN_CORRECTED", "HUMAN_WITHDRAWN"} and human_actor_ref is None:
        human_actor_ref = _ref("person", "alice")
    if session_state == "UNASSIGNED_INBOX":
        governance = {
            "creation_mode": "UNASSIGNED_INBOX",
            "task_ssot_ref": None,
            "plan_ref": None,
            "requirement_refs": [],
            "invocation_ref": None,
            "model_ref": None,
            "capability_grant_refs": [],
            "knowledge_grant_refs": [],
            "mcp_tool_grant_refs": [],
            "delegation_ref": None,
            "dependency_refs": [],
            "parallel_status_ref": None,
            "evidence_refs": [],
            "invalidation_refs": [],
        }
    else:
        governance = {
            "creation_mode": "AUTO_CREATED",
            "task_ssot_ref": _ref("task", "demo"),
            "plan_ref": _ref("plan", "demo"),
            "requirement_refs": [_ref("requirement", "demo")],
            "invocation_ref": _ref("invocation", "demo"),
            "model_ref": _ref("model", "candidate-only"),
            "capability_grant_refs": [_ref("grant", "capability-demo")],
            "knowledge_grant_refs": [_ref("knowledge-grant", "demo")],
            "mcp_tool_grant_refs": [_ref("mcp-grant", "demo")],
            "delegation_ref": _ref("delegation", "demo"),
            "dependency_refs": [],
            "parallel_status_ref": _ref("parallel-status", "demo"),
            "evidence_refs": [_ref("evidence", "session-demo")],
            "invalidation_refs": [],
        }
    event = {
        "kind": "kotodama.conversation-event",
        "schema_revision": "v1",
        "event_id": _ref("event", event_id),
        "sequence": sequence,
        "session": {
            "state": session_state,
            "session_ref": session_ref,
            "revision_ref": revision,
            "binding_event_ref": None,
            "governance": governance,
        },
        "source": {
            "type": source_type,
            "occurred_at": occurred_at or f"2026-08-26T00:00:{sequence:02d}Z",
            "ingested_at": ingested_at or f"2026-08-26T00:01:{sequence:02d}Z",
            "locator_ref": _ref("source", f"locator-{event_id}"),
            "source_revision_ref": _ref("source-revision", f"{event_id}-1"),
            "actor_ref": actor_ref,
            "identity_verification": (
                "UNVERIFIED_PUBLIC_CLAIM"
                if actor_ref.startswith(("ref/actor/", "ref/speaker/"))
                else "NOT_APPLICABLE"
            ),
            "speaker_track_ref": speaker_track_ref,
            "authority": {"role": authority_role, "authority_ref": authority_ref},
            "thread_ref": _ref("thread", "demo"),
            "channel_ref": _ref("channel", "demo"),
            "document_ref": None,
            "repository_ref": None,
            "evidence_ref": _ref("evidence", f"source-{event_id}"),
            "consent_ref": _ref("consent", "default"),
        },
        "content": {
            "payload_vault_ref": _ref("vault", f"payload-{event_id}"),
            "vault_manifest_ref": _ref("vault-manifest", f"manifest-{event_id}"),
            "content_hash": content_hash,
            "span_ref": _ref("span", f"{event_id}-whole"),
            "storage": "PROTECTED_PAYLOAD_VAULT",
            "raw_content_embedded": False,
            "artifact_stage": artifact_stage,
            "derived_from_event_refs": derived_from_event_refs,
        },
        "causation": {
            "caused_by_event_refs": caused_by_event_refs,
            "correlation_ref": _ref("correlation", "demo"),
            "idempotency_key_ref": _ref("idempotency", event_id),
            "cursor_ref": _ref("cursor", f"{event_id}-1"),
            "replay_of_event_ref": None,
        },
        "context": {
            "background_ref": _ref("context", "demo-background"),
            "knowledge_scope_ref": _ref("knowledge-scope", "demo"),
            "context_pack_refs": [],
            "omission_refs": [],
        },
        "ownership": {
            "owner_ref": _ref("owner", "alice"),
            "assignee_ref": None,
        },
        "event": {
            "kind": event_kind,
            "state": compaction_state or event_state,
            "summary_ref": _ref("summary", event_id),
            "correction_of_event_ref": correction_of_event_ref,
            "withdrawal_of_event_ref": withdrawal_of_event_ref,
            "confirmation_of_event_ref": confirmation_of_event_ref,
            "invalidation_kind": invalidation_kind,
            "invalidation_refs": invalidation_refs,
            "binding": {
                "target_event_refs": binding_targets,
                "destination_session_ref": binding_destination,
                "destination_revision_ref": binding_revision,
            },
        },
        "decision": {
            "status": decision_status,
            "candidate_ref": candidate_ref,
            "human_evidence_ref": human_evidence_ref,
            "human_decision_ref": human_decision_ref,
            "human_actor_ref": human_actor_ref,
            "current_truth_ref": None,
            "execution_authority_granted": False,
        },
        "policy_deviation": {
            "status": deviation_status,
            "rule_ref": None,
            "reason_ref": None,
            "approver_ref": None,
            "expires_at": None,
            "remediation_ref": None,
        },
        "retention": {
            "policy_ref": _ref("retention-policy", "default"),
            "policy_revision_ref": _ref("retention-policy-revision", "default-1"),
            "storage_class": "PROTECTED_HOT",
            "encryption_ref": _ref("encryption", "vault-default"),
            "encryption_status": "DECLARED_UNVERIFIED",
            "retain_until": "2026-09-26T00:00:00Z",
            "archive_target_kind": "NONE",
            "archive_target_ref": None,
            "archive_target_uri_ref": None,
            "archive_package_digest": None,
            "snapshot_receipt_ref": None,
            "archive_status": "NOT_REQUESTED",
            "archive_receipt_ref": None,
            "restore_status": "NOT_REQUESTED",
            "restore_receipt_ref": None,
            "deletion_trigger": "expiry_or_withdrawal",
            "deletion_state": deletion_state,
            "deletion_receipt_ref": deletion_receipt_ref,
            "deletion_readback": deletion_readback,
        },
        "provenance": {
            "adapter_contract_ref": _ref("adapter", source_type),
            "ingested_by_ref": _ref("ingester", "local-contract"),
            "ingest_mode": ingest_mode,
            "connector_ref": _ref("connector", source_type),
            "extraction": {
                "kind": extraction_kind,
                "candidate_ref": candidate_ref if extraction_kind != "NONE" else None,
                "model_ref": _ref("model", "candidate-only") if extraction_kind != "NONE" else None,
                "confirmation_required": True,
            },
            "recovery": {
                "status": "NOT_APPLICABLE" if ingest_mode == "ONLINE" else "RECOVERED",
                "cursor_ref": None if ingest_mode == "ONLINE" else _ref("cursor", "recovery"),
                "receipt_ref": None if ingest_mode == "ONLINE" else _ref("recovery-receipt", event_id),
            },
        },
        "public_safety": {
            "record_visibility": "PUBLIC_SANITIZED_METADATA",
            "raw_payload_embedded": False,
            "protected_payload_ref": _ref("vault", f"payload-{event_id}"),
            "knowledge_scope_ref": _ref("knowledge-scope", "demo"),
            "acl_state": acl_state,
        },
        "integrity": {
            "marker": integrity_marker,
            "gap_start_sequence": None,
            "gap_end_sequence": None,
            "marker_ref": None if integrity_marker == "NONE" else _ref("integrity-marker", event_id),
        },
        "previous_event_hash": previous_hash,
        "event_hash": "0" * 64,
    }
    return ledger.seal_event(event, sequence=sequence, previous_hash=previous_hash)


def _valid_records() -> list[dict]:
    first = _event("inbox-1")
    second = _event(
        "binding-1",
        sequence=2,
        previous_hash=first["event_hash"],
        event_kind="session_binding",
        session_state="BOUND",
        binding_targets=[first["event_id"]],
        binding_destination=_ref("session", "demo"),
        binding_revision=_ref("session-revision", "1"),
        source_type="system",
        actor_ref="ref/agent/ledger",
        authority_role="SYSTEM",
        authority_ref="ref/authority/ledger",
    )
    third = _event(
        "candidate-1",
        sequence=3,
        previous_hash=second["event_hash"],
        event_kind="decision_candidate",
        session_state="BOUND",
        session_ref=_ref("session", "demo"),
        event_state="CANDIDATE",
        decision_status="LLM_CANDIDATE",
        candidate_ref=_ref("candidate", "intent-1"),
        extraction_kind="LLM_CANDIDATE",
        source_type="codex",
        actor_ref="ref/agent/codex",
        authority_role="AGENT",
        authority_ref="ref/authority/codex",
    )
    return [first, second, third]


def _lifecycle_records(event_kind: str, decision_status: str, event_state: str) -> list[dict]:
    records = _valid_records()
    candidate = records[-1]
    target_kwargs = {
        "correction": {"correction_of_event_ref": candidate["event_id"]},
        "withdrawal": {"withdrawal_of_event_ref": candidate["event_id"]},
        "confirmation": {"confirmation_of_event_ref": candidate["event_id"]},
        "decision_confirmed": {"confirmation_of_event_ref": candidate["event_id"]},
    }[event_kind]
    lifecycle = _event(
        f"{event_kind}-1",
        sequence=4,
        previous_hash=candidate["event_hash"],
        event_kind=event_kind,
        session_state="BOUND",
        session_ref=_ref("session", "demo"),
        event_state=event_state,
        decision_status=decision_status,
        candidate_ref=_ref("candidate", "intent-1"),
        human_evidence_ref=_ref("evidence", f"human-{event_kind}"),
        human_decision_ref=_ref("decision", f"decision-{event_kind}"),
        caused_by_event_refs=[candidate["event_id"]],
        source_type="discord_text",
        actor_ref="ref/speaker/alice",
        authority_role="HUMAN",
        authority_ref="ref/authority/alice",
        **target_kwargs,
    )
    records.append(lifecycle)
    return records


class SessionConversationLedgerTests(unittest.TestCase):
    def test_event_and_projection_schemas_are_closed_and_valid(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        projection_schema = json.loads(PROJECTION_SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator.check_schema(projection_schema)
        self.assertFalse(schema["additionalProperties"])
        self.assertFalse(projection_schema["additionalProperties"])
        self.assertEqual([], list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(_valid_records()[0])))
        report = ledger.validate_ledger(_valid_records())
        self.assertEqual("LEDGER_VALID", report["result"], report)
        self.assertFalse(hasattr(ledger, "rechain"))

    def test_append_is_idempotent_but_conflicting_duplicate_is_refused(self) -> None:
        records = _valid_records()
        retry = copy.deepcopy(records[-1])
        result, status = ledger.append_event(records, retry)
        self.assertEqual("IDEMPOTENT_REPLAY", status)
        self.assertEqual(records, result)
        conflicting = copy.deepcopy(retry)
        conflicting["content"]["content_hash"] = "b" * 64
        with self.assertRaises(ledger.LedgerValidationError) as raised:
            ledger.append_event(records, conflicting)
        self.assertIn("DUPLICATE_EVENT_ID", raised.exception.reason_codes)

    def test_unassigned_event_is_bound_by_new_event_and_projection_is_rebuildable(self) -> None:
        records = _valid_records()
        projection = ledger.project_session(records, _ref("session", "demo"))
        projection_schema = json.loads(PROJECTION_SCHEMA.read_text(encoding="utf-8"))
        projection_errors = list(
            Draft202012Validator(projection_schema, format_checker=FormatChecker()).iter_errors(projection)
        )
        self.assertEqual([], projection_errors)
        self.assertEqual("REBUILDABLE", projection["status"])
        self.assertEqual(
            [_ref("event", "inbox-1"), _ref("event", "binding-1"), _ref("event", "candidate-1")],
            projection["source_event_refs"],
        )
        self.assertFalse(projection["authority"]["compaction_summary_is_source"])

    def test_cli_project_emits_schema_valid_projection_and_exit_zero(self) -> None:
        records = _valid_records()
        projection_schema = json.loads(PROJECTION_SCHEMA.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.jsonl"
            path.write_text(
                "\n".join(json.dumps(record, sort_keys=True, separators=(",", ":")) for record in records) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            completed = subprocess.run(
                [sys.executable, "-B", str(VALIDATOR), "project", str(path), _ref("session", "demo")],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
        self.assertEqual(0, completed.returncode, completed.stderr)
        projection = json.loads(completed.stdout)
        self.assertEqual("REBUILDABLE", projection["status"])
        self.assertEqual([], list(Draft202012Validator(projection_schema, format_checker=FormatChecker()).iter_errors(projection)))

    def test_confirmation_correction_and_withdrawal_supersede_candidate(self) -> None:
        projection_schema = json.loads(PROJECTION_SCHEMA.read_text(encoding="utf-8"))
        for event_kind, decision_status, event_state, expected_status in (
            ("decision_confirmed", "HUMAN_CONFIRMED", "CONFIRMED", "HUMAN_CONFIRMED"),
            ("correction", "HUMAN_CORRECTED", "CORRECTED", "HUMAN_CORRECTED"),
            ("withdrawal", "HUMAN_WITHDRAWN", "WITHDRAWN", "WITHDRAWN"),
        ):
            with self.subTest(event_kind=event_kind):
                records = _lifecycle_records(event_kind, decision_status, event_state)
                projection = ledger.project_session(records, _ref("session", "demo"))
                errors = list(Draft202012Validator(projection_schema, format_checker=FormatChecker()).iter_errors(projection))
                self.assertEqual([], errors)
                intents = [item for item in projection["confirmed_intent"] if item["candidate_ref"] == _ref("candidate", "intent-1")]
                self.assertEqual(1, len(intents))
                self.assertEqual(expected_status, intents[0]["status"])
                self.assertEqual(_ref("event", f"{event_kind}-1"), intents[0]["confirmation_event_ref"])
                self.assertEqual("NONE", projection["next_safe_action"]["kind"])

    def test_mixed_offset_timestamps_compare_instants_not_strings(self) -> None:
        records = _valid_records()
        records[1]["source"]["ingested_at"] = "2026-08-26T09:01:02+09:00"
        records[2]["source"]["ingested_at"] = "2026-08-26T00:01:03Z"
        self.assertEqual("LEDGER_VALID", ledger.validate_ledger(_rechain(records))["result"])
        records[2]["source"]["ingested_at"] = "2026-08-26T00:00:59Z"
        report = ledger.validate_ledger(_rechain(records))
        self.assertIn("INGESTED_AT_NOT_MONOTONIC", report["reason_codes"])

    def test_revision_schema_and_validator_have_positive_parity(self) -> None:
        records = _valid_records()
        records[2]["session"]["revision_ref"] = _ref("session-revision", "0")
        records = _rechain(records)
        report = ledger.validate_ledger(records)
        self.assertIn("SCHEMA_INVALID", report["reason_codes"])
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(records[2]))
        self.assertTrue(errors)
        stale = _valid_records()
        stale[1]["session"]["revision_ref"] = _ref("session-revision", "2")
        stale[1]["event"]["binding"]["destination_revision_ref"] = _ref("session-revision", "2")
        stale[2]["session"]["revision_ref"] = _ref("session-revision", "1")
        stale_report = ledger.validate_ledger(_rechain(stale))
        self.assertIn("STALE_SESSION_REVISION", stale_report["reason_codes"])

    def test_ref_length_boundaries_match_schema_and_validator(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        for value in ("ref/a", "ref/" + "a" * 509):
            with self.subTest(value_length=len(value)):
                records = _valid_records()
                records[0]["context"]["background_ref"] = value
                records = _rechain(records)
                report = ledger.validate_ledger(records)
                schema_errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(records[0]))
                self.assertTrue(schema_errors)
                self.assertIn("SCHEMA_INVALID", report["reason_codes"])

    def test_raw_and_derived_content_lineage_is_explicit_and_non_reused(self) -> None:
        records = _valid_records()
        raw = _event(
            "voice-raw",
            sequence=4,
            previous_hash=records[-1]["event_hash"],
            session_state="BOUND",
            session_ref=_ref("session", "demo"),
            event_kind="voice_segment",
            source_type="discord_voice",
            speaker_track_ref=_ref("track", "alice"),
            artifact_stage="RAW_AUDIO",
            content_hash="b" * 64,
        )
        asr = _event(
            "voice-asr",
            sequence=5,
            previous_hash=raw["event_hash"],
            session_state="BOUND",
            session_ref=_ref("session", "demo"),
            event_kind="voice_segment",
            source_type="discord_voice",
            speaker_track_ref=_ref("track", "alice"),
            artifact_stage="RAW_ASR",
            derived_from_event_refs=[raw["event_id"]],
            content_hash="c" * 64,
        )
        derived = _event(
            "voice-transcript",
            sequence=6,
            previous_hash=asr["event_hash"],
            session_state="BOUND",
            session_ref=_ref("session", "demo"),
            event_kind="voice_segment",
            source_type="discord_voice",
            speaker_track_ref=_ref("track", "alice"),
            artifact_stage="ALIGNED_TRANSCRIPT",
            derived_from_event_refs=[asr["event_id"]],
            content_hash="d" * 64,
        )
        valid_report = ledger.validate_ledger(records + [raw, asr, derived])
        self.assertEqual("LEDGER_VALID", valid_report["result"], valid_report)
        reused = copy.deepcopy(records + [raw, asr, derived])
        reused[-1]["content"]["payload_vault_ref"] = reused[-2]["content"]["payload_vault_ref"]
        reused[-1]["content"]["vault_manifest_ref"] = reused[-2]["content"]["vault_manifest_ref"]
        reused[-1]["content"]["content_hash"] = reused[-2]["content"]["content_hash"]
        reuse_report = ledger.validate_ledger(_rechain(reused))
        self.assertIn("CONTENT_LINEAGE_REUSE", reuse_report["reason_codes"])

    def test_artifact_lineage_is_a_forward_dag_with_stage_and_session_edges(self) -> None:
        records = _valid_records()
        previous = records[-1]["event_hash"]
        chain: list[dict] = []
        stages = (
            ("raw-audio", "RAW_AUDIO", [], "b"),
            ("raw-asr", "RAW_ASR", [_ref("event", "raw-audio")], "c"),
            ("aligned", "ALIGNED_TRANSCRIPT", [_ref("event", "raw-asr")], "d"),
            ("speaker", "SPEAKER_ATTRIBUTED_TRANSCRIPT", [_ref("event", "aligned")], "e"),
            ("corrected", "CORRECTED_TRANSCRIPT", [_ref("event", "speaker")], "f"),
            ("minutes", "MINUTES", [_ref("event", "corrected")], "1"),
            ("evidence", "SOURCE_EVIDENCE", [_ref("event", "minutes")], "2"),
        )
        for offset, (event_id, stage, parents, digest_prefix) in enumerate(stages, start=4):
            event = _event(
                event_id,
                sequence=offset,
                previous_hash=previous,
                session_state="BOUND",
                session_ref=_ref("session", "demo"),
                artifact_stage=stage,
                derived_from_event_refs=parents,
                content_hash=digest_prefix * 64,
                source_type="system",
                actor_ref="ref/system/ledger",
                authority_role="SYSTEM",
                authority_ref="ref/authority/ledger",
            )
            chain.append(event)
            previous = event["event_hash"]
        valid = records + chain
        self.assertEqual("LEDGER_VALID", ledger.validate_ledger(valid)["result"])

        same_stage = copy.deepcopy(valid[:5])
        same_stage_parent = same_stage[-1]
        same_stage_child = _event(
            "raw-asr-again",
            sequence=6,
            previous_hash=same_stage_parent["event_hash"],
            session_state="BOUND",
            session_ref=_ref("session", "demo"),
            artifact_stage="RAW_ASR",
            derived_from_event_refs=[same_stage_parent["event_id"]],
            content_hash="8" * 64,
            source_type="system",
            actor_ref="ref/system/ledger",
            authority_role="SYSTEM",
            authority_ref="ref/authority/ledger",
        )
        same_stage.append(same_stage_child)
        report = ledger.validate_ledger(_rechain(same_stage))
        self.assertIn("CONTENT_LINEAGE_STAGE_INVALID", report["reason_codes"])

        backward = copy.deepcopy(valid)
        backward[4]["content"]["derived_from_event_refs"] = [backward[5]["event_id"]]
        report = ledger.validate_ledger(_rechain(backward))
        self.assertIn("CONTENT_LINEAGE_ORDER_INVALID", report["reason_codes"])

        cross_session = copy.deepcopy(valid[:5])
        cross_session[-2]["session"]["session_ref"] = _ref("session", "other")
        cross_session[-1]["content"]["derived_from_event_refs"] = [cross_session[-2]["event_id"]]
        report = ledger.validate_ledger(_rechain(cross_session))
        self.assertIn("CONTENT_LINEAGE_SESSION_INVALID", report["reason_codes"])

    def test_archive_state_combinations_are_coherent(self) -> None:
        restored = _valid_records()
        restored[-1]["retention"].update(
            {
                "archive_target_kind": "ARCHIVE_TARGET",
                "archive_target_ref": _ref("archive-target", "session-demo"),
                "archive_target_uri_ref": _ref("archive-uri", "session-demo"),
                "archive_package_digest": "c" * 64,
                "snapshot_receipt_ref": _ref("snapshot-receipt", "session-demo"),
                "archive_status": "RESTORED",
                "archive_receipt_ref": _ref("archive-receipt", "session-demo"),
                "restore_status": "RESTORED",
                "restore_receipt_ref": _ref("restore-receipt", "session-demo"),
            }
        )
        self.assertEqual("LEDGER_VALID", ledger.validate_ledger(_rechain(restored))["result"])

        deleted = copy.deepcopy(restored)
        deleted[-1]["retention"].update(
            {
                "archive_status": "DELETED",
                "restore_status": "RESTORED",
                "deletion_state": "CONFIRMED",
                "deletion_readback": "CONFIRMED",
                "deletion_receipt_ref": _ref("deletion-receipt", "session-demo"),
            }
        )
        self.assertEqual("LEDGER_VALID", ledger.validate_ledger(_rechain(deleted))["result"])

        cold_none = _valid_records()
        cold_none[-1]["retention"].update(
            {"storage_class": "ENCRYPTED_COLD_ARCHIVE", "encryption_status": "DECLARED_UNVERIFIED"}
        )
        report = ledger.validate_ledger(_rechain(cold_none))
        self.assertIn("COLD_ARCHIVE_TARGET_REQUIRED", report["reason_codes"])

        restore_not_requested = copy.deepcopy(restored)
        restore_not_requested[-1]["retention"]["archive_status"] = "RESTORED"
        restore_not_requested[-1]["retention"]["restore_status"] = "NOT_REQUESTED"
        restore_not_requested[-1]["retention"]["restore_receipt_ref"] = None
        report = ledger.validate_ledger(_rechain(restore_not_requested))
        self.assertIn("ARCHIVE_RESTORE_STATE_INVALID", report["reason_codes"])

        deleted_without_readback = copy.deepcopy(restored)
        deleted_without_readback[-1]["retention"].update(
            {
                "archive_status": "DELETED",
                "restore_status": "NOT_REQUESTED",
                "restore_receipt_ref": None,
                "deletion_state": "PENDING",
                "deletion_readback": "NOT_REQUESTED",
                "deletion_receipt_ref": None,
            }
        )
        report = ledger.validate_ledger(_rechain(deleted_without_readback))
        self.assertIn("ARCHIVE_DELETION_STATE_INVALID", report["reason_codes"])

        contradictory_restore = copy.deepcopy(restored)
        contradictory_restore[-1]["retention"]["restore_status"] = "NOT_REQUESTED"
        report = ledger.validate_ledger(_rechain(contradictory_restore))
        self.assertIn("RESTORE_RECEIPT_INVALID", report["reason_codes"])

        direct_delete = _valid_records()
        direct_delete[-1]["retention"].update(
            {
                "archive_target_kind": "ARCHIVE_TARGET",
                "archive_target_ref": _ref("archive-target", "direct-delete"),
                "archive_target_uri_ref": _ref("archive-uri", "direct-delete"),
                "archive_package_digest": "e" * 64,
                "snapshot_receipt_ref": _ref("snapshot-receipt", "direct-delete"),
                "archive_status": "DELETED",
                "archive_receipt_ref": _ref("archive-receipt", "direct-delete"),
                "restore_status": "NOT_REQUESTED",
                "restore_receipt_ref": None,
                "deletion_state": "CONFIRMED",
                "deletion_readback": "CONFIRMED",
                "deletion_receipt_ref": _ref("deletion-receipt", "direct-delete"),
            }
        )
        self.assertEqual("LEDGER_VALID", ledger.validate_ledger(_rechain(direct_delete))["result"])

    def test_later_llm_candidate_reuse_after_human_state_is_refused(self) -> None:
        records = _lifecycle_records("decision_confirmed", "HUMAN_CONFIRMED", "CONFIRMED")
        previous = records[-1]["event_hash"]
        later = _event(
            "candidate-retry",
            sequence=5,
            previous_hash=previous,
            event_kind="decision_candidate",
            session_state="BOUND",
            session_ref=_ref("session", "demo"),
            event_state="CANDIDATE",
            decision_status="LLM_CANDIDATE",
            candidate_ref=_ref("candidate", "intent-1"),
            extraction_kind="LLM_CANDIDATE",
            source_type="codex",
            actor_ref="ref/agent/codex",
            authority_role="AGENT",
            authority_ref="ref/authority/codex",
            content_hash="d" * 64,
        )
        records.append(later)
        report = ledger.validate_ledger(records)
        self.assertEqual("REFUSED", report["result"])
        self.assertIn("CANDIDATE_LIFECYCLE_REGRESSION", report["reason_codes"])

    def test_content_artifact_identity_is_global_not_only_parent_scoped(self) -> None:
        for field in ("payload_vault_ref", "vault_manifest_ref", "content_hash"):
            with self.subTest(field=field):
                records = _valid_records()
                sibling = _event(
                    f"alias-{field}",
                    sequence=4,
                    previous_hash=records[-1]["event_hash"],
                    session_state="BOUND",
                    session_ref=_ref("session", "demo"),
                    source_type="system",
                    actor_ref="ref/system/ledger",
                    authority_role="SYSTEM",
                    authority_ref="ref/authority/ledger",
                )
                sibling["content"][field] = records[0]["content"][field]
                records.append(sibling)
                report = ledger.validate_ledger(_rechain(records))
                self.assertEqual("REFUSED", report["result"], report)
                self.assertIn("CONTENT_ARTIFACT_ALIAS", report["reason_codes"])

    def test_archive_deletion_coupling_is_scoped_to_archive_targets(self) -> None:
        hot_delete = _valid_records()
        hot_delete[-1]["retention"].update(
            {
                "deletion_state": "CONFIRMED",
                "deletion_readback": "CONFIRMED",
                "deletion_receipt_ref": _ref("deletion-receipt", "hot-source"),
            }
        )
        self.assertEqual("LEDGER_VALID", ledger.validate_ledger(_rechain(hot_delete))["result"])

        contradictory = _valid_records()
        contradictory[-1]["retention"].update(
            {
                "archive_target_kind": "ARCHIVE_TARGET",
                "archive_target_ref": _ref("archive-target", "demo"),
                "archive_target_uri_ref": _ref("archive-uri", "demo"),
                "archive_package_digest": "d" * 64,
                "archive_status": "DECLARED",
                "archive_receipt_ref": _ref("archive-receipt", "demo"),
                "deletion_state": "CONFIRMED",
                "deletion_readback": "CONFIRMED",
                "deletion_receipt_ref": _ref("deletion-receipt", "demo"),
            }
        )
        report = ledger.validate_ledger(_rechain(contradictory))
        self.assertEqual("REFUSED", report["result"], report)
        self.assertIn("ARCHIVE_DELETION_STATE_INVALID", report["reason_codes"])

    def test_candidate_human_state_is_monotonic_and_withdrawal_is_terminal(self) -> None:
        records = _valid_records()
        candidate = records[-1]
        confirmation = _event(
            "confirm-chain",
            sequence=4,
            previous_hash=candidate["event_hash"],
            event_kind="decision_confirmed",
            session_state="BOUND",
            session_ref=_ref("session", "demo"),
            event_state="CONFIRMED",
            decision_status="HUMAN_CONFIRMED",
            candidate_ref=_ref("candidate", "intent-1"),
            human_evidence_ref=_ref("evidence", "human-confirm-chain"),
            human_decision_ref=_ref("decision", "confirm-chain"),
            confirmation_of_event_ref=candidate["event_id"],
            caused_by_event_refs=[candidate["event_id"]],
            source_type="system",
            actor_ref="ref/speaker/alice",
            authority_role="HUMAN",
            authority_ref="ref/authority/alice",
        )
        correction = _event(
            "correct-chain",
            sequence=5,
            previous_hash=confirmation["event_hash"],
            event_kind="correction",
            session_state="BOUND",
            session_ref=_ref("session", "demo"),
            event_state="CORRECTED",
            decision_status="HUMAN_CORRECTED",
            candidate_ref=_ref("candidate", "intent-1"),
            human_evidence_ref=_ref("evidence", "human-correct-chain"),
            human_decision_ref=_ref("decision", "correct-chain"),
            correction_of_event_ref=confirmation["event_id"],
            caused_by_event_refs=[confirmation["event_id"]],
            source_type="system",
            actor_ref="ref/speaker/alice",
            authority_role="HUMAN",
            authority_ref="ref/authority/alice",
        )
        withdrawal = _event(
            "withdraw-chain",
            sequence=6,
            previous_hash=correction["event_hash"],
            event_kind="withdrawal",
            session_state="BOUND",
            session_ref=_ref("session", "demo"),
            event_state="WITHDRAWN",
            decision_status="HUMAN_WITHDRAWN",
            candidate_ref=_ref("candidate", "intent-1"),
            human_evidence_ref=_ref("evidence", "human-withdraw-chain"),
            human_decision_ref=_ref("decision", "withdraw-chain"),
            withdrawal_of_event_ref=correction["event_id"],
            caused_by_event_refs=[correction["event_id"]],
            source_type="system",
            actor_ref="ref/speaker/alice",
            authority_role="HUMAN",
            authority_ref="ref/authority/alice",
        )
        records.extend([confirmation, correction, withdrawal])
        self.assertEqual("LEDGER_VALID", ledger.validate_ledger(records)["result"])
        projection = ledger.project_session(records, _ref("session", "demo"))
        intent = next(item for item in projection["confirmed_intent"] if item["candidate_ref"] == _ref("candidate", "intent-1"))
        self.assertEqual("WITHDRAWN", intent["status"])
        self.assertEqual("NONE", projection["next_safe_action"]["kind"])

        late_confirmation = _event(
            "confirm-after-withdraw",
            sequence=7,
            previous_hash=withdrawal["event_hash"],
            event_kind="decision_confirmed",
            session_state="BOUND",
            session_ref=_ref("session", "demo"),
            event_state="CONFIRMED",
            decision_status="HUMAN_CONFIRMED",
            candidate_ref=_ref("candidate", "intent-1"),
            human_evidence_ref=_ref("evidence", "human-late-confirm"),
            human_decision_ref=_ref("decision", "late-confirm"),
            confirmation_of_event_ref=withdrawal["event_id"],
            caused_by_event_refs=[withdrawal["event_id"]],
            source_type="system",
            actor_ref="ref/speaker/alice",
            authority_role="HUMAN",
            authority_ref="ref/authority/alice",
        )
        report = ledger.validate_ledger(records + [late_confirmation])
        self.assertEqual("REFUSED", report["result"], report)
        self.assertIn("CANDIDATE_LIFECYCLE_REGRESSION", report["reason_codes"])

    def test_replay_requires_session_parity(self) -> None:
        cases: list[list[dict]] = []
        bound_replaying_unassigned = _valid_records()
        bound_replaying_unassigned[2]["causation"]["replay_of_event_ref"] = bound_replaying_unassigned[0]["event_id"]
        cases.append(_rechain(bound_replaying_unassigned))

        unassigned_replaying_bound = _valid_records()
        replay = _event(
            "unassigned-replay",
            sequence=4,
            previous_hash=unassigned_replaying_bound[-1]["event_hash"],
            session_state="UNASSIGNED_INBOX",
            source_type="system",
            actor_ref="ref/system/ledger",
            authority_role="SYSTEM",
            authority_ref="ref/authority/ledger",
        )
        replay["causation"]["replay_of_event_ref"] = unassigned_replaying_bound[1]["event_id"]
        unassigned_replaying_bound.append(replay)
        cases.append(_rechain(unassigned_replaying_bound))

        different_bound_session = _valid_records()
        replay = _event(
            "different-session-replay",
            sequence=4,
            previous_hash=different_bound_session[-1]["event_hash"],
            session_state="BOUND",
            session_ref=_ref("session", "other"),
            source_type="system",
            actor_ref="ref/system/ledger",
            authority_role="SYSTEM",
            authority_ref="ref/authority/ledger",
        )
        replay["causation"]["replay_of_event_ref"] = different_bound_session[2]["event_id"]
        different_bound_session.append(replay)
        cases.append(_rechain(different_bound_session))

        for records in cases:
            with self.subTest(event_id=records[-1]["event_id"]):
                report = ledger.validate_ledger(records)
                self.assertEqual("REFUSED", report["result"], report)
                self.assertIn("REPLAY_SESSION_INVALID", report["reason_codes"])

        first = _event("replay-inbox-1", source_type="system", actor_ref="ref/system/ledger", authority_role="SYSTEM", authority_ref="ref/authority/ledger")
        second = _event(
            "replay-inbox-2",
            sequence=2,
            previous_hash=first["event_hash"],
            session_state="UNASSIGNED_INBOX",
            source_type="system",
            actor_ref="ref/system/ledger",
            authority_role="SYSTEM",
            authority_ref="ref/authority/ledger",
        )
        second["causation"]["replay_of_event_ref"] = first["event_id"]
        self.assertEqual("LEDGER_VALID", ledger.validate_ledger(_rechain([first, second]))["result"])

    def test_malformed_integrity_values_refuse_without_traceback(self) -> None:
        for malformed_integrity in (None, "not-an-object", [], ["marker"], 1):
            with self.subTest(malformed_integrity=malformed_integrity):
                records = _valid_records()
                records[0]["integrity"] = malformed_integrity
                report = ledger.validate_ledger(records)
                self.assertEqual("REFUSED", report["result"])
                self.assertIn("SCHEMA_INVALID", report["reason_codes"])

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "malformed-integrity.jsonl"
            records = _valid_records()
            records[0]["integrity"] = {"marker": "bad"}
            path.write_text(
                "\n".join(json.dumps(record, sort_keys=True, separators=(",", ":")) for record in records) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            completed = subprocess.run(
                [sys.executable, "-B", str(VALIDATOR), "validate", str(path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
        self.assertEqual(2, completed.returncode)
        self.assertNotIn("Traceback", completed.stderr)
        self.assertIn("SCHEMA_INVALID", json.loads(completed.stdout)["reason_codes"])

    def test_replay_and_session_binding_targets_must_be_strictly_earlier(self) -> None:
        self_replay = _valid_records()
        self_replay[2]["causation"]["replay_of_event_ref"] = self_replay[2]["event_id"]
        report = ledger.validate_ledger(_rechain(self_replay))
        self.assertIn("REPLAY_TARGET_SELF_REFERENCE", report["reason_codes"])

        future_target = _event(
            "future-replay",
            sequence=4,
            previous_hash=_valid_records()[-1]["event_hash"],
            session_state="BOUND",
            session_ref=_ref("session", "demo"),
            source_type="system",
            actor_ref="ref/system/ledger",
            authority_role="SYSTEM",
            authority_ref="ref/authority/ledger",
        )
        future_replay = _valid_records()
        future_replay[2]["causation"]["replay_of_event_ref"] = future_target["event_id"]
        future_replay.append(future_target)
        report = ledger.validate_ledger(_rechain(future_replay))
        self.assertIn("REPLAY_TARGET_ORDER_INVALID", report["reason_codes"])

        future_binding_target = _event(
            "future-inbox",
            sequence=3,
            previous_hash="0" * 64,
            session_state="UNASSIGNED_INBOX",
            source_type="system",
            actor_ref="ref/system/ledger",
            authority_role="SYSTEM",
            authority_ref="ref/authority/ledger",
        )
        binding = _event(
            "binding-future",
            sequence=2,
            previous_hash="0" * 64,
            event_kind="session_binding",
            session_state="BOUND",
            session_ref=_ref("session", "demo"),
            binding_targets=[future_binding_target["event_id"]],
            binding_destination=_ref("session", "demo"),
            binding_revision=_ref("session-revision", "1"),
            source_type="system",
            actor_ref="ref/system/ledger",
            authority_role="SYSTEM",
            authority_ref="ref/authority/ledger",
        )
        binding_records = [_event("inbox-first"), binding, future_binding_target]
        report = ledger.validate_ledger(_rechain(binding_records))
        self.assertIn("SESSION_BINDING_TARGET_ORDER_INVALID", report["reason_codes"])

    def test_acl_invalidation_is_persistent_until_a_new_contract(self) -> None:
        records = _valid_records()
        acl_lost = _event(
            "acl-lost",
            sequence=4,
            previous_hash=records[-1]["event_hash"],
            event_kind="acl_loss",
            session_state="BOUND",
            session_ref=_ref("session", "demo"),
            event_state="INVALIDATED",
            invalidation_kind="ACL_LOST",
            invalidation_refs=[_ref("projection", "demo")],
            acl_state="LOST",
            source_type="system",
            actor_ref="ref/system/ledger",
            authority_role="SYSTEM",
            authority_ref="ref/authority/ledger",
        )
        available = _event(
            "acl-available-later",
            sequence=5,
            previous_hash=acl_lost["event_hash"],
            session_state="BOUND",
            session_ref=_ref("session", "demo"),
            source_type="system",
            actor_ref="ref/system/ledger",
            authority_role="SYSTEM",
            authority_ref="ref/authority/ledger",
        )
        records.extend([acl_lost, available])
        projection = ledger.project_session(records, _ref("session", "demo"))
        self.assertEqual("FAIL_CLOSED", projection["knowledge_scope"]["projection_access"])

        unknown_records = _valid_records()
        unknown = _event(
            "acl-unknown",
            sequence=4,
            previous_hash=unknown_records[-1]["event_hash"],
            session_state="BOUND",
            session_ref=_ref("session", "demo"),
            acl_state="UNKNOWN",
            source_type="system",
            actor_ref="ref/system/ledger",
            authority_role="SYSTEM",
            authority_ref="ref/authority/ledger",
        )
        unknown_available = copy.deepcopy(available)
        unknown_available["event_id"] = _ref("event", "acl-unknown-later")
        unknown_available["sequence"] = 5
        unknown_records.extend([unknown, unknown_available])
        projection = ledger.project_session(_rechain(unknown_records), _ref("session", "demo"))
        self.assertEqual("FAIL_CLOSED", projection["knowledge_scope"]["projection_access"])

    def test_projection_bounds_fail_closed_instead_of_truncating(self) -> None:
        records = _valid_records()
        previous = records[-1]["event_hash"]
        for sequence in range(4, 261):
            action = _event(
                f"action-{sequence}",
                sequence=sequence,
                previous_hash=previous,
                event_kind="tool_action",
                session_state="BOUND",
                session_ref=_ref("session", "demo"),
                source_type="system",
                actor_ref="ref/system/ledger",
                authority_role="SYSTEM",
                authority_ref="ref/authority/ledger",
                content_hash=f"{sequence:064x}",
                occurred_at="2026-08-26T00:00:00Z",
                ingested_at="2026-08-26T00:02:00Z",
            )
            action["ownership"]["assignee_ref"] = _ref("assignee", f"worker-{sequence}")
            records.append(action)
            previous = action["event_hash"]
        records = _rechain(records)
        with self.assertRaises(ledger.LedgerValidationError) as raised:
            ledger.project_session(records, _ref("session", "demo"))
        self.assertIn("PROJECTION_LIMIT_EXCEEDED", raised.exception.reason_codes)

    def test_validate_projection_rejects_overbound_saved_output(self) -> None:
        records = _valid_records()
        projection = ledger.project_session(records, _ref("session", "demo"))
        projection["source_event_refs"] = [_ref("event", f"overflow-{index}") for index in range(4097)]
        with self.assertRaises(ledger.LedgerValidationError) as raised:
            ledger.validate_projection(projection, records, _ref("session", "demo"))
        self.assertIn("PROJECTION_LIMIT_EXCEEDED", raised.exception.reason_codes)

    def test_validate_projection_rejects_overbound_integrity_refs(self) -> None:
        records = _valid_records()
        projection = ledger.project_session(records, _ref("session", "demo"))
        projection["integrity"]["invalidation_refs"] = [_ref("projection", f"overflow-{index}") for index in range(4097)]
        with self.assertRaises(ledger.LedgerValidationError) as raised:
            ledger.validate_projection(projection, records, _ref("session", "demo"))
        self.assertIn("PROJECTION_LIMIT_EXCEEDED", raised.exception.reason_codes)

        records = _valid_records()
        previous = records[-1]["event_hash"]
        for sequence in range(4, 4098):
            event = _event(
                f"bulk-{sequence}",
                sequence=sequence,
                previous_hash=previous,
                session_state="BOUND",
                session_ref=_ref("session", "demo"),
                source_type="system",
                actor_ref="ref/system/ledger",
                authority_role="SYSTEM",
                authority_ref="ref/authority/ledger",
                occurred_at="2026-08-26T00:00:00Z",
                ingested_at="2026-08-26T00:02:00Z",
                content_hash=f"{sequence:064x}",
            )
            records.append(event)
            previous = event["event_hash"]
        records = _rechain(records)
        with self.assertRaises(ledger.LedgerValidationError) as raised:
            ledger.project_session(records, _ref("session", "demo"))
        self.assertIn("PROJECTION_LIMIT_EXCEEDED", raised.exception.reason_codes)

    def test_malformed_roots_and_cli_arity_fail_closed(self) -> None:
        for malformed in ([None], [[]], ["not-an-object"], [True]):
            with self.subTest(malformed=malformed):
                report = ledger.validate_ledger(malformed)
                self.assertEqual("REFUSED", report["result"])
                self.assertIn("SCHEMA_INVALID", report["reason_codes"])

        records = _valid_records()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.jsonl"
            path.write_text(
                "\n".join(json.dumps(record, sort_keys=True, separators=(",", ":")) for record in records) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            validate_extra = subprocess.run(
                [sys.executable, "-B", str(VALIDATOR), "validate", str(path), "extra"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            project_missing = subprocess.run(
                [sys.executable, "-B", str(VALIDATOR), "project", str(path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            project_extra = subprocess.run(
                [sys.executable, "-B", str(VALIDATOR), "project", str(path), _ref("session", "demo"), "extra"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
        self.assertEqual(2, validate_extra.returncode)
        self.assertIn("USAGE", json.loads(validate_extra.stdout)["reason_codes"])
        self.assertEqual(2, project_missing.returncode)
        self.assertIn("USAGE", json.loads(project_missing.stdout)["reason_codes"])
        self.assertEqual(2, project_extra.returncode)
        self.assertIn("USAGE", json.loads(project_extra.stdout)["reason_codes"])

    def test_json_schema_and_validator_agree_on_integral_numeric_values(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        integral = _valid_records()
        integral[0]["sequence"] = 1.0
        integral[0]["integrity"]["marker"] = "GAP"
        integral[0]["integrity"]["gap_start_sequence"] = 1.0
        integral[0]["integrity"]["gap_end_sequence"] = 1.0
        integral[0]["integrity"]["marker_ref"] = _ref("integrity-marker", "gap-1")
        integral = _rechain(integral)
        self.assertEqual(
            [], list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(integral[0]))
        )
        self.assertEqual("LEDGER_VALID", ledger.validate_ledger(integral)["result"])
        projection = ledger.project_session(integral, _ref("session", "demo"))
        self.assertEqual(3, projection["source_ledger_head"]["sequence"])
        self.assertEqual("ref/projection-revision/3", projection["projection_revision_ref"])

        for value in (1.5, True):
            invalid = _valid_records()
            invalid[0]["sequence"] = value
            invalid = _rechain(invalid)
            with self.subTest(value=value):
                self.assertTrue(list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(invalid[0])))
                report = ledger.validate_ledger(invalid)
                self.assertEqual("REFUSED", report["result"])
                self.assertIn("SCHEMA_INVALID", report["reason_codes"])

    def test_lifecycle_target_must_share_bound_session(self) -> None:
        records = _lifecycle_records("decision_confirmed", "HUMAN_CONFIRMED", "CONFIRMED")
        records[-1]["session"]["session_ref"] = _ref("session", "other")
        report = ledger.validate_ledger(_rechain(records))
        self.assertIn("LIFECYCLE_TARGET_SESSION_INVALID", report["reason_codes"])

    def test_lifecycle_target_refs_are_required_earlier_and_typed(self) -> None:
        target_fields = {
            "correction": "correction_of_event_ref",
            "withdrawal": "withdrawal_of_event_ref",
            "confirmation": "confirmation_of_event_ref",
            "decision_confirmed": "confirmation_of_event_ref",
        }
        for event_kind, target_field in target_fields.items():
            decision_status = (
                "HUMAN_CONFIRMED" if event_kind in {"confirmation", "decision_confirmed"}
                else ("HUMAN_CORRECTED" if event_kind == "correction" else "HUMAN_WITHDRAWN")
            )
            event_state = (
                "CONFIRMED" if event_kind in {"confirmation", "decision_confirmed"}
                else ("CORRECTED" if event_kind == "correction" else "WITHDRAWN")
            )
            with self.subTest(event_kind=event_kind):
                records = _lifecycle_records(event_kind, decision_status, event_state)
                records[-1]["event"][target_field] = None
                report = ledger.validate_ledger(_rechain(records))
                self.assertIn("LIFECYCLE_TARGET_REQUIRED", report["reason_codes"])

                records = _lifecycle_records(event_kind, decision_status, event_state)
                records[-1]["event"][target_field] = records[-1]["event_id"]
                report = ledger.validate_ledger(_rechain(records))
                self.assertIn("LIFECYCLE_TARGET_SELF_REFERENCE", report["reason_codes"])

                records = _lifecycle_records(event_kind, decision_status, event_state)
                records[-1]["event"][target_field] = _ref("event", "does-not-exist")
                report = ledger.validate_ledger(_rechain(records))
                self.assertIn("LIFECYCLE_TARGET_MISSING", report["reason_codes"])

                records = _lifecycle_records(event_kind, decision_status, event_state)
                records[-1]["event"][target_field] = _ref("event", "binding-1")
                report = ledger.validate_ledger(_rechain(records))
                self.assertIn("LIFECYCLE_TARGET_RELATION_INVALID", report["reason_codes"])

    def test_archive_and_delete_cross_fields_fail_closed(self) -> None:
        cases = []
        none_receipt = _valid_records()
        none_receipt[-1]["retention"]["archive_receipt_ref"] = _ref("archive-receipt", "unexpected")
        cases.append((none_receipt, "ARCHIVE_TARGET_INVALID"))
        none_status = _valid_records()
        none_status[-1]["retention"]["archive_status"] = "DECLARED"
        none_status[-1]["retention"]["archive_receipt_ref"] = _ref("archive-receipt", "declared")
        cases.append((none_status, "ARCHIVE_STATUS_INCOMPLETE"))
        cold_unencrypted = _valid_records()
        cold_unencrypted[-1]["retention"].update({
            "storage_class": "ENCRYPTED_COLD_ARCHIVE",
            "encryption_status": "NOT_APPLICABLE",
        })
        cases.append((cold_unencrypted, "COLD_ARCHIVE_ENCRYPTION_REQUIRED"))
        deletion_state = _valid_records()
        deletion_state[-1]["retention"]["deletion_state"] = "CONFIRMED"
        cases.append((deletion_state, "DELETION_STATE_RECEIPT_INVALID"))
        source_delete_records = _valid_records()
        source_delete = _event(
            "delete-1",
            sequence=4,
            previous_hash=source_delete_records[-1]["event_hash"],
            event_kind="source_delete",
            session_state="BOUND",
            session_ref=_ref("session", "demo"),
            event_state="INVALIDATED",
            invalidation_kind="SOURCE_DELETED",
            invalidation_refs=[_ref("projection", "demo")],
        )
        source_delete_records.append(source_delete)
        cases.append((source_delete_records, "SOURCE_DELETE_READBACK_REQUIRED"))
        for records, reason in cases:
            with self.subTest(reason=reason):
                report = ledger.validate_ledger(_rechain(records))
                self.assertIn(reason, report["reason_codes"], report)

    def test_source_update_invalidates_projection_and_acl_loss_fails_closed(self) -> None:
        records = _valid_records()
        event = _event(
            "source-update",
            sequence=4,
            previous_hash=records[-1]["event_hash"],
            event_kind="source_update",
            session_state="BOUND",
            session_ref=_ref("session", "demo"),
            event_state="INVALIDATED",
            invalidation_kind="SOURCE_UPDATED",
            invalidation_refs=[_ref("context-pack", "demo"), _ref("task", "demo")],
        )
        records.append(event)
        projection = ledger.project_session(records, _ref("session", "demo"))
        self.assertEqual("INVALIDATED", projection["status"])
        broken = copy.deepcopy(records)
        broken[-1]["public_safety"]["acl_state"] = "LOST"
        broken[-1]["event"]["invalidation_kind"] = None
        broken[-1]["event"]["invalidation_refs"] = []
        broken = _rechain(broken)
        report = ledger.validate_ledger(broken)
        self.assertEqual("REFUSED", report["result"])
        self.assertIn("ACL_LOSS_NOT_INVALIDATED", report["reason_codes"])

    def test_negative_controls_cover_closed_and_public_safe_boundaries(self) -> None:
        cases: list[tuple[str, dict, str]] = []
        unknown = copy.deepcopy(_valid_records())
        unknown[0]["private_audio"] = "base64"
        cases.append(("unknown fields", unknown, "SCHEMA_INVALID"))
        unknown_kind = copy.deepcopy(_valid_records())
        unknown_kind[0]["event"]["kind"] = "future_unlisted_kind"
        cases.append(("unknown event kind", unknown_kind, "SCHEMA_INVALID"))
        missing_source = copy.deepcopy(_valid_records())
        missing_source[0]["source"]["locator_ref"] = None
        cases.append(("missing source ref", missing_source, "SCHEMA_INVALID"))
        missing_hash = copy.deepcopy(_valid_records())
        missing_hash[0]["content"]["content_hash"] = "not-a-digest"
        cases.append(("missing content hash", missing_hash, "SCHEMA_INVALID"))
        raw = copy.deepcopy(_valid_records())
        raw[0]["content"]["raw_content"] = "do not publish"
        cases.append(("raw private content", raw, "SCHEMA_INVALID"))
        confused = copy.deepcopy(_valid_records())
        confused[0]["source"]["actor_ref"] = "ref/authority/alice"
        cases.append(("actor authority confusion", confused, "ACTOR_AUTHORITY_CONFUSION"))
        confirmed = copy.deepcopy(_valid_records())
        confirmed[2]["event"]["kind"] = "decision_confirmed"
        confirmed[2]["event"]["state"] = "CONFIRMED"
        confirmed[2]["decision"]["status"] = "HUMAN_CONFIRMED"
        confirmed[2]["decision"]["candidate_ref"] = _ref("candidate", "intent-1")
        cases.append(("confirmed without human evidence", confirmed, "CONFIRMED_DECISION_NEEDS_HUMAN_EVIDENCE"))
        deviation = copy.deepcopy(_valid_records())
        deviation[2]["policy_deviation"]["status"] = "APPROVED"
        cases.append(("incomplete deviation", deviation, "DEVIATION_FIELDS_INCOMPLETE"))
        missing_model = copy.deepcopy(_valid_records())
        missing_model[2]["provenance"]["extraction"]["model_ref"] = None
        cases.append(("missing model provenance", missing_model, "LLM_MODEL_PROVENANCE_MISSING"))
        missing_grants = copy.deepcopy(_valid_records())
        missing_grants[2]["session"]["governance"]["capability_grant_refs"] = []
        cases.append(("missing session grants", missing_grants, "SESSION_GOVERNANCE_INCOMPLETE"))
        missing_plan = copy.deepcopy(_valid_records())
        missing_plan[2]["session"]["governance"]["plan_ref"] = None
        cases.append(("missing plan binding", missing_plan, "SESSION_GOVERNANCE_INCOMPLETE"))
        missing_requirement = copy.deepcopy(_valid_records())
        missing_requirement[2]["session"]["governance"]["requirement_refs"] = []
        cases.append(("missing requirement binding", missing_requirement, "SESSION_GOVERNANCE_INCOMPLETE"))
        stale = copy.deepcopy(_valid_records())
        stale[1]["session"]["revision_ref"] = _ref("session-revision", "2")
        stale[1]["event"]["binding"]["destination_revision_ref"] = _ref("session-revision", "2")
        stale[2]["session"]["revision_ref"] = _ref("session-revision", "1")
        cases.append(("stale revision", stale, "STALE_SESSION_REVISION"))
        reversed_time = copy.deepcopy(_valid_records())
        reversed_time[2]["source"]["ingested_at"] = "2026-08-25T23:00:00Z"
        cases.append(("time reversal", reversed_time, "INGESTED_AT_NOT_MONOTONIC"))
        gap = copy.deepcopy(_valid_records())
        gap[2]["sequence"] = 4
        cases.append(("sequence gap", gap, "SEQUENCE_NOT_CONTIGUOUS"))
        deletion = copy.deepcopy(_valid_records())
        deletion[2]["retention"]["deletion_state"] = "CONFIRMED"
        deletion[2]["retention"]["deletion_readback"] = "CONFIRMED"
        cases.append(("invalid deletion receipt", deletion, "DELETION_READBACK_RECEIPT_INVALID"))
        compaction = copy.deepcopy(_valid_records())
        compaction[2]["event"]["kind"] = "pre_compact"
        compaction[2]["event"]["state"] = "OBSERVED"
        cases.append(("compaction summary as source", compaction, "COMPACTION_NOT_SOURCE"))
        bad_causal = copy.deepcopy(_valid_records())
        bad_causal[2]["causation"]["caused_by_event_refs"] = [_ref("event", "does-not-exist")]
        cases.append(("bad causal ref", bad_causal, "CAUSATION_REF_MISSING"))
        duplicate = copy.deepcopy(_valid_records())
        duplicate[2]["event_id"] = duplicate[1]["event_id"]
        cases.append(("duplicate event id", duplicate, "DUPLICATE_EVENT_ID"))
        for name, records, reason in cases:
            with self.subTest(name=name):
                report = ledger.validate_ledger(_rechain(records))
                self.assertEqual("REFUSED", report["result"], report)
                self.assertIn(reason, report["reason_codes"], report)

        overwritten = copy.deepcopy(_valid_records())
        overwritten[0]["content"]["content_hash"] = "b" * 64
        overwrite_report = ledger.validate_ledger(overwritten)
        self.assertIn("CONTENT_DIGEST_DRIFT", overwrite_report["reason_codes"])

    def test_public_fixes_reject_forged_authority_non_discord_consent_voice_gap_and_unsafe_refs(self) -> None:
        forged = _lifecycle_records("decision_confirmed", "HUMAN_CONFIRMED", "CONFIRMED")
        forged[-1]["source"]["actor_ref"] = "ref/agent/forged"
        forged[-1]["source"]["authority"] = {
            "role": "OWNER",
            "authority_ref": "ref/authority/forged",
        }
        forged_report = ledger.validate_ledger(_rechain(forged))
        self.assertEqual("REFUSED", forged_report["result"], forged_report)
        self.assertIn("ACTOR_AUTHORITY_ROLE_MISMATCH", forged_report["reason_codes"])
        forged_schema_errors = list(
            Draft202012Validator(
                json.loads(SCHEMA.read_text(encoding="utf-8")),
                format_checker=FormatChecker(),
            ).iter_errors(forged[-1])
        )
        self.assertTrue(forged_schema_errors)

        for source_type in sorted(ledger.SOURCE_TYPES - {"system"}):
            with self.subTest(source_type=source_type):
                records = _valid_records()
                records[0]["source"]["type"] = source_type
                records[0]["source"]["consent_ref"] = None
                report = ledger.validate_ledger(_rechain(records))
                self.assertEqual("REFUSED", report["result"], report)
                self.assertIn("CONSENT_REF_MISSING", report["reason_codes"])
                schema_errors = list(
                    Draft202012Validator(
                        json.loads(SCHEMA.read_text(encoding="utf-8")),
                        format_checker=FormatChecker(),
                    ).iter_errors(records[0])
                )
                self.assertTrue(schema_errors)

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        voice = _valid_records()[0]
        voice["source"]["type"] = "discord_voice"
        voice["source"]["speaker_track_ref"] = None
        voice["source"]["consent_ref"] = _ref("consent", "voice-demo")
        voice_schema_errors = list(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(voice)
        )
        self.assertTrue(voice_schema_errors)
        voice_report = ledger.validate_ledger(_rechain([voice]))
        self.assertIn("VOICE_TRACK_REF_MISSING", voice_report["reason_codes"])

        for unsafe in (
            "ref/source/12345678901234567",
            "ref/source/sk-test-token",
            "alice@example.com",
            "192.0.2.10",
            "C:/Users/alice/private.json",
            "host.example.com",
        ):
            with self.subTest(unsafe=unsafe):
                records = _valid_records()
                records[0]["source"]["locator_ref"] = unsafe
                records = _rechain(records)
                report = ledger.validate_ledger(records)
                self.assertEqual("REFUSED", report["result"], report)
                self.assertIn("PUBLIC_METADATA_UNSAFE_REF", report["reason_codes"])
                schema_errors = list(
                    Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(records[0])
                )
                self.assertTrue(schema_errors)

    def test_malformed_jsonl_and_projection_digest_mismatch_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "truncated.jsonl"
            path.write_text('{"kind":"kotodama.conversation-event"\n', encoding="utf-8", newline="\n")
            completed = subprocess.run(
                [sys.executable, "-B", str(VALIDATOR), "validate", str(path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
        self.assertEqual(2, completed.returncode)
        self.assertIn("INPUT_INVALID", json.loads(completed.stdout)["reason_codes"])

        nested = _valid_records()
        nested[0]["context"]["omission_refs"] = [["nested"]]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested.jsonl"
            path.write_text(
                "\n".join(json.dumps(record, sort_keys=True, separators=(",", ":")) for record in nested) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            completed = subprocess.run(
                [sys.executable, "-B", str(VALIDATOR), "validate", str(path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
        self.assertEqual(2, completed.returncode)
        self.assertNotIn("Traceback", completed.stderr)
        self.assertIn("SCHEMA_INVALID", json.loads(completed.stdout)["reason_codes"])

        records = _valid_records()
        projection = ledger.project_session(records, _ref("session", "demo"))
        projection["source_timeline"][0]["summary_ref"] = _ref("summary", "tampered")
        with self.assertRaises(ledger.LedgerValidationError) as raised:
            ledger.validate_projection(projection, records, _ref("session", "demo"))
        self.assertIn("PROJECTION_DIGEST_MISMATCH", raised.exception.reason_codes)

    def test_offline_recovery_and_integrity_markers_are_explicit(self) -> None:
        records = _valid_records()
        recovered = _event(
            "recovery-1",
            sequence=4,
            previous_hash=records[-1]["event_hash"],
            event_kind="recovery_marker",
            session_state="BOUND",
            session_ref=_ref("session", "demo"),
            event_state="RECOVERY",
            ingest_mode="OFFLINE_RECOVERY",
            integrity_marker="RECOVERY",
            source_type="system",
            actor_ref="ref/agent/recovery",
            authority_role="SYSTEM",
            authority_ref="ref/authority/recovery",
        )
        records.append(recovered)
        report = ledger.validate_ledger(records)
        self.assertEqual("LEDGER_VALID", report["result"], report)
        self.assertEqual("RECOVERY", report["integrity_markers"][0])

    def test_archive_target_is_provider_neutral_and_receipt_bound(self) -> None:
        records = _valid_records()
        retention = records[-1]["retention"]
        retention.update(
            {
                "archive_target_kind": "ARCHIVE_TARGET",
                "archive_target_ref": _ref("archive-target", "session-demo"),
                "archive_target_uri_ref": _ref("archive-uri", "session-demo"),
                "archive_package_digest": "c" * 64,
                "snapshot_receipt_ref": _ref("snapshot-receipt", "session-demo"),
                "archive_status": "DECLARED",
                "archive_receipt_ref": _ref("archive-receipt", "session-demo"),
            }
        )
        report = ledger.validate_ledger(_rechain(records))
        self.assertEqual("LEDGER_VALID", report["result"], report)

    def test_cli_is_read_only_and_returns_machine_result(self) -> None:
        records = _valid_records()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.jsonl"
            path.write_text(
                "\n".join(json.dumps(record, sort_keys=True, separators=(",", ":")) for record in records) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            completed = subprocess.run(
                [sys.executable, "-B", str(VALIDATOR), "validate", str(path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("LEDGER_VALID", json.loads(completed.stdout)["result"])

    def test_adversarial_review_regressions_fail_closed(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

        def rejected_by_schema_and_validator(mutator) -> None:  # type: ignore[no-untyped-def]
            records = _valid_records()
            mutator(records[-1])
            records = _rechain(records)
            self.assertTrue(list(Draft202012Validator(schema).iter_errors(records[-1])))
            self.assertEqual("REFUSED", ledger.validate_ledger(records)["result"])

        rejected_by_schema_and_validator(
            lambda record: record["content"].update(
                {"artifact_stage": "MINUTES", "derived_from_event_refs": []}
            )
        )
        rejected_by_schema_and_validator(
            lambda record: record["retention"].update(
                {"archive_target_kind": "NONE", "archive_status": "DECLARED", "archive_receipt_ref": _ref("archive-receipt", "forged")}
            )
        )
        rejected_by_schema_and_validator(
            lambda record: record["retention"].update(
                {"deletion_state": "CONFIRMED", "deletion_readback": "CONFIRMED", "deletion_receipt_ref": None}
            )
        )
        rejected_by_schema_and_validator(
            lambda record: record["integrity"].update(
                {"marker": "GAP", "gap_start_sequence": 1, "gap_end_sequence": 2, "marker_ref": None}
            )
        )
        rejected_by_schema_and_validator(
            lambda record: record["provenance"].update(
                {"ingest_mode": "OFFLINE_RECOVERY", "recovery": {"status": "PENDING", "cursor_ref": None, "receipt_ref": None}}
            )
        )
        rejected_by_schema_and_validator(
            lambda record: record["provenance"].update(
                {"extraction": {"kind": "LLM_CANDIDATE", "candidate_ref": _ref("candidate", "demo"), "model_ref": None, "confirmation_required": True}}
            )
        )
        rejected_by_schema_and_validator(
            lambda record: (
                record["content"].update({"artifact_stage": "RAW_AUDIO"}),
                record["retention"].update({"storage_class": "DERIVED_SEARCH_INDEX"}),
            )
        )

        self.assertEqual(
            "REFUSED",
            ledger.validate_ledger([{"event_id": []}])["result"],
        )

    def test_deep_json_and_embedded_public_identifiers_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deep.jsonl"
            path.write_text('{"x":' * 5000 + "0" + "}" * 5000 + "\n", encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, "-B", str(VALIDATOR), "validate", str(path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
        self.assertEqual(2, completed.returncode)
        self.assertNotIn("Traceback", completed.stderr)
        self.assertIn("INPUT_INVALID", json.loads(completed.stdout)["reason_codes"])

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        for unsafe in (
            "ref/source/discord-12345678901234567",
            "ref/source/foo-sk-token",
        ):
            records = _valid_records()
            records[0]["source"]["locator_ref"] = unsafe
            records = _rechain(records)
            with self.subTest(unsafe=unsafe):
                self.assertTrue(list(Draft202012Validator(schema).iter_errors(records[0])))
                self.assertIn("PUBLIC_METADATA_UNSAFE_REF", ledger.validate_ledger(records)["reason_codes"])

    def test_voice_reply_egress_is_exactly_destination_and_receipt_bound(self) -> None:
        records = _valid_records()
        reply = _event(
            "voice-reply-1",
            sequence=4,
            previous_hash=records[-1]["event_hash"],
            event_kind="voice_reply",
            session_state="BOUND",
            session_ref=_ref("session", "demo"),
            revision=_ref("session-revision", "1"),
            source_type="discord_voice",
            speaker_track_ref=_ref("track", "reply"),
        )
        reply["egress"] = {
            "destination_ref": reply["source"]["channel_ref"],
            "consent_ref": reply["source"]["consent_ref"],
            "reply_artifact_ref": _ref("reply-artifact", "voice-reply-1"),
            "delivery_receipt_ref": _ref("delivery-receipt", "voice-reply-1"),
            "delivery_state": "VERIFIED",
            "raw_content_embedded": False,
        }
        records.append(reply)
        records = _rechain(records)
        self.assertEqual("LEDGER_VALID", ledger.validate_ledger(records)["result"])

        wrong = copy.deepcopy(records)
        wrong[-1]["egress"]["destination_ref"] = _ref("channel", "other")
        wrong = _rechain(wrong)
        self.assertIn("VOICE_REPLY_EGRESS_SCOPE_INVALID", ledger.validate_ledger(wrong)["reason_codes"])

    def test_runbook_covers_all_lifecycle_and_source_hooks_without_connectors(self) -> None:
        runbook = RUNBOOK.read_text(encoding="utf-8")
        for token in (
            "SessionStart/open",
            "incoming human message/voice segment",
            "tool/agent action",
            "decision confirmation/correction",
            "pre-compact",
            "session end/seal",
            "source update/delete/ACL loss",
            "Discord",
            "Notion",
            "GitHub",
            "Codex",
            "Claude",
            "Google Drive",
            "n8n",
            "compaction summary",
            "Open Knowledge Format (OKF) v0.2",
            "OKF_V0_2",
            "raw recognition text",
            "raw PCM/event JSON",
            "optional alignment",
            "SPEAKER_ATTRIBUTED_TRANSCRIPT",
            "forward-only DAG",
            "CONTENT_ARTIFACT_ALIAS",
            "corrected transcript sidecar",
            "Phoneme/G2P",
            "policy revision",
            "ENCRYPTED_COLD_ARCHIVE",
            "Archive backend selection is OPEN",
            "case-dependent",
            "auto-created Session",
            "Disposable Experiment Environment",
            "kill switch",
            "Luna-first",
            "Terra",
            "Goal Completion Loop",
            "Archive Target / Session Archive Vault",
            "COLD_ARCHIVE_TARGET_REQUIRED",
            "CANDIDATE_LIFECYCLE_REGRESSION",
            "REPLAY_SESSION_INVALID",
            "PROJECTION_LIMIT_EXCEEDED",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(token=token):
                self.assertIn(token, runbook)


if __name__ == "__main__":
    unittest.main()
