import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "company-pack-decision-record-candidate.schema.json"
RUNBOOK = ROOT / "docs" / "DECISION-RECORD-CANDIDATE.md"


class CompanyPackDecisionRecordCandidateContractTests(unittest.TestCase):
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
