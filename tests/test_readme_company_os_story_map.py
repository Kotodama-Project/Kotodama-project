from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ReadmeCompanyOsStoryMapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_reader_map_is_near_top_and_preserves_narrative_order(self) -> None:
        start = self.readme.index("## この README の読み方")
        north_star = self.readme.index("## North Star")
        self.assertLess(start, north_star)
        section = self.readme[start:north_star]

        markers = (
            "Vision",
            "Experience",
            "Architecture",
            "Current Reality",
            "Try it",
        )
        positions = [section.index(marker) for marker in markers]
        self.assertEqual(positions, sorted(positions))

        for target in (
            "#north-star",
            "#理想のユーザー体験",
            "#local-first-architecture",
            "#現在地--夢と実証範囲を分ける",
            "#最初に選ぶ",
        ):
            with self.subTest(target=target):
                self.assertIn(target, section)

    def test_company_os_map_connects_all_layers_without_broadening_claims(self) -> None:
        start = self.readme.index("## Company OS system map")
        end = self.readme.index("## North Star", start)
        section = self.readme[start:end]

        for marker in (
            "Office / Input",
            "Voice Adapter",
            "Intent / GrillU",
            "Governance / Evidence",
            "Company Pack",
            "Context Platform",
            "Workforce / Runtime",
            "Business / Learning",
            "理想の役割",
            "現在の公開境界",
            "Incomplete Public Preview",
            "NO_GO_UNPUBLISHED",
            "public Voice Bot は未提供",
            "Public Beta access は未提供",
            "Final Human GO は未完了",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, section)

    def test_story_map_links_existing_details_instead_of_replacing_them(self) -> None:
        start = self.readme.index("## Company OS system map")
        end = self.readme.index("## North Star", start)
        section = self.readme[start:end]

        for target in (
            "#discord-の中に会社を作る",
            "#voice--最初に価値を体感する入口",
            "#grillu--一度に一つだけ深掘りする",
            "#evidence-chain--会話から-current-truth-まで",
            "#company-template--会社を再現できる部品",
            "#context-platform--会社の共有記憶",
            "#agent-foundry-と-ai-workforce",
            "#ai-business-loop",
        ):
            with self.subTest(target=target):
                self.assertIn(target, section)


if __name__ == "__main__":
    unittest.main()
