from pathlib import Path
import unittest


from tests.document_contract_helpers import section, assert_links, shell_commands, assert_command_order, table_rows, assert_preview_boundary, headings, link_targets

ROOT = Path(__file__).resolve().parents[1]


class ReadmeVoiceRotationContractTests(unittest.TestCase):
    def test_voice_rotation_explains_user_value_and_current_boundary(self) -> None:
        """Read the product comparison table; these claims remain unverified."""
        path = ROOT / "docs/OVERVIEW.md"
        surface = section(path.read_text(encoding="utf-8"), "15分-voice-rotation")
        rows = table_rows(surface)
        self.assertEqual(len(rows), 5)
        self.assertEqual(len(rows[0]), 3)
        by_item = {row[0]: row for row in rows[1:]}
        self.assertEqual(set(by_item), {"境界", "投稿", "継続", "保持"})
        for item, essential in (("境界", r"900\s*秒"), ("投稿", "transcript"), ("継続", "listener"), ("保持", "receipt")):
            with self.subTest(item=item):
                self.assertRegex(by_item[item][1], essential)
                self.assertRegex(by_item[item][2], r"未証明|未提供|含まれない")
        self.assertRegex(surface, r"E2E.*証明ではありません")
        assert_links(self, path, surface)

    def test_voice_rotation_keeps_product_contract_before_unproven_claim(self) -> None:
        surface = section((ROOT / "docs/OVERVIEW.md").read_text(encoding="utf-8"), "15分-voice-rotation")
        rows = table_rows(surface)
        self.assertEqual(len(rows[0]), 3)
        self.assertIn("理想", rows[0][1])
        self.assertIn("Public Preview", rows[0][2])
        # Each comparison keeps the designed value and observed absence in separate columns.
        for row in rows[1:]:
            with self.subTest(item=row[0]):
                self.assertEqual(len(row), 3)
                self.assertNotEqual(row[1], row[2])
                self.assertRegex(row[2], r"未証明|未提供|含まれない")
        self.assertLess(surface.index(rows[-1][2]), surface.index("証明ではありません"))


if __name__ == "__main__":
    unittest.main()
