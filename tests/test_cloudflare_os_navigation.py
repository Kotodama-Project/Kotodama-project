from __future__ import annotations

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class CloudflareOsNavigationTests(unittest.TestCase):
    def test_public_entrypoints_link_the_candidate(self) -> None:
        expected = {
            "README.md": "docs/CLOUDFLARE-OS-ADOPTION.md",
            "STATUS.md": "docs/CLOUDFLARE-OS-ADOPTION.md",
            "runtime/README.md": "cloudflare-os/README.md",
            "docs/SCHEMA-VALIDATOR-MATRIX.md": "cloudflare-os-upstream-pin.schema.json",
            "runtime/cloudflare-os/README.md": "local-runtime-evaluation.json",
            "docs/CLOUDFLARE-OS-LOCAL-RUNTIME-EVALUATION.md": "1060",
        }
        for relative, marker in expected.items():
            with self.subTest(relative=relative):
                text = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn(marker, text)
                self.assertIn("NO_GO_UNPUBLISHED", text)

    def test_adoption_doc_separates_all_authority_planes(self) -> None:
        text = (ROOT / "docs" / "CLOUDFLARE-OS-ADOPTION.md").read_text(encoding="utf-8")
        for marker in (
            "Cloudflare edge",
            "Official Cloudflare OS",
            "Proxmox",
            "BecomeOne / Human Intent",
            "Context Gateway",
            "Workers Paid",
            "1060",
            "independent review",
            "NO_GO_UNPUBLISHED",
        ):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
