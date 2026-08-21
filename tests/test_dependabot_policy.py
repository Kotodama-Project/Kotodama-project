"""Regression checks for publication-safe dependency maintenance."""

from __future__ import annotations

from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_dependabot_maintains_github_actions_without_private_registry_configuration() -> None:
    config = yaml.safe_load(
        (REPOSITORY_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    )

    assert config["version"] == 2
    assert "registries" not in config

    updates = config["updates"]
    action_updates = [
        update for update in updates if update.get("package-ecosystem") == "github-actions"
    ]

    assert len(action_updates) == 1
    policy = action_updates[0]
    assert policy["directory"] == "/"
    assert policy["schedule"]["interval"] == "weekly"
    assert policy["schedule"]["timezone"] == "Asia/Tokyo"
    assert 1 <= policy["open-pull-requests-limit"] <= 10
    assert policy["rebase-strategy"] == "auto"


def test_action_update_group_does_not_auto_group_major_versions() -> None:
    config = yaml.safe_load(
        (REPOSITORY_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    )
    policy = next(
        update
        for update in config["updates"]
        if update.get("package-ecosystem") == "github-actions"
    )

    group = policy["groups"]["actions-minor-and-patch"]
    assert set(group["update-types"]) == {"minor", "patch"}
