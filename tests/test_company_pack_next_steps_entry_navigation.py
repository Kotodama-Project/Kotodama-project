from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CompanyPackNextStepsEntryNavigationTests(unittest.TestCase):
    def test_next_steps_exposes_ideal_current_smoke_first_stop(self) -> None:
        document = (ROOT / "docs/COMPANY-PACK-NEXT-STEPS.md").read_text(
            encoding="utf-8"
        )
        start = document.index("## Read next: ideal -> current -> smoke")
        run = document.index("## Run", start)
        entry = document[start:run]

        for marker in (
            "**Ideal:**",
            "../docs/TEMPLATE-GUIDE.md",
            "../templates/company/README.md",
            "../templates/blocks/README.md",
            "../templates/records/README.md",
            "../templates/mocs/README.md",
            "**Current:**",
            "COMPANY-PACK-CATALOG.md",
            "PUBLIC-PREVIEW-SELF-CHECK.md",
            "STARTER-WALKTHROUGH.md",
            "**Smoke:**",
            "plan_company_pack_next_steps.py",
            "../tests/test_plan_company_pack_next_steps.py",
            "../schemas/company-pack-next-steps.schema.json",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, entry)

        self.assertLess(start, run)

    def test_next_steps_navigation_targets_are_repository_files(self) -> None:
        document = (ROOT / "docs/COMPANY-PACK-NEXT-STEPS.md").read_text(
            encoding="utf-8"
        )
        for target in (
            "../docs/TEMPLATE-GUIDE.md",
            "../templates/company/README.md",
            "../templates/blocks/README.md",
            "../templates/records/README.md",
            "../templates/mocs/README.md",
            "COMPANY-PACK-CATALOG.md",
            "PUBLIC-PREVIEW-SELF-CHECK.md",
            "STARTER-WALKTHROUGH.md",
            "../schemas/company-pack-next-steps.schema.json",
            "../tests/test_plan_company_pack_next_steps.py",
        ):
            with self.subTest(target=target):
                self.assertIn(target, document)

        ordered_markers = (
            "[Company Pack Catalog](COMPANY-PACK-CATALOG.md)",
            "[Public Preview Self-check](PUBLIC-PREVIEW-SELF-CHECK.md)",
            "[Starter Walkthrough](STARTER-WALKTHROUGH.md)",
        )
        positions = [document.index(marker) for marker in ordered_markers]
        self.assertEqual(positions, sorted(positions))

    def test_next_steps_exposes_review_chain_after_smoke(self) -> None:
        document = (ROOT / "docs/COMPANY-PACK-NEXT-STEPS.md").read_text(
            encoding="utf-8"
        )
        start = document.index("## Read next: ideal -> current -> smoke")
        run = document.index("## Run", start)
        entry = document[start:run]

        for marker in (
            "**Review chain:**",
            "[Review Bundle](REVIEW-BUNDLE.md)",
            "[Review Request](REVIEW-REQUEST.md)",
            "[Review Response](REVIEW-RESPONSE.md)",
            "[Decision Handoff](REVIEW-DECISION-HANDOFF.md)",
            "separate Human Decision",
            "Promotion",
            "Current Truth",
            "Public Beta GO",
            "candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, entry)

        ordered_markers = (
            "[Review Bundle](REVIEW-BUNDLE.md)",
            "[Review Request](REVIEW-REQUEST.md)",
            "[Review Response](REVIEW-RESPONSE.md)",
            "[Decision Handoff](REVIEW-DECISION-HANDOFF.md)",
        )
        positions = [entry.index(marker) for marker in ordered_markers]
        self.assertEqual(positions, sorted(positions))

    def test_next_steps_links_review_chain_artifact_map(self) -> None:
        document = (ROOT / "docs/COMPANY-PACK-NEXT-STEPS.md").read_text(
            encoding="utf-8"
        )
        start = document.index("## Read next: ideal -> current -> smoke")
        run = document.index("## Run", start)
        entry = document[start:run]

        for marker in (
            "[Review-chain artifact map](STARTER-WALKTHROUGH.md#review-chain-artifact-map)",
            "Review Bundle, Review Request, Review Response, and Decision Handoff",
            "before or after the external-free smoke",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
            "Human Decision",
            "Promotion",
            "Current Truth",
            "Public Beta GO",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, entry)

        self.assertTrue((ROOT / "docs/STARTER-WALKTHROUGH.md").is_file())


if __name__ == "__main__":
    unittest.main()
