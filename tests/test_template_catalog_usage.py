from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TemplateCatalogUsageTests(unittest.TestCase):
    def test_company_template_recommended_order_matches_governed_layer_flow(self) -> None:
        company = (ROOT / "templates" / "company" / "README.md").read_text(
            encoding="utf-8"
        )
        start = company.index("## Recommended order")
        end = company.index("## 最初に読む: Company Templateからstarterへ", start)
        section = company[start:end]
        markers = (
            "Human Intent",
            "fact family",
            "必要なBlock",
            "Governed Record",
            "MOC",
            "validator",
            "runtime profile",
            "synthetic",
        )
        positions = [section.index(marker) for marker in markers]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("read-only/candidate-only", section)
        self.assertIn("NO_GO_UNPUBLISHED", section)

    def test_runtime_profile_row_links_directly_to_installation_lifecycle(self) -> None:
        catalog = (ROOT / "templates" / "README.md").read_text(encoding="utf-8")
        row = next(
            line for line in catalog.splitlines() if "[Runtime profiles]" in line
        )
        self.assertIn(
            "[Installation Lifecycle](../docs/INSTALLATION-LIFECYCLE.md)",
            row,
        )
        self.assertTrue((ROOT / "docs" / "INSTALLATION-LIFECYCLE.md").is_file())
        self.assertIn("read-only/candidate-only", " ".join(catalog.split()))
        self.assertIn("NO_GO_UNPUBLISHED", catalog)

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

    def test_company_pack_catalog_exposes_direct_links_to_each_template_layer(self) -> None:
        catalog = (ROOT / "docs" / "COMPANY-PACK-CATALOG.md").read_text(
            encoding="utf-8"
        )
        layer_map = catalog.index("## Template層への直接リンク")
        section_end = catalog.index("## Quick start", layer_map)
        section = catalog[layer_map:section_end]

        required = (
            "[Company Template](../templates/company/README.md)",
            "[Blocks](../templates/blocks/README.md)",
            "[Governed Records](../templates/records/README.md)",
            "[MOCs](../templates/mocs/company-operations-moc.md)",
            "[Company starter](../examples/company-starter/README.md)",
            "[Template Guide](TEMPLATE-GUIDE.md)",
            "[Starter Walkthrough](STARTER-WALKTHROUGH.md)",
            "[Public Preview Self-check](PUBLIC-PREVIEW-SELF-CHECK.md)",
            "[Installation Lifecycle](INSTALLATION-LIFECYCLE.md)",
            "navigation-only",
            "NO_GO_UNPUBLISHED",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, section)

        for relative_path in (
            "../templates/company/README.md",
            "../templates/blocks/README.md",
            "../templates/records/README.md",
            "../templates/mocs/company-operations-moc.md",
            "../examples/company-starter/README.md",
            "TEMPLATE-GUIDE.md",
            "STARTER-WALKTHROUGH.md",
            "PUBLIC-PREVIEW-SELF-CHECK.md",
            "INSTALLATION-LIFECYCLE.md",
        ):
            with self.subTest(relative_path=relative_path):
                self.assertTrue((ROOT / "docs" / relative_path).exists())

        for earlier, later in (
            (
                "[Company Template](../templates/company/README.md)",
                "[Blocks](../templates/blocks/README.md)",
            ),
            (
                "[Blocks](../templates/blocks/README.md)",
                "[Governed Records](../templates/records/README.md)",
            ),
            (
                "[Governed Records](../templates/records/README.md)",
                "[MOCs](../templates/mocs/company-operations-moc.md)",
            ),
            (
                "[MOCs](../templates/mocs/company-operations-moc.md)",
                "[Company starter](../examples/company-starter/README.md)",
            ),
        ):
            with self.subTest(earlier=earlier, later=later):
                self.assertLess(section.index(earlier), section.index(later))

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

        for relative_path in (
            "mocs/company-operations-moc.md",
            "mocs/public-release-moc.md",
            "mocs/incident-recovery-moc.md",
        ):
            with self.subTest(relative_path=relative_path):
                self.assertTrue((ROOT / "templates" / relative_path).exists())

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

    def test_template_catalog_exposes_shipped_moc_map_by_purpose(self) -> None:
        catalog = (ROOT / "templates" / "README.md").read_text(encoding="utf-8")
        moc_map = catalog.index("## MOCを目的で選ぶ")
        section_end = catalog.index("## 最短の確認手順", moc_map)
        section = catalog[moc_map:section_end]

        required = (
            "[Company Operations MOC](mocs/company-operations-moc.md)",
            "[Public Release Review MOC](mocs/public-release-moc.md)",
            "[Incident / Recovery MOC](mocs/incident-recovery-moc.md)",
            "same canonical flow",
            "navigation-only",
            "NO_GO_UNPUBLISHED",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, section)

        for earlier, later in (
            (
                "[Company Operations MOC](mocs/company-operations-moc.md)",
                "[Public Release Review MOC](mocs/public-release-moc.md)",
            ),
            (
                "[Public Release Review MOC](mocs/public-release-moc.md)",
                "[Incident / Recovery MOC](mocs/incident-recovery-moc.md)",
            ),
        ):
            with self.subTest(earlier=earlier, later=later):
                self.assertLess(section.index(earlier), section.index(later))

    def test_blocks_catalog_exposes_all_shipped_blocks_in_canonical_order(self) -> None:
        blocks = (ROOT / "templates" / "blocks" / "README.md").read_text(
            encoding="utf-8"
        )
        block_map = blocks.index("## 公開starterの9 Blocksを目的で選ぶ")
        section_end = blocks.index("## 現在のstarterと後続review", block_map)
        section = blocks[block_map:section_end]

        required = (
            "Source Intake",
            "Intent Candidate",
            "Human Decision",
            "Work Order",
            "Capability Grant",
            "Change Execution",
            "Verification Receipt",
            "Promotion Gate",
            "Promotion Decision",
            "canonical flow",
            "candidate-only",
            "NO_GO_UNPUBLISHED",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, section)

        paths = (
            "source-intake.json",
            "intent-candidate.json",
            "human-decision.json",
            "work-order.json",
            "capability-grant.json",
            "change-execution.json",
            "verification-receipt.json",
            "promotion-gate.json",
            "promotion-decision.json",
        )
        for path in paths:
            marker = f"../../examples/company-starter/blocks/{path}"
            with self.subTest(path=path):
                self.assertIn(marker, section)
                self.assertTrue((ROOT / "examples" / "company-starter" / "blocks" / path).exists())

        for earlier, later in zip(paths, paths[1:]):
            earlier_marker = f"../../examples/company-starter/blocks/{earlier}"
            later_marker = f"../../examples/company-starter/blocks/{later}"
            with self.subTest(earlier=earlier, later=later):
                self.assertLess(section.index(earlier_marker), section.index(later_marker))

    def test_company_template_entry_exposes_first_use_navigation_and_command_parity(self) -> None:
        company = (ROOT / "templates" / "company" / "README.md").read_text(
            encoding="utf-8"
        )
        first_use = company.index("## 最初に読む: Company Templateからstarterへ")
        section_end = company.index("## Current status", first_use)
        section = company[first_use:section_end]

        required = (
            "[Company Pack Catalog](../../docs/COMPANY-PACK-CATALOG.md)",
            "[Starter Walkthrough](../../docs/STARTER-WALKTHROUGH.md)",
            "[Public Preview Self-check](../../docs/PUBLIC-PREVIEW-SELF-CHECK.md)",
            "[Installation Lifecycle](../../docs/INSTALLATION-LIFECYCLE.md)",
            "[公開starter](../../examples/company-starter/README.md)",
            "~~~powershell",
            "python tools\\catalog_company_pack.py examples\\company-starter --format markdown",
            "New-Item -ItemType Directory -Force work | Out-Null",
            "python tools\\create_company_pack.py my-company work\\my-company",
            "python tools\\check_company_pack_customization.py work\\my-company",
            "python tools\\validate_template_pack.py work\\my-company",
            "python tools\\check_company_pack_public_preview.py work\\my-company --format markdown",
            "~~~bash",
            "python3 tools/catalog_company_pack.py examples/company-starter --format markdown",
            "mkdir -p work",
            "python3 tools/create_company_pack.py my-company work/my-company",
            "python3 tools/check_company_pack_customization.py work/my-company",
            "python3 tools/validate_template_pack.py work/my-company",
            "python3 tools/check_company_pack_public_preview.py work/my-company --format markdown",
            "既存のtargetを上書きしません",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, section)

        for earlier, later in (
            (
                "[Company Pack Catalog](../../docs/COMPANY-PACK-CATALOG.md)",
                "[Starter Walkthrough](../../docs/STARTER-WALKTHROUGH.md)",
            ),
            (
                "[Starter Walkthrough](../../docs/STARTER-WALKTHROUGH.md)",
                "[Public Preview Self-check](../../docs/PUBLIC-PREVIEW-SELF-CHECK.md)",
            ),
            (
                "[Public Preview Self-check](../../docs/PUBLIC-PREVIEW-SELF-CHECK.md)",
                "[Installation Lifecycle](../../docs/INSTALLATION-LIFECYCLE.md)",
            ),
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
            (
                "python3 tools/validate_template_pack.py work/my-company",
                "python3 tools/check_company_pack_public_preview.py work/my-company --format markdown",
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

    def test_records_catalog_exposes_all_shipped_records_in_canonical_order(self) -> None:
        records = (ROOT / "templates" / "records" / "README.md").read_text(
            encoding="utf-8"
        )
        record_map = records.index("## 公開starterの9 Governed Recordsを目的で選ぶ")
        section_end = records.index("## まだ証明しないこと", record_map)
        section = records[record_map:section_end]

        required = (
            "Source Record",
            "Intent Candidate",
            "Decision Record",
            "Work Order Candidate",
            "Capability Grant Candidate",
            "Change Candidate",
            "Verification Receipt",
            "Promotion Candidate",
            "Promotion Decision Record",
            "canonical flow",
            "candidate-only",
            "NO_GO_UNPUBLISHED",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, section)

        paths = (
            "source-record.json",
            "intent-candidate.json",
            "decision-record.json",
            "work-order-candidate.json",
            "capability-grant-candidate.json",
            "change-candidate.json",
            "verification-receipt.json",
            "promotion-candidate.json",
            "promotion-decision-record.json",
        )
        for path in paths:
            marker = f"../../examples/company-starter/records/{path}"
            with self.subTest(path=path):
                self.assertIn(marker, section)
                self.assertTrue(
                    (ROOT / "examples" / "company-starter" / "records" / path).exists()
                )

        for earlier, later in zip(paths, paths[1:]):
            earlier_marker = f"../../examples/company-starter/records/{earlier}"
            later_marker = f"../../examples/company-starter/records/{later}"
            with self.subTest(earlier=earlier, later=later):
                self.assertLess(section.index(earlier_marker), section.index(later_marker))

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

    def test_starter_walkthrough_exposes_layer_reading_entry_before_initializer(self) -> None:
        walkthrough = (ROOT / "docs" / "STARTER-WALKTHROUGH.md").read_text(
            encoding="utf-8"
        )
        reading = walkthrough.index("## 0. まず層を読む")
        initializer = walkthrough.index("## 1. initializerで作業copyを作る", reading)
        section = walkthrough[reading:initializer]

        required = (
            "[Company Template](../templates/company/README.md)",
            "[Blocks](../templates/blocks/README.md)",
            "[Governed Records](../templates/records/README.md)",
            "[MOCs](../templates/mocs/company-operations-moc.md)",
            "[Company Pack Catalog](COMPANY-PACK-CATALOG.md)",
            "[Public Preview Self-check](PUBLIC-PREVIEW-SELF-CHECK.md)",
            "理想",
            "現在",
            "runtimeを起動せず",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, section)

        for relative_path in (
            "../templates/company/README.md",
            "../templates/blocks/README.md",
            "../templates/records/README.md",
            "../templates/mocs/company-operations-moc.md",
            "COMPANY-PACK-CATALOG.md",
            "PUBLIC-PREVIEW-SELF-CHECK.md",
        ):
            with self.subTest(relative_path=relative_path):
                self.assertTrue((ROOT / "docs" / relative_path).exists())

        for earlier, later in (
            (
                "[Company Template](../templates/company/README.md)",
                "[Blocks](../templates/blocks/README.md)",
            ),
            (
                "[Blocks](../templates/blocks/README.md)",
                "[Governed Records](../templates/records/README.md)",
            ),
            (
                "[Governed Records](../templates/records/README.md)",
                "[MOCs](../templates/mocs/company-operations-moc.md)",
            ),
            (
                "[MOCs](../templates/mocs/company-operations-moc.md)",
                "[Company Pack Catalog](COMPANY-PACK-CATALOG.md)",
            ),
            (
                "[Company Pack Catalog](COMPANY-PACK-CATALOG.md)",
                "[Public Preview Self-check](PUBLIC-PREVIEW-SELF-CHECK.md)",
            ),
        ):
            with self.subTest(earlier=earlier, later=later):
                self.assertLess(section.index(earlier), section.index(later))

    def test_public_preview_self_check_exposes_cross_navigation_entry(self) -> None:
        self_check = (ROOT / "docs" / "PUBLIC-PREVIEW-SELF-CHECK.md").read_text(
            encoding="utf-8"
        )
        reading = self_check.index("## 0. 読み始める場所")
        quick_start = self_check.index("## Quick start", reading)
        section = self_check[reading:quick_start]

        required = (
            "[Template Guide](TEMPLATE-GUIDE.md)",
            "[Company Template](../templates/company/README.md)",
            "[Blocks](../templates/blocks/README.md)",
            "[Governed Records](../templates/records/README.md)",
            "[MOCs](../templates/mocs/company-operations-moc.md)",
            "[Company Pack Catalog](COMPANY-PACK-CATALOG.md)",
            "[Starter Walkthrough](STARTER-WALKTHROUGH.md)",
            "[Installation Lifecycle](INSTALLATION-LIFECYCLE.md)",
            "理想",
            "現在",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, section)

        for relative_path in (
            "TEMPLATE-GUIDE.md",
            "../templates/company/README.md",
            "../templates/blocks/README.md",
            "../templates/records/README.md",
            "../templates/mocs/company-operations-moc.md",
            "COMPANY-PACK-CATALOG.md",
            "STARTER-WALKTHROUGH.md",
            "INSTALLATION-LIFECYCLE.md",
        ):
            with self.subTest(relative_path=relative_path):
                self.assertTrue((ROOT / "docs" / relative_path).exists())

        for earlier, later in (
            (
                "[Template Guide](TEMPLATE-GUIDE.md)",
                "[Company Template](../templates/company/README.md)",
            ),
            (
                "[Company Template](../templates/company/README.md)",
                "[Blocks](../templates/blocks/README.md)",
            ),
            (
                "[Blocks](../templates/blocks/README.md)",
                "[Governed Records](../templates/records/README.md)",
            ),
            (
                "[Governed Records](../templates/records/README.md)",
                "[MOCs](../templates/mocs/company-operations-moc.md)",
            ),
            (
                "[MOCs](../templates/mocs/company-operations-moc.md)",
                "[Company Pack Catalog](COMPANY-PACK-CATALOG.md)",
            ),
            (
                "[Company Pack Catalog](COMPANY-PACK-CATALOG.md)",
                "[Starter Walkthrough](STARTER-WALKTHROUGH.md)",
            ),
            (
                "[Starter Walkthrough](STARTER-WALKTHROUGH.md)",
                "[Installation Lifecycle](INSTALLATION-LIFECYCLE.md)",
            ),
        ):
            with self.subTest(earlier=earlier, later=later):
                self.assertLess(section.index(earlier), section.index(later))
