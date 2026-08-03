import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "company-pack-decision-record-candidate.schema.json"
RUNBOOK = ROOT / "docs" / "DECISION-RECORD-CANDIDATE.md"


def candidate_instances(schema: dict) -> tuple[dict, dict]:
    claims = {key: False for key in schema["$defs"]["claims"]["properties"]}
    binding = {"sha256": "a" * 64, "bytes": 1}
    pending = {
        "kind": "company_pack_decision_record_candidate",
        "version": "1.0",
        "status": "CANDIDATE_ONLY",
        "decision_state": "HUMAN_DECISION_REQUIRED",
        "decision_candidate_id": "decision-candidate-01",
        "review_chain": {
            "handoff": {
                "locator": "ref/handoff",
                "binding": binding,
                "expected_status": "CANDIDATE_DECISION_HANDOFF",
            },
            "handoff_verification": {
                "locator": "ref/handoff-verification",
                "binding": binding,
                "expected_status": "DECISION_HANDOFF_MATCH",
            },
        },
        "intent_candidate_binding": {
            "locator": "ref/intent-candidate",
            "binding": binding,
            "candidate_revision": "candidate-01",
            "schema_status": "NOT_VERIFIED",
        },
        "human_outcome": None,
        "reviewer_evidence": None,
        "decision_maker_evidence": None,
        "scope": None,
        "reason": None,
        "reviewed_at": None,
        "decided_at": None,
        "proposed_effective_at": None,
        "expires_at": None,
        "review_trigger": None,
        "unresolved_evidence": {
            "state": "EVIDENCE_REQUIRED",
            "required_count": 5,
            "refs": [],
        },
        "retention_policy_ref": None,
        "claims": claims,
        "public_beta": "NO_GO_UNPUBLISHED",
    }
    entered = copy.deepcopy(pending)
    entered.update(
        {
            "decision_state": "HUMAN_OUTCOME_ENTERED_UNVERIFIED",
            "human_outcome": {
                "state": "UNVERIFIED_HUMAN_ENTRY",
                "selected_outcome": "accept",
                "entry_evidence_ref": "ref/human-entry",
                "entered_at": "2026-08-03T15:00:00+09:00",
            },
            "reviewer_evidence": {
                "identity_ref": "ref/reviewer",
                "role": "reviewer-role",
                "authority_ref": "ref/reviewer-authority",
                "independence_ref": "ref/independence",
            },
            "decision_maker_evidence": {
                "identity_ref": "ref/decision-maker",
                "role": "decision-maker-role",
                "authority_ref": "ref/decision-authority",
            },
            "scope": {"in_scope": ["candidate revision"], "out_of_scope": ["runtime"]},
            "reason": "Unverified Human entry for schema validation only.",
            "reviewed_at": "2026-08-03T15:00:00+09:00",
            "decided_at": "2026-08-03T15:01:00+09:00",
            "proposed_effective_at": "2026-08-03T15:02:00+09:00",
            "expires_at": "2026-08-03T16:00:00+09:00",
            "review_trigger": [
                "intent_candidate_digest_drift",
                "review_handoff_digest_drift",
                "evidence_change",
                "scope_change",
                "authority_or_evidence_expiry",
                "retention_policy_change",
            ],
            "unresolved_evidence": {
                "state": "EVIDENCE_REQUIRED",
                "required_count": 5,
                "refs": [f"ref/evidence-{index}" for index in range(1, 6)],
            },
            "retention_policy_ref": "ref/retention-policy",
        }
    )
    return pending, entered


class CompanyPackDecisionRecordCandidateContractTests(unittest.TestCase):
    def test_real_draft_2020_12_validation_accepts_only_candidate_shapes(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        pending, entered = candidate_instances(schema)

        for name, instance in (("pending", pending), ("entered", entered)):
            with self.subTest(valid=name):
                self.assertEqual(list(validator.iter_errors(instance)), [])

        hostile = {}
        mutated = copy.deepcopy(entered)
        mutated["claims"]["candidate_bound_human_decision_verified"] = True
        hostile["true_claim"] = mutated
        mutated = copy.deepcopy(entered)
        mutated["unresolved_evidence"]["refs"].pop()
        hostile["four_evidence_refs"] = mutated
        mutated = copy.deepcopy(entered)
        mutated["effective_at"] = mutated["proposed_effective_at"]
        hostile["effective_at_extra"] = mutated
        mutated = copy.deepcopy(entered)
        mutated["status"] = "APPROVED"
        hostile["approved_status"] = mutated
        mutated = copy.deepcopy(entered)
        mutated["outcome_count"] = 46
        hostile["outcome_count_injection"] = mutated
        mutated = copy.deepcopy(entered)
        mutated["review_chain"]["handoff"]["expected_status"] = "APPROVED"
        hostile["forged_handoff_status"] = mutated
        mutated = copy.deepcopy(entered)
        mutated["intent_candidate_binding"]["schema_status"] = "VERIFIED"
        hostile["intent_schema_overclaim"] = mutated
        mutated = copy.deepcopy(entered)
        del mutated["decision_maker_evidence"]["authority_ref"]
        hostile["missing_authority"] = mutated
        mutated = copy.deepcopy(pending)
        mutated["human_outcome"] = entered["human_outcome"]
        hostile["pending_with_outcome"] = mutated
        mutated = copy.deepcopy(entered)
        mutated["decided_at"] = "2026-02-30T25:61:61+09:00"
        hostile["invalid_calendar_timestamp"] = mutated
        mutated = copy.deepcopy(entered)
        mutated["review_chain"]["handoff"]["binding"]["bytes"] = True
        hostile["boolean_byte_size"] = mutated

        for name, instance in hostile.items():
            with self.subTest(invalid=name):
                self.assertNotEqual(list(validator.iter_errors(instance)), [])

    def test_real_validator_is_a_declared_test_only_dependency(self) -> None:
        requirement = (ROOT / "requirements-test.txt").read_text(encoding="utf-8")
        self.assertEqual(requirement.strip(), "jsonschema[format-nongpl]==4.26.0")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("python -m pip install -r requirements-test.txt", readme)

    def test_schema_closes_every_authority_and_execution_claim(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(schema["additionalProperties"], False)
        self.assertEqual(schema["properties"]["kind"]["const"], "company_pack_decision_record_candidate")
        self.assertEqual(schema["properties"]["status"]["const"], "CANDIDATE_ONLY")
        self.assertEqual(schema["properties"]["public_beta"]["const"], "NO_GO_UNPUBLISHED")
        self.assertEqual(
            schema["properties"]["decision_state"]["enum"],
            ["HUMAN_DECISION_REQUIRED", "HUMAN_OUTCOME_ENTERED_UNVERIFIED"],
        )
        claims = schema["$defs"]["claims"]
        self.assertEqual(claims["additionalProperties"], False)
        self.assertTrue(
            all(value["const"] is False for value in claims["properties"].values())
        )
        self.assertEqual(len(claims["properties"]), 18)
        for forbidden in (
            "approved",
            "verified",
            "effective_at",
            "promotion",
            "current_truth",
            "execution_authority",
        ):
            self.assertNotIn(forbidden, schema["properties"])

    def test_schema_keeps_sources_and_human_entry_structurally_separate(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        review_chain = schema["$defs"]["review_chain"]
        self.assertEqual(review_chain["additionalProperties"], False)
        self.assertEqual(
            review_chain["required"], ["handoff", "handoff_verification"]
        )
        intent = schema["$defs"]["intent_candidate_binding"]
        self.assertEqual(intent["additionalProperties"], False)
        self.assertEqual(intent["properties"]["schema_status"]["const"], "NOT_VERIFIED")
        outcome = schema["$defs"]["human_outcome"]
        self.assertEqual(outcome["additionalProperties"], False)
        self.assertEqual(
            outcome["properties"]["selected_outcome"]["enum"],
            ["accept", "request_changes", "reject"],
        )
        unresolved = schema["properties"]["unresolved_evidence"]
        self.assertEqual(unresolved["additionalProperties"], False)
        self.assertEqual(unresolved["properties"]["required_count"]["const"], 5)
        self.assertEqual(unresolved["properties"]["refs"]["maxItems"], 5)
        self.assertEqual(
            schema["properties"]["proposed_effective_at"]["oneOf"][0]["type"],
            "null",
        )

    def test_state_conditions_never_create_a_verified_decision(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        encoded = json.dumps(schema, ensure_ascii=False)
        self.assertIn("HUMAN_DECISION_REQUIRED", encoded)
        self.assertIn("UNVERIFIED_HUMAN_ENTRY", encoded)
        self.assertIn("EVIDENCE_REQUIRED", encoded)
        self.assertNotIn('"const": true', encoded)
        self.assertNotIn("DECISION_VERIFIED", encoded)
        self.assertNotIn("APPROVED", encoded)

    def test_runbook_is_schema_only_and_blocks_a_future_builder(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        for required in (
            "Ideal use",
            "Current implementation",
            "schema-only",
            "builder",
            "verifier",
            "NOT_VERIFIED",
            "HUMAN_OUTCOME_ENTERED_UNVERIFIED",
            "46件",
            "5件",
            "generic Decision Record",
            "NO_GO_UNPUBLISHED",
        ):
            self.assertIn(required, text)
        discoverability_files = (
            ROOT / "README.md",
            ROOT / "docs" / "REVIEW-DECISION-HANDOFF.md",
            ROOT / "docs" / "REVIEW-WORKFLOW.md",
            ROOT / "docs" / "STARTER-WALKTHROUGH.md",
            ROOT / "docs" / "TEMPLATE-GUIDE.md",
            ROOT / "docs" / "VALIDATION.md",
            ROOT / "docs" / "CUSTOMIZATION-CHECKLIST.md",
            ROOT / "examples" / "company-starter" / "README.md",
        )
        for path in discoverability_files:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIn(
                    "DECISION-RECORD-CANDIDATE.md", path.read_text(encoding="utf-8")
                )


if __name__ == "__main__":
    unittest.main()
