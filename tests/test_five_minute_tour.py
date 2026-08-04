import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOUR = ROOT / "docs" / "FIVE-MINUTE-TOUR.md"
SMOKE = ROOT / "tools" / "smoke_company_pack_review_chain.py"


class FiveMinuteTourTests(unittest.TestCase):
    def test_tour_carries_a_new_visitor_from_clone_to_bounded_next_choice(self) -> None:
        text = TOUR.read_text(encoding="utf-8")

        for marker in (
            "git clone https://github.com/dj-thank/Kotodama-project.git",
            "Set-Location Kotodama-project",
            "python -S -B tools/smoke_company_pack_review_chain.py",
            "cd Kotodama-project",
            "python3 -S -B tools/smoke_company_pack_review_chain.py",
            '"status": "PASS"',
            '"temporary_workspace_deleted": true',
            '"artifacts_persisted": false',
            '"public_beta": "NO_GO_UNPUBLISHED"',
            "13 steps",
            "REFUSED",
            "safe stop",
            "Company Pack Catalog",
            "Starter Walkthrough",
            "Company Pack CLI Reference",
            "STATUS",
            "ROADMAP",
            "read-only/candidate-only",
            "Final Human GO",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

        powershell = text.index("Set-Location Kotodama-project")
        powershell_smoke = text.index(
            "python -S -B tools/smoke_company_pack_review_chain.py"
        )
        posix = text.index("cd Kotodama-project")
        posix_smoke = text.index(
            "python3 -S -B tools/smoke_company_pack_review_chain.py"
        )
        self.assertLess(powershell, powershell_smoke)
        self.assertLess(posix, posix_smoke)
        self.assertNotIn("docker compose up", text)
        self.assertNotIn("Public Beta GO: true", text)

    def test_readme_exposes_tour_before_the_longer_quick_start(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        link = "[5-minute tour](docs/FIVE-MINUTE-TOUR.md)"

        self.assertGreaterEqual(readme.count(link), 2)
        self.assertLess(readme.index(link), readme.index("## Quick Start"))
        self.assertIn("clone → 1 command → 結果を読む", readme)
        self.assertIn("最初に読む", readme)

    def test_documented_success_contract_matches_the_real_smoke_report(self) -> None:
        with tempfile.TemporaryDirectory() as caller:
            completed = subprocess.run(
                [sys.executable, "-S", "-B", str(SMOKE)],
                cwd=caller,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="strict",
                timeout=90,
                check=False,
            )
            caller_entries = list(Path(caller).iterdir())

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        self.assertEqual(caller_entries, [])
        report = json.loads(completed.stdout)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(len(report["steps"]), 13)
        self.assertTrue(report["temporary_workspace_deleted"])
        self.assertFalse(report["artifacts_persisted"])
        self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")
        self.assertTrue(all(value is False for value in report["claims"].values()))


if __name__ == "__main__":
    unittest.main()
