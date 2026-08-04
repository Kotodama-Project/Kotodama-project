from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PublicStatusRoadmapSyncTests(unittest.TestCase):
    def test_public_status_and_roadmap_bind_r107_current_fixed_point(self) -> None:
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        status_flat = " ".join(status.split())
        roadmap_flat = " ".join(roadmap.split())

        self.assertIn("R107 is the current public Company Template layer-order candidate", status_flat)
        self.assertIn("de163c060006d50545229fd8ef092f97c583074d", status_flat)
        self.assertIn("a9679c8f2ff04146b8ddaf1803ee094b56b5d4bc", status_flat)
        self.assertIn("R107 aligned the Company Template ideal order", status_flat)
        self.assertIn("R105 added the direct Installation Lifecycle link", status_flat)
        self.assertNotIn(
            "R105 added the direct Installation Lifecycle link in the Template Catalog Runtime profiles row and is the current public",
            status_flat,
        )
        self.assertIn("R105 remains historical", status_flat)
        self.assertIn("NO_GO_UNPUBLISHED", status_flat)

        self.assertIn("R108 is the latest STATUS/ROADMAP provenance synchronization", roadmap_flat)
        self.assertIn("R107 is the latest public Company Template layer-order revision", roadmap_flat)
        self.assertIn("R107 aligned the Company Template ideal order", roadmap_flat)
        self.assertIn("de163c060006d50545229fd8ef092f97c583074d", roadmap_flat)
        self.assertIn("a9679c8f2ff04146b8ddaf1803ee094b56b5d4bc", roadmap_flat)
        self.assertIn("read-only/candidate-only", roadmap_flat)
        self.assertIn("NO_GO_UNPUBLISHED", roadmap_flat)
        self.assertNotIn("R104 is the latest STATUS/ROADMAP provenance synchronization", roadmap_flat)

    def test_public_status_and_roadmap_preserve_r104_r103_history(self) -> None:
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        status_flat = " ".join(status.split())
        roadmap_flat = " ".join(roadmap.split())

        self.assertIn("R104 synchronized STATUS/ROADMAP provenance to R103", status_flat)
        self.assertIn("R103 remains the historical README/documentation layer-map candidate", status_flat)
        self.assertIn("92a67b1bd0b450b549590d915b24dd983bb3eb7a", status_flat)
        self.assertIn("a8437da05a2688e64129458eb604a6f604deb59c", status_flat)
        self.assertIn("R103 added the README ideal/current layer map", status_flat)
        self.assertIn("NO_GO_UNPUBLISHED", status_flat)
        self.assertIn("real Voice rotation remains unproven", status_flat)

        self.assertIn("R108 is the latest STATUS/ROADMAP provenance synchronization", roadmap_flat)
        self.assertIn("R107 is the latest public Company Template layer-order revision", roadmap_flat)
        self.assertIn("R103 remains the historical README/documentation revision", roadmap_flat)
        self.assertIn("R103 added the README ideal/current layer map", roadmap_flat)
        self.assertIn("92a67b1bd0b450b549590d915b24dd983bb3eb7a", roadmap_flat)
        self.assertIn("a8437da05a2688e64129458eb604a6f604deb59c", roadmap_flat)
        self.assertIn("read-only/candidate-only", roadmap_flat)
        self.assertIn("NO_GO_UNPUBLISHED", roadmap_flat)
        self.assertNotIn("R101 is the current public Template/Company/Blocks/Records/MOCs/starter", status_flat)
        self.assertNotIn("R104 is the latest STATUS/ROADMAP provenance synchronization", roadmap_flat)

    def test_public_status_and_roadmap_name_r91_documentation_surface(self) -> None:
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        status_flat = " ".join(status.split())
        roadmap_flat = " ".join(roadmap.split())

        self.assertIn(
            "R107 is the current public Company Template layer-order candidate",
            status_flat,
        )
        self.assertIn("R92 synchronizes the public STATUS/ROADMAP provenance", status_flat)
        self.assertIn("b071ce9b2fd4167c8ac199bcd1983b64224fba43", status_flat)
        self.assertIn("c6c7bafebd9cca6bdc37365af560b2f11f9fc7e8", status_flat)
        self.assertIn("R91 added Compose candidate runbook POSIX parity", status_flat)
        self.assertIn("R90 added Public Preview Self-check POSIX parity", status_flat)
        self.assertIn("R89 added Validation Guide core POSIX parity", status_flat)
        self.assertIn("R88 added guided onboarding POSIX parity", status_flat)
        self.assertIn("R87 added Template Guide and Catalog POSIX parity", status_flat)
        self.assertIn("R86 synchronized STATUS and ROADMAP provenance", status_flat)
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
        self.assertIn(
            "R76 clarified the ideal/current MOC boundary",
            status_flat,
        )
        self.assertIn(
            "public starter ships exactly three navigation-only MOCs",
            status_flat,
        )
        self.assertIn(
            "R78 clarified the ideal six-phase installation lifecycle",
            status_flat,
        )
        self.assertIn(
            "R80 clarified the ideal Company Template -> Blocks -> Governed Records -> MOCs",
            status_flat,
        )
        self.assertIn(
            "current local/synthetic, read-only/candidate-only starter path",
            status_flat,
        )
        self.assertIn(
            "R82 clarified the ideal six-phase installation lifecycle",
            status_flat,
        )
        self.assertIn(
            "R83 aligned the Validation Guide ideal/current boundary",
            status_flat,
        )
        self.assertIn(
            "R84 added README PowerShell/POSIX command parity",
            status_flat,
        )
        self.assertIn(
            "R85 added onboarding PowerShell/POSIX command parity",
            status_flat,
        )
        self.assertIn("Installation Lifecycle remains profile guidance only", status_flat)
        self.assertIn(
            "target-bound runtime receipt",
            status_flat,
        )
        self.assertIn("real Voice rotation remains unproven", status_flat)
        self.assertIn("Review Request, Review Response, and Decision Handoff", status_flat)
        self.assertIn("Public Beta access", status_flat)
        self.assertIn("Not open", status_flat)
        self.assertIn("Final Human GO", status_flat)
        self.assertIn("Not completed", status_flat)

        self.assertIn("R108 is the latest STATUS/ROADMAP provenance synchronization", roadmap_flat)
        self.assertIn("R107 is the latest public Company Template layer-order revision", roadmap_flat)
        self.assertIn("R100 is the latest Public Preview Self-check POSIX parity", roadmap_flat)
        self.assertIn("R89 is the latest Validation Guide core POSIX parity", roadmap_flat)
        self.assertIn("R88 is the latest guided onboarding POSIX parity", roadmap_flat)
        self.assertIn("R87 is the latest Template Guide and Catalog POSIX parity", roadmap_flat)
        self.assertIn("R86 is the latest STATUS/ROADMAP provenance before R92", roadmap_flat)
        self.assertIn("R58 synchronizes this roadmap with the current public", roadmap_flat)
        self.assertIn("R68 is the historical README contract synchronization", roadmap_flat)
        self.assertIn(
            "R74 is the latest documentation synchronization for schema/validator parity",
            roadmap_flat,
        )
        self.assertIn(
            "R76 is the latest Template Guide usability synchronization",
            roadmap_flat,
        )
        self.assertIn(
            "R78 is the latest installation lifecycle usability synchronization",
            roadmap_flat,
        )
        self.assertIn(
            "R80 is the latest starter navigation usability synchronization",
            roadmap_flat,
        )
        self.assertIn(
            "R82 is the latest runbook usability synchronization",
            roadmap_flat,
        )
        self.assertIn(
            "R83 is the latest Validation Guide usability synchronization",
            roadmap_flat,
        )
        self.assertIn(
            "R84 is the latest README command parity synchronization",
            roadmap_flat,
        )
        self.assertIn(
            "R85 is the latest onboarding command parity synchronization",
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
        self.assertIn(
            "[x] Template Guide ideal/future versus shipped MOC distinction",
            roadmap_flat,
        )
        self.assertIn(
            "[x] Installation lifecycle ideal/current and command/path clarity",
            roadmap_flat,
        )
        self.assertIn(
            "[x] Starter ideal/current navigation and Installation Lifecycle profile guidance",
            roadmap_flat,
        )
        self.assertIn("R107 remains the current Company Pack surface label", roadmap_flat)
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
