from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "PUBLIC-PREVIEW-SELF-CHECK.md"


class PublicPreviewSelfCheckNavigationTests(unittest.TestCase):
    def test_post_pass_section_points_to_full_candidate_review_chain(self) -> None:
        document = GUIDE.read_text(encoding="utf-8")
        start_marker = "## Next after PASS: full review-chain smoke"
        end_marker = "## 成功時の意味"
        self.assertIn(start_marker, document)
        self.assertIn(end_marker, document)
        start = document.index(start_marker)
        end = document.index(end_marker, start)
        section = document[start:end]

        required = (
            "examples/company-starter",
            "work/my-company",
            "Company Pack Guided Next Steps",
            "Review Bundle",
            "Review Request",
            "Review Response",
            "Decision Handoff",
            "test_public_starter_runbook_smoke.py",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
            "Human approval",
            "runtime authority",
            "Promotion",
            "Current Truth",
            "Public Beta GO",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, section)

        for relative in (
            "../examples/company-starter/README.md",
            "COMPANY-PACK-NEXT-STEPS.md",
            "STARTER-WALKTHROUGH.md#review-chain-artifact-map",
            "../tests/test_public_starter_runbook_smoke.py",
        ):
            target = relative.split("#", 1)[0]
            self.assertTrue((GUIDE.parent / target).is_file(), relative)

    def test_post_pass_commands_are_cross_shell_and_ordered(self) -> None:
        document = GUIDE.read_text(encoding="utf-8")
        start = document.index("## Next after PASS: full review-chain smoke")
        end = document.index("## 成功時の意味", start)
        section = document[start:end]

        command_groups = (
            (
                "python tools\\plan_company_pack_next_steps.py work\\my-company --format markdown",
                "python -m unittest tests.test_public_starter_runbook_smoke -v",
            ),
            (
                "python3 tools/plan_company_pack_next_steps.py work/my-company --format markdown",
                "python3 -m unittest tests.test_public_starter_runbook_smoke -v",
            ),
        )
        for planner, smoke in command_groups:
            with self.subTest(planner=planner):
                self.assertIn(planner, section)
                self.assertIn(smoke, section)
                self.assertLess(section.index(planner), section.index(smoke))

        self.assertIn("temporary", section)
        self.assertIn("external-free", section)


if __name__ == "__main__":
    unittest.main()
