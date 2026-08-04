from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "docs" / "COMPANY-PACK-CATALOG.md"


class CompanyPackCatalogRunbookSmokeEntryTests(unittest.TestCase):
    def test_catalog_exposes_direct_runbook_smoke_path(self) -> None:
        document = CATALOG.read_text(encoding="utf-8")
        required = (
            "## Runbook smoke",
            "[Schema / Validator / Test Matrix](SCHEMA-VALIDATOR-MATRIX.md)",
            "[test_public_starter_runbook_smoke.py](../tests/test_public_starter_runbook_smoke.py)",
            "python -m unittest tests.test_public_starter_runbook_smoke -v",
            "python3 -m unittest tests.test_public_starter_runbook_smoke -v",
            "CANDIDATE_FOR_GOVERNED_REVIEW",
            "MATCH",
            "CUSTOMIZATION_REQUIRED",
            "BUNDLE_REFUSED",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, document)

        smoke = document.index("## Runbook smoke")
        layers = document.index("## Template層への直接リンク")
        self.assertLess(smoke, layers)
        for relative in (
            "SCHEMA-VALIDATOR-MATRIX.md",
            "../tests/test_public_starter_runbook_smoke.py",
        ):
            self.assertTrue((CATALOG.parent / relative).is_file())

    def test_catalog_smoke_keeps_guided_and_plain_boundaries_separate(self) -> None:
        document = CATALOG.read_text(encoding="utf-8")
        start = document.index("## Runbook smoke")
        end = document.index("## Template層への直接リンク", start)
        section = document[start:end]
        self.assertLess(
            section.index("CANDIDATE_FOR_GOVERNED_REVIEW"),
            section.index("MATCH"),
        )
        self.assertLess(
            section.index("CUSTOMIZATION_REQUIRED"),
            section.index("BUNDLE_REFUSED"),
        )
        self.assertNotIn("Public Beta GO: true", section)
        self.assertNotIn(
            "python -m pytest tests/test_public_starter_runbook_smoke.py -q",
            section,
        )
        self.assertNotIn(
            "python3 -m pytest tests/test_public_starter_runbook_smoke.py -q",
            section,
        )
