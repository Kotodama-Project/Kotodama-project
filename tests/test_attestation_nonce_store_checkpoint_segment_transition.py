import base64
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFY_TRANSITION = (
    ROOT
    / "tools"
    / "verify_attestation_nonce_store_checkpoint_segment_transition.py"
)
TRANSITION_SCHEMA = (
    ROOT
    / "schemas"
    / "attestation-nonce-store-checkpoint-segment-transition.schema.json"
)
VERIFICATION_SCHEMA = (
    ROOT
    / "schemas"
    / "attestation-nonce-store-checkpoint-segment-transition-verification.schema.json"
)
TRANSITION_NAMESPACE = "kotodama-nonce-store-checkpoint-segment-transition"
sys.path.insert(0, str(ROOT / "tests"))
import test_attestation_nonce_store_checkpoint_chain as r20_helpers  # noqa: E402


TRANSITION_SUCCESS_CLAIMS = {
    "transition_file_digest_match_verified",
    "prior_bundle_digest_match_verified",
    "prior_bundle_structure_verified",
    "prior_checkpoint_signatures_verified",
    "prior_head_binding_verified",
    "successor_checkpoint_digest_match_verified",
    "successor_checkpoint_signature_verified",
    "parent_link_verified",
    "store_identity_continuity_verified",
    "reservation_append_only_verified",
    "successor_store_match_verified",
    "transition_signature_verified",
    "prior_signer_policy_verified",
    "successor_signer_policy_verified",
    "transition_reviewer_policy_verified",
    "signer_policy_mode_verified",
    "checkpoint_segment_boundary_verified",
    "signed_evaluation_window_verified",
    "ssh_keygen_binary_binding_verified",
}
TRANSITION_FALSE_CLAIMS = {
    "canonical_anchor_authority_verified",
    "trusted_clock_source_verified",
    "authoritative_complete_history_verified",
    "parallel_branch_absence_verified",
    "old_key_revocation_verified",
    "key_compromise_absence_verified",
    "segmentation_policy_adopted",
    "actual_store_continuity_verified",
    "backup_creation_verified",
    "restore_execution_verified",
    "protected_runner_execution_verified",
    "signer_reviewer_person_independence_verified",
    "promotion_verified",
    "current_truth_changed",
    "final_human_go",
    "public_beta_go",
    "ssh_keygen_vendor_authority_verified",
}


class AttestationNonceStoreCheckpointSegmentTransitionCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ssh_keygen = shutil.which("ssh-keygen")
        if cls.ssh_keygen is None:
            raise unittest.SkipTest("ssh-keygen is unavailable")

    def digest(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_r22_schemas_are_closed_bounded_and_keep_terminal_claims_false(
        self,
    ) -> None:
        transition = json.loads(TRANSITION_SCHEMA.read_text(encoding="utf-8"))
        verification = json.loads(
            VERIFICATION_SCHEMA.read_text(encoding="utf-8")
        )

        self.assertFalse(transition["additionalProperties"])
        self.assertEqual(
            transition["properties"]["transition_mode"]["enum"],
            ["KEY_ROTATION_SEGMENT", "SAME_POLICY_SEGMENT"],
        )
        self.assertEqual(
            transition["properties"]["prior_segment_binding"]["properties"][
                "checkpoint_count"
            ]["maximum"],
            1024,
        )
        self.assertEqual(
            transition["properties"]["successor_checkpoint_binding"][
                "properties"
            ]["reservation_count"]["minimum"],
            0,
        )
        transition_claims = transition["$defs"]["terminal_claims"]
        self.assertEqual(set(transition_claims["required"]), TRANSITION_FALSE_CLAIMS)
        for definition in transition_claims["properties"].values():
            self.assertIs(definition["const"], False)

        self.assertFalse(verification["additionalProperties"])
        self.assertEqual(len(verification["allOf"]), 3)
        report_claims = verification["$defs"]["report_claims"]
        self.assertEqual(
            set(report_claims["required"]),
            TRANSITION_SUCCESS_CLAIMS
            | TRANSITION_FALSE_CLAIMS
            | {
                "key_rotation_transition_binding_verified",
                "same_policy_segmentation_binding_verified",
            },
        )
        for name in TRANSITION_FALSE_CLAIMS:
            self.assertIs(report_claims["properties"][name]["const"], False)
        for definition in verification["$defs"]["invalid_claims"][
            "properties"
        ].values():
            self.assertIs(definition["const"], False)
        self.assertEqual(
            verification["properties"]["public_beta"]["const"],
            "NO_GO_UNPUBLISHED",
        )

    def make_signer(
        self, temporary: Path, name: str, identity_value: str
    ) -> dict[str, Path]:
        key = temporary / name
        generated = subprocess.run(
            [self.ssh_keygen, "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
        identity = temporary / f"{name}.identity"
        identity.write_text(identity_value, encoding="utf-8")
        public_key = Path(str(key) + ".pub").read_text(encoding="utf-8").strip()
        allowed = temporary / f"{name}.allowed-signers"
        allowed.write_text(f"{identity_value} {public_key}\n", encoding="utf-8")
        return {"key": key, "identity": identity, "allowed": allowed}

    def sign(self, document: Path, key: Path, namespace: str) -> Path:
        result = subprocess.run(
            [
                self.ssh_keygen,
                "-Y",
                "sign",
                "-f",
                str(key),
                "-n",
                namespace,
                str(document),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return Path(str(document) + ".sig")

    def rewrite_and_resign_transition(
        self,
        material: dict[str, object],
        value: dict[str, object],
        key: Path | None = None,
    ) -> None:
        transition = Path(material["transition"])
        transition.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        signature = Path(material["transition_signature"])
        signature.unlink(missing_ok=True)
        reviewer = material["transition_reviewer"]
        assert isinstance(reviewer, dict)
        material["transition_signature"] = self.sign(
            transition, key or reviewer["key"], TRANSITION_NAMESPACE
        )

    def make_case(
        self, temporary: Path, mode: str = "KEY_ROTATION_SEGMENT"
    ) -> dict[str, object]:
        helper = r20_helpers.AttestationNonceStoreCheckpointChainCliTests(
            methodName="test_three_checkpoint_chain_and_supplied_store_are_logically_equivalent"
        )
        helper.ssh_keygen = self.ssh_keygen
        case = helper.make_chain(temporary)
        bundle = temporary / "prior-chain-bundle.json"
        created_bundle = helper.create_bundle(case, bundle)
        self.assertEqual(
            created_bundle.returncode,
            0,
            created_bundle.stdout + created_bundle.stderr,
        )

        old_inputs = case["inputs"]
        checkpoints = case["checkpoints"]
        r19_helper = case["helper"]
        assert isinstance(old_inputs, dict)
        assert isinstance(checkpoints, list)
        new_signer = self.make_signer(
            temporary, "new-checkpoint-key", "new-checkpoint-reviewer@example.test"
        )
        transition_reviewer = self.make_signer(
            temporary, "transition-reviewer-key", "transition-reviewer@example.test"
        )
        successor_inputs = dict(old_inputs)
        if mode == "KEY_ROTATION_SEGMENT":
            successor_inputs["allowed_signers"] = new_signer["allowed"]
            successor_inputs["identity_file"] = new_signer["identity"]
            successor_key = new_signer["key"]
        else:
            successor_key = temporary / "inputs" / "reviewer-key"

        r19_helper.add_reservation(old_inputs, b"r22-segment-boundary-reservation")
        successor = temporary / "successor-checkpoint.json"
        created_successor = r19_helper.create_checkpoint(
            successor_inputs, successor, checkpoints[-1]
        )
        self.assertEqual(
            created_successor.returncode,
            0,
            created_successor.stdout + created_successor.stderr,
        )
        successor_signature = r19_helper.sign_checkpoint(successor, successor_key)

        bundle_value = json.loads(bundle.read_text(encoding="utf-8"))
        prior_checkpoint = json.loads(checkpoints[-1].read_text(encoding="utf-8"))
        successor_value = json.loads(successor.read_text(encoding="utf-8"))
        prior_allowed = Path(old_inputs["allowed_signers"])
        prior_identity = Path(old_inputs["identity_file"])
        successor_allowed = Path(successor_inputs["allowed_signers"])
        successor_identity = Path(successor_inputs["identity_file"])
        transition = {
            "kind": "attestation_nonce_store_checkpoint_segment_transition",
            "version": "1.0",
            "status": "SEGMENT_TRANSITION_CANDIDATE",
            "namespace": TRANSITION_NAMESPACE,
            "transition_id_sha256": hashlib.sha256(b"r22-transition-id").hexdigest(),
            "transition_mode": mode,
            "issued_at": "2026-08-03T01:00:00Z",
            "expires_at": "2026-08-03T01:10:00Z",
            "prior_segment_binding": {
                "bundle_file_sha256": self.digest(bundle),
                "current_checkpoint_sha256": bundle_value[
                    "current_checkpoint_sha256"
                ],
                "current_checkpoint_chain_sha256": prior_checkpoint[
                    "checkpoint_chain_sha256"
                ],
                "store_id_sha256": prior_checkpoint["store_binding"][
                    "store_id_sha256"
                ],
                "checkpoint_count": bundle_value["checkpoint_count"],
                "allowed_signers_file_sha256": self.digest(prior_allowed),
                "signer_identity_file_sha256": self.digest(prior_identity),
            },
            "successor_checkpoint_binding": {
                "checkpoint_file_sha256": self.digest(successor),
                "checkpoint_chain_sha256": successor_value[
                    "checkpoint_chain_sha256"
                ],
                "store_id_sha256": successor_value["store_binding"][
                    "store_id_sha256"
                ],
                "reservation_count": successor_value["store_binding"][
                    "reservation_count"
                ],
                "allowed_signers_file_sha256": self.digest(successor_allowed),
                "signer_identity_file_sha256": self.digest(successor_identity),
            },
            "reviewer_policy_binding": {
                "allowed_signers_file_sha256": self.digest(
                    transition_reviewer["allowed"]
                ),
                "signer_identity_file_sha256": self.digest(
                    transition_reviewer["identity"]
                ),
                "signer_role": "independent_transition_reviewer",
            },
            "claims": {name: False for name in sorted(TRANSITION_FALSE_CLAIMS)},
            "public_beta": "NO_GO_UNPUBLISHED",
        }
        transition_path = temporary / "segment-transition.json"
        transition_path.write_text(
            json.dumps(transition, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        transition_signature = self.sign(
            transition_path, transition_reviewer["key"], TRANSITION_NAMESPACE
        )
        return {
            "case": case,
            "bundle": bundle,
            "successor": successor,
            "successor_signature": successor_signature,
            "successor_key": successor_key,
            "successor_allowed": successor_allowed,
            "successor_identity": successor_identity,
            "transition": transition_path,
            "transition_signature": transition_signature,
            "transition_reviewer": transition_reviewer,
        }

    def verify_transition(
        self,
        material: dict[str, object],
        *,
        expected_transition_sha256: str | None = None,
        expected_bundle_sha256: str | None = None,
        expected_successor_sha256: str | None = None,
        store: Path | None = None,
        prior_allowed: Path | None = None,
        prior_identity: Path | None = None,
        successor_allowed: Path | None = None,
        successor_identity: Path | None = None,
        reviewer_allowed: Path | None = None,
        reviewer_identity: Path | None = None,
        expected_ssh_keygen_sha256: str | None = None,
        evaluated_at: str = "2026-08-03T01:05:00Z",
    ) -> subprocess.CompletedProcess[str]:
        case = material["case"]
        transition_reviewer = material["transition_reviewer"]
        assert isinstance(case, dict) and isinstance(transition_reviewer, dict)
        inputs = case["inputs"]
        assert isinstance(inputs, dict)
        transition = Path(material["transition"])
        bundle = Path(material["bundle"])
        successor = Path(material["successor"])
        return subprocess.run(
            [
                sys.executable,
                str(VERIFY_TRANSITION),
                str(transition),
                str(material["transition_signature"]),
                expected_transition_sha256 or self.digest(transition),
                str(bundle),
                expected_bundle_sha256 or self.digest(bundle),
                str(successor),
                str(material["successor_signature"]),
                expected_successor_sha256 or self.digest(successor),
                str(store or inputs["store"]),
                str(prior_allowed or inputs["allowed_signers"]),
                str(prior_identity or inputs["identity_file"]),
                str(successor_allowed or material["successor_allowed"]),
                str(successor_identity or material["successor_identity"]),
                str(reviewer_allowed or transition_reviewer["allowed"]),
                str(reviewer_identity or transition_reviewer["identity"]),
                expected_ssh_keygen_sha256
                or hashlib.sha256(Path(self.ssh_keygen).read_bytes()).hexdigest(),
                evaluated_at,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_key_rotation_segment_binds_old_chain_new_successor_and_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            material = self.make_case(Path(directory))
            result = self.verify_transition(material)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "SIGNED_KEY_ROTATION_SEGMENT_TRANSITION")
        for name in TRANSITION_SUCCESS_CLAIMS | {
            "key_rotation_transition_binding_verified"
        }:
            self.assertTrue(report["claims"][name], name)
        self.assertFalse(report["claims"]["same_policy_segmentation_binding_verified"])
        for name in TRANSITION_FALSE_CLAIMS:
            self.assertFalse(report["claims"][name], name)
        self.assertEqual(report["counts"]["prior_checkpoints_verified"], 3)
        self.assertEqual(report["counts"]["successor_parent_links_verified"], 1)
        self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")

    def test_same_policy_segment_keeps_rotation_claim_false(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            material = self.make_case(Path(directory), mode="SAME_POLICY_SEGMENT")
            result = self.verify_transition(material)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "SIGNED_SAME_POLICY_SEGMENT_TRANSITION")
        for name in TRANSITION_SUCCESS_CLAIMS | {
            "same_policy_segmentation_binding_verified"
        }:
            self.assertTrue(report["claims"][name], name)
        self.assertFalse(report["claims"]["key_rotation_transition_binding_verified"])
        for name in TRANSITION_FALSE_CLAIMS:
            self.assertFalse(report["claims"][name], name)

    def test_signed_overclaim_and_fake_rotation_fail_closed_without_reflection(
        self,
    ) -> None:
        private_marker = "private-transition-marker-must-not-leak"
        with tempfile.TemporaryDirectory() as directory:
            material = self.make_case(Path(directory), mode="SAME_POLICY_SEGMENT")
            transition = Path(material["transition"])
            value = json.loads(transition.read_text(encoding="utf-8"))
            value["transition_mode"] = "KEY_ROTATION_SEGMENT"
            value["claims"]["public_beta_go"] = True
            value[private_marker] = private_marker
            self.rewrite_and_resign_transition(material, value)
            result = self.verify_transition(material)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "INVALID")
        self.assertIn("transition contains unknown fields", report["errors"])
        self.assertIn("claim public_beta_go must remain false", report["errors"])
        self.assertIn(
            "key rotation mode requires a changed signer key set", report["errors"]
        )
        self.assertTrue(all(not value for value in report["claims"].values()))
        self.assertNotIn(private_marker, result.stdout + result.stderr)

    def test_pins_store_window_and_reviewer_structure_fail_closed(self) -> None:
        cases: list[tuple[str, subprocess.CompletedProcess[str], str]] = []
        for name in (
            "transition-digest",
            "stale-store",
            "same-reviewer",
            "ssh-pin",
            "expired",
        ):
            with tempfile.TemporaryDirectory() as directory:
                material = self.make_case(Path(directory))
                case = material["case"]
                assert isinstance(case, dict)
                if name == "transition-digest":
                    result = self.verify_transition(
                        material, expected_transition_sha256="0" * 64
                    )
                    expected = "supplied transition digest mismatch"
                elif name == "stale-store":
                    result = self.verify_transition(
                        material, store=Path(case["restored_store"])
                    )
                    expected = "supplied store does not match successor checkpoint"
                elif name == "same-reviewer":
                    result = self.verify_transition(
                        material,
                        reviewer_allowed=Path(material["successor_allowed"]),
                        reviewer_identity=Path(material["successor_identity"]),
                    )
                    expected = "transition reviewer hashes must be structurally distinct"
                elif name == "ssh-pin":
                    result = self.verify_transition(
                        material, expected_ssh_keygen_sha256="0" * 64
                    )
                    expected = "ssh-keygen executable binding mismatch"
                else:
                    result = self.verify_transition(
                        material, evaluated_at="2026-08-03T01:11:00Z"
                    )
                    expected = "evaluation time is outside the signed window"
                cases.append((name, result, expected))

        for name, result, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stderr, "")
                report = json.loads(result.stdout)
                self.assertEqual(report["status"], "INVALID")
                self.assertIn(expected, report["errors"])
                self.assertTrue(all(not value for value in report["claims"].values()))

    def test_prior_successor_and_transition_signature_tamper_fail_closed(self) -> None:
        cases: list[tuple[str, subprocess.CompletedProcess[str], str, str]] = []
        for name in ("prior", "successor", "transition"):
            with tempfile.TemporaryDirectory() as directory:
                material = self.make_case(Path(directory))
                private_marker = f"private-{name}-signature-marker"
                if name == "prior":
                    bundle = Path(material["bundle"])
                    bundle_value = json.loads(bundle.read_text(encoding="utf-8"))
                    signature_bytes = private_marker.encode("utf-8")
                    bundle_value["entries"][1]["signature_bytes_base64"] = (
                        base64.b64encode(signature_bytes).decode("ascii")
                    )
                    bundle_value["entries"][1]["signature_file_sha256"] = (
                        hashlib.sha256(signature_bytes).hexdigest()
                    )
                    bundle_value["ordered_chain_sha256"] = (
                        r20_helpers.chain_tool.ordered_chain_sha256(
                            bundle_value["entries"]
                        )
                    )
                    bundle.write_text(json.dumps(bundle_value), encoding="utf-8")
                    transition = Path(material["transition"])
                    transition_value = json.loads(
                        transition.read_text(encoding="utf-8")
                    )
                    transition_value["prior_segment_binding"][
                        "bundle_file_sha256"
                    ] = self.digest(bundle)
                    self.rewrite_and_resign_transition(material, transition_value)
                    expected = "prior checkpoint 1 signature verification failed"
                elif name == "successor":
                    Path(material["successor_signature"]).write_text(
                        private_marker, encoding="utf-8"
                    )
                    expected = "successor checkpoint signature verification failed"
                else:
                    Path(material["transition_signature"]).write_text(
                        private_marker, encoding="utf-8"
                    )
                    expected = "transition signature verification failed"
                result = self.verify_transition(material)
                cases.append((name, result, expected, private_marker))

        for name, result, expected, private_marker in cases:
            with self.subTest(name=name):
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stderr, "")
                report = json.loads(result.stdout)
                self.assertIn(expected, report["errors"])
                self.assertTrue(all(not value for value in report["claims"].values()))
                self.assertNotIn(private_marker, result.stdout + result.stderr)

    def test_structurally_valid_wrong_parent_cannot_start_a_segment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            material = self.make_case(Path(directory))
            successor = Path(material["successor"])
            successor_value = json.loads(successor.read_text(encoding="utf-8"))
            successor_value["parent_binding"][
                "parent_checkpoint_file_sha256"
            ] = "0" * 64
            successor_value["checkpoint_chain_sha256"] = (
                r20_helpers.r19_helpers.checkpoint_tool.checkpoint_chain_sha256(
                    successor_value
                )
            )
            successor.write_text(
                json.dumps(successor_value, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            Path(material["successor_signature"]).unlink(missing_ok=True)
            material["successor_signature"] = self.sign(
                successor,
                Path(material["successor_key"]),
                "kotodama-nonce-store-checkpoint",
            )
            transition = Path(material["transition"])
            transition_value = json.loads(transition.read_text(encoding="utf-8"))
            transition_value["successor_checkpoint_binding"][
                "checkpoint_file_sha256"
            ] = self.digest(successor)
            transition_value["successor_checkpoint_binding"][
                "checkpoint_chain_sha256"
            ] = successor_value["checkpoint_chain_sha256"]
            self.rewrite_and_resign_transition(material, transition_value)
            result = self.verify_transition(material)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertIn(
            "successor parent binding does not match prior segment head",
            report["errors"],
        )
        self.assertTrue(all(not value for value in report["claims"].values()))

    def test_strict_and_deep_transition_json_are_structured_refusals(self) -> None:
        payloads = {
            "duplicate": b'{"kind":"one","kind":"two"}',
            "nonfinite": b'{"kind":NaN}',
            "deep": (b'{"nested":' * 5000) + b"0" + (b"}" * 5000),
        }
        results: list[tuple[str, subprocess.CompletedProcess[str]]] = []
        for name, payload in payloads.items():
            with tempfile.TemporaryDirectory() as directory:
                material = self.make_case(Path(directory))
                Path(material["transition"]).write_bytes(payload)
                Path(material["transition_signature"]).write_bytes(
                    b"not-a-private-signature-body"
                )
                results.append((name, self.verify_transition(material)))

        for name, result in results:
            with self.subTest(name=name):
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stderr, "")
                report = json.loads(result.stdout)
                self.assertEqual(report["status"], "INVALID")
                self.assertEqual(report["errors"], ["input is invalid"])
                self.assertTrue(all(not value for value in report["claims"].values()))

    def test_usage_error_is_not_a_verification_report(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VERIFY_TRANSITION)],
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
