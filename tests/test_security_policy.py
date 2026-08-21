"""Publication regression checks for the repository security policy."""

from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_security_policy_requires_private_reporting_and_sanitized_evidence() -> None:
    policy = (REPOSITORY_ROOT / "SECURITY.md").read_text(encoding="utf-8")

    required_phrases = {
        "Report a vulnerability",
        "private GitHub Security Advisory",
        "Do not open a public issue",
        "sanitized logs or screenshots",
        "revoke or rotate the secret before history cleanup",
        "A deleted file or rewritten commit does not invalidate a credential",
    }

    missing = sorted(phrase for phrase in required_phrases if phrase not in policy)
    assert not missing, f"SECURITY.md is missing publication-safety language: {missing}"


def test_security_policy_does_not_publish_placeholder_contact_details() -> None:
    policy = (REPOSITORY_ROOT / "SECURITY.md").read_text(encoding="utf-8").lower()

    forbidden = {
        "security@example.com",
        "todo@example.com",
        "replace-me",
        "your-email",
    }

    assert all(value not in policy for value in forbidden)
