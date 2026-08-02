import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFY_RESTORE = (
    ROOT / "tools" / "verify_attestation_nonce_store_restore_drill_evidence.py"
)
EVIDENCE_SCHEMA = (
    ROOT / "schemas" / "attestation-nonce-store-restore-drill-evidence.schema.json"
)
VERIFICATION_SCHEMA = (
    ROOT
    / "schemas"
    / "attestation-nonce-store-restore-drill-evidence-verification.schema.json"
)
sys.path.insert(0, str(ROOT / "tests"))
import test_attestation_nonce_store_checkpoint_head_anchor as anchor_helpers  # noqa: E402


RESTORE_FALSE_CLAIMS = {
    "anchor_report_authenticity_verified",
    "chain_report_authenticity_verified",
    "external_anchor_authority_verified",
    "trusted_clock_source_verified",
    "authoritative_complete_history_verified",
    "parallel_branch_absence_verified",
    "backup_artifact_verified",
    "backup_execution_verified",
    "restore_execution_verified",
    "physical_store_lineage_verified",
    "protected_runner_execution_verified",
    "runner_reviewer_person_separation_verified",
    "store_continuity_verified",
    "promotion_verified",
    "current_truth_changed",
    "final_human_go",
    "public_beta_go",
    "ssh_keygen_vendor_authority_verified",
}
REPORTED_CHECKS = {
    "backup_command_completed_reported",
    "backup_artifact_digest_match_reported",
    "restore_command_completed_reported",
    "restored_store_opened_reported",
    "restored_store_chain_equivalence_reported",
    "source_store_remained_unmodified_reported",
    "private_data_not_published_reported",
}


class AttestationNonceStoreRestoreDrillEvidenceCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ssh_keygen = shutil.which("ssh-keygen")
        if cls.ssh_keygen is None:
            raise unittest.SkipTest("ssh-keygen is unavailable")

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def make_case(self, temporary: Path) -> dict[str, object]:
        anchor_helper = anchor_helpers.AttestationNonceStoreCheckpointHeadAnchorCliTests(
            methodName="test_signed_anchor_binds_the_exact_r20_bundle_head_and_store"
        )
        anchor_helper.ssh_keygen = self.ssh_keygen
        case = anchor_helper.make_r20_case(temporary)
        inputs = case["inputs"]
        r20_helper = case["r20_helper"]
        assert isinstance(inputs, dict)

        source_result = r20_helper.verify_bundle(case, case["bundle"])
        self.assertEqual(
            source_result.returncode, 0, source_result.stdout + source_result.stderr
        )
        source_report = temporary / "source-chain-report.json"
        source_report.write_text(source_result.stdout, encoding="utf-8")
        restored_result = r20_helper.verify_bundle(case, case["bundle"])
        self.assertEqual(
            restored_result.returncode,
            0,
            restored_result.stdout + restored_result.stderr,
        )
        restored_report = temporary / "restored-chain-report.json"
        restored_report.write_text(restored_result.stdout, encoding="utf-8")
        self.assertNotEqual(self.digest(source_report), self.digest(restored_report))

        anchor_value = anchor_helper.make_anchor(case)
        anchor = temporary / "checkpoint-head-anchor.json"
        anchor.write_text(
            json.dumps(anchor_value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        anchor_signature = anchor_helper.sign(
            anchor,
            temporary / "inputs" / "reviewer-key",
            "kotodama-nonce-store-checkpoint-head",
        )
        anchor_result = anchor_helper.verify_anchor(case, anchor, anchor_signature)
        self.assertEqual(
            anchor_result.returncode,
            0,
            anchor_result.stdout + anchor_result.stderr,
        )
        anchor_report = temporary / "anchor-report.json"
        anchor_report.write_text(anchor_result.stdout, encoding="utf-8")

        backup_receipt = temporary / "private-backup-receipt.bin"
        restore_receipt = temporary / "private-restore-receipt.bin"
        backup_receipt.write_bytes(b"synthetic-private-backup-receipt-v1\n")
        restore_receipt.write_bytes(b"synthetic-private-restore-receipt-v1\n")
        runner_identity_sha256 = hashlib.sha256(
            b"synthetic-private-runner-identity"
        ).hexdigest()
        reviewer_identity_sha256 = self.digest(Path(inputs["identity_file"]))
        self.assertNotEqual(runner_identity_sha256, reviewer_identity_sha256)

        anchor_report_value = json.loads(anchor_report.read_text(encoding="utf-8"))
        source_value = json.loads(source_report.read_text(encoding="utf-8"))
        restored_value = json.loads(restored_report.read_text(encoding="utf-8"))
        evidence_value = {
            "kind": "attestation_nonce_store_restore_drill_evidence",
            "version": "1.0",
            "status": "RESTORE_DRILL_EVIDENCE_CANDIDATE",
            "namespace": "kotodama-nonce-store-restore-drill",
            "drill_id_sha256": hashlib.sha256(b"r21-restore-drill-id").hexdigest(),
            "reported_started_at": "2026-08-03T00:00:00Z",
            "reported_completed_at": "2026-08-03T00:03:00Z",
            "issued_at": "2026-08-03T00:04:00Z",
            "expires_at": "2026-08-03T00:14:00Z",
            "anchor_binding": {
                "report_file_sha256": self.digest(anchor_report),
                "anchor_id_sha256": anchor_report_value["input_bindings"][
                    "anchor_id_sha256"
                ],
                "anchor_file_sha256": anchor_report_value["input_bindings"][
                    "anchor_file_sha256"
                ],
                "bundle_file_sha256": anchor_report_value["input_bindings"][
                    "bundle_file_sha256"
                ],
                "current_checkpoint_sha256": anchor_report_value["input_bindings"][
                    "current_checkpoint_sha256"
                ],
                "store_id_sha256": anchor_report_value["input_bindings"][
                    "store_id_sha256"
                ],
                "checkpoint_count": anchor_report_value["counts"][
                    "checkpoints_bound"
                ],
            },
            "source_verification_binding": {
                "report_file_sha256": self.digest(source_report),
                "bundle_file_sha256": source_value["input_bindings"][
                    "bundle_file_sha256"
                ],
                "current_checkpoint_sha256": source_value["input_bindings"][
                    "current_checkpoint_sha256"
                ],
                "store_id_sha256": source_value["input_bindings"]["store_id_sha256"],
                "checkpoints_verified": source_value["counts"][
                    "checkpoints_verified"
                ],
                "reservations_at_current": source_value["counts"][
                    "reservations_at_current"
                ],
            },
            "restored_verification_binding": {
                "report_file_sha256": self.digest(restored_report),
                "bundle_file_sha256": restored_value["input_bindings"][
                    "bundle_file_sha256"
                ],
                "current_checkpoint_sha256": restored_value["input_bindings"][
                    "current_checkpoint_sha256"
                ],
                "store_id_sha256": restored_value["input_bindings"]["store_id_sha256"],
                "checkpoints_verified": restored_value["counts"][
                    "checkpoints_verified"
                ],
                "reservations_at_current": restored_value["counts"][
                    "reservations_at_current"
                ],
            },
            "operation_receipts": {
                "backup_receipt_file_sha256": self.digest(backup_receipt),
                "restore_receipt_file_sha256": self.digest(restore_receipt),
                "backup_artifact_sha256": hashlib.sha256(
                    b"synthetic-private-backup-artifact"
                ).hexdigest(),
            },
            "reported_checks": {
                name: True for name in sorted(REPORTED_CHECKS)
            },
            "signature_policy_binding": {
                "allowed_signers_file_sha256": self.digest(
                    Path(inputs["allowed_signers"])
                ),
                "signer_identity_file_sha256": reviewer_identity_sha256,
                "signer_role": "independent_restore_reviewer",
            },
            "runner_identity_sha256": runner_identity_sha256,
            "identities_distinct": True,
            "claims": {name: False for name in sorted(RESTORE_FALSE_CLAIMS)},
            "public_beta": "NO_GO_UNPUBLISHED",
        }
        evidence = temporary / "restore-drill-evidence.json"
        evidence.write_text(
            json.dumps(evidence_value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        evidence_signature = anchor_helper.sign(
            evidence,
            temporary / "inputs" / "reviewer-key",
            "kotodama-nonce-store-restore-drill",
        )
        return {
            "case": case,
            "evidence": evidence,
            "evidence_signature": evidence_signature,
            "anchor_report": anchor_report,
            "source_report": source_report,
            "restored_report": restored_report,
            "backup_receipt": backup_receipt,
            "restore_receipt": restore_receipt,
        }

    def resign_evidence(
        self,
        material: dict[str, object],
        evidence_value: dict[str, object],
        filename: str,
    ) -> None:
        original = Path(material["evidence"])
        evidence = original.parent / filename
        evidence.write_text(
            json.dumps(evidence_value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        key = original.parent / "inputs" / "reviewer-key"
        result = subprocess.run(
            [
                self.ssh_keygen,
                "-Y",
                "sign",
                "-f",
                str(key),
                "-n",
                "kotodama-nonce-store-restore-drill",
                str(evidence),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        material["evidence"] = evidence
        material["evidence_signature"] = Path(str(evidence) + ".sig")

    def verify(
        self,
        material: dict[str, object],
        *,
        expected_evidence_sha256: str | None = None,
        evaluated_at: str = "2026-08-03T00:09:00Z",
    ) -> subprocess.CompletedProcess[str]:
        case = material["case"]
        assert isinstance(case, dict)
        inputs = case["inputs"]
        assert isinstance(inputs, dict)
        evidence = Path(material["evidence"])
        return subprocess.run(
            [
                sys.executable,
                str(VERIFY_RESTORE),
                str(evidence),
                str(material["evidence_signature"]),
                expected_evidence_sha256 or self.digest(evidence),
                str(material["anchor_report"]),
                str(material["source_report"]),
                str(material["restored_report"]),
                str(material["backup_receipt"]),
                str(material["restore_receipt"]),
                str(inputs["allowed_signers"]),
                str(inputs["identity_file"]),
                hashlib.sha256(Path(self.ssh_keygen).read_bytes()).hexdigest(),
                evaluated_at,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_signed_evidence_binds_distinct_matching_reports_and_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            material = self.make_case(Path(directory))
            result = self.verify(material)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "SIGNED_RESTORE_DRILL_REPORT_BINDING")
        self.assertEqual(report["counts"]["checkpoints_bound"], 3)
        self.assertEqual(report["counts"]["reported_checks_bound"], 7)
        self.assertTrue(
            report["claims"]["runner_reviewer_hash_distinct_verified"]
        )
        for name in RESTORE_FALSE_CLAIMS:
            self.assertFalse(report["claims"][name])
        self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")

    def test_restore_drill_schemas_are_closed_and_keep_execution_claims_false(self) -> None:
        evidence = json.loads(EVIDENCE_SCHEMA.read_text(encoding="utf-8"))
        verification = json.loads(
            VERIFICATION_SCHEMA.read_text(encoding="utf-8")
        )
        self.assertFalse(evidence["additionalProperties"])
        self.assertFalse(
            evidence["properties"]["operation_receipts"]["additionalProperties"]
        )
        self.assertEqual(
            evidence["properties"]["anchor_binding"]["properties"][
                "checkpoint_count"
            ]["maximum"],
            1024,
        )
        for name in RESTORE_FALSE_CLAIMS:
            self.assertIs(
                evidence["properties"]["claims"]["properties"][name]["const"],
                False,
            )
            self.assertIs(
                verification["properties"]["claims"]["properties"][name][
                    "const"
                ],
                False,
            )
        self.assertEqual(
            verification["properties"]["public_beta"]["const"],
            "NO_GO_UNPUBLISHED",
        )

    def test_signed_hostile_evidence_cannot_assert_execution_or_person_separation(self) -> None:
        private_marker = "private-drill-id-must-not-leak"
        with tempfile.TemporaryDirectory() as directory:
            material = self.make_case(Path(directory))
            evidence_value = json.loads(
                Path(material["evidence"]).read_text(encoding="utf-8")
            )
            evidence_value["drill_id_sha256"] = private_marker
            evidence_value["reported_checks"][
                "backup_command_completed_reported"
            ] = False
            evidence_value["claims"]["backup_execution_verified"] = True
            evidence_value["runner_identity_sha256"] = evidence_value[
                "signature_policy_binding"
            ]["signer_identity_file_sha256"]
            self.resign_evidence(material, evidence_value, "hostile-evidence.json")
            result = self.verify(material)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertIn("drill_id_sha256 must be lowercase SHA-256", report["errors"])
        self.assertIn(
            "reported check backup_command_completed_reported must be true",
            report["errors"],
        )
        self.assertIn(
            "claim backup_execution_verified must remain false", report["errors"]
        )
        self.assertIn(
            "runner and reviewer identity hashes must be distinct", report["errors"]
        )
        self.assertNotIn("drill_id_sha256", report["input_bindings"])
        self.assertTrue(all(not value for value in report["claims"].values()))
        self.assertNotIn(private_marker, result.stdout + result.stderr)

    def test_same_report_bytes_cannot_be_reused_as_source_and_restored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            material = self.make_case(Path(directory))
            evidence_value = json.loads(
                Path(material["evidence"]).read_text(encoding="utf-8")
            )
            evidence_value["restored_verification_binding"] = dict(
                evidence_value["source_verification_binding"]
            )
            material["restored_report"] = material["source_report"]
            self.resign_evidence(material, evidence_value, "reused-report.json")
            result = self.verify(material)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertIn(
            "source and restored report files must be distinct", report["errors"]
        )
        self.assertTrue(all(not value for value in report["claims"].values()))
        self.assertEqual(report["counts"]["reported_checks_bound"], 0)

    def test_unsigned_report_shape_cannot_overclaim_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            material = self.make_case(Path(directory))
            source_report = Path(material["source_report"])
            source_value = json.loads(source_report.read_text(encoding="utf-8"))
            source_value["claims"]["promotion_verified"] = True
            source_report.write_text(
                json.dumps(source_value, sort_keys=True) + "\n", encoding="utf-8"
            )
            evidence_value = json.loads(
                Path(material["evidence"]).read_text(encoding="utf-8")
            )
            evidence_value["source_verification_binding"][
                "report_file_sha256"
            ] = self.digest(source_report)
            self.resign_evidence(
                material, evidence_value, "overclaiming-report-evidence.json"
            )
            result = self.verify(material)

        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertIn(
            "source report claim promotion_verified must be false",
            report["errors"],
        )
        self.assertTrue(all(not value for value in report["claims"].values()))

    def test_independent_evidence_pin_and_signed_window_are_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            material = self.make_case(Path(directory))
            wrong_pin = self.verify(material, expected_evidence_sha256="0" * 64)
            outside_window = self.verify(
                material, evaluated_at="2026-08-03T00:15:00Z"
            )

        for result, expected_error in (
            (wrong_pin, "supplied evidence digest mismatch"),
            (outside_window, "evaluation time is outside the signed window"),
        ):
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stderr, "")
            report = json.loads(result.stdout)
            self.assertIn(expected_error, report["errors"])
            self.assertTrue(all(not value for value in report["claims"].values()))

    def test_usage_error_is_not_a_verification_report(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VERIFY_RESTORE)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("usage:", result.stderr)

    def test_report_counts_cannot_exceed_the_closed_schema_limits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            material = self.make_case(Path(directory))
            evidence_value = json.loads(
                Path(material["evidence"]).read_text(encoding="utf-8")
            )
            for report_key, binding_key in (
                ("source_report", "source_verification_binding"),
                ("restored_report", "restored_verification_binding"),
            ):
                report_path = Path(material[report_key])
                report_value = json.loads(report_path.read_text(encoding="utf-8"))
                report_value["counts"]["reservations_at_current"] = 10001
                report_path.write_text(
                    json.dumps(report_value, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                evidence_value[binding_key]["report_file_sha256"] = self.digest(
                    report_path
                )
                evidence_value[binding_key]["reservations_at_current"] = 10001
            self.resign_evidence(
                material, evidence_value, "oversized-count-evidence.json"
            )
            result = self.verify(material)

        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertIn(
            "source report counts.reservations_at_current exceeds maximum 10000",
            report["errors"],
        )
        self.assertIn(
            "restored report counts.reservations_at_current exceeds maximum 10000",
            report["errors"],
        )
        self.assertTrue(all(not value for value in report["claims"].values()))

    def test_deep_json_is_a_structured_refusal_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            material = self.make_case(Path(directory))
            evidence = Path(material["evidence"])
            evidence.write_bytes(
                (b'{"nested":' * 5000) + b"0" + (b"}" * 5000)
            )
            result = self.verify(material)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "INVALID")
        self.assertEqual(report["errors"], ["input is invalid"])
        self.assertTrue(all(not value for value in report["claims"].values()))


if __name__ == "__main__":
    unittest.main()
