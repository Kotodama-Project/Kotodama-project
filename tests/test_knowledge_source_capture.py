"""Source capture keeps pathlib semantics and the complete file-change gates."""
from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from kotodama_kb import cli, foundation, session

AS_OF = "2026-10-10T00:00:00Z"


class SourceCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = cli.load_bundle(ROOT, as_of=cli._parse_as_of(AS_OF))

    def test_posix_and_windows_relative_semantics_match_pathlib(self):
        cases = [
            (PurePosixPath, "/root", "/root/a/b.md"),
            (PurePosixPath, "/root", "/root"),
            (PurePosixPath, "/root", "/rooted/a.md"),
            (PurePosixPath, "/root", "/root/../outside.md"),
            (PurePosixPath, "/root", "root/a.md"),
            (PurePosixPath, ".", "/root/a.md"),
            (PurePosixPath, ".", "a/b.md"),
            (PurePosixPath, "a", "a/b.md"),
            (PurePosixPath, "/", "/日本語/δοκιμή.md"),
            (PurePosixPath, "//root", "//root/a.md"),
            (PureWindowsPath, "C:/root", "C:/root/a/b.md"),
            (PureWindowsPath, "C:/ROOT", "c:/root/A.md"),
            (PureWindowsPath, "C:/root", "D:/root/a.md"),
            (PureWindowsPath, "C:/root", "C:root/a.md"),
            (PureWindowsPath, "C:/root", "C:/rooted/a.md"),
            (PureWindowsPath, ".", "C:/root/a.md"),
            (PureWindowsPath, "//server/share/root", "//SERVER/SHARE/ROOT/a.md"),
            (PureWindowsPath, "//server/share/root", "//server/other/root/a.md"),
        ]
        paths = [(factory(root), factory(path)) for factory, root, path in cases]
        paths.append((PureWindowsPath("C:a"), PurePosixPath("C:/a")))
        for root, path in paths:
            with self.subTest(root=str(root), path=str(path)):
                try:
                    expected = path.relative_to(root).as_posix()
                except ValueError:
                    with self.assertRaises(ValueError):
                        foundation._relative_input_path(path, root, root.parts)
                else:
                    self.assertEqual(expected, foundation._relative_input_path(path, root, root.parts))

    def tiny_bundle(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name).resolve()
        knowledge = root / "knowledge"
        knowledge.mkdir()
        (knowledge / "a.md").write_bytes(b"source A\n")
        (root / "external.md").write_bytes(b"source B\n")
        paths = [knowledge / "a.md", root / "external.md"]
        bound = foundation._capture_inputs(root, paths)
        return root, dataclasses.replace(self.bundle, root=root, bundle_root=knowledge, input_bindings=bound)

    def test_exact_bytes_sorted_names_and_full_stat_reads_remain(self):
        root, bundle = self.tiny_bundle()
        actual_read = foundation._read_bytes
        actual_resolve = Path.resolve
        read, resolved = [], []
        def capture(path):
            read.append(path)
            return actual_read(path)
        def resolve(path, *args, **kwargs):
            resolved.append(path)
            return actual_resolve(path, *args, **kwargs)
        with mock.patch.object(foundation, "_read_bytes", side_effect=capture), \
             mock.patch.object(Path, "resolve", resolve):
            foundation._assert_current(bundle)
        self.assertEqual(["external.md", "knowledge/a.md"], [p.relative_to(root).as_posix() for p in read])
        self.assertEqual(read, resolved)
        self.assertEqual(bundle.input_bindings, foundation._capture_inputs(root, reversed(read)))

    def test_changed_source_bytes_and_directory_membership_refuse(self):
        for change in ("same_size_mtime", "add", "delete", "rename", "external"):
            with self.subTest(change=change):
                root, bundle = self.tiny_bundle()
                path = root / "knowledge/a.md"
                if change == "same_size_mtime":
                    before = path.stat()
                    path.write_bytes(b"source Z\n")
                    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
                elif change == "add":
                    (root / "knowledge/new.md").write_bytes(b"new\n")
                elif change == "delete":
                    path.unlink()
                elif change == "rename":
                    path.rename(path.with_name("renamed.md"))
                else:
                    (root / "external.md").write_bytes(b"source X\n")
                with self.assertRaises(foundation.KnowledgeBaseError):
                    foundation._assert_current(bundle)

    def test_parent_escape_is_checked_after_realpath_resolution(self):
        root, _ = self.tiny_bundle()
        sibling = root.parent / (root.name + "-outside.md")
        sibling.write_bytes(b"outside")
        self.addCleanup(lambda: sibling.unlink(missing_ok=True))
        escaped = root / "knowledge" / ".." / ".." / sibling.name
        with self.assertRaisesRegex(foundation.KnowledgeBaseError, "INPUT_OUTSIDE_REPOSITORY"):
            foundation._capture_inputs(root, [escaped])

    def full_fixture(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        shutil.copytree(ROOT / "knowledge", root / "knowledge")
        for relative, _ in self.bundle.input_bindings:
            target = root / relative
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, target)
        return root

    def test_mutation_during_execution_is_refused_at_final_guard(self):
        for change in ("same_size_mtime", "add", "delete", "rename", "external"):
            with self.subTest(change=change):
                root = self.full_fixture()
                instance = session.KnowledgeSession(root)
                raw = json.dumps({"id": "find", "args": ["query", "KGI", "--as-of", AS_OF]}).encode()
                self.assertTrue(json.loads(instance.handle(raw))["ok"])
                execute = cli._execute
                def mutate(*args, **kwargs):
                    result = execute(*args, **kwargs)
                    path = root / "knowledge/project/goal.md"
                    if change == "same_size_mtime":
                        before = path.stat()
                        path.write_bytes(path.read_bytes().replace(b"Kotodama", b"kotodama"))
                        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
                    elif change == "add":
                        (root / "knowledge/new.md").write_bytes(b"new\n")
                    elif change == "delete":
                        path.unlink()
                    elif change == "rename":
                        path.rename(path.with_name("renamed.md"))
                    else:
                        path = root / "docs/PROJECT-MAP.md"
                        path.write_bytes(path.read_bytes() + b"\nchanged\n")
                    return result
                with mock.patch.object(cli, "_execute", side_effect=mutate):
                    response = json.loads(instance.handle(raw))
                self.assertFalse(response["ok"], response)
                self.assertNotIn("result", response)


if __name__ == "__main__":
    unittest.main()
