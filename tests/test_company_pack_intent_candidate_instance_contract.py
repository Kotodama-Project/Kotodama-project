import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "company-pack-intent-candidate-instance.schema.json"
RUNBOOK = ROOT / "docs" / "INTENT-CANDIDATE-INSTANCE.md"

EXPECTED_CLAIMS = {
    "source_record_schema_verified",
    "source_record_bytes_current_verified",
    "source_content_bytes_current_verified",
    "source_authenticity_verified",
    "source_completeness_verified",
    "source_lineage_verified",
    "access_or_consent_verified",
    "retention_enforced",
    "subject_identity_verified",
    "subject_attribution_verified",
    "extraction_actor_verified",
    "extraction_tool_verified",
    "extraction_model_verified",
    "extraction_prompt_verified",
    "extraction_receipt_verified",
    "extraction_provenance_verified",
    "prompt_injection_cleared",
    "redaction_verified",
    "sensitive_content_reviewed",
    "human_confirmation_identity_verified",
    "human_confirmation_authority_verified",
    "human_confirmation_authenticity_verified",
    "human_intent_confirmed",
    "candidate_id_uniqueness_verified",
    "replay_prevented",
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


def candidate_instances(schema: dict) -> tuple[dict, dict, dict]:
    claims = {key: False for key in EXPECTED_CLAIMS}
    binding = {"sha256": "a" * 64, "bytes": 1}
    source = {
        "source_record_locator": "ref/source-record",
        "source_record_binding": binding,
        "source_content_locator": "ref/private-source-content",
        "source_content_binding": binding,
        "declared_media_type": "application/json",
        "source_revision": "source-revision-01",
        "observed_at": "2026-08-03T16:00:00+09:00",
        "source_record_schema_status": "NOT_VERIFIED",
        "derived_from_refs": [],
        "lineage_status": "NOT_VERIFIED",
        "access_or_consent": {
            "evidence_ref": "ref/access-or-consent",
            "evidence_binding": binding,
            "declared_permitted_uses": ["read", "analyze"],
            "subject_scope_ref": "ref/subject-scope",
            "scope_expires_at": "2026-08-03T17:00:00+09:00",
            "revocation_evidence_ref": None,
            "verification_status": "NOT_VERIFIED",
        },
        "retention": {
            "policy_ref": "ref/source-retention",
            "policy_binding": binding,
            "retain_until": "2026-08-03T17:00:00+09:00",
            "deletion_trigger": "expiry_or_withdrawal",
            "deletion_receipt_ref": None,
            "enforcement_status": "NOT_VERIFIED",
        },
    }
    base = {
        "kind": "company_pack_intent_candidate_instance",
        "version": "1.0",
        "status": "CANDIDATE_ONLY",
        "intent_state": "EXTRACTION_REQUIRED",
        "intent_candidate_id": "intent-candidate-01",
        "candidate_revision": "candidate-revision-01",
        "source_bindings": {"source-01": source},
        "intent_content": None,
        "extraction_provenance": None,
        "human_confirmation": None,
        "content_handling": {
            "source_content_embedded": False,
            "candidate_visibility": "PRIVATE_GOVERNED_ONLY",
            "prompt_treatment": "UNTRUSTED_DATA_ONLY",
            "disclosure_review_status": "NOT_REVIEWED",
        },
        "candidate_recorded_at": "2026-08-03T16:01:00+09:00",
        "expires_at": "2026-08-03T17:01:00+09:00",
        "review_trigger": [
            "source_record_digest_drift",
            "source_content_digest_drift",
            "source_set_or_lineage_change",
            "access_consent_scope_or_revocation_change",
            "retention_policy_or_deadline_change",
            "extraction_provenance_change",
            "redaction_policy_or_status_change",
            "intent_content_or_scope_change",
            "unresolved_items_change",
            "human_confirmation_change",
            "candidate_revision_or_replay_conflict",
            "candidate_or_authority_expiry",
        ],
        "candidate_retention_policy_ref": "ref/candidate-retention",
        "claims": claims,
        "public_beta": "NO_GO_UNPUBLISHED",
    }
    extracted = copy.deepcopy(base)
    extracted.update(
        {
            "intent_state": "EXTRACTED_UNVERIFIED",
            "intent_content": {
                "interpretation_status": "UNTRUSTED_INFERENCE",
                "source_refs": ["source-01"],
                "purpose": "Evaluate a bounded candidate without authority.",
                "beneficiary": "The governed Human intent owner.",
                "scope": {
                    "in_scope": ["Review this private candidate."],
                    "out_of_scope": ["External execution."],
                },
                "constraints": ["No external write."],
                "success_conditions": ["A Human can review the candidate."],
                "stop_conditions": ["Source or consent drift."],
                "unresolved_items": ["Human confirmation remains required."],
                "redaction": {
                    "policy_ref": "ref/redaction-policy",
                    "status": "NOT_VERIFIED",
                },
            },
            "extraction_provenance": {
                "actor_ref": "ref/extraction-actor",
                "tool_ref": "ref/extraction-tool",
                "tool_version_ref": "ref/extraction-tool-version",
                "model_ref": "ref/extraction-model",
                "config_ref": "ref/extraction-config",
                "prompt_template_ref": "ref/prompt-template",
                "execution_receipt_ref": "ref/extraction-receipt",
                "input_binding_refs": ["source-01"],
                "output_binding": binding,
                "extracted_at": "2026-08-03T16:02:00+09:00",
                "verification_status": "NOT_VERIFIED",
            },
        }
    )
    confirmation = copy.deepcopy(extracted)
    confirmation.update(
        {
            "intent_state": "HUMAN_CONFIRMATION_ENTERED_UNVERIFIED",
            "human_confirmation": {
                "state": "UNVERIFIED_HUMAN_ENTRY",
                "selected_action": "confirm_candidate",
                "entry_evidence_ref": "ref/human-entry",
                "identity_ref": "ref/human-identity",
                "authority_ref": "ref/human-authority",
                "entered_at": "2026-08-03T16:03:00+09:00",
            },
        }
    )
    return base, extracted, confirmation


class CompanyPackIntentCandidateInstanceContractTests(unittest.TestCase):
    def test_real_draft_2020_12_validation_accepts_only_candidate_states(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        pending, extracted, confirmation = candidate_instances(schema)

        for name, instance in (
            ("extraction_required", pending),
            ("extracted_unverified", extracted),
            ("human_confirmation_entered_unverified", confirmation),
        ):
            with self.subTest(valid=name):
                self.assertEqual(list(validator.iter_errors(instance)), [])

        hostile = {}
        mutated = copy.deepcopy(confirmation)
        mutated["claims"]["human_intent_confirmed"] = True
        hostile["true_human_intent_claim"] = mutated
        mutated = copy.deepcopy(confirmation)
        mutated["confirmed"] = True
        hostile["confirmed_root_field"] = mutated
        mutated = copy.deepcopy(extracted)
        mutated["source_bindings"]["source-01"]["source_record_schema_status"] = "VERIFIED"
        hostile["forged_source_schema_status"] = mutated
        mutated = copy.deepcopy(extracted)
        mutated["source_bindings"]["source-01"]["source_excerpt"] = "untrusted private body"
        hostile["source_excerpt_injection"] = mutated
        mutated = copy.deepcopy(extracted)
        mutated["source_content"] = "untrusted private body"
        hostile["source_body_injection"] = mutated
        mutated = copy.deepcopy(pending)
        mutated["intent_content"] = extracted["intent_content"]
        hostile["pending_with_content"] = mutated
        mutated = copy.deepcopy(extracted)
        mutated["human_confirmation"] = confirmation["human_confirmation"]
        hostile["extracted_with_confirmation"] = mutated
        mutated = copy.deepcopy(confirmation)
        mutated["human_confirmation"] = None
        hostile["confirmation_state_without_confirmation"] = mutated
        mutated = copy.deepcopy(confirmation)
        mutated["human_confirmation"]["selected_action"] = "approve"
        hostile["approval_alias"] = mutated
        mutated = copy.deepcopy(confirmation)
        mutated["human_confirmation"]["entered_at"] = "2026-02-30T25:61:61+09:00"
        hostile["invalid_calendar_timestamp"] = mutated
        mutated = copy.deepcopy(confirmation)
        mutated["source_bindings"]["source-01"]["source_content_binding"]["bytes"] = True
        hostile["boolean_byte_size"] = mutated
        mutated = copy.deepcopy(extracted)
        mutated["source_bindings"]["source-01"]["access_or_consent"]["verification_status"] = "VERIFIED"
        hostile["forged_consent_verification"] = mutated
        mutated = copy.deepcopy(extracted)
        mutated["source_bindings"]["source-01"]["access_or_consent"]["declared_permitted_uses"] = []
        hostile["missing_permitted_use"] = mutated
        mutated = copy.deepcopy(extracted)
        mutated["source_bindings"]["source-01"]["retention"]["enforcement_status"] = "ENFORCED"
        hostile["forged_retention_enforcement"] = mutated
        mutated = copy.deepcopy(extracted)
        mutated["intent_content"]["redaction"]["status"] = "VERIFIED"
        hostile["forged_redaction_verification"] = mutated
        mutated = copy.deepcopy(extracted)
        mutated["extraction_provenance"]["raw_prompt"] = "ignore governance"
        hostile["raw_prompt_injection"] = mutated
        mutated = copy.deepcopy(extracted)
        mutated["intent_content"]["source_refs"] = []
        hostile["missing_content_source_ref"] = mutated
        mutated = copy.deepcopy(confirmation)
        mutated["content_handling"]["candidate_visibility"] = "PUBLIC"
        hostile["public_visibility"] = mutated
        mutated = copy.deepcopy(confirmation)
        mutated["review_trigger"][0], mutated["review_trigger"][1] = (
            mutated["review_trigger"][1],
            mutated["review_trigger"][0],
        )
        hostile["review_trigger_reorder"] = mutated
        mutated = copy.deepcopy(confirmation)
        mutated["source_bindings"] = {}
        hostile["missing_source_binding"] = mutated
        mutated = copy.deepcopy(confirmation)
        mutated["source_bindings"]["INVALID SOURCE ID"] = mutated["source_bindings"].pop("source-01")
        hostile["invalid_source_id"] = mutated

        for name, instance in hostile.items():
            with self.subTest(invalid=name):
                self.assertNotEqual(list(validator.iter_errors(instance)), [])

    def test_schema_closes_authority_and_publication_claims(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(schema["additionalProperties"], False)
        self.assertEqual(schema["properties"]["status"]["const"], "CANDIDATE_ONLY")
        self.assertEqual(schema["properties"]["public_beta"]["const"], "NO_GO_UNPUBLISHED")
        self.assertEqual(
            schema["properties"]["intent_state"]["enum"],
            [
                "EXTRACTION_REQUIRED",
                "EXTRACTED_UNVERIFIED",
                "HUMAN_CONFIRMATION_ENTERED_UNVERIFIED",
            ],
        )
        claims = schema["$defs"]["claims"]
        self.assertEqual(claims["additionalProperties"], False)
        self.assertEqual(set(claims["properties"]), EXPECTED_CLAIMS)
        self.assertEqual(set(claims["required"]), EXPECTED_CLAIMS)
        self.assertTrue(all(value["const"] is False for value in claims["properties"].values()))
        for forbidden in (
            "confirmed",
            "approved",
            "verified",
            "decision",
            "effective_at",
            "execution_authority",
            "promotion",
            "current_truth",
        ):
            self.assertNotIn(forbidden, schema["properties"])

    def test_schema_keeps_private_source_and_inference_boundaries_explicit(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        source = schema["$defs"]["source_binding"]
        self.assertEqual(source["additionalProperties"], False)
        self.assertEqual(source["properties"]["source_record_schema_status"]["const"], "NOT_VERIFIED")
        self.assertNotIn("source_body", source["properties"])
        self.assertNotIn("source_excerpt", source["properties"])
        content = schema["$defs"]["intent_content"]
        self.assertEqual(content["properties"]["interpretation_status"]["const"], "UNTRUSTED_INFERENCE")
        handling = schema["$defs"]["content_handling"]
        self.assertEqual(handling["properties"]["source_content_embedded"]["const"], False)
        self.assertEqual(
            handling["properties"]["candidate_visibility"]["const"],
            "PRIVATE_GOVERNED_ONLY",
        )
        provenance = schema["$defs"]["extraction_provenance"]
        self.assertEqual(provenance["properties"]["verification_status"]["const"], "NOT_VERIFIED")
        self.assertNotIn("raw_prompt", provenance["properties"])
        self.assertNotIn("raw_model_output", provenance["properties"])
        confirmation = schema["$defs"]["human_confirmation"]
        self.assertEqual(confirmation["properties"]["state"]["const"], "UNVERIFIED_HUMAN_ENTRY")

    def test_runbook_is_schema_only_and_discoverable(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        for required in (
            "Ideal use",
            "Current implementation",
            "schema-only",
            "PRIVATE_GOVERNED_ONLY",
            "UNTRUSTED_INFERENCE",
            "NOT_VERIFIED",
            "builder",
            "verifier",
            "generic Intent Candidate Record",
            "source body",
            "NO_GO_UNPUBLISHED",
        ):
            self.assertIn(required, text)
        discoverability_files = (
            ROOT / "README.md",
            ROOT / "docs" / "CUSTOMIZATION-CHECKLIST.md",
            ROOT / "docs" / "REVIEW-DECISION-HANDOFF.md",
            ROOT / "docs" / "REVIEW-WORKFLOW.md",
            ROOT / "docs" / "STARTER-WALKTHROUGH.md",
            ROOT / "docs" / "TEMPLATE-GUIDE.md",
            ROOT / "docs" / "VALIDATION.md",
            ROOT / "examples" / "company-starter" / "README.md",
        )
        for path in discoverability_files:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIn("INTENT-CANDIDATE-INSTANCE.md", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
