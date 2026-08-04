from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ValidationGuideEntryNavigationTests(unittest.TestCase):
    def test_validation_guide_exposes_ideal_current_smoke_first_stop(self) -> None:
        document = (ROOT / "docs" / "VALIDATION.md").read_text(encoding="utf-8")
        start = document.index("## Read next: ideal -> current -> smoke")
        end = document.index("## 理想と現在の公開candidate", start)
        section = document[start:end]

        for marker in (
            "**Ideal:**",
            "[Company Template](../templates/company/README.md)",
            "[Blocks](../templates/blocks/README.md)",
            "[Governed Records](../templates/records/README.md)",
            "[MOCs](../templates/mocs/README.md)",
            "**Current:**",
            "[Company Pack Catalog](COMPANY-PACK-CATALOG.md)",
            "[Company Pack Guided Next Steps](COMPANY-PACK-NEXT-STEPS.md)",
            "**Smoke:**",
            "[Starter Walkthrough](STARTER-WALKTHROUGH.md)",
            "[Public Preview Self-check](PUBLIC-PREVIEW-SELF-CHECK.md)",
            "[Schema / Validator / Test Matrix](SCHEMA-VALIDATOR-MATRIX.md)",
            "[Public starter smoke regression](../tests/test_public_starter_runbook_smoke.py)",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, section)

        self.assertLess(section.index("Ideal"), section.index("Current"))
        self.assertLess(section.index("Current"), section.index("Smoke"))

    def test_validation_guide_entry_targets_are_repository_paths(self) -> None:
        targets = (
            "templates/company/README.md",
            "templates/blocks/README.md",
            "templates/records/README.md",
            "templates/mocs/README.md",
            "docs/COMPANY-PACK-CATALOG.md",
            "docs/COMPANY-PACK-NEXT-STEPS.md",
            "docs/STARTER-WALKTHROUGH.md",
            "docs/PUBLIC-PREVIEW-SELF-CHECK.md",
            "docs/SCHEMA-VALIDATOR-MATRIX.md",
            "tests/test_public_starter_runbook_smoke.py",
        )
        for target in targets:
            with self.subTest(target=target):
                self.assertTrue((ROOT / target).is_file())

    def test_validation_guide_tests_expose_cross_shell_full_suite_commands(self) -> None:
        document = (ROOT / "docs" / "VALIDATION.md").read_text(encoding="utf-8")
        start = document.index("## Tests")
        end = document.index("## Boundary", start)
        section = document[start:end]
        required = (
            "python -m pip install -r requirements-test.txt",
            "python -m unittest discover -s tests -v",
            "python3 -m pip install -r requirements-test.txt",
            "python3 -m unittest discover -s tests -v",
            "test-only",
            "Draft202012Validator",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, section)
        self.assertLess(
            section.index("python -m pip install -r requirements-test.txt"),
            section.index("python -m unittest discover -s tests -v"),
        )
        self.assertLess(
            section.index("python3 -m pip install -r requirements-test.txt"),
            section.index("python3 -m unittest discover -s tests -v"),
        )

    def test_validation_guide_exposes_customization_and_bundle_stop_semantics(self) -> None:
        document = (ROOT / "docs" / "VALIDATION.md").read_text(encoding="utf-8")
        start = document.index("## Customization and bundle stop semantics")
        end = document.index("## What it validates", start)
        section = document[start:end]
        required = (
            "CUSTOMIZATION_REQUIRED",
            "BUNDLE_REFUSED",
            "replacement_required: 0",
            "READY_FOR_GOVERNED_REVIEW",
            "work/my-company",
            "python tools\\check_company_pack_customization.py work\\my-company",
            "python tools\\build_company_pack_review_bundle.py work\\my-company",
            "python3 tools/check_company_pack_customization.py work/my-company",
            "python3 tools/build_company_pack_review_bundle.py work/my-company",
            "編集",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
            "Human approval",
            "Promotion",
            "Current Truth",
            "Public Beta GO",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, section)

        for prefix, separator in (("python", "\\"), ("python3", "/")):
            customization = section.index(
                f"{prefix} tools{separator}check_company_pack_customization.py work{separator}my-company"
            )
            bundle = section.index(
                f"{prefix} tools{separator}build_company_pack_review_bundle.py work{separator}my-company"
            )
            with self.subTest(prefix=prefix):
                self.assertLess(customization, bundle)
        self.assertLess(
            section.index("replacement_required: 0"),
            section.index("build_company_pack_review_bundle.py"),
        )


if __name__ == "__main__":
    unittest.main()
