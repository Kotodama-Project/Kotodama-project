import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CREATOR = ROOT / "tools" / "create_company_pack.py"
BUILDER = ROOT / "tools" / "build_company_pack_review_bundle.py"
VERIFIER = ROOT / "tools" / "verify_company_pack_review_bundle.py"


class CompanyPackReviewBundleVerifierCliTests(unittest.TestCase):
    def create_ready_pack(self, parent: Path) -> tuple[Path, str]:
        pack = parent / "verified-pack"
        creation = subprocess.run(
            [sys.executable, str(CREATOR), "verified-pack", str(pack)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(creation.returncode, 0, creation.stdout)
        private_locator = "human-intent:private-verifier-source"
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

    def build_saved_bundle(self, pack: Path, output: Path) -> dict[str, object]:
        result = subprocess.run(
            [sys.executable, str(BUILDER), str(pack)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        output.write_text(result.stdout, encoding="utf-8")
        return json.loads(result.stdout)

    def run_verifier(
        self, bundle: Path, pack: Path
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VERIFIER), str(bundle), str(pack)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_exact_saved_bundle_matches_without_granting_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            pack, private_locator = self.create_ready_pack(parent)
            bundle_path = parent / "review-bundle.json"
            saved = self.build_saved_bundle(pack, bundle_path)
            saved_bytes = bundle_path.read_bytes()
            result = self.run_verifier(bundle_path, pack)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stderr, "")
        self.assertNotIn(private_locator, result.stdout)
        self.assertNotIn("retention:private-v1", result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report["kind"], "company_pack_review_bundle_verification")
        self.assertEqual(report["version"], "1.0")
        self.assertEqual(report["status"], "MATCH")
        self.assertIsNone(report["reason"])
        self.assertEqual(report["pack_id"], "verified-pack")
        self.assertEqual(
            report["saved_bundle"],
            {
                "sha256": hashlib.sha256(saved_bytes).hexdigest(),
                "bytes": len(saved_bytes),
                "bundle_digest": saved["bundle_digest"]["value"],
            },
        )
        self.assertEqual(report["actual_bundle_digest"], saved["bundle_digest"]["value"])
        self.assertEqual(report["binding_count"], 22)
        self.assertEqual(report["matched_bindings"], 22)
        self.assertEqual(report["mismatched_paths"], [])
        self.assertTrue(all(not value for value in report["claims"].values()))
        self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")

    def test_oversized_saved_bundle_is_rejected_before_matching_current_pack(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            pack, private_locator = self.create_ready_pack(parent)
            bundle_path = parent / "oversized-review-bundle.json"
            self.build_saved_bundle(pack, bundle_path)
            bundle_path.write_bytes(
                bundle_path.read_bytes() + b" " * (1024 * 1024)
            )
            result = self.run_verifier(bundle_path, pack)

        self.assertEqual(result.returncode, 1)
        self.assertNotIn(private_locator, result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "MISMATCH")
        self.assertEqual(report["reason"], "BUNDLE_READ_FAILED")
        self.assertIsNone(report["pack_id"])
        self.assertEqual(report["binding_count"], 0)
        self.assertEqual(report["matched_bindings"], 0)
        self.assertEqual(report["mismatched_paths"], [])

    def test_one_byte_pack_drift_reports_only_safe_mismatched_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            pack, private_locator = self.create_ready_pack(parent)
            bundle_path = parent / "review-bundle.json"
            self.build_saved_bundle(pack, bundle_path)
            changed = pack / "records" / "source-record.json"
            changed.write_bytes(changed.read_bytes() + b"\n")
            result = self.run_verifier(bundle_path, pack)

        self.assertEqual(result.returncode, 1)
        self.assertNotIn(private_locator, result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "MISMATCH")
        self.assertEqual(report["reason"], "BINDINGS_MISMATCH")
        self.assertEqual(report["matched_bindings"], 21)
        self.assertEqual(report["mismatched_paths"], ["records/source-record.json"])
        self.assertTrue(all(not value for value in report["claims"].values()))

    def test_tampered_saved_digest_is_invalid_before_pack_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            pack, _private_locator = self.create_ready_pack(parent)
            bundle_path = parent / "review-bundle.json"
            saved = self.build_saved_bundle(pack, bundle_path)
            saved["bundle_digest"]["value"] = "0" * 64
            bundle_path.write_text(json.dumps(saved), encoding="utf-8")
            result = self.run_verifier(bundle_path, pack)

        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "MISMATCH")
        self.assertEqual(report["reason"], "INVALID_BUNDLE_DIGEST")
        self.assertIsNone(report["pack_id"])
        self.assertEqual(report["binding_count"], 0)
        self.assertEqual(report["matched_bindings"], 0)
        self.assertEqual(report["mismatched_paths"], [])

    def test_tampered_source_check_metadata_cannot_match_valid_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            pack, _private_locator = self.create_ready_pack(parent)
            bundle_path = parent / "review-bundle.json"
            saved = self.build_saved_bundle(pack, bundle_path)
            saved["source_checks"]["customization"]["counts"]["review_required"] += 1
            bundle_path.write_text(json.dumps(saved), encoding="utf-8")
            result = self.run_verifier(bundle_path, pack)

        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "MISMATCH")
        self.assertEqual(report["reason"], "BUNDLE_METADATA_MISMATCH")
        self.assertEqual(report["mismatched_paths"], [])
        self.assertEqual(report["matched_bindings"], 22)

    def test_duplicate_json_key_is_invalid_even_when_last_value_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            pack, _private_locator = self.create_ready_pack(parent)
            bundle_path = parent / "review-bundle.json"
            self.build_saved_bundle(pack, bundle_path)
            original = bundle_path.read_text(encoding="utf-8")
            bundle_path.write_text('{"kind":"shadow-value",' + original[1:], encoding="utf-8")
            result = self.run_verifier(bundle_path, pack)

        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "MISMATCH")
        self.assertEqual(report["reason"], "INVALID_BUNDLE_FORMAT")
        self.assertIsNone(report["pack_id"])

    def test_deep_saved_json_is_a_non_reflective_format_refusal(self) -> None:
        marker = "SYNTHETIC_PRIVATE_BUNDLE_BODY"
        leaf = json.dumps(marker).encode("utf-8")
        payloads = {
            "shallow invalid": b'{"nested":' + leaf + b'}',
            "deep array": (
                b'{"nested":' + b'[' * 5000 + leaf + b']' * 5000 + b'}'
            ),
            "deep object": b'{"nested":' * 5000 + leaf + b'}' * 5000,
        }
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            bundle_path = parent / "synthetic-private-bundle.json"
            pack = parent / "unused-private-pack"
            for label, data in payloads.items():
                with self.subTest(payload=label):
                    self.assertLess(len(data), 1024 * 1024)
                    bundle_path.write_bytes(data)
                    result = self.run_verifier(bundle_path, pack)
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stderr, "")
                    self.assertEqual(len(result.stdout.splitlines()), 1)
                    self.assertNotIn(marker, result.stdout)
                    self.assertNotIn(str(bundle_path), result.stdout)
                    self.assertNotIn(str(pack), result.stdout)
                    report = json.loads(result.stdout)
                    self.assertEqual(report["status"], "MISMATCH")
                    self.assertEqual(report["reason"], "INVALID_BUNDLE_FORMAT")
                    self.assertIsNone(report["pack_id"])
                    self.assertEqual(report["binding_count"], 0)
                    self.assertEqual(report["matched_bindings"], 0)
                    self.assertEqual(report["mismatched_paths"], [])
                    self.assertTrue(
                        all(value is False for value in report["claims"].values())
                    )
                    self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")
                    self.assertEqual(bundle_path.read_bytes(), data)
                    self.assertFalse(pack.exists())

    def test_pack_not_ready_is_refused_without_binding_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            ready_pack, _private_locator = self.create_ready_pack(parent)
            bundle_path = parent / "review-bundle.json"
            self.build_saved_bundle(ready_pack, bundle_path)
            incomplete = parent / "incomplete-pack"
            creation = subprocess.run(
                [sys.executable, str(CREATOR), "incomplete-pack", str(incomplete)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(creation.returncode, 0, creation.stdout)
            result = self.run_verifier(bundle_path, incomplete)

        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "MISMATCH")
        self.assertEqual(report["reason"], "PACK_NOT_REVIEW_READY")
        self.assertIsNone(report["actual_bundle_digest"])
        self.assertEqual(report["matched_bindings"], 0)

    def test_verification_is_deterministic_for_unchanged_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            pack, _private_locator = self.create_ready_pack(parent)
            bundle_path = parent / "review-bundle.json"
            self.build_saved_bundle(pack, bundle_path)
            first = self.run_verifier(bundle_path, pack)
            second = self.run_verifier(bundle_path, pack)

        self.assertEqual(first.returncode, 0, first.stdout)
        self.assertEqual(first.stdout, second.stdout)

    def test_verification_schema_has_closed_false_claims(self) -> None:
        schema = json.loads(
            (
                ROOT
                / "schemas"
                / "company-pack-review-bundle-verification.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(schema["properties"]["public_beta"]["const"], "NO_GO_UNPUBLISHED")
        self.assertFalse(schema["properties"]["claims"]["additionalProperties"])
        self.assertEqual(
            set(schema["properties"]["status"]["enum"]),
            {"MATCH", "MISMATCH"},
        )

    def test_usage_error_returns_two_without_json_report(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VERIFIER)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("usage:", result.stderr)


if __name__ == "__main__":
    unittest.main()
