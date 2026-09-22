"""The required status must include the complete, hash-locked task swarm matrix."""
from pathlib import Path
import os
import re
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements-task-swarm-ci.txt"


class TaskSwarmRequiredGateTests(unittest.TestCase):
    def test_required_context_depends_on_the_swarm_matrix(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/repository-validation.yml").read_text(encoding="utf-8"))
        jobs = workflow["jobs"]
        self.assertEqual(jobs["swarm"]["uses"], "./.github/workflows/task-swarm.yml")
        required = jobs["validate"]
        self.assertEqual(required["name"], "Trusted repository validation")
        self.assertEqual(set(required["needs"]), {"discord", "swarm"})
        self.assertEqual(required["if"], "${{ always() }}")
        gate = next(step for step in required["steps"] if step.get("name") == "Require the complete task swarm test matrix")
        self.assertEqual(gate["env"]["SWARM_RESULT"], "${{ needs.swarm.result }}")
        self.assertEqual(gate["run"], 'test "$SWARM_RESULT" = success')

    def test_swarm_workflow_installs_only_the_hash_locked_set_on_both_platforms(self):
        swarm = yaml.safe_load((ROOT / ".github/workflows/task-swarm.yml").read_text(encoding="utf-8"))
        # PyYAML's YAML 1.1 resolver reads the Actions key `on` as True.
        triggers = swarm.get("on", swarm.get(True))
        self.assertIn("workflow_call", triggers)
        self.assertNotIn("pull_request", triggers, "the required gate already calls this workflow")
        job = swarm["jobs"]["validate"]
        self.assertEqual(set(job["strategy"]["matrix"]["os"]), {"ubuntu-latest", "windows-latest"})
        commands = [step.get("run", "") for step in job["steps"]]
        installs = [command for command in commands if "pip install" in command]
        self.assertEqual(installs, ["python -m pip install --require-hashes -r requirements-task-swarm-ci.txt"])
        self.assertIn("python -m pytest -q -p no:cacheprovider tests -k task_swarm", commands)
        self.assertTrue(any("tools/task_swarm.py demo" in command for command in commands))
        setup = next(step for step in job["steps"] if str(step.get("uses", "")).startswith("actions/setup-python@"))
        self.assertEqual(setup["with"]["python-version"], "3.12.10")

    def test_swarm_lock_is_universal_pinned_and_hashed(self):
        lock = LOCK.read_text(encoding="utf-8")
        self.assertIn("uv pip compile --universal --generate-hashes", lock)
        requirements = [line for line in lock.splitlines() if line and not line.startswith(("#", " ", "\t"))]
        pinned = re.compile(r"^[a-z0-9._-]+(\[[a-z0-9,._-]+\])?==[^ ;]+( ; [^\\]+)? \\$")
        for line in requirements:
            self.assertRegex(line, pinned)
        names = {line.split("==")[0].split("[")[0] for line in requirements}
        # Windows-only dependencies stay in the same lock behind markers.
        self.assertIn("pywin32", names)
        self.assertIn("colorama", names)
        for name in ("mcp", "psutil", "pytest", "jsonschema", "pyyaml"):
            self.assertIn(name, names)
        digests = re.findall(r"--hash=sha256:([0-9a-f]{64})", lock)
        self.assertEqual(len(digests), len(set(digests)))
        self.assertGreaterEqual(len(digests), len(requirements))
        self.assertNotIn("--hash=md5:", lock)
        self.assertNotIn("--hash=sha1:", lock)

    def test_failure_skip_cancellation_and_missing_results_do_not_pass(self):
        for result in ["success", "failure", "skipped", "cancelled", ""]:
            with self.subTest(result=result):
                status = subprocess.run(["bash", "-c", 'test "$SWARM_RESULT" = success'],
                                        env={**os.environ, "SWARM_RESULT": result}, check=False)
                self.assertEqual(status.returncode == 0, result == "success")


if __name__ == "__main__":
    unittest.main()
