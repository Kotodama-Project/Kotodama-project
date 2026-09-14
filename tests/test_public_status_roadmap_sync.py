"""STATUS.md and ROADMAP.md must describe the current public surface.

The historical R91 to R179 revision narrative lives in docs/HISTORY.md. These
tests keep the two orientation documents current instead of pinning prose:
they check the dated ``Updated:`` line against the last change to STATUS.md,
refuse a historical revision being narrated as current, and keep the public
boundary statements and entry links present.
"""

import re
import subprocess
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "STATUS.md"
ROADMAP = ROOT / "ROADMAP.md"
HISTORY = ROOT / "docs" / "HISTORY.md"
HISTORICAL_AS_CURRENT = re.compile(r"\bR\d{2,3} (?:is|remains) the (?:current|latest)\b")


def last_commit_date(path: Path) -> "date | None":
    try:
        completed = subprocess.run(
            ["git", "log", "-1", "--format=%cs", "--", path.name],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    if completed.returncode != 0 or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


class PublicStatusRoadmapSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.status = STATUS.read_text(encoding="utf-8")
        self.roadmap = ROADMAP.read_text(encoding="utf-8")
        self.history = HISTORY.read_text(encoding="utf-8")

    def test_status_updated_line_is_dated_and_not_stale(self) -> None:
        match = re.search(r"^Updated: (\d{4}-\d{2}-\d{2})$", self.status, re.MULTILINE)
        self.assertIsNotNone(match, "STATUS.md needs a dated 'Updated: YYYY-MM-DD' line")
        updated = date.fromisoformat(match.group(1))
        last_change = last_commit_date(STATUS)
        if last_change is not None:
            self.assertLessEqual(
                (last_change - updated).days,
                30,
                "STATUS.md changed without refreshing its Updated line",
            )

    def test_status_and_roadmap_do_not_narrate_a_historical_revision_as_current(self) -> None:
        for name, text in (("STATUS.md", self.status), ("ROADMAP.md", self.roadmap)):
            with self.subTest(document=name):
                self.assertIsNone(HISTORICAL_AS_CURRENT.search(text))
        self.assertNotIn("## Latest public template result", self.status)
        self.assertNotIn("## Current public documentation revision", self.roadmap)

    def test_history_document_is_marked_historical_and_linked(self) -> None:
        head = "\n".join(self.history.splitlines()[:12])
        self.assertIn("historical", head)
        self.assertIn("## Moved from STATUS.md", self.history)
        self.assertIn("## Moved from ROADMAP.md", self.history)
        self.assertIn("docs/HISTORY.md", self.status)
        self.assertIn("docs/HISTORY.md", self.roadmap)

    def test_status_surface_table_covers_main_components(self) -> None:
        table = self.status.split("## Latest Cloudflare candidate result", 1)[0]
        for marker in (
            "runtime/discord-template",
            "docs/DISCORD-RUNTIME.md",
            "docs/COMPANY-PACK-TASK-EXECUTION.md",
            "runtime/local-review-gateway/README.md",
            "docs/SESSION-CONVERSATION-LEDGER.md",
            "docs/CLOUDFLARE-OS-ADOPTION.md",
            "docs/OWNER-INTENT-COMPANY-AGI.md",
            "| Public Beta access | Not open |",
            "| Public Voice Bot | Inactive |",
            "| Final Human GO | Not completed |",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, table)

    def test_public_status_surface_exposes_pack_entry_links(self) -> None:
        status_table = self.status.split("## Latest runtime result", 1)[0]
        roadmap_published = self.roadmap.split("## Documentation revision history", 1)[0]

        for marker in (
            "[Company Pack Catalog](docs/COMPANY-PACK-CATALOG.md)",
            "[Company Pack Guided Next Steps](docs/COMPANY-PACK-NEXT-STEPS.md)",
            "[Schema / Validator / Test Matrix](docs/SCHEMA-VALIDATOR-MATRIX.md)",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(surface="status", marker=marker):
                self.assertIn(marker, status_table)

        self.assertIn(
            "[x] Company Pack Catalog, Guided Next Steps, and Schema / Validator / Test Matrix entry navigation",
            roadmap_published,
        )

    def test_roadmap_keeps_gates_and_boundary_statements(self) -> None:
        self.assertIn("## Required before opening access", self.roadmap)
        self.assertIn("- [ ] Candidate-bound Final Human GO", self.roadmap)
        self.assertIn("docs/PRODUCT-DIRECTION.md", self.roadmap)
        for name, text in (("STATUS.md", self.status), ("ROADMAP.md", self.roadmap)):
            with self.subTest(document=name):
                self.assertIn("NO_GO_UNPUBLISHED", text)


if __name__ == "__main__":
    unittest.main()
