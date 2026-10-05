from pathlib import Path
import unittest


from tests.document_contract_helpers import section, assert_links, shell_commands, assert_command_order, table_rows, assert_preview_boundary, headings, link_targets

ROOT = Path(__file__).resolve().parents[1]


class ReadmeCompanyTemplateUsageMapTests(unittest.TestCase):
    def _section(self) -> str:
        return section((ROOT / "docs/OVERVIEW.md").read_text(encoding="utf-8"), "company-templateblocksmocsの使い方")

    def test_usage_map_explains_ideal_and_current_order(self) -> None:
        surface = self._section()
        ideal = section(surface, "理想の会社づくり")
        current = section(surface, "現在の-public-previewで実際に行う順番")
        self.assertLess(surface.index(ideal), surface.index(current))
        # Navigation, rather than arbitrary mentions, binds each governed layer to its owner.
        targets = link_targets(ideal)
        ordered = ("../templates/company/README.md", "../templates/blocks/README.md",
                   "../templates/mocs/README.md", "../templates/records/README.md")
        positions = [targets.index(target) for target in ordered]
        self.assertEqual(positions, sorted(positions))
        assert_preview_boundary(self, current, ("Human approval", "execution authority", "runtime activation", "Promotion", "Current Truth"))

    def test_usage_map_links_each_shipped_entrypoint(self) -> None:
        assert_links(self, ROOT / "docs/OVERVIEW.md", self._section(), (
            "../templates/company/README.md", "../templates/blocks/README.md", "../templates/records/README.md",
            "../templates/mocs/README.md", "COMPANY-PACK-CATALOG.md", "STARTER-WALKTHROUGH.md", "VALIDATION.md"))

    def test_usage_map_keeps_example_immutable_and_commands_on_candidate(self) -> None:
        surface = self._section()
        for prefix, language in (("python", "powershell"), ("python3", "bash")):
            expected = [f"{prefix} tools/{command}" for command in (
                "create_company_pack.py my-company work/my-company", "check_company_pack_customization.py work/my-company",
                "catalog_company_pack.py work/my-company --format markdown", "validate_template_pack.py work/my-company",
                "build_company_pack_review_bundle.py work/my-company")]
            with self.subTest(shell=language):
                assert_command_order(self, surface, expected, language)
                for command in shell_commands(surface, language):
                    self.assertNotIn("examples/company-starter", command, "editable commands must target the working candidate")
        self.assertIn("examples/company-starter", surface)
        self.assertIn("CUSTOMIZATION_REQUIRED", surface)
        assert_preview_boundary(self, surface, ("Human approval", "Promotion", "Current Truth"))


if __name__ == "__main__":
    unittest.main()
