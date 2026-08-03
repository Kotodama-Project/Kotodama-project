import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
import build_company_pack_review_response as response_builder


CREATOR = ROOT / "tools" / "create_company_pack.py"
BUNDLE_BUILDER = ROOT / "tools" / "build_company_pack_review_bundle.py"
REQUEST_BUILDER = ROOT / "tools" / "build_company_pack_review_request.py"
RESPONSE_BUILDER = ROOT / "tools" / "build_company_pack_review_response.py"
RESPONSE_VERIFIER = ROOT / "tools" / "verify_company_pack_review_response.py"


class CompanyPackReviewResponseCliTests(unittest.TestCase):
    def create_saved_request(self, parent: Path) -> tuple[Path, dict, bytes]:
        pack = parent / "review-response-pack"
        creation = subprocess.run(
            [
                sys.executable,
                str(CREATOR),
                "review-response-pack",
                str(pack),
                "--human-intent-ref",
                "human-intent:private-review-response-source",
                "--authority-expires-at",
                "2026-08-20T00:00:00Z",
                "--retention-policy-ref",
                "retention-policy:private-review-response-policy",
            ],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
        self.assertEqual(creation.returncode, 0, creation.stdout.decode("utf-8"))

        bundle = subprocess.run(
            [sys.executable, str(BUNDLE_BUILDER), str(pack)],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
        self.assertEqual(bundle.returncode, 0, bundle.stdout.decode("utf-8"))
        bundle_path = parent / "saved-review-bundle.json"
        bundle_path.write_bytes(bundle.stdout)

        request = subprocess.run(
            [sys.executable, str(REQUEST_BUILDER), str(bundle_path), str(pack)],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
        self.assertEqual(request.returncode, 0, request.stdout.decode("utf-8"))
        request_path = parent / "saved-review-request.json"
        request_path.write_bytes(request.stdout)
        return request_path, json.loads(request.stdout), request.stdout

    def run_builder(
        self, request_path: Path, *, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, str(RESPONSE_BUILDER), str(request_path)],
            cwd=ROOT,
            capture_output=True,
            check=False,
            env=env,
        )

    def run_verifier(
        self,
        request_path: Path,
        response_path: Path,
        *,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [
                sys.executable,
                str(RESPONSE_VERIFIER),
                str(request_path),
                str(response_path),
            ],
            cwd=ROOT,
            capture_output=True,
            check=False,
            env=env,
        )

    def test_request_builds_exact_response_candidate_without_retyping_items(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request_path, request, request_bytes = self.create_saved_request(root)
            result = self.run_builder(request_path)

        self.assertEqual(result.returncode, 0, result.stdout.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        self.assertNotIn(b"private-review-response", result.stdout)
        response = json.loads(result.stdout)
        self.assertEqual(response["kind"], "company_pack_review_response")
        self.assertEqual(response["version"], "1.0")
        self.assertEqual(response["status"], "REVIEW_RESPONSE_CANDIDATE")
        self.assertIsNone(response["reason"])
        self.assertEqual(response["pack_id"], "review-response-pack")
        self.assertEqual(
            response["request_binding"],
            {
                "sha256": hashlib.sha256(request_bytes).hexdigest(),
                "bytes": len(request_bytes),
            },
        )
        self.assertEqual(response["candidate_binding"], request["candidate_binding"])
        review = response["review_response"]
        self.assertEqual(review["state"], "ITEM_RESPONSES_PENDING")
        self.assertEqual(review["item_count"], 46)
        self.assertEqual(review["permitted_outcomes"], ["accept", "request_changes", "reject"])
        self.assertIsNone(review["selected_outcome"])
        self.assertEqual(len(review["items"]), 46)
        for original, editable in zip(request["review_request"]["items"], review["items"], strict=True):
            self.assertEqual(
                {key: editable[key] for key in ("id", "category", "path", "reason")},
                original,
            )
            self.assertIsNone(editable["outcome"])
            self.assertIsNone(editable["reviewer_note"])
        self.assertEqual(response["unresolved_evidence"], request["unresolved_evidence"])
        self.assertTrue(all(value is False for value in response["claims"].values()))
        self.assertEqual(response["public_beta"], "NO_GO_UNPUBLISHED")

    def test_all_item_outcomes_match_the_exact_request_without_making_a_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request_path, request, request_bytes = self.create_saved_request(root)
            built = self.run_builder(request_path)
            self.assertEqual(built.returncode, 0, built.stdout.decode("utf-8"))
            response = json.loads(built.stdout)
            outcomes = ["accept", "request_changes", "reject"]
            for index, item in enumerate(response["review_response"]["items"]):
                item["outcome"] = outcomes[index % len(outcomes)]
                if item["outcome"] != "accept":
                    item["reviewer_note"] = f"review-note-ref:{index:02d}"
            response_bytes = (
                json.dumps(response, ensure_ascii=False, sort_keys=True) + "\n"
            ).encode("utf-8")
            response_path = root / "saved-review-response.json"
            response_path.write_bytes(response_bytes)
            result = self.run_verifier(request_path, response_path)

        self.assertEqual(result.returncode, 0, result.stdout.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        self.assertNotIn(b"review-note-ref", result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report["kind"], "company_pack_review_response_verification")
        self.assertEqual(report["version"], "1.0")
        self.assertEqual(report["status"], "ITEM_RESPONSES_MATCH_REQUEST")
        self.assertIsNone(report["reason"])
        self.assertEqual(report["pack_id"], "review-response-pack")
        self.assertEqual(
            report["request_binding"],
            {
                "sha256": hashlib.sha256(request_bytes).hexdigest(),
                "bytes": len(request_bytes),
            },
        )
        self.assertEqual(
            report["response_binding"],
            {
                "sha256": hashlib.sha256(response_bytes).hexdigest(),
                "bytes": len(response_bytes),
            },
        )
        self.assertEqual(report["candidate_binding"], request["candidate_binding"])
        self.assertEqual(
            report["review_summary"],
            {
                "state": "ALL_ITEM_RESPONSES_PRESENT",
                "expected_items": 46,
                "completed_items": 46,
                "outcome_counts": {
                    "accept": 16,
                    "request_changes": 15,
                    "reject": 15,
                },
                "selected_outcome": None,
            },
        )
        self.assertEqual(
            report["unresolved_evidence"],
            {"state": "EVIDENCE_REQUIRED", "item_count": 5},
        )
        self.assertNotIn("items", report["review_summary"])
        self.assertTrue(all(value is False for value in report["claims"].values()))
        self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")

    def test_builder_strictly_refuses_tampered_or_oversized_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request_path, request, _request_bytes = self.create_saved_request(root)
            sentinel = "PRIVATE_SENTINEL_DO_NOT_ECHO"
            cases: list[tuple[str, bytes]] = []

            unknown = {**request, "unknown": sentinel}
            cases.append(("unknown field", json.dumps(unknown).encode("utf-8")))

            wrong_count = json.loads(json.dumps(request))
            wrong_count["review_request"]["item_count"] = 45
            cases.append(("wrong count", json.dumps(wrong_count).encode("utf-8")))

            duplicate_item = json.loads(json.dumps(request))
            duplicate_item["review_request"]["items"][1]["id"] = duplicate_item[
                "review_request"
            ]["items"][0]["id"]
            cases.append(("duplicate item", json.dumps(duplicate_item).encode("utf-8")))

            raised_claim = json.loads(json.dumps(request))
            raised_claim["claims"]["human_approval_verified"] = True
            cases.append(("raised claim", json.dumps(raised_claim).encode("utf-8")))

            duplicate_key = (
                '{"kind":"company_pack_review_request","kind":"'
                + sentinel
                + '"}'
            ).encode("utf-8")
            cases.append(("duplicate key", duplicate_key))

            deep = (b'{"nested":' + b"[" * 80 + b"0" + b"]" * 80 + b"}")
            cases.append(("deep input", deep))

            oversized = json.dumps(request).encode("utf-8") + b" " * (1024 * 1024)
            cases.append(("oversized input", oversized))

            for label, payload in cases:
                with self.subTest(label=label):
                    request_path.write_bytes(payload)
                    result = self.run_builder(request_path)
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stderr, b"")
                    self.assertNotIn(sentinel.encode("utf-8"), result.stdout)
                    self.assertNotIn(str(request_path).encode("utf-8"), result.stdout)
                    refusal = json.loads(result.stdout)
                    self.assertEqual(refusal["status"], "RESPONSE_BUILD_REFUSED")
                    self.assertEqual(refusal["reason"], "REQUEST_INVALID")
                    self.assertIsNone(refusal["pack_id"])
                    self.assertIsNone(refusal["request_binding"])
                    self.assertIsNone(refusal["candidate_binding"])
                    self.assertEqual(refusal["review_response"]["items"], [])
                    self.assertEqual(refusal["unresolved_evidence"]["items"], [])
                    self.assertTrue(
                        all(value is False for value in refusal["claims"].values())
                    )

    def test_builder_refuses_request_byte_change_during_read_as_source_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request_path, _request, request_bytes = self.create_saved_request(root)
            with mock.patch.object(
                Path,
                "read_bytes",
                side_effect=[request_bytes, request_bytes + b" "],
            ):
                response = response_builder.build_response_candidate(request_path)

        self.assertEqual(response["status"], "RESPONSE_BUILD_REFUSED")
        self.assertEqual(response["reason"], "SOURCE_DRIFT_DETECTED")
        self.assertIsNone(response["request_binding"])
        self.assertEqual(response["review_response"]["items"], [])


if __name__ == "__main__":
    unittest.main()
