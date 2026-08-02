import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "tools" / "verify_protected_compose_evidence_attestation.py"
SCHEMA = ROOT / "schemas" / "protected-compose-evidence-attestation.schema.json"
LEDGER_SCHEMA = ROOT / "schemas" / "nonce-use-snapshot.schema.json"
sys.path.insert(0, str(ROOT / "tests"))
import test_verify_compose_clean_install_migration_evidence_candidate as evidence_helpers  # noqa: E402


CLAIMS = (
    "execution_authenticity_verified",
    "observation_freshness_verified",
    "observation_atomicity_verified",
    "current_daemon_reachable_verified",
    "current_local_image_available_verified",
    "clean_install_verified",
    "services_started_verified",
    "migrations_verified",
    "database_positive_checks_verified",
    "database_negative_checks_verified",
    "application_least_privilege_verified",
    "restart_verified",
    "rollback_verified",
    "backup_verified",
    "restore_verified",
    "promotion_verified",
    "current_truth_changed",
    "final_human_go",
    "public_beta_go",
)


class ProtectedComposeEvidenceAttestationCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ssh_keygen = shutil.which("ssh-keygen")
        if cls.ssh_keygen is None:
            raise unittest.SkipTest("ssh-keygen is unavailable")

    def make_inputs(self, temporary: Path) -> dict[str, Path | str | dict[str, object]]:
        temporary.mkdir(parents=True, exist_ok=True)
        helper = evidence_helpers.ComposeCleanInstallMigrationEvidenceCandidateVerifierCliTests(
            methodName="test_usage_error_returns_two_without_json"
        )
        candidate_path, preflight_path, candidate, preflight = helper.make_inputs(temporary)
        evidence = helper.make_evidence(candidate_path, preflight_path, candidate, preflight)
        evidence_path = temporary / "evidence.json"
        evidence_path.write_text(json.dumps(evidence, sort_keys=True), encoding="utf-8")

        identity = "independent-reviewer@example.invalid"
        identity_file = temporary / "signer-identity"
        identity_file.write_text(identity, encoding="utf-8")
        key_path = temporary / "reviewer-key"
        generated = subprocess.run(
            [self.ssh_keygen, "-q", "-t", "ed25519", "-N", "", "-C", "r17-test", "-f", str(key_path)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
        allowed_signers = temporary / "allowed-signers"
        allowed_signers.write_text(
            identity + " " + key_path.with_suffix(".pub").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        nonce = hashlib.sha256(b"r17-one-use-nonce").hexdigest()
        attestation = {
            "kind": "protected_compose_evidence_attestation",
            "version": "1.0",
            "status": "PROTECTED_ATTESTATION_CANDIDATE",
            "namespace": "kotodama-compose-evidence",
            "signer_identity_sha256": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
            "signer_role": "independent_reviewer",
            "issued_at": "2026-08-02T20:01:00Z",
            "expires_at": "2026-08-02T20:06:00Z",
            "nonce_sha256": nonce,
            "evidence_file_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
            "claims": {claim: False for claim in CLAIMS},
            "public_beta": "NO_GO_UNPUBLISHED",
        }
        attestation_path = temporary / "attestation.json"
        attestation_path.write_text(
            json.dumps(attestation, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        signed = subprocess.run(
            [self.ssh_keygen, "-Y", "sign", "-f", str(key_path), "-n", "kotodama-compose-evidence", str(attestation_path)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(signed.returncode, 0, signed.stdout + signed.stderr)
        ledger = {
            "kind": "nonce_use_snapshot",
            "version": "1.0",
            "snapshot_at": "2026-08-02T20:02:00Z",
            "used_nonce_sha256s": [],
        }
        ledger_path = temporary / "nonce-ledger.json"
        ledger_path.write_text(json.dumps(ledger, sort_keys=True), encoding="utf-8")
        return {
            "candidate": candidate_path,
            "preflight": preflight_path,
            "evidence": evidence_path,
            "attestation": attestation_path,
            "signature": Path(str(attestation_path) + ".sig"),
            "allowed_signers": allowed_signers,
            "ledger": ledger_path,
            "identity": identity,
            "identity_file": identity_file,
            "nonce": nonce,
            "attestation_value": attestation,
            "ledger_value": ledger,
        }

    def run_verify(self, inputs: dict[str, object], evaluated_at: str = "2026-08-02T20:02:00Z") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(VERIFY),
                str(inputs["attestation"]),
                str(inputs["signature"]),
                str(inputs["evidence"]),
                str(inputs["candidate"]),
                str(inputs["preflight"]),
                str(inputs["allowed_signers"]),
                str(inputs["ledger"]),
                str(inputs["identity_file"]),
                evaluated_at,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def resign(self, inputs: dict[str, object], temporary: Path) -> None:
        signature = Path(inputs["signature"])
        signature.unlink(missing_ok=True)
        result = subprocess.run(
            [self.ssh_keygen, "-Y", "sign", "-f", str(temporary / "reviewer-key"), "-n", "kotodama-compose-evidence", str(inputs["attestation"])],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_valid_signature_and_policy_match_is_point_in_time_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inputs = self.make_inputs(Path(directory))
            result = self.run_verify(inputs)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "SIGNATURE_AND_POLICY_MATCH_POINT_IN_TIME")
        for claim in (
            "attestation_bytes_signature_verified",
            "allowed_signer_verified",
            "signer_identity_binding_verified",
            "signer_role_policy_verified",
            "signed_evidence_binding_verified",
            "signed_evaluation_window_verified",
            "nonce_absent_in_snapshot_verified",
        ):
            self.assertTrue(report["claims"][claim])
        for claim in CLAIMS:
            self.assertFalse(report["claims"][claim])
        self.assertFalse(report["claims"]["atomic_nonce_reservation_verified"])
        self.assertFalse(report["claims"]["canonical_trust_root_pin_verified"])
        self.assertFalse(report["claims"]["evaluation_clock_source_verified"])
        self.assertFalse(report["claims"]["nonce_snapshot_authority_verified"])
        self.assertEqual(report["evaluated_at"], "2026-08-02T20:02:00Z")
        self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")
        self.assertNotIn(str(inputs["identity"]), result.stdout)

    def test_attestation_or_evidence_byte_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            inputs = self.make_inputs(temporary)
            attestation = dict(inputs["attestation_value"])
            attestation["expires_at"] = "2026-08-02T20:07:00Z"
            Path(inputs["attestation"]).write_text(json.dumps(attestation, sort_keys=True), encoding="utf-8")
            signature_result = self.run_verify(inputs)

            inputs = self.make_inputs(temporary / "evidence-drift")
            evidence_path = Path(inputs["evidence"])
            evidence_path.write_bytes(evidence_path.read_bytes() + b"\n")
            evidence_result = self.run_verify(inputs)

        self.assertEqual(signature_result.returncode, 1)
        self.assertIn("detached signature verification failed", json.loads(signature_result.stdout)["errors"])
        self.assertEqual(evidence_result.returncode, 1)
        self.assertIn("signed evidence file binding mismatch", json.loads(evidence_result.stdout)["errors"])

    def test_wrong_identity_and_non_reviewer_role_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            inputs = self.make_inputs(temporary)
            wrong_identity = dict(inputs)
            wrong_identity_file = temporary / "wrong-identity"
            wrong_identity_file.write_text("other@example.invalid", encoding="utf-8")
            wrong_identity["identity_file"] = wrong_identity_file
            identity_result = self.run_verify(wrong_identity)

            attestation = dict(inputs["attestation_value"])
            attestation["signer_role"] = "executor"
            attestation_path = Path(inputs["attestation"])
            attestation_path.write_text(
                json.dumps(attestation, sort_keys=True, separators=(",", ":")), encoding="utf-8"
            )
            self.resign(inputs, temporary)
            role_result = self.run_verify(inputs)

        self.assertEqual(identity_result.returncode, 1)
        self.assertIn("signer identity binding mismatch", json.loads(identity_result.stdout)["errors"])
        self.assertEqual(role_result.returncode, 1)
        self.assertIn("signer role must be independent_reviewer", json.loads(role_result.stdout)["errors"])

    def test_wrong_trust_root_fails_detached_signature_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            inputs = self.make_inputs(temporary)
            other_key = temporary / "other-key"
            generated = subprocess.run(
                [self.ssh_keygen, "-q", "-t", "ed25519", "-N", "", "-f", str(other_key)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            Path(inputs["allowed_signers"]).write_text(
                str(inputs["identity"]) + " " + other_key.with_suffix(".pub").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            result = self.run_verify(inputs)

        self.assertEqual(result.returncode, 1)
        self.assertIn("detached signature verification failed", json.loads(result.stdout)["errors"])

    def test_expired_future_and_oversized_signed_windows_fail_closed(self) -> None:
        results = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = [
                ("expired", "2026-08-02T20:07:00Z", None, "evaluation time is outside the signed window"),
                ("future", "2026-08-02T20:00:00Z", None, "evaluation time is outside the signed window"),
                ("wide", "2026-08-02T20:02:00Z", "2026-08-02T21:01:01Z", "signed window exceeds 900 seconds"),
            ]
            for name, evaluated_at, expires_at, expected in cases:
                temporary = root / name
                inputs = self.make_inputs(temporary)
                if expires_at is not None:
                    attestation = dict(inputs["attestation_value"])
                    attestation["expires_at"] = expires_at
                    Path(inputs["attestation"]).write_text(
                        json.dumps(attestation, sort_keys=True, separators=(",", ":")), encoding="utf-8"
                    )
                    self.resign(inputs, temporary)
                results.append((self.run_verify(inputs, evaluated_at), expected))

        for result, expected in results:
            self.assertEqual(result.returncode, 1)
            self.assertIn(expected, json.loads(result.stdout)["errors"])

    def test_used_nonce_stale_snapshot_and_future_snapshot_fail_closed(self) -> None:
        results = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = [
                ("used", "2026-08-02T20:02:00Z", None, "nonce is already present in supplied snapshot"),
                ("stale", "2026-08-02T20:00:59Z", [], "nonce snapshot is older than 60 seconds"),
                ("future", "2026-08-02T20:02:01Z", [], "nonce snapshot is later than evaluation time"),
            ]
            for name, snapshot_at, used, expected in cases:
                inputs = self.make_inputs(root / name)
                ledger = dict(inputs["ledger_value"])
                ledger["snapshot_at"] = snapshot_at
                ledger["used_nonce_sha256s"] = [inputs["nonce"]] if used is None else used
                Path(inputs["ledger"]).write_text(json.dumps(ledger, sort_keys=True), encoding="utf-8")
                results.append((self.run_verify(inputs), expected))

        for result, expected in results:
            self.assertEqual(result.returncode, 1)
            self.assertIn(expected, json.loads(result.stdout)["errors"])

    def test_duplicate_nonce_unknown_field_and_private_marker_are_safe_refusals(self) -> None:
        private_marker = "private-secret-marker-must-not-leak"
        results = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            duplicate = self.make_inputs(root / "duplicate")
            nonce = duplicate["nonce"]
            ledger_path = Path(duplicate["ledger"])
            ledger_path.write_text(
                json.dumps({"kind": "nonce_use_snapshot", "version": "1.0", "snapshot_at": "2026-08-02T20:02:00Z", "used_nonce_sha256s": [nonce, nonce]}),
                encoding="utf-8",
            )
            results.append(self.run_verify(duplicate))

            unknown = self.make_inputs(root / "unknown")
            ledger = dict(unknown["ledger_value"])
            ledger[private_marker] = private_marker
            Path(unknown["ledger"]).write_text(json.dumps(ledger), encoding="utf-8")
            results.append(self.run_verify(unknown))

            duplicate_json = self.make_inputs(root / "duplicate-json")
            Path(duplicate_json["ledger"]).write_text(
                '{"kind":"nonce_use_snapshot","kind":"shadow","version":"1.0","snapshot_at":"2026-08-02T20:02:00Z","used_nonce_sha256s":[]}',
                encoding="utf-8",
            )
            results.append(self.run_verify(duplicate_json))

        for result in results:
            self.assertEqual(result.returncode, 1)
            self.assertTrue(all(not value for value in json.loads(result.stdout)["claims"].values()))
            self.assertNotIn(private_marker, result.stdout)

    def test_schema_is_closed_and_live_claims_are_const_false(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        ledger_schema = json.loads(LEDGER_SCHEMA.read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["status"]["const"], "PROTECTED_ATTESTATION_CANDIDATE")
        self.assertEqual(schema["properties"]["signer_role"]["const"], "independent_reviewer")
        self.assertEqual(schema["properties"]["public_beta"]["const"], "NO_GO_UNPUBLISHED")
        for definition in schema["properties"]["claims"]["properties"].values():
            self.assertIs(definition["const"], False)
        self.assertFalse(ledger_schema["additionalProperties"])
        self.assertTrue(ledger_schema["properties"]["used_nonce_sha256s"]["uniqueItems"])

    def test_usage_error_returns_two_without_json(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VERIFY)], cwd=ROOT, text=True, capture_output=True, check=False
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("usage:", result.stderr)


if __name__ == "__main__":
    unittest.main()
