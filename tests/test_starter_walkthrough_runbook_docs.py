from pathlib import Path
import re
import unittest


from tests.document_contract_helpers import section, assert_links, shell_commands, assert_command_order, table_rows, assert_preview_boundary, headings, link_targets

ROOT = Path(__file__).resolve().parents[1]
WALKTHROUGH = ROOT / "docs" / "STARTER-WALKTHROUGH.md"


class StarterWalkthroughRunbookDocumentationTests(unittest.TestCase):
    def test_walkthrough_exposes_the_executable_smoke_before_initializer(self) -> None:
        document = WALKTHROUGH.read_text(encoding="utf-8")
        smoke = section(document, "実行確認-runbook-smoke")
        initializer = section(document, "1-initializerで作業copyを作る")
        self.assertLess(document.index(smoke), document.index(initializer))
        assert_links(self, WALKTHROUGH, smoke, ("SCHEMA-VALIDATOR-MATRIX.md", "../tests/test_public_starter_runbook_smoke.py"))
        for prefix, language in (("python", "powershell"), ("python3", "bash")):
            with self.subTest(shell=language):
                assert_command_order(self, smoke, (f"{prefix} -S -B tools/smoke_company_pack_review_chain.py",
                                     f"{prefix} -m unittest tests.test_public_starter_runbook_smoke -v"), language)
                self.assertFalse(any("pytest" in command for command in shell_commands(smoke, language)))
        for state in ("CANDIDATE_FOR_GOVERNED_REVIEW", "MATCH", "CUSTOMIZATION_REQUIRED", "BUNDLE_REFUSED"):
            self.assertIn(state, smoke)

    def test_walkthrough_keeps_current_preview_boundary_explicit(self) -> None:
        smoke = section(WALKTHROUGH.read_text(encoding="utf-8"), "実行確認-runbook-smoke")
        assert_preview_boundary(self, smoke, ("Human approval", "runtime", "Promotion", "Current Truth", "Public Beta GO"))

    def test_walkthrough_exposes_review_chain_artifact_map(self) -> None:
        surface = section(WALKTHROUGH.read_text(encoding="utf-8"), "review-chain-artifact-map")
        rows = table_rows(surface)
        self.assertEqual(len(rows[1:]), 4)
        for row, tools, state in zip(rows[1:],
                (("build_company_pack_review_bundle.py", "verify_company_pack_review_bundle.py"),
                 ("build_company_pack_review_request.py",),
                 ("build_company_pack_review_response.py", "verify_company_pack_review_response.py"),
                 ("build_company_pack_review_decision_handoff.py", "verify_company_pack_review_decision_handoff.py")),
                ("MATCH", "PENDING_AUTHORIZED_REVIEW", "ITEM_RESPONSES_MATCH_REQUEST", "DECISION_HANDOFF_MATCH")):
            with self.subTest(artifact=row[0]):
                self.assertEqual(len(row), 5)
                actual_tools = re.findall(r"`([a-z_]+\.py)`", row[2])
                self.assertEqual(actual_tools, list(tools))
                for tool in actual_tools:
                    self.assertTrue((ROOT / "tools" / tool).is_file())
                self.assertRegex(row[1], r"work/my-company-review-[a-z-]+\.json")
                self.assertIn(state, row[3])
                self.assertTrue(row[4])
        self.assertIn("decision: null", rows[-1][3])
        self.assertIn("selected_outcome: null", rows[-1][3])
        assert_links(self, WALKTHROUGH, surface)
        self.assertRegex(" ".join(surface.split()), r"none of these states is a Human Decision")
        assert_preview_boundary(self, surface, ("Promotion", "Current Truth", "Public Beta GO"))
