from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import importlib
from unittest import mock
import io
from contextlib import chdir, redirect_stdout, redirect_stderr
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

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
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            before = tuple(work.iterdir())
            for tool, usage, purpose in REVIEW_CHAIN_COMMANDS:
                module = importlib.import_module(tool.removesuffix(".py"))
                direct_outputs = []
                for flag in ("-h", "--help"):
                    with self.subTest(tool=tool, flag=flag):
                        stdout, stderr = io.StringIO(), io.StringIO()
                        with (
                            chdir(work), redirect_stdout(stdout), redirect_stderr(stderr),
                            mock.patch.object(sys, "argv", [tool, flag]),
                            mock.patch.object(subprocess, "run", side_effect=AssertionError("help must not start child work")),
                            mock.patch.object(subprocess, "Popen", side_effect=AssertionError("help must not start child work")),
                            mock.patch("socket.socket", side_effect=AssertionError("help must not open a socket")),
                            mock.patch("socket.create_connection", side_effect=AssertionError("help must not connect externally")),
                            mock.patch("socket.getaddrinfo", side_effect=AssertionError("help must not resolve external hosts")),
                        ):
                            code = module.main([tool, flag])
                        direct_outputs.append(stdout.getvalue())
                        self.assertEqual(code, 0)
                        self.assertEqual(stderr.getvalue(), "")
                        self.assertIn(usage, stdout.getvalue())
                        self.assertIn(purpose, stdout.getvalue())
                        self.assertIn("read-only/candidate-only", stdout.getvalue())
                        self.assertIn("NO_GO_UNPUBLISHED", stdout.getvalue())
                        self.assertEqual(before, tuple(work.iterdir()))
                self.assertEqual(len(direct_outputs), 2, "both help aliases must complete")
                self.assertEqual(direct_outputs[0], direct_outputs[1])
                cold = self.run_tool(tool, "--help", cwd=work)
                self.assertEqual(cold.returncode, 0)
                self.assertEqual(cold.stderr, "")
                self.assertEqual(cold.stdout, direct_outputs[1])
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
