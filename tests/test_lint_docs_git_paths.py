"""Keep Git's tracked Markdown paths intact without widening lint scope."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


TOOL = Path(__file__).resolve().parents[1] / "tools" / "lint_docs.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("lint_docs_git_paths", TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=True,
        timeout=30,
    )


def write(root: Path, name: str, text: str = "# Document\n") -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class LintDocsGitPathTests(unittest.TestCase):
    def test_real_git_preserves_unicode_and_space_paths(self) -> None:
        tool = load_tool()
        names = ["README.md", "docs/日本語.md", "docs/with space.md"]
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            git(root, "init", "-q")
            for name in names:
                write(root, name)
            git(root, "add", "--", *names)
            for quote_path in ("true", "false"):
                with self.subTest(quote_path=quote_path):
                    git(root, "config", "core.quotePath", quote_path)
                    actual = [p.relative_to(root).as_posix() for p in tool.tracked_markdown(root)]
                    self.assertCountEqual(actual, names)

    def test_unicode_line_separators_are_not_record_separators(self) -> None:
        tool = load_tool()
        names = ["README.md", "docs/next\u0085line.md", "docs/next\u2028line.md"]
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            git(root, "init", "-q")
            git(root, "config", "core.quotePath", "false")
            for name in names:
                write(root, name)
            git(root, "add", "--", *names)
            actual = [p.relative_to(root).as_posix() for p in tool.tracked_markdown(root)]
            self.assertCountEqual(actual, names)

    def test_nul_protocol_preserves_control_characters_and_occurrences(self) -> None:
        tool = load_tool()
        names = ["line\r\nbreak.md", "tab\tname.md", "日本語.md", "日本語.md"]
        output = b"\0".join(os.fsencode(name) for name in names) + b"\0"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            completed = subprocess.CompletedProcess([], 0, stdout=output, stderr=b"")
            with mock.patch.object(tool.subprocess, "run", return_value=completed) as run:
                with mock.patch.object(Path, "is_file", return_value=True):
                    actual = [p.relative_to(root).as_posix() for p in tool.tracked_markdown(root)]
            self.assertEqual(actual, names)
            args, kwargs = run.call_args
            self.assertEqual(args[0], ["git", "ls-files", "-z", "--", "*.md", "**/*.md"])
            self.assertFalse(kwargs.get("text", False))
            self.assertEqual(kwargs["timeout"], 60)

    def test_real_cli_rejects_broken_link_in_unicode_tracked_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            git(root, "init", "-q")
            for name in ("README.md", "STATUS.md", "ROADMAP.md", "docs/FIVE-MINUTE-TOUR.md"):
                write(root, name)
            write(root, "docs/日本語.md", "[broken](MISSING.md)\n")
            git(root, "add", "--", ".")
            completed = subprocess.run(
                [sys.executable, "-S", "-B", str(TOOL), str(root)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                timeout=30,
            )
            self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
            self.assertEqual(len(completed.stdout.splitlines()), 1)
            report = json.loads(completed.stdout)
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(report["checked_files"], 5)
            self.assertEqual(report["errors"], ["docs/日本語.md: broken link MISSING.md"])

    def test_git_scope_and_existing_exclusions_are_preserved(self) -> None:
        tool = load_tool()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            git(root, "init", "-q")
            names = ["README.md", "docs/日本語.md", "work/ignored.md", "node_modules/ignored.md"]
            for name in names:
                write(root, name)
            git(root, "add", "--", *names)
            write(root, "untracked.md", "[broken](MISSING.md)\n")
            actual = [p.relative_to(root).as_posix() for p in tool.tracked_markdown(root)]
            self.assertCountEqual(actual, ["README.md", "docs/日本語.md"])

    def test_missing_git_or_failed_listing_preserves_archive_fallback(self) -> None:
        tool = load_tool()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write(root, "README.md")
            write(root, "日本語.md")
            write(root, "work/ignored.md")
            for mode in ("missing", "failed", "timeout"):
                with self.subTest(mode=mode):
                    kwargs = (
                        {"return_value": subprocess.CompletedProcess([], 128, stdout=b"", stderr=b"not a repository")}
                        if mode == "failed"
                        else {"side_effect": FileNotFoundError("git") if mode == "missing" else subprocess.TimeoutExpired("git", 60)}
                    )
                    with mock.patch.object(tool.subprocess, "run", **kwargs):
                        actual = [p.relative_to(root).as_posix() for p in tool.tracked_markdown(root)]
                    self.assertCountEqual(actual, ["README.md", "日本語.md"])

    def test_empty_listing_preserves_existing_archive_fallback(self) -> None:
        tool = load_tool()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write(root, "README.md")
            completed = subprocess.CompletedProcess([], 0, stdout=b"", stderr=b"")
            with mock.patch.object(tool.subprocess, "run", return_value=completed):
                self.assertEqual(tool.tracked_markdown(root), [root / "README.md"])


if __name__ == "__main__":
    unittest.main()
