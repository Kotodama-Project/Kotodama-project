import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


from tests.document_contract_helpers import command_section, section, assert_links, shell_commands, assert_command_order, table_rows, assert_preview_boundary, headings, link_targets

from tests.document_contract_helpers import owned_smoke_receipt, fenced_blocks
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
TOUR = ROOT / "docs" / "FIVE-MINUTE-TOUR.md"
SMOKE = ROOT / "tools" / "smoke_company_pack_review_chain.py"


class FiveMinuteTourTests(unittest.TestCase):
    def test_tour_carries_a_new_visitor_from_clone_to_bounded_next_choice(self) -> None:
        text = TOUR.read_text(encoding="utf-8")
        clone = "git clone https://github.com/Kotodama-Project/Kotodama-project.git"
        for prefix, language, change_directory in (("python", "powershell", "Set-Location Kotodama-project"),
                                                 ("python3", "bash", "cd Kotodama-project")):
            with self.subTest(shell=language):
                assert_command_order(self, text, (clone, change_directory,
                                     f"{prefix} -S -B tools/smoke_company_pack_review_chain.py"), language)
        assert_links(self, TOUR, text, ("COMPANY-PACK-CATALOG.md", "STARTER-WALKTHROUGH.md",
                     "COMPANY-PACK-CLI-REFERENCE.md", "../STATUS.md", "../ROADMAP.md"))
        assert_preview_boundary(self, text, ("Human approval", "runtime", "Promotion", "Current Truth", "Final Human GO"))
        self.assertTrue(any(anchor.startswith("refused") for _, anchor, _ in headings(text)))
        self.assertFalse(any("docker compose up" in command for command in shell_commands(text)))

    def test_readme_exposes_tour_before_the_longer_quick_start(self) -> None:
        for relative, target in (("README.md", "docs/FIVE-MINUTE-TOUR.md"),
                                 ("docs/OVERVIEW.md", "FIVE-MINUTE-TOUR.md")):
            with self.subTest(surface=relative):
                path = ROOT / relative
                text = path.read_text(encoding="utf-8")
                assert_links(self, path, text, (target,))
                if relative == "README.md":
                    first_smoke = command_section(text, ("python3 -S -B tools/smoke_company_pack_review_chain.py",))
                    first_visit_end = text.index(first_smoke) + len(first_smoke)
                    self.assertIn(target, link_targets(text[:first_visit_end]))
                else:
                    required = {"python3 tools/create_company_pack.py my-company work/my-company"}
                    required.update(f"python3 tools/{tool} --help" for tool in (
                        "validate_template_pack.py", "check_company_pack_customization.py",
                        "check_company_pack_public_preview.py"))
                    long_runbook = command_section(text, required)
                    self.assertIn(target, link_targets(text[:text.index(long_runbook)]))
                # One working near-top tour link is sufficient on each surface.
                self.assertLess(text.index(target), len(text) // 3)

    def test_documented_success_contract_matches_the_real_smoke_report(self) -> None:
        receipt = owned_smoke_receipt()  # Shared real foreign-cwd/cleanup integration, not a mocked report.
        self.assertEqual(receipt.returncode, 0, receipt.stderr)
        self.assertEqual(receipt.stderr, "")
        self.assertEqual(receipt.before_entries, ())
        self.assertEqual(receipt.after_entries, ())
        report = json.loads(receipt.stdout)
        schema = json.loads((ROOT / "schemas/company-pack-review-chain-smoke.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(report)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["temporary_workspace_deleted"])
        self.assertFalse(report["artifacts_persisted"])
        self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")
        claim_keys = set(schema["properties"]["claims"]["required"])
        self.assertTrue(claim_keys)
        self.assertEqual(set(report["claims"]), claim_keys)
        self.assertTrue(all(value is False for value in report["claims"].values()))
        examples = [json.loads(block) for block in fenced_blocks(TOUR.read_text(encoding="utf-8"), "json")]
        self.assertTrue(examples)
        for example in examples:
            with self.subTest(fields=sorted(example)):
                self.assertTrue(example)
                self.assertLessEqual(set(example), set(report))
                for field, expected in example.items():
                    self.assertEqual(report[field], expected)
        # The document's enumerated machine step IDs must match the closed real report.
        step_blocks = [block for block in fenced_blocks(TOUR.read_text(encoding="utf-8"), "text") if "→" in block]
        self.assertEqual(len(step_blocks), 1)
        self.assertEqual([item.strip() for item in step_blocks[0].replace("\n", " ").split("→")],
                         [step["id"] for step in report["steps"]])


if __name__ == "__main__":
    unittest.main()
