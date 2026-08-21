from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CURRENT_DATE = "2026-08-21"
PUBLISHED_MAIN = "be71f424689648b3ab1b1db15adbaddea374586b"
ACTIVE_CANDIDATES = {
    "PR #18": "ec76f48d2623476e6433ec8673d2586ee51f9aa1",
    "PR #17": "704ced6a4b8be6465849646c7d2c1ba95f4fd7af",
    "PR #1": "4963801bd17deee30623171199a54c6c8ee9e5c3",
}


class PublicStatusRoadmapSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        self.roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")

    def test_current_documents_bind_the_same_fixed_points(self) -> None:
        for surface, text in (("status", self.status), ("roadmap", self.roadmap)):
            with self.subTest(surface=surface, marker=CURRENT_DATE):
                self.assertIn(CURRENT_DATE, text)
            with self.subTest(surface=surface, marker=PUBLISHED_MAIN):
                self.assertIn(PUBLISHED_MAIN, text)
            for candidate, sha in ACTIVE_CANDIDATES.items():
                with self.subTest(surface=surface, candidate=candidate):
                    self.assertIn(candidate, text)
                    self.assertIn(sha, text)

    def test_current_documents_require_refresh_after_fixed_point_drift(self) -> None:
        for surface, text in (("status", self.status), ("roadmap", self.roadmap)):
            with self.subTest(surface=surface):
                self.assertIn("## Current public state", text)
                self.assertIn("must be refreshed", text)

    def test_current_documents_separate_evidence_lanes(self) -> None:
        for surface, text in (("status", self.status), ("roadmap", self.roadmap)):
            for marker in (
                "Code evidence",
                "Local evidence",
                "Hosted evidence",
                "Admin evidence",
                "Human evidence",
                "independent",
                "Final Human GO",
            ):
                with self.subTest(surface=surface, marker=marker):
                    self.assertIn(marker, text)

    def test_current_documents_preserve_the_public_boundary(self) -> None:
        for surface, text in (("status", self.status), ("roadmap", self.roadmap)):
            for marker in (
                "read-only/candidate-only",
                "NO_GO_UNPUBLISHED",
                "Public Beta",
                "private Voice runtime cutover attempt",
            ):
                with self.subTest(surface=surface, marker=marker):
                    self.assertIn(marker, text)
            self.assertNotIn("CT200", text)

    def test_roadmap_has_the_required_safe_integration_order(self) -> None:
        ordered = self.roadmap.split("## Safe integration order", 1)[1].split(
            "## Evidence required at every stage", 1
        )[0]
        positions = [
            ordered.index("PR #18"),
            ordered.index("issue #19"),
            ordered.index("PR #17"),
            ordered.index("PR #1"),
            ordered.index("runtime lifecycle"),
            ordered.index("Voice and privacy"),
            ordered.index("Final Human GO"),
            ordered.index("Limited Public Beta"),
        ]
        self.assertEqual(sorted(positions), positions)

    def test_historical_revision_detail_is_preserved_outside_the_ssot(self) -> None:
        status_history = ROOT / "docs/history/STATUS-R179-AND-EARLIER.md"
        roadmap_history = ROOT / "docs/history/ROADMAP-R179-AND-EARLIER.md"
        history_index = ROOT / "docs/history/README.md"

        for path in (status_history, roadmap_history, history_index):
            with self.subTest(path=path):
                self.assertTrue(path.is_file())

        self.assertGreater(len(status_history.read_text(encoding="utf-8")), 10_000)
        self.assertGreater(len(roadmap_history.read_text(encoding="utf-8")), 10_000)
        self.assertIn(
            "R179 is the current public documentation revision",
            status_history.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "R179 is the latest public documentation revision",
            roadmap_history.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "docs/history/STATUS-R179-AND-EARLIER.md",
            self.status,
        )
        self.assertIn(
            "docs/history/ROADMAP-R179-AND-EARLIER.md",
            self.roadmap,
        )

    def test_top_level_documents_are_operationally_compact(self) -> None:
        self.assertLess(len(self.status.splitlines()), 180)
        self.assertLess(len(self.roadmap.splitlines()), 220)


if __name__ == "__main__":
    unittest.main()
