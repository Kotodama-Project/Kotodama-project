from __future__ import annotations

import base64
import hashlib
import importlib.util
import pathlib
import tempfile
import unittest


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
            report = MODULE.verify_artifact(metadata_for(artifact), artifact_path)
        self.assertEqual("PASS", report["status"])
        self.assertTrue(report["npm_integrity_verified"])
        self.assertTrue(report["npm_shasum_verified"])
        self.assertTrue(report["slsa_subject_digest_verified"])
        self.assertFalse(report["slsa_attestation_signature_verified"])

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
