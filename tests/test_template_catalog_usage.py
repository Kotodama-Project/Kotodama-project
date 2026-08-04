from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TemplateCatalogUsageTests(unittest.TestCase):
    def test_template_catalog_explains_layer_order_and_current_preview_boundary(self) -> None:
        catalog = (ROOT / "templates" / "README.md").read_text(encoding="utf-8")
        flat = " ".join(catalog.split())

        self.assertIn("## 使う順番", catalog)
        self.assertIn("Company Template", catalog)
        self.assertIn("Blocks", catalog)
        self.assertIn("Governed Records", catalog)
        self.assertIn("MOCs", catalog)
        self.assertIn("runtime profile", catalog)
        self.assertIn("理想", catalog)
        self.assertIn("現在", catalog)
        self.assertIn("read-only/candidate-only", flat)
        self.assertIn("navigation-only", flat)
        self.assertIn("Public Beta GO", flat)
        self.assertIn("../docs/COMPANY-PACK-CATALOG.md", catalog)
        self.assertIn("../docs/TEMPLATE-GUIDE.md", catalog)
        self.assertIn("../docs/STARTER-WALKTHROUGH.md", catalog)
        self.assertIn("../docs/PUBLIC-PREVIEW-SELF-CHECK.md", catalog)
        self.assertIn("../examples/company-starter/README.md", catalog)

        for link in (
            "../docs/COMPANY-PACK-CATALOG.md",
            "../docs/TEMPLATE-GUIDE.md",
            "../docs/STARTER-WALKTHROUGH.md",
            "../docs/PUBLIC-PREVIEW-SELF-CHECK.md",
            "../examples/company-starter/README.md",
        ):
            self.assertTrue((ROOT / "templates" / link).exists(), link)

    def test_company_pack_catalog_exposes_first_stop_sequence(self) -> None:
        catalog = (ROOT / "docs" / "COMPANY-PACK-CATALOG.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("## 最初に選ぶ", catalog)
        first_stop = catalog.index("## 最初に選ぶ")
        section_end = catalog.index("## Quick start", first_stop)
        section = catalog[first_stop:section_end]
        for marker in (
            "Company Pack Catalog",
            "[Starter Walkthrough](STARTER-WALKTHROUGH.md)",
            "[Installation Lifecycle](INSTALLATION-LIFECYCLE.md)",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, section)

        starter = section.index("[Starter Walkthrough](STARTER-WALKTHROUGH.md)")
        lifecycle = section.index(
            "[Installation Lifecycle](INSTALLATION-LIFECYCLE.md)"
        )
        self.assertLess(starter, lifecycle)

    def test_template_catalog_exposes_copy_paste_first_use_path(self) -> None:
        catalog = (ROOT / "templates" / "README.md").read_text(encoding="utf-8")
        first_use = catalog.index("## 最短の確認手順")
        section_end = catalog.index("## Planned catalog", first_use)
        section = catalog[first_use:section_end]

        required = (
            "~~~powershell",
            "python tools\\catalog_company_pack.py examples/company-starter --format markdown",
            "New-Item -ItemType Directory -Force work | Out-Null",
            "python tools\\create_company_pack.py my-company work\\my-company",
            "python tools\\check_company_pack_customization.py work\\my-company",
            "python tools\\catalog_company_pack.py work\\my-company --format markdown",
            "python tools\\validate_template_pack.py work\\my-company",
            "~~~bash",
            "python3 tools/catalog_company_pack.py examples/company-starter --format markdown",
            "python3 tools/create_company_pack.py my-company work/my-company",
            "python3 tools/check_company_pack_customization.py work/my-company",
            "python3 tools/catalog_company_pack.py work/my-company --format markdown",
            "python3 tools/validate_template_pack.py work/my-company",
            "既存のtargetを上書きしません",
            "[Starter Walkthrough](../docs/STARTER-WALKTHROUGH.md)",
            "[Public Preview Self-check](../docs/PUBLIC-PREVIEW-SELF-CHECK.md)",
            "NO_GO_UNPUBLISHED",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, section)

        for earlier, later in (
            (
                "python3 tools/catalog_company_pack.py examples/company-starter --format markdown",
                "python3 tools/create_company_pack.py my-company work/my-company",
            ),
            (
                "python3 tools/create_company_pack.py my-company work/my-company",
                "python3 tools/check_company_pack_customization.py work/my-company",
            ),
            (
                "python3 tools/check_company_pack_customization.py work/my-company",
                "python3 tools/validate_template_pack.py work/my-company",
            ),
        ):
            with self.subTest(earlier=earlier, later=later):
                self.assertLess(section.index(earlier), section.index(later))

    def test_template_guide_separates_ideal_mocs_from_shipped_current_mocs(self) -> None:
        guide = (ROOT / "docs" / "TEMPLATE-GUIDE.md").read_text(encoding="utf-8")
        ideal_marker = "Conceptual ideal/future MOC candidates (not shipped starter files)"
        current_marker = "The public starter currently ships exactly three MOCs:"
        self.assertIn(ideal_marker, guide)
        self.assertIn(current_marker, guide)

        ideal_start = guide.index(ideal_marker)
        current_start = guide.index(current_marker)
        ideal = guide[ideal_start:current_start]
        current = guide[current_start:]
        for future_moc in ("Voice Operations MOC", "Venture / Customer Discovery MOC"):
            with self.subTest(future_moc=future_moc):
                self.assertIn(future_moc, ideal)
                self.assertNotIn(future_moc, current)
        for shipped_moc in (
            "Company Operations",
            "Public Release Review",
            "Incident / Recovery",
        ):
            with self.subTest(shipped_moc=shipped_moc):
                self.assertIn(shipped_moc, current)

    def test_template_guide_and_catalog_expose_work_copy_posix_parity(self) -> None:
        guide = (ROOT / "docs" / "TEMPLATE-GUIDE.md").read_text(encoding="utf-8")
        catalog = (ROOT / "docs" / "COMPANY-PACK-CATALOG.md").read_text(
            encoding="utf-8"
        )

        guide_markers = (
            "python tools/catalog_company_pack.py examples/company-starter --format markdown",
            "python3 tools/catalog_company_pack.py examples/company-starter --format markdown",
            "python tools/check_company_pack_public_preview.py examples/company-starter",
            "python3 tools/check_company_pack_public_preview.py examples/company-starter",
        )
        catalog_markers = (
            "python tools/create_company_pack.py my-company work/my-company",
            "python3 tools/create_company_pack.py my-company work/my-company",
            "python tools/catalog_company_pack.py work/my-company --format markdown",
            "python3 tools/catalog_company_pack.py work/my-company --format markdown",
            "python tools/validate_template_pack.py work/my-company",
            "python3 tools/validate_template_pack.py work/my-company",
        )
        for marker in guide_markers:
            with self.subTest(surface="guide", marker=marker):
                self.assertIn(marker, guide)
        for marker in catalog_markers:
            with self.subTest(surface="catalog", marker=marker):
                self.assertIn(marker, catalog)

        for surface, text, earlier, later in (
            (
                "guide",
                guide,
                "python3 tools/catalog_company_pack.py examples/company-starter --format markdown",
                "python3 tools/check_company_pack_public_preview.py examples/company-starter",
            ),
            (
                "catalog",
                catalog,
                "python3 tools/create_company_pack.py my-company work/my-company",
                "python3 tools/validate_template_pack.py work/my-company",
            ),
        ):
            with self.subTest(surface=surface, order=(earlier, later)):
                self.assertLess(text.index(earlier), text.index(later))

    def test_guided_onboarding_surfaces_expose_remaining_posix_paths(self) -> None:
        checklist = (ROOT / "docs" / "CUSTOMIZATION-CHECKLIST.md").read_text(
            encoding="utf-8"
        )
        initializer = (
            ROOT / "docs" / "GUIDED-COMPANY-PACK-INITIALIZATION.md"
        ).read_text(encoding="utf-8")
        next_steps = (ROOT / "docs" / "COMPANY-PACK-NEXT-STEPS.md").read_text(
            encoding="utf-8"
        )

        checklist_markers = (
            "python tools\\plan_company_pack_next_steps.py work\\my-company --format markdown",
            "python3 tools/plan_company_pack_next_steps.py work/my-company --format markdown",
            "NO_GO_UNPUBLISHED",
        )
        initializer_markers = (
            "python tools/create_company_pack.py my-company work/my-company",
            "python3 tools/create_company_pack.py my-company work/my-company",
            "python tools/check_company_pack_customization.py work/my-company",
            "python3 tools/check_company_pack_customization.py work/my-company",
            "python tools/plan_company_pack_next_steps.py work/my-company --format markdown",
            "python3 tools/plan_company_pack_next_steps.py work/my-company --format markdown",
            "NO_GO_UNPUBLISHED",
        )
        next_steps_markers = (
            "python tools\\plan_company_pack_next_steps.py work\\my-company",
            "python3 tools/plan_company_pack_next_steps.py work/my-company",
            "NO_GO_UNPUBLISHED",
        )
        for surface, text, markers in (
            ("checklist", checklist, checklist_markers),
            ("initializer", initializer, initializer_markers),
            ("next_steps", next_steps, next_steps_markers),
        ):
            for marker in markers:
                with self.subTest(surface=surface, marker=marker):
                    self.assertIn(marker, text)

        for surface, text, earlier, later in (
            (
                "initializer",
                initializer,
                "python3 tools/create_company_pack.py my-company work/my-company",
                "python3 tools/plan_company_pack_next_steps.py work/my-company --format markdown",
            ),
            (
                "next_steps",
                next_steps,
                "python3 tools/plan_company_pack_next_steps.py work/my-company",
                "## 現在地の読み方",
            ),
        ):
            with self.subTest(surface=surface, order=(earlier, later)):
                self.assertLess(text.index(earlier), text.index(later))

    def test_onboarding_surfaces_expose_power_shell_and_posix_command_parity(self) -> None:
        starter = (ROOT / "docs" / "STARTER-WALKTHROUGH.md").read_text(
            encoding="utf-8"
        )
        example = (ROOT / "examples" / "company-starter" / "README.md").read_text(
            encoding="utf-8"
        )

        starter_markers = (
            "python tools\\check_company_pack_customization.py work\\my-company",
            "python3 tools/check_company_pack_customization.py work/my-company",
            "python tools\\plan_company_pack_next_steps.py work\\my-company --format markdown",
            "python3 tools/plan_company_pack_next_steps.py work/my-company --format markdown",
            "python tools\\check_company_pack_public_preview.py work\\my-company --format markdown",
            "python3 tools/check_company_pack_public_preview.py work/my-company --format markdown",
            "python tools\\catalog_company_pack.py work\\my-company --format markdown",
            "python3 tools/catalog_company_pack.py work/my-company --format markdown",
            "python tools\\build_company_pack_review_bundle.py work\\my-company",
            "python3 tools/build_company_pack_review_bundle.py work/my-company",
            "NO_GO_UNPUBLISHED",
        )
        example_markers = (
            "python tools/catalog_company_pack.py examples/company-starter --format markdown",
            "python3 tools/catalog_company_pack.py examples/company-starter --format markdown",
            "python tools/check_company_pack_public_preview.py examples/company-starter --format markdown",
            "python3 tools/check_company_pack_public_preview.py examples/company-starter --format markdown",
            "python tools/validate_template_pack.py examples/company-starter",
            "python3 tools/validate_template_pack.py examples/company-starter",
            "python tools/create_company_pack.py my-company work/my-company",
            "python3 tools/create_company_pack.py my-company work/my-company",
            "python tools/check_company_pack_customization.py work/my-company",
            "python3 tools/check_company_pack_customization.py work/my-company",
            "python tools/plan_company_pack_next_steps.py work/my-company --format markdown",
            "python3 tools/plan_company_pack_next_steps.py work/my-company --format markdown",
            "python tools/build_company_pack_review_bundle.py work/my-company",
            "python3 tools/build_company_pack_review_bundle.py work/my-company",
            "NO_GO_UNPUBLISHED",
        )
        for marker in starter_markers:
            with self.subTest(surface="starter", marker=marker):
                self.assertIn(marker, starter)
        for marker in example_markers:
            with self.subTest(surface="example", marker=marker):
                self.assertIn(marker, example)

        for earlier, later in (
            (
                "python3 tools/check_company_pack_customization.py work/my-company",
                "python3 tools/catalog_company_pack.py work/my-company --format markdown",
            ),
            (
                "python3 tools/catalog_company_pack.py work/my-company --format markdown",
                "python3 tools/build_company_pack_review_bundle.py work/my-company",
            ),
        ):
            with self.subTest(earlier=earlier, later=later):
                self.assertLess(starter.index(earlier), starter.index(later))
