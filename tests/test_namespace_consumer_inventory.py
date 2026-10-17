import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import inventory_namespace_consumers as scanner


class NamespaceInventoryTests(unittest.TestCase):
    def test_all_python_namespace_roots_are_imports(self):
        for root in ("runtime", "kotodama", "kotodama_core", "ktdm"):
            rows = scanner.scan_text("entry.py", f"import {root}.api as alias\nfrom {root} import api\n".encode())
            self.assertEqual([(r["category"], r["namespaces"]) for r in rows],
                             [("python_import", [root]), ("python_from_import", [root])])
        self.assertEqual(scanner.targets("python -m kotodama_core.cli"), ["kotodama_core"])
        self.assertEqual(scanner.targets("kotodama_coreish runtimeish"), [])

    def test_dynamic_aliases_follow_order_and_do_not_escape_nested_scopes(self):
        source = b'''import importlib as loader
loader.import_module("runtime.first")
import unrelated as loader
loader.import_module("runtime.second")
def nested():
    import importlib as loader
    loader.import_module("runtime.third")
loader.import_module("runtime.fourth")
import importlib as loader
def shadow(loader):
    loader.import_module("runtime.fifth")
def later_local():
    loader.import_module("runtime.sixth")
    import unrelated as loader
loader.import_module("runtime.seventh")
'''
        rows = scanner.scan_text("entry.py", source)
        self.assertEqual([r["line"] for r in rows if r["category"] == "dynamic_import_literal_candidate"], [2, 7, 15])
        self.assertEqual([r["line"] for r in rows if r["category"] == "python_literal_candidate"], [4, 8, 11, 13])
        rows = scanner.scan_text("entry.py", b'import unrelated as loader\nloader.import_module("runtime.x")\nimport importlib as loader\n')
        self.assertNotIn("dynamic_import_literal_candidate", {r["category"] for r in rows})

    def test_markdown_fences_require_matching_character_and_sufficient_length(self):
        raw = b'~~~~console\nktdm --help\n```\nkotodama-core --help\n~~~\npython -m kotodama_core\n~~~~\nktdm prose\n'
        rows = scanner.scan_text("README.md", raw)
        self.assertEqual([r["line"] for r in rows], [2, 4, 6])
        self.assertTrue(all(r["category"] == "document_command_candidate" for r in rows))

    def test_annotation_only_preserves_module_binding_but_shadows_function_local(self):
        module = b'import importlib as loader\nloader: object\nloader.import_module(name)\n'
        rows = scanner.scan_text("entry.py", module)
        self.assertEqual([r["line"] for r in rows if r["category"] == "computed_import_or_execution_blocked"], [3])
        function = b'import importlib as loader\ndef f(name):\n    loader: object\n    loader.import_module(name)\n'
        rows = scanner.scan_text("entry.py", function)
        self.assertNotIn("computed_import_or_execution_blocked", {r["category"] for r in rows})

    def test_unmodeled_binding_scopes_remain_explicitly_blocked(self):
        cases = [
            'import importlib as loader\ndef f(name):\n    values = [loader for loader in []]\n    loader.import_module(name)\n',
            'import importlib as loader\ndef f(name):\n    global loader\n    loader.import_module(name)\n    loader = None\n',
            'import importlib as loader\ntry:\n    pass\nexcept Exception as loader:\n    loader.import_module("runtime.x")\n',
        ]
        for source in cases:
            with self.subTest(source=source.splitlines()[1]):
                rows = scanner.scan_text("entry.py", source.encode())
                self.assertIn("python_scope_blocked", {r["category"] for r in rows})
                self.assertNotIn("dynamic_import_literal_candidate", {r["category"] for r in rows})
        rows = scanner.scan_text("entry.py", b'import kotodama_core\nfor value in []:\n    pass\n')
        self.assertIn("python_import", {r["category"] for r in rows})

    def test_old_git_has_an_explicit_capability_refusal_without_fetch_fallback(self):
        error = subprocess.CalledProcessError(129, ["git"], stderr=b"unknown option: --no-lazy-fetch")
        with patch.object(scanner.subprocess, "run", side_effect=error) as run:
            with self.assertRaisesRegex(ValueError, "GIT_NO_LAZY_FETCH_REQUIRED"):
                scanner.git(Path("."), "rev-parse", "HEAD")
        self.assertEqual(run.call_count, 1)
        self.assertIn("--no-lazy-fetch", run.call_args.args[0])

    def test_failed_private_publication_leaves_no_truncated_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); output = root / "private.json"
            with patch.object(scanner.os, "fsync", side_effect=OSError("synthetic quota")):
                with self.assertRaises(OSError):
                    scanner.publish_private(output, b'{"complete":true}')
            self.assertFalse(output.exists())
            self.assertEqual(list(root.iterdir()), [])
            scanner.publish_private(output, b'{"complete":true}')
            with self.assertRaises(FileExistsError):
                scanner.publish_private(output, b'changed')
            self.assertEqual(output.read_bytes(), b'{"complete":true}')
            self.assertEqual(list(root.iterdir()), [output])

    def test_invalid_utf8_git_path_preserves_other_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo, _ = self.fixture(Path(temporary))
            def command(*args, input_bytes=None):
                return subprocess.run(["git", "-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid",
                    "-C", str(repo), *args], input=input_bytes, check=True, capture_output=True).stdout.strip()
            blob = command("hash-object", "-w", "--stdin", input_bytes=b'import kotodama_core\n')
            tree = command("mktree", "-z", input_bytes=b'100644 blob '+blob+b'\tbroken-\xff.py\0'+b'100644 blob '+blob+b'\tvalid.py\0')
            commit = command("commit-tree", tree.decode(), input_bytes=b'synthetic paths\n').decode()
            result = scanner.inventory(repo, commit)
            self.assertEqual(result["tracked_entries"], 2)
            self.assertEqual(result["uninspected_or_blocked_files"], 1)
            self.assertEqual(result["category_counts"], {"path_encoding_blocked": 1, "python_import": 1})
            blocked = next(r for r in result["rows"] if r["category"] == "path_encoding_blocked")
            self.assertEqual(bytes.fromhex(blocked["path"].removeprefix("git-path-bytes:")), b'broken-\xff.py')
            self.assertEqual(blocked["path_encoding"], "hex")
            self.assertEqual(blocked["final_disposition"], "BLOCKED")

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

    def test_subdirectory_and_linked_worktree_cannot_write_checkout_or_git_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); repo, commit = self.fixture(root)
            nested = repo / "nested"; nested.mkdir()
            linked = root / "linked"
            subprocess.run(["git", "-C", str(repo), "worktree", "add", "--detach", str(linked), commit],
                           check=True, capture_output=True)
            linked_nested = linked / "nested"; linked_nested.mkdir()
            metadata = repo / ".git"
            for source, destination in [(nested, repo / "blocked.json"),
                                        (linked_nested, linked / "blocked.json"),
                                        (linked_nested, metadata / "blocked.json"),
                                        (linked_nested, metadata / "worktrees/linked/blocked.json")]:
                with self.subTest(source=source.name, target=destination.parent.name):
                    args = [sys.executable, "-B", str(Path(scanner.__file__)), "--source-git", str(source),
                            "--commit", commit, "--private-output", str(destination)]
                    result = subprocess.run(args, capture_output=True)
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(json.loads(result.stdout), {"status": "NAMESPACE_INVENTORY_REFUSED"})
                    self.assertFalse(destination.exists())
            for index, source in enumerate([nested, linked_nested]):
                destination = root / f"private-{index}.json"
                result = subprocess.run([sys.executable, "-B", str(Path(scanner.__file__)),
                    "--source-git", str(source), "--commit", commit, "--private-output", str(destination)],
                    capture_output=True, check=True)
                self.assertEqual(json.loads(result.stdout)["status"], "PRIVATE_INVENTORY_CANDIDATE")
                self.assertEqual(json.loads(destination.read_bytes())["source_commit"], commit)


if __name__ == "__main__":
    unittest.main()
