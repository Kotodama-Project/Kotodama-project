"""Run the offline Node suite from the repository's normal unittest discovery."""
from pathlib import Path
import shutil
import subprocess
import unittest


class LiveWorkspaceRuntimeTests(unittest.TestCase):
    def test_offline_live_workspace_contracts(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for Live workspace regression tests")
        root = Path(__file__).resolve().parents[1]
        suite = root / "runtime" / "live-workspace" / "live-workspace.test.mjs"
        result = subprocess.run(
            [node, "--test", str(suite)], cwd=root, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
