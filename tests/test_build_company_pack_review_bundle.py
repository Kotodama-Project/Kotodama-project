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
import build_company_pack_review_bundle as bundle_builder


BUILDER = ROOT / "tools" / "build_company_pack_review_bundle.py"
CREATOR = ROOT / "tools" / "create_company_pack.py"


class CompanyPackReviewBundleCliTests(unittest.TestCase):
    def run_builder(self, pack: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(BUILDER), str(pack)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def create_pack(self, parent: Path) -> tuple[Path, str]:
        pack = parent / "review-pack"
        result = subprocess.run(
            [sys.executable, str(CREATOR), "review-pack", str(pack)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        private_locator = "human-intent:private-review-source"
        manifest_path = pack / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["human_intent_ref"] = private_locator
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        for collection in ("blocks", "mocs", "records"):
            for relative in manifest[collection]:
                path = pack / relative
                document = json.loads(path.read_text(encoding="utf-8"))
                if collection == "blocks":
                    document["authority"]["expires_at"] = "2026-09-01T00:00:00Z"
                if collection == "records":
                    document["retention"]["policy_ref"] = "retention:private-v1"
                path.write_text(json.dumps(document), encoding="utf-8")
        return pack, private_locator

    def create_recordless_pack(self, parent: Path) -> Path:
        pack = parent / "recordless-review-pack"
        result = subprocess.run(
            [sys.executable, str(CREATOR), "recordless-review-pack", str(pack)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        manifest_path = pack / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["human_intent_ref"] = "human-intent:governed-alpha"
        manifest.pop("records")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        for relative in manifest["blocks"]:
            path = pack / relative
            document = json.loads(path.read_text(encoding="utf-8"))
            document["authority"]["expires_at"] = "2026-09-01T00:00:00Z"
            path.write_text(json.dumps(document), encoding="utf-8")
        return pack

    def test_ready_pack_builds_exact_candidate_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack, private_locator = self.create_pack(Path(temporary))
            result = self.run_builder(pack)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stderr, "")
        self.assertNotIn(private_locator, result.stdout)
        self.assertNotIn("retention:private-v1", result.stdout)
        bundle = json.loads(result.stdout)
        self.assertEqual(bundle["kind"], "company_pack_review_bundle")
        self.assertEqual(bundle["version"], "1.0")
        self.assertEqual(bundle["status"], "CANDIDATE_FOR_GOVERNED_REVIEW")
        self.assertEqual(bundle["pack_id"], "review-pack")
        self.assertEqual(bundle["source_checks"]["structural_validation"], {
            "status": "PASS",
            "validated_files": 22,
        })
        self.assertEqual(
            bundle["source_checks"]["customization"],
            {
                "status": "READY_FOR_GOVERNED_REVIEW",
                "counts": {
                    "replacement_required": 0,
                    "review_required": 46,
                    "evidence_required": 5,
                },
            },
        )
        self.assertEqual(bundle["binding_count"], 22)
        self.assertEqual(bundle["bindings"][0]["path"], "manifest.json")
        self.assertEqual(
            [binding["path"] for binding in bundle["bindings"]],
            sorted(
                [binding["path"] for binding in bundle["bindings"]],
                key=lambda path: (path != "manifest.json", path),
            ),
        )
        for binding in bundle["bindings"]:
            self.assertRegex(binding["sha256"], r"^[0-9a-f]{64}$")
            self.assertGreater(binding["bytes"], 0)
        canonical = json.dumps(
            bundle["bindings"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(
            bundle["bundle_digest"],
            {
                "algorithm": "SHA-256",
                "canonicalization": "utf8-json-sort-keys-no-whitespace-v1",
                "value": hashlib.sha256(canonical).hexdigest(),
            },
        )
        self.assertTrue(all(not value for value in bundle["claims"].values()))
        self.assertEqual(bundle["public_beta"], "NO_GO_UNPUBLISHED")

    def test_bundle_is_deterministic_and_changes_on_byte_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack, _private_locator = self.create_pack(Path(temporary))
            first = self.run_builder(pack)
            second = self.run_builder(pack)
            self.assertEqual(first.returncode, 0, first.stdout)
            self.assertEqual(first.stdout, second.stdout)

            record_path = pack / "records" / "source-record.json"
            record_path.write_bytes(record_path.read_bytes() + b"\n")
            drifted = self.run_builder(pack)

        self.assertEqual(drifted.returncode, 0, drifted.stdout)
        self.assertNotEqual(first.stdout, drifted.stdout)
        self.assertNotEqual(
            json.loads(first.stdout)["bundle_digest"]["value"],
            json.loads(drifted.stdout)["bundle_digest"]["value"],
        )

    def test_recordless_pack_binds_only_referenced_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = self.create_recordless_pack(Path(temporary))
            result = self.run_builder(pack)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stderr, "")
        bundle = json.loads(result.stdout)
        self.assertEqual(bundle["status"], "CANDIDATE_FOR_GOVERNED_REVIEW")
        self.assertEqual(bundle["source_checks"]["structural_validation"], {
            "status": "PASS",
            "validated_files": 13,
        })
        self.assertEqual(bundle["binding_count"], 13)
        self.assertTrue(all("records/" not in binding["path"] for binding in bundle["bindings"]))
        self.assertTrue(all(not value for value in bundle["claims"].values()))
        self.assertEqual(bundle["public_beta"], "NO_GO_UNPUBLISHED")

    def test_initialized_pack_is_refused_without_file_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            pack = parent / "incomplete-pack"
            creation = subprocess.run(
                [sys.executable, str(CREATOR), "incomplete-pack", str(pack)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(creation.returncode, 0, creation.stdout)
            result = self.run_builder(pack)

        self.assertEqual(result.returncode, 1)
        response = json.loads(result.stdout)
        self.assertEqual(response["status"], "BUNDLE_REFUSED")
        self.assertEqual(response["reason"], "CUSTOMIZATION_REQUIRED")
        self.assertEqual(response["bindings"], [])
        self.assertEqual(response["binding_count"], 0)
        self.assertIsNone(response["bundle_digest"])
        self.assertTrue(all(not value for value in response["claims"].values()))

    def test_invalid_pack_is_refused_without_echoing_private_locator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack, private_locator = self.create_pack(Path(temporary))
            manifest_path = pack / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            del manifest["profiles"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_builder(pack)

        self.assertEqual(result.returncode, 1)
        self.assertNotIn(private_locator, result.stdout)
        response = json.loads(result.stdout)
        self.assertEqual(response["status"], "BUNDLE_REFUSED")
        self.assertEqual(response["reason"], "STRUCTURAL_VALIDATION_FAILED")
        self.assertEqual(response["source_checks"]["structural_validation"]["status"], "FAIL")
        self.assertIsNone(response["source_checks"]["customization"])

    def test_customization_read_error_fails_closed_as_source_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack, _private_locator = self.create_pack(Path(temporary))
            with mock.patch.object(
                bundle_builder,
                "check_customization",
                side_effect=OSError("simulated concurrent replacement"),
            ):
                response = bundle_builder.build_review_bundle(pack)

        self.assertEqual(response["status"], "BUNDLE_REFUSED")
        self.assertEqual(response["reason"], "SOURCE_DRIFT_DETECTED")
        self.assertEqual(response["bindings"], [])
        self.assertIsNone(response["source_checks"]["customization"])

    def test_pack_becoming_invalid_between_checks_is_normalized_to_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack, _private_locator = self.create_pack(Path(temporary))
            with mock.patch.object(
                bundle_builder,
                "check_customization",
                return_value={
                    "status": "INVALID_PACK",
                    "counts": {
                        "replacement_required": 0,
                        "review_required": 0,
                        "evidence_required": 0,
                    },
                },
            ):
                response = bundle_builder.build_review_bundle(pack)

        self.assertEqual(response["status"], "BUNDLE_REFUSED")
        self.assertEqual(response["reason"], "SOURCE_DRIFT_DETECTED")
        self.assertIsNone(response["source_checks"]["customization"])

    def test_pack_id_drift_between_validations_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack, _private_locator = self.create_pack(Path(temporary))
            actual_validation = bundle_builder.validate_pack(pack)
            changed_validation = {**actual_validation, "pack_id": "other-valid-pack"}
            with mock.patch.object(
                bundle_builder,
                "validate_pack",
                side_effect=[actual_validation, changed_validation],
            ):
                response = bundle_builder.build_review_bundle(pack)

        self.assertEqual(response["status"], "BUNDLE_REFUSED")
        self.assertEqual(response["reason"], "SOURCE_DRIFT_DETECTED")
        self.assertEqual(response["bindings"], [])
        self.assertIsNone(response["bundle_digest"])

    def test_review_bundle_schema_matches_success_and_refusal_shapes(self) -> None:
        schema = json.loads(
            (ROOT / "schemas" / "company-pack-review-bundle.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(schema["properties"]["public_beta"]["const"], "NO_GO_UNPUBLISHED")
        self.assertEqual(schema["properties"]["claims"]["additionalProperties"], False)
        self.assertIn("CANDIDATE_FOR_GOVERNED_REVIEW", schema["properties"]["status"]["enum"])
        self.assertIn("BUNDLE_REFUSED", schema["properties"]["status"]["enum"])


if __name__ == "__main__":
    unittest.main()
