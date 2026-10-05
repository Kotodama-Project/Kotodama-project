from pathlib import Path
import re
import unittest


from tests.document_contract_helpers import section, assert_links, shell_commands, assert_command_order, table_rows, assert_preview_boundary, headings, link_targets

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs" / "SCHEMA-VALIDATOR-MATRIX.md"


class SchemaValidatorMatrixDocumentationTests(unittest.TestCase):
    def test_matrix_exposes_ideal_current_smoke_first_stop(self) -> None:
        matrix = MATRIX.read_text(encoding="utf-8")
        start = matrix.index("## Read next: ideal -> current -> smoke")
        end = matrix.index("## 使い方", start)
        section = matrix[start:end]

        for marker in (
            "**Ideal:**",
            "[Company Template](../templates/company/README.md)",
            "[Blocks](../templates/blocks/README.md)",
            "[Governed Records](../templates/records/README.md)",
            "[MOCs](../templates/mocs/README.md)",
            "**Current:**",
            "[Company Pack Catalog](COMPANY-PACK-CATALOG.md)",
            "[Company Pack Guided Next Steps](COMPANY-PACK-NEXT-STEPS.md)",
            "**Smoke:**",
            "[Validation Guide](VALIDATION.md)",
            "[Starter Walkthrough](STARTER-WALKTHROUGH.md)",
            "[Public Preview Self-check](PUBLIC-PREVIEW-SELF-CHECK.md)",
            "[Public starter smoke regression](../tests/test_public_starter_runbook_smoke.py)",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, section)

        self.assertLess(section.index("Ideal"), section.index("Current"))
        self.assertLess(section.index("Current"), section.index("Smoke"))

        for relative in (
            "../templates/company/README.md",
            "../templates/blocks/README.md",
            "../templates/records/README.md",
            "../templates/mocs/README.md",
            "COMPANY-PACK-CATALOG.md",
            "COMPANY-PACK-NEXT-STEPS.md",
            "VALIDATION.md",
            "STARTER-WALKTHROUGH.md",
            "PUBLIC-PREVIEW-SELF-CHECK.md",
            "../tests/test_public_starter_runbook_smoke.py",
        ):
            with self.subTest(relative=relative):
                self.assertTrue((MATRIX.parent / relative).is_file())

    def test_matrix_links_review_chain_artifact_map(self) -> None:
        surface = section(MATRIX.read_text(encoding="utf-8"), "read-next-ideal---current---smoke")
        assert_links(self, MATRIX, surface, ("STARTER-WALKTHROUGH.md#review-chain-artifact-map",))
        assert_preview_boundary(self, surface, ("Human Decision", "Promotion", "Current Truth", "Public Beta GO"))

    def test_matrix_exposes_ordered_contract_tool_test_runbook_path(self) -> None:
        text = MATRIX.read_text(encoding="utf-8")
        # Stable schema/CLI/test/runbook associations are checked in each actual row.
        inventory = (
            ("1-company-template", "company-manifest.schema.json", "validate_template_pack.py", "test_validate_template_pack.py", "../templates/company/README.md"),
            ("2-blocks", "block.schema.json", "validate_template_pack.py", "test_validate_template_pack.py", "../templates/blocks/README.md"),
            ("3-governed-records", "record.schema.json", "validate_template_pack.py", "test_validate_template_pack.py", "../templates/records/README.md"),
            ("4-mocs", "moc.schema.json", "validate_template_pack.py", "test_validate_template_pack.py", "../templates/mocs/README.md"),
            ("5-company-pack-catalog", "company-pack-catalog.schema.json", "catalog_company_pack.py", "test_catalog_company_pack.py", "COMPANY-PACK-CATALOG.md"),
            ("6-customization", "customization-report.schema.json", "check_company_pack_customization.py", "test_check_company_pack_customization.py", "CUSTOMIZATION-CHECKLIST.md"),
            ("7-public-preview-self-check", "company-pack-public-preview-check.schema.json", "check_company_pack_public_preview.py", "test_company_pack_public_preview_check.py", "PUBLIC-PREVIEW-SELF-CHECK.md"),
            ("8-company-pack-next-steps", "company-pack-next-steps.schema.json", "plan_company_pack_next_steps.py", "test_plan_company_pack_next_steps.py", "COMPANY-PACK-NEXT-STEPS.md"),
            ("9-review-bundle", "company-pack-review-bundle.schema.json", "build_company_pack_review_bundle.py", "test_build_company_pack_review_bundle.py", "REVIEW-BUNDLE.md"),
        )
        positions = []
        for anchor, schema, tool, test, runbook in inventory:
            with self.subTest(stage=anchor):
                surface = section(text, anchor)
                positions.append(text.index(surface))
                rows = table_rows(surface)
                self.assertEqual(rows[0], ["Schema", "Validator / CLI", "Regression test", "Runbook / PASSの意味"])
                self.assertEqual(len(rows), 2)
                row = rows[1]
                self.assertIn("../schemas/" + schema, link_targets(row[0]))
                self.assertIn("../tools/" + tool, link_targets(row[1]))
                self.assertIn("../tests/" + test, link_targets(row[2]))
                self.assertIn(runbook, link_targets(row[3]))
                assert_links(self, MATRIX, surface)
        self.assertEqual(positions, sorted(positions))
        assert_preview_boundary(self, text, ("Human approval", "runtime", "provider", "Voice / Discord", "Promotion", "Current Truth", "Public Beta GO"))
        # The matrix links to commands in its owned runbooks; verify both-shell coverage
        # for all first-nine-stage tools without duplicating their editorial headings.
        for language, prefix in (("powershell", "python"), ("bash", "python3")):
            commands = shell_commands(text, language)
            for tool in ("create_company_pack.py", "validate_template_pack.py", "catalog_company_pack.py",
                         "check_company_pack_customization.py", "check_company_pack_public_preview.py",
                         "plan_company_pack_next_steps.py", "build_company_pack_review_bundle.py", "verify_company_pack_review_bundle.py"):
                self.assertTrue(any(re.search(r"(?:^|=\s*)" + re.escape(f"{prefix} tools/{tool}") + r"(?:\s|$)", command) for command in commands), (language, tool))

    def test_matrix_runbook_smoke_links_back_to_catalog_entry(self) -> None:
        matrix = MATRIX.read_text(encoding="utf-8")
        start = matrix.index("## Runbook smoke")
        end = matrix.index("## 1. Company Template", start)
        smoke = matrix[start:end]
        for marker in (
            "[Company Pack Catalog](COMPANY-PACK-CATALOG.md)",
            "[`test_company_pack_catalog_runbook_smoke_entry.py`](../tests/test_company_pack_catalog_runbook_smoke_entry.py)",
            "CANDIDATE_FOR_GOVERNED_REVIEW",
            "MATCH",
            "CUSTOMIZATION_REQUIRED",
            "BUNDLE_REFUSED",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, smoke)

        for relative in (
            "COMPANY-PACK-CATALOG.md",
            "../tests/test_company_pack_catalog_runbook_smoke_entry.py",
        ):
            self.assertTrue((MATRIX.parent / relative).is_file())

    def test_matrix_runbook_smoke_names_complete_review_chain(self) -> None:
        matrix = MATRIX.read_text(encoding="utf-8")
        start = matrix.index("## Runbook smoke")
        end = matrix.index("## 1. Company Template", start)
        smoke = matrix[start:end]
        chain = (
            "initializer -> validator -> Catalog -> customization -> Public Preview -> "
            "Next Steps -> Review Bundle -> Review Request -> Review Response -> "
            "Review Decision Handoff -> verify"
        )
        self.assertIn(chain, smoke)
        for marker in (
            "Review Request",
            "Review Response",
            "Review Decision Handoff",
            "exact bytes",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
            "Human Decision",
            "Promotion",
            "Current Truth",
            "Public Beta GO",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, smoke)

        self.assertNotIn("Review Bundleの順に進み", smoke)
        self.assertNotIn("Review Bundle → verify", smoke)
        self.assertLess(smoke.index("Review Bundle"), smoke.index("Review Request"))
        self.assertLess(smoke.index("Review Request"), smoke.index("Review Response"))
        self.assertLess(
            smoke.index("Review Response"), smoke.index("Review Decision Handoff")
        )
        self.assertLess(
            smoke.index("Review Decision Handoff"), smoke.index("verify")
        )

    def test_matrix_exposes_the_complete_review_chain_contracts(self) -> None:
        text = MATRIX.read_text(encoding="utf-8")
        # The public CLI reference owns the shipped entrypoint inventory.
        reference = ROOT / "docs/COMPANY-PACK-CLI-REFERENCE.md"
        public_tools = {Path(target).name for target in link_targets(reference.read_text(encoding="utf-8")) if target.startswith("../tools/")}
        positions = [text.index(section(text, "9-review-bundle"))]
        for anchor, schemas, tools, test, runbook, state in (
                ("10-review-request", ("company-pack-review-request.schema.json",), ("build_company_pack_review_request.py",), "test_build_company_pack_review_request.py", "REVIEW-REQUEST.md", "PENDING_AUTHORIZED_REVIEW"),
                ("11-review-response", ("company-pack-review-response.schema.json", "company-pack-review-response-verification.schema.json"), ("build_company_pack_review_response.py", "verify_company_pack_review_response.py"), "test_company_pack_review_response.py", "REVIEW-RESPONSE.md", "ITEM_RESPONSES_MATCH_REQUEST"),
                ("12-review-decision-handoff", ("company-pack-review-decision-handoff.schema.json", "company-pack-review-decision-handoff-verification.schema.json"), ("build_company_pack_review_decision_handoff.py", "verify_company_pack_review_decision_handoff.py"), "test_company_pack_review_decision_handoff.py", "REVIEW-DECISION-HANDOFF.md", "DECISION_HANDOFF_MATCH")):
            with self.subTest(stage=anchor):
                surface = section(text, anchor)
                positions.append(text.index(surface))
                rows = table_rows(surface)
                self.assertEqual(len(rows), 2)
                self.assertEqual(len(rows[1]), 4)
                row = rows[1]
                self.assertEqual(set(link_targets(row[0])), {"../schemas/" + schema for schema in schemas})
                self.assertEqual(set(link_targets(row[1])), {"../tools/" + tool for tool in tools})
                self.assertEqual(link_targets(row[2]), ["../tests/" + test])
                self.assertIn(runbook, link_targets(row[3]))
                self.assertIn(state, row[3])
                assert_links(self, MATRIX, surface)
                for language, prefix in (("powershell", "python"), ("bash", "python3")):
                    actual = shell_commands(surface, language)
                    for tool in tools:
                        self.assertIn(tool, public_tools)
                        self.assertTrue(any(command.startswith(f"{prefix} tools/{tool}") for command in actual), (language, tool))
        self.assertEqual(positions, sorted(positions))
        handoff = section(text, "12-review-decision-handoff")
        self.assertIn("decision: null", handoff)
        self.assertIn("selected_outcome: null", handoff)
        assert_preview_boundary(self, text)

    def test_matrix_links_are_present_and_entry_surfaces_link_back(self) -> None:
        matrix = MATRIX.read_text(encoding="utf-8")
        links = re.findall(r"\]\(([^)]+)\)", matrix)
        local_links = [
            link.split("#", 1)[0]
            for link in links
            if not link.startswith(("http://", "https://", "mailto:", "#"))
        ]
        for link in local_links:
            with self.subTest(link=link):
                self.assertTrue((MATRIX.parent / link).exists(), link)

        for surface in (
            ROOT / "README.md",
            ROOT / "docs" / "TEMPLATE-GUIDE.md",
            ROOT / "docs" / "VALIDATION.md",
        ):
            with self.subTest(surface=surface):
                self.assertIn("SCHEMA-VALIDATOR-MATRIX.md", surface.read_text(encoding="utf-8"))
