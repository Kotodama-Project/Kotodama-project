import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CREATE = ROOT / "tools" / "create_attestation_nonce_store_checkpoint.py"
VERIFY = ROOT / "tools" / "verify_attestation_nonce_store_checkpoint.py"
CHECKPOINT_SCHEMA = ROOT / "schemas" / "attestation-nonce-store-checkpoint.schema.json"
CREATION_SCHEMA = ROOT / "schemas" / "attestation-nonce-store-checkpoint-creation.schema.json"
VERIFICATION_SCHEMA = ROOT / "schemas" / "attestation-nonce-store-checkpoint-verification.schema.json"
sys.path.insert(0, str(ROOT / "tests"))
import test_evaluate_compose_attestation_once as r18_helpers  # noqa: E402
sys.path.insert(0, str(ROOT / "tools"))
import create_attestation_nonce_store_checkpoint as checkpoint_tool  # noqa: E402


class AttestationNonceStoreCheckpointCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ssh_keygen = shutil.which("ssh-keygen")
        if cls.ssh_keygen is None:
            raise unittest.SkipTest("ssh-keygen is unavailable")

    def make_r18_inputs(self, temporary: Path) -> dict[str, object]:
        helper = r18_helpers.ComposeAttestationOneUseEvaluationCliTests(
            methodName="test_evaluator_usage_error_returns_two_without_json"
        )
        helper.ssh_keygen = self.ssh_keygen
        inputs = helper.make_inputs(temporary)
        evaluated = helper.run_evaluate(inputs)
        self.assertEqual(evaluated.returncode, 0, evaluated.stdout + evaluated.stderr)
        return inputs

    def create_checkpoint(
        self,
        inputs: dict[str, object],
        output: Path,
        parent: str | Path = "GENESIS",
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(CREATE),
                str(inputs["store"]),
                str(parent),
                str(inputs["allowed_signers"]),
                str(inputs["identity_file"]),
                "--output",
                str(output),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def sign_checkpoint(self, checkpoint: Path, key: Path) -> Path:
        signature = Path(str(checkpoint) + ".sig")
        signature.unlink(missing_ok=True)
        signed = subprocess.run(
            [
                self.ssh_keygen,
                "-Y",
                "sign",
                "-f",
                str(key),
                "-n",
                "kotodama-nonce-store-checkpoint",
                str(checkpoint),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(signed.returncode, 0, signed.stdout + signed.stderr)
        return signature

    def verify_checkpoint(
        self,
        inputs: dict[str, object],
        checkpoint: Path,
        signature: Path,
        parent: str | Path = "GENESIS",
        parent_signature: str | Path = "GENESIS",
        expected_parent_sha256: str = "GENESIS",
        expected_current_sha256: str | None = None,
        store: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(VERIFY),
                str(checkpoint),
                str(signature),
                str(store or inputs["store"]),
                str(inputs["allowed_signers"]),
                str(inputs["identity_file"]),
                expected_current_sha256
                or hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                str(parent),
                str(parent_signature),
                expected_parent_sha256,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def add_reservation(self, inputs: dict[str, object], marker: bytes) -> None:
        attestation_path = Path(inputs["attestation"])
        attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
        attestation["nonce_sha256"] = hashlib.sha256(marker).hexdigest()
        attestation_path.write_text(
            json.dumps(attestation, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        signature = Path(inputs["signature"])
        signature.unlink(missing_ok=True)
        signed = subprocess.run(
            [
                self.ssh_keygen,
                "-Y",
                "sign",
                "-f",
                str(attestation_path.parent / "reviewer-key"),
                "-n",
                "kotodama-compose-evidence",
                str(attestation_path),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(signed.returncode, 0, signed.stdout + signed.stderr)
        evaluated = r18_helpers.ComposeAttestationOneUseEvaluationCliTests(
            methodName="test_evaluator_usage_error_returns_two_without_json"
        )
        evaluated.ssh_keygen = self.ssh_keygen
        result = evaluated.run_evaluate(inputs)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def checkpoint_value(self, path: Path) -> dict[str, object]:
        return json.loads(path.read_text(encoding="utf-8"))

    def test_signed_genesis_checkpoint_matches_the_exact_private_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            inputs = self.make_r18_inputs(temporary)
            checkpoint = temporary / "genesis-checkpoint.json"
            created = self.create_checkpoint(inputs, checkpoint)
            signature = self.sign_checkpoint(checkpoint, temporary / "reviewer-key")
            verified = self.verify_checkpoint(inputs, checkpoint, signature)

        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        self.assertEqual(json.loads(created.stdout)["status"], "CHECKPOINT_CREATED")
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        self.assertEqual(verified.stderr, "")
        report = json.loads(verified.stdout)
        self.assertEqual(report["status"], "SIGNED_GENESIS_CHECKPOINT_STORE_MATCH")
        for claim in (
            "supplied_current_checkpoint_digest_match_verified",
            "current_checkpoint_signature_verified",
            "allowed_signer_verified",
            "signer_identity_binding_verified",
            "checkpoint_chain_self_digest_verified",
            "store_matches_checkpoint_verified",
            "genesis_parent_binding_verified",
        ):
            self.assertTrue(report["claims"][claim])
        for claim in (
            "supplied_parent_checkpoint_digest_match_verified",
            "immediate_parent_signature_verified",
            "one_link_append_only_extension_verified",
            "external_anchor_authority_verified",
            "trusted_clock_source_verified",
            "store_continuity_verified",
            "restore_execution_verified",
            "current_truth_changed",
            "final_human_go",
            "public_beta_go",
        ):
            self.assertFalse(report["claims"][claim])
        self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")
        self.assertNotIn(str(inputs["identity"]), created.stdout + verified.stdout)

    def test_signed_successor_proves_one_link_extension_but_not_global_continuity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            inputs = self.make_r18_inputs(temporary)
            genesis = temporary / "genesis.json"
            self.assertEqual(self.create_checkpoint(inputs, genesis).returncode, 0)
            genesis_signature = self.sign_checkpoint(genesis, temporary / "reviewer-key")
            self.add_reservation(inputs, b"r19-second-reservation")
            successor = temporary / "successor.json"
            created = self.create_checkpoint(inputs, successor, genesis)
            successor_signature = self.sign_checkpoint(successor, temporary / "reviewer-key")
            verified = self.verify_checkpoint(
                inputs,
                successor,
                successor_signature,
                genesis,
                genesis_signature,
                hashlib.sha256(genesis.read_bytes()).hexdigest(),
            )

        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        report = json.loads(verified.stdout)
        self.assertEqual(report["status"], "SIGNED_SUCCESSOR_CHECKPOINT_STORE_MATCH")
        for claim in (
            "supplied_current_checkpoint_digest_match_verified",
            "current_checkpoint_signature_verified",
            "allowed_signer_verified",
            "signer_identity_binding_verified",
            "checkpoint_chain_self_digest_verified",
            "store_matches_checkpoint_verified",
            "supplied_parent_checkpoint_digest_match_verified",
            "immediate_parent_signature_verified",
            "one_link_append_only_extension_verified",
        ):
            self.assertTrue(report["claims"][claim])
        self.assertFalse(report["claims"]["genesis_parent_binding_verified"])
        for claim in (
            "external_anchor_authority_verified",
            "trusted_clock_source_verified",
            "store_continuity_verified",
            "restore_execution_verified",
            "promotion_verified",
            "current_truth_changed",
            "final_human_go",
            "public_beta_go",
        ):
            self.assertFalse(report["claims"][claim])

    def test_rollback_store_and_parent_missing_from_store_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            inputs = self.make_r18_inputs(temporary)
            genesis = temporary / "genesis.json"
            self.assertEqual(self.create_checkpoint(inputs, genesis).returncode, 0)
            genesis_signature = self.sign_checkpoint(genesis, temporary / "reviewer-key")
            rollback_store = temporary / "rollback.sqlite3"
            source = sqlite3.connect(str(inputs["store"]))
            target = sqlite3.connect(str(rollback_store))
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
            self.add_reservation(inputs, b"r19-second-reservation")
            successor = temporary / "successor.json"
            self.assertEqual(self.create_checkpoint(inputs, successor, genesis).returncode, 0)
            successor_signature = self.sign_checkpoint(successor, temporary / "reviewer-key")
            rolled_back_inputs = dict(inputs)
            rolled_back_inputs["store"] = rollback_store
            rollback_verify = self.verify_checkpoint(
                rolled_back_inputs,
                successor,
                successor_signature,
                genesis,
                genesis_signature,
                hashlib.sha256(genesis.read_bytes()).hexdigest(),
            )
            replacement_store = temporary / "same-count-replacement.sqlite3"
            source = sqlite3.connect(str(inputs["store"]))
            target = sqlite3.connect(str(replacement_store))
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
            connection = sqlite3.connect(str(replacement_store))
            try:
                row = connection.execute(
                    "SELECT nonce_sha256, attestation_sha256, policy_sha256, evidence_sha256, "
                    "signature_sha256, allowed_signers_sha256, identity_file_sha256, "
                    "evaluated_at FROM nonce_reservations ORDER BY nonce_sha256 LIMIT 1"
                ).fetchone()
                self.assertIsNotNone(row)
                replacement = list(row)
                replacement[0] = hashlib.sha256(b"r19-same-count-replacement").hexdigest()
                replacement_digest = hashlib.sha256(
                    "\n".join(replacement).encode("utf-8")
                ).hexdigest()
                connection.execute(
                    "UPDATE nonce_reservations SET nonce_sha256=?, reservation_sha256=? "
                    "WHERE nonce_sha256=?",
                    (replacement[0], replacement_digest, row[0]),
                )
                connection.commit()
            finally:
                connection.close()
            replacement_verify = self.verify_checkpoint(
                inputs,
                successor,
                successor_signature,
                genesis,
                genesis_signature,
                hashlib.sha256(genesis.read_bytes()).hexdigest(),
                store=replacement_store,
            )
            missing_parent_output = temporary / "must-not-exist.json"
            missing_parent = self.create_checkpoint(
                rolled_back_inputs, missing_parent_output, successor
            )

        self.assertEqual(rollback_verify.returncode, 1)
        self.assertIn(
            "store snapshot does not match checkpoint",
            json.loads(rollback_verify.stdout)["errors"],
        )
        self.assertEqual(replacement_verify.returncode, 1)
        self.assertIn(
            "store snapshot does not match checkpoint",
            json.loads(replacement_verify.stdout)["errors"],
        )
        self.assertEqual(missing_parent.returncode, 1)
        self.assertEqual(json.loads(missing_parent.stdout)["status"], "INVALID")
        self.assertFalse(missing_parent_output.exists())

    def test_digest_signature_parent_and_genesis_argument_tampering_fail_closed(self) -> None:
        results: list[tuple[subprocess.CompletedProcess[str], str]] = []
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            inputs = self.make_r18_inputs(temporary)
            genesis = temporary / "genesis.json"
            self.assertEqual(self.create_checkpoint(inputs, genesis).returncode, 0)
            genesis_signature = self.sign_checkpoint(genesis, temporary / "reviewer-key")
            self.add_reservation(inputs, b"r19-second-reservation")
            successor = temporary / "successor.json"
            self.assertEqual(self.create_checkpoint(inputs, successor, genesis).returncode, 0)
            successor_signature = self.sign_checkpoint(successor, temporary / "reviewer-key")
            results.append(
                (
                    self.verify_checkpoint(
                        inputs,
                        successor,
                        successor_signature,
                        genesis,
                        genesis_signature,
                        hashlib.sha256(genesis.read_bytes()).hexdigest(),
                        expected_current_sha256="0" * 64,
                    ),
                    "supplied current checkpoint digest mismatch",
                )
            )
            results.append(
                (
                    self.verify_checkpoint(
                        inputs,
                        successor,
                        successor_signature,
                        genesis,
                        genesis_signature,
                        "f" * 64,
                    ),
                    "supplied parent checkpoint digest mismatch",
                )
            )
            bad_signature = temporary / "bad-current.sig"
            bad_signature.write_bytes(b"not-an-openssh-signature\n")
            results.append(
                (
                    self.verify_checkpoint(
                        inputs,
                        successor,
                        bad_signature,
                        genesis,
                        genesis_signature,
                        hashlib.sha256(genesis.read_bytes()).hexdigest(),
                    ),
                    "current checkpoint signature verification failed",
                )
            )
            bad_parent_signature = temporary / "bad-parent.sig"
            bad_parent_signature.write_bytes(b"not-an-openssh-signature\n")
            results.append(
                (
                    self.verify_checkpoint(
                        inputs,
                        successor,
                        successor_signature,
                        genesis,
                        bad_parent_signature,
                        hashlib.sha256(genesis.read_bytes()).hexdigest(),
                    ),
                    "parent checkpoint signature verification failed",
                )
            )
            results.append(
                (
                    self.verify_checkpoint(
                        inputs,
                        successor,
                        successor_signature,
                        genesis,
                        "GENESIS",
                        hashlib.sha256(genesis.read_bytes()).hexdigest(),
                    ),
                    "successor parent inputs are incomplete",
                )
            )

        for result, expected in results:
            with self.subTest(expected=expected):
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual(report["status"], "INVALID")
                self.assertIn(expected, report["errors"])
                self.assertTrue(all(not value for value in report["claims"].values()))

    def test_checkpoint_shape_chain_and_private_input_tampering_are_safe_refusals(self) -> None:
        private_marker = "private-checkpoint-marker-must-not-leak"
        results: list[subprocess.CompletedProcess[str]] = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = self.make_r18_inputs(root / "base")
            checkpoint = root / "base" / "checkpoint.json"
            self.assertEqual(self.create_checkpoint(inputs, checkpoint).returncode, 0)
            signature = self.sign_checkpoint(checkpoint, root / "base" / "reviewer-key")
            original = self.checkpoint_value(checkpoint)

            unknown = root / "unknown.json"
            unknown_value = dict(original)
            unknown_value[private_marker] = private_marker
            unknown.write_text(json.dumps(unknown_value), encoding="utf-8")
            results.append(self.verify_checkpoint(inputs, unknown, signature))

            duplicate = root / "duplicate.json"
            raw = checkpoint.read_text(encoding="utf-8")
            duplicate.write_text('{"kind":"shadow",' + raw.lstrip()[1:], encoding="utf-8")
            results.append(self.verify_checkpoint(inputs, duplicate, signature))

            nonfinite = root / "nonfinite.json"
            nonfinite.write_text('{"kind":NaN}', encoding="utf-8")
            results.append(self.verify_checkpoint(inputs, nonfinite, signature))

            overclaim = root / "overclaim.json"
            overclaim_value = json.loads(json.dumps(original))
            overclaim_value["claims"]["store_continuity_verified"] = True
            overclaim.write_text(json.dumps(overclaim_value), encoding="utf-8")
            results.append(self.verify_checkpoint(inputs, overclaim, signature))

            bad_chain = root / "bad-chain.json"
            bad_chain_value = dict(original)
            bad_chain_value["created_at"] = "2026-08-03T00:00:00Z"
            bad_chain.write_text(json.dumps(bad_chain_value), encoding="utf-8")
            results.append(self.verify_checkpoint(inputs, bad_chain, signature))

        for result in results:
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["status"], "INVALID")
            self.assertNotIn(private_marker, result.stdout + result.stderr)

    def test_deep_checkpoint_and_parent_json_are_structured_refusals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            inputs = self.make_r18_inputs(temporary)
            deep = temporary / "deep-checkpoint.json"
            deep.write_bytes((b'{"nested":' * 5000) + b"0" + (b"}" * 5000))
            placeholder_signature = temporary / "placeholder.sig"
            placeholder_signature.write_bytes(b"not-a-private-signature-body")

            direct = self.verify_checkpoint(inputs, deep, placeholder_signature)
            refused_output = temporary / "must-not-exist.json"
            parent_creation = self.create_checkpoint(inputs, refused_output, deep)

            genesis = temporary / "genesis.json"
            self.assertEqual(self.create_checkpoint(inputs, genesis).returncode, 0)
            genesis_signature = self.sign_checkpoint(
                genesis, temporary / "reviewer-key"
            )
            self.add_reservation(inputs, b"deep-parent-regression")
            successor = temporary / "successor.json"
            self.assertEqual(
                self.create_checkpoint(inputs, successor, genesis).returncode, 0
            )
            successor_signature = self.sign_checkpoint(
                successor, temporary / "reviewer-key"
            )
            parent_verify = self.verify_checkpoint(
                inputs,
                successor,
                successor_signature,
                deep,
                genesis_signature,
                hashlib.sha256(deep.read_bytes()).hexdigest(),
            )
            refused_output_exists = refused_output.exists()

        for result in (direct, parent_creation, parent_verify):
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stderr, "")
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "INVALID")
            self.assertTrue(all(not value for value in report["claims"].values()))
        self.assertEqual(json.loads(direct.stdout)["errors"], ["input is invalid"])
        self.assertEqual(
            json.loads(parent_creation.stdout)["errors"],
            ["checkpoint creation failed"],
        )
        self.assertIn(
            "parent checkpoint input is invalid",
            json.loads(parent_verify.stdout)["errors"],
        )
        self.assertFalse(refused_output_exists)

    def test_allowed_signers_identity_and_store_corruption_fail_closed(self) -> None:
        results: list[tuple[subprocess.CompletedProcess[str], str | None]] = []
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            inputs = self.make_r18_inputs(temporary)
            checkpoint = temporary / "checkpoint.json"
            self.assertEqual(self.create_checkpoint(inputs, checkpoint).returncode, 0)
            signature = self.sign_checkpoint(checkpoint, temporary / "reviewer-key")

            changed_allowed = temporary / "changed-allowed-signers"
            changed_allowed.write_bytes(Path(inputs["allowed_signers"]).read_bytes() + b"\n")
            allowed_inputs = dict(inputs)
            allowed_inputs["allowed_signers"] = changed_allowed
            results.append(
                (
                    self.verify_checkpoint(allowed_inputs, checkpoint, signature),
                    "allowed signers binding mismatch",
                )
            )

            changed_identity = temporary / "changed-identity"
            changed_identity.write_text("different-reviewer", encoding="utf-8")
            identity_inputs = dict(inputs)
            identity_inputs["identity_file"] = changed_identity
            results.append(
                (
                    self.verify_checkpoint(identity_inputs, checkpoint, signature),
                    "signer identity binding mismatch",
                )
            )

            for name, mutation in (
                (
                    "bad-row.sqlite3",
                    "UPDATE nonce_reservations SET reservation_sha256='" + "0" * 64 + "'",
                ),
                ("extra-table.sqlite3", "CREATE TABLE unexpected(value TEXT)"),
            ):
                target_path = temporary / name
                source = sqlite3.connect(str(inputs["store"]))
                target = sqlite3.connect(str(target_path))
                try:
                    source.backup(target)
                    target.execute(mutation)
                    target.commit()
                finally:
                    target.close()
                    source.close()
                results.append(
                    (
                        self.verify_checkpoint(
                            inputs, checkpoint, signature, store=target_path
                        ),
                        None,
                    )
                )

        for result, expected in results:
            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "INVALID")
            if expected is not None:
                self.assertIn(expected, report["errors"])
            self.assertTrue(all(not value for value in report["claims"].values()))

    def test_store_snapshot_lease_blocks_commit_until_verdict_scope_exits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inputs = self.make_r18_inputs(Path(directory))
            store = Path(inputs["store"])
            writer_started = threading.Event()
            writer_finished = threading.Event()
            writer_errors: list[str] = []

            def writer() -> None:
                connection = sqlite3.connect(str(store), timeout=5)
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute(
                        "UPDATE store_metadata SET store_id_sha256=store_id_sha256 WHERE singleton=1"
                    )
                    writer_started.set()
                    connection.commit()
                except sqlite3.Error as error:
                    writer_errors.append(str(error))
                finally:
                    connection.close()
                    writer_finished.set()

            with checkpoint_tool.hold_store_snapshot(store) as (snapshot, errors):
                self.assertEqual(errors, [])
                self.assertIsNotNone(snapshot)
                thread = threading.Thread(target=writer)
                thread.start()
                self.assertTrue(writer_started.wait(timeout=2))
                time.sleep(0.2)
                self.assertFalse(writer_finished.is_set())
            thread.join(timeout=5)

        self.assertTrue(writer_finished.is_set())
        self.assertEqual(writer_errors, [])

    def test_generator_refuses_overwrite_and_usage_without_leaking_private_bytes(self) -> None:
        private_marker = "private-existing-checkpoint-must-not-leak"
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            inputs = self.make_r18_inputs(temporary)
            output = temporary / "existing.json"
            output.write_text(private_marker, encoding="utf-8")
            refused = self.create_checkpoint(inputs, output)
            after = output.read_text(encoding="utf-8")
            usage = subprocess.run(
                [sys.executable, str(CREATE)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(refused.returncode, 1)
        self.assertEqual(json.loads(refused.stdout)["status"], "INVALID")
        self.assertEqual(after, private_marker)
        self.assertNotIn(private_marker, refused.stdout + refused.stderr)
        self.assertEqual(usage.returncode, 2)
        self.assertEqual(usage.stdout, "")
        self.assertIn("usage:", usage.stderr)

    def test_r19_schemas_are_closed_bounded_and_keep_terminal_claims_false(self) -> None:
        checkpoint = json.loads(CHECKPOINT_SCHEMA.read_text(encoding="utf-8"))
        creation = json.loads(CREATION_SCHEMA.read_text(encoding="utf-8"))
        verification = json.loads(VERIFICATION_SCHEMA.read_text(encoding="utf-8"))

        self.assertFalse(checkpoint["additionalProperties"])
        self.assertEqual(
            checkpoint["properties"]["store_binding"]["properties"][
                "reservation_sha256s"
            ]["maxItems"],
            10_000,
        )
        self.assertTrue(
            checkpoint["properties"]["store_binding"]["properties"][
                "reservation_sha256s"
            ]["uniqueItems"]
        )
        for definition in checkpoint["properties"]["claims"]["properties"].values():
            self.assertIs(definition["const"], False)
        self.assertEqual(
            checkpoint["properties"]["public_beta"]["const"], "NO_GO_UNPUBLISHED"
        )

        self.assertFalse(creation["additionalProperties"])
        self.assertEqual(len(creation["allOf"]), 1)
        for name in (
            "checkpoint_signature_verified",
            "external_anchor_authority_verified",
            "trusted_clock_source_verified",
            "store_continuity_verified",
            "restore_execution_verified",
            "public_beta_go",
        ):
            self.assertIs(
                creation["properties"]["claims"]["properties"][name]["const"], False
            )

        self.assertFalse(verification["additionalProperties"])
        self.assertEqual(len(verification["allOf"]), 3)
        for name in (
            "external_anchor_authority_verified",
            "trusted_clock_source_verified",
            "store_continuity_verified",
            "restore_execution_verified",
            "promotion_verified",
            "current_truth_changed",
            "final_human_go",
            "public_beta_go",
        ):
            self.assertIs(
                verification["properties"]["claims"]["properties"][name]["const"],
                False,
            )
        for definition in verification["$defs"]["invalid_claims"]["properties"].values():
            self.assertIs(definition["const"], False)
        self.assertEqual(
            verification["properties"]["public_beta"]["const"],
            "NO_GO_UNPUBLISHED",
        )


if __name__ == "__main__":
    unittest.main()
