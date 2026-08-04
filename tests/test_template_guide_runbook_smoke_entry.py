from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "TEMPLATE-GUIDE.md"


class TemplateGuideRunbookSmokeEntryTests(unittest.TestCase):
    def test_template_guide_exposes_ideal_current_and_smoke_order(self) -> None:
        document = GUIDE.read_text(encoding="utf-8")
        required = (
            "## 最初に読む順番: ideal → current → smoke",
            "[Company Template](../templates/company/README.md)",
            "[Blocks](../templates/blocks/README.md)",
            "[Governed Records](../templates/records/README.md)",
            "[MOCs](../templates/mocs/README.md)",
            "[Company Pack Catalog](COMPANY-PACK-CATALOG.md)",
            "[Company Pack Guided Next Steps](COMPANY-PACK-NEXT-STEPS.md)",
            "[Starter Walkthrough](STARTER-WALKTHROUGH.md)",
            "[test_public_starter_runbook_smoke.py](../tests/test_public_starter_runbook_smoke.py)",
            "ideal/current",
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

        first_read = document.index("## 最初に読む順番: ideal → current → smoke")
        ideal = document.index("## 理想としての使い方")
        self.assertLess(first_read, ideal)
        for relative in (
            "../templates/company/README.md",
            "../templates/blocks/README.md",
            "../templates/records/README.md",
            "../templates/mocs/README.md",
            "COMPANY-PACK-CATALOG.md",
            "COMPANY-PACK-NEXT-STEPS.md",
            "STARTER-WALKTHROUGH.md",
            "../tests/test_public_starter_runbook_smoke.py",
        ):
            self.assertTrue((GUIDE.parent / relative).is_file())

        ordered_markers = (
            "[Company Pack Catalog](COMPANY-PACK-CATALOG.md)",
            "[Company Pack Guided Next Steps](COMPANY-PACK-NEXT-STEPS.md)",
            "[Starter Walkthrough](STARTER-WALKTHROUGH.md)",
        )
        positions = [document.index(marker) for marker in ordered_markers]
        self.assertEqual(positions, sorted(positions))

    def test_template_guide_smoke_entry_keeps_candidate_boundary_explicit(self) -> None:
        document = GUIDE.read_text(encoding="utf-8")
        start = document.index("## 最初に読む順番: ideal → current → smoke")
        end = document.index("## 理想としての使い方", start)
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

    def test_template_guide_exposes_cross_shell_candidate_runbook_and_stop(self) -> None:
        document = GUIDE.read_text(encoding="utf-8")
        start = document.index("## Current candidate runbook smoke")
        end = document.index("## 理想としての使い方", start)
        section = document[start:end]
        required = (
            "examples/company-starter",
            "work/my-company",
            "python tools\\create_company_pack.py my-company work\\my-company",
            "python tools\\check_company_pack_customization.py work\\my-company",
            "python tools\\catalog_company_pack.py work\\my-company --format markdown",
            "python tools\\validate_template_pack.py work\\my-company",
            "python tools\\check_company_pack_public_preview.py work\\my-company --format markdown",
            "python tools\\build_company_pack_review_bundle.py work\\my-company",
            "python3 tools/create_company_pack.py my-company work/my-company",
            "python3 tools/check_company_pack_customization.py work/my-company",
            "python3 tools/catalog_company_pack.py work/my-company --format markdown",
            "python3 tools/validate_template_pack.py work/my-company",
            "python3 tools/check_company_pack_public_preview.py work/my-company --format markdown",
            "python3 tools/build_company_pack_review_bundle.py work/my-company",
            "CUSTOMIZATION_REQUIRED",
            "BUNDLE_REFUSED",
            "replacement_required: 0",
            "編集後に再実行",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, section)

        for prefix, separator in (("python", "\\"), ("python3", "/")):
            commands = (
                f"{prefix} tools{separator}create_company_pack.py my-company work{separator}my-company",
                f"{prefix} tools{separator}check_company_pack_customization.py work{separator}my-company",
                f"{prefix} tools{separator}catalog_company_pack.py work{separator}my-company --format markdown",
                f"{prefix} tools{separator}validate_template_pack.py work{separator}my-company",
                f"{prefix} tools{separator}check_company_pack_public_preview.py work{separator}my-company --format markdown",
                f"{prefix} tools{separator}build_company_pack_review_bundle.py work{separator}my-company",
            )
            positions = [section.index(command) for command in commands]
            with self.subTest(prefix=prefix):
                self.assertEqual(positions, sorted(positions))

        self.assertLess(
            section.index("replacement_required: 0"),
            section.index("build_company_pack_review_bundle.py"),
        )
