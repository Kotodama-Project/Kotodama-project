from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
CURRENT_DATE = "2026-08-21"
PUBLISHED_MAIN = "be71f424689648b3ab1b1db15adbaddea374586b"
ACTIVE_CANDIDATES = {
    "PR #18": "fbb6da377edd2b726a854912eb17c964a1ec01e9",
    "PR #17": "704ced6a4b8be6465849646c7d2c1ba95f4fd7af",
    "PR #1": "83e7b9e0789f941f993fd2c43a938dd872b12581",
}
GOVERNANCE_EVIDENCE = {
    "repository validation run": "32488194816",
    "dependency review run": "32488194768",
    "public test count": "529 tests",
}
HISTORICAL_GIT_BLOBS = {
    "README.md": "9a591992b1d74681fe8b011222625c6a0525c0c8",
    "STATUS-R179-AND-EARLIER.md": "71877969c3eae7f32d928884a9e7766a6945a0ea",
    "ROADMAP-R179-AND-EARLIER.md": "96bb07e5dff7612368b03943c6c0c6c5faaa51d9",
}


def git_blob_sha(path: Path) -> str:
    result = subprocess.run(
        ["git", "hash-object", str(path)],
        cwd=ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout.strip()


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
            for evidence, marker in GOVERNANCE_EVIDENCE.items():
                with self.subTest(surface=surface, evidence=evidence):
                    self.assertIn(marker, text)

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

    def test_current_documents_bound_credential_evidence(self) -> None:
        for surface, text in (("status", self.status), ("roadmap", self.roadmap)):
            for marker in (
                "current-tree",
                "Git history",
                "provider",
                "credential",
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
        exact_steps = (
            "1. **Validate PR #18 exactly.**",
            "2. **Complete issue #19.**",
            "4. **Publish the operational status safely.**",
            "5. **Rebase and validate PR #17.**",
            "6. **Reconcile and validate PR #1.**",
            "7. **Prove runtime lifecycle.**",
            "8. **Prove Voice and privacy boundaries.**",
            "10. **Final Human GO.**",
            "11. **Limited Public Beta.**",
        )
        positions = [ordered.index(step) for step in exact_steps]
        self.assertEqual(sorted(positions), positions)

    def test_historical_revision_detail_is_preserved_outside_the_ssot(self) -> None:
        history_dir = ROOT / "docs/history"
        status_history = history_dir / "STATUS-R179-AND-EARLIER.md"
        roadmap_history = history_dir / "ROADMAP-R179-AND-EARLIER.md"
        history_index = history_dir / "README.md"

        for path in (status_history, roadmap_history, history_index):
            with self.subTest(path=path):
                self.assertTrue(path.is_file())

        for name, expected_blob in HISTORICAL_GIT_BLOBS.items():
            with self.subTest(history_blob=name):
                self.assertEqual(git_blob_sha(history_dir / name), expected_blob)

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
