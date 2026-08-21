"""Regression checks for publication-safe dependency maintenance."""

from __future__ import annotations

from pathlib import Path
import unittest

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class DependabotPolicyTests(unittest.TestCase):
    def _load_config(self) -> dict[str, object]:
        return yaml.safe_load(
            (REPOSITORY_ROOT / ".github" / "dependabot.yml").read_text(
                encoding="utf-8"
            )
        )

    def _github_actions_policy(self) -> dict[str, object]:
        config = self._load_config()
        updates = config["updates"]
        self.assertIsInstance(updates, list)
        action_updates = [
            update
            for update in updates
            if update.get("package-ecosystem") == "github-actions"
        ]
        self.assertEqual(len(action_updates), 1)
        return action_updates[0]

    def test_dependabot_maintains_github_actions_without_private_registry_configuration(
        self,
    ) -> None:
        config = self._load_config()

        self.assertEqual(config["version"], 2)
        self.assertNotIn("registries", config)

        policy = self._github_actions_policy()
        self.assertEqual(policy["directory"], "/")
        self.assertEqual(policy["schedule"]["interval"], "weekly")
        self.assertEqual(policy["schedule"]["timezone"], "Asia/Tokyo")
        self.assertLessEqual(1, policy["open-pull-requests-limit"])
        self.assertLessEqual(policy["open-pull-requests-limit"], 10)
        self.assertEqual(policy["rebase-strategy"], "auto")

    def test_action_update_group_does_not_auto_group_major_versions(self) -> None:
        policy = self._github_actions_policy()
        group = policy["groups"]["actions-minor-and-patch"]
        self.assertEqual(set(group["update-types"]), {"minor", "patch"})
