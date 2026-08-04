from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


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
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        start = readme.index("## Quick Start — Company starter を試す")
        end = readme.index("## Runtime candidate を検査する", start)
        section = readme[start:end]
        help_heading = section.index("### 先にCLIの境界を確認する")
        create_heading = section.index("### 作業copyを作って確認する")
        self.assertLess(help_heading, create_heading)

        for prefix in ("python", "python3"):
            for command in (
                "tools/validate_template_pack.py --help",
                "tools/check_company_pack_customization.py --help",
                "tools/check_company_pack_public_preview.py --help",
            ):
                with self.subTest(prefix=prefix, command=command):
                    self.assertIn(f"{prefix} {command}", section)

        for marker in (
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
            "Packを読み書きしません",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, section)


if __name__ == "__main__":
    unittest.main()
