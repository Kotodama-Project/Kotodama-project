"""Offline Git-fixture tests; these do not claim a native OS build or live use."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "prepare_cloudflare_native", Path(__file__).resolve().parents[1]
    / "tools/prepare_cloudflare_native.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class NativeWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="native-workspace-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.core = self.init_repo("core")
        self.repo = self.init_repo("kotodama")
        self.destination = self.root / "prepared"
        self.write(self.core, "package.json", json.dumps({
            "packageManager": "pnpm@11.17.0+sha512." + "a" * 128}))
        self.write(self.core, "packages/workshop-backend/format-blueprints/original/README.md",
                   "Synthetic upstream blueprint.\n")
        self.write(self.core, "scripts/run-local.ts", "// Synthetic; never executed.\n")
        self.pin = self.commit(self.core)
        self.manifest = {"upstream": {
            "repository": "cloudflare/cloudflare-os",
            "compatibility_commit": self.pin,
            "extension_path": MODULE.EXTENSION,
        }}
        self.write_manifest()
        for relative in MODULE.REQUIRED:
            self.write(self.repo, MODULE.EXTENSION + "/" + relative,
                       "synthetic source: " + relative + "\n")
        self.source_commit = self.commit(self.repo)

    def init_repo(self, name):
        path = self.root / name
        path.mkdir()
        MODULE.git(path, "init", "--quiet")
        MODULE.git(path, "config", "user.name", "Fixture")
        MODULE.git(path, "config", "user.email", "fixture@example.invalid")
        return path

    @staticmethod
    def write(repo, relative, content):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")

    @staticmethod
    def commit(repo):
        MODULE.git(repo, "add", "--all")
        MODULE.git(repo, "commit", "--quiet", "-m", "fixture")
        return MODULE.git(repo, "rev-parse", "HEAD").decode().strip()

    def write_manifest(self):
        self.write(self.repo, MODULE.MANIFEST, json.dumps(self.manifest))

    def prepare(self, **kwargs):
        return MODULE.prepare(self.repo, self.destination, source_core=self.core, **kwargs)

    def test_copies_exact_snapshot_into_real_detached_git_checkout(self):
        result = self.prepare()
        self.assertEqual(result["status"], "PREPARED_NOT_INSTALLED")
        self.assertEqual(result["core_commit"], self.pin)
        self.assertEqual(result["kotodama_commit"], self.source_commit)
        self.assertFalse(result["runtime_started"])
        self.assertEqual(result["copied_files"], len(MODULE.REQUIRED))
        self.assertEqual(MODULE.git(self.destination, "rev-parse", "HEAD").decode().strip(), self.pin)
        self.assertEqual(MODULE.git(self.destination, "branch", "--show-current"), b"")
        self.assertEqual(MODULE.git(self.destination, "diff", "HEAD"), b"")
        self.assertEqual(MODULE.git(self.core, "status", "--porcelain"), b"")
        for source, target in MODULE.MOUNTS.items():
            for path in (self.repo / MODULE.EXTENSION / source).rglob("*"):
                if path.is_file():
                    self.assertEqual((self.destination / target / path.relative_to(
                        self.repo / MODULE.EXTENSION / source)).read_bytes(), path.read_bytes())
        self.assertFalse((self.destination / "node_modules").exists())
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_same_refs_produce_same_files_in_a_second_checkout(self):
        first = self.prepare()
        second_path = self.root / "second"
        second = MODULE.prepare(self.repo, second_path, source_core=self.core)
        self.assertEqual(first, second)
        for target in MODULE.MOUNTS.values():
            first_root = self.destination / target
            for path in first_root.rglob("*"):
                if path.is_file():
                    self.assertEqual(path.read_bytes(), (second_path / target /
                                     path.relative_to(first_root)).read_bytes())

    def test_ignores_dirty_and_untracked_data_without_changing_sources(self):
        source = "gatekeeper-kotodama-brief/src/kotodama.ts"
        self.write(self.repo, MODULE.EXTENSION + "/" + source, "UNCOMMITTED\n")
        self.write(self.repo, MODULE.EXTENSION + "/gatekeeper-kotodama-brief/.env", "LOCAL\n")
        self.write(self.repo, MODULE.EXTENSION + "/gatekeeper-kotodama-brief/node_modules/x", "LOCAL\n")
        self.write(self.core, "package.json", "UNCOMMITTED UPSTREAM\n")
        self.write(self.core, "runtime-state.json", "LOCAL\n")
        before = MODULE.git(self.repo, "status", "--porcelain")
        before_core = MODULE.git(self.core, "status", "--porcelain")
        self.prepare()
        target = self.destination / "packages" / source
        self.assertEqual(target.read_text(), "synthetic source: " + source + "\n")
        self.assertFalse((target.parents[1] / ".env").exists())
        self.assertFalse((target.parents[1] / "node_modules").exists())
        self.assertFalse((self.destination / "runtime-state.json").exists())
        self.assertEqual(before, MODULE.git(self.repo, "status", "--porcelain"))
        self.assertEqual(before_core, MODULE.git(self.core, "status", "--porcelain"))

    def test_selected_commit_not_current_working_tree_controls_pin(self):
        self.manifest["upstream"]["compatibility_commit"] = "f" * 40
        self.write_manifest()
        self.commit(self.repo)
        self.assertEqual(self.prepare(ref=self.source_commit)["core_commit"], self.pin)

    def test_existing_directory_or_file_is_never_overwritten(self):
        for kind in ("directory", "file"):
            with self.subTest(kind=kind):
                destination = self.root / kind
                if kind == "directory":
                    destination.mkdir()
                    self.write(destination, "keep.txt", "KEEP\n")
                else:
                    destination.write_text("KEEP\n")
                with self.assertRaisesRegex(MODULE.PreparationError, "destination_exists"):
                    MODULE.prepare(self.repo, destination, source_core=self.core)
                kept = destination / "keep.txt" if kind == "directory" else destination
                self.assertEqual(kept.read_text(), "KEEP\n")

    @unittest.skipIf(os.name == "nt", "creating filesystem symlinks requires Windows privilege")
    def test_dangling_destination_symlink_is_not_followed(self):
        missing = self.root / "missing"
        self.destination.symlink_to(missing, target_is_directory=True)
        with self.assertRaisesRegex(MODULE.PreparationError, "destination_exists"):
            self.prepare()
        self.assertFalse(missing.exists())
        self.assertTrue(self.destination.is_symlink())

    def test_refuses_to_vendor_core_into_either_source_repository(self):
        for parent in (self.repo, self.core):
            with self.subTest(parent=parent.name):
                with self.assertRaisesRegex(MODULE.PreparationError, "destination_inside_source"):
                    MODULE.prepare(self.repo, parent / "nested", source_core=self.core)
                self.assertFalse((parent / "nested").exists())

    def test_invalid_pin_repository_and_mount_fail_before_creating_destination(self):
        for field, value in (("repository", "other/repo"),
                             ("compatibility_commit", "main"),
                             ("compatibility_commit", 42),
                             ("extension_path", "../private")):
            with self.subTest(field=field):
                original = self.manifest["upstream"][field]
                self.manifest["upstream"][field] = value
                self.write_manifest()
                self.commit(self.repo)
                with self.assertRaisesRegex(MODULE.PreparationError, "invalid_native_source_pin"):
                    self.prepare()
                self.assertFalse(self.destination.exists())
                self.manifest["upstream"][field] = original

    def test_malformed_manifest_is_refused_before_creation(self):
        for value in ([], {"upstream": None}):
            with self.subTest(value=value):
                self.write(self.repo, MODULE.MANIFEST, json.dumps(value))
                self.commit(self.repo)
                with self.assertRaisesRegex(MODULE.PreparationError, "invalid_native_source_pin"):
                    self.prepare()
                self.assertFalse(self.destination.exists())

    def test_tracked_runtime_configuration_is_not_copied(self):
        self.write(self.repo, MODULE.EXTENSION + "/gatekeeper-kotodama-brief/.dev.vars",
                   "SYNTHETIC LOCAL CONFIGURATION\n")
        self.commit(self.repo)
        with self.assertRaisesRegex(MODULE.PreparationError, "runtime_state_in_addon"):
            self.prepare()
        self.assertFalse(self.destination.exists())

    def test_ambient_git_directory_and_index_do_not_redirect_the_work(self):
        with patch.dict(os.environ, {"GIT_DIR": str(self.root / "absent"),
                                     "GIT_INDEX_FILE": str(self.root / "other-index")}):
            result = self.prepare()
        self.assertEqual(result["core_commit"], self.pin)
        self.assertFalse((self.root / "other-index").exists())

    def test_missing_native_entrypoint_is_not_a_success(self):
        (self.repo / MODULE.EXTENSION / "blueprints/kotodama-requirements/files/server.js").unlink()
        self.commit(self.repo)
        with self.assertRaisesRegex(MODULE.PreparationError, "incomplete_native_addon"):
            self.prepare()
        self.assertFalse(self.destination.exists())

    def test_committed_symlink_is_rejected_without_following_it(self):
        # Git plumbing gives the same test on Windows without filesystem symlink rights.
        path = MODULE.EXTENSION + "/gatekeeper-kotodama-brief/link"
        blob = MODULE.git(self.repo, "rev-parse", "HEAD:" + MODULE.MANIFEST).decode().strip()
        MODULE.git(self.repo, "update-index", "--add", "--cacheinfo", f"120000,{blob},{path}")
        MODULE.git(self.repo, "commit", "--quiet", "-m", "synthetic link")
        with self.assertRaisesRegex(MODULE.PreparationError, "unsupported_addon_entry"):
            self.prepare()
        self.assertFalse(self.destination.exists())

    def test_committed_submodule_is_not_copied(self):
        path = MODULE.EXTENSION + "/gatekeeper-kotodama-brief/vendor"
        MODULE.git(self.repo, "update-index", "--add", "--cacheinfo",
                   f"160000,{self.source_commit},{path}")
        MODULE.git(self.repo, "commit", "--quiet", "-m", "synthetic gitlink")
        with self.assertRaisesRegex(MODULE.PreparationError, "unsupported_addon_entry"):
            self.prepare()
        self.assertFalse(self.destination.exists())

    def test_unknown_commit_in_local_core_is_rejected_before_creation(self):
        self.manifest["upstream"]["compatibility_commit"] = "f" * 40
        self.write_manifest()
        self.commit(self.repo)
        with self.assertRaises(MODULE.PreparationError):
            self.prepare()
        self.assertFalse(self.destination.exists())

    def repin(self):
        self.pin = self.commit(self.core)
        self.manifest["upstream"]["compatibility_commit"] = self.pin
        self.write_manifest()
        self.commit(self.repo)

    def test_core_layout_drift_fails_without_copying_addon(self):
        MODULE.git(self.core, "mv", "packages/workshop-backend/format-blueprints",
                   "packages/workshop-backend/changed-layout")
        self.repin()
        with self.assertRaises(MODULE.PreparationError):
            self.prepare()
        self.assertFalse((self.destination / "packages/gatekeeper-kotodama-brief").exists())

    def test_existing_core_mount_is_not_overwritten(self):
        self.write(self.core, "packages/gatekeeper-kotodama-brief/keep.txt", "UPSTREAM\n")
        self.repin()
        with self.assertRaisesRegex(MODULE.PreparationError, "addon_mount_exists"):
            self.prepare()
        self.assertEqual((self.destination / "packages/gatekeeper-kotodama-brief/keep.txt")
                         .read_text(), "UPSTREAM\n")

    def test_package_manager_must_be_version_and_integrity_pinned(self):
        self.write(self.core, "package.json", '{"packageManager":"pnpm@latest"}')
        self.repin()
        with self.assertRaisesRegex(MODULE.PreparationError, "unbound_package_manager"):
            self.prepare()

    def test_unknown_ref_option_is_not_interpreted_as_a_git_argument(self):
        with self.assertRaises(MODULE.PreparationError):
            self.prepare(ref="--output=elsewhere")
        self.assertFalse(self.destination.exists())

    def test_cli_failure_never_prints_a_prepared_receipt_or_private_exception(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(MODULE, "prepare", side_effect=OSError("private-location")):
            with redirect_stdout(out), redirect_stderr(err):
                result = MODULE.main(["--destination", str(self.destination)])
        self.assertEqual(result, 1)
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(json.loads(err.getvalue()), {
            "status": "NOT_PREPARED", "error": "invalid_input_or_io"})


if __name__ == "__main__":
    unittest.main()
