from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PublicStatusRoadmapSyncTests(unittest.TestCase):
    def test_public_status_and_roadmap_name_r56_documentation_surface(self) -> None:
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        status_flat = " ".join(status.split())
        roadmap_flat = " ".join(roadmap.split())

        self.assertIn(
            "R56 is the current public Template/Company/Blocks/Records/MOCs/starter",
            status_flat,
        )
        self.assertNotIn("R52 is the current public Template/Company/Blocks/Records/MOCs/starter", status_flat)
        self.assertNotIn("R48 is the current public template/documentation surface", status_flat)
        self.assertIn("R50 added the eight-entry-point navigation synchronization", status_flat)
        self.assertIn("R52 added the explicit ideal/current Company Template usage", status_flat)
        self.assertIn("R54 added the practical ideal/current Template Catalog usage", status_flat)
        self.assertIn("R55 hardened standard unittest discovery", status_flat)
        self.assertIn("R56 added the first-read order and bounded runtime profile selection", status_flat)
        self.assertIn("Review Request, Review Response, and Decision Handoff", status_flat)
        self.assertIn("Public Beta access", status_flat)
        self.assertIn("Not open", status_flat)
        self.assertIn("Final Human GO", status_flat)
        self.assertIn("Not completed", status_flat)

        self.assertIn("R56 synchronizes this roadmap with the current public", roadmap_flat)
        self.assertNotIn("R52 synchronizes this roadmap with the current public Company Pack surface", roadmap_flat)
        self.assertNotIn("R49 synchronizes this roadmap with the R48 public Company Pack surface", roadmap_flat)
        self.assertIn("[x] Template/Company/Blocks/Records/MOCs/starter navigation synchronization", roadmap_flat)
        self.assertIn("[x] Company Template ideal/current usage documentation synchronization", roadmap_flat)
        self.assertIn("[x] Installation lifecycle first-read and profile-selection guidance", roadmap_flat)
        self.assertIn("read-only/candidate-only", roadmap_flat)
        self.assertIn("Public Beta GO", roadmap_flat)
        self.assertIn("[ ] Candidate-bound Final Human GO", roadmap_flat)


if __name__ == "__main__":
    unittest.main()
