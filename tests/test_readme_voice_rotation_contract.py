from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ReadmeVoiceRotationContractTests(unittest.TestCase):
    def test_voice_rotation_explains_user_value_and_current_boundary(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        start = readme.index("### 15分 Voice rotation")
        end = readme.index("## GrillU", start)
        section = readme[start:end]

        for marker in (
            "利用者が受け取る15分の境界",
            "理想の製品体験",
            "現在の Public Preview",
            "900秒境界",
            "話者・時刻付き transcript を private channel へ投稿",
            "listener / rejoin",
            "retention/delete receipt",
            "公開済みの証明ではありません",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, section)

    def test_voice_rotation_keeps_product_contract_before_unproven_claim(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        start = readme.index("### 15分 Voice rotation")
        end = readme.index("## GrillU", start)
        section = readme[start:end]

        ideal = section.index("理想の製品体験")
        current = section.index("現在の Public Preview")
        unproven = section.index("公開済みの証明ではありません")
        self.assertLess(ideal, current)
        self.assertLess(current, unproven)


if __name__ == "__main__":
    unittest.main()
