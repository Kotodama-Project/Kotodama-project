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

    def test_readme_exposes_posix_examples_for_the_same_public_candidate_path(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        required = (
            "```bash\nmkdir -p work",
            "python3 tools/create_company_pack.py my-company work/my-company",
            "python3 tools/check_company_pack_customization.py work/my-company",
            "python3 tools/validate_template_pack.py examples/company-starter",
            "python3 tools/catalog_company_pack.py examples/company-starter --format markdown",
            "python3 tools/check_company_pack_public_preview.py examples/company-starter --format markdown",
            "bundle_path='work/my-company-review-bundle.json'",
            "python3 tools/build_company_pack_review_bundle.py work/my-company",
            "python3 tools/verify_company_pack_review_bundle.py \"$bundle_path\" work/my-company",
            "python3 tools/validate_installation_lifecycle.py \\\n  examples/installation-lifecycle/compose-minimum.json",
            "python3 tools/validate_installation_lifecycle.py \\\n  examples/installation-lifecycle/proxmox-segmented.json",
            "python3 tools/validate_compose_minimum_skeleton.py runtime/compose-minimum",
            "NO_GO_UNPUBLISHED",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, readme)

    def test_readme_keeps_posix_candidate_commands_in_governance_order(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        quick_start = readme.index("## Quick Start — Company starter を試す")
        runtime = readme.index("## Runtime candidate を検査する", quick_start)
        section = readme[quick_start:runtime]
        for earlier, later in (
            (
                "python3 tools/create_company_pack.py my-company work/my-company",
                "python3 tools/check_company_pack_customization.py work/my-company",
            ),
            (
                "python3 tools/check_company_pack_customization.py work/my-company",
                "python3 tools/build_company_pack_review_bundle.py work/my-company",
            ),
            (
                "python3 tools/build_company_pack_review_bundle.py work/my-company",
                "python3 tools/verify_company_pack_review_bundle.py \"$bundle_path\" work/my-company",
            ),
        ):
            with self.subTest(earlier=earlier, later=later):
                self.assertLess(section.index(earlier), section.index(later))


if __name__ == "__main__":
    unittest.main()
