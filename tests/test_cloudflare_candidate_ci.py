from __future__ import annotations

import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "cloudflare-candidate-validation.yml"
LOCK = ROOT / "requirements-ci.txt"


class CloudflareCandidateCIContractTests(unittest.TestCase):
    def test_ci_is_read_only_secret_free_hash_locked_and_candidate_focused(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        lock = LOCK.read_text(encoding="utf-8")

        self.assertIn("pull_request:", workflow)
        self.assertIn("push:", workflow)
        self.assertIn("codex/cloudflare-os-foundation", workflow)
        self.assertNotIn("pull_request_target", workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn("ubuntu-24.04", workflow)
        self.assertIn("actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803", workflow)
        self.assertIn("actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97", workflow)
        self.assertIn('python-version: "3.12.10"', workflow)
        self.assertIn("--require-hashes -r requirements-ci.txt", workflow)
        self.assertIn("tests.test_cloudflare_candidate_ci", workflow)
        self.assertIn("tests.test_cloudflare_edge_candidate", workflow)
        self.assertIn("tests.test_cloudflare_os_candidate", workflow)
        self.assertIn("tests.test_cloudflare_os_local_runtime_evaluation", workflow)
        self.assertIn("validate_cloudflare_edge_candidate.py --root .", workflow)
        self.assertIn("validate_cloudflare_os_candidate.py", workflow)
        self.assertIn("validate_cloudflare_os_local_runtime_evaluation.py --json", workflow)
        self.assertIn("git status --porcelain", workflow)

        forbidden = (
            "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "secrets.",
            "wrangler", "versions upload", "deploy", "environment:",
        )
        self.assertFalse(any(marker in workflow for marker in forbidden))

        requirements = [line for line in lock.splitlines() if line and not line.startswith("#")]
        self.assertEqual(6, len(requirements))
        for line in requirements:
            self.assertRegex(line, r"^[a-z0-9-]+==[^ ]+ --hash=sha256:[0-9a-f]{64}$")
        self.assertEqual(6, len(set(re.findall(r"sha256:([0-9a-f]{64})", lock))))


if __name__ == "__main__":
    unittest.main()
