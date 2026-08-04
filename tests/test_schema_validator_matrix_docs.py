from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs" / "SCHEMA-VALIDATOR-MATRIX.md"


class SchemaValidatorMatrixDocumentationTests(unittest.TestCase):
    def test_matrix_exposes_ordered_contract_tool_test_runbook_path(self) -> None:
        self.assertTrue(MATRIX.is_file())
        matrix = MATRIX.read_text(encoding="utf-8")
        required = (
            "# Schema / Validator / Test Matrix",
            "Company Template",
            "Blocks",
            "Governed Records",
            "MOCs",
            "Company Pack Catalog",
            "Customization",
            "Public Preview Self-check",
            "Company Pack Next Steps",
            "Review Bundle",
            "PowerShell",
            "POSIX",
            "read-only",
            "candidate-only",
            "NO_GO_UNPUBLISHED",
            "Public Beta GO",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, matrix)

        for marker in (
            "Human approval",
            "runtime",
            "provider",
            "Voice / Discord",
            "Promotion",
            "Current Truth",
        ):
            with self.subTest(boundary=marker):
                self.assertIn(marker, matrix)

        command_pairs = (
            ("python tools\\create_company_pack.py", "python3 tools/create_company_pack.py"),
            ("python tools\\validate_template_pack.py", "python3 tools/validate_template_pack.py"),
            ("python tools\\catalog_company_pack.py", "python3 tools/catalog_company_pack.py"),
            (
                "python tools\\check_company_pack_customization.py",
                "python3 tools/check_company_pack_customization.py",
            ),
            (
                "python tools\\check_company_pack_public_preview.py",
                "python3 tools/check_company_pack_public_preview.py",
            ),
            (
                "python tools\\plan_company_pack_next_steps.py",
                "python3 tools/plan_company_pack_next_steps.py",
            ),
            (
                "python tools\\build_company_pack_review_bundle.py",
                "python3 tools/build_company_pack_review_bundle.py",
            ),
            (
                "python tools\\verify_company_pack_review_bundle.py",
                "python3 tools/verify_company_pack_review_bundle.py",
            ),
        )
        for powershell, posix in command_pairs:
            with self.subTest(powershell=powershell, posix=posix):
                self.assertIn(powershell, matrix)
                self.assertIn(posix, matrix)

        ordered = (
            "## 1. Company Template",
            "## 2. Blocks",
            "## 3. Governed Records",
            "## 4. MOCs",
            "## 5. Company Pack Catalog",
            "## 6. Customization",
            "## 7. Public Preview Self-check",
            "## 8. Company Pack Next Steps",
            "## 9. Review Bundle",
        )
        positions = [matrix.index(marker) for marker in ordered]
        self.assertEqual(positions, sorted(positions))

    def test_matrix_runbook_smoke_links_back_to_catalog_entry(self) -> None:
        matrix = MATRIX.read_text(encoding="utf-8")
        start = matrix.index("## Runbook smoke")
        end = matrix.index("## 1. Company Template", start)
        smoke = matrix[start:end]
        for marker in (
            "[Company Pack Catalog](COMPANY-PACK-CATALOG.md)",
            "[`test_company_pack_catalog_runbook_smoke_entry.py`](../tests/test_company_pack_catalog_runbook_smoke_entry.py)",
            "CANDIDATE_FOR_GOVERNED_REVIEW",
            "MATCH",
            "CUSTOMIZATION_REQUIRED",
            "BUNDLE_REFUSED",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, smoke)

        for relative in (
            "COMPANY-PACK-CATALOG.md",
            "../tests/test_company_pack_catalog_runbook_smoke_entry.py",
        ):
            self.assertTrue((MATRIX.parent / relative).is_file())

    def test_matrix_links_are_present_and_entry_surfaces_link_back(self) -> None:
        matrix = MATRIX.read_text(encoding="utf-8")
        links = re.findall(r"\]\(([^)]+)\)", matrix)
        local_links = [
            link.split("#", 1)[0]
            for link in links
            if not link.startswith(("http://", "https://", "mailto:", "#"))
        ]
        for link in local_links:
            with self.subTest(link=link):
                self.assertTrue((MATRIX.parent / link).exists(), link)

        for surface in (
            ROOT / "README.md",
            ROOT / "docs" / "TEMPLATE-GUIDE.md",
            ROOT / "docs" / "VALIDATION.md",
        ):
            with self.subTest(surface=surface):
                self.assertIn("SCHEMA-VALIDATOR-MATRIX.md", surface.read_text(encoding="utf-8"))
