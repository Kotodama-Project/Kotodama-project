from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "verify_wrangler_artifact.py"
SPEC = importlib.util.spec_from_file_location("verify_wrangler_artifact", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def metadata_for(value: bytes) -> dict[str, str]:
    sha512 = hashlib.sha512(value).digest()
    return {
        **MODULE.EXPECTED_IDENTITY,
        "npm_integrity": "sha512-" + base64.b64encode(sha512).decode("ascii"),
        "npm_shasum": hashlib.sha1(value, usedforsecurity=False).hexdigest(),
        "slsa_subject_sha512": sha512.hex(),
    }


class WranglerArtifactIntegrityTests(unittest.TestCase):
    def test_matching_npm_and_slsa_digests_pass(self) -> None:
        artifact = b"synthetic wrangler archive bytes"
        with tempfile.TemporaryDirectory() as temporary:
            artifact_path = pathlib.Path(temporary) / "wrangler.tgz"
            artifact_path.write_bytes(artifact)
            metadata_path = pathlib.Path(temporary) / "wrangler-integrity.json"
            metadata_path.write_text(json.dumps(metadata_for(artifact)), encoding="utf-8")
            self.assertEqual(MODULE.REQUIRED_FIELDS, set(MODULE.load_metadata(metadata_path)))
            report = MODULE.verify_artifact(MODULE.load_metadata(metadata_path), artifact_path)
        self.assertEqual("PASS", report["status"])
        self.assertTrue(report["npm_integrity_verified"])
        self.assertTrue(report["npm_shasum_verified"])
        self.assertTrue(report["slsa_subject_digest_verified"])
        self.assertFalse(report["slsa_attestation_signature_verified"])

    def test_metadata_loader_refuses_non_exact_shape_and_identity(self) -> None:
        artifact = b"synthetic shape fixture"
        valid = metadata_for(artifact)
        missing = dict(valid)
        del missing["npm_integrity"]
        with tempfile.TemporaryDirectory() as temporary:
            metadata_path = pathlib.Path(temporary) / "metadata.json"
            for value in (None, [], "private-shape-marker", missing,
                          {**valid, "extra": "private-shape-marker"}):
                with self.subTest(shape=type(value).__name__):
                    metadata_path.write_text(json.dumps(value), encoding="utf-8")
                    with self.assertRaisesRegex(MODULE.WranglerIntegrityViolation, "^Wrangler metadata shape is not exact$"):
                        MODULE.load_metadata(metadata_path)
            for field in MODULE.EXPECTED_IDENTITY:
                with self.subTest(identity=field):
                    metadata_path.write_text(json.dumps({**valid, field: "unreviewed-identity"}), encoding="utf-8")
                    with self.assertRaisesRegex(MODULE.WranglerIntegrityViolation, "^Wrangler metadata identity mismatch: " + field + "$"):
                        MODULE.validate_identity(MODULE.load_metadata(metadata_path))

    def test_sparse_oversized_and_empty_artifacts_refuse_before_read(self) -> None:
        metadata = metadata_for(b"synthetic bounded artifact")
        with tempfile.TemporaryDirectory() as temporary:
            artifact_path = pathlib.Path(temporary) / "sparse-wrangler.tgz"
            for size in (0, MODULE.MAX_ARTIFACT_BYTES + 1):
                with self.subTest(size=size):
                    with artifact_path.open("wb") as stream:
                        stream.truncate(size)
                    self.assertEqual(size, artifact_path.stat().st_size)
                    with mock.patch.object(pathlib.Path, "open", side_effect=AssertionError("refused artifacts must not be read")):
                        with self.assertRaisesRegex(MODULE.WranglerIntegrityViolation, "^Wrangler artifact size is outside the trusted bound$"):
                            MODULE.verify_artifact(metadata, artifact_path)

    def test_cli_reports_content_integrity_and_exact_metadata_or_size_refusal(self) -> None:
        # Synthetic local bytes only: this is no download/provider/signature
        # provenance or archive execution claim.
        artifact = b"synthetic CLI integrity fixture"
        with tempfile.TemporaryDirectory() as temporary:
            artifact_path = pathlib.Path(temporary) / "wrangler.tgz"
            metadata_path = pathlib.Path(temporary) / "metadata.json"
            artifact_path.write_bytes(artifact)
            metadata = metadata_for(artifact)
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            command = [sys.executable, "-B", str(MODULE_PATH), "--metadata", str(metadata_path),
                       "--artifact", str(artifact_path)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["artifact_bytes"], len(artifact))
            self.assertEqual(report["artifact_sha512"], hashlib.sha512(artifact).hexdigest())
            for claim in ("npm_integrity_verified", "npm_shasum_verified", "slsa_subject_digest_verified"):
                self.assertIs(report[claim], True)
            self.assertIs(report["slsa_attestation_signature_verified"], False)
            for mutation in ("shape", "oversized"):
                with self.subTest(mutation=mutation):
                    if mutation == "shape":
                        metadata_path.write_text(json.dumps({**metadata, "extra": "private-shape-marker"}), encoding="utf-8")
                        message = "Wrangler metadata shape is not exact"
                    else:
                        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
                        with artifact_path.open("wb") as stream:
                            stream.truncate(MODULE.MAX_ARTIFACT_BYTES + 1)
                        message = "Wrangler artifact size is outside the trusted bound"
                    result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stderr, "")
                    self.assertEqual(json.loads(result.stdout), {
                        "kind": "wrangler_artifact_integrity", "status": "REFUSED", "error": message,
                    })
                    self.assertNotIn("private-shape-marker", result.stdout)
                    self.assertNotIn("Traceback", result.stdout)

    def test_modified_archive_is_refused_before_execution(self) -> None:
        approved = b"approved archive"
        with tempfile.TemporaryDirectory() as temporary:
            artifact_path = pathlib.Path(temporary) / "wrangler.tgz"
            artifact_path.write_bytes(approved + b" tampered")
            with self.assertRaisesRegex(MODULE.WranglerIntegrityViolation, "npm integrity mismatch"):
                MODULE.verify_artifact(metadata_for(approved), artifact_path)

    def test_each_recorded_digest_is_independently_enforced(self) -> None:
        artifact = b"synthetic wrangler archive bytes"
        mutations = {
            "npm_integrity": ("sha512-invalid", "npm integrity mismatch"),
            "npm_shasum": ("0" * 40, "npm shasum mismatch"),
            "slsa_subject_sha512": ("0" * 128, "SLSA subject digest mismatch"),
        }
        with tempfile.TemporaryDirectory() as temporary:
            artifact_path = pathlib.Path(temporary) / "wrangler.tgz"
            artifact_path.write_bytes(artifact)
            for field, (value, message) in mutations.items():
                with self.subTest(field=field):
                    changed = metadata_for(artifact)
                    changed[field] = value
                    with self.assertRaisesRegex(MODULE.WranglerIntegrityViolation, message):
                        MODULE.verify_artifact(changed, artifact_path)

    def test_metadata_cannot_redirect_the_download_identity(self) -> None:
        artifact = b"synthetic wrangler archive bytes"
        changed = metadata_for(artifact)
        changed["npm_tarball"] = "https://untrusted.example.test/wrangler.tgz"
        with tempfile.TemporaryDirectory() as temporary:
            artifact_path = pathlib.Path(temporary) / "wrangler.tgz"
            artifact_path.write_bytes(artifact)
            with self.assertRaisesRegex(MODULE.WranglerIntegrityViolation, "npm_tarball"):
                MODULE.verify_artifact(changed, artifact_path)


if __name__ == "__main__":
    unittest.main()
