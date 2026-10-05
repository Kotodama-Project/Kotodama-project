from pathlib import Path
import unittest


from tests.document_contract_helpers import section, assert_links, shell_commands, assert_command_order, table_rows, assert_preview_boundary, headings, link_targets

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "docs" / "OVERVIEW.md"


class ReadmeRunbookSmokeEntryTests(unittest.TestCase):
    def test_readme_links_executable_smoke_before_quick_start_commands(self) -> None:
        document = README.read_text(encoding="utf-8")
        required = (
            "### 実行確認: Runbook smoke",
            "[Starter Walkthrough](STARTER-WALKTHROUGH.md)",
            "[test_public_starter_runbook_smoke.py](../tests/test_public_starter_runbook_smoke.py)",
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

        smoke = document.index("### 実行確認: Runbook smoke")
        quick_start = document.index("## Quick Start — Company starter を試す")
        self.assertLess(smoke, quick_start)
        self.assertTrue((ROOT / "docs" / "STARTER-WALKTHROUGH.md").is_file())
        self.assertTrue((ROOT / "tests" / "test_public_starter_runbook_smoke.py").is_file())

    def test_readme_smoke_entry_keeps_preview_boundary_explicit(self) -> None:
        surface = section(README.read_text(encoding="utf-8"), "実行確認-runbook-smoke")
        assert_preview_boundary(self, surface, ("Human approval", "runtime", "Promotion", "Current Truth", "Public Beta GO"))
        assert_links(self, README, surface, ("STARTER-WALKTHROUGH.md", "../tests/test_public_starter_runbook_smoke.py"))
