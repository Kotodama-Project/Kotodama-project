"""Regression tests for repository-local secret and deployment-state ignores."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _ignore_lines() -> set[str]:
    return {
        line.strip()
        for line in (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def _ignored_paths(paths: set[str]) -> set[str]:
    """Exercise this repository's rules without global excludes or a Git index."""
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        subprocess.run(
            ["git", "init", "--quiet", "--template="], cwd=root,
            env=environment, capture_output=True, check=True, timeout=10,
        )
        (root / ".gitignore").write_bytes((REPOSITORY_ROOT / ".gitignore").read_bytes())
        for relative in paths:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch()
        result = subprocess.run(
            ["git", "-c", f"core.excludesFile={os.devnull}", "check-ignore", "--no-index", "--stdin", "-z"],
            cwd=root, env=environment, input="\0".join(sorted(paths)).encode() + b"\0",
            capture_output=True, check=False, timeout=10,
        )
        if result.returncode not in (0, 1):
            raise RuntimeError("Git ignore-policy inspection failed")
        return {value.decode() for value in result.stdout.split(b"\0") if value}


class LocalSecretIgnorePolicyTests(unittest.TestCase):
    def test_local_secret_files_are_ignored_but_reviewed_examples_remain_trackable(
        self,
    ) -> None:
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

        self.assertLessEqual(required, patterns)
        secret_files = {
            ".env", ".env.production", ".dev.vars", ".dev.vars.production",
            "private.pem", "private.key", "private.p12", "private.pfx",
            "credentials.json", "credentials.production.json", "credentials.local.json",
            "service-account-test.json", "service_account_test.json", "id_rsa", "id_ed25519",
            "state.tfstate", "state.tfstate.backup", ".terraform/local-state.json", ".wrangler/local-state.json",
        }
        examples = {
            ".env.example", ".env.sample", ".env.template", ".env.production.example",
            ".dev.vars.example", ".dev.vars.production.example",
        }
        # Root and component directories must obey the same secret/example rule.
        secret_files |= {"component/" + path for path in secret_files}
        examples |= {"component/" + path for path in examples}
        self.assertEqual(secret_files, _ignored_paths(secret_files | examples))

    def test_ignore_policy_does_not_hide_reviewable_provider_configuration(
        self,
    ) -> None:
        patterns = _ignore_lines()

        forbidden_broad_ignores = {
            "*.json",
            "*.toml",
            "wrangler.toml",
            "supabase/config.toml",
            ".github/",
            "tests/",
        }

        self.assertTrue(patterns.isdisjoint(forbidden_broad_ignores))
        reviewable = {
            "wrangler.toml", "supabase/config.toml", "provider-config.json",
            ".github/workflows/check.yml", "tests/test_fixture.py",
            "runtime/component/wrangler.toml", "runtime/component/supabase/config.toml",
            "runtime/component/provider-config.json",
        }
        self.assertEqual(set(), _ignored_paths(reviewable))
