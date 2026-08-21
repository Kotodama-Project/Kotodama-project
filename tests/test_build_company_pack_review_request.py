import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
import build_company_pack_review_request as request_builder


REQUEST_BUILDER = ROOT / "tools" / "build_company_pack_review_request.py"
BUNDLE_BUILDER = ROOT / "tools" / "build_company_pack_review_bundle.py"
CREATOR = ROOT / "tools" / "create_company_pack.py"
REQUEST_SCHEMA = ROOT / "schemas" / "company-pack-review-request.schema.json"
REVIEW_REQUEST_DOC = ROOT / "docs" / "REVIEW-REQUEST.md"
AUTHORITY_EXPIRES_AT = (
    datetime.now(timezone.utc) + timedelta(days=7)
).isoformat(timespec="seconds").replace("+00:00", "Z")


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
                    document["authority"]["expires_at"] = AUTHORITY_EXPIRES_AT
                else:
                    document["retention"]["policy_ref"] = retention_policy_ref
                path.write_text(json.dumps(document), encoding="utf-8")
        return pack, human_intent_ref, retention_policy_ref

    def create_recordless_ready_pack(self, parent: Path) -> tuple[Path, str]:
        pack = parent / "recordless-review-request-pack"
        creation = subprocess.run(
            [sys.executable, str(CREATOR), "recordless-review-request-pack", str(pack)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(creation.returncode, 0, creation.stdout)

        human_intent_ref = "human-intent:private-recordless-review-request-source"
        manifest_path = pack / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["human_intent_ref"] = human_intent_ref
        manifest.pop("records")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        for relative in manifest["blocks"]:
            path = pack / relative
            document = json.loads(path.read_text(encoding="utf-8"))
            document["authority"]["expires_at"] = AUTHORITY_EXPIRES_AT
            path.write_text(json.dumps(document), encoding="utf-8")
        return pack, human_intent_ref

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
        self, bundle_path: Path, pack: Path, *, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, str(REQUEST_BUILDER), str(bundle_path), str(pack)],
            cwd=ROOT,
            capture_output=True,
            check=False,
            env=env,
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
            len({item["id"] for item in review["items"]}), review["item_count"]
        )
        self.assertEqual(
            len({item["path"] for item in review["items"]}), review["item_count"]
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

    def test_recordless_pack_request_uses_dynamic_item_and_binding_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pack, human_intent_ref = self.create_recordless_ready_pack(root)
            bundle_path = root / "recordless-saved-review-bundle.json"
            bundle, _bundle_bytes = self.save_bundle(pack, bundle_path)
            result = self.run_builder(bundle_path, pack)

        self.assertEqual(result.returncode, 0, result.stdout.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        self.assertNotIn(str(pack).encode("utf-8"), result.stdout)
        self.assertNotIn(str(bundle_path).encode("utf-8"), result.stdout)
        self.assertNotIn(human_intent_ref.encode("utf-8"), result.stdout)
        request = json.loads(result.stdout)
        schema = json.loads(REQUEST_SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(request)
        self.assertEqual(request["status"], "CANDIDATE_REVIEW_REQUEST")
        self.assertEqual(request["candidate_binding"]["binding_count"], 13)
        self.assertEqual(
            request["source_checks"]["bundle_verification"]["matched_bindings"], 13
        )
        review = request["review_request"]
        evidence = request["unresolved_evidence"]
        self.assertEqual(review["item_count"], len(review["items"]))
        self.assertEqual(evidence["item_count"], len(evidence["items"]))
        self.assertEqual(review["item_count"], bundle["source_checks"]["customization"]["counts"]["review_required"])
        self.assertEqual(evidence["item_count"], bundle["source_checks"]["customization"]["counts"]["evidence_required"])
        self.assertTrue(all(value is False for value in request["claims"].values()))
        self.assertEqual(request["public_beta"], "NO_GO_UNPUBLISHED")
        self.assertIn("`review_request.item_count`", REVIEW_REQUEST_DOC.read_text(encoding="utf-8"))

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

    def test_pack_change_during_second_checker_read_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pack, _human_intent_ref, _retention_policy_ref = self.create_ready_pack(root)
            bundle_path = root / "saved-review-bundle.json"
            self.save_bundle(pack, bundle_path)
            stable_report = request_builder.check_customization(pack)
            calls = 0

            def checker_with_late_change(_pack: Path) -> dict:
                nonlocal calls
                calls += 1
                if calls == 2:
                    record_path = pack / "records" / "source-record.json"
                    record_path.write_bytes(record_path.read_bytes() + b"\n")
                return stable_report

            with mock.patch.object(
                request_builder,
                "check_customization",
                side_effect=checker_with_late_change,
            ):
                request = request_builder.build_review_request(bundle_path, pack)

        self.assertEqual(request["status"], "REQUEST_REFUSED")
        self.assertEqual(request["reason"], "SOURCE_DRIFT_DETECTED")
        self.assertIsNone(request["candidate_binding"])

    def test_output_is_deterministic_utf8_under_legacy_console_encoding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pack, _human_intent_ref, _retention_policy_ref = self.create_ready_pack(root)
            bundle_path = root / "saved-review-bundle.json"
            self.save_bundle(pack, bundle_path)
            legacy_env = dict(os.environ)
            legacy_env["PYTHONIOENCODING"] = "cp1252"
            first = self.run_builder(bundle_path, pack, env=legacy_env)
            second = self.run_builder(bundle_path, pack, env=legacy_env)

        self.assertEqual(first.returncode, 0, first.stdout.decode("utf-8"))
        self.assertEqual(first.stderr, b"")
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(
            json.loads(first.stdout)["review_request"]["state"],
            "PENDING_AUTHORIZED_REVIEW",
        )

    def test_malformed_bundle_and_hostile_extra_arg_do_not_reflect_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pack, _human_intent_ref, _retention_policy_ref = self.create_ready_pack(root)
            bundle_path = root / "malformed-private-bundle.json"
            hostile_value = "PRIVATE_SENTINEL_DO_NOT_ECHO"
            bundle_path.write_text(
                json.dumps({"unexpected": hostile_value}), encoding="utf-8"
            )
            refused = self.run_builder(bundle_path, pack)
            usage = subprocess.run(
                [
                    sys.executable,
                    str(REQUEST_BUILDER),
                    str(bundle_path),
                    str(pack),
                    hostile_value,
                ],
                cwd=ROOT,
                capture_output=True,
                check=False,
            )

        self.assertEqual(refused.returncode, 1)
        self.assertNotIn(hostile_value.encode("utf-8"), refused.stdout)
        self.assertEqual(
            json.loads(refused.stdout)["reason"], "BUNDLE_VERIFICATION_FAILED"
        )
        self.assertEqual(usage.returncode, 2)
        self.assertEqual(usage.stdout, b"")
        self.assertNotIn(hostile_value.encode("utf-8"), usage.stderr)
        self.assertIn(b"usage:", usage.stderr)


if __name__ == "__main__":
    unittest.main()
