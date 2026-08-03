import copy
import json
import re
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "company-pack-protected-source-binding-receipt-candidate.schema.json"
RUNBOOK = ROOT / "docs" / "PROTECTED-SOURCE-BINDING-RECEIPT-CANDIDATE.md"

EXPECTED_EVIDENCE = {
    "source_authenticity",
    "source_completeness",
    "source_lineage",
    "identity_attribution",
    "access_consent_revocation",
    "retention_policy",
}

EXPECTED_CLAIMS = {
    "protected_runner_execution_verified",
    "runner_identity_verified",
    "runner_binary_verified",
    "runner_configuration_verified",
    "runner_signer_person_independence_verified",
    "detached_attestation_verified",
    "independent_receipt_verification_verified",
    "trusted_time_verified",
    "atomic_private_snapshot_verified",
    "source_record_locator_resolution_verified",
    "access_evidence_locator_resolution_verified",
    "immutable_source_version_verified",
    "source_authenticity_verified",
    "source_completeness_verified",
    "source_lineage_verified",
    "identity_or_attribution_verified",
    "access_or_consent_verified",
    "revocation_verified",
    "retention_enforced",
    "deletion_enforced",
    "deletion_receipt_verified",
    "replay_prevented",
    "r32_candidate_result_verified",
    "r30_projection_verified",
    "human_intent_confirmed",
    "human_decision_verified",
    "work_order_authority_granted",
    "promotion_verified",
    "current_truth_changed",
    "voice_runtime_verified",
    "discord_runtime_verified",
    "provider_transfer_authorized",
    "external_transfer_authorized",
    "final_human_go",
    "public_beta_go",
}

REVIEW_TRIGGERS = [
    "runner_policy_binary_or_configuration_change",
    "clock_source_policy_or_skew_change",
    "snapshot_transaction_isolation_or_artifact_change",
    "locator_resolution_or_immutable_version_change",
    "source_authenticity_completeness_or_lineage_evidence_change",
    "identity_or_attribution_evidence_change",
    "access_consent_or_revocation_evidence_change",
    "retention_policy_deadline_or_deletion_receipt_change",
    "replay_store_nonce_or_reservation_change",
    "r32_candidate_result_or_projection_digest_change",
    "detached_attestation_or_receipt_binding_change",
    "independent_reviewer_policy_or_result_change",
    "receipt_or_authority_expiry",
]


def binding(seed: str, byte_count: int = 64) -> dict:
    return {"sha256": seed * 64, "bytes": byte_count}


def evidence_item(name: str) -> dict:
    return {
        "evidence_ref": f"ref/protected-evidence/{name}",
        "evidence_binding": binding("e"),
        "covered_subject_ref": f"ref/protected-subject/{name}",
        "recorded_status": "RECORDED_UNVERIFIED",
    }


def locator_resolution(role: str, seed: str) -> dict:
    return {
        "role": role,
        "governed_locator_ref": f"ref/governed-locator/{role}",
        "immutable_version_ref": f"ref/immutable-version/{role}",
        "resolved_binding": binding(seed, 512),
        "resolver_policy_ref": "ref/resolver-policy/source-binding",
        "resolver_policy_binding": binding("9"),
        "resolution_receipt_ref": f"ref/resolution-receipt/{role}",
        "resolution_receipt_binding": binding("8"),
        "verification_status": "NOT_VERIFIED",
    }


def receipt_candidate(*, deletion_receipt: bool = False) -> dict:
    deletion_ref = "ref/deletion-receipt/source-binding" if deletion_receipt else None
    deletion_binding = binding("d") if deletion_receipt else None
    return {
        "kind": "company_pack_protected_source_binding_receipt_candidate",
        "version": "1.0",
        "status": "CANDIDATE_ONLY",
        "receipt_state": "PROTECTED_RECEIPT_RECORDED_UNVERIFIED",
        "receipt_id_ref": "ref/receipt/source-binding-01",
        "r32_contract": {
            "public_revision": "2" * 40,
            "verifier_binding": binding("a", 34792),
            "result_binding": binding("b", 4096),
            "reported_result": "SOURCE_BINDING_MATCH_POINT_IN_TIME",
            "r30_projection_digest_candidate": binding("c", 512),
            "verification_status": "NOT_VERIFIED",
        },
        "runner": {
            "runner_identity_ref": "ref/protected-runner/identity",
            "runner_policy_ref": "ref/protected-runner/policy",
            "runner_policy_binding": binding("1"),
            "executable_binding": binding("2", 8192),
            "configuration_binding": binding("3", 2048),
            "execution_environment_ref": "ref/protected-runner/environment",
            "verification_status": "NOT_VERIFIED",
        },
        "evaluation_clock": {
            "clock_source_ref": "ref/trusted-clock/source",
            "clock_policy_ref": "ref/trusted-clock/policy",
            "clock_policy_binding": binding("4"),
            "evaluation_time": "2026-08-03T20:30:00+09:00",
            "maximum_skew_seconds": 30,
            "clock_evidence_ref": "ref/trusted-clock/evidence",
            "clock_evidence_binding": binding("5"),
            "verification_status": "NOT_VERIFIED",
        },
        "private_snapshot": {
            "transaction_ref": "ref/private-snapshot/transaction",
            "isolation_policy_ref": "ref/private-snapshot/isolation-policy",
            "isolation_policy_binding": binding("6"),
            "opened_at": "2026-08-03T20:29:55+09:00",
            "sealed_at": "2026-08-03T20:30:00+09:00",
            "artifacts": {
                "source_record": binding("7", 1024),
                "source_content": binding("8", 8192),
                "access_projection_evidence": binding("9", 1024),
            },
            "snapshot_receipt_ref": "ref/private-snapshot/receipt",
            "snapshot_receipt_binding": binding("a"),
            "verification_status": "NOT_VERIFIED",
        },
        "locator_resolutions": [
            locator_resolution("source_record", "7"),
            locator_resolution("access_projection_evidence", "9"),
        ],
        "evidence_set": {name: evidence_item(name) for name in EXPECTED_EVIDENCE},
        "replay_reservation": {
            "nonce_sha256": "f" * 64,
            "store_ref": "ref/replay-store/source-binding",
            "store_binding": binding("b"),
            "reservation_receipt_ref": "ref/replay-reservation/receipt",
            "reservation_receipt_binding": binding("c"),
            "reserved_at": "2026-08-03T20:30:00+09:00",
            "verification_status": "NOT_VERIFIED",
        },
        "retention_and_deletion": {
            "policy_ref": "ref/retention/source-binding",
            "policy_binding": binding("d"),
            "covered_artifacts": [
                "source_record",
                "source_content",
                "access_projection_evidence",
                "protected_receipt",
            ],
            "retain_until": "2026-08-04T20:30:00+09:00",
            "deletion_trigger": "expiry_or_withdrawal",
            "deletion_status": (
                "RECEIPT_RECORDED_UNVERIFIED"
                if deletion_receipt
                else "NOT_DUE_REPORTED_UNVERIFIED"
            ),
            "deletion_receipt_ref": deletion_ref,
            "deletion_receipt_binding": deletion_binding,
            "verification_status": "NOT_VERIFIED",
        },
        "detached_attestation": {
            "payload_binding": binding("e", 4096),
            "signer_identity_ref": "ref/protected-signer/identity",
            "signer_policy_ref": "ref/protected-signer/policy",
            "signer_policy_binding": binding("f"),
            "signature_ref": "ref/protected-signature/source-binding",
            "signature_binding": binding("1"),
            "verification_status": "NOT_VERIFIED",
        },
        "independent_verification_handoff": {
            "reviewer_policy_ref": "ref/independent-reviewer/policy",
            "reviewer_policy_binding": binding("2"),
            "verification_result_ref": None,
            "verification_result_binding": None,
            "handoff_status": "INDEPENDENT_VERIFICATION_REQUIRED",
        },
        "receipt_binding_handoff": {
            "serialized_receipt_locator": None,
            "serialized_receipt_binding": None,
            "binding_status": "EXTERNAL_BINDING_REQUIRED",
        },
        "content_handling": {
            "source_content_embedded": False,
            "audio_embedded": False,
            "transcript_embedded": False,
            "private_projection_embedded": False,
            "candidate_visibility": "PRIVATE_GOVERNED_ONLY",
        },
        "recorded_at": "2026-08-03T20:30:01+09:00",
        "expires_at": "2026-08-03T21:30:01+09:00",
        "review_trigger": REVIEW_TRIGGERS,
        "claims": {name: False for name in EXPECTED_CLAIMS},
        "public_beta": "NO_GO_UNPUBLISHED",
    }


class ProtectedSourceBindingReceiptCandidateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema, format_checker=FormatChecker())

    def assert_valid(self, instance: dict) -> None:
        errors = list(self.validator.iter_errors(instance))
        self.assertEqual(errors, [], [error.message for error in errors])

    def assert_invalid(self, instance: dict, name: str) -> None:
        self.assertTrue(list(self.validator.iter_errors(instance)), name)

    def test_real_draft_2020_12_accepts_candidate_and_deletion_receipt_shapes(self) -> None:
        self.assert_valid(receipt_candidate())
        self.assert_valid(receipt_candidate(deletion_receipt=True))

    def test_hostile_overclaims_private_data_and_malformed_bindings_are_rejected(self) -> None:
        base = receipt_candidate()
        cases = {}

        mutated = copy.deepcopy(base)
        mutated["claims"]["atomic_private_snapshot_verified"] = True
        cases["atomic overclaim"] = mutated
        mutated = copy.deepcopy(base)
        mutated["approved"] = True
        cases["approval alias"] = mutated
        mutated = copy.deepcopy(base)
        mutated["runner"]["verification_status"] = "VERIFIED"
        cases["runner verified alias"] = mutated
        mutated = copy.deepcopy(base)
        mutated["evaluation_clock"]["verification_status"] = "VERIFIED"
        cases["clock verified alias"] = mutated
        mutated = copy.deepcopy(base)
        mutated["private_snapshot"]["verification_status"] = "VERIFIED"
        cases["snapshot verified alias"] = mutated
        mutated = copy.deepcopy(base)
        mutated["evidence_set"]["source_authenticity"]["recorded_status"] = "VERIFIED"
        cases["evidence verified alias"] = mutated
        mutated = copy.deepcopy(base)
        mutated["content_handling"]["source_content_embedded"] = True
        cases["source content embedded"] = mutated
        mutated = copy.deepcopy(base)
        mutated["content_handling"]["audio_embedded"] = True
        cases["audio embedded"] = mutated
        mutated = copy.deepcopy(base)
        mutated["content_handling"]["transcript_embedded"] = True
        cases["transcript embedded"] = mutated
        mutated = copy.deepcopy(base)
        mutated["content_handling"]["candidate_visibility"] = "PUBLIC"
        cases["public visibility"] = mutated
        mutated = copy.deepcopy(base)
        mutated["source_content"] = "private body"
        cases["raw source alias"] = mutated
        mutated = copy.deepcopy(base)
        mutated["evaluation_clock"]["evaluation_time"] = "2026-02-30T25:61:61+09:00"
        cases["invalid clock time"] = mutated
        mutated = copy.deepcopy(base)
        mutated["private_snapshot"]["artifacts"]["source_content"]["bytes"] = True
        cases["boolean bytes"] = mutated
        mutated = copy.deepcopy(base)
        mutated["runner"]["runner_identity_ref"] = "C:\\private\\runner"
        cases["private path ref"] = mutated
        mutated = copy.deepcopy(base)
        del mutated["private_snapshot"]["artifacts"]["access_projection_evidence"]
        cases["incomplete snapshot"] = mutated
        mutated = copy.deepcopy(base)
        mutated["locator_resolutions"].reverse()
        cases["locator role reorder"] = mutated
        mutated = copy.deepcopy(base)
        del mutated["evidence_set"]["access_consent_revocation"]
        cases["missing consent evidence"] = mutated
        mutated = copy.deepcopy(base)
        mutated["replay_reservation"]["reservation_receipt_ref"] = None
        cases["missing replay receipt"] = mutated
        mutated = copy.deepcopy(base)
        mutated["retention_and_deletion"]["deletion_receipt_ref"] = "ref/deletion/early"
        cases["early deletion receipt ref"] = mutated
        mutated = copy.deepcopy(base)
        mutated["retention_and_deletion"]["deletion_status"] = "RECEIPT_RECORDED_UNVERIFIED"
        cases["receipt state without receipt"] = mutated
        mutated = copy.deepcopy(receipt_candidate(deletion_receipt=True))
        mutated["retention_and_deletion"]["deletion_receipt_binding"] = None
        cases["receipt ref without binding"] = mutated
        mutated = copy.deepcopy(base)
        mutated["r32_contract"]["public_revision"] = "not-a-commit"
        cases["invalid public revision"] = mutated
        mutated = copy.deepcopy(base)
        mutated["r32_contract"]["reported_result"] = "REFUSED"
        cases["refusal with projection digest"] = mutated
        mutated = copy.deepcopy(base)
        mutated["review_trigger"][0], mutated["review_trigger"][1] = (
            mutated["review_trigger"][1],
            mutated["review_trigger"][0],
        )
        cases["review trigger reorder"] = mutated
        mutated = copy.deepcopy(base)
        mutated["independent_verification_handoff"]["verification_result_ref"] = (
            "ref/forged-independent-result"
        )
        cases["forged independent result"] = mutated
        mutated = copy.deepcopy(base)
        del mutated["independent_verification_handoff"]
        cases["missing independent verification handoff"] = mutated

        for name, instance in cases.items():
            with self.subTest(name=name):
                self.assert_invalid(instance, name)

    def test_refused_r32_result_requires_no_projection_digest(self) -> None:
        instance = receipt_candidate()
        instance["r32_contract"]["reported_result"] = "REFUSED"
        instance["r32_contract"]["r30_projection_digest_candidate"] = None
        self.assert_valid(instance)

    def test_schema_closes_every_authority_runtime_and_go_claim(self) -> None:
        claims = self.schema["$defs"]["claims"]
        self.assertEqual(claims["additionalProperties"], False)
        self.assertEqual(set(claims["required"]), EXPECTED_CLAIMS)
        self.assertEqual(set(claims["properties"]), EXPECTED_CLAIMS)
        self.assertTrue(all(spec["const"] is False for spec in claims["properties"].values()))
        self.assertEqual(self.schema["properties"]["status"]["const"], "CANDIDATE_ONLY")
        self.assertEqual(
            self.schema["properties"]["public_beta"]["const"],
            "NO_GO_UNPUBLISHED",
        )

    def test_schema_requires_complete_private_evidence_roles_without_raw_bodies(self) -> None:
        evidence = self.schema["$defs"]["evidence_set"]
        self.assertEqual(set(evidence["required"]), EXPECTED_EVIDENCE)
        self.assertEqual(set(evidence["properties"]), EXPECTED_EVIDENCE)
        handling = self.schema["$defs"]["content_handling"]
        for key in (
            "source_content_embedded",
            "audio_embedded",
            "transcript_embedded",
            "private_projection_embedded",
        ):
            self.assertEqual(handling["properties"][key]["const"], False)
        self.assertEqual(
            handling["properties"]["candidate_visibility"]["const"],
            "PRIVATE_GOVERNED_ONLY",
        )
        for forbidden in (
            "source_content",
            "audio",
            "transcript",
            "prompt",
            "model_output",
            "human_decision",
            "work_order",
        ):
            self.assertNotIn(forbidden, self.schema["properties"])

    def test_receipt_handoff_prevents_self_binding_claim(self) -> None:
        handoff = self.schema["$defs"]["receipt_binding_handoff"]
        self.assertEqual(handoff["properties"]["serialized_receipt_locator"]["type"], "null")
        self.assertEqual(handoff["properties"]["serialized_receipt_binding"]["type"], "null")
        self.assertEqual(
            handoff["properties"]["binding_status"]["const"],
            "EXTERNAL_BINDING_REQUIRED",
        )

    def test_independent_verification_is_required_but_not_preclaimed(self) -> None:
        self.assertIn("independent_verification_handoff", self.schema["required"])
        handoff = self.schema["$defs"]["independent_verification_handoff"]
        self.assertEqual(handoff["properties"]["verification_result_ref"]["type"], "null")
        self.assertEqual(
            handoff["properties"]["verification_result_binding"]["type"],
            "null",
        )
        self.assertEqual(
            handoff["properties"]["handoff_status"]["const"],
            "INDEPENDENT_VERIFICATION_REQUIRED",
        )

    def test_documented_workflow_steps_are_strictly_numbered(self) -> None:
        cases = (
            (ROOT / "docs" / "CUSTOMIZATION-CHECKLIST.md", "## Ideal use"),
            (ROOT / "docs" / "TEMPLATE-GUIDE.md", "## 現時点での使い方"),
        )
        for path, heading in cases:
            text = path.read_text(encoding="utf-8")
            section = text.split(heading, 1)[1].split("\n## ", 1)[0]
            numbers = [
                int(match.group(1))
                for match in re.finditer(r"(?m)^(\d+)\. ", section)
            ]
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertEqual(numbers, list(range(1, len(numbers) + 1)))

    def test_runbook_states_ideal_current_and_unverified_boundaries(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        for required in (
            "Ideal use",
            "Current implementation",
            "schema-only",
            "PRIVATE_GOVERNED_ONLY",
            "RECORDED_UNVERIFIED",
            "NOT_VERIFIED",
            "atomic",
            "trusted clock",
            "replay",
            "deletion receipt",
            "protected runner",
            "NO_GO_UNPUBLISHED",
        ):
            self.assertIn(required, text)

    def test_contract_is_discoverable_from_company_pack_entry_surfaces(self) -> None:
        paths = (
            ROOT / "README.md",
            ROOT / "ROADMAP.md",
            ROOT / "STATUS.md",
            ROOT / "docs" / "CUSTOMIZATION-CHECKLIST.md",
            ROOT / "docs" / "SOURCE-BINDING-VERIFIER-CANDIDATE.md",
            ROOT / "docs" / "SOURCE-RECORD-INSTANCE.md",
            ROOT / "docs" / "STARTER-WALKTHROUGH.md",
            ROOT / "docs" / "TEMPLATE-GUIDE.md",
            ROOT / "docs" / "VALIDATION.md",
            ROOT / "examples" / "company-starter" / "README.md",
        )
        for path in paths:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIn(
                    "PROTECTED-SOURCE-BINDING-RECEIPT-CANDIDATE.md",
                    path.read_text(encoding="utf-8"),
                )


if __name__ == "__main__":
    unittest.main()
