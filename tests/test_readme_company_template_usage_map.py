from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ReadmeCompanyTemplateUsageMapTests(unittest.TestCase):
    def _section(self) -> str:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        start = readme.index("## Company Template・Blocks・MOCsの使い方")
        end = readme.index("## Context Platform — 会社の共有記憶", start)
        return readme[start:end]

    def test_usage_map_explains_ideal_and_current_order(self) -> None:
        section = self._section()
        required = (
            "理想の会社づくり",
            "現在の Public Preview",
            "Company Template",
            "Blocks",
            "MOCs",
            "Governed Records",
            "validator",
            "Review Bundle",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, section)

        order = [
            section.index("Company Template"),
            section.index("Blocks"),
            section.index("MOCs"),
            section.index("Governed Records"),
            section.index("validator"),
            section.index("Review Bundle"),
        ]
        self.assertEqual(order, sorted(order))

    def test_usage_map_links_each_shipped_entrypoint(self) -> None:
        section = self._section()
        links = (
            "[Company Template](templates/company/README.md)",
            "[Blocks](templates/blocks/README.md)",
            "[Governed Records](templates/records/README.md)",
            "[MOCs](templates/mocs/README.md)",
            "[Company Pack Catalog](docs/COMPANY-PACK-CATALOG.md)",
            "[Starter Walkthrough](docs/STARTER-WALKTHROUGH.md)",
            "[Validation Guide](docs/VALIDATION.md)",
        )
        for link in links:
            with self.subTest(link=link):
                self.assertIn(link, section)
                relative_path = link.split("](", 1)[1][:-1]
                self.assertTrue((ROOT / relative_path).is_file())

    def test_usage_map_keeps_example_immutable_and_commands_on_candidate(self) -> None:
        section = self._section()
        required = (
            "examples/company-starter",
            "work/my-company",
            "python tools/create_company_pack.py my-company work/my-company",
            "python tools/check_company_pack_customization.py work/my-company",
            "python tools/catalog_company_pack.py work/my-company --format markdown",
            "python tools/validate_template_pack.py work/my-company",
            "python tools/build_company_pack_review_bundle.py work/my-company",
            "python3 tools/create_company_pack.py my-company work/my-company",
            "python3 tools/check_company_pack_customization.py work/my-company",
            "python3 tools/catalog_company_pack.py work/my-company --format markdown",
            "python3 tools/validate_template_pack.py work/my-company",
            "python3 tools/build_company_pack_review_bundle.py work/my-company",
            "公開exampleは変更しない",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, section)

        for command in (
            "create_company_pack.py examples/company-starter",
            "catalog_company_pack.py examples/company-starter",
            "validate_template_pack.py examples/company-starter",
        ):
            with self.subTest(command=command):
                self.assertNotIn(command, section)

        for prefix in ("python", "python3"):
            with self.subTest(prefix=prefix):
                create = section.index(
                    f"{prefix} tools/create_company_pack.py my-company work/my-company"
                )
                customize = section.index(
                    f"{prefix} tools/check_company_pack_customization.py work/my-company"
                )
                catalog = section.index(
                    f"{prefix} tools/catalog_company_pack.py work/my-company --format markdown"
                )
                validate = section.index(
                    f"{prefix} tools/validate_template_pack.py work/my-company"
                )
                bundle = section.index(
                    f"{prefix} tools/build_company_pack_review_bundle.py work/my-company"
                )
                self.assertLess(create, customize)
                self.assertLess(customize, catalog)
                self.assertLess(catalog, validate)
                self.assertLess(validate, bundle)

        self.assertIn("CUSTOMIZATION_REQUIRED", section)
        self.assertIn("これは失敗ではなく", section)


if __name__ == "__main__":
    unittest.main()
