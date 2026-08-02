import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INITIALIZE = ROOT / "tools" / "initialize_attestation_nonce_store.py"
EVALUATE = ROOT / "tools" / "evaluate_compose_attestation_once.py"
POLICY_SCHEMA = ROOT / "schemas" / "compose-attestation-one-use-policy.schema.json"
EVALUATION_SCHEMA = ROOT / "schemas" / "compose-attestation-one-use-evaluation.schema.json"
INITIALIZATION_SCHEMA = ROOT / "schemas" / "attestation-nonce-store-initialization.schema.json"
sys.path.insert(0, str(ROOT / "tests"))
import test_verify_compose_clean_install_migration_evidence_candidate as evidence_helpers  # noqa: E402
import test_verify_protected_compose_evidence_attestation as attestation_helpers  # noqa: E402


POLICY_CLAIMS = (
    "canonical_trust_policy_verified",
    "trusted_clock_source_verified",
    "nonce_store_continuity_verified",
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


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class ComposeAttestationOneUseEvaluationCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ssh_keygen = shutil.which("ssh-keygen")
        if cls.ssh_keygen is None:
            raise unittest.SkipTest("ssh-keygen is unavailable")

    def make_inputs(self, temporary: Path) -> dict[str, object]:
        temporary.mkdir(parents=True, exist_ok=True)
        helper = attestation_helpers.ProtectedComposeEvidenceAttestationCliTests(
            methodName="test_usage_error_returns_two_without_json"
        )
        helper.ssh_keygen = self.ssh_keygen
        inputs = helper.make_inputs(temporary)
        now = datetime.now(timezone.utc)

        evidence_path = Path(inputs["evidence"])
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["reported_at"] = iso(now - timedelta(seconds=60))
        evidence["evidence_candidate_sha256"] = evidence_helpers.canonical_sha256(
            {key: value for key, value in evidence.items() if key != "evidence_candidate_sha256"}
        )
        evidence_path.write_text(json.dumps(evidence, sort_keys=True), encoding="utf-8")

        attestation_path = Path(inputs["attestation"])
        attestation = dict(inputs["attestation_value"])
        attestation["issued_at"] = iso(now - timedelta(seconds=30))
        attestation["expires_at"] = iso(now + timedelta(seconds=600))
        attestation["evidence_file_sha256"] = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
        attestation_path.write_text(
            json.dumps(attestation, sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )
        Path(inputs["signature"]).unlink(missing_ok=True)
        signed = subprocess.run(
            [self.ssh_keygen, "-Y", "sign", "-f", str(temporary / "reviewer-key"), "-n", "kotodama-compose-evidence", str(attestation_path)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(signed.returncode, 0, signed.stdout + signed.stderr)

        store_id = hashlib.sha256(b"r18-private-store-id").hexdigest()
        store_path = temporary / "nonce-store.sqlite3"
        initialized = subprocess.run(
            [sys.executable, str(INITIALIZE), str(store_path), store_id],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(initialized.returncode, 0, initialized.stdout + initialized.stderr)
        self.assertEqual(json.loads(initialized.stdout)["status"], "INITIALIZED")

        policy = {
            "kind": "compose_attestation_one_use_policy",
            "version": "1.0",
            "status": "POLICY_CANDIDATE",
            "policy_id": "r18-local-protected-evaluation",
            "allowed_signers_file_sha256": hashlib.sha256(
                Path(inputs["allowed_signers"]).read_bytes()
            ).hexdigest(),
            "nonce_store_id_sha256": store_id,
            "required_namespace": "kotodama-compose-evidence",
            "required_signer_role": "independent_reviewer",
            "max_signed_window_seconds": 900,
            "max_report_to_signature_seconds": 300,
            "not_before": iso(now - timedelta(seconds=60)),
            "expires_at": iso(now + timedelta(hours=1)),
            "clock_source": "local_system_utc_untrusted",
            "claims": {claim: False for claim in POLICY_CLAIMS},
            "public_beta": "NO_GO_UNPUBLISHED",
        }
        policy_path = temporary / "policy.json"
        policy_path.write_text(
            json.dumps(policy, sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )
        inputs.update(
            {
                "policy": policy_path,
                "policy_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
                "store": store_path,
            }
        )
        return inputs

    def run_evaluate(self, inputs: dict[str, object]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self.evaluate_command(inputs),
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def evaluate_command(self, inputs: dict[str, object]) -> list[str]:
        return [
                sys.executable,
                str(EVALUATE),
                str(inputs["policy"]),
                str(inputs["policy_sha256"]),
                str(inputs["attestation"]),
                str(inputs["signature"]),
                str(inputs["evidence"]),
                str(inputs["candidate"]),
                str(inputs["preflight"]),
                str(inputs["allowed_signers"]),
                str(inputs["identity_file"]),
                str(inputs["store"]),
            ]

    def replace_policy(self, inputs: dict[str, object], **changes: object) -> None:
        path = Path(inputs["policy"])
        policy = json.loads(path.read_text(encoding="utf-8"))
        policy.update(changes)
        path.write_text(
            json.dumps(policy, sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )
        inputs["policy_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()

    def test_first_evaluation_reserves_nonce_and_second_evaluation_refuses_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inputs = self.make_inputs(Path(directory))
            first = self.run_evaluate(inputs)
            second = self.run_evaluate(inputs)

        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(first.stderr, "")
        first_report = json.loads(first.stdout)
        self.assertEqual(first_report["status"], "ONE_USE_SIGNATURE_AND_POLICY_MATCH")
        self.assertTrue(first_report["claims"]["external_policy_digest_match_verified"])
        self.assertTrue(first_report["claims"]["allowed_signers_file_binding_verified"])
        self.assertTrue(first_report["claims"]["nonce_store_identity_binding_verified"])
        self.assertEqual(
            first_report["input_bindings"]["nonce_store_id_sha256"],
            hashlib.sha256(b"r18-private-store-id").hexdigest(),
        )
        self.assertTrue(first_report["claims"]["atomic_nonce_reservation_verified"])
        self.assertTrue(first_report["claims"]["one_use_evaluation_recorded"])
        self.assertTrue(first_report["claims"]["local_system_clock_used"])
        for claim in POLICY_CLAIMS:
            self.assertFalse(first_report["claims"][claim])
        self.assertEqual(first_report["public_beta"], "NO_GO_UNPUBLISHED")

        self.assertEqual(second.returncode, 1)
        self.assertEqual(second.stderr, "")
        second_report = json.loads(second.stdout)
        self.assertEqual(second_report["status"], "REPLAY_REFUSED")
        self.assertTrue(second_report["claims"]["replay_detected_in_bound_store"])
        self.assertFalse(second_report["claims"]["atomic_nonce_reservation_verified"])
        self.assertNotIn(str(inputs["identity"]), first.stdout + second.stdout)

    def test_two_concurrent_evaluations_commit_exactly_one_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inputs = self.make_inputs(Path(directory))
            processes = [
                subprocess.Popen(
                    self.evaluate_command(inputs),
                    cwd=ROOT,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                for _ in range(2)
            ]
            results = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=30)
                results.append((process.returncode, json.loads(stdout), stderr))

        self.assertEqual(sorted(result[0] for result in results), [0, 1])
        self.assertEqual(
            sorted(result[1]["status"] for result in results),
            ["ONE_USE_SIGNATURE_AND_POLICY_MATCH", "REPLAY_REFUSED"],
        )
        self.assertTrue(all(result[2] == "" for result in results))

    def test_invalid_signature_does_not_consume_the_nonce(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inputs = self.make_inputs(Path(directory))
            attestation_path = Path(inputs["attestation"])
            valid_attestation = attestation_path.read_bytes()
            attestation_path.write_bytes(valid_attestation + b"\n")
            invalid = self.run_evaluate(inputs)
            attestation_path.write_bytes(valid_attestation)
            valid = self.run_evaluate(inputs)

        self.assertEqual(invalid.returncode, 1)
        invalid_report = json.loads(invalid.stdout)
        self.assertEqual(invalid_report["status"], "INVALID")
        self.assertIn("detached signature verification failed", invalid_report["errors"])
        self.assertFalse(invalid_report["claims"]["atomic_nonce_reservation_verified"])
        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
        self.assertEqual(json.loads(valid.stdout)["status"], "ONE_USE_SIGNATURE_AND_POLICY_MATCH")

    def test_wrong_external_policy_digest_does_not_consume_the_nonce(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inputs = self.make_inputs(Path(directory))
            expected = inputs["policy_sha256"]
            inputs["policy_sha256"] = "0" * 64
            invalid = self.run_evaluate(inputs)
            inputs["policy_sha256"] = expected
            valid = self.run_evaluate(inputs)

        self.assertEqual(invalid.returncode, 1)
        self.assertIn("external policy digest mismatch", json.loads(invalid.stdout)["errors"])
        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)

    def test_policy_trust_root_and_store_identity_drift_fail_closed(self) -> None:
        results = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trust_root = self.make_inputs(root / "trust-root")
            self.replace_policy(trust_root, allowed_signers_file_sha256="0" * 64)
            results.append((self.run_evaluate(trust_root), "allowed signers file binding mismatch"))

            store = self.make_inputs(root / "store")
            self.replace_policy(store, nonce_store_id_sha256="f" * 64)
            results.append((self.run_evaluate(store), "nonce store identity binding mismatch"))

        for result, expected_error in results:
            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "INVALID")
            self.assertIn(expected_error, report["errors"])
            self.assertTrue(all(not value for value in report["claims"].values()))

    def test_policy_clock_source_validity_and_stricter_limits_fail_closed(self) -> None:
        results = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clock = self.make_inputs(root / "clock")
            self.replace_policy(clock, clock_source="claimed-trusted-clock")
            results.append((self.run_evaluate(clock), "clock_source must remain local_system_utc_untrusted"))

            expired = self.make_inputs(root / "expired")
            self.replace_policy(
                expired,
                not_before="2000-01-01T00:00:00Z",
                expires_at="2000-01-02T00:00:00Z",
            )
            results.append((self.run_evaluate(expired), "local evaluation time is outside policy validity"))

            strict = self.make_inputs(root / "strict")
            self.replace_policy(strict, max_signed_window_seconds=60)
            results.append((self.run_evaluate(strict), "attestation signed window exceeds policy"))

        for result, expected_error in results:
            self.assertEqual(result.returncode, 1)
            self.assertIn(expected_error, json.loads(result.stdout)["errors"])

    def test_concurrent_initializers_create_exactly_one_new_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "new-store.sqlite3"
            store_id = hashlib.sha256(b"concurrent-store").hexdigest()
            command = [sys.executable, str(INITIALIZE), str(target), store_id]
            processes = [
                subprocess.Popen(
                    command,
                    cwd=ROOT,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                for _ in range(2)
            ]
            results = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=30)
                results.append((process.returncode, json.loads(stdout), stderr))

        self.assertEqual(sorted(result[0] for result in results), [0, 1])
        self.assertEqual(sum(result[1]["status"] == "INITIALIZED" for result in results), 1)
        self.assertTrue(all(result[2] == "" for result in results))

    def test_store_schema_drift_and_missing_store_fail_without_creating_a_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            drift = self.make_inputs(root / "drift")
            connection = sqlite3.connect(str(drift["store"]))
            try:
                connection.execute("CREATE TABLE unexpected(value TEXT)")
                connection.commit()
            finally:
                connection.close()
            drift_result = self.run_evaluate(drift)

            weakened = self.make_inputs(root / "weakened")
            connection = sqlite3.connect(str(weakened["store"]))
            try:
                connection.execute("DROP TABLE nonce_reservations")
                connection.execute(
                    "CREATE TABLE nonce_reservations ("
                    "nonce_sha256 TEXT, attestation_sha256 TEXT, policy_sha256 TEXT, "
                    "evidence_sha256 TEXT, signature_sha256 TEXT, allowed_signers_sha256 TEXT, "
                    "identity_file_sha256 TEXT, evaluated_at TEXT, reservation_sha256 TEXT)"
                )
                connection.commit()
            finally:
                connection.close()
            weakened_result = self.run_evaluate(weakened)

            unsafe_journal = self.make_inputs(root / "unsafe-journal")
            connection = sqlite3.connect(str(unsafe_journal["store"]))
            try:
                connection.execute("PRAGMA journal_mode=WAL")
            finally:
                connection.close()
            unsafe_journal_result = self.run_evaluate(unsafe_journal)

            missing = self.make_inputs(root / "missing")
            missing_path = root / "missing" / "absent.sqlite3"
            Path(missing["store"]).unlink()
            missing["store"] = missing_path
            missing_result = self.run_evaluate(missing)

        self.assertEqual(drift_result.returncode, 1)
        self.assertIn("nonce store schema is invalid", json.loads(drift_result.stdout)["errors"])
        self.assertEqual(weakened_result.returncode, 1)
        self.assertIn("nonce store schema is invalid", json.loads(weakened_result.stdout)["errors"])
        self.assertEqual(unsafe_journal_result.returncode, 1)
        self.assertIn(
            "nonce store journal mode is invalid",
            json.loads(unsafe_journal_result.stdout)["errors"],
        )
        self.assertEqual(missing_result.returncode, 1)
        self.assertFalse(missing_path.exists())

    def test_initializer_refuses_overwrite_invalid_id_and_usage(self) -> None:
        private_marker = "private-existing-bytes-must-not-leak"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "existing.sqlite3"
            existing.write_text(private_marker, encoding="utf-8")
            refused = subprocess.run(
                [sys.executable, str(INITIALIZE), str(existing), "a" * 64],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            invalid_target = root / "invalid.sqlite3"
            invalid = subprocess.run(
                [sys.executable, str(INITIALIZE), str(invalid_target), "not-a-digest"],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            usage = subprocess.run(
                [sys.executable, str(INITIALIZE)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            existing_after = existing.read_text(encoding="utf-8")
            invalid_exists = invalid_target.exists()

        self.assertEqual(refused.returncode, 1)
        self.assertEqual(json.loads(refused.stdout)["status"], "REFUSED")
        self.assertNotIn(private_marker, refused.stdout)
        self.assertEqual(existing_after, private_marker)
        self.assertEqual(invalid.returncode, 1)
        self.assertFalse(invalid_exists)
        self.assertEqual(usage.returncode, 2)
        self.assertEqual(usage.stdout, "")
        self.assertIn("usage:", usage.stderr)

    def test_policy_duplicate_unknown_nonfinite_and_overclaim_are_safe_refusals(self) -> None:
        private_marker = "private-policy-marker-must-not-leak"
        results = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unknown = self.make_inputs(root / "unknown")
            policy_path = Path(unknown["policy"])
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            policy[private_marker] = private_marker
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            unknown["policy_sha256"] = hashlib.sha256(policy_path.read_bytes()).hexdigest()
            results.append(self.run_evaluate(unknown))

            duplicate = self.make_inputs(root / "duplicate")
            policy_path = Path(duplicate["policy"])
            original = policy_path.read_text(encoding="utf-8")
            policy_path.write_text('{"kind":"shadow",' + original.lstrip()[1:], encoding="utf-8")
            duplicate["policy_sha256"] = hashlib.sha256(policy_path.read_bytes()).hexdigest()
            results.append(self.run_evaluate(duplicate))

            nonfinite = self.make_inputs(root / "nonfinite")
            policy_path = Path(nonfinite["policy"])
            policy_path.write_text('{"kind":NaN}', encoding="utf-8")
            nonfinite["policy_sha256"] = hashlib.sha256(policy_path.read_bytes()).hexdigest()
            results.append(self.run_evaluate(nonfinite))

            overclaim = self.make_inputs(root / "overclaim")
            policy_path = Path(overclaim["policy"])
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            policy["claims"]["trusted_clock_source_verified"] = True
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            overclaim["policy_sha256"] = hashlib.sha256(policy_path.read_bytes()).hexdigest()
            results.append(self.run_evaluate(overclaim))

        for result in results:
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["status"], "INVALID")
            self.assertNotIn(private_marker, result.stdout)

    def test_r18_schemas_are_closed_and_terminal_claims_remain_false(self) -> None:
        policy_schema = json.loads(POLICY_SCHEMA.read_text(encoding="utf-8"))
        evaluation_schema = json.loads(EVALUATION_SCHEMA.read_text(encoding="utf-8"))
        initialization_schema = json.loads(INITIALIZATION_SCHEMA.read_text(encoding="utf-8"))

        self.assertFalse(policy_schema["additionalProperties"])
        self.assertEqual(policy_schema["properties"]["clock_source"]["const"], "local_system_utc_untrusted")
        self.assertEqual(policy_schema["properties"]["public_beta"]["const"], "NO_GO_UNPUBLISHED")
        for definition in policy_schema["properties"]["claims"]["properties"].values():
            self.assertIs(definition["const"], False)
        self.assertFalse(evaluation_schema["additionalProperties"])
        self.assertEqual(len(evaluation_schema["allOf"]), 3)
        self.assertEqual(
            evaluation_schema["properties"]["claims"]["properties"]["trusted_clock_source_verified"]["const"],
            False,
        )
        self.assertEqual(evaluation_schema["properties"]["public_beta"]["const"], "NO_GO_UNPUBLISHED")
        self.assertFalse(initialization_schema["additionalProperties"])
        self.assertEqual(initialization_schema["properties"]["public_beta"]["const"], "NO_GO_UNPUBLISHED")

    def test_evaluator_usage_error_returns_two_without_json(self) -> None:
        result = subprocess.run(
            [sys.executable, str(EVALUATE)],
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
