from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


from tests.document_contract_helpers import section, assert_links, shell_commands, assert_command_order, table_rows, assert_preview_boundary, headings, link_targets

ROOT = Path(__file__).resolve().parents[1]

CORE_COMMANDS = (
    (
        "tools/validate_template_pack.py",
        "usage: validate_template_pack.py PACK_DIRECTORY",
        "Validate a Company Pack",
    ),
    (
        "tools/check_company_pack_customization.py",
        "usage: check_company_pack_customization.py PACK_DIRECTORY",
        "Inspect Company Pack customization",
    ),
    (
        "tools/check_company_pack_public_preview.py",
        "usage: check_company_pack_public_preview.py PACK_DIRECTORY [--format json|markdown]",
        "Summarize the Public Preview boundary",
    ),
)


class CoreCompanyPackCliHelpTests(unittest.TestCase):
    def run_tool(self, relative_tool: str, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ROOT / relative_tool), *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

    def test_short_and_long_help_are_read_only_successes(self) -> None:
        for relative_tool, usage, purpose in CORE_COMMANDS:
            for flag in ("-h", "--help"):
                with self.subTest(tool=relative_tool, flag=flag), tempfile.TemporaryDirectory() as tmp:
                    work = Path(tmp)
                    before = tuple(work.iterdir())
                    result = self.run_tool(relative_tool, flag, cwd=work)
                    after = tuple(work.iterdir())

                    self.assertEqual(result.returncode, 0, result)
                    self.assertEqual(result.stderr, "")
                    self.assertIn(usage, result.stdout)
                    self.assertIn(purpose, result.stdout)
                    self.assertIn("read-only/candidate-only", result.stdout)
                    self.assertIn("NO_GO_UNPUBLISHED", result.stdout)
                    self.assertEqual(before, after)

    def test_malformed_invocation_stays_sanitized(self) -> None:
        secret_like = "opaque-user-input-that-must-not-be-reflected"
        for relative_tool, usage, _purpose in CORE_COMMANDS:
            with self.subTest(tool=relative_tool), tempfile.TemporaryDirectory() as tmp:
                result = self.run_tool(
                    relative_tool,
                    "--unknown-option",
                    secret_like,
                    cwd=Path(tmp),
                )
                combined = result.stdout + result.stderr

                self.assertEqual(result.returncode, 2)
                self.assertIn(usage, result.stderr)
                self.assertNotIn("--unknown-option", combined)
                self.assertNotIn(secret_like, combined)

    def test_readme_quick_start_exposes_cross_shell_help_first(self) -> None:
        """Legacy case ID: the tested onboarding surface is docs/OVERVIEW.md."""
        path = ROOT / "docs/OVERVIEW.md"
        quick_start = section(path.read_text(encoding="utf-8"), "quick-start--company-starter-を試す")
        for prefix, language in (("python", "powershell"), ("python3", "bash")):
            commands = [f"{prefix} {command}" for command in (
                "tools/validate_template_pack.py --help",
                "tools/check_company_pack_customization.py --help",
                "tools/check_company_pack_public_preview.py --help",
                "tools/create_company_pack.py my-company work/my-company",
            )]
            with self.subTest(shell=language):
                actual = shell_commands(quick_start, language)
                for help_command in commands[:3]:
                    self.assertIn(help_command, actual)
                    self.assertLess(actual.index(help_command), actual.index(commands[-1]))
        assert_preview_boundary(self, quick_start)


if __name__ == "__main__":
    unittest.main()
