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
