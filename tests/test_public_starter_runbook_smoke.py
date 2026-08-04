from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs" / "SCHEMA-VALIDATOR-MATRIX.md"


class PublicStarterRunbookSmokeTests(unittest.TestCase):
    def run_tool(self, tool: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ROOT / "tools" / tool), *arguments],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

    def json_output(self, result: subprocess.CompletedProcess[str]) -> dict[str, object]:
        self.assertTrue(result.stdout.strip(), result.stderr)
        value = json.loads(result.stdout)
        self.assertIsInstance(value, dict)
        return value

    def test_public_docs_expose_full_review_chain_smoke(self) -> None:
        surfaces = {
            "README.md": (ROOT / "README.md").read_text(encoding="utf-8"),
            "docs/STARTER-WALKTHROUGH.md": (
                ROOT / "docs" / "STARTER-WALKTHROUGH.md"
            ).read_text(encoding="utf-8"),
            "docs/SCHEMA-VALIDATOR-MATRIX.md": MATRIX.read_text(encoding="utf-8"),
            "docs/COMPANY-PACK-NEXT-STEPS.md": (
                ROOT / "docs" / "COMPANY-PACK-NEXT-STEPS.md"
            ).read_text(encoding="utf-8"),
        }
        expected = {
            "README.md": (
                "test_public_starter_runbook_smoke.py",
                "Review Request",
                "Review Response",
                "Decision Handoff",
                "NO_GO_UNPUBLISHED",
            ),
            "docs/STARTER-WALKTHROUGH.md": (
                "test_public_starter_runbook_smoke.py",
                "Review Request",
                "Review Response",
                "Decision Handoff",
                "NO_GO_UNPUBLISHED",
            ),
            "docs/SCHEMA-VALIDATOR-MATRIX.md": (
                "## Full review-chain smoke",
                "test_public_starter_runbook_smoke.py",
                "Review Request",
                "Review Response",
                "Review Decision Handoff",
                "NO_GO_UNPUBLISHED",
            ),
            "docs/COMPANY-PACK-NEXT-STEPS.md": (
                "full review-chain smoke",
                "test_public_starter_runbook_smoke.py",
                "Review Request",
                "Review Response",
                "Decision Handoff",
                "NO_GO_UNPUBLISHED",
            ),
        }
        for path, markers in expected.items():
            with self.subTest(path=path):
                flattened = " ".join(surfaces[path].split())
                for marker in markers:
                    with self.subTest(marker=marker):
                        self.assertIn(marker, flattened)

    def test_matrix_links_the_executable_smoke_and_expected_bundle_boundaries(self) -> None:
        matrix = MATRIX.read_text(encoding="utf-8")
        for marker in (
            "## Runbook smoke",
            "test_public_starter_runbook_smoke.py",
            "CUSTOMIZATION_REQUIRED",
            "CANDIDATE_FOR_GOVERNED_REVIEW",
            "MATCH",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, matrix)

    def test_guided_starter_chain_reaches_bundle_match_in_a_temporary_pack(self) -> None:
        expires_at = (
            datetime.now(timezone.utc) + timedelta(days=1)
        ).isoformat().replace("+00:00", "Z")

        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "work"
            parent.mkdir()
            target = parent / "guided-company"
            bundle_path = parent / "guided-company-review-bundle.json"

            created = self.json_output(
                self.run_tool(
                    "create_company_pack.py",
                    "guided-company",
                    str(target),
                    "--human-intent-ref",
                    "human-intent:governed-alpha-v1",
                    "--authority-expires-at",
                    expires_at,
                    "--retention-policy-ref",
                    "retention-policy:governed-v1",
                )
            )
            self.assertEqual(created["status"], "PASS")
            self.assertEqual(created["validated_files"], 22)
            self.assertEqual(created["draft_documents"], 22)
            self.assertEqual(created["static_customizations_applied"], 19)
            self.assertEqual(created["customization_status"], "READY_FOR_GOVERNED_REVIEW")
            self.assertEqual(created["public_beta"], "NO_GO_UNPUBLISHED")
            self.assertFalse(any(created["claims"].values()))  # type: ignore[union-attr]

            validated = self.json_output(
                self.run_tool("validate_template_pack.py", str(target))
            )
            self.assertEqual(validated["status"], "PASS")
            self.assertEqual(validated["validated_files"], 22)

            catalog = self.run_tool(
                "catalog_company_pack.py", str(target), "--format", "markdown"
            )
            self.assertEqual(catalog.returncode, 0, catalog.stderr)
            self.assertIn("# Company Pack Catalog", catalog.stdout)
            self.assertIn("Public Beta: NO_GO_UNPUBLISHED", catalog.stdout)

            customization = self.json_output(
                self.run_tool("check_company_pack_customization.py", str(target))
            )
            self.assertEqual(customization["status"], "READY_FOR_GOVERNED_REVIEW")
            self.assertEqual(
                customization["counts"],
                {
                    "replacement_required": 0,
                    "review_required": 46,
                    "evidence_required": 5,
                },
            )
            self.assertFalse(any(customization["claims"].values()))  # type: ignore[union-attr]

            preview = self.run_tool(
                "check_company_pack_public_preview.py",
                str(target),
                "--format",
                "markdown",
            )
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertIn("Status: `PASS`", preview.stdout)
            self.assertIn("Public Beta: `NO_GO_UNPUBLISHED`", preview.stdout)

            next_steps = self.run_tool(
                "plan_company_pack_next_steps.py",
                str(target),
                "--format",
                "markdown",
            )
            self.assertEqual(next_steps.returncode, 0, next_steps.stderr)
            self.assertIn("# Company Pack Next Steps", next_steps.stdout)
            self.assertIn("NO_GO_UNPUBLISHED", next_steps.stdout)

            bundle_result = self.run_tool(
                "build_company_pack_review_bundle.py", str(target)
            )
            self.assertEqual(bundle_result.returncode, 0, bundle_result.stderr)
            bundle = self.json_output(bundle_result)
            self.assertEqual(bundle["status"], "CANDIDATE_FOR_GOVERNED_REVIEW")
            self.assertEqual(bundle["binding_count"], 22)
            self.assertEqual(bundle["public_beta"], "NO_GO_UNPUBLISHED")
            self.assertFalse(any(bundle["claims"].values()))  # type: ignore[union-attr]
            bundle_path.write_text(bundle_result.stdout, encoding="utf-8")

            verified = self.json_output(
                self.run_tool(
                    "verify_company_pack_review_bundle.py",
                    str(bundle_path),
                    str(target),
                )
            )
            self.assertEqual(verified["status"], "MATCH")
            self.assertEqual(verified["reason"], None)
            self.assertEqual(verified["binding_count"], 22)
            self.assertEqual(verified["matched_bindings"], 22)
            self.assertEqual(verified["mismatched_paths"], [])
            self.assertFalse(any(verified["claims"].values()))  # type: ignore[union-attr]
            self.assertEqual(verified["public_beta"], "NO_GO_UNPUBLISHED")

            bundle_verification_path = parent / "guided-company-review-bundle-verification.json"
            bundle_verification_path.write_text(
                json.dumps(verified, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            request_path = parent / "guided-company-review-request.json"
            request_result = self.run_tool(
                "build_company_pack_review_request.py",
                str(bundle_path),
                str(target),
            )
            self.assertEqual(request_result.returncode, 0, request_result.stderr)
            request = self.json_output(request_result)
            request_path.write_bytes(request_result.stdout.encode("utf-8"))
            self.assertEqual(request["status"], "CANDIDATE_REVIEW_REQUEST")
            self.assertEqual(
                request["review_request"]["state"], "PENDING_AUTHORIZED_REVIEW"
            )
            self.assertIsNone(request["review_request"]["selected_outcome"])
            self.assertFalse(any(request["claims"].values()))
            self.assertEqual(request["public_beta"], "NO_GO_UNPUBLISHED")

            response_result = self.run_tool(
                "build_company_pack_review_response.py", str(request_path)
            )
            self.assertEqual(response_result.returncode, 0, response_result.stderr)
            response = self.json_output(response_result)
            for item in response["review_response"]["items"]:
                item["outcome"] = "accept"
            response_path = parent / "guided-company-review-response.json"
            response_path.write_text(
                json.dumps(response, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(response["status"], "REVIEW_RESPONSE_CANDIDATE")
            self.assertEqual(
                response["review_response"]["item_count"],
                len(response["review_response"]["items"]),
            )
            self.assertIsNone(response["review_response"]["selected_outcome"])
            self.assertFalse(any(response["claims"].values()))
            self.assertEqual(response["public_beta"], "NO_GO_UNPUBLISHED")

            response_verification_result = self.run_tool(
                "verify_company_pack_review_response.py",
                str(request_path),
                str(response_path),
            )
            self.assertEqual(
                response_verification_result.returncode,
                0,
                response_verification_result.stderr,
            )
            response_verification = self.json_output(response_verification_result)
            response_verification_path = (
                parent / "guided-company-review-response-verification.json"
            )
            response_verification_path.write_bytes(
                response_verification_result.stdout.encode("utf-8")
            )
            self.assertEqual(
                response_verification["status"], "ITEM_RESPONSES_MATCH_REQUEST"
            )
            self.assertFalse(any(response_verification["claims"].values()))
            self.assertEqual(
                response_verification["public_beta"], "NO_GO_UNPUBLISHED"
            )

            handoff_result = self.run_tool(
                "build_company_pack_review_decision_handoff.py",
                str(bundle_path),
                str(target),
                str(bundle_verification_path),
                str(request_path),
                str(response_path),
                str(response_verification_path),
            )
            self.assertEqual(handoff_result.returncode, 0, handoff_result.stderr)
            handoff = self.json_output(handoff_result)
            handoff_path = parent / "guided-company-review-decision-handoff.json"
            handoff_path.write_bytes(handoff_result.stdout.encode("utf-8"))
            self.assertEqual(handoff["status"], "CANDIDATE_DECISION_HANDOFF")
            self.assertEqual(
                handoff["review_summary"]["completed_items"],
                request["review_request"]["item_count"],
            )
            self.assertEqual(
                handoff["decision_requirements"]["state"], "HUMAN_DECISION_REQUIRED"
            )
            self.assertIsNone(handoff["decision_requirements"]["decision"])
            self.assertIsNone(handoff["decision_requirements"]["selected_outcome"])
            self.assertFalse(any(handoff["claims"].values()))
            self.assertEqual(handoff["public_beta"], "NO_GO_UNPUBLISHED")

            handoff_verification_result = self.run_tool(
                "verify_company_pack_review_decision_handoff.py",
                str(bundle_path),
                str(target),
                str(bundle_verification_path),
                str(request_path),
                str(response_path),
                str(response_verification_path),
                str(handoff_path),
            )
            self.assertEqual(
                handoff_verification_result.returncode,
                0,
                handoff_verification_result.stderr,
            )
            handoff_verification = self.json_output(handoff_verification_result)
            self.assertEqual(
                handoff_verification["status"], "DECISION_HANDOFF_MATCH"
            )
            self.assertFalse(any(handoff_verification["claims"].values()))
            self.assertEqual(
                handoff_verification["public_beta"], "NO_GO_UNPUBLISHED"
            )

    def test_plain_starter_path_refuses_bundle_until_static_customization_is_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "work"
            parent.mkdir()
            target = parent / "plain-company"

            created = self.json_output(
                self.run_tool("create_company_pack.py", "plain-company", str(target))
            )
            self.assertEqual(created["status"], "PASS")
            self.assertEqual(created["customization_status"], "CUSTOMIZATION_REQUIRED")

            refused = self.run_tool(
                "build_company_pack_review_bundle.py", str(target)
            )
            self.assertEqual(refused.returncode, 1)
            refusal = self.json_output(refused)
            self.assertEqual(refusal["status"], "BUNDLE_REFUSED")
            self.assertEqual(refusal["reason"], "CUSTOMIZATION_REQUIRED")
            self.assertEqual(refusal["bundle_digest"], None)
            self.assertEqual(refusal["binding_count"], 0)
            self.assertEqual(refusal["public_beta"], "NO_GO_UNPUBLISHED")
            self.assertFalse(any(refusal["claims"].values()))  # type: ignore[union-attr]
