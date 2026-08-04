import re
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE = ROOT / "docs" / "INSTALLATION-LIFECYCLE.md"


class InstallationLifecycleDocumentationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
