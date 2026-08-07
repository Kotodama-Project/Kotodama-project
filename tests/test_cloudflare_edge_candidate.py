from __future__ import annotations

import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "validate_cloudflare_edge_candidate.py"
SPEC = importlib.util.spec_from_file_location("cloudflare_edge_validator", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class CloudflareEdgeCandidateTests(unittest.TestCase):
    def test_candidate_is_fail_closed_and_non_production(self) -> None:
        self.assertEqual([], MODULE.validate())

    def test_only_manual_preview_upload_is_declared(self) -> None:
        workflow = MODULE.WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("versions upload --env preview", workflow)
        self.assertNotIn("wrangler deploy", workflow)
        self.assertNotIn("versions deploy", workflow)


if __name__ == "__main__":
    unittest.main()
