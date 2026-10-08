import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import inventory_namespace_consumers as scanner


class NamespaceInventoryTests(unittest.TestCase):
    def test_ast_alias_relative_serialized_names_and_computed_imports(self):
        source = b'''import runtime.app.entry as app
from runtime.app import cli
from .helper import helper
import importlib.metadata
importlib.import_module(target)
from importlib import import_module as load
load("runtime.app.cli")
resource = "runtime.app.plugin"
'''
        rows = scanner.scan_text("platform/runtime/entry.py", source)
        categories = {row["category"] for row in rows}
        self.assertTrue({"python_import", "python_from_import", "relative_runtime_import",
                         "computed_import_or_execution_blocked", "dynamic_import_literal_candidate",
                         "python_literal_candidate"} <= categories)
        self.assertNotIn("runtime.app.plugin", json.dumps(rows))

    def test_namespace_prefix_and_plain_markdown_prose_are_not_consumers(self):
        self.assertEqual(scanner.scan_text("sample.py", b'import runtimeish\nname = "kotodamax"\n'), [])
        self.assertEqual(scanner.scan_text("README.md", b'The kotodama project has a runtime.\n'), [])
        self.assertEqual(scanner.scan_text("README.md", b'Run `ktdm --help`.\n')[0]["category"], "document_command_candidate")

    def test_imports_do_not_hide_other_consumers_on_the_same_line(self):
        rows = scanner.scan_text("sample.py", b'import runtime; command = "ktdm --help"; label = "kotodama"\n')
        self.assertEqual({name for row in rows for name in row["namespaces"]}, {"runtime", "ktdm", "kotodama"})
        self.assertEqual(len(rows), 3)

    def test_parse_failure_keeps_unknown_without_exposing_source(self):
        rows = scanner.scan_text("invalid.py", b'private_marker = [\n')
        self.assertEqual(rows[0]["category"], "python_parse_blocked")
        self.assertNotIn("private_marker", json.dumps(rows))

    @staticmethod
    def fixture(root):
        repo = root / "source"; repo.mkdir()
        def run(*args):
            return subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "core.hooksPath=/dev/null",
                "-c", "commit.gpgsign=false", "-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid",
                "-C", str(repo), *args], check=True, capture_output=True).stdout
        run("init", "-q")
        (repo / "entry.py").write_text('import runtime.app.entry\nsecret_marker = "never-copy-source"\n', encoding="utf-8")
        (repo / "pyproject.toml").write_text('[project]\nname = "kotodama"\n[project.scripts]\nktdm = "runtime.app.cli:main"\n', encoding="utf-8")
        (repo / "picture.bin").write_bytes(b'\x00runtime.private')
        run("add", "entry.py", "pyproject.toml", "picture.bin"); run("commit", "-qm", "synthetic snapshot")
        return repo, run("rev-parse", "HEAD").decode().strip()

    def test_committed_snapshot_is_deterministic_and_never_reads_dirty_code(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo, commit = self.fixture(Path(temporary))
            first = scanner.inventory(repo, commit)
            marker = repo / "should-not-execute"
            (repo / "entry.py").write_text(f'from pathlib import Path\nPath({str(marker)!r}).touch()\n', encoding="utf-8")
            second = scanner.inventory(repo, commit)
            self.assertEqual(first, second)
            self.assertFalse(marker.exists())
            self.assertEqual(first["tracked_entries"], 3)
            self.assertEqual(first["uninspected_or_blocked_files"], 1)
            self.assertFalse(first["working_tree_inspected"])
            self.assertFalse(first["semantic_coverage_verified"])
            self.assertTrue(all(row["final_disposition"] == "BLOCKED" for row in first["rows"]))
            self.assertNotIn("never-copy-source", json.dumps(first))
            self.assertNotIn(str(repo), json.dumps(first))

    def test_cli_private_output_is_exclusive_and_stdout_contains_no_paths_or_bodies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); repo, commit = self.fixture(root)
            destination = root / "private.json"
            args = [sys.executable, "-B", str(Path(scanner.__file__)), "--source-git", str(repo), "--commit", commit, "--private-output", str(destination)]
            first = subprocess.run(args, capture_output=True, check=True)
            result = json.loads(first.stdout)
            self.assertEqual(result["status"], "PRIVATE_INVENTORY_CANDIDATE")
            self.assertNotIn(b"entry.py", first.stdout)
            saved = destination.read_bytes()
            second = subprocess.run(args, capture_output=True)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(destination.read_bytes(), saved)
            args[-1] = str(repo / "must-not-write.json")
            self.assertNotEqual(subprocess.run(args, capture_output=True).returncode, 0)
            self.assertFalse((repo / "must-not-write.json").exists())

    def test_file_size_limit_and_mutable_revision_are_explicitly_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo, commit = self.fixture(Path(temporary))
            with self.assertRaisesRegex(ValueError, "IMMUTABLE_COMMIT_REQUIRED"):
                scanner.inventory(repo, "HEAD")
            with patch.object(scanner, "MAX_FILE", 1):
                result = scanner.inventory(repo, commit)
            self.assertEqual(result["read_text_candidate_files"], 0)
            self.assertEqual(result["uninspected_or_blocked_files"], 3)


if __name__ == "__main__":
    unittest.main()
