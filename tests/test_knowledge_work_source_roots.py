"""Integration of operator-selected evidence roots without changing package v1."""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import knowledge_work_validator as validator
import audit_knowledge_workspaces as audit
from compile_knowledge_context import compile_context

NOW = datetime(2026, 9, 9, tzinfo=timezone.utc)


class KnowledgeWorkSourceRootTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="knowledge-roots-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.workspace = self.root / "private" / "package-one"
        self.workspace.mkdir(parents=True)
        self.evidence = self.root / "source-parent" / "evidence"
        self.evidence.mkdir(parents=True)
        example = ROOT / "examples/knowledge-work/business-rehearsal"
        self.package = json.loads((example / validator.MANIFEST).read_text(encoding="utf-8"))
        for name in ("source.txt", "deliverable.md"):
            shutil.copyfile(example / name, self.evidence / name)
        self.save()

    def save(self, workspace=None):
        workspace = workspace or self.workspace
        (workspace / validator.MANIFEST).write_text(json.dumps(self.package) + "\n", encoding="utf-8")

    def validate(self, **kwargs):
        return validator.validate_package(self.workspace, NOW, source_root=self.evidence, **kwargs)[0]

    def cli(self, tool, *args):
        return subprocess.run([sys.executable, str(ROOT / "tools" / tool), *map(str, args)],
                              capture_output=True, text=True, encoding="utf-8", timeout=30)

    def test_explicit_evidence_root_without_workspace_source_copies(self):
        self.assertFalse((self.workspace / "source.txt").exists())
        self.assertFalse((self.workspace / "deliverable.md").exists())
        (self.evidence / validator.MANIFEST).write_text("not the manifest", encoding="utf-8")
        report = self.validate()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(len(report["bindings"]), 2)
        self.assertFalse(any(report["claims"].values()))
        self.assertEqual(compile_context(self.workspace, now=NOW, source_root=self.evidence)["state"], "ready_candidate")

    def test_no_implicit_parent_search_and_no_fallback_to_workspace(self):
        report, _ = validator.validate_package(self.workspace, NOW)
        self.assertEqual(report["status"], "FAIL")
        (self.workspace / "source.txt").write_bytes((self.evidence / "source.txt").read_bytes())
        (self.workspace / "deliverable.md").write_bytes((self.evidence / "deliverable.md").read_bytes())
        empty = self.root / "empty-evidence"
        empty.mkdir()
        report, _ = validator.validate_package(self.workspace, NOW, source_root=empty)
        self.assertEqual(report["status"], "FAIL")

    def test_source_and_deliverable_changes_at_explicit_root_refuse(self):
        for name, code in (("source.txt", "SOURCE_DIGEST_MISMATCH"), ("deliverable.md", "DELIVERABLE_DIGEST_MISMATCH")):
            path = self.evidence / name
            original = path.read_bytes()
            path.write_bytes(original + b" changed")
            self.assertIn(code, self.validate()["errors"])
            path.write_bytes(original)

    def test_relative_bindings_stay_under_selected_root(self):
        for case_index, relative in enumerate(("../source.txt", str(self.evidence / "source.txt"), "source.txt:ads", "a\\source.txt")):
            with self.subTest(case=("parent-path", "absolute-path", "alternate-stream", "backslash")[case_index]):
                self.package["sources"][0]["path"] = relative
                self.save()
                self.assertIn("PATH_REFUSED", self.validate()["errors"])

    def test_source_root_and_workspace_ancestor_reparse_refused(self):
        original = Path.lstat
        for ancestor in (self.evidence.parent, self.workspace.parent):
            with self.subTest(ancestor=ancestor.name):
                def marked(path, *args, **kwargs):
                    if path == ancestor:
                        return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
                    return original(path, *args, **kwargs)
                with mock.patch.object(Path, "lstat", marked):
                    self.assertIn("ROOT_REFUSED", self.validate()["errors"])

    def test_real_symlink_ancestor_refused(self):
        link = self.root / "linked-source-parent"
        try:
            link.symlink_to(self.evidence.parent, target_is_directory=True)
        except OSError as error:
            if os.name == "nt" and getattr(error, "winerror", None) == 1314:
                self.skipTest("symlink privilege unavailable")
            raise
        report, _ = validator.validate_package(self.workspace, NOW, source_root=link / "evidence")
        self.assertIn("ROOT_REFUSED", report["errors"])

    def test_unc_root_refused_before_network_filesystem_probe(self):
        for value in ("//server/share", "\\\\server\\share"):
            with self.subTest(value=value), mock.patch.object(Path, "lstat", side_effect=AssertionError("must not probe UNC")):
                with self.assertRaisesRegex(validator.Refusal, "ROOT_REFUSED"):
                    validator.selected_root(Path(value))

    def test_ceiling_refuses_before_bound_reads_or_private_metadata(self):
        self.package["sensitivity"] = "restricted"
        self.package["package_id"] = "private-package-marker"
        self.package["objective"] = "PRIVATE BODY MARKER"
        self.save()
        with mock.patch.object(validator, "read_bound", wraps=validator.read_bound) as reader:
            report = self.validate()
        self.assertIn("SENSITIVITY_CEILING", report["errors"])
        self.assertEqual([call.args[1] for call in reader.call_args_list], [validator.MANIFEST])
        self.assertIsNone(report["package_id"])
        self.assertIsNone(report["package_sha256"])
        self.assertEqual(report["bindings"], [])
        self.assertNotIn("private-package-marker", json.dumps(report))
        self.assertNotIn("PRIVATE BODY MARKER", json.dumps(report))
        self.assertEqual(self.validate(ceiling="restricted")["status"], "PASS")

    def test_ceiling_does_not_allow_sensitivity_downgrade(self):
        self.package["sources"][0]["sensitivity"] = "restricted"
        self.save()
        self.assertIn("SENSITIVITY_DOWNGRADE", self.validate(ceiling="restricted")["errors"])
        with mock.patch.object(validator, "read_bound", wraps=validator.read_bound) as reader:
            report = self.validate()
        self.assertIn("SENSITIVITY_DOWNGRADE", report["errors"])
        self.assertEqual([call.args[1] for call in reader.call_args_list], [validator.MANIFEST])

    def test_three_explicit_private_drafts_audit_without_source_copy(self):
        self.package["state"] = "draft"
        self.package["sensitivity"] = "restricted"
        self.package["questions"][0]["blocking"] = True
        args = ["--root", self.root, "--source-root", self.evidence, "--ceiling", "restricted", "--require-package"]
        for number in range(3):
            workspace = self.root / "private" / f"case-{number}"
            workspace.mkdir()
            self.package["package_id"] = f"private-case-{number}"
            self.save(workspace)
            args += ["--workspace", workspace.relative_to(self.root).as_posix()]
        result = self.cli("audit_knowledge_workspaces.py", *args)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["package_count"], 3)
        self.assertTrue(all("BLOCKING_QUESTION_OPEN" in p["warnings"] for p in report["packages"]))
        self.assertFalse(any(report["claims"].values()))

    def test_unknown_absolute_and_duplicate_explicit_workspace_refused(self):
        for case_index, workspaces in enumerate((["absent"], ["../outside"], [str(self.workspace)], ["private/package-one"] * 2)):
            with self.subTest(case=("absent", "parent-path", "absolute-path", "duplicate")[case_index]):
                args = ["--root", self.root, "--source-root", self.evidence]
                for workspace in workspaces:
                    args += ["--workspace", workspace]
                result = self.cli("audit_knowledge_workspaces.py", *args)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(json.loads(result.stdout)["errors"], ["INPUT_INVALID"])
                self.assertNotIn(str(self.root), result.stdout)

    def test_validate_and_compile_cli_share_root_and_ceiling(self):
        self.package["sensitivity"] = "restricted"
        self.save()
        for tool in ("validate_knowledge_work_package.py", "compile_knowledge_context.py"):
            with self.subTest(tool=tool):
                result = self.cli(tool, self.workspace, "--source-root", self.evidence, "--ceiling", "restricted")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                denied = self.cli(tool, self.workspace, "--source-root", self.evidence)
                self.assertEqual(denied.returncode, 1)
                self.assertIn("SENSITIVITY_CEILING", json.loads(denied.stdout)["errors"])


    def test_required_repository_audit_fails_without_packages_and_runs_real_example(self):
        empty = self.root / "empty"
        empty.mkdir()
        command = [sys.executable, str(ROOT / "tools/audit_knowledge_workspaces.py"), "--require-package", "--format", "json", "--root"]
        missing = subprocess.run([*command, str(empty)], capture_output=True, timeout=30, check=False)
        self.assertEqual(missing.returncode, 1)
        self.assertEqual(json.loads(missing.stdout)["errors"], ["PACKAGE_REQUIRED"])
        actual = subprocess.run([*command, str(ROOT)], capture_output=True, timeout=30, check=False)
        self.assertEqual(actual.returncode, 0, actual.stdout)
        self.assertGreaterEqual(json.loads(actual.stdout)["package_count"], 1)

    def test_audit_warning_policy_does_not_promote_a_draft(self):
        self.package["state"] = "draft"
        self.package["questions"][0]["blocking"] = True
        self.save()
        result = self.cli("audit_knowledge_workspaces.py", "--root", self.root,
                          "--workspace", "private/package-one", "--source-root", self.evidence,
                          "--fail-on", "warning")
        report = json.loads(result.stdout)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(report["package_count"], 1)
        self.assertIn("BLOCKING_QUESTION_OPEN", report["packages"][0]["warnings"])
        self.assertFalse(any(report["claims"].values()))

    def test_audit_checks_bound_bytes_instead_of_counting_manifests(self):
        (self.evidence / "source.txt").write_text("changed", encoding="utf-8")
        result = self.cli("audit_knowledge_workspaces.py", "--root", self.root,
                          "--workspace", "private/package-one", "--source-root", self.evidence)
        self.assertEqual(result.returncode, 1)
        self.assertIn("SOURCE_DIGEST_MISMATCH", json.loads(result.stdout)["packages"][0]["errors"])

    def test_audit_rejects_duplicate_discovered_and_explicit_packages(self):
        target = self.root / "knowledge-work" / "one"
        target.mkdir(parents=True)
        self.save(target)
        result = self.cli("audit_knowledge_workspaces.py", "--root", self.root,
                          "--workspace", "knowledge-work/one", "--source-root", self.evidence)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["errors"], ["INPUT_INVALID"])

    def test_discovery_is_streamed_and_stops_at_entry_limit(self):
        directory = self.root / "knowledge-work"
        directory.mkdir()
        consumed = []
        def entries():
            for number in range(audit.MAX_ENTRIES + 2):
                consumed.append(number)
                yield SimpleNamespace(name="irrelevant.txt", path=str(directory / str(number)),
                                      stat=lambda **kw: SimpleNamespace(st_mode=stat.S_IFREG))
        stream = mock.MagicMock()
        stream.__enter__.return_value = entries()
        with mock.patch.object(audit.os, "scandir", return_value=stream):
            with self.assertRaises(ValueError):
                audit.discover_packages(self.root, [])
        self.assertEqual(len(consumed), 4097)
        stream.__exit__.assert_called_once()

    def test_discovery_rejects_over_package_quota(self):
        directory = self.root / "knowledge-work"
        for number in range(65):
            target = directory / str(number)
            target.mkdir(parents=True)
            self.save(target)
        result = self.cli("audit_knowledge_workspaces.py", "--root", self.root)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["packages"], [])

    def test_discovery_rejects_reparse_and_reports_unreadable_directory(self):
        directory = self.root / "knowledge-work"
        directory.mkdir()
        entry = SimpleNamespace(name="linked", path=str(directory / "linked"),
                                stat=lambda **kw: SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400))
        stream = mock.MagicMock()
        stream.__enter__.return_value = iter([entry])
        with mock.patch.object(audit.os, "scandir", return_value=stream):
            with self.assertRaises(ValueError):
                audit.discover_packages(self.root, [])
        stream.__exit__.assert_called_once()
        with mock.patch.object(sys, "argv", ["audit", "--root", str(self.root)]), \
                mock.patch.object(audit.os, "scandir", side_effect=PermissionError("PRIVATE_PATH")), \
                mock.patch.object(audit, "emit") as output:
            self.assertEqual(audit.main(), 1)
        report = output.call_args.args[0]
        self.assertEqual(report["errors"], ["INPUT_INVALID"])
        self.assertNotIn("PRIVATE_PATH", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
