import re
from pathlib import Path
import unittest

from tests.document_contract_helpers import section, assert_links, link_targets

ROOT = Path(__file__).resolve().parents[1]


class CompanyPackCatalogEntryNavigationTests(unittest.TestCase):
    def test_catalog_exposes_ideal_current_smoke_first_stop(self) -> None:
        source = ROOT / "docs/COMPANY-PACK-CATALOG.md"
        text = source.read_text(encoding="utf-8")
        entry = section(text, "read-next-ideal---current---smoke")
        targets = (
            "../templates/company/README.md", "../templates/blocks/README.md",
            "../templates/records/README.md", "../templates/mocs/README.md",
            "../examples/company-starter/README.md", "COMPANY-PACK-NEXT-STEPS.md",
            "SCHEMA-VALIDATOR-MATRIX.md", "STARTER-WALKTHROUGH.md",
        )
        assert_links(self, source, entry, targets)
        positions = [link_targets(entry).index(target) for target in targets]
        self.assertEqual(positions, sorted(positions))
        self.assertLess(text.index(entry), text.index(section(text, "runbook-smoke")))
        commands = re.findall(r"`([^`]+)`", entry)
        for prefix in ("python", "python3"):
            self.assertIn(f"{prefix} -m unittest tests.test_company_pack_catalog_entry_navigation -v", commands)
        self.assertNotRegex(entry, r"python3? -m pytest")
        self.assertIn("read-only/candidate-only", entry)
        self.assertIn("NO_GO_UNPUBLISHED", entry)

    def test_catalog_links_the_review_chain_artifact_map(self) -> None:
        source = ROOT / "docs/COMPANY-PACK-CATALOG.md"
        text = source.read_text(encoding="utf-8")
        assert_links(self, source, text, ("STARTER-WALKTHROUGH.md#review-chain-artifact-map",))

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
