"""tools/lint_docs.py keeps the entry documents short, linked, and current."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "lint_docs.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("lint_docs", TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class LintDocsTests(unittest.TestCase):
    def test_repository_documentation_passes(self) -> None:
        report = load_tool().lint(ROOT)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["status"], "PASS")
        self.assertGreater(report["checked_files"], 10)

    def test_cli_reports_one_line_json_and_exit_code(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-S", "-B", str(TOOL)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        lines = completed.stdout.strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["status"], "PASS")

    def test_help_and_usage_boundaries(self) -> None:
        tool = load_tool()
        self.assertEqual(tool.main(["--help"]), 0)
        self.assertEqual(tool.main(["--bogus"]), 2)

    def test_anchor_rules_follow_github_slugs(self) -> None:
        tool = load_tool()
        self.assertEqual(
            tool.github_anchor("Voice — 最初に価値を体感する入口"),
            "voice--最初に価値を体感する入口",
        )
        self.assertEqual(
            tool.github_anchor("Evidence Chain — 会話から Current Truth まで"),
            "evidence-chain--会話から-current-truth-まで",
        )
        self.assertEqual(tool.github_anchor("5 分で試す"), "5-分で試す")

    def test_broken_link_stale_narrative_and_long_readme_fail(self) -> None:
        tool = load_tool()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "docs").mkdir()
            (root / "README.md").write_text(
                "# X\n\n[missing](docs/NOPE.md) [anchor](#nope) R179 "
                "NO_GO_UNPUBLISHED NO_GO_UNPUBLISHED NO_GO_UNPUBLISHED\n" + "line\n" * 160,
                encoding="utf-8",
            )
            (root / "docs" / "FIVE-MINUTE-TOUR.md").write_text("# Tour\n", encoding="utf-8")
            (root / "STATUS.md").write_text(
                "R179 is the current public documentation revision\n", encoding="utf-8"
            )
            (root / "ROADMAP.md").write_text("# Roadmap\n", encoding="utf-8")
            report = tool.lint(root)
        self.assertEqual(report["status"], "FAIL")
        joined = "\n".join(report["errors"])
        for marker in (
            "broken link docs/NOPE.md",
            "unresolved anchor #nope",
            "internal revision number",
            "NO_GO_UNPUBLISHED appears 3",
            "exceeds the 150-line budget",
            "narrates a historical revision as current",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, joined)


if __name__ == "__main__":
    unittest.main()
