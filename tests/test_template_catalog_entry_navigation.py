from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "templates" / "README.md"


class TemplateCatalogEntryNavigationTests(unittest.TestCase):
    def test_catalog_exposes_stable_ideal_current_smoke_first_stop(self) -> None:
        document = CATALOG.read_text(encoding="utf-8")
        start = document.index("## Read next: ideal -> current -> smoke")
        section = document[start:]
        required = (
            "[Company Template](company/README.md)",
            "[Blocks](blocks/README.md)",
            "[Governed Records](records/README.md)",
            "[MOCs](mocs/README.md)",
            "[Company Pack Catalog](../docs/COMPANY-PACK-CATALOG.md)",
            "[Schema / Validator / Test Matrix](../docs/SCHEMA-VALIDATOR-MATRIX.md)",
            "[Starter Walkthrough](../docs/STARTER-WALKTHROUGH.md)",
            "[Public Preview Self-check](../docs/PUBLIC-PREVIEW-SELF-CHECK.md)",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, section)
        self.assertLess(section.index("Ideal"), section.index("Current"))
        self.assertLess(section.index("Current"), section.index("Smoke"))

    def test_catalog_entry_targets_are_repository_files(self) -> None:
        for relative in (
            "company/README.md",
            "blocks/README.md",
            "records/README.md",
            "mocs/README.md",
            "../docs/COMPANY-PACK-CATALOG.md",
            "../docs/SCHEMA-VALIDATOR-MATRIX.md",
            "../docs/STARTER-WALKTHROUGH.md",
            "../docs/PUBLIC-PREVIEW-SELF-CHECK.md",
        ):
            with self.subTest(relative=relative):
                self.assertTrue((CATALOG.parent / relative).is_file())


if __name__ == "__main__":
    unittest.main()
