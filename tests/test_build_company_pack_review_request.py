import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
import build_company_pack_review_request as request_builder


REQUEST_BUILDER = ROOT / "tools" / "build_company_pack_review_request.py"
BUNDLE_BUILDER = ROOT / "tools" / "build_company_pack_review_bundle.py"
CREATOR = ROOT / "tools" / "create_company_pack.py"


class CompanyPackReviewRequestCliTests(unittest.TestCase):
    def create_ready_pack(self, parent: Path) -> tuple[Path, str, str]:
        pack = parent / "review-request-pack"
        creation = subprocess.run(
            [sys.executable, str(CREATOR), "review-request-pack", str(pack)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(creation.returncode, 0, creation.stdout)

        human_intent_ref = "human-intent:private-review-request-source"
        retention_policy_ref = "retention-policy:private-review-request-policy"
        manifest_path = pack / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["human_intent_ref"] = human_intent_ref
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        for collection in ("blocks", "records"):
            for relative in manifest[collection]:
                path = pack / relative
                document = json.loads(path.read_text(encoding="utf-8"))
                if collection == "blocks":
                    document["authority"]["expires_at"] = "2026-08-20T00:00:00Z"
                else:
                    document["retention"]["policy_ref"] = retention_policy_ref
                path.write_text(json.dumps(document), encoding="utf-8")
        return pack, human_intent_ref, retention_policy_ref

    def save_bundle(self, pack: Path, path: Path) -> tuple[dict, bytes]:
        result = subprocess.run(
            [sys.executable, str(BUNDLE_BUILDER), str(pack)],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout.decode("utf-8"))
        path.write_bytes(result.stdout)
        return json.loads(result.stdout), result.stdout

    def run_builder(
        self, bundle_path: Path, pack: Path
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, str(REQUEST_BUILDER), str(bundle_path), str(pack)],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )

    def test_matched_ready_pack_builds_exact_pending_review_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pack, human_intent_ref, retention_policy_ref = self.create_ready_pack(root)
            bundle_path = root / "saved-review-bundle.json"
            bundle, bundle_bytes = self.save_bundle(pack, bundle_path)
            result = self.run_builder(bundle_path, pack)

        self.assertEqual(result.returncode, 0, result.stdout.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        self.assertNotIn(human_intent_ref.encode("utf-8"), result.stdout)
        self.assertNotIn(retention_policy_ref.encode("utf-8"), result.stdout)
        request = json.loads(result.stdout)
        self.assertEqual(request["kind"], "company_pack_review_request")
        self.assertEqual(request["version"], "1.0")
        self.assertEqual(request["status"], "CANDIDATE_REVIEW_REQUEST")
        self.assertIsNone(request["reason"])
        self.assertEqual(request["pack_id"], "review-request-pack")
        self.assertEqual(
            request["candidate_binding"],
            {
                "saved_bundle": {
                    "sha256": hashlib.sha256(bundle_bytes).hexdigest(),
                    "bytes": len(bundle_bytes),
                },
                "bundle_digest": bundle["bundle_digest"],
                "binding_count": 22,
            },
        )
        self.assertEqual(
            request["source_checks"],
            {
                "bundle_verification": {
                    "status": "MATCH",
                    "matched_bindings": 22,
                },
                "customization": {
                    "status": "READY_FOR_GOVERNED_REVIEW",
                    "counts": {
                        "replacement_required": 0,
                        "review_required": 46,
                        "evidence_required": 5,
                    },
                },
            },
        )
        review = request["review_request"]
        self.assertEqual(review["state"], "PENDING_AUTHORIZED_REVIEW")
        self.assertEqual(review["item_count"], 46)
        self.assertEqual(len(review["items"]), 46)
        self.assertTrue(
            all(item["category"] == "review_required" for item in review["items"])
        )
        self.assertEqual(
            review["permitted_outcomes"],
            ["accept", "request_changes", "reject"],
        )
        self.assertIsNone(review["selected_outcome"])
        evidence = request["unresolved_evidence"]
        self.assertEqual(evidence["state"], "EVIDENCE_REQUIRED")
        self.assertEqual(evidence["item_count"], 5)
        self.assertEqual(len(evidence["items"]), 5)
        self.assertTrue(
            all(item["category"] == "evidence_required" for item in evidence["items"])
        )
        self.assertTrue(all(value is False for value in request["claims"].values()))
        self.assertEqual(request["public_beta"], "NO_GO_UNPUBLISHED")

    def test_pack_byte_change_refuses_request_without_echoing_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pack, human_intent_ref, retention_policy_ref = self.create_ready_pack(root)
            bundle_path = root / "private-bundle-name.json"
            self.save_bundle(pack, bundle_path)
            record_path = pack / "records" / "source-record.json"
            record_path.write_bytes(record_path.read_bytes() + b"\n")
            result = self.run_builder(bundle_path, pack)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, b"")
        self.assertNotIn(str(pack).encode("utf-8"), result.stdout)
        self.assertNotIn(str(bundle_path).encode("utf-8"), result.stdout)
        self.assertNotIn(human_intent_ref.encode("utf-8"), result.stdout)
        self.assertNotIn(retention_policy_ref.encode("utf-8"), result.stdout)
        request = json.loads(result.stdout)
        self.assertEqual(request["status"], "REQUEST_REFUSED")
        self.assertEqual(request["reason"], "BUNDLE_VERIFICATION_FAILED")
        self.assertIsNone(request["pack_id"])
        self.assertIsNone(request["candidate_binding"])
        self.assertEqual(request["review_request"]["state"], "NOT_CREATED")
        self.assertEqual(request["review_request"]["items"], [])
        self.assertIsNone(request["review_request"]["selected_outcome"])
        self.assertEqual(request["unresolved_evidence"]["items"], [])
        self.assertTrue(all(value is False for value in request["claims"].values()))
        self.assertEqual(request["public_beta"], "NO_GO_UNPUBLISHED")

    def test_review_request_schema_closes_request_and_decision_boundaries(self) -> None:
        schema = json.loads(
            (
                ROOT / "schemas" / "company-pack-review-request.schema.json"
            ).read_text(encoding="utf-8")
        )

        self.assertEqual(schema["additionalProperties"], False)
        self.assertEqual(
            schema["properties"]["public_beta"]["const"], "NO_GO_UNPUBLISHED"
        )
        review_schema = schema["properties"]["review_request"]
        self.assertEqual(review_schema["additionalProperties"], False)
        self.assertEqual(
            review_schema["properties"]["selected_outcome"]["type"], "null"
        )
        self.assertEqual(
            review_schema["properties"]["permitted_outcomes"]["prefixItems"],
            [
                {"const": "accept"},
                {"const": "request_changes"},
                {"const": "reject"},
            ],
        )
        self.assertEqual(
            schema["properties"]["claims"]["additionalProperties"], False
        )
        self.assertTrue(
            all(
                definition["const"] is False
                for definition in schema["properties"]["claims"]["properties"].values()
            )
        )

    def test_bundle_file_change_during_read_is_refused_as_source_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pack, _human_intent_ref, _retention_policy_ref = self.create_ready_pack(root)
            bundle_path = root / "saved-review-bundle.json"
            bundle, bundle_bytes = self.save_bundle(pack, bundle_path)
            with mock.patch.object(
                request_builder,
                "load_valid_saved_bundle",
                return_value=(bundle, bundle_bytes + b" "),
            ):
                request = request_builder.build_review_request(bundle_path, pack)

        self.assertEqual(request["status"], "REQUEST_REFUSED")
        self.assertEqual(request["reason"], "SOURCE_DRIFT_DETECTED")
        self.assertIsNone(request["candidate_binding"])
        self.assertEqual(request["review_request"]["items"], [])

    def test_unexpected_verifier_read_failure_is_a_safe_refusal(self) -> None:
        with mock.patch.object(
            request_builder,
            "verify_saved_bundle",
            side_effect=OSError("private operating system detail"),
        ):
            request = request_builder.build_review_request(
                Path("private-bundle-name.json"), Path("private-pack-name")
            )

        self.assertEqual(request["status"], "REQUEST_REFUSED")
        self.assertEqual(request["reason"], "BUNDLE_VERIFICATION_FAILED")
        self.assertNotIn("private", json.dumps(request))
        self.assertIsNone(request["candidate_binding"])


if __name__ == "__main__":
    unittest.main()
