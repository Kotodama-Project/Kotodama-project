from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_template_catalog_explains_layer_order_and_current_preview_boundary() -> None:
    catalog = (ROOT / "templates" / "README.md").read_text(encoding="utf-8")
    flat = " ".join(catalog.split())

    assert "## 使う順番" in catalog
    assert "Company Template" in catalog
    assert "Blocks" in catalog
    assert "Governed Records" in catalog
    assert "MOCs" in catalog
    assert "runtime profile" in catalog
    assert "理想" in catalog
    assert "現在" in catalog
    assert "read-only/candidate-only" in flat
    assert "navigation-only" in flat
    assert "Public Beta GO" in flat
    assert "../docs/COMPANY-PACK-CATALOG.md" in catalog
    assert "../docs/TEMPLATE-GUIDE.md" in catalog
    assert "../docs/STARTER-WALKTHROUGH.md" in catalog
    assert "../docs/PUBLIC-PREVIEW-SELF-CHECK.md" in catalog
    assert "../examples/company-starter/README.md" in catalog

    for link in (
        "../docs/COMPANY-PACK-CATALOG.md",
        "../docs/TEMPLATE-GUIDE.md",
        "../docs/STARTER-WALKTHROUGH.md",
        "../docs/PUBLIC-PREVIEW-SELF-CHECK.md",
        "../examples/company-starter/README.md",
    ):
        assert (ROOT / "templates" / link).exists()
