from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CompanyPackCatalogEntryNavigationTests(unittest.TestCase):
    def test_catalog_exposes_ideal_current_smoke_first_stop(self) -> None:
        text = (ROOT / "docs" / "COMPANY-PACK-CATALOG.md").read_text(encoding="utf-8")
        flat = " ".join(text.split())

        for marker in (
            "## Read next: ideal -> current -> smoke",
            "**Ideal:**",
            "../templates/company/README.md",
            "../templates/blocks/README.md",
            "../templates/records/README.md",
            "../templates/mocs/README.md",
            "**Current:**",
            "../examples/company-starter/README.md",
            "[Company Pack Guided Next Steps](COMPANY-PACK-NEXT-STEPS.md)",
            "**Smoke:**",
            "SCHEMA-VALIDATOR-MATRIX.md",
            "STARTER-WALKTHROUGH.md",
            "../tests/test_company_pack_catalog_entry_navigation.py",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, flat)

        self.assertLess(
            text.index("## Read next: ideal -> current -> smoke"),
            text.index("## Runbook smoke"),
        )

    def test_catalog_links_the_review_chain_artifact_map(self) -> None:
        text = (ROOT / "docs" / "COMPANY-PACK-CATALOG.md").read_text(encoding="utf-8")
        marker = "[Review-chain artifact map](STARTER-WALKTHROUGH.md#review-chain-artifact-map)"
        self.assertIn(marker, text)
        self.assertIn("before or after the smoke", text)
        self.assertTrue((ROOT / "docs" / "STARTER-WALKTHROUGH.md").is_file())

    def test_catalog_quick_start_separates_baseline_and_generated_candidate_chain(self) -> None:
        text = (ROOT / "docs" / "COMPANY-PACK-CATALOG.md").read_text(encoding="utf-8")
        start = text.index("## Quick start: immutable example -> generated candidate")
        end = text.index("## JSONの読み方", start)
        section = text[start:end]
        flat = " ".join(section.split())

        markers = (
            "immutable published baseline",
            "python tools/catalog_company_pack.py examples/company-starter",
            "python tools/check_company_pack_public_preview.py examples/company-starter --format markdown",
            "python tools/validate_template_pack.py examples/company-starter",
            "python tools/create_company_pack.py my-company work/my-company",
            "python tools/check_company_pack_customization.py work/my-company",
            "python tools/validate_template_pack.py work/my-company",
            "python tools/catalog_company_pack.py work/my-company --format markdown",
            "python tools/check_company_pack_public_preview.py work/my-company --format markdown",
            "python tools/plan_company_pack_next_steps.py work/my-company --format markdown",
            "python3 tools/catalog_company_pack.py examples/company-starter",
            "python3 tools/check_company_pack_public_preview.py examples/company-starter --format markdown",
            "python3 tools/validate_template_pack.py examples/company-starter",
            "python3 tools/create_company_pack.py my-company work/my-company",
            "python3 tools/check_company_pack_customization.py work/my-company",
            "python3 tools/validate_template_pack.py work/my-company",
            "python3 tools/catalog_company_pack.py work/my-company --format markdown",
            "python3 tools/check_company_pack_public_preview.py work/my-company --format markdown",
            "python3 tools/plan_company_pack_next_steps.py work/my-company --format markdown",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        )
        for marker in markers:
            with self.subTest(marker=marker):
                self.assertIn(marker, flat)

        ordered = (
            "python tools/create_company_pack.py my-company work/my-company",
            "python tools/check_company_pack_customization.py work/my-company",
            "python tools/validate_template_pack.py work/my-company",
            "python tools/catalog_company_pack.py work/my-company --format markdown",
            "python tools/check_company_pack_public_preview.py work/my-company --format markdown",
            "python tools/plan_company_pack_next_steps.py work/my-company --format markdown",
        )
        positions = [section.index(marker) for marker in ordered]
        self.assertEqual(positions, sorted(positions))
        self.assertLess(
            section.index("examples/company-starter"),
            section.index("python tools/create_company_pack.py my-company work/my-company"),
        )
        self.assertNotIn(
            "check_company_pack_customization.py examples/company-starter", section
        )


if __name__ == "__main__":
    unittest.main()
