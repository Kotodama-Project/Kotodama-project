"""Regression checks for the repository pull-request safety checklist."""

from __future__ import annotations

from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class PullRequestTemplateTests(unittest.TestCase):
    def test_pull_request_template_preserves_publication_and_provider_gates(
        self,
    ) -> None:
        template = (
            REPOSITORY_ROOT / ".github" / "pull_request_template.md"
        ).read_text(encoding="utf-8")

        required = {
            "No live credential",
            "fail closed",
            "full commit SHAs",
            "authoritative generator",
            "negative cases",
            "rollback or disablement path",
            "will be read back after mutation",
            "paid capability enablement remains blocked",
        }

        missing = sorted(fragment for fragment in required if fragment not in template)
        self.assertFalse(
            missing, f"pull-request template is missing safety gates: {missing}"
        )

    def test_pull_request_template_does_not_request_secret_evidence(self) -> None:
        template = (
            REPOSITORY_ROOT / ".github" / "pull_request_template.md"
        ).read_text(encoding="utf-8").lower()

        self.assertIn("do not paste secrets", template)
        self.assertNotIn("paste your token", template)
        self.assertNotIn("include the api key", template)
