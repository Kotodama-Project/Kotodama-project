import json
import re
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MocsEntryNavigationTests(unittest.TestCase):
    def test_mocs_catalog_exposes_ideal_current_smoke_first_stop(self) -> None:
        text = (ROOT / "templates" / "mocs" / "README.md").read_text(encoding="utf-8")
        flat = " ".join(text.split())

        for marker in (
            "## Read next: ideal -> current -> smoke",
            "**Ideal:**",
            "../company/README.md",
            "../blocks/README.md",
            "../records/README.md",
            "**Current:**",
            "../../docs/COMPANY-PACK-CATALOG.md",
            "[Company Pack Guided Next Steps](../../docs/COMPANY-PACK-NEXT-STEPS.md)",
            "**Smoke:**",
            "../../docs/STARTER-WALKTHROUGH.md",
            "../../tests/test_mocs_entry_navigation.py",
            "navigation-only",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, flat)

        self.assertLess(
            text.index("## Read next: ideal -> current -> smoke"),
            text.index("## Current shipped MOCs"),
        )

    def test_moc_smoke_commands_are_standard_library_and_cross_shell(self) -> None:
        text = (ROOT / "templates" / "mocs" / "README.md").read_text(encoding="utf-8")
        flat = " ".join(text.split())

        for marker in (
            "追加依存なし",
            "python -m unittest tests.test_mocs_entry_navigation -v",
            "python3 -m unittest tests.test_mocs_entry_navigation -v",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, flat)

        self.assertNotIn("python -m pytest tests.test_mocs_entry_navigation -q", text)

    def test_shipped_moc_links_bind_to_json_starters(self) -> None:
        index = (ROOT / "templates" / "mocs" / "README.md").read_text(
            encoding="utf-8"
        )
        shipped = (
            ("Company Operations MOC", "company-operations-moc.md", "company-operations.json"),
            ("Public Release Review MOC", "public-release-moc.md", "public-release.json"),
            ("Incident / Recovery MOC", "incident-recovery-moc.md", "incident-recovery.json"),
        )
        for label, markdown_name, json_name in shipped:
            with self.subTest(label=label):
                self.assertIn(f"[{label}]({markdown_name})", index)
                self.assertIn(
                    f"[{json_name}]" \
                    f"(../../examples/company-starter/mocs/{json_name})",
                    index,
                )

                markdown_path = ROOT / "templates" / "mocs" / markdown_name
                json_path = ROOT / "examples" / "company-starter" / "mocs" / json_name
                self.assertTrue(markdown_path.is_file())
                self.assertTrue(json_path.is_file())

                markdown = markdown_path.read_text(encoding="utf-8")
                self.assertEqual(
                    re.search(r"^authority:\s*(\S+)$", markdown, re.MULTILINE).group(1),
                    "navigation_only",
                )
                self.assertEqual(
                    re.search(r"^status:\s*(\S+)$", markdown, re.MULTILINE).group(1),
                    "example",
                )

                starter = json.loads(json_path.read_text(encoding="utf-8"))
                self.assertEqual(starter["authority"], "navigation_only")
                self.assertEqual(starter["status"], "example")
                self.assertEqual(starter["kind"], "moc")


if __name__ == "__main__":
    unittest.main()
