from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BlocksRecordsNavigationTests(unittest.TestCase):
    def test_catalogs_expose_ideal_current_smoke_navigation(self) -> None:
        catalogs = {
            "blocks": ROOT / "templates" / "blocks" / "README.md",
            "records": ROOT / "templates" / "records" / "README.md",
        }
        shared_markers = (
            "## Read next: ideal -> current -> smoke",
            "[Company Pack Catalog](../../docs/COMPANY-PACK-CATALOG.md)",
            "[Company Pack Guided Next Steps](../../docs/COMPANY-PACK-NEXT-STEPS.md)",
            "[Starter Walkthrough](../../docs/STARTER-WALKTHROUGH.md)",
            "[Schema / Validator / Test Matrix](../../docs/SCHEMA-VALIDATOR-MATRIX.md)",
            "[MOCs](../mocs/README.md)",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        )
        companion_links = {
            "blocks": "[Governed Records](../records/README.md)",
            "records": "[Blocks](../blocks/README.md)",
        }
        for name, path in catalogs.items():
            document = path.read_text(encoding="utf-8")
            start = document.index("## Read next: ideal -> current -> smoke")
            section = document[start:]
            for marker in shared_markers + (companion_links[name],):
                with self.subTest(catalog=name, marker=marker):
                    self.assertIn(marker, section)
            self.assertLess(section.index("Ideal"), section.index("Current"))
            self.assertLess(section.index("Current"), section.index("Smoke"))

    def test_navigation_targets_are_repository_files(self) -> None:
        targets = (
            "docs/COMPANY-PACK-CATALOG.md",
            "docs/COMPANY-PACK-NEXT-STEPS.md",
            "docs/STARTER-WALKTHROUGH.md",
            "docs/SCHEMA-VALIDATOR-MATRIX.md",
            "templates/mocs/README.md",
            "templates/blocks/README.md",
            "templates/records/README.md",
        )
        for target in targets:
            with self.subTest(target=target):
                self.assertTrue((ROOT / target).is_file())


if __name__ == "__main__":
    unittest.main()
