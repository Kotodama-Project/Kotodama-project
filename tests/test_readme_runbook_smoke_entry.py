from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


class ReadmeRunbookSmokeEntryTests(unittest.TestCase):
    def test_readme_links_executable_smoke_before_quick_start_commands(self) -> None:
        document = README.read_text(encoding="utf-8")
        required = (
            "### 実行確認: Runbook smoke",
            "[Starter Walkthrough](docs/STARTER-WALKTHROUGH.md)",
            "[test_public_starter_runbook_smoke.py](tests/test_public_starter_runbook_smoke.py)",
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
        self.assertTrue((README.parent / "docs" / "STARTER-WALKTHROUGH.md").is_file())
        self.assertTrue((README.parent / "tests" / "test_public_starter_runbook_smoke.py").is_file())

    def test_readme_smoke_entry_keeps_preview_boundary_explicit(self) -> None:
        document = README.read_text(encoding="utf-8")
        start = document.index("### 実行確認: Runbook smoke")
        end = document.index("## Quick Start — Company starter を試す", start)
        section = document[start:end]
        for marker in (
            "read-only/candidate-only",
            "Human approval",
            "runtime",
            "Promotion",
            "Current Truth",
            "Public Beta",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, section)
        self.assertNotIn("Public Beta GO: true", section)
