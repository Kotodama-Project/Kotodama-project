import re
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE = ROOT / "docs" / "INSTALLATION-LIFECYCLE.md"


class InstallationLifecycleDocumentationTests(unittest.TestCase):
    def test_standalone_entry_exposes_layer_then_profile_reading_path(self) -> None:
        document = LIFECYCLE.read_text(encoding="utf-8")

        entry = document.index("## 0. 読み始める場所")
        profile_table = document.index("## 理想の導入ライフサイクルと現在の公開candidate")
        self.assertLess(entry, profile_table)
        section = document[entry:profile_table]
        required = (
            "[Template Guide](TEMPLATE-GUIDE.md)",
            "[Company Template](../templates/company/README.md)",
            "[Blocks](../templates/blocks/README.md)",
            "[Governed Records](../templates/records/README.md)",
            "[MOCs](../templates/mocs/README.md)",
            "[Company Pack Catalog](COMPANY-PACK-CATALOG.md)",
            "[Starter Walkthrough](STARTER-WALKTHROUGH.md)",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, section)

        positions = [section.index(marker) for marker in required[:7]]
        self.assertEqual(positions, sorted(positions))
        for relative_path in (
            "TEMPLATE-GUIDE.md",
            "../templates/company/README.md",
            "../templates/blocks/README.md",
            "../templates/records/README.md",
            "../templates/mocs/README.md",
            "COMPANY-PACK-CATALOG.md",
            "STARTER-WALKTHROUGH.md",
        ):
            with self.subTest(relative_path=relative_path):
                self.assertTrue((LIFECYCLE.parent / relative_path).is_file())

    def test_first_read_order_and_profile_selection_are_explicit(self) -> None:
        document = LIFECYCLE.read_text(encoding="utf-8")

        self.assertIn("## 最初に選ぶ", document)
        self.assertRegex(
            document,
            re.compile(r"`compose_minimum`.*?1台の管理対象host", re.DOTALL),
        )
        self.assertRegex(
            document,
            re.compile(r"`proxmox_segmented`.*?既存のProxmox", re.DOTALL),
        )
        self.assertIn("COMPANY-PACK-CATALOG.md", document)
        self.assertIn("STARTER-WALKTHROUGH.md", document)
        self.assertIn("read-only", document)
        self.assertIn("NO_GO_UNPUBLISHED", document)
        self.assertIn("Public Beta GO", document)

    def test_docs_separate_ideal_lifecycle_from_current_public_candidate(self) -> None:
        document = LIFECYCLE.read_text(encoding="utf-8")

        ideal_marker = "## 理想の導入ライフサイクルと現在の公開candidate"
        current_marker = "### 現在の公開candidate"
        boundary_marker = "validatorの`PASS`やrunbookの存在は"
        for marker in (ideal_marker, current_marker, boundary_marker, "NO_GO_UNPUBLISHED"):
            with self.subTest(marker=marker):
                self.assertIn(marker, document)

        ideal_start = document.index(ideal_marker)
        current_start = document.index(current_marker, ideal_start)
        boundary_start = document.index(boundary_marker, current_start)
        self.assertLess(ideal_start, current_start)
        self.assertLess(current_start, boundary_start)

        ideal = document[ideal_start:current_start]
        current = document[current_start:boundary_start]
        self.assertIn("preflight", ideal)
        self.assertIn("restore_rehearsal", ideal)
        self.assertIn("sanitized", current)
        self.assertIn("target-bound runtime receipt", current)

    def test_documented_commands_and_links_bind_to_shipped_files(self) -> None:
        document = LIFECYCLE.read_text(encoding="utf-8")
        compose_runbook = ROOT / "docs" / "COMPOSE-MINIMUM-RUNBOOK.md"
        proxmox_runbook = ROOT / "docs" / "PROXMOX-SEGMENTED-RUNBOOK.md"

        for path in (
            ROOT / "tools" / "validate_installation_lifecycle.py",
            ROOT / "tools" / "validate_compose_minimum_skeleton.py",
            ROOT / "tools" / "resolve_compose_candidate.py",
            ROOT / "tools" / "validate_resolved_compose_candidate.py",
            ROOT / "tools" / "preflight_compose_image_availability.py",
            ROOT / "tools" / "verify_compose_image_availability_preflight.py",
            ROOT / "examples" / "installation-lifecycle" / "compose-minimum.json",
            ROOT / "examples" / "installation-lifecycle" / "proxmox-segmented.json",
            compose_runbook,
            proxmox_runbook,
        ):
            with self.subTest(path=path):
                self.assertTrue(path.is_file(), path)

        self.assertIn(
            "python tools\\validate_installation_lifecycle.py examples\\installation-lifecycle\\compose-minimum.json",
            document,
        )
        self.assertIn(
            "python3 tools/validate_installation_lifecycle.py examples/installation-lifecycle/compose-minimum.json",
            document,
        )
        self.assertIn(
            "python tools\\validate_installation_lifecycle.py examples\\installation-lifecycle\\proxmox-segmented.json",
            document,
        )
        self.assertIn(
            "python3 tools/validate_installation_lifecycle.py examples/installation-lifecycle/proxmox-segmented.json",
            document,
        )
        compose_text = compose_runbook.read_text(encoding="utf-8")
        for marker in (
            "tools\\resolve_compose_candidate.py",
            "tools\\validate_resolved_compose_candidate.py",
            "tools\\preflight_compose_image_availability.py",
            "tools\\verify_compose_image_availability_preflight.py",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, compose_text)
        self.assertIn("tools\\validate_installation_lifecycle.py", proxmox_runbook.read_text(encoding="utf-8"))

    def test_runbooks_separate_ideal_current_and_offer_posix_command_parity(self) -> None:
        compose_runbook = (ROOT / "docs" / "COMPOSE-MINIMUM-RUNBOOK.md").read_text(encoding="utf-8")
        proxmox_runbook = (ROOT / "docs" / "PROXMOX-SEGMENTED-RUNBOOK.md").read_text(encoding="utf-8")

        for name, runbook in (("compose", compose_runbook), ("proxmox", proxmox_runbook)):
            with self.subTest(runbook=name):
                ideal_marker = "### 理想の導入ライフサイクル"
                current_marker = "### 現在の公開candidate"
                ideal_start = runbook.index(ideal_marker)
                current_start = runbook.index(current_marker, ideal_start)
                self.assertLess(ideal_start, current_start)
                ideal = runbook[ideal_start:current_start]
                current = runbook[current_start:]
                self.assertIn("preflight", ideal)
                self.assertIn("restore_rehearsal", ideal)
                for marker in (
                    "local / synthetic",
                    "target-bound receipt",
                    "provider connection",
                    "NO_GO_UNPUBLISHED",
                ):
                    self.assertIn(marker, current)

        self.assertIn(
            "python3 tools/validate_installation_lifecycle.py examples/installation-lifecycle/compose-minimum.json",
            compose_runbook,
        )
        self.assertIn(
            "python3 tools/validate_compose_minimum_skeleton.py runtime/compose-minimum",
            compose_runbook,
        )
        self.assertIn(
            "python3 tools/validate_installation_lifecycle.py examples/installation-lifecycle/proxmox-segmented.json",
            proxmox_runbook,
        )

    def test_validation_guide_separates_ideal_current_and_offers_posix_parity(self) -> None:
        validation = (ROOT / "docs" / "VALIDATION.md").read_text(encoding="utf-8")
        ideal_marker = "## 理想と現在の公開candidate"
        current_marker = "### 現在の公開candidate"
        ideal_start = validation.index(ideal_marker)
        current_start = validation.index(current_marker, ideal_start)
        self.assertLess(ideal_start, current_start)
        ideal = validation[ideal_start:current_start]
        current = validation[current_start:]
        for marker in ("schema", "cross-file", "negative", "review"):
            self.assertIn(marker, ideal)
        for marker in ("local / synthetic", "runtime", "provider", "Voice / Discord", "NO_GO_UNPUBLISHED"):
            self.assertIn(marker, current)

        for command in (
            "python tools\\validate_installation_lifecycle.py examples\\installation-lifecycle\\compose-minimum.json",
            "python tools\\validate_installation_lifecycle.py examples\\installation-lifecycle\\proxmox-segmented.json",
            "python3 tools/validate_installation_lifecycle.py examples/installation-lifecycle/compose-minimum.json",
            "python3 tools/validate_installation_lifecycle.py examples/installation-lifecycle/proxmox-segmented.json",
        ):
            with self.subTest(command=command):
                self.assertIn(command, validation)

    def test_validation_guide_core_public_paths_have_posix_parity(self) -> None:
        validation = (ROOT / "docs" / "VALIDATION.md").read_text(encoding="utf-8")

        command_pairs = (
            (
                "python tools/create_company_pack.py my-company work/my-company",
                "python3 tools/create_company_pack.py my-company work/my-company",
            ),
            (
                "python tools/check_company_pack_customization.py work/my-company",
                "python3 tools/check_company_pack_customization.py work/my-company",
            ),
            (
                "python tools/build_company_pack_review_bundle.py work/my-company",
                "python3 tools/build_company_pack_review_bundle.py work/my-company",
            ),
            (
                "python tools/verify_company_pack_review_bundle.py work/my-company-review-bundle.json work/my-company",
                "python3 tools/verify_company_pack_review_bundle.py work/my-company-review-bundle.json work/my-company",
            ),
            (
                "python tools\\build_company_pack_review_response.py work\\my-company-review-request.json",
                "python3 tools/build_company_pack_review_response.py work/my-company-review-request.json",
            ),
            (
                "python tools\\verify_company_pack_review_response.py work\\my-company-review-request.json work\\my-company-review-response.json",
                "python3 tools/verify_company_pack_review_response.py work/my-company-review-request.json work/my-company-review-response.json",
            ),
            (
                "python tools\\validate_compose_minimum_skeleton.py runtime\\compose-minimum",
                "python3 tools/validate_compose_minimum_skeleton.py runtime/compose-minimum",
            ),
            (
                "python tools\\resolve_compose_candidate.py <bounded-project-name> --output work\\resolved-compose-candidate.json",
                "python3 tools/resolve_compose_candidate.py <bounded-project-name> --output work/resolved-compose-candidate.json",
            ),
            (
                "python tools\\validate_resolved_compose_candidate.py work\\resolved-compose-candidate.json",
                "python3 tools/validate_resolved_compose_candidate.py work/resolved-compose-candidate.json",
            ),
            (
                "python tools\\preflight_compose_image_availability.py work\\resolved-compose-candidate.json --output work\\compose-image-availability.json",
                "python3 tools/preflight_compose_image_availability.py work/resolved-compose-candidate.json --output work/compose-image-availability.json",
            ),
            (
                "python tools\\verify_compose_image_availability_preflight.py work\\compose-image-availability.json work\\resolved-compose-candidate.json",
                "python3 tools/verify_compose_image_availability_preflight.py work/compose-image-availability.json work/resolved-compose-candidate.json",
            ),
            (
                "python tools\\verify_compose_clean_install_migration_evidence_candidate.py work\\private-evidence-candidate.json work\\resolved-compose-candidate.json work\\compose-image-availability.json",
                "python3 tools/verify_compose_clean_install_migration_evidence_candidate.py work/private-evidence-candidate.json work/resolved-compose-candidate.json work/compose-image-availability.json",
            ),
        )
        for powershell_command, posix_command in command_pairs:
            with self.subTest(powershell_command=powershell_command):
                self.assertIn(powershell_command, validation)
                self.assertIn(posix_command, validation)

        self.assertIn("POSIX shell", validation)
        self.assertIn("private Source Binding", validation)
        self.assertIn("NO_GO_UNPUBLISHED", validation)

        ordered_markers = (
            "python3 tools/create_company_pack.py my-company work/my-company",
            "python3 tools/check_company_pack_customization.py work/my-company",
            "python3 tools/build_company_pack_review_bundle.py work/my-company",
            "python3 tools/verify_company_pack_review_bundle.py work/my-company-review-bundle.json work/my-company",
            "python3 tools/validate_compose_minimum_skeleton.py runtime/compose-minimum",
            "python3 tools/resolve_compose_candidate.py <bounded-project-name> --output work/resolved-compose-candidate.json",
            "python3 tools/validate_resolved_compose_candidate.py work/resolved-compose-candidate.json",
            "python3 tools/preflight_compose_image_availability.py work/resolved-compose-candidate.json --output work/compose-image-availability.json",
            "python3 tools/verify_compose_image_availability_preflight.py work/compose-image-availability.json work/resolved-compose-candidate.json",
        )
        positions = [validation.index(marker) for marker in ordered_markers]
        self.assertEqual(positions, sorted(positions))


if __name__ == "__main__":
    unittest.main()
