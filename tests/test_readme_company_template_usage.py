from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ReadmeCompanyTemplateUsageTests(unittest.TestCase):
    def test_readme_quick_start_keeps_generated_candidate_as_target(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        start = readme.index("## Quick Start — Company starter を試す")
        end = readme.index("## Runtime candidate を検査する", start)
        section = readme[start:end]

        for marker in (
            "examples/company-starter",
            "公開example",
            "work/my-company",
            "生成した候補",
            "plan_company_pack_next_steps.py",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, section)

        candidate_commands = (
            "python tools/validate_template_pack.py work/my-company",
            "python tools/catalog_company_pack.py work/my-company --format markdown",
            "python tools/check_company_pack_public_preview.py work/my-company",
            "python tools/plan_company_pack_next_steps.py work/my-company --format markdown",
            "python3 tools/validate_template_pack.py work/my-company",
            "python3 tools/catalog_company_pack.py work/my-company --format markdown",
            "python3 tools/check_company_pack_public_preview.py work/my-company",
            "python3 tools/plan_company_pack_next_steps.py work/my-company --format markdown",
        )
        for command in candidate_commands:
            with self.subTest(command=command):
                self.assertIn(command, section)

        for command in (
            "validate_template_pack.py examples/company-starter",
            "catalog_company_pack.py examples/company-starter",
            "check_company_pack_public_preview.py examples/company-starter",
            "plan_company_pack_next_steps.py examples/company-starter",
        ):
            with self.subTest(command=command):
                self.assertNotIn(command, section)

    def test_company_template_entry_exposes_guided_next_steps(self) -> None:
        document_path = ROOT / "templates" / "company" / "README.md"
        document = document_path.read_text(encoding="utf-8")

        for marker in (
            "[Company Pack Catalog](../../docs/COMPANY-PACK-CATALOG.md)",
            "[Company Pack Guided Next Steps](../../docs/COMPANY-PACK-NEXT-STEPS.md)",
            "[Starter Walkthrough](../../docs/STARTER-WALKTHROUGH.md)",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, document)

        self.assertTrue(
            (ROOT / "docs" / "COMPANY-PACK-NEXT-STEPS.md").is_file()
        )

    def test_document_map_exposes_ideal_layers_before_current_entrypoints(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        start = readme.index("### 最初に読む")
        end = readme.index("### Company pack を review する", start)
        section = readme[start:end]
        required = (
            "[Template Guide](docs/TEMPLATE-GUIDE.md)",
            "[Company Template](templates/company/README.md)",
            "[Blocks](templates/blocks/README.md)",
            "[Governed Records](templates/records/README.md)",
            "[MOCs](templates/mocs/README.md)",
            "[Company Pack Catalog](docs/COMPANY-PACK-CATALOG.md)",
            "[Starter Walkthrough](docs/STARTER-WALKTHROUGH.md)",
            "[Public Preview Self-check](docs/PUBLIC-PREVIEW-SELF-CHECK.md)",
            "[Company Pack Guided Next Steps](docs/COMPANY-PACK-NEXT-STEPS.md)",
            "[Installation Lifecycle](docs/INSTALLATION-LIFECYCLE.md)",
            "理想のCompany Template層",
            "Status と Roadmap は公開状況とPublic Beta gateを確認するためのorientationです",
            "その後の5項目",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, section)

        links = required[:10]
        positions = [section.index(link) for link in links]
        self.assertEqual(positions, sorted(positions))
        orientation = section.index(
            "Status と Roadmap は公開状況とPublic Beta gateを確認するためのorientationです"
        )
        template_guide = section.index("[Template Guide](docs/TEMPLATE-GUIDE.md)")
        ideal_layers = section.index("その後の5項目")
        self.assertLess(orientation, template_guide)
        self.assertLess(ideal_layers, template_guide)
        for relative_path in (
            "docs/TEMPLATE-GUIDE.md",
            "templates/company/README.md",
            "templates/blocks/README.md",
            "templates/records/README.md",
            "templates/mocs/README.md",
            "docs/COMPANY-PACK-CATALOG.md",
            "docs/STARTER-WALKTHROUGH.md",
            "docs/PUBLIC-PREVIEW-SELF-CHECK.md",
            "docs/COMPANY-PACK-NEXT-STEPS.md",
            "docs/INSTALLATION-LIFECYCLE.md",
        ):
            with self.subTest(relative_path=relative_path):
                self.assertTrue((ROOT / relative_path).is_file())

    def test_document_map_links_review_chain_artifact_map_after_guided_next_steps(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        start = readme.index("### 最初に読む")
        end = readme.index("### Company pack を review する", start)
        section = readme[start:end]

        required = (
            "[Company Pack Guided Next Steps](docs/COMPANY-PACK-NEXT-STEPS.md)",
            "[Review-chain artifact map](docs/STARTER-WALKTHROUGH.md#review-chain-artifact-map)",
            "artifact states and next handoffs",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, section)

        guided = section.index(
            "[Company Pack Guided Next Steps](docs/COMPANY-PACK-NEXT-STEPS.md)"
        )
        artifact_map = section.find(
            "[Review-chain artifact map](docs/STARTER-WALKTHROUGH.md#review-chain-artifact-map)"
        )
        if artifact_map < 0:
            return
        lifecycle = section.index("[Installation Lifecycle](docs/INSTALLATION-LIFECYCLE.md)")
        self.assertLess(guided, artifact_map)
        self.assertLess(artifact_map, lifecycle)
        self.assertTrue(
            (ROOT / "docs" / "STARTER-WALKTHROUGH.md").is_file()
        )

    def test_readme_distinguishes_ideal_and_current_template_usage(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        required = (
            "理想の使い方",
            "現在の Public Preview でできること",
            "Company Template を複製",
            "activation candidate",
            "candidate-only",
            "Public Beta",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, readme)

    def test_template_usage_flow_preserves_governance_order(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        ideal = readme.index("Company Template を複製")
        validator = readme.index("validator", ideal)
        review = readme.index("Review Bundle", validator)
        activation = readme.index("activation candidate", review)
        self.assertLess(ideal, validator)
        self.assertLess(validator, review)
        self.assertLess(review, activation)

    def test_readme_first_stop_points_to_catalog_before_runtime_profiles(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        for marker in (
            "## 最初に選ぶ",
            "Company Pack Catalog",
            "Starter Walkthrough",
            "Installation Lifecycle",
            "compose_minimum",
            "proxmox_segmented",
            "read-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, readme)

        first_stop = readme.index("## 最初に選ぶ")
        catalog = readme.index("Company Pack Catalog", first_stop)
        starter = readme.index("Starter Walkthrough", first_stop)
        lifecycle = readme.index("Installation Lifecycle", first_stop)
        self.assertLess(catalog, starter)
        self.assertLess(starter, lifecycle)

    def test_readme_exposes_posix_examples_for_the_same_public_candidate_path(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        required = (
            "```bash\nmkdir -p work",
            "python3 tools/create_company_pack.py my-company work/my-company",
            "python3 tools/check_company_pack_customization.py work/my-company",
            "python3 tools/validate_template_pack.py work/my-company",
            "python3 tools/catalog_company_pack.py work/my-company --format markdown",
            "python3 tools/check_company_pack_public_preview.py work/my-company --format markdown",
            "python3 tools/plan_company_pack_next_steps.py work/my-company --format markdown",
            "bundle_path='work/my-company-review-bundle.json'",
            "python3 tools/build_company_pack_review_bundle.py work/my-company",
            "python3 tools/verify_company_pack_review_bundle.py \"$bundle_path\" work/my-company",
            "python3 tools/validate_installation_lifecycle.py \\\n  examples/installation-lifecycle/compose-minimum.json",
            "python3 tools/validate_installation_lifecycle.py \\\n  examples/installation-lifecycle/proxmox-segmented.json",
            "python3 tools/validate_compose_minimum_skeleton.py runtime/compose-minimum",
            "NO_GO_UNPUBLISHED",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, readme)

    def test_readme_keeps_posix_candidate_commands_in_governance_order(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        quick_start = readme.index("## Quick Start — Company starter を試す")
        runtime = readme.index("## Runtime candidate を検査する", quick_start)
        section = readme[quick_start:runtime]
        for earlier, later in (
            (
                "python3 tools/create_company_pack.py my-company work/my-company",
                "python3 tools/check_company_pack_customization.py work/my-company",
            ),
            (
                "python3 tools/check_company_pack_customization.py work/my-company",
                "python3 tools/build_company_pack_review_bundle.py work/my-company",
            ),
            (
                "python3 tools/build_company_pack_review_bundle.py work/my-company",
                "python3 tools/verify_company_pack_review_bundle.py \"$bundle_path\" work/my-company",
            ),
        ):
            with self.subTest(earlier=earlier, later=later):
                self.assertLess(section.index(earlier), section.index(later))


if __name__ == "__main__":
    unittest.main()
