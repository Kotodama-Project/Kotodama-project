from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WALKTHROUGH = ROOT / "docs" / "STARTER-WALKTHROUGH.md"


class StarterWalkthroughRunbookDocumentationTests(unittest.TestCase):
    def test_walkthrough_exposes_the_executable_smoke_before_initializer(self) -> None:
        document = WALKTHROUGH.read_text(encoding="utf-8")
        required = (
            "## 実行確認: Runbook smoke",
            "[Schema / Validator / Test Matrix](SCHEMA-VALIDATOR-MATRIX.md)",
            "[test_public_starter_runbook_smoke.py](../tests/test_public_starter_runbook_smoke.py)",
            "python -m unittest tests.test_public_starter_runbook_smoke -v",
            "python3 -m unittest tests.test_public_starter_runbook_smoke -v",
            "guided path",
            "CANDIDATE_FOR_GOVERNED_REVIEW",
            "MATCH",
            "CUSTOMIZATION_REQUIRED",
            "BUNDLE_REFUSED",
            "NO_GO_UNPUBLISHED",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, document)

        smoke = document.index("## 実行確認: Runbook smoke")
        initializer = document.index("## 1. initializerで作業copyを作る")
        self.assertLess(smoke, initializer)

        for relative in (
            "../tests/test_public_starter_runbook_smoke.py",
            "SCHEMA-VALIDATOR-MATRIX.md",
        ):
            with self.subTest(link=relative):
                self.assertTrue((WALKTHROUGH.parent / relative).is_file())

        self.assertNotIn(
            "python -m pytest tests/test_public_starter_runbook_smoke.py -q",
            document,
        )
        self.assertNotIn(
            "python3 -m pytest tests/test_public_starter_runbook_smoke.py -q",
            document,
        )

    def test_walkthrough_keeps_current_preview_boundary_explicit(self) -> None:
        document = WALKTHROUGH.read_text(encoding="utf-8")
        boundary_start = document.index("## 実行確認: Runbook smoke")
        boundary_end = document.index("## 1. initializerで作業copyを作る", boundary_start)
        section = document[boundary_start:boundary_end]
        self.assertIn("read-only/candidate-only", section)
        self.assertIn("Human approval", section)
        self.assertIn("runtime", section)
        self.assertIn("Promotion", section)
        self.assertIn("Current Truth", section)
        self.assertIn("Public Beta", section)
        self.assertNotIn("Public Beta GO: true", section)

    def test_walkthrough_exposes_review_chain_artifact_map(self) -> None:
        document = WALKTHROUGH.read_text(encoding="utf-8")
        required = (
            "## Review-chain artifact map",
            "before or after the external-free smoke",
            "Review Bundle",
            "Review Request",
            "Review Response",
            "Review Decision Handoff",
            "build_company_pack_review_bundle.py",
            "verify_company_pack_review_bundle.py",
            "build_company_pack_review_request.py",
            "build_company_pack_review_response.py",
            "verify_company_pack_review_response.py",
            "build_company_pack_review_decision_handoff.py",
            "verify_company_pack_review_decision_handoff.py",
            "MATCH",
            "PENDING_AUTHORIZED_REVIEW",
            "ITEM_RESPONSES_MATCH_REQUEST",
            "DECISION_HANDOFF_MATCH",
            "decision: null",
            "selected_outcome: null",
            "Human Decision",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, document)
