"""Linux development contract and exact child cleanup, without upstream execution."""
import io
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import run_cloudflare_linux_evaluation as runner

try:
    import psutil
except ImportError:
    psutil = None


class LinuxEvaluationTests(unittest.TestCase):
    def test_only_named_finite_local_commands_are_admitted(self):
        self.assertEqual(runner.command_arguments("build"), ["run", "build"])
        for command in ("install", "run-local", "deploy", "exec wrangler dev --remote", "test --watch", "build; install"):
            with self.subTest(command=command), self.assertRaises(runner.CandidateViolation):
                runner.command_arguments(command)

    def test_environment_does_not_inherit_provider_or_loader_settings(self):
        with patch.dict(os.environ, {"PATH": "/ambient", "CLOUDFLARE_API_TOKEN": "synthetic", "NODE_OPTIONS": "synthetic", "npm_config_userconfig": "/ambient"}):
            env = runner.clean_environment(PurePosixPath("/owned/home"), PurePosixPath("/owned/bin"))
        self.assertEqual(env["PATH"], "/owned/bin:/usr/bin:/bin")
        self.assertNotIn("CLOUDFLARE_API_TOKEN", env)
        self.assertNotIn("NODE_OPTIONS", env)
        self.assertEqual(env["npm_config_userconfig"], "/owned/home/npmrc")
        self.assertEqual(env["npm_config_offline"], "true")

    def test_windows_refuses_before_any_runtime_launch(self):
        with patch.object(runner.sys, "platform", "win32"), patch.object(runner.subprocess, "Popen") as launch:
            with self.assertRaises(runner.CandidateViolation):
                runner.preflight(Path("/core"), Path("/node"), Path("/pnpm"), {})
        launch.assert_not_called()

    @unittest.skipUnless(sys.platform == "linux" and psutil is not None, "Linux and locked psutil required")
    def test_timeout_stops_owned_grandchild_and_preserves_unrelated_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outsider = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
            identity = psutil.Process(outsider.pid).create_time()
            try:
                code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); time.sleep(30)"
                with (root / "log").open("wb") as log:
                    result = runner.owned_run([sys.executable, "-c", code], root, dict(os.environ), log, 0.5)
                self.assertEqual(result["reason"], "timeout")
                self.assertGreaterEqual(result["tracked_processes"], 2)
                self.assertEqual(result["owned_processes_remaining"], 0)
                self.assertIsNone(outsider.poll())
            finally:
                other = psutil.Process(outsider.pid)
                if other.create_time() == identity:
                    other.terminate()
                outsider.wait(timeout=3)

    @unittest.skipUnless(sys.platform == "linux" and psutil is not None, "Linux and locked psutil required")
    def test_failed_command_remains_failed_with_zero_owned_processes(self):
        with tempfile.TemporaryDirectory() as temporary:
            with (Path(temporary) / "log").open("wb") as log:
                result = runner.owned_run([sys.executable, "-c", "raise SystemExit(7)"], temporary, dict(os.environ), log, 3)
        self.assertEqual(result["exit_code"], 7)
        self.assertEqual(result["owned_processes_remaining"], 0)

    @unittest.skipUnless(sys.platform == "linux" and psutil is not None, "Linux and locked psutil required")
    def test_immediate_leader_exit_does_not_hide_living_grandchild(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            code = "import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])"
            with (root / "log").open("wb") as log:
                result = runner.owned_run([sys.executable, "-c", code], root, dict(os.environ), log, 3)
        self.assertEqual(result["exit_code"], 0)
        self.assertGreaterEqual(result["tracked_processes"], 2)
        self.assertEqual(result["owned_processes_remaining"], 0)

    @unittest.skipUnless(sys.platform == "linux" and psutil is not None, "Linux and locked psutil required")
    def test_wildcard_listener_is_not_reported_as_loopback(self):
        with tempfile.TemporaryDirectory() as temporary:
            code = "import socket,time; s=socket.socket(); s.bind(('0.0.0.0',0)); s.listen(); time.sleep(30)"
            with (Path(temporary) / "log").open("wb") as log:
                result = runner.owned_run([sys.executable, "-c", code], temporary, dict(os.environ), log, 0.5, observe_listeners=True)
        self.assertTrue(result["listeners_observed"])
        self.assertFalse(result["all_listeners_loopback"])
        self.assertEqual(result["owned_listeners_remaining"], 0)


if __name__ == "__main__":
    unittest.main()
