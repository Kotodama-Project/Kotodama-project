"""Run the dependency-free Git Steward suite in existing unittest discovery.

Missing Node/SQLite/Git is a failure, not a silent skip or runtime-evidence claim.
"""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GitStewardRuntimeTests(unittest.TestCase):
    def test_git_steward_node_suite(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Git Steward tests require Node >=22.13 with node:sqlite")
        self.assertIsNotNone(shutil.which("git"), "Git Steward tests require Git")
        result = subprocess.run(
            [node, "--test", "--test-reporter=tap", "runtime/git-steward/coordinator.test.mjs",
             "runtime/git-steward/business-simulation.test.mjs"],
            cwd=ROOT, text=True, encoding="utf-8", errors="replace",
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout[-30000:])
        self.assertIn("# fail 0", result.stdout)
        self.assertIn("# skipped 0", result.stdout)


if __name__ == "__main__":
    unittest.main()
