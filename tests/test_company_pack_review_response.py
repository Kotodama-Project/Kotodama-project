import hashlib
import io
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
import verify_company_pack_review_response as response_verifier


CREATOR = ROOT / "tools" / "create_company_pack.py"
BUNDLE_BUILDER = ROOT / "tools" / "build_company_pack_review_bundle.py"
REQUEST_BUILDER = ROOT / "tools" / "build_company_pack_review_request.py"
RESPONSE_BUILDER = ROOT / "tools" / "build_company_pack_review_response.py"
RESPONSE_VERIFIER = ROOT / "tools" / "verify_company_pack_review_response.py"


class CompanyPackReviewResponseCliTests(unittest.TestCase):
    def test_input_reader_never_requests_more_than_limit_plus_one(self) -> None:
        class TrackingBytesIO(io.BytesIO):
            def __init__(self, value: bytes) -> None:
                super().__init__(value)
                self.read_sizes: list[int] = []

            def read(self, size: int = -1) -> bytes:
                self.read_sizes.append(size)
                return super().read(size)

        stream = TrackingBytesIO(b"{}")
        with mock.patch.object(Path, "open", return_value=stream):
            result = response_builder.read_limited_bytes(Path("ignored.json"))

        self.assertEqual(result, b"{}")
        self.assertEqual(stream.read_sizes, [response_builder.MAX_JSON_BYTES + 1])

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

    def completed_response(self, request_path: Path) -> dict:
        built = self.run_builder(request_path)
        self.assertEqual(built.returncode, 0, built.stdout.decode("utf-8"))
        response = json.loads(built.stdout)
        for item in response["review_response"]["items"]:
            item["outcome"] = "accept"
        return response

    def save_json(self, path: Path, value: dict) -> bytes:
        data = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        path.write_bytes(data)
        return data

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

            float_count = json.loads(json.dumps(request))
            float_count["review_request"]["item_count"] = 46.0
            cases.append(("float item count", json.dumps(float_count).encode("utf-8")))

            float_binding_count = json.loads(json.dumps(request))
            float_binding_count["candidate_binding"]["binding_count"] = 22.0
            cases.append(
                ("float binding count", json.dumps(float_binding_count).encode("utf-8"))
            )

            boolean_zero_count = json.loads(json.dumps(request))
            boolean_zero_count["source_checks"]["customization"]["counts"][
                "replacement_required"
            ] = False
            cases.append(
                ("boolean zero count", json.dumps(boolean_zero_count).encode("utf-8"))
            )

            duplicate_item = json.loads(json.dumps(request))
            duplicate_item["review_request"]["items"][1]["id"] = duplicate_item[
                "review_request"
            ]["items"][0]["id"]
            cases.append(("duplicate item", json.dumps(duplicate_item).encode("utf-8")))

            cross_category_path = json.loads(json.dumps(request))
            cross_category_path["unresolved_evidence"]["items"][0]["path"] = (
                cross_category_path["review_request"]["items"][0]["path"]
            )
            cases.append(
                (
                    "cross-category duplicate path",
                    json.dumps(cross_category_path).encode("utf-8"),
                )
            )

            surrogate_text = json.loads(json.dumps(request))
            surrogate_text["review_request"]["items"][0]["reason"] = "bad-\ud800-text"
            cases.append(("surrogate text", json.dumps(surrogate_text).encode("utf-8")))

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
                response_builder,
                "read_limited_bytes",
                side_effect=[request_bytes, request_bytes + b" "],
            ):
                response = response_builder.build_response_candidate(request_path)

        self.assertEqual(response["status"], "RESPONSE_BUILD_REFUSED")
        self.assertEqual(response["reason"], "SOURCE_DRIFT_DETECTED")
        self.assertIsNone(response["request_binding"])
        self.assertEqual(response["review_response"]["items"], [])

    def test_verifier_distinguishes_incomplete_input_from_binding_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request_path, _request, _request_bytes = self.create_saved_request(root)
            response_path = root / "saved-review-response.json"

            pending = json.loads(self.run_builder(request_path).stdout)
            self.save_json(response_path, pending)
            incomplete = self.run_verifier(request_path, response_path)
            self.assertEqual(incomplete.returncode, 1)
            self.assertEqual(
                json.loads(incomplete.stdout)["reason"],
                "INCOMPLETE_ITEM_RESPONSES",
            )

            missing_note = self.completed_response(request_path)
            missing_note["review_response"]["items"][0]["outcome"] = "reject"
            self.save_json(response_path, missing_note)
            missing_note_result = self.run_verifier(request_path, response_path)
            self.assertEqual(missing_note_result.returncode, 1)
            self.assertEqual(
                json.loads(missing_note_result.stdout)["reason"],
                "INCOMPLETE_ITEM_RESPONSES",
            )

            sentinel = "PRIVATE_SENTINEL_DO_NOT_ECHO"
            binding_cases: list[tuple[str, dict]] = []
            tampered_id = self.completed_response(request_path)
            tampered_id["review_response"]["items"][0]["id"] = sentinel
            binding_cases.append(("tampered item", tampered_id))

            reordered = self.completed_response(request_path)
            reordered["review_response"]["items"][0:2] = list(
                reversed(reordered["review_response"]["items"][0:2])
            )
            binding_cases.append(("reordered items", reordered))

            missing_item = self.completed_response(request_path)
            missing_item["review_response"]["items"].pop()
            binding_cases.append(("missing item", missing_item))

            duplicate_response_item = self.completed_response(request_path)
            duplicate_response_item["review_response"]["items"][1] = dict(
                duplicate_response_item["review_response"]["items"][0]
            )
            binding_cases.append(("duplicate item", duplicate_response_item))

            for field in ("category", "path", "reason"):
                tampered_field = self.completed_response(request_path)
                tampered_field["review_response"]["items"][0][field] = sentinel
                binding_cases.append((f"tampered {field}", tampered_field))

            changed_evidence = self.completed_response(request_path)
            changed_evidence["unresolved_evidence"]["items"] = []
            changed_evidence["unresolved_evidence"]["item_count"] = 0
            binding_cases.append(("changed evidence", changed_evidence))

            for label, response in binding_cases:
                with self.subTest(label=label):
                    self.save_json(response_path, response)
                    result = self.run_verifier(request_path, response_path)
                    self.assertEqual(result.returncode, 1)
                    self.assertNotIn(sentinel.encode("utf-8"), result.stdout)
                    report = json.loads(result.stdout)
                    self.assertEqual(report["reason"], "ITEM_BINDING_MISMATCH")
                    self.assertIsNone(report["pack_id"])
                    self.assertIsNone(report["request_binding"])
                    self.assertIsNone(report["response_binding"])
                    self.assertEqual(report["review_summary"]["completed_items"], 0)
                    self.assertTrue(
                        all(value is False for value in report["claims"].values())
                    )

    def test_verifier_rejects_malformed_response_and_private_note_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request_path, _request, _request_bytes = self.create_saved_request(root)
            response_path = root / "private-response-name.json"
            sentinel = "PRIVATE_SENTINEL_DO_NOT_ECHO"
            cases: list[tuple[str, bytes]] = []

            unknown = self.completed_response(request_path)
            unknown["unknown"] = sentinel
            cases.append(("unknown field", json.dumps(unknown).encode("utf-8")))

            nested_unknown = self.completed_response(request_path)
            nested_unknown["review_response"]["unknown"] = sentinel
            cases.append(
                ("nested unknown field", json.dumps(nested_unknown).encode("utf-8"))
            )

            numeric_false_claim = self.completed_response(request_path)
            numeric_false_claim["claims"]["human_approval_verified"] = 0
            cases.append(
                ("numeric false claim", json.dumps(numeric_false_claim).encode("utf-8"))
            )

            float_request_binding = self.completed_response(request_path)
            float_request_binding["request_binding"]["bytes"] = float(
                float_request_binding["request_binding"]["bytes"]
            )
            cases.append(
                (
                    "float request binding",
                    json.dumps(float_request_binding).encode("utf-8"),
                )
            )

            float_candidate_binding = self.completed_response(request_path)
            float_candidate_binding["candidate_binding"]["binding_count"] = 22.0
            cases.append(
                (
                    "float candidate binding",
                    json.dumps(float_candidate_binding).encode("utf-8"),
                )
            )

            secret_note = self.completed_response(request_path)
            secret_note["review_response"]["items"][0]["reviewer_note"] = (
                "sk-abcdefghijklmnopqrstuvwxyz123456"
            )
            cases.append(("secret note", json.dumps(secret_note).encode("utf-8")))

            local_path_note = self.completed_response(request_path)
            local_path_note["review_response"]["items"][0]["reviewer_note"] = (
                "C:\\Users\\private\\review.txt"
            )
            cases.append(("local path note", json.dumps(local_path_note).encode("utf-8")))

            forward_slash_local_path_note = self.completed_response(request_path)
            forward_slash_local_path_note["review_response"]["items"][0][
                "reviewer_note"
            ] = "C:/Users/private/review.txt"
            cases.append(
                (
                    "forward slash local path note",
                    json.dumps(forward_slash_local_path_note).encode("utf-8"),
                )
            )

            unc_local_path_note = self.completed_response(request_path)
            unc_local_path_note["review_response"]["items"][0]["reviewer_note"] = (
                "\\\\private-host\\review-share\\review.txt"
            )
            cases.append(
                ("UNC local path note", json.dumps(unc_local_path_note).encode("utf-8"))
            )

            duplicate_key = (
                '{"kind":"company_pack_review_response","kind":"'
                + sentinel
                + '"}'
            ).encode("utf-8")
            cases.append(("duplicate key", duplicate_key))

            deep = (b'{"nested":' + b"[" * 80 + b"0" + b"]" * 80 + b"}")
            cases.append(("deep input", deep))

            oversized = json.dumps(self.completed_response(request_path)).encode(
                "utf-8"
            ) + b" " * (1024 * 1024)
            cases.append(("oversized input", oversized))

            for label, payload in cases:
                with self.subTest(label=label):
                    response_path.write_bytes(payload)
                    result = self.run_verifier(request_path, response_path)
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stderr, b"")
                    self.assertNotIn(sentinel.encode("utf-8"), result.stdout)
                    self.assertNotIn(str(response_path).encode("utf-8"), result.stdout)
                    report = json.loads(result.stdout)
                    self.assertEqual(report["status"], "RESPONSE_MISMATCH")
                    self.assertEqual(report["reason"], "RESPONSE_INVALID")
                    self.assertIsNone(report["pack_id"])

    def test_verifier_final_reread_refuses_late_request_or_response_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request_path, _request, request_bytes = self.create_saved_request(root)
            response = self.completed_response(request_path)
            response_path = root / "saved-review-response.json"
            response_bytes = self.save_json(response_path, response)

            cases = [
                (
                    "late request drift",
                    [request_bytes, request_bytes],
                    [
                        response_bytes,
                        response_bytes,
                        request_bytes + b" ",
                        response_bytes,
                    ],
                ),
                (
                    "late response drift",
                    [request_bytes, request_bytes],
                    [
                        response_bytes,
                        response_bytes,
                        request_bytes,
                        response_bytes + b" ",
                    ],
                ),
            ]
            for label, request_reads, response_reads in cases:
                with self.subTest(label=label):
                    with mock.patch.object(
                        response_builder,
                        "read_limited_bytes",
                        side_effect=request_reads,
                    ), mock.patch.object(
                        response_verifier,
                        "read_limited_bytes",
                        side_effect=response_reads,
                    ):
                        report = response_verifier.verify_response(
                            request_path, response_path
                        )
                    self.assertEqual(report["status"], "RESPONSE_MISMATCH")
                    self.assertEqual(report["reason"], "SOURCE_DRIFT_DETECTED")
                    self.assertIsNone(report["request_binding"])
                    self.assertIsNone(report["response_binding"])

    def test_response_schemas_are_closed_and_keep_authority_claims_false(self) -> None:
        response_schema = json.loads(
            (ROOT / "schemas" / "company-pack-review-response.schema.json").read_text(
                encoding="utf-8"
            )
        )
        verification_schema = json.loads(
            (
                ROOT
                / "schemas"
                / "company-pack-review-response-verification.schema.json"
            ).read_text(encoding="utf-8")
        )

        for schema in (response_schema, verification_schema):
            self.assertEqual(schema["additionalProperties"], False)
            self.assertEqual(
                schema["properties"]["public_beta"]["const"],
                "NO_GO_UNPUBLISHED",
            )
            claims = schema["$defs"]["claims"]
            self.assertEqual(claims["additionalProperties"], False)
            self.assertTrue(
                all(
                    definition["const"] is False
                    for definition in claims["properties"].values()
                )
            )

        response_review = response_schema["properties"]["review_response"]
        self.assertEqual(response_review["additionalProperties"], False)
        self.assertEqual(
            response_review["properties"]["selected_outcome"]["type"], "null"
        )
        item = response_schema["$defs"]["response_item"]
        self.assertEqual(item["additionalProperties"], False)
        self.assertEqual(
            item["properties"]["outcome"]["oneOf"][1]["enum"],
            ["accept", "request_changes", "reject"],
        )

        summary = verification_schema["properties"]["review_summary"]
        self.assertEqual(summary["additionalProperties"], False)
        self.assertEqual(summary["properties"]["selected_outcome"]["type"], "null")
        self.assertNotIn("items", summary["properties"])

    def test_output_is_deterministic_utf8_and_usage_never_reflects_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request_path, _request, _request_bytes = self.create_saved_request(root)
            legacy_env = dict(os.environ)
            legacy_env["PYTHONIOENCODING"] = "cp1252"
            first_builder = self.run_builder(request_path, env=legacy_env)
            second_builder = self.run_builder(request_path, env=legacy_env)
            self.assertEqual(first_builder.returncode, 0)
            self.assertEqual(first_builder.stdout, second_builder.stdout)
            self.assertEqual(
                json.loads(first_builder.stdout)["status"],
                "REVIEW_RESPONSE_CANDIDATE",
            )

            response = json.loads(first_builder.stdout)
            for item in response["review_response"]["items"]:
                item["outcome"] = "accept"
            response_path = root / "saved-review-response.json"
            self.save_json(response_path, response)
            first_verifier = self.run_verifier(
                request_path, response_path, env=legacy_env
            )
            second_verifier = self.run_verifier(
                request_path, response_path, env=legacy_env
            )
            self.assertEqual(first_verifier.returncode, 0)
            self.assertEqual(first_verifier.stdout, second_verifier.stdout)
            self.assertEqual(
                json.loads(first_verifier.stdout)["status"],
                "ITEM_RESPONSES_MATCH_REQUEST",
            )

            sentinel = "PRIVATE_SENTINEL_DO_NOT_ECHO"
            builder_usage = subprocess.run(
                [
                    sys.executable,
                    str(RESPONSE_BUILDER),
                    str(request_path),
                    sentinel,
                ],
                cwd=ROOT,
                capture_output=True,
                check=False,
            )
            verifier_usage = subprocess.run(
                [
                    sys.executable,
                    str(RESPONSE_VERIFIER),
                    str(request_path),
                    str(response_path),
                    sentinel,
                ],
                cwd=ROOT,
                capture_output=True,
                check=False,
            )

        for result in (builder_usage, verifier_usage):
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, b"")
            self.assertIn(b"usage:", result.stderr)
            self.assertNotIn(sentinel.encode("utf-8"), result.stderr)
            self.assertNotIn(str(request_path).encode("utf-8"), result.stderr)


if __name__ == "__main__":
    unittest.main()
