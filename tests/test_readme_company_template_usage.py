from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ReadmeCompanyTemplateUsageTests(unittest.TestCase):
    def test_readme_distinguishes_ideal_and_current_template_usage(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        required = (
            "理想の使い方",
            "現在の Public Preview でできること",
            "Company Template を複製",
            "activation candidate",
            "candidate-only",
            "Public Beta",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, readme)

    def test_template_usage_flow_preserves_governance_order(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        ideal = readme.index("Company Template を複製")
        validator = readme.index("validator", ideal)
        review = readme.index("Review Bundle", validator)
        activation = readme.index("activation candidate", review)
        self.assertLess(ideal, validator)
        self.assertLess(validator, review)
        self.assertLess(review, activation)

    def test_readme_first_stop_points_to_catalog_before_runtime_profiles(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        for marker in (
            "## 最初に選ぶ",
            "Company Pack Catalog",
            "Starter Walkthrough",
            "Installation Lifecycle",
            "compose_minimum",
            "proxmox_segmented",
            "read-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, readme)

        first_stop = readme.index("## 最初に選ぶ")
        catalog = readme.index("Company Pack Catalog", first_stop)
        starter = readme.index("Starter Walkthrough", first_stop)
        lifecycle = readme.index("Installation Lifecycle", first_stop)
        self.assertLess(catalog, starter)
        self.assertLess(starter, lifecycle)


if __name__ == "__main__":
    unittest.main()
