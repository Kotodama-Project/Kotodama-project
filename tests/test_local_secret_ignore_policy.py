"""Regression tests for repository-local secret and deployment-state ignores."""

from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _ignore_lines() -> set[str]:
    return {
        line.strip()
        for line in (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def test_local_secret_files_are_ignored_but_reviewed_examples_remain_trackable() -> None:
    patterns = _ignore_lines()

    required = {
        ".env",
        ".env.*",
        "!.env.example",
        "!.env.*.example",
        ".dev.vars",
        ".dev.vars.*",
        "!.dev.vars.example",
        "!.dev.vars.*.example",
        "*.pem",
        "*.key",
        "*.p12",
        "*.pfx",
        "service-account*.json",
        "credentials.local.json",
        "*.tfstate",
        "*.tfstate.*",
        ".terraform/",
        ".wrangler/",
    }

    assert required <= patterns


def test_ignore_policy_does_not_hide_reviewable_provider_configuration() -> None:
    patterns = _ignore_lines()

    forbidden_broad_ignores = {
        "*.json",
        "*.toml",
        "wrangler.toml",
        "supabase/config.toml",
        ".github/",
        "tests/",
    }

    assert patterns.isdisjoint(forbidden_broad_ignores)
