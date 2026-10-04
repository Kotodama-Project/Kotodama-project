"""Run the dependency-free Git Steward suite in existing unittest discovery.

Missing Node/SQLite/Git is a failure, not a silent skip or runtime-evidence claim.
"""
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
# node:sqlite is available without a flag from Node 22.13.
MINIMUM_NODE = (22, 13)
NODE_SUITES = ("runtime/git-steward/coordinator.test.mjs",)


def node_version(node):
    completed = subprocess.run(
        [node, "--version"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=30, check=False,
    )
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)\s*", completed.stdout)
    return (int(match.group(1)), int(match.group(2))) if match else None


def tap_count(output, name):
    match = re.search(rf"^# {name} (\d+)$", output, re.MULTILINE)
    return int(match.group(1)) if match else None


class GitStewardRuntimeTests(unittest.TestCase):
    def test_git_steward_node_suite(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Git Steward tests require Node >=22.13 with node:sqlite")
        self.assertIsNotNone(shutil.which("git"), "Git Steward tests require Git")
        version = node_version(node)
        self.assertIsNotNone(version, "Could not read the Node version")
        self.assertGreaterEqual(
            version, MINIMUM_NODE, f"Git Steward tests require Node >=22.13; found {version}"
        )
        result = subprocess.run(
            [node, "--test", "--test-reporter=tap", *NODE_SUITES],
            cwd=ROOT, text=True, encoding="utf-8", errors="replace",
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout[-30000:])
        self.assertIn("# fail 0", result.stdout)
        self.assertIn("# skipped 0", result.stdout)
        self.assertIn("# cancelled 0", result.stdout)
        self.assertIn("# todo 0", result.stdout)
        tests, passed = tap_count(result.stdout, "tests"), tap_count(result.stdout, "pass")
        self.assertIsNotNone(tests, result.stdout[-30000:])
        self.assertGreater(tests, 0, "The Git Steward suite ran no tests")
        self.assertEqual(passed, tests, result.stdout[-30000:])

    def test_launcher_names_only_suites_that_exist(self):
        for suite in NODE_SUITES:
            with self.subTest(suite=suite):
                self.assertTrue((ROOT / suite).is_file(), suite)

    def test_tap_summary_parser_requires_a_summary_line(self):
        self.assertEqual(tap_count("# tests 3\n# pass 2\n", "tests"), 3)
        self.assertEqual(tap_count("# tests 3\n# pass 2\n", "pass"), 2)
        self.assertIsNone(tap_count("# pass 3\n", "tests"))
        self.assertIsNone(tap_count("ok 1 - # tests 3 inside a name\n", "tests"))


if __name__ == "__main__":
    unittest.main()
