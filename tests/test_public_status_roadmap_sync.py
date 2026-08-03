from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PublicStatusRoadmapSyncTests(unittest.TestCase):
    def test_public_status_and_roadmap_name_r74_documentation_surface(self) -> None:
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        status_flat = " ".join(status.split())
        roadmap_flat = " ".join(roadmap.split())

        self.assertIn(
            "R58 is the current public Template/Company/Blocks/Records/MOCs/starter",
            status_flat,
        )
        self.assertNotIn(
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
        self.assertIn("R58 added the README first-stop guide", status_flat)
        self.assertIn("R62 added the Company Pack Catalog first-stop sequence", status_flat)
        self.assertIn("R64 added template-pack path canonicalization", status_flat)
        self.assertIn("R65 added installation-lifecycle purpose schema/validator parity", status_flat)
        self.assertIn("R66 added Compose binding integer schema/validator parity", status_flat)
        self.assertIn(
            "R68 added the README Voice rotation ideal/current contract",
            status_flat,
        )
        self.assertIn(
            "R70 aligned the resolved Compose candidate's bytes semantics",
            status_flat,
        )
        self.assertIn(
            "Docker-free synthetic candidate passes both validators",
            status_flat,
        )
        self.assertIn(
            "R72 added installation-lifecycle fixed-boolean schema/validator parity",
            status_flat,
        )
        self.assertIn(
            "R73 added Compose security fixed-boolean schema/validator parity",
            status_flat,
        )
        self.assertIn(
            "R74 added resolved Compose nested boolean schema/validator parity",
            status_flat,
        )
        self.assertIn(
            "numeric 0/1 aliases are rejected by both schema and stdlib validator",
            status_flat,
        )
        self.assertIn("real Voice rotation remains unproven", status_flat)
        self.assertIn("Review Request, Review Response, and Decision Handoff", status_flat)
        self.assertIn("Public Beta access", status_flat)
        self.assertIn("Not open", status_flat)
        self.assertIn("Final Human GO", status_flat)
        self.assertIn("Not completed", status_flat)

        self.assertIn("R58 synchronizes this roadmap with the current public", roadmap_flat)
        self.assertIn("R68 is the latest README contract synchronization", roadmap_flat)
        self.assertIn(
            "R74 is the latest documentation synchronization for schema/validator parity",
            roadmap_flat,
        )
        self.assertIn("R62 remains the latest navigation synchronization", roadmap_flat)
        self.assertIn("R74 is the latest parity synchronization", roadmap_flat)
        self.assertIn("R68 added the README Voice rotation ideal/current contract", roadmap_flat)
        self.assertIn(
            "[x] Resolved Compose binding integer schema/validator parity",
            roadmap_flat,
        )
        self.assertIn(
            "[x] Installation-lifecycle fixed-boolean schema/validator parity",
            roadmap_flat,
        )
        self.assertIn(
            "[x] Compose security fixed-boolean schema/validator parity",
            roadmap_flat,
        )
        self.assertIn(
            "[x] Resolved Compose nested boolean schema/validator parity",
            roadmap_flat,
        )
        self.assertIn("R58 remains the current Company Pack surface label", roadmap_flat)
        self.assertNotIn("R56 synchronizes this roadmap with the current public", roadmap_flat)
        self.assertNotIn("R52 synchronizes this roadmap with the current public Company Pack surface", roadmap_flat)
        self.assertNotIn("R49 synchronizes this roadmap with the R48 public Company Pack surface", roadmap_flat)
        self.assertIn("[x] Template/Company/Blocks/Records/MOCs/starter navigation synchronization", roadmap_flat)
        self.assertIn("[x] Company Template ideal/current usage documentation synchronization", roadmap_flat)
        self.assertIn("[x] Installation lifecycle first-read and profile-selection guidance", roadmap_flat)
        self.assertIn("[x] README first-stop guide and bounded profile-selection navigation", roadmap_flat)
        self.assertIn("[x] Company Pack Catalog first-stop sequence", roadmap_flat)
        self.assertIn("read-only/candidate-only", roadmap_flat)
        self.assertIn("Public Beta GO", roadmap_flat)
        self.assertIn("[ ] Candidate-bound Final Human GO", roadmap_flat)


if __name__ == "__main__":
    unittest.main()
