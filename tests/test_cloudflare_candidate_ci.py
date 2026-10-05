"""Automatic Cloudflare checks own candidate assurance, never provider effects."""
from __future__ import annotations

import copy
import pathlib
import re
import shlex
import unittest

import yaml

from tools.build_release_sbom import python_components


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "cloudflare-candidate-validation.yml"
LOCK = ROOT / "requirements-ci.txt"


def load_workflow(path: pathlib.Path) -> dict:
    # BaseLoader preserves GitHub's `on` key rather than applying YAML 1.1
    # boolean coercion. All policy values below have explicit scalar checks.
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def action_step(steps: list[dict], action: str) -> dict:
    matches = [step for step in steps if step.get("uses", "").startswith(action + "@")]
    if len(matches) != 1:
        raise AssertionError(f"expected one {action} step")
    return matches[0]


class CloudflareCandidateCIContractTests(unittest.TestCase):
    def _assert_workflow(self, workflow: dict) -> None:
        self.assertEqual(set(workflow["on"]), {"pull_request", "push"})
        self.assertEqual(workflow["on"]["push"], {"branches": ["main"]})
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        self.assertEqual(set(workflow["jobs"]), {"validate"})
        job = workflow["jobs"]["validate"]
        self.assertEqual(job["name"], "Trusted Cloudflare candidate validation")
        self.assertEqual(job["runs-on"], "ubuntu-24.04")
        self.assertNotIn("if", job)
        self.assertNotIn("needs", job)
        self.assertNotIn("continue-on-error", job)
        self.assertNotIn("environment", job)
        self.assertEqual(job.get("permissions", workflow["permissions"]), {"contents": "read"})
        steps = job["steps"]
        by_name = {step["name"]: step for step in steps}
        self.assertEqual(len(steps), len(by_name))
        for step in steps:
            self.assertNotIn("if", step)
            self.assertNotIn("continue-on-error", step)
            self.assertNotIn("environment", step)
        for action in ("actions/checkout", "actions/setup-python", "actions/setup-node"):
            step = action_step(steps, action)
            self.assertIsNotNone(re.fullmatch(re.escape(action) + r"@[0-9a-f]{40}", step["uses"]))
        checkout = action_step(steps, "actions/checkout")
        self.assertEqual(checkout["with"]["persist-credentials"], "false")
        python = action_step(steps, "actions/setup-python")
        node = action_step(steps, "actions/setup-node")
        # Exact versions follow their maintained workflow owners, so reviewed
        # bumps do not need an unrelated duplicated literal in this contract.
        repository_steps = load_workflow(ROOT / ".github/workflows/repository-validation.yml")["jobs"]["repository"]["steps"]
        preview_steps = load_workflow(ROOT / ".github/workflows/cloudflare-edge-preview.yml")["jobs"]["upload-preview-version"]["steps"]
        self.assertEqual(python["with"]["python-version"], action_step(repository_steps, "actions/setup-python")["with"]["python-version"])
        self.assertEqual(node["with"]["node-version"], action_step(preview_steps, "actions/setup-node")["with"]["node-version"])
        for step in (python, node):
            self.assertRegex(next(value for name, value in step["with"].items() if name.endswith("-version")), r"^[0-9]+\.[0-9]+\.[0-9]+$")
            self.assertEqual(step["with"]["check-latest"], "false")
        gate = "Run tracked credential gate before dependency installation"
        install = "Install hash-locked validator dependencies"
        expected_commands = {
            gate: "python -S -B tools/check_tracked_secret_hygiene.py",
            install: "python -m pip install --require-hashes -r requirements-ci.txt",
            "Run focused candidate tests": "python -m unittest tests.test_cloudflare_candidate_ci tests.test_cloudflare_edge_candidate tests.test_cloudflare_os_candidate tests.test_cloudflare_os_local_runtime_evaluation tests.test_cloudflare_os_security_overlay tests.test_verify_wrangler_artifact -v",
            "Run Worker and local Gateway review contracts": "node --test tests/node/test_cloudflare_voice_review.mjs tests/node/test_local_review_gateway.mjs tests/node/test_information_access.mjs",
        }
        for name, expected in expected_commands.items():
            self.assertEqual(shlex.split(by_name[name]["run"]), shlex.split(expected))
        self.assertLess(steps.index(by_name[gate]), steps.index(by_name[install]))
        validators = by_name["Run fail-closed candidate validators"]
        self.assertEqual(validators["shell"], "bash")
        self.assertEqual(validators["run"].splitlines(), [
            "set -euo pipefail",
            "python tools/validate_cloudflare_edge_candidate.py --root .",
            "python tools/validate_cloudflare_os_candidate.py",
            "python tools/validate_cloudflare_os_local_runtime_evaluation.py --json",
            "python tools/validate_cloudflare_os_security_candidate.py",
        ])
        side_effects = by_name["Refuse validator side effects"]
        self.assertEqual(side_effects["shell"], "bash")
        self.assertEqual(side_effects["run"].splitlines(), [
            "set -euo pipefail", 'test -z "$(git status --porcelain)"',
        ])
        self.assertEqual(
            {step["name"] for step in steps if "run" in step},
            {*expected_commands, "Run fail-closed candidate validators", "Refuse validator side effects"},
        )
        self.assertLess(steps.index(validators), steps.index(side_effects))
        # Inspect actual YAML values. Comments cannot create a job permission,
        # protected environment, credential reference or executable command.
        def scalars(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    self.assertNotEqual(key, "environment")
                    yield key
                    yield from scalars(child)
            elif isinstance(value, list):
                for child in value:
                    yield from scalars(child)
            else:
                yield value
        rendered = "\n".join(str(value) for value in scalars(workflow))
        for forbidden in ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "secrets.",
                          "versions upload", "deploy", "npx wrangler", "npm exec wrangler",
                          "codex/cloudflare-os-foundation", "pull_request_target"):
            self.assertNotIn(forbidden, rendered)

    def test_ci_is_read_only_secret_free_hash_locked_and_candidate_focused(self) -> None:
        workflow = load_workflow(WORKFLOW)
        self._assert_workflow(workflow)
        components = python_components(LOCK.read_text(encoding="utf-8"))
        self.assertTrue(components)
        self.assertEqual(len(components), len({component["name"] for component in components}))
        self.assertIn("jsonschema", {component["name"] for component in components})
        lock = LOCK.read_text(encoding="utf-8")
        for requirement in (ROOT / "requirements-test.txt").read_text(encoding="utf-8").splitlines():
            requirement = requirement.split("#", 1)[0].strip()
            if requirement and not requirement.startswith("-r "):
                name, _separator, version = requirement.partition("==")
                self.assertIn(name.lower() + "==" + version,
                              [line.split()[0] for line in lock.splitlines()
                               if line and not line.startswith(("#", " ", "\t"))])
        # Every entry, including platform branches, must carry valid SHA-256
        # hashes. The owner parser rejects unhashed and weak-digest entries.
        for component in components:
            self.assertTrue(component["hashes"])
            self.assertTrue(all(digest["alg"] == "SHA-256" and re.fullmatch(r"[0-9a-f]{64}", digest["content"])
                                for digest in component["hashes"]))
        # These controls formerly passed when required strings only appeared in
        # comments or another job; the real scheduled step must now match.
        for mutation in ("comment", "different-job", "conditional", "unhashed-install", "missing-action", "job-write-permission"):
            changed = copy.deepcopy(workflow)
            job = changed["jobs"]["validate"]
            focused = next(step for step in job["steps"] if step["name"] == "Run focused candidate tests")
            if mutation == "comment":
                focused["run"] = "# " + focused["run"] + "\npython -c 'pass'"
            elif mutation == "different-job":
                job["steps"].remove(focused)
                changed["jobs"]["decoy"] = {"steps": [focused]}
            elif mutation == "conditional":
                focused["if"] = "${{ false }}"
            elif mutation == "unhashed-install":
                next(step for step in job["steps"] if step["name"] == "Install hash-locked validator dependencies")["run"] = "python -m pip install -r requirements-ci.txt"
            elif mutation == "missing-action":
                job["steps"].remove(action_step(job["steps"], "actions/setup-node"))
            else:
                job["permissions"] = {"contents": "write"}
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                self._assert_workflow(changed)


if __name__ == "__main__":
    unittest.main()
