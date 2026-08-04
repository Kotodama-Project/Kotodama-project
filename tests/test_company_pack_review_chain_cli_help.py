from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "docs" / "REVIEW-WORKFLOW.md"

REVIEW_CHAIN_COMMANDS = (
    (
        "build_company_pack_review_bundle.py",
        "usage: build_company_pack_review_bundle.py PACK_DIRECTORY",
        "Bind a review-ready Company Pack to exact bytes without approving it.",
    ),
    (
        "verify_company_pack_review_bundle.py",
        "usage: verify_company_pack_review_bundle.py BUNDLE_JSON PACK_DIRECTORY",
        "Verify saved Company Pack bindings without approving or promoting them.",
    ),
    (
        "build_company_pack_review_request.py",
        "usage: build_company_pack_review_request.py BUNDLE_JSON PACK_DIRECTORY",
        "Prepare an exact, non-authorizing Company Pack review request.",
    ),
    (
        "build_company_pack_review_response.py",
        "usage: build_company_pack_review_response.py REQUEST_JSON",
        "Create an editable, non-authorizing response for one saved review request.",
    ),
    (
        "verify_company_pack_review_response.py",
        "usage: verify_company_pack_review_response.py REQUEST_JSON RESPONSE_JSON",
        "Verify item-response structure without verifying reviewer authority or approval.",
    ),
    (
        "build_company_pack_review_decision_handoff.py",
        "usage: build_company_pack_review_decision_handoff.py BUNDLE_JSON PACK_DIRECTORY BUNDLE_VERIFICATION_JSON REQUEST_JSON RESPONSE_JSON RESPONSE_VERIFICATION_JSON",
        "Bind a complete review chain for a separate Human Decision step.",
    ),
    (
        "verify_company_pack_review_decision_handoff.py",
        "usage: verify_company_pack_review_decision_handoff.py BUNDLE_JSON PACK_DIRECTORY BUNDLE_VERIFICATION_JSON REQUEST_JSON RESPONSE_JSON RESPONSE_VERIFICATION_JSON HANDOFF_JSON",
        "Verify a review-to-Decision handoff without verifying a Human Decision.",
    ),
)


class CompanyPackReviewChainCliHelpTests(unittest.TestCase):
    def run_tool(self, tool: str, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ROOT / "tools" / tool), *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

    def test_short_and_long_help_are_external_free_successes(self) -> None:
        for tool, usage, purpose in REVIEW_CHAIN_COMMANDS:
            for flag in ("-h", "--help"):
                with self.subTest(tool=tool, flag=flag), tempfile.TemporaryDirectory() as tmp:
                    work = Path(tmp)
                    before = tuple(work.iterdir())
                    result = self.run_tool(tool, flag, cwd=work)

                    self.assertEqual(result.returncode, 0, result)
                    self.assertEqual(result.stderr, "")
                    self.assertIn(usage, result.stdout)
                    self.assertIn(purpose, result.stdout)
                    self.assertIn("read-only/candidate-only", result.stdout)
                    self.assertIn("NO_GO_UNPUBLISHED", result.stdout)
                    self.assertEqual(before, tuple(work.iterdir()))

    def test_malformed_invocation_stays_usage_only_and_non_reflective(self) -> None:
        opaque = "opaque-review-input-that-must-not-be-reflected"
        invalid_args = ("--unknown-option", opaque, *["extra" for _ in range(8)])
        for tool, usage, _purpose in REVIEW_CHAIN_COMMANDS:
            with self.subTest(tool=tool), tempfile.TemporaryDirectory() as tmp:
                result = self.run_tool(tool, *invalid_args, cwd=Path(tmp))
                combined = result.stdout + result.stderr

                self.assertEqual(result.returncode, 2)
                self.assertIn(usage, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertNotIn("--unknown-option", combined)
                self.assertNotIn(opaque, combined)

    def test_review_workflow_exposes_cross_shell_help_preflight(self) -> None:
        document = WORKFLOW.read_text(encoding="utf-8")
        start = document.index("## CLI help preflight")
        end = document.index("## 1.", start)
        section = document[start:end]

        for prefix in ("python", "python3"):
            for tool, _usage, _purpose in REVIEW_CHAIN_COMMANDS:
                with self.subTest(prefix=prefix, tool=tool):
                    self.assertIn(f"{prefix} tools/{tool} --help", section)

        for marker in (
            "artifactやPackを読み書きしません",
            "read-only/candidate-only",
            "NO_GO_UNPUBLISHED",
            "Human approval",
            "Final Human GO",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, section)


if __name__ == "__main__":
    unittest.main()
