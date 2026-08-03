import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class InstallationLifecycleDocumentationTests(unittest.TestCase):
    def test_first_read_order_and_profile_selection_are_explicit(self) -> None:
        document = (ROOT / "docs" / "INSTALLATION-LIFECYCLE.md").read_text(
            encoding="utf-8"
        )

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


if __name__ == "__main__":
    unittest.main()
