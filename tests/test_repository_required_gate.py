"""Parallel repository checks must remain part of the required, fail-closed gate."""
from itertools import product
import os
from pathlib import Path
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


def workflow_jobs():
    path = ROOT / ".github/workflows/repository-validation.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"]


class RepositoryRequiredGateTests(unittest.TestCase):
    def test_complete_repository_checks_start_without_waiting_for_the_matrices(self):
        repository = workflow_jobs()["repository"]
        self.assertNotIn("needs", repository)
        self.assertNotIn("if", repository)
        self.assertFalse(repository.get("continue-on-error", False))
        self.assertEqual(repository["runs-on"], "ubuntu-24.04")
        self.assertEqual(repository["timeout-minutes"], 25)
        steps = repository["steps"]
        for step in steps:
            with self.subTest(step=step["name"]):
                self.assertNotIn("if", step)
                self.assertFalse(step.get("continue-on-error", False))
        commands = [step.get("run", "") for step in steps]
        for command in (
            "python -S -B tools/check_tracked_secret_hygiene.py",
            "python -S -B tools/smoke_company_pack_review_chain.py",
            "python -m pip install --require-hashes -r requirements-ci.txt",
            "python -B tools/check_workflow_references.py",
            "python -m unittest discover -s tests -v",
        ):
            with self.subTest(command=command):
                self.assertEqual(commands.count(command), 1)
        self.assertLess(commands.index("python -S -B tools/check_tracked_secret_hygiene.py"),
                        commands.index("python -m pip install --require-hashes -r requirements-ci.txt"))
        candidates = next(step for step in steps if step["name"] == "Run the README runtime candidate checks")
        self.assertIn("validate_installation_lifecycle.py", candidates["run"])
        self.assertIn("validate_compose_minimum_skeleton.py", candidates["run"])
        self.assertTrue(any("actionlint" in command for command in commands))
        clean_tree = next(step for step in steps if step["name"] == "Refuse whitespace errors and generated changes")
        self.assertIn("git diff --check", clean_tree["run"])
        self.assertIn('test -z "$(git status --porcelain)"', clean_tree["run"])

    def test_trusted_context_requires_all_three_unconditional_success_checks(self):
        jobs = workflow_jobs()
        gate = jobs["validate"]
        self.assertEqual(gate["name"], "Trusted repository validation")
        self.assertEqual(set(gate["needs"]), {"repository", "discord", "swarm"})
        self.assertEqual(gate["if"], "${{ always() }}")
        self.assertFalse(gate.get("continue-on-error", False))
        self.assertEqual(gate["runs-on"], "ubuntu-24.04")
        self.assertEqual(gate["timeout-minutes"], 15)
        self.assertEqual(len(gate["steps"]), 3)
        for job_id in ("repository", "discord", "swarm"):
            variable = f"{job_id.upper()}_RESULT"
            step = next(step for step in gate["steps"] if variable in step.get("env", {}))
            with self.subTest(job=job_id):
                self.assertEqual(step["env"], {variable: "${{ needs." + job_id + ".result }}"})
                self.assertEqual(step["run"], f'test "${variable}" = success')
                self.assertNotIn("if", step)
                self.assertFalse(step.get("continue-on-error", False))
                self.assertNotIn("needs", jobs[job_id])
                self.assertFalse(jobs[job_id].get("continue-on-error", False))

    # Trusted runs on Linux. Windows bash may be WSL and drop process env vars.
    @unittest.skipUnless(os.name == "posix", "the gate uses bash on Linux")
    def test_any_failed_skipped_cancelled_missing_or_unknown_dependency_refuses(self):
        gate = workflow_jobs()["validate"]
        script = "\n".join(step["run"] for step in gate["steps"])
        variables = ("REPOSITORY_RESULT", "DISCORD_RESULT", "SWARM_RESULT")
        results = ("success", "failure", "skipped", "cancelled", "", "unknown")
        # bash -e matches the Actions Linux shell: failure in an earlier gate
        # cannot be hidden by a successful later matrix check.
        for combination in product(results, repeat=len(variables)):
            with self.subTest(results=combination):
                status = subprocess.run(
                    ["bash", "-e", "-c", script],
                    env={**os.environ, **dict(zip(variables, combination))},
                    check=False,
                )
                self.assertEqual(status.returncode == 0,
                                 all(result == "success" for result in combination))


if __name__ == "__main__":
    unittest.main()
