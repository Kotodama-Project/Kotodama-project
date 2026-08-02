import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFY_ANCHOR = (
    ROOT / "tools" / "verify_attestation_nonce_store_checkpoint_head_anchor.py"
)
ANCHOR_SCHEMA = (
    ROOT / "schemas" / "attestation-nonce-store-checkpoint-head-anchor.schema.json"
)
VERIFICATION_SCHEMA = (
    ROOT
    / "schemas"
    / "attestation-nonce-store-checkpoint-head-anchor-verification.schema.json"
)
sys.path.insert(0, str(ROOT / "tests"))
import test_attestation_nonce_store_checkpoint_chain as r20_helpers  # noqa: E402


ANCHOR_FALSE_CLAIMS = {
    "external_anchor_authority_verified",
    "trusted_clock_source_verified",
    "authoritative_complete_history_verified",
    "parallel_branch_absence_verified",
    "store_continuity_verified",
    "backup_execution_verified",
    "restore_execution_verified",
    "protected_runner_execution_verified",
    "signer_person_independence_verified",
    "promotion_verified",
    "current_truth_changed",
    "final_human_go",
    "public_beta_go",
    "ssh_keygen_vendor_authority_verified",
}


class AttestationNonceStoreCheckpointHeadAnchorCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ssh_keygen = shutil.which("ssh-keygen")
        if cls.ssh_keygen is None:
            raise unittest.SkipTest("ssh-keygen is unavailable")

    def make_r20_case(self, temporary: Path) -> dict[str, object]:
        helper = r20_helpers.AttestationNonceStoreCheckpointChainCliTests(
            methodName="test_three_checkpoint_chain_and_supplied_store_are_logically_equivalent"
        )
        helper.ssh_keygen = self.ssh_keygen
        case = helper.make_chain(temporary)
        bundle = temporary / "chain-bundle.json"
        created = helper.create_bundle(case, bundle)
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        verified = helper.verify_bundle(case, bundle)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        report = json.loads(verified.stdout)
        case.update(
            {
                "r20_helper": helper,
                "bundle": bundle,
                "bundle_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
                "chain_report": report,
            }
        )
        return case

    def make_anchor(self, case: dict[str, object]) -> dict[str, object]:
        inputs = case["inputs"]
        report = case["chain_report"]
        assert isinstance(inputs, dict) and isinstance(report, dict)
        return {
            "kind": "attestation_nonce_store_checkpoint_head_anchor",
            "version": "1.0",
            "status": "CHECKPOINT_HEAD_ANCHOR_CANDIDATE",
            "namespace": "kotodama-nonce-store-checkpoint-head",
            "anchor_id_sha256": hashlib.sha256(b"r21-anchor-id").hexdigest(),
            "issued_at": "2026-08-03T00:00:00Z",
            "expires_at": "2026-08-03T00:10:00Z",
            "bundle_binding": {
                "bundle_file_sha256": case["bundle_sha256"],
                "current_checkpoint_sha256": report["input_bindings"][
                    "current_checkpoint_sha256"
                ],
                "store_id_sha256": report["input_bindings"]["store_id_sha256"],
                "checkpoint_count": report["counts"]["checkpoints_verified"],
            },
            "signature_policy_binding": {
                "allowed_signers_file_sha256": hashlib.sha256(
                    Path(inputs["allowed_signers"]).read_bytes()
                ).hexdigest(),
                "signer_identity_file_sha256": hashlib.sha256(
                    Path(inputs["identity_file"]).read_bytes()
                ).hexdigest(),
                "signer_role": "independent_anchor_reviewer",
            },
            "claims": {name: False for name in sorted(ANCHOR_FALSE_CLAIMS)},
            "public_beta": "NO_GO_UNPUBLISHED",
        }

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

    def verify_anchor(
        self,
        case: dict[str, object],
        anchor: Path,
        signature: Path,
    ) -> subprocess.CompletedProcess[str]:
        inputs = case["inputs"]
        assert isinstance(inputs, dict)
        return subprocess.run(
            [
                sys.executable,
                str(VERIFY_ANCHOR),
                str(anchor),
                str(signature),
                hashlib.sha256(anchor.read_bytes()).hexdigest(),
                str(case["bundle"]),
                str(case["bundle_sha256"]),
                str(inputs["allowed_signers"]),
                str(inputs["identity_file"]),
                hashlib.sha256(Path(self.ssh_keygen).read_bytes()).hexdigest(),
                "2026-08-03T00:05:00Z",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_signed_anchor_binds_the_exact_r20_bundle_head_and_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            case = self.make_r20_case(temporary)
            anchor_value = self.make_anchor(case)
            anchor = temporary / "checkpoint-head-anchor.json"
            anchor.write_text(
                json.dumps(anchor_value, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            signature = self.sign(
                anchor,
                temporary / "inputs" / "reviewer-key",
                "kotodama-nonce-store-checkpoint-head",
            )
            result = self.verify_anchor(case, anchor, signature)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "SIGNED_CHECKPOINT_HEAD_ANCHOR_MATCH")
        for name in (
            "anchor_file_digest_match_verified",
            "supplied_bundle_digest_match_verified",
            "bundle_structure_verified",
            "bundle_head_binding_verified",
            "store_identity_binding_verified",
            "checkpoint_count_binding_verified",
            "anchor_signature_verified",
            "allowed_signer_verified",
            "signer_identity_binding_verified",
            "signer_role_policy_verified",
            "signed_evaluation_window_verified",
            "ssh_keygen_binary_binding_verified",
        ):
            self.assertTrue(report["claims"][name])
        for name in ANCHOR_FALSE_CLAIMS:
            self.assertFalse(report["claims"][name])
        self.assertEqual(report["counts"]["checkpoints_bound"], 3)
        self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")
        inputs = case["inputs"]
        assert isinstance(inputs, dict)
        self.assertNotIn(str(inputs["identity"]), result.stdout)

    def test_head_anchor_schemas_are_closed_and_keep_terminal_claims_false(self) -> None:
        anchor = json.loads(ANCHOR_SCHEMA.read_text(encoding="utf-8"))
        verification = json.loads(VERIFICATION_SCHEMA.read_text(encoding="utf-8"))

        self.assertFalse(anchor["additionalProperties"])
        self.assertFalse(
            anchor["properties"]["bundle_binding"]["additionalProperties"]
        )
        self.assertEqual(
            anchor["properties"]["bundle_binding"]["properties"][
                "checkpoint_count"
            ]["maximum"],
            1024,
        )
        for name in ANCHOR_FALSE_CLAIMS:
            self.assertIs(
                anchor["properties"]["claims"]["properties"][name]["const"],
                False,
            )

        self.assertFalse(verification["additionalProperties"])
        self.assertEqual(len(verification["allOf"]), 1)
        for name in ANCHOR_FALSE_CLAIMS:
            self.assertIs(
                verification["properties"]["claims"]["properties"][name][
                    "const"
                ],
                False,
            )
        for definition in verification["$defs"]["invalid_claims"][
            "properties"
        ].values():
            self.assertIs(definition["const"], False)
        self.assertEqual(
            verification["properties"]["public_beta"]["const"],
            "NO_GO_UNPUBLISHED",
        )

    def test_invalid_anchor_id_is_not_copied_into_the_refusal_report(self) -> None:
        private_marker = "private-anchor-id-must-not-leak"
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            case = self.make_r20_case(temporary)
            anchor_value = self.make_anchor(case)
            anchor_value["anchor_id_sha256"] = private_marker
            anchor = temporary / "invalid-anchor-id.json"
            anchor.write_text(
                json.dumps(anchor_value, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            signature = self.sign(
                anchor,
                temporary / "inputs" / "reviewer-key",
                "kotodama-nonce-store-checkpoint-head",
            )
            result = self.verify_anchor(case, anchor, signature)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "INVALID")
        self.assertIn("anchor_id_sha256 must be lowercase SHA-256", report["errors"])
        self.assertNotIn("anchor_id_sha256", report["input_bindings"])
        self.assertTrue(all(not value for value in report["claims"].values()))
        self.assertNotIn(private_marker, result.stdout + result.stderr)

    def test_signed_hostile_anchor_cannot_change_head_window_or_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            case = self.make_r20_case(temporary)
            anchor_value = self.make_anchor(case)
            anchor_value["bundle_binding"]["current_checkpoint_sha256"] = "0" * 64
            anchor_value["expires_at"] = "2026-08-03T00:20:00Z"
            anchor_value["claims"]["promotion_verified"] = True
            anchor_value["unexpected_private_field"] = "must-not-be-copied"
            anchor = temporary / "hostile-anchor.json"
            anchor.write_text(
                json.dumps(anchor_value, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            signature = self.sign(
                anchor,
                temporary / "inputs" / "reviewer-key",
                "kotodama-nonce-store-checkpoint-head",
            )
            result = self.verify_anchor(case, anchor, signature)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertIn("anchor contains unknown fields", report["errors"])
        self.assertIn("anchor bundle binding mismatch", report["errors"])
        self.assertIn("signed window exceeds 900 seconds", report["errors"])
        self.assertIn(
            "claim promotion_verified must remain false", report["errors"]
        )
        self.assertEqual(report["counts"]["checkpoints_bound"], 0)
        self.assertTrue(all(not value for value in report["claims"].values()))
        self.assertNotIn("must-not-be-copied", result.stdout + result.stderr)

    def test_usage_error_is_not_a_verification_report(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VERIFY_ANCHOR)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("usage:", result.stderr)

    def test_deep_json_is_a_structured_refusal_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            case = self.make_r20_case(temporary)
            anchor = temporary / "deep-anchor.json"
            anchor.write_bytes(
                (b'{"nested":' * 5000) + b"0" + (b"}" * 5000)
            )
            signature = temporary / "placeholder.sig"
            signature.write_bytes(b"not-a-private-signature-body")
            result = self.verify_anchor(case, anchor, signature)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "INVALID")
        self.assertEqual(report["errors"], ["input is invalid"])
        self.assertTrue(all(not value for value in report["claims"].values()))


if __name__ == "__main__":
    unittest.main()
