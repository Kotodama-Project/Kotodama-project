"""The required status must include the complete, hash-locked task swarm matrix."""
from pathlib import Path
import ast
import os
import re
import subprocess
import unittest
import yaml

from tools.build_release_sbom import python_components

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements-task-swarm-ci.txt"


class TaskSwarmRequiredGateTests(unittest.TestCase):
    def test_required_context_depends_on_the_swarm_matrix(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/repository-validation.yml").read_text(encoding="utf-8"))
        jobs = workflow["jobs"]
        self.assertEqual(jobs["swarm"]["uses"], "./.github/workflows/task-swarm.yml")
        required = jobs["validate"]
        self.assertEqual(required["name"], "Trusted repository validation")
        self.assertEqual(set(required["needs"]), {"repository", "discord", "swarm"})
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
        self.assertIn("python -m pytest -q -p no:cacheprovider -o 'python_files=test_task_swarm_*.py' tests", commands)
        self.assertTrue(any("tools/task_swarm.py demo" in command for command in commands))
        setup = next(step for step in job["steps"] if str(step.get("uses", "")).startswith("actions/setup-python@"))
        self.assertRegex(setup["with"]["python-version"], r"^3\.12\.[0-9]+$")
        repository = yaml.safe_load((ROOT / ".github/workflows/repository-validation.yml").read_text(encoding="utf-8"))
        repository_setup = next(step for step in repository["jobs"]["repository"]["steps"]
                                if str(step.get("uses", "")).startswith("actions/setup-python@"))
        self.assertEqual(setup["with"]["python-version"], repository_setup["with"]["python-version"])
        self.assertFalse(setup["with"].get("check-latest", False))

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
        # Counted hashes can all belong to one entry while another is unhashed.
        # The existing release parser checks the hash of every requirement.
        components = python_components(lock)
        self.assertEqual(len(components), len(requirements))
        self.assertTrue(all(component["hashes"] for component in components))

        # The shared lock parser verifies every pin/hash and marker grammar.
        # Evaluate the current lock's equality/boolean marker subset for each
        # supported CPython platform without adding a unittest dependency.
        def active_marker(node, environment):
            if isinstance(node, ast.Expression):
                return active_marker(node.body, environment)
            if isinstance(node, ast.BoolOp):
                values = [active_marker(value, environment) for value in node.values]
                if isinstance(node.op, ast.And):
                    return all(values)
                if isinstance(node.op, ast.Or):
                    return any(values)
            if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1:
                self.assertIsInstance(node.left, ast.Name)
                right = ast.literal_eval(node.comparators[0])
                self.assertIsInstance(right, str)
                left = environment[node.left.id]
                if isinstance(node.ops[0], ast.Eq):
                    return left == right
                if isinstance(node.ops[0], ast.NotEq):
                    return left != right
            self.fail("extend platform marker evaluation when the lock adds another operator")

        for platform in ("linux", "win32"):
            environment = {"sys_platform": platform, "implementation_name": "cpython",
                           "platform_python_implementation": "CPython"}
            active = set()
            for line in requirements:
                requirement, _, marker = line.rstrip(" \\ ").partition(";")
                name = requirement.split("==")[0].split("[")[0]
                if not marker or active_marker(ast.parse(marker.strip(), mode="eval"), environment):
                    active.add(name)
            with self.subTest(platform=platform):
                for name in ("pywin32", "colorama"):
                    with self.subTest(dependency=name):
                        self.assertEqual(name in active, platform == "win32")
                self.assertNotIn("httpx2-jsfetch", active)
                self.assertTrue({"mcp", "psutil", "pytest", "jsonschema", "pyyaml"} <= active)

    # The gate step runs on the Linux runner; on Windows `bash` may resolve to
    # WSL, which does not inherit this process's environment.
    @unittest.skipUnless(os.name == "posix", "the gate step runs under bash on Linux")
    def test_failure_skip_cancellation_and_missing_results_do_not_pass(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/repository-validation.yml").read_text(encoding="utf-8"))
        gate = next(step for step in workflow["jobs"]["validate"]["steps"]
                    if step.get("name") == "Require the complete task swarm test matrix")
        for result in ["success", "failure", "skipped", "cancelled", ""]:
            with self.subTest(result=result):
                status = subprocess.run(["bash", "-e", "-c", gate["run"]],
                                        env={**os.environ, "SWARM_RESULT": result}, check=False)
                self.assertEqual(status.returncode == 0, result == "success")


if __name__ == "__main__":
    unittest.main()
