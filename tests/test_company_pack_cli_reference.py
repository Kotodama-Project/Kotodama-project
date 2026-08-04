from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOUNDARY = "Boundary: read-only/candidate-only; Public Beta remains NO_GO_UNPUBLISHED."
TOOLS = (
    "create_company_pack.py",
    "validate_template_pack.py",
    "catalog_company_pack.py",
    "check_company_pack_customization.py",
    "check_company_pack_public_preview.py",
    "plan_company_pack_next_steps.py",
    "build_company_pack_review_bundle.py",
    "verify_company_pack_review_bundle.py",
    "build_company_pack_review_request.py",
    "build_company_pack_review_response.py",
    "verify_company_pack_review_response.py",
    "build_company_pack_review_decision_handoff.py",
    "verify_company_pack_review_decision_handoff.py",
    "smoke_company_pack_review_chain.py",
)
GROUPS = (
    "Create",
    "Inspect",
    "Plan",
    "Bind",
    "Request",
    "Respond",
    "Handoff",
    "Smoke",
)


class CompanyPackCliReferenceTests(unittest.TestCase):
    def test_every_entrypoint_has_side_effect_free_boundary_help(self) -> None:
        for tool in TOOLS:
            for flag in ("-h", "--help"):
                with self.subTest(tool=tool, flag=flag), tempfile.TemporaryDirectory() as tmp:
                    workdir = Path(tmp)
                    before = tuple(workdir.iterdir())
                    result = subprocess.run(
                        [sys.executable, str(ROOT / "tools" / tool), flag],
                        cwd=workdir,
                        text=True,
                        encoding="utf-8",
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stderr, "")
                    self.assertIn(BOUNDARY, result.stdout)
                    self.assertEqual(tuple(workdir.iterdir()), before)

    def test_reference_indexes_exactly_the_public_entrypoints(self) -> None:
        reference = (ROOT / "docs" / "COMPANY-PACK-CLI-REFERENCE.md").read_text(
            encoding="utf-8"
        )
        for group in GROUPS:
            self.assertIn(f"## {group}", reference)
        for tool in TOOLS:
            link = f"[`{tool}`](../tools/{tool})"
            self.assertEqual(reference.count(link), 1, tool)
            self.assertIn(f"python tools/{tool} --help", reference)
            self.assertIn(f"python3 tools/{tool} --help", reference)
        linked_tools = reference.count("](../tools/")
        self.assertEqual(linked_tools, len(TOOLS))
        self.assertIn("initializer is the only command", reference)
        self.assertIn("does not create Human approval", reference)
        self.assertIn("NO_GO_UNPUBLISHED", reference)
        self.assertIn(
            "`CUSTOMIZATION_REQUIRED` / `READY_FOR_GOVERNED_REVIEW` / `INVALID_PACK`",
            reference,
        )
        self.assertIn("`STATIC_CUSTOMIZATION` / `CANDIDATE_BINDING`", reference)

    def test_readme_links_reference_from_quick_start_and_document_map(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        link = "[Company Pack CLI Reference](docs/COMPANY-PACK-CLI-REFERENCE.md)"
        quick_start = readme.index("## Quick Start")
        document_map = readme.index("## Document Map")
        self.assertIn(link, readme[quick_start:document_map])
        self.assertIn(link, readme[document_map:])


if __name__ == "__main__":
    unittest.main()
