"""Synthetic cryptographic controls and fail-closed provenance policy tests."""
import base64
import copy
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import verify_pnpm_supply as supply


class PnpmSupplyVerifierTests(unittest.TestCase):
    def fixture(self):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            row = tarfile.TarInfo("package/package.json")
            body = b'{"name":"pnpm","version":"11.9.0"}'
            row.size = len(body)
            archive.addfile(row, io.BytesIO(body))
        artifact = stream.getvalue()
        policy = json.loads(supply.POLICY.read_text(encoding="utf-8"))
        policy.update(archive_sha512=hashlib.sha512(artifact).hexdigest(), archive_entries=1, archive_unpacked_bytes=len(body), registry_key_id="test-public-key")
        key = {"keyid": "test-public-key", "key": "public-key-fixture", "expires": None, "scheme": "ecdsa-sha2-nistp256", "keytype": "ecdsa-sha2-nistp256"}
        metadata = {"name": "pnpm", "version": "11.9.0", "dist": {"tarball": policy["tarball"], "integrity": "sha512-"+base64.b64encode(hashlib.sha512(artifact).digest()).decode(), "signatures": [{"keyid": "test-public-key", "sig": "signature-fixture"}]}}
        return policy, metadata, {"keys": [key]}, artifact

    def test_registry_binds_exact_package_artifact_and_key(self):
        policy, metadata, keys, artifact = self.fixture()
        now = dt.datetime(2026, 10, 8, tzinfo=dt.timezone.utc)
        result = supply.registry_message(metadata, keys, artifact, policy, now)
        self.assertTrue(result["message"].startswith("pnpm@11.9.0:sha512-"))
        controls = (
            ("name", lambda m, k: m.update(name="different")),
            ("version", lambda m, k: m.update(version="11.10.0")),
            ("origin", lambda m, k: m["dist"].update(tarball="https://example.invalid/archive")),
            ("integrity", lambda m, k: m["dist"].update(integrity="sha512-invalid")),
            ("duplicate key", lambda m, k: k["keys"].append(copy.deepcopy(k["keys"][0]))),
            ("unknown key", lambda m, k: k["keys"][0].update(keyid="other")),
            ("expired key", lambda m, k: k["keys"][0].update(expires="2026-10-07T00:00:00Z")),
            ("wrong algorithm", lambda m, k: k["keys"][0].update(scheme="rsa")),
            ("duplicate signature", lambda m, k: m["dist"]["signatures"].append(m["dist"]["signatures"][0])),
        )
        for label, change in controls:
            with self.subTest(label=label):
                m, k = copy.deepcopy(metadata), copy.deepcopy(keys)
                change(m, k)
                with self.assertRaises(supply.SupplyViolation):
                    supply.registry_message(m, k, artifact, policy, now)
        with self.assertRaises(supply.SupplyViolation):
            supply.registry_message(metadata, keys, artifact+b"changed", policy, now)

    def test_verified_statement_still_requires_exact_certificate_and_subject(self):
        policy = json.loads(supply.POLICY.read_text(encoding="utf-8"))
        certificate = {"subjectAlternativeName": policy["certificate_identity"], "issuer": policy["certificate_issuer"], "sourceRepositoryURI": "https://github.com/"+policy["source_repository"], "sourceRepositoryRef": policy["source_ref"], "sourceRepositoryDigest": policy["source_commit"], "buildSignerURI": policy["certificate_identity"], "runnerEnvironment": "github-hosted"}
        verified = {"signature": {"certificate": certificate}, "verifiedTimestamps": [{}], "statement": {"predicateType": policy["predicate_type"], "subject": [{"name": "pkg:npm/pnpm@11.9.0", "digest": {"sha512": policy["archive_sha512"]}}]}}
        supply.verify_statement([{"verificationResult": verified}], policy)
        for field in certificate:
            with self.subTest(field=field):
                candidate = copy.deepcopy(verified)
                candidate["signature"]["certificate"][field] = "different"
                with self.assertRaises(supply.SupplyViolation):
                    supply.verify_statement([{"verificationResult": candidate}], policy)
        candidate = copy.deepcopy(verified)
        candidate["statement"]["subject"][0]["digest"]["sha512"] = "0" * 128
        with self.assertRaises(supply.SupplyViolation):
            supply.verify_statement([{"verificationResult": candidate}], policy)

    def test_input_bounds_duplicates_and_provider_environment(self):
        with self.assertRaises(supply.SupplyViolation):
            supply.document(b'{"a":1,"a":2}')
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "input"
            path.write_bytes(b"12345")
            self.assertEqual(supply.read_regular(path, 5), b"12345")
            with self.assertRaises(supply.SupplyViolation):
                supply.read_regular(path, 4)
            with patch.dict(os.environ, {"GH_TOKEN": "synthetic", "GITHUB_TOKEN": "synthetic", "OPENAI_API_KEY": "synthetic", "NODE_OPTIONS": "injected"}):
                env = supply.child_environment(Path(temporary))
            self.assertFalse({"GH_TOKEN", "GITHUB_TOKEN", "OPENAI_API_KEY", "NODE_OPTIONS"} & set(env))

    @unittest.skipUnless(shutil.which("node"), "Node crypto toolchain")
    def test_real_ecdsa_positive_tampered_message_and_wrong_curve(self):
        generator = """const crypto=require('node:crypto');
const {privateKey,publicKey}=crypto.generateKeyPairSync('ec',{namedCurve:process.argv[2]});
const message='synthetic-package@1.0.0:sha512-synthetic';
console.log(JSON.stringify({message,key:publicKey.export({type:'spki',format:'der'}).toString('base64'),signature:crypto.sign('sha256',Buffer.from(message),privateKey).toString('base64')}));
"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sign.cjs"
            path.write_text(generator, encoding="utf-8")
            def signed(curve):
                result = subprocess.run([shutil.which("node"), str(path), curve], check=True, capture_output=True, timeout=10)
                return json.loads(result.stdout)
            def verify(value):
                result = subprocess.run([shutil.which("node"), str(supply.ROOT/"tools/npm_registry_signature.mjs")], input=json.dumps(value).encode(), capture_output=True, timeout=10)
                return json.loads(result.stdout)
            original = signed("prime256v1")
            self.assertTrue(verify(original)["verified"])
            modified = dict(original, message=original["message"]+"changed")
            self.assertFalse(verify(modified)["verified"])
            self.assertFalse(verify(signed("secp384r1"))["verified"])


if __name__ == "__main__":
    unittest.main()
