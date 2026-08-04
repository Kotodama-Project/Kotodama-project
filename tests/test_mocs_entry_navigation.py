from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MocsEntryNavigationTests(unittest.TestCase):
    def test_mocs_catalog_exposes_ideal_current_smoke_first_stop(self) -> None:
        text = (ROOT / "templates" / "mocs" / "README.md").read_text(encoding="utf-8")
        flat = " ".join(text.split())

        for marker in (
            "## Read next: ideal -> current -> smoke",
            "**Ideal:**",
            "../company/README.md",
            "../blocks/README.md",
            "../records/README.md",
            "**Current:**",
            "../../docs/COMPANY-PACK-CATALOG.md",
            "**Smoke:**",
            "../../docs/STARTER-WALKTHROUGH.md",
            "../../tests/test_mocs_entry_navigation.py",
            "navigation-only",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, flat)

        self.assertLess(
            text.index("## Read next: ideal -> current -> smoke"),
            text.index("## Current shipped MOCs"),
        )


if __name__ == "__main__":
    unittest.main()
