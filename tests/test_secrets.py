"""Real Git index/worktree divergence regression; no live secrets or network."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("check_secrets", Path(__file__).resolve().parents[1] / "tools/check_secrets.py")
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)


class GitSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repository"
        self.root.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Synthetic fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.file = self.root / "example.txt"
        self.file.write_text("committed bytes\n", encoding="utf-8")
        self.git("add", "example.txt")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
        self.snapshot = Path(self.temporary.name) / "snapshot"

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, stderr=subprocess.PIPE)

    def test_staged_content_survives_clean_worktree_replacement(self):
        self.file.write_text("staged-only bytes\n", encoding="utf-8")
        self.git("add", "example.txt")
        self.file.write_text("clean working bytes\n", encoding="utf-8")
        scanner.snapshot_sources(self.root, self.snapshot)
        self.assertEqual((self.snapshot / "index/example.txt").read_text(), "staged-only bytes\n")
        self.assertEqual((self.snapshot / "head/example.txt").read_text(), "committed bytes\n")
        self.assertEqual((self.snapshot / "working/example.txt").read_text(), "clean working bytes\n")

    def test_deleted_working_file_does_not_hide_staged_content(self):
        self.file.write_text("staged bytes\n", encoding="utf-8")
        self.git("add", "example.txt")
        self.file.unlink()
        scanner.snapshot_sources(self.root, self.snapshot)
        self.assertEqual((self.snapshot / "index/example.txt").read_text(), "staged bytes\n")
        self.assertFalse((self.snapshot / "working/example.txt").exists())

    def test_staged_deletion_keeps_committed_content_covered(self):
        self.git("rm", "-q", "example.txt")
        scanner.snapshot_sources(self.root, self.snapshot)
        self.assertEqual((self.snapshot / "head/example.txt").read_text(), "committed bytes\n")
        self.assertFalse((self.snapshot / "index/example.txt").exists())

    def test_index_symlink_is_rejected_before_materializing_target(self):
        oid = self.git("hash-object", "-w", "example.txt").decode().strip()
        self.git("update-index", "--add", "--cacheinfo", f"120000,{oid},unsafe-link")
        with self.assertRaisesRegex(ValueError, "Non-regular"):
            scanner.snapshot_sources(self.root, self.snapshot)


if __name__ == "__main__":
    unittest.main()
