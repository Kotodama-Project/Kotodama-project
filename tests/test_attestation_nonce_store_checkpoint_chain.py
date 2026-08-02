import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CREATE_CHAIN = ROOT / "tools" / "create_attestation_nonce_store_checkpoint_chain_bundle.py"
VERIFY_CHAIN = ROOT / "tools" / "verify_attestation_nonce_store_checkpoint_chain.py"
BUNDLE_SCHEMA = ROOT / "schemas" / "attestation-nonce-store-checkpoint-chain-bundle.schema.json"
CREATION_SCHEMA = ROOT / "schemas" / "attestation-nonce-store-checkpoint-chain-bundle-creation.schema.json"
VERIFICATION_SCHEMA = ROOT / "schemas" / "attestation-nonce-store-checkpoint-chain-verification.schema.json"
sys.path.insert(0, str(ROOT / "tests"))
import test_attestation_nonce_store_checkpoint as r19_helpers  # noqa: E402
sys.path.insert(0, str(ROOT / "tools"))
import verify_protected_compose_evidence_attestation as protected_helpers  # noqa: E402
import create_attestation_nonce_store_checkpoint_chain_bundle as chain_tool  # noqa: E402


class AttestationNonceStoreCheckpointChainCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ssh_keygen = shutil.which("ssh-keygen")
        if cls.ssh_keygen is None:
            raise unittest.SkipTest("ssh-keygen is unavailable")

    def make_chain(self, temporary: Path, length: int = 3) -> dict[str, object]:
        helper = r19_helpers.AttestationNonceStoreCheckpointCliTests(
            methodName="test_signed_genesis_checkpoint_matches_the_exact_private_store"
        )
        helper.ssh_keygen = self.ssh_keygen
        inputs = helper.make_r18_inputs(temporary / "inputs")
        chain = temporary / "chain"
        chain.mkdir()
        checkpoints: list[Path] = []
        signatures: list[Path] = []
        store_snapshots: list[Path] = []
        parent: str | Path = "GENESIS"
        for sequence in range(length):
            if sequence:
                helper.add_reservation(inputs, f"r20-reservation-{sequence}".encode())
            checkpoint = chain / f"checkpoint-{sequence:06d}.json"
            created = helper.create_checkpoint(inputs, checkpoint, parent)
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            signature = helper.sign_checkpoint(
                checkpoint, temporary / "inputs" / "reviewer-key"
            )
            checkpoints.append(checkpoint)
            signatures.append(signature)
            store_snapshot = temporary / f"store-snapshot-{sequence:06d}.sqlite3"
            source = sqlite3.connect(str(inputs["store"]))
            target = sqlite3.connect(str(store_snapshot))
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
            store_snapshots.append(store_snapshot)
            parent = checkpoint
        restored_store = temporary / "supplied-restored-store.sqlite3"
        source = sqlite3.connect(str(inputs["store"]))
        target = sqlite3.connect(str(restored_store))
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        return {
            "helper": helper,
            "inputs": inputs,
            "chain": chain,
            "checkpoints": checkpoints,
            "signatures": signatures,
            "store_snapshots": store_snapshots,
            "restored_store": restored_store,
        }

    def create_bundle(
        self, case: dict[str, object], output: Path
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(CREATE_CHAIN),
                str(case["chain"]),
                "--output",
                str(output),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def verify_bundle(
        self,
        case: dict[str, object],
        bundle: Path,
        *,
        expected_bundle_sha256: str | None = None,
        store: Path | None = None,
        allowed_signers: Path | None = None,
        identity_file: Path | None = None,
        expected_ssh_keygen_sha256: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        inputs = case["inputs"]
        assert isinstance(inputs, dict)
        return subprocess.run(
            [
                sys.executable,
                str(VERIFY_CHAIN),
                str(bundle),
                expected_bundle_sha256
                or hashlib.sha256(bundle.read_bytes()).hexdigest(),
                str(store or case["restored_store"]),
                str(allowed_signers or inputs["allowed_signers"]),
                str(identity_file or inputs["identity_file"]),
                expected_ssh_keygen_sha256
                or hashlib.sha256(Path(self.ssh_keygen).read_bytes()).hexdigest(),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )

    def test_three_checkpoint_chain_and_supplied_store_are_logically_equivalent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            case = self.make_chain(temporary)
            bundle = temporary / "chain-bundle.json"
            created = self.create_bundle(case, bundle)
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            bundle_sha256 = hashlib.sha256(bundle.read_bytes()).hexdigest()
            # Verification is bound to the self-contained bundle, not a later
            # pathname re-open of the source directory.
            shutil.rmtree(Path(case["chain"]))
            verified = self.verify_bundle(case, bundle)

        creation = json.loads(created.stdout)
        self.assertEqual(creation["status"], "CHAIN_BUNDLE_CREATED")
        self.assertEqual(creation["checkpoint_count"], 3)
        self.assertEqual(creation["bundle_file_sha256"], bundle_sha256)
        self.assertNotIn("manifest_file_sha256", creation)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        self.assertEqual(verified.stderr, "")
        report = json.loads(verified.stdout)
        self.assertEqual(
            report["status"], "SIGNED_RECURSIVE_CHAIN_AND_STORE_EQUIVALENCE"
        )
        self.assertEqual(report["counts"]["checkpoints_verified"], 3)
        self.assertEqual(report["counts"]["parent_links_verified"], 2)
        self.assertEqual(
            report["input_bindings"]["bundle_file_sha256"],
            bundle_sha256,
        )
        self.assertNotIn("bundle_manifest_sha256", report["input_bindings"])
        for claim in (
            "supplied_bundle_digest_match_verified",
            "bundle_structure_verified",
            "all_checkpoint_digests_verified",
            "all_signature_digests_verified",
            "all_checkpoint_signatures_verified",
            "allowed_signer_verified",
            "signer_identity_binding_verified",
            "genesis_binding_verified",
            "recursive_parent_links_verified",
            "append_only_reservation_path_verified",
            "single_store_identity_verified",
            "supplied_store_logical_equivalence_verified",
            "ssh_keygen_binary_binding_verified",
        ):
            self.assertTrue(report["claims"][claim])
        for claim in (
            "external_anchor_authority_verified",
            "trusted_clock_source_verified",
            "authoritative_complete_history_verified",
            "parallel_branch_absence_verified",
            "key_rotation_verified",
            "store_continuity_verified",
            "backup_creation_verified",
            "restore_execution_verified",
            "promotion_verified",
            "current_truth_changed",
            "final_human_go",
            "public_beta_go",
            "ssh_keygen_vendor_authority_verified",
        ):
            self.assertFalse(report["claims"][claim])
        self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")
        inputs = case["inputs"]
        assert isinstance(inputs, dict)
        self.assertNotIn(str(inputs["identity"]), created.stdout + verified.stdout)

    def test_bundle_cannot_rebind_a_different_allowed_signers_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            case = self.make_chain(temporary)
            bundle = temporary / "chain-bundle.json"
            created = self.create_bundle(case, bundle)
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            inputs = case["inputs"]
            assert isinstance(inputs, dict)
            changed_allowed = temporary / "changed-allowed-signers"
            changed_allowed.write_bytes(
                Path(inputs["allowed_signers"]).read_bytes() + b"\n"
            )
            value = json.loads(bundle.read_text(encoding="utf-8"))
            value["signature_policy_binding"]["allowed_signers_file_sha256"] = (
                hashlib.sha256(changed_allowed.read_bytes()).hexdigest()
            )
            rebound = temporary / "rebound-bundle.json"
            rebound.write_text(json.dumps(value), encoding="utf-8")
            verified = self.verify_bundle(
                case, rebound, allowed_signers=changed_allowed
            )

        self.assertEqual(verified.returncode, 1)
        report = json.loads(verified.stdout)
        self.assertEqual(report["status"], "INVALID")
        self.assertIn("bundle signer policy does not match checkpoint chain", report["errors"])
        self.assertTrue(all(not value for value in report["claims"].values()))

    def test_boolean_sequence_cannot_alias_integer_zero_after_digest_rebinding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            case = self.make_chain(temporary)
            bundle = temporary / "chain-bundle.json"
            self.assertEqual(self.create_bundle(case, bundle).returncode, 0)
            value = json.loads(bundle.read_text(encoding="utf-8"))
            value["entries"][0]["sequence"] = False
            value["ordered_chain_sha256"] = chain_tool.ordered_chain_sha256(
                value["entries"]
            )
            rebound = temporary / "boolean-sequence-bundle.json"
            rebound.write_text(json.dumps(value), encoding="utf-8")
            verified = self.verify_bundle(case, rebound)

        self.assertEqual(verified.returncode, 1)
        report = json.loads(verified.stdout)
        self.assertEqual(report["status"], "INVALID")
        self.assertIn("entry 0 sequence mismatch", report["errors"])
        self.assertTrue(all(not value for value in report["claims"].values()))

    def test_rollback_and_same_count_replacement_do_not_match_current_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            case = self.make_chain(temporary)
            bundle = temporary / "chain-bundle.json"
            self.assertEqual(self.create_bundle(case, bundle).returncode, 0)
            snapshots = case["store_snapshots"]
            assert isinstance(snapshots, list)
            rollback = self.verify_bundle(case, bundle, store=snapshots[0])

            replacement = temporary / "same-count-replacement.sqlite3"
            source = sqlite3.connect(str(case["restored_store"]))
            target = sqlite3.connect(str(replacement))
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
            connection = sqlite3.connect(str(replacement))
            try:
                row = connection.execute(
                    "SELECT nonce_sha256, attestation_sha256, policy_sha256, evidence_sha256, "
                    "signature_sha256, allowed_signers_sha256, identity_file_sha256, "
                    "evaluated_at FROM nonce_reservations ORDER BY nonce_sha256 LIMIT 1"
                ).fetchone()
                self.assertIsNotNone(row)
                values = list(row)
                values[0] = hashlib.sha256(b"r20-same-count-replacement").hexdigest()
                replacement_digest = hashlib.sha256(
                    "\n".join(values).encode("utf-8")
                ).hexdigest()
                connection.execute(
                    "UPDATE nonce_reservations SET nonce_sha256=?, reservation_sha256=? "
                    "WHERE nonce_sha256=?",
                    (values[0], replacement_digest, row[0]),
                )
                connection.commit()
            finally:
                connection.close()
            replaced = self.verify_bundle(case, bundle, store=replacement)

        for result in (rollback, replaced):
            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "INVALID")
            self.assertIn(
                "supplied store does not match current checkpoint", report["errors"]
            )
            self.assertTrue(all(not value for value in report["claims"].values()))

    def test_bundle_creation_is_deterministic_new_file_only_and_strict_about_directory(self) -> None:
        private_marker = "private-chain-extra-must-not-leak"
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            case = self.make_chain(temporary)
            first = temporary / "first-bundle.json"
            second = temporary / "second-bundle.json"
            first_result = self.create_bundle(case, first)
            second_result = self.create_bundle(case, second)
            first_bytes = first.read_bytes()
            second_bytes = second.read_bytes()
            overwrite = self.create_bundle(case, first)
            first_after = first.read_bytes()

            extra = Path(case["chain"]) / private_marker
            extra.write_text(private_marker, encoding="utf-8")
            invalid_directory = self.create_bundle(
                case, temporary / "must-not-exist.json"
            )
            extra.unlink()

            checkpoints = case["checkpoints"]
            signatures = case["signatures"]
            assert isinstance(checkpoints, list) and isinstance(signatures, list)
            checkpoints[1].unlink()
            signatures[1].unlink()
            gap = self.create_bundle(case, temporary / "gap-must-not-exist.json")

            usage = subprocess.run(
                [sys.executable, str(CREATE_CHAIN)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(first_result.returncode, 0)
        self.assertEqual(second_result.returncode, 0)
        self.assertEqual(first_bytes, second_bytes)
        self.assertEqual(overwrite.returncode, 1)
        self.assertEqual(first_after, first_bytes)
        self.assertEqual(invalid_directory.returncode, 1)
        self.assertNotIn(private_marker, invalid_directory.stdout)
        self.assertEqual(gap.returncode, 1)
        self.assertEqual(usage.returncode, 2)
        self.assertEqual(usage.stdout, "")
        self.assertIn("usage:", usage.stderr)

    def test_bundle_digest_strict_json_and_signature_tamper_fail_closed(self) -> None:
        private_marker = "private-bundle-marker-must-not-leak"
        results: list[tuple[subprocess.CompletedProcess[str], str | None]] = []
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            case = self.make_chain(temporary)
            bundle = temporary / "chain-bundle.json"
            self.assertEqual(self.create_bundle(case, bundle).returncode, 0)
            results.append(
                (
                    self.verify_bundle(
                        case, bundle, expected_bundle_sha256="0" * 64
                    ),
                    "supplied bundle digest mismatch",
                )
            )
            original = bundle.read_text(encoding="utf-8")
            unknown_value = json.loads(original)
            unknown_value[private_marker] = private_marker
            unknown = temporary / "unknown.json"
            unknown.write_text(json.dumps(unknown_value), encoding="utf-8")
            results.append((self.verify_bundle(case, unknown), None))
            duplicate = temporary / "duplicate.json"
            duplicate.write_text(
                '{"kind":"shadow",' + original.lstrip()[1:], encoding="utf-8"
            )
            results.append((self.verify_bundle(case, duplicate), None))
            nonfinite = temporary / "nonfinite.json"
            nonfinite.write_text('{"kind":NaN}', encoding="utf-8")
            results.append((self.verify_bundle(case, nonfinite), None))
            overclaim_value = json.loads(original)
            overclaim_value["claims"]["restore_execution_verified"] = True
            overclaim = temporary / "overclaim.json"
            overclaim.write_text(json.dumps(overclaim_value), encoding="utf-8")
            results.append((self.verify_bundle(case, overclaim), None))
            malformed_entry_value = json.loads(original)
            malformed_entry_value["entries"][0] = "not-an-object"
            malformed_entry = temporary / "malformed-entry.json"
            malformed_entry.write_text(
                json.dumps(malformed_entry_value), encoding="utf-8"
            )
            results.append((self.verify_bundle(case, malformed_entry), None))

            signatures = case["signatures"]
            assert isinstance(signatures, list)
            signatures[1].write_bytes(b"not-an-openssh-signature\n")
            tampered_bundle = temporary / "tampered-signature-bundle.json"
            self.assertEqual(
                self.create_bundle(case, tampered_bundle).returncode, 0
            )
            results.append(
                (
                    self.verify_bundle(case, tampered_bundle),
                    "checkpoint 1 signature verification failed",
                )
            )

        for result, expected in results:
            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "INVALID")
            if expected is not None:
                self.assertIn(expected, report["errors"])
            self.assertTrue(all(not value for value in report["claims"].values()))
            self.assertNotIn(private_marker, result.stdout + result.stderr)

    def test_ssh_keygen_executable_is_pinned_and_bundle_type_errors_are_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            case = self.make_chain(temporary)
            bundle = temporary / "chain-bundle.json"
            self.assertEqual(self.create_bundle(case, bundle).returncode, 0)

            wrong_pin = self.verify_bundle(
                case, bundle, expected_ssh_keygen_sha256="0" * 64
            )

            stub_directory = temporary / "stub-bin"
            stub_directory.mkdir()
            if os.name == "nt":
                stub = stub_directory / "ssh-keygen.cmd"
                stub.write_text("@exit /b 0\n", encoding="utf-8")
            else:
                stub = stub_directory / "ssh-keygen"
                stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                stub.chmod(0o700)
            environment = os.environ.copy()
            environment["PATH"] = str(stub_directory) + os.pathsep + environment["PATH"]
            path_stub = self.verify_bundle(case, bundle, environment=environment)

            malformed_value = json.loads(bundle.read_text(encoding="utf-8"))
            malformed_value["signature_policy_binding"] = "not-an-object"
            malformed = temporary / "malformed-bundle.json"
            malformed.write_text(json.dumps(malformed_value), encoding="utf-8")
            malformed_result = self.verify_bundle(case, malformed)

        for result in (wrong_pin, path_stub):
            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertIn("ssh-keygen executable binding mismatch", report["errors"])
            self.assertTrue(all(not value for value in report["claims"].values()))
        self.assertEqual(malformed_result.returncode, 1)
        self.assertEqual(malformed_result.stderr, "")
        malformed_report = json.loads(malformed_result.stdout)
        self.assertEqual(malformed_report["status"], "INVALID")
        self.assertTrue(
            all(not value for value in malformed_report["claims"].values())
        )

    def test_individually_valid_but_wrong_parent_link_is_refused_by_bundle_builder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            case = self.make_chain(temporary, length=2)
            checkpoints = case["checkpoints"]
            signatures = case["signatures"]
            assert isinstance(checkpoints, list) and isinstance(signatures, list)
            child = json.loads(checkpoints[1].read_text(encoding="utf-8"))
            child["parent_binding"]["parent_checkpoint_file_sha256"] = "0" * 64
            child["checkpoint_chain_sha256"] = (
                r19_helpers.checkpoint_tool.checkpoint_chain_sha256(child)
            )
            checkpoints[1].write_text(
                json.dumps(child, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            inputs = case["inputs"]
            assert isinstance(inputs, dict)
            signatures[1].unlink(missing_ok=True)
            helper = case["helper"]
            assert isinstance(
                helper, r19_helpers.AttestationNonceStoreCheckpointCliTests
            )
            helper.sign_checkpoint(checkpoints[1], temporary / "inputs" / "reviewer-key")
            output = temporary / "must-not-exist.json"
            result = self.create_bundle(case, output)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["status"], "INVALID")
        self.assertFalse(output.exists())

    def test_aggregate_chain_byte_budget_is_enforced_before_json_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            chain = temporary / "chain"
            chain.mkdir()
            payload = b"{" + b" " * (2 * 1024 * 1024 - 1)
            for sequence in range(9):
                name = f"checkpoint-{sequence:06d}.json"
                (chain / name).write_bytes(payload)
                (chain / (name + ".sig")).write_bytes(b"x")
            case: dict[str, object] = {"chain": chain}
            output = temporary / "must-not-exist.json"
            result = self.create_bundle(case, output)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["status"], "INVALID")
        self.assertFalse(output.exists())

    def test_file_and_store_limits_apply_before_open_or_sqlite_query(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            oversized_input = temporary / "oversized-input"
            oversized_input.write_bytes(b"x" * 33)
            with mock.patch.object(protected_helpers.os, "open") as open_mock:
                with self.assertRaises(OSError):
                    protected_helpers.safe_read(oversized_input, maximum=32)
                open_mock.assert_not_called()

            oversized_store = temporary / "oversized-store.sqlite3"
            with oversized_store.open("wb") as output:
                output.truncate(r19_helpers.checkpoint_tool.MAX_NONCE_STORE_BYTES + 1)
            with mock.patch.object(
                r19_helpers.checkpoint_tool.sqlite3, "connect"
            ) as connect_mock:
                with r19_helpers.checkpoint_tool.hold_store_snapshot(
                    oversized_store
                ) as (snapshot, errors):
                    self.assertIsNone(snapshot)
                    self.assertTrue(errors)
                connect_mock.assert_not_called()

    def test_store_path_reopen_cannot_replace_the_opened_object_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            case = self.make_chain(temporary)
            snapshots = case["store_snapshots"]
            assert isinstance(snapshots, list)
            opened_store = snapshots[0]
            substituted_store = case["restored_store"]
            real_connect = sqlite3.connect
            calls = 0

            def connect_with_first_path_substituted(
                database: object, *args: object, **kwargs: object
            ) -> sqlite3.Connection:
                nonlocal calls
                calls += 1
                if calls == 1:
                    return real_connect(
                        Path(substituted_store).as_uri() + "?mode=ro",
                        *args,
                        **kwargs,
                    )
                return real_connect(database, *args, **kwargs)

            with mock.patch.object(
                r19_helpers.checkpoint_tool.sqlite3,
                "connect",
                side_effect=connect_with_first_path_substituted,
            ):
                with r19_helpers.checkpoint_tool.hold_store_snapshot(
                    opened_store
                ) as (snapshot, errors):
                    self.assertIsNone(snapshot)
                    self.assertIn(
                        "nonce store opened-object snapshot mismatch", errors
                    )

    def test_r20_schemas_are_closed_bounded_and_keep_authority_claims_false(self) -> None:
        bundle = json.loads(BUNDLE_SCHEMA.read_text(encoding="utf-8"))
        creation = json.loads(CREATION_SCHEMA.read_text(encoding="utf-8"))
        verification = json.loads(VERIFICATION_SCHEMA.read_text(encoding="utf-8"))

        self.assertFalse(bundle["additionalProperties"])
        self.assertEqual(bundle["properties"]["entries"]["maxItems"], 1024)
        self.assertTrue(bundle["properties"]["entries"]["uniqueItems"])
        for definition in bundle["properties"]["claims"]["properties"].values():
            self.assertIs(definition["const"], False)
        self.assertEqual(
            bundle["properties"]["public_beta"]["const"], "NO_GO_UNPUBLISHED"
        )

        self.assertFalse(creation["additionalProperties"])
        self.assertEqual(len(creation["allOf"]), 1)
        for name in (
            "checkpoint_signatures_verified",
            "external_anchor_authority_verified",
            "trusted_clock_source_verified",
            "authoritative_complete_history_verified",
            "parallel_branch_absence_verified",
            "key_rotation_verified",
            "store_continuity_verified",
            "backup_creation_verified",
            "restore_execution_verified",
            "public_beta_go",
        ):
            self.assertIs(
                creation["properties"]["claims"]["properties"][name]["const"], False
            )

        self.assertFalse(verification["additionalProperties"])
        self.assertEqual(len(verification["allOf"]), 1)
        for name in (
            "external_anchor_authority_verified",
            "trusted_clock_source_verified",
            "authoritative_complete_history_verified",
            "parallel_branch_absence_verified",
            "key_rotation_verified",
            "store_continuity_verified",
            "backup_creation_verified",
            "restore_execution_verified",
            "promotion_verified",
            "current_truth_changed",
            "final_human_go",
            "public_beta_go",
            "ssh_keygen_vendor_authority_verified",
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
