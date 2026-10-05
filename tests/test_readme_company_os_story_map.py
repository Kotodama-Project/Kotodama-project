from pathlib import Path
import unittest


from tests.document_contract_helpers import section, assert_links, shell_commands, assert_command_order, table_rows, assert_preview_boundary, headings, link_targets

ROOT = Path(__file__).resolve().parents[1]


class ReadmeCompanyOsStoryMapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.readme = (ROOT / "docs" / "OVERVIEW.md").read_text(encoding="utf-8")

    def test_reader_map_is_near_top_and_preserves_narrative_order(self) -> None:
        """Legacy README case ID; verify the overview's actual reader table."""
        reader = section(self.readme, "この-readme-の読み方")
        self.assertLess(self.readme.index(reader), next(offset for _, anchor, offset in headings(self.readme) if anchor == "north-star"))
        rows = table_rows(reader)[1:]
        self.assertEqual(len(rows), 5)
        self.assertEqual([row[0].strip("*") for row in rows],
                         ["Vision", "Experience", "Architecture", "Current Reality", "Try it"])
        for row, target in zip(rows, ("#north-star", "#理想のユーザー体験", "#local-first-architecture",
                                     "#現在地--夢と実証範囲を分ける", "#最初に選ぶ")):
            with self.subTest(target=target):
                assert_links(self, ROOT / "docs/OVERVIEW.md", row[2], (target,))

    def test_company_os_map_connects_all_layers_without_broadening_claims(self) -> None:
        """The overview maps eight layers; the table is not an execution receipt."""
        surface = section(self.readme, "company-os-system-map")
        rows = table_rows(surface)
        self.assertEqual(len(rows[0]), 3)
        self.assertEqual(len(rows[1:]), 8)
        for row in rows[1:]:
            with self.subTest(layer=row[0]):
                self.assertEqual(len(row), 3)
                self.assertTrue(row[1])
                self.assertTrue(row[2])
                self.assertTrue(link_targets(row[0]))
        self.assertIn("Incomplete Public Preview", surface)
        assert_preview_boundary(self, surface, ("public Voice Bot", "Public Beta access", "Final Human GO"))

    def test_story_map_links_existing_details_instead_of_replacing_them(self) -> None:
        """Verify real overview heading anchors rather than literal link spelling."""
        surface = section(self.readme, "company-os-system-map")
        assert_links(self, ROOT / "docs/OVERVIEW.md", surface, (
            "#discord-の中に会社を作る", "#voice--最初に価値を体感する入口", "#grillu-adaptive-requirements",
            "#evidence-chain--会話から-current-truth-まで", "#company-template--会社を再現できる部品",
            "#context-platform--会社の共有記憶", "#agent-foundry-と-ai-workforce", "#ai-business-loop"))


if __name__ == "__main__":
    unittest.main()
