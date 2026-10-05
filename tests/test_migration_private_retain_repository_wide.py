"""Owned Git repositories prove batch-external migration-copy detection."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import check_migration_source_hygiene as scanner


def blob(data):
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


class MigrationRepositoryHygieneTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.original = b"synthetic donor content\n"
        self.source_path = "synthetic-private/retained.txt"
        self.manifest = "migration/fixture.manifest.json"
        rows = [{"source_path": self.source_path, "source_blob_sha": blob(self.original),
                 "decision": "PRIVATE_RETAIN"},
                {"source_path": "synthetic-private/obsolete.txt", "source_blob_sha": blob(b"superseded"),
                 "decision": "SUPERSEDED"}]
        self.policy = {self.manifest: scanner.mapping_digest(rows)}
        self.write(self.manifest, json.dumps({"entries": rows}).encode())
        self.git("init", "--quiet", "--template=")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "synthetic baseline")

    def git(self, *args, input=None):
        environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        return subprocess.run(["git", *args], cwd=self.root, env=environment,
                              input=input, capture_output=True, check=True, timeout=10).stdout

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def scan(self):
        return scanner.scan(self.root, self.policy)

    def codes(self, report):
        return {f["code"] for f in report["findings"]}

    def test_current_repository_and_real_cli(self):
        result = subprocess.run([sys.executable, "-B", str(ROOT / "tools/check_migration_source_hygiene.py")],
                                cwd=self.root, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual((report["status"], report["source_blob_count"], report["restricted_path_count"]),
                         ("PASS", 32, 13))
        self.assertGreater(report["checked_snapshots"], 600)
        self.assertEqual(result.stderr, "")

    def test_external_copy_in_index_survives_working_file_deletion(self):
        path = self.write("unrelated/copied.bin", self.original)
        self.git("add", ".")
        path.unlink()
        report = self.scan()
        self.assertIn("SOURCE_BLOB_REUSED", self.codes(report))
        self.assertTrue(any(f["snapshot"] == "index" for f in report["findings"]))
        self.assertNotIn(self.original.decode().strip(), json.dumps(report))

    def test_head_copy_is_detected_after_index_and_working_tree_delete(self):
        self.write("unrelated/copied.bin", self.original)
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "synthetic forbidden copy")
        self.git("rm", "--quiet", "unrelated/copied.bin")
        report = self.scan()
        self.assertIn("SOURCE_BLOB_REUSED", self.codes(report))
        self.assertTrue(any(f["snapshot"] == "HEAD" for f in report["findings"]))

    def test_unstaged_copy_and_superseded_copy_are_detected(self):
        path = self.write("unrelated/copied.bin", b"permitted draft")
        self.git("add", ".")
        for data in (self.original, b"superseded"):
            with self.subTest(size=len(data)):
                path.write_bytes(data)
                report = self.scan()
                self.assertIn("SOURCE_BLOB_REUSED", self.codes(report))
                self.assertTrue(any(f["snapshot"] == "working tree" for f in report["findings"]))

    def test_path_detection_binary_bom_and_redacted_path_label(self):
        path = self.write("other/notes.bin", b"permitted")
        self.git("add", ".")
        for data in (b"\x00\n" + self.source_path.encode(),
                     b"\xff\xfe\n\x00" + self.source_path.encode(),
                     b"\xff\xfe\n\x00" + self.source_path.encode() + b"\xff",
                     ("intro\n" + self.source_path).encode("utf-16"),
                     ("intro\n" + self.source_path).encode("utf-32")):
            with self.subTest(size=len(data)):
                path.write_bytes(data)
                report = self.scan()
                findings = [f for f in report["findings"] if f["code"] == "SOURCE_PATH_COPIED"]
                self.assertEqual(len(findings), 1)
                self.assertEqual(findings[0]["line"], 2)
                self.assertNotIn(self.source_path, json.dumps(report))
        self.write(self.source_path, self.original)
        self.git("add", self.source_path)
        self.assertNotIn(self.source_path, json.dumps(self.scan()))

    def test_unrelated_dates_contacts_and_changelog_do_not_fail(self):
        self.write("CHANGELOG.md", b"2026-10-06: fixture@example.invalid; public documentation update\n")
        self.git("add", ".")
        self.assertEqual(self.scan()["findings"], [])

    def test_manifest_cannot_remove_or_reclassify_the_source_inventory(self):
        path = self.root / self.manifest
        original = path.read_bytes()
        for change in (lambda p: p["entries"].pop(),
                       lambda p: p["entries"][0].update(decision="PUBLIC_REAUTHOR"),
                       lambda p: p["entries"][0].update(source_blob_sha="0" * 40)):
            value = json.loads(original)
            change(value)
            path.write_text(json.dumps(value))
            self.assertIn("SCAN_INCOMPLETE", self.codes(self.scan()))
        path.write_bytes(original)
        self.git("rm", "--cached", self.manifest)
        self.assertIn("SCAN_INCOMPLETE", self.codes(self.scan()))

    def test_manifest_is_not_a_blanket_path_exemption(self):
        path = self.root / self.manifest
        value = json.loads(path.read_bytes())
        value["unapproved_copy"] = self.source_path
        path.write_text(json.dumps(value))
        self.assertIn("SOURCE_PATH_COPIED", self.codes(self.scan()))

    def test_unreadable_or_oversized_file_is_not_silently_skipped(self):
        self.write("oversized.bin", b"x" * (scanner.MAX_BYTES + 1))
        self.git("add", ".")
        report = self.scan()
        self.assertIn("FILE_TOO_LARGE", self.codes(report))
        self.assertIn("FILE_UNREADABLE", self.codes(report))

    def test_blob_reads_are_batched_and_do_not_fetch_source_objects(self):
        for index in range(50):
            self.write(f"unrelated/{index}.txt", f"permitted {index}".encode())
        self.git("add", ".")
        original_git = scanner.git
        with mock.patch.object(scanner, "git", wraps=original_git) as calls:
            self.assertEqual(self.scan()["status"], "PASS")
        reads = [c for c in calls.call_args_list if c.args[1:3] == ("cat-file", "--batch")]
        self.assertEqual(len(reads), 1)
        self.assertNotIn(blob(self.original).encode(), reads[0].kwargs["input"])

    def test_repository_failure_has_no_exception_or_selected_root_in_report(self):
        with tempfile.TemporaryDirectory(prefix="unreported-fixture-") as temporary:
            result = scanner.scan(Path(temporary), self.policy)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(self.codes(result), {"SCAN_INCOMPLETE"})
            self.assertNotIn(temporary, json.dumps(result))


if __name__ == "__main__":
    unittest.main()
