from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PublicStatusRoadmapSyncTests(unittest.TestCase):
    def test_public_orientation_promotes_r179_and_preserves_r178_to_r172_history(self) -> None:
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        status_flat = " ".join(status.split())
        roadmap_flat = " ".join(roadmap.split())

        for surface, text in (("status", status_flat), ("roadmap", roadmap_flat)):
            current = (
                "R179 is the current public documentation revision"
                if surface == "status"
                else "R179 is the latest public documentation revision"
            )
            for marker in (
                current,
                "23e954d4f5bb0dbf4450d768d6b37c2895c97b0b",
                "25986611496feeebfed1d58ddf4b008d7f965457",
                "R178 remains historical",
                "R177 remains historical",
                "R176 remains historical",
                "R175 remains historical",
                "R174 remains historical",
                "R173 remains historical",
                "R172 remains historical",
                "5-minute tour",
                "Company OS",
                "Vision -> Experience -> Architecture -> Current Reality -> Try it",
                "git clone",
                "Company Pack CLI Reference",
                "fourteen",
                "python -S -B tools/smoke_company_pack_review_chain.py",
                "python3 -S -B tools/smoke_company_pack_review_chain.py",
                "exact thirteen",
                "temporary",
                "persists no intermediate artifacts",
                "read-only/candidate-only",
                "NO_GO_UNPUBLISHED",
            ):
                with self.subTest(surface=surface, marker=marker):
                    self.assertIn(marker, text)

            for stale in (
                "R172",
                "R173",
                "R174",
                "R175",
                "R176",
                "R177",
                "R178",
            ):
                with self.subTest(surface=surface, stale=stale):
                    self.assertNotIn(
                        f"{stale} is the current public documentation revision", text
                    )
                    self.assertNotIn(
                        f"{stale} is the latest public documentation revision", text
                    )

    def test_public_orientation_preserves_r166_r165_r164_r163_history_under_r179(self) -> None:
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        status_flat = " ".join(status.split())
        roadmap_flat = " ".join(roadmap.split())

        for surface, text in (("status", status_flat), ("roadmap", roadmap_flat)):
            for marker in (
                "R179 is the current public documentation revision"
                if surface == "status"
                else "R179 is the latest public documentation revision",
                "030a2e14aa15ca3f201b96105743c48eeeee54cb",
                "08c4f8b9a784b1a30d82bf68b7316b5e3b32e6b9",
                "R166 remains historical",
                "python -m unittest tests.test_public_starter_runbook_smoke -v",
                "python3 -m unittest tests.test_public_starter_runbook_smoke -v",
                "b3db55ca241c18fd795a2c5b341ef3d629dcf477",
                "036e8b1421c88e1e66fa3394c4f35e9d93ecf6b7",
                "R165 remains historical",
                "Validation full-suite cross-shell parity",
                "python3 -m pip install -r requirements-test.txt",
                "python3 -m unittest discover -s tests -v",
                "02cf18e6696e61839ecb866ce8d720b1fba8c582",
                "dff3c0b2e8990daa85650ef591158c94593c6b40",
                "R164 remains historical",
                "b7979b2946a262ef6d024512606ecb80b4ab6845",
                "f316557224384c2d7a7a51ac3b314cff0bc236c2",
                "R163 remains historical",
                "aca4d22772e84cf7da103b97872c94a04c67ac31",
                "008f43ff3f929c990717799fd2bb1b1a52419485",
                "R162 remains historical",
                "MOC smoke command parity",
                "Markdown-to-JSON link-integrity",
                "python -m unittest tests.test_mocs_entry_navigation -v",
                "read-only/candidate-only",
                "NO_GO_UNPUBLISHED",
            ):
                with self.subTest(surface=surface, marker=marker):
                    self.assertIn(marker, text)

            with self.subTest(surface=surface, stale="R155 current/latest"):
                self.assertNotIn(
                    "R155 is the current public documentation revision", text
                )
                self.assertNotIn(
                    "R155 is the latest public documentation revision", text
                )
            with self.subTest(surface=surface, stale="R163 current/latest"):
                self.assertNotIn(
                    "R163 is the current public documentation revision", text
                )
                self.assertNotIn(
                    "R163 is the latest public documentation revision", text
                )
            with self.subTest(surface=surface, stale="R166 current/latest"):
                self.assertNotIn(
                    "R166 is the current public documentation revision", text
                )
                self.assertNotIn(
                    "R166 is the latest public documentation revision", text
                )

    def test_public_status_and_roadmap_bind_r179_current_surface(self) -> None:
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        status_flat = " ".join(status.split())
        roadmap_flat = " ".join(roadmap.split())

        for marker in (
            "R179 is the current public documentation revision",
            "97dca324e28777d4618abf53804f47db995e5abc",
            "9e4ad41d7f79ef6d2d9096ebccaad276ff03615c",
            "Company Pack Catalog",
            "Company Pack Guided Next Steps",
            "Schema / Validator / Test Matrix",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(surface="status", marker=marker):
                self.assertIn(marker, status_flat)

        for marker in (
            "R179 is the latest public documentation revision",
            "97dca324e28777d4618abf53804f47db995e5abc",
            "9e4ad41d7f79ef6d2d9096ebccaad276ff03615c",
            "Company Pack Catalog",
            "Company Pack Guided Next Steps",
            "Schema / Validator / Test Matrix",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(surface="roadmap", marker=marker):
                self.assertIn(marker, roadmap_flat)

        self.assertIn("R154 remains historical", status_flat)
        self.assertIn("R154 remains historical", roadmap_flat)
        self.assertIn("R153 remains historical", status_flat)
        self.assertIn("R153 remains historical", roadmap_flat)
        self.assertNotIn("R154 is the current public documentation revision", status_flat)
        self.assertNotIn("R154 is the latest public documentation revision", roadmap_flat)
        self.assertNotIn("R153 is the current public documentation revision", status_flat)
        self.assertNotIn("R153 is the latest public documentation revision", roadmap_flat)

    def test_public_status_surface_exposes_pack_entry_links(self) -> None:
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        status_table = status.split("## Latest runtime result", 1)[0]
        roadmap_published = roadmap.split("## Current public documentation revision", 1)[0]

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
        self.assertIn("NO_GO_UNPUBLISHED", roadmap)

    def test_public_status_and_roadmap_preserve_r153_readme_artifact_map_history(self) -> None:
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        status_flat = " ".join(status.split())
        roadmap_flat = " ".join(roadmap.split())

        for marker in (
            "R179 is the current public documentation revision",
            "92b574129ada8d9af2fc2a95e29cdd92590a5dd8",
            "b8d981464e18c31e448b3b57d3bb758ad6f67ae2",
            "README Document Map",
            "Review-chain artifact map",
            "Company Pack Guided Next Steps",
            "Installation Lifecycle",
            "STARTER-WALKTHROUGH.md#review-chain-artifact-map",
            "artifact states and next handoffs",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(surface="status", marker=marker):
                self.assertIn(marker, status_flat)

        for marker in (
            "R179 is the latest public documentation revision",
            "92b574129ada8d9af2fc2a95e29cdd92590a5dd8",
            "b8d981464e18c31e448b3b57d3bb758ad6f67ae2",
            "README Document Map",
            "review-chain artifact map",
            "Company Pack Guided Next Steps",
            "Installation Lifecycle",
            "STARTER-WALKTHROUGH.md#review-chain-artifact-map",
            "artifact states and next handoffs",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(surface="roadmap", marker=marker):
                self.assertIn(marker, roadmap_flat)

        self.assertIn("R152 remains historical", status_flat)
        self.assertIn("R152 remains historical", roadmap_flat)
        self.assertNotIn("R152 is the current public documentation revision", status_flat)
        self.assertNotIn("R152 is the latest public documentation revision", roadmap_flat)

    def test_public_status_and_roadmap_preserve_r151_entry_surfaces_history(self) -> None:
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        status_flat = " ".join(status.split())
        roadmap_flat = " ".join(roadmap.split())

        for marker in (
            "R179 is the current public documentation revision",
            "7633f0d4996c1bd210fb68b65fb12ff81c7fe4b7",
            "5bcb3b231e1377b3505e51385b57feb04f607361",
            "Company Pack Guided Next Steps",
            "Schema / Validator / Test Matrix",
            "Review-chain artifact map",
            "STARTER-WALKTHROUGH.md#review-chain-artifact-map",
            "before or after the external-free smoke",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(surface="status", marker=marker):
                self.assertIn(marker, status_flat)

        for marker in (
            "R179 is the latest public documentation revision",
            "7633f0d4996c1bd210fb68b65fb12ff81c7fe4b7",
            "5bcb3b231e1377b3505e51385b57feb04f607361",
            "Company Pack Guided Next Steps",
            "Schema / Validator / Test Matrix",
            "review-chain artifact map",
            "STARTER-WALKTHROUGH.md#review-chain-artifact-map",
            "before or after the external-free smoke",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(surface="roadmap", marker=marker):
                self.assertIn(marker, roadmap_flat)

        self.assertNotIn("R150 is the current public documentation revision", status_flat)
        self.assertNotIn("R150 is the latest public documentation revision", roadmap_flat)
        self.assertNotIn("R149 is the current public documentation revision", status_flat)
        self.assertNotIn("R149 is the latest public documentation revision", roadmap_flat)
        self.assertIn("R151 remains historical", status_flat)
        self.assertIn("R151 remains historical", roadmap_flat)

    def test_public_status_and_roadmap_preserve_r149_artifact_map_history(self) -> None:
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        status_flat = " ".join(status.split())
        roadmap_flat = " ".join(roadmap.split())

        for marker in (
            "R179 is the current public documentation revision",
            "ea23f3a31ae68025bf23889beea878d3062adefa",
            "0fa942044a2140b243b4a03c831c511b9938332b",
            "Review-chain artifact map",
            "Review Bundle, Review Request, Review Response, and Review Decision Handoff",
            "COMPANY-PACK-CATALOG.md",
            "before or after the external-free smoke",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(surface="status", marker=marker):
                self.assertIn(marker, status_flat)

        for marker in (
            "R179 is the latest public documentation revision",
            "ea23f3a31ae68025bf23889beea878d3062adefa",
            "0fa942044a2140b243b4a03c831c511b9938332b",
            "review-chain artifact map",
            "Review Bundle, Review Request, Review Response, and Decision Handoff",
            "COMPANY-PACK-CATALOG.md",
            "before or after the external-free smoke",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(surface="roadmap", marker=marker):
                self.assertIn(marker, roadmap_flat)

        self.assertNotIn(
            "R147 is the current public documentation revision",
            status_flat,
        )
        self.assertNotIn(
            "R147 is the latest public documentation revision",
            roadmap_flat,
        )
        self.assertIn("R149 remains historical", status_flat)
        self.assertIn("R149 remains historical", roadmap_flat)

    def test_roadmap_labels_r107_as_historical_not_current(self) -> None:
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        roadmap_flat = " ".join(roadmap.split())

        self.assertIn(
            "R107 is historical provenance for the Company Pack surface label",
            roadmap_flat,
        )
        self.assertNotIn(
            "R107 remains the current Company Pack surface label",
            roadmap_flat,
        )

    def test_public_status_and_roadmap_preserve_r146_review_chain_history(self) -> None:
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        status_flat = " ".join(status.split())
        roadmap_flat = " ".join(roadmap.split())

        for marker in (
            "R179 is the current public documentation revision",
            "1abcfd8f835f7d52627c194aacd8a62efb87875b",
            "2c8579fa242357dcc28a6d73c95011e1446b6846",
            "test_public_starter_runbook_smoke.py",
            "full review-chain smoke",
            "Review Request",
            "Review Response",
            "Review Decision Handoff",
            "R146 remains historical",
            "R145 remains historical",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(surface="status", marker=marker):
                self.assertIn(marker, status_flat)

        for marker in (
            "R179 is the latest public documentation revision",
            "Review Request, Review Response, and Decision Handoff",
            "1abcfd8f835f7d52627c194aacd8a62efb87875b",
            "2c8579fa242357dcc28a6d73c95011e1446b6846",
            "R146 remains historical",
            "R145 remains historical",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(surface="roadmap", marker=marker):
                self.assertIn(marker, roadmap_flat)

        self.assertNotIn(
            "R146 is the current public documentation revision",
            status_flat,
        )
        self.assertNotIn("R146 is the latest public documentation revision", roadmap_flat)

    def test_public_status_and_roadmap_preserve_r141_entry_history(self) -> None:
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        status_flat = " ".join(status.split())
        roadmap_flat = " ".join(roadmap.split())

        for marker in (
            "R179 is the current public documentation revision",
            "ebcdd003d062c6bc90b5ea546da3d430911bda74",
            "ec765b5f824a92d2efdc065b4a225d7779a6e9d2",
            "docs/COMPANY-PACK-NEXT-STEPS.md",
            "docs/INSTALLATION-LIFECYCLE.md",
            "test_company_pack_next_steps_entry_navigation.py",
            "test_installation_lifecycle_docs.py",
            "R140 remains historical",
            "R139 remains historical",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(surface="status", marker=marker):
                self.assertIn(marker, status_flat)

        for marker in (
            "R179 is the latest public documentation revision",
            "Company Pack Guided Next Steps and Installation Lifecycle",
            "ebcdd003d062c6bc90b5ea546da3d430911bda74",
            "ec765b5f824a92d2efdc065b4a225d7779a6e9d2",
            "R140 remains historical",
            "R139 remains historical",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(surface="roadmap", marker=marker):
                self.assertIn(marker, roadmap_flat)

        self.assertNotIn(
            "R133 is the current public README Document Map layer-wording revision",
            status_flat,
        )
        self.assertNotIn("R133 is the latest public documentation revision", roadmap_flat)

    def test_public_status_and_roadmap_preserve_r133_document_map_history(self) -> None:
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        status_flat = " ".join(status.split())
        roadmap_flat = " ".join(roadmap.split())

        for marker in (
            "R179 is the current public documentation revision",
            "15a94c9f041c04994ab1ae00630ae0ea58387276",
            "538badff2d305e7b567b312e1ae918579050b44c",
            "README.md",
            "test_readme_company_template_usage.py",
            "Status and Roadmap are orientation",
            "five ideal Company Template layers",
            "Catalog onward remains current read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(surface="status", marker=marker):
                self.assertIn(marker, status_flat)

        for marker in (
            "R179 is the latest public documentation revision",
            "15a94c9f041c04994ab1ae00630ae0ea58387276",
            "538badff2d305e7b567b312e1ae918579050b44c",
            "README Document Map layer-wording",
            "Status and Roadmap are orientation",
            "five ideal Company Template layers",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(surface="roadmap", marker=marker):
                self.assertIn(marker, roadmap_flat)

        self.assertNotIn(
            "R132 is the current public README Document Map layer-wording revision",
            status_flat,
        )
        self.assertNotIn("R132 is the latest public documentation revision", roadmap_flat)

    def test_public_status_and_roadmap_preserve_r130_next_steps_history(self) -> None:
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        status_flat = " ".join(status.split())
        roadmap_flat = " ".join(roadmap.split())

        for marker in (
            "R179 is the current public documentation revision",
            "1667007004f92ac65e0124355fda9b71d81d7e6b",
            "aebd38c2012b745333e66348232dc88804181b65",
            "docs/COMPANY-PACK-NEXT-STEPS.md",
            "test_company_pack_next_steps_entry_navigation.py",
            "ideal/current/smoke",
            "R124 remains historical",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(surface="status", marker=marker):
                self.assertIn(marker, status_flat)

        for marker in (
            "R179 is the latest public documentation revision",
            "Company Pack Next Steps entry navigation",
            "1667007004f92ac65e0124355fda9b71d81d7e6b",
            "aebd38c2012b745333e66348232dc88804181b65",
            "R124 remains historical",
            "R123 remains historical",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(surface="roadmap", marker=marker):
                self.assertIn(marker, roadmap_flat)

        self.assertNotIn(
            "R124 is the current public Template Catalog entry-navigation revision",
            status_flat,
        )
        self.assertNotIn("R124 is the latest public documentation revision", roadmap_flat)

    def test_public_status_and_roadmap_preserve_r122_navigation_history(self) -> None:
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        status_flat = " ".join(status.split())
        roadmap_flat = " ".join(roadmap.split())

        for marker in (
            "R179 is the current public documentation revision",
            "677bd15bec0fdfd22410b237916d05be0d1ca02c",
            "299a0248734daec3974b80ff174b4540995f4c47",
            "templates/blocks/README.md",
            "templates/records/README.md",
            "test_blocks_records_navigation.py",
            "ideal/current/smoke",
            "R121 remains historical",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(surface="status", marker=marker):
                self.assertIn(marker, status_flat)

        for marker in (
            "R179 is the latest public documentation revision",
            "Blocks/Records navigation",
            "677bd15bec0fdfd22410b237916d05be0d1ca02c",
            "299a0248734daec3974b80ff174b4540995f4c47",
            "R121 remains historical",
            "R120 remains historical",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(surface="roadmap", marker=marker):
                self.assertIn(marker, roadmap_flat)

        self.assertNotIn(
            "R119 is the current public Company Pack Catalog Runbook smoke revision",
            status_flat,
        )
        self.assertNotIn("R119 is the latest public documentation revision", roadmap_flat)

    def test_public_status_and_roadmap_preserve_r119_catalog_smoke_history(self) -> None:
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        status_flat = " ".join(status.split())
        roadmap_flat = " ".join(roadmap.split())

        for marker in (
            "R179 is the current public documentation revision",
            "b878464eca0571fe293222d372cf417c9e9e1573",
            "f5aa3a3fa405c0e5fed4d984921d6ad44dca0bd3",
            "COMPANY-PACK-CATALOG.md",
            "test_company_pack_catalog_runbook_smoke_entry.py",
            "CANDIDATE_FOR_GOVERNED_REVIEW",
            "MATCH",
            "CUSTOMIZATION_REQUIRED",
            "BUNDLE_REFUSED",
            "R118 remains historical",
            "R117 remains historical",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, status_flat)

        for marker in (
            "R179 is the latest public documentation revision",
            "Company Pack Catalog Runbook smoke entry",
            "b878464eca0571fe293222d372cf417c9e9e1573",
            "f5aa3a3fa405c0e5fed4d984921d6ad44dca0bd3",
            "R118 remains historical",
            "R117 remains historical",
            "CANDIDATE_FOR_GOVERNED_REVIEW",
            "MATCH",
            "CUSTOMIZATION_REQUIRED",
            "BUNDLE_REFUSED",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, roadmap_flat)

    def test_public_status_and_roadmap_preserve_r119_fixed_point_history(self) -> None:
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        status_flat = " ".join(status.split())
        roadmap_flat = " ".join(roadmap.split())

        self.assertIn(
            "R179 is the current public documentation revision",
            status_flat,
        )
        self.assertIn("2a5a65cdbefc0e1fc33c88771a95443ed52d5960", status_flat)
        self.assertIn("456d5a990ae030699246959e12daf0a4a9cbb6d1", status_flat)
        self.assertIn("README Quick Start", status_flat)
        self.assertIn("STARTER-WALKTHROUGH.md", status_flat)
        self.assertIn("test_public_starter_runbook_smoke.py", status_flat)
        self.assertIn("SCHEMA-VALIDATOR-MATRIX.md", status_flat)
        self.assertIn("test_public_starter_runbook_smoke.py", status_flat)
        self.assertIn("guided path reaches bundle", status_flat)
        self.assertIn("CUSTOMIZATION_REQUIRED", status_flat)
        self.assertIn("R112 remains historical", status_flat)
        self.assertIn("R110 remains historical", status_flat)
        self.assertIn("R109 remains historical", status_flat)
        self.assertIn("NO_GO_UNPUBLISHED", status_flat)
        self.assertIn(
            "R179 is the latest public documentation revision",
            roadmap_flat,
        )
        self.assertIn("R111 added the schema/validator/test matrix", roadmap_flat)
        self.assertIn("R116 added the README Runbook smoke entry", roadmap_flat)
        self.assertIn("2a5a65cdbefc0e1fc33c88771a95443ed52d5960", roadmap_flat)
        self.assertIn("456d5a990ae030699246959e12daf0a4a9cbb6d1", roadmap_flat)
        self.assertIn("R115 remains historical", roadmap_flat)
        self.assertIn("test_public_starter_runbook_smoke.py", roadmap_flat)
        self.assertIn("CANDIDATE_FOR_GOVERNED_REVIEW", roadmap_flat)
        self.assertIn("MATCH", roadmap_flat)
        self.assertIn("CUSTOMIZATION_REQUIRED", roadmap_flat)
        self.assertIn("R112 remains historical", roadmap_flat)
        self.assertIn("R110 remains historical", roadmap_flat)
        self.assertIn("R109 remains historical", roadmap_flat)
        self.assertIn("read-only/candidate-only", roadmap_flat)
        self.assertIn("NO_GO_UNPUBLISHED", roadmap_flat)
        self.assertIn("Public Beta access", status_flat)
        self.assertIn("Not open", status_flat)

    def test_public_status_and_roadmap_preserve_r107_fixed_point_history(self) -> None:
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        status_flat = " ".join(status.split())
        roadmap_flat = " ".join(roadmap.split())

        self.assertIn(
            "R179 is the current public documentation revision",
            status_flat,
        )
        self.assertIn("de163c060006d50545229fd8ef092f97c583074d", status_flat)
        self.assertIn("a9679c8f2ff04146b8ddaf1803ee094b56b5d4bc", status_flat)
        self.assertIn("R107 aligned the Company Template ideal order", status_flat)
        self.assertIn("R105 added the direct Installation Lifecycle link", status_flat)
        self.assertNotIn(
            "R105 added the direct Installation Lifecycle link in the Template Catalog Runtime profiles row and is the current public",
            status_flat,
        )
        self.assertIn("R105 remains historical", status_flat)
        self.assertIn("R107 remains historical provenance", status_flat)
        self.assertIn("NO_GO_UNPUBLISHED", status_flat)

        self.assertIn("R179 is the latest public documentation revision", roadmap_flat)
        self.assertIn("R107 remains historical provenance", roadmap_flat)
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

        self.assertIn("R179 is the latest public documentation revision", roadmap_flat)
        self.assertIn("R107 remains historical provenance", roadmap_flat)
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
            "R179 is the current public documentation revision",
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

        self.assertIn("R179 is the latest public documentation revision", roadmap_flat)
        self.assertIn("R107 remains historical provenance", roadmap_flat)
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
        self.assertIn(
            "R107 is historical provenance for the Company Pack surface label",
            roadmap_flat,
        )
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
