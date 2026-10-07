"""Behavioral tests for a nonblocking, private, repeatable setup hook."""
from contextlib import ExitStack
import hashlib
import importlib.util
import io
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("agent_environment_setup", ROOT / "tools/dev/setup_agent_env.py")
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


class AgentEnvironmentSetupTests(unittest.TestCase):
    def test_local_hook_does_not_create_workspace_or_run_tools(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {"CLAUDE_CODE_REMOTE": "false"}), patch.object(setup, "run") as run:
            target = Path(temporary) / "unused"
            self.assertEqual(setup.prepare(target, hook=True), {"status": "SKIPPED_LOCAL_HOOK"})
            self.assertFalse(target.exists())
            run.assert_not_called()

    def test_dependency_environment_excludes_ambient_credentials_and_package_config(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic-not-a-key", "GITHUB_TOKEN": "synthetic", "NPM_TOKEN": "synthetic", "PIP_INDEX_URL": "https://example.invalid", "NODE_OPTIONS": "--require injected", "HTTPS_PROXY": "http://proxy.invalid"}, clear=True):
            env = setup.safe_environment(Path("work/example"))
        for key in ("OPENAI_API_KEY", "GITHUB_TOKEN", "NPM_TOKEN", "PIP_INDEX_URL", "NODE_OPTIONS"):
            self.assertNotIn(key, env)
        self.assertEqual(env["HTTPS_PROXY"], "http://proxy.invalid")
        self.assertEqual(env["npm_config_registry"], "https://registry.npmjs.org/")

    def test_bad_archive_digest_never_extracts(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "node"
            destination.with_suffix(".archive").write_bytes(b"different bytes")
            with self.assertRaises(setup.Unavailable):
                setup.verified_archive("https://example.invalid", destination, "0" * 64, "sha256")
            self.assertFalse(destination.exists())

    def test_archive_traversal_does_not_publish_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "node"
            archive = destination.with_suffix(".archive")
            with tarfile.open(archive, "w") as output:
                member = tarfile.TarInfo("../../outside")
                member.size = 1
                output.addfile(member, io.BytesIO(b"x"))
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            with self.assertRaises(setup.Unavailable):
                setup.verified_archive("https://example.invalid", destination, digest, "sha256")
            self.assertFalse(destination.exists())
            self.assertFalse((Path(temporary) / "outside").exists())

    def fixture(self, root):
        for name in (*setup.LOCKS, "runtime/discord-template/pnpm-lock.yaml", "runtime/discord-template/package.json", "tools/dev/setup_agent_env.py"):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / name).read_bytes())

    def test_ready_repeat_skips_installs_and_lock_change_reinstalls(self):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            self.fixture(root)
            calls = []

            def command(args, *, cwd, env, timeout=180, output=False):
                calls.append(args)
                if "--version" in args:
                    return "11.19.0" if "corepack.js" in " ".join(args) else "v24.14.0"
                if "venv" in args:
                    python = Path(args[-1]) / "bin/python"
                    python.parent.mkdir(parents=True)
                    python.write_text("fixture", encoding="utf-8")
                if "--frozen-lockfile" in args:
                    marker = cwd / "node_modules/.modules.yaml"
                    marker.parent.mkdir(parents=True, exist_ok=True)
                    marker.write_text("fixture", encoding="utf-8")
                return ""

            stack.enter_context(patch.object(setup.sys, "platform", "linux"))
            stack.enter_context(patch.object(setup.sys, "version_info", (3, 12, 10)))
            stack.enter_context(patch.object(setup.shutil, "which", return_value=str(root / "node")))
            stack.enter_context(patch.object(setup, "verified_archive"))
            stack.enter_context(patch.object(setup, "run", side_effect=command))
            first = setup.prepare(root)
            self.assertEqual(first["status"], "READY")
            self.assertFalse(first["cached"])
            installs = [call for call in calls if "install" in call]
            self.assertEqual(len(installs), 2)
            self.assertIn("--require-hashes", installs[0])
            self.assertIn("--ignore-scripts", installs[1])
            self.assertIn("--frozen-lockfile", installs[1])
            calls.clear()
            self.assertTrue(setup.prepare(root)["cached"])
            self.assertFalse(any("install" in call and "--dry-run" not in call for call in calls))
            with (root / setup.LOCKS[0]).open("a", encoding="utf-8") as stream:
                stream.write("\n# changed lock\n")
            calls.clear()
            self.assertFalse(setup.prepare(root)["cached"])
            self.assertEqual(sum("install" in call for call in calls), 2)
            self.assertFalse((root / "work/agent-env/setup.lock").exists())

    def test_failure_is_actionable_and_does_not_create_ready_receipt(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(setup.sys, "platform", "linux"), patch.object(setup.sys, "version_info", (3, 12, 10)), patch.object(setup, "run", side_effect=setup.Unavailable("private detail")):
            root = Path(temporary)
            result = setup.prepare(root)
            self.assertEqual(result["status"], "INCOMPLETE")
            self.assertEqual(result["stage"], "credential gate")
            self.assertNotIn("private detail", json.dumps(result))
            self.assertFalse((root / "work/agent-env/ready.json").exists())
            self.assertFalse((root / "work/agent-env/setup.lock").exists())

    def test_initial_write_failure_is_nonblocking(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(setup.sys, "platform", "linux"), patch.object(setup.sys, "version_info", (3, 12, 10)), patch.object(Path, "mkdir", side_effect=PermissionError("private detail")):
            result = setup.prepare(Path(temporary))
            self.assertEqual(result["status"], "INCOMPLETE")
            self.assertIn("write access", result["stage"])
            self.assertNotIn("private detail", json.dumps(result))

    def test_external_work_and_child_links_do_not_write_outside(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(setup.sys, "platform", "linux"), patch.object(setup.sys, "version_info", (3, 12, 10)), patch.object(setup, "run") as run:
            base = Path(temporary)
            outside = base / "outside"
            outside.mkdir()
            for relative in ("work", "work/agent-env/bin", "work/agent-env/venv"):
                with self.subTest(relative=relative):
                    root = base / relative.replace("/", "-")
                    root.mkdir()
                    link = root / relative
                    link.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        link.symlink_to(outside, target_is_directory=True)
                    except OSError:
                        self.skipTest("host does not permit test symlinks")
                    self.assertEqual(setup.prepare(root)["status"], "INCOMPLETE")
                    self.assertEqual(list(outside.iterdir()), [])
            run.assert_not_called()

    @unittest.skipUnless(shutil.which("node"), "Node is needed for real dependency probe")
    def test_real_node_probe_rejects_missing_dependency_and_entry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"dependencies":{"fixture":"1.0.0"}}', encoding="utf-8")
            package = root / "node_modules/fixture"
            package.mkdir(parents=True)
            (package / "package.json").write_text('{"version":"1.0.0","main":"index.js"}', encoding="utf-8")
            entry = package / "index.js"
            entry.write_text("module.exports = {};", encoding="utf-8")
            script = root / "dependency-probe.cjs"
            script.write_text(setup.NODE_DEPENDENCY_PROBE, encoding="utf-8")
            def probe():
                return subprocess.run([shutil.which("node"), str(script)], cwd=root, capture_output=True, timeout=10).returncode
            self.assertEqual(probe(), 0)
            entry.unlink()
            self.assertNotEqual(probe(), 0)
            (package / "package.json").unlink()
            self.assertNotEqual(probe(), 0)

    @unittest.skipUnless(sys.platform == "linux", "Linux cloud hook")
    def test_real_bash_hook_returns_zero_without_cloud_flag(self):
        env = dict(os.environ, CLAUDE_CODE_REMOTE="false")
        result = subprocess.run(["bash", str(ROOT / "tools/dev/setup_agent_env.sh"), "--hook"], env=env, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")


if __name__ == "__main__":
    unittest.main()
