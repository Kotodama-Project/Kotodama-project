import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "tools" / "validate_template_pack.py"
FIXTURES = ROOT / "tests" / "fixtures"
EXAMPLES = ROOT / "examples"


class TemplatePackCliTests(unittest.TestCase):
    def run_validator(self, fixture: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), str(FIXTURES / fixture)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def run_pack(self, path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), str(path)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_valid_pack_passes_with_machine_readable_summary(self) -> None:
        result = self.run_validator("valid-pack")

        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "PASS")
        self.assertEqual(summary["pack_id"], "example-company")
        self.assertEqual(summary["validated_files"], 3)
        self.assertEqual(summary["errors"], [])

    def test_shipped_company_starter_passes(self) -> None:
        result = self.run_pack(EXAMPLES / "company-starter")

        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "PASS")
        self.assertEqual(summary["pack_id"], "kotodama-company-starter")
        self.assertEqual(summary["validated_files"], 22)

    def test_shipped_starter_validates_source_record_template(self) -> None:
        pack = EXAMPLES / "company-starter"
        manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
        source_record = json.loads(
            (pack / "records" / "source-record.json").read_text(encoding="utf-8")
        )

        self.assertEqual(
            manifest["records"],
            [
                "records/source-record.json",
                "records/intent-candidate.json",
                "records/decision-record.json",
                "records/work-order-candidate.json",
                "records/capability-grant-candidate.json",
                "records/change-candidate.json",
                "records/verification-receipt.json",
                "records/promotion-candidate.json",
                "records/promotion-decision-record.json",
            ],
        )
        self.assertEqual(source_record["kind"], "record_template")
        self.assertEqual(source_record["artifact"], "source_record")
        self.assertTrue(
            source_record["authority"]["promotion_required_for_current_truth"]
        )
        self.assertEqual(
            source_record["retention"]["mode"],
            "policy_ref",
        )
        self.assertIn("self_promotion", source_record["denied_claims"])

    def test_record_schema_required_fields_match_shipped_record_shape(self) -> None:
        schema = json.loads(
            (ROOT / "schemas" / "record.schema.json").read_text(encoding="utf-8")
        )
        record = json.loads(
            (
                EXAMPLES
                / "company-starter"
                / "records"
                / "source-record.json"
            ).read_text(encoding="utf-8")
        )

        self.assertEqual(set(schema["required"]), set(record))
        self.assertEqual(
            set(schema["properties"]["authority"]["required"]),
            set(record["authority"]),
        )
        self.assertEqual(
            set(schema["properties"]["retention"]["required"]),
            set(record["retention"]),
        )

    def test_shipped_starter_maps_every_block_output_to_one_record(self) -> None:
        pack = EXAMPLES / "company-starter"
        manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
        block_outputs = []
        for relative in manifest["blocks"]:
            block = json.loads((pack / relative).read_text(encoding="utf-8"))
            block_outputs.extend(block["outputs"])
        record_artifacts = []
        for relative in manifest["records"]:
            record = json.loads((pack / relative).read_text(encoding="utf-8"))
            record_artifacts.append(record["artifact"])

        self.assertEqual(sorted(record_artifacts), sorted(block_outputs))
        self.assertEqual(len(record_artifacts), len(set(record_artifacts)))

    def test_manifest_records_must_cover_every_block_output_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "pack"
            shutil.copytree(EXAMPLES / "company-starter", pack)
            manifest_path = pack / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["records"] = manifest["records"][:-1]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_pack(pack)

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn(
            "manifest records must cover every Block output exactly once",
            summary["errors"],
        )

    def test_declared_empty_record_catalog_cannot_disable_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "pack"
            shutil.copytree(EXAMPLES / "company-starter", pack)
            manifest_path = pack / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["records"] = []
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_pack(pack)

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn(
            "manifest records must cover every Block output exactly once",
            summary["errors"],
        )

    def test_record_template_cannot_omit_mandatory_denied_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "pack"
            shutil.copytree(EXAMPLES / "company-starter", pack)
            record_path = pack / "records" / "source-record.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["denied_claims"].remove("self_promotion")
            record_path.write_text(json.dumps(record), encoding="utf-8")
            result = self.run_pack(pack)

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn(
            "records/source-record.json missing mandatory denied claim: self_promotion",
            summary["errors"],
        )

    def test_record_creator_and_verifier_roles_must_be_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "pack"
            shutil.copytree(EXAMPLES / "company-starter", pack)
            record_path = pack / "records" / "source-record.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["authority"]["verifier_role"] = record["authority"][
                "creator_role"
            ]
            record_path.write_text(json.dumps(record), encoding="utf-8")
            result = self.run_pack(pack)

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn(
            "records/source-record.json authority creator_role and verifier_role must differ",
            summary["errors"],
        )

    def test_record_artifacts_must_be_unique(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "pack"
            shutil.copytree(EXAMPLES / "company-starter", pack)
            record_path = pack / "records" / "promotion-candidate.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["artifact"] = "source_record"
            record_path.write_text(json.dumps(record), encoding="utf-8")
            result = self.run_pack(pack)

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn("duplicate record artifact: source_record", summary["errors"])
        self.assertIn(
            "manifest records must cover every Block output exactly once",
            summary["errors"],
        )

    def test_malformed_record_shape_returns_a_structured_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "pack"
            shutil.copytree(EXAMPLES / "company-starter", pack)
            record_path = pack / "records" / "source-record.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["authority"] = "not-an-object"
            record_path.write_text(json.dumps(record), encoding="utf-8")
            result = self.run_pack(pack)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        summary = json.loads(result.stdout)
        self.assertIn(
            "records/source-record.json field authority must be an object",
            summary["errors"],
        )

    def test_shipped_starter_exposes_the_minimal_governance_chain(self) -> None:
        pack = EXAMPLES / "company-starter"
        manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
        moc = json.loads(
            (pack / "mocs" / "company-operations.json").read_text(encoding="utf-8")
        )

        self.assertEqual(
            manifest["blocks"],
            [
                "blocks/source-intake.json",
                "blocks/intent-candidate.json",
                "blocks/human-decision.json",
                "blocks/work-order.json",
                "blocks/capability-grant.json",
                "blocks/change-execution.json",
                "blocks/verification-receipt.json",
                "blocks/promotion-gate.json",
                "blocks/promotion-decision.json",
            ],
        )
        self.assertEqual(
            moc["refs"],
            [
                "kotodama-company-starter",
                "source-intake-starter",
                "intent-candidate-starter",
                "human-decision-starter",
                "work-order-starter",
                "capability-grant-starter",
                "change-execution-starter",
                "verification-receipt-starter",
                "promotion-gate-starter",
                "promotion-decision-starter",
            ],
        )

    def test_shipped_starter_exposes_task_specific_navigation_mocs(self) -> None:
        pack = EXAMPLES / "company-starter"
        manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
        public_release = json.loads(
            (pack / "mocs" / "public-release.json").read_text(encoding="utf-8")
        )
        incident_recovery = json.loads(
            (pack / "mocs" / "incident-recovery.json").read_text(encoding="utf-8")
        )

        self.assertEqual(
            manifest["mocs"],
            [
                "mocs/company-operations.json",
                "mocs/public-release.json",
                "mocs/incident-recovery.json",
            ],
        )
        self.assertEqual(public_release["authority"], "navigation_only")
        self.assertEqual(public_release["projection"], "flow_subsequence")
        self.assertEqual(
            public_release["refs"],
            [
                "kotodama-company-starter",
                "human-decision-starter",
                "work-order-starter",
                "capability-grant-starter",
                "change-execution-starter",
                "verification-receipt-starter",
                "promotion-gate-starter",
                "promotion-decision-starter",
            ],
        )
        self.assertEqual(incident_recovery["authority"], "navigation_only")
        self.assertEqual(incident_recovery["projection"], "flow_subsequence")
        self.assertEqual(
            incident_recovery["refs"],
            [
                "kotodama-company-starter",
                "work-order-starter",
                "capability-grant-starter",
                "change-execution-starter",
                "verification-receipt-starter",
            ],
        )

    def test_secondary_moc_must_preserve_canonical_flow_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "pack"
            shutil.copytree(EXAMPLES / "company-starter", pack)
            moc_path = pack / "mocs" / "public-release.json"
            moc = json.loads(moc_path.read_text(encoding="utf-8"))
            moc["refs"][1], moc["refs"][2] = moc["refs"][2], moc["refs"][1]
            moc_path.write_text(json.dumps(moc), encoding="utf-8")
            result = self.run_pack(pack)

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn(
            "manifest secondary MOC public-release-starter refs must be manifest id followed by an ordered subsequence of flow sequence",
            summary["errors"],
        )

    def test_secondary_moc_cannot_mix_record_ids_into_flow_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "pack"
            shutil.copytree(EXAMPLES / "company-starter", pack)
            moc_path = pack / "mocs" / "incident-recovery.json"
            moc = json.loads(moc_path.read_text(encoding="utf-8"))
            moc["refs"].append("verification-receipt-template")
            moc_path.write_text(json.dumps(moc), encoding="utf-8")
            result = self.run_pack(pack)

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn(
            "manifest secondary MOC incident-recovery-starter refs must be manifest id followed by an ordered subsequence of flow sequence",
            summary["errors"],
        )

    def test_secondary_flow_projection_contract_is_opt_in_for_legacy_mocs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "pack"
            shutil.copytree(EXAMPLES / "company-starter", pack)
            moc_path = pack / "mocs" / "incident-recovery.json"
            moc = json.loads(moc_path.read_text(encoding="utf-8"))
            moc.pop("projection", None)
            moc["refs"].append("verification-receipt-template")
            moc_path.write_text(json.dumps(moc), encoding="utf-8")
            result = self.run_pack(pack)

        self.assertEqual(result.returncode, 0)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "PASS")

    def test_moc_rejects_unknown_projection_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "pack"
            shutil.copytree(EXAMPLES / "company-starter", pack)
            moc_path = pack / "mocs" / "public-release.json"
            moc = json.loads(moc_path.read_text(encoding="utf-8"))
            moc["projection"] = "freeform_navigation"
            moc_path.write_text(json.dumps(moc), encoding="utf-8")
            result = self.run_pack(pack)

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn(
            "mocs/public-release.json projection must be flow_subsequence",
            summary["errors"],
        )

    def test_starter_requires_capability_before_change_and_human_promotion_decision(self) -> None:
        pack = EXAMPLES / "company-starter"
        work_order = json.loads(
            (pack / "blocks" / "work-order.json").read_text(encoding="utf-8")
        )
        capability = json.loads(
            (pack / "blocks" / "capability-grant.json").read_text(encoding="utf-8")
        )
        change = json.loads(
            (pack / "blocks" / "change-execution.json").read_text(encoding="utf-8")
        )
        promotion_decision = json.loads(
            (pack / "blocks" / "promotion-decision.json").read_text(encoding="utf-8")
        )

        self.assertEqual(work_order["outputs"], ["work_order_candidate"])
        self.assertEqual(
            capability["inputs"],
            ["work_order_candidate", "capability_grant_evidence"],
        )
        self.assertEqual(capability["outputs"], ["capability_grant_candidate"])
        self.assertEqual(
            change["inputs"],
            [
                "work_order_candidate",
                "capability_grant_candidate",
                "candidate_revision",
            ],
        )
        self.assertEqual(change["outputs"], ["change_candidate"])
        self.assertEqual(
            promotion_decision["inputs"],
            ["promotion_candidate", "human_promotion_decision_evidence"],
        )
        self.assertEqual(
            promotion_decision["outputs"], ["promotion_decision_record"]
        )

    def test_shipped_starter_declares_its_flow_contract(self) -> None:
        manifest = json.loads(
            (EXAMPLES / "company-starter" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            manifest["flow"],
            {
                "entry_inputs": [
                    "source_locator",
                    "access_or_consent_ref",
                    "retention_rule",
                    "human_decision_evidence",
                    "capability_grant_evidence",
                    "candidate_revision",
                    "human_promotion_decision_evidence",
                ],
                "sequence": [
                    "source-intake-starter",
                    "intent-candidate-starter",
                    "human-decision-starter",
                    "work-order-starter",
                    "capability-grant-starter",
                    "change-execution-starter",
                    "verification-receipt-starter",
                    "promotion-gate-starter",
                    "promotion-decision-starter",
                ],
                "moc_ref": "company-operations-starter",
            },
        )

    def test_flow_rejects_a_block_before_its_required_input_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "pack"
            shutil.copytree(EXAMPLES / "company-starter", pack)
            manifest_path = pack / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["flow"]["sequence"] = [
                "source-intake-starter",
                "intent-candidate-starter",
                "work-order-starter",
                "human-decision-starter",
                "capability-grant-starter",
                "change-execution-starter",
                "verification-receipt-starter",
                "promotion-gate-starter",
                "promotion-decision-starter",
            ]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_pack(pack)

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn(
            "manifest flow block work-order-starter has unavailable input: decision_record",
            summary["errors"],
        )

    def test_flow_rejects_change_before_capability_grant(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "pack"
            shutil.copytree(EXAMPLES / "company-starter", pack)
            manifest_path = pack / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            sequence = manifest["flow"]["sequence"]
            grant_index = sequence.index("capability-grant-starter")
            change_index = sequence.index("change-execution-starter")
            sequence[grant_index], sequence[change_index] = (
                sequence[change_index],
                sequence[grant_index],
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_pack(pack)

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn(
            "manifest flow block change-execution-starter has unavailable input: capability_grant_candidate",
            summary["errors"],
        )

    def test_flow_entry_inputs_cannot_shadow_protected_block_outputs(self) -> None:
        cases = (
            (
                "capability_grant_candidate",
                "capability-grant-starter",
                "change-execution-starter",
            ),
            (
                "promotion_candidate",
                "promotion-gate-starter",
                "promotion-decision-starter",
            ),
        )
        for artifact, producer_id, consumer_id in cases:
            with self.subTest(artifact=artifact):
                with tempfile.TemporaryDirectory() as temporary:
                    pack = Path(temporary) / "pack"
                    shutil.copytree(EXAMPLES / "company-starter", pack)
                    manifest_path = pack / "manifest.json"
                    manifest = json.loads(
                        manifest_path.read_text(encoding="utf-8")
                    )
                    sequence = manifest["flow"]["sequence"]
                    producer_index = sequence.index(producer_id)
                    consumer_index = sequence.index(consumer_id)
                    sequence[producer_index], sequence[consumer_index] = (
                        sequence[consumer_index],
                        sequence[producer_index],
                    )
                    manifest["flow"]["entry_inputs"].append(artifact)
                    manifest_path.write_text(
                        json.dumps(manifest), encoding="utf-8"
                    )
                    moc_path = pack / "mocs" / "company-operations.json"
                    moc = json.loads(moc_path.read_text(encoding="utf-8"))
                    moc["refs"] = [manifest["id"], *sequence]
                    moc_path.write_text(json.dumps(moc), encoding="utf-8")
                    result = self.run_pack(pack)

            self.assertEqual(result.returncode, 1)
            summary = json.loads(result.stdout)
            self.assertIn(
                f"manifest flow entry input shadows Block output: {artifact}",
                summary["errors"],
            )

    def test_promotion_decision_requires_human_evidence_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "pack"
            shutil.copytree(EXAMPLES / "company-starter", pack)
            manifest_path = pack / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["flow"]["entry_inputs"].remove(
                "human_promotion_decision_evidence"
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_pack(pack)

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn(
            "manifest flow block promotion-decision-starter has unavailable input: human_promotion_decision_evidence",
            summary["errors"],
        )

    def test_flow_requires_its_moc_to_match_the_declared_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "pack"
            shutil.copytree(EXAMPLES / "company-starter", pack)
            moc_path = pack / "mocs" / "company-operations.json"
            moc = json.loads(moc_path.read_text(encoding="utf-8"))
            moc["refs"] = [moc["refs"][0], *reversed(moc["refs"][1:])]
            moc_path.write_text(json.dumps(moc), encoding="utf-8")
            result = self.run_pack(pack)

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn(
            "manifest flow MOC company-operations-starter refs must equal manifest id followed by flow sequence",
            summary["errors"],
        )

    def test_flow_sequence_must_cover_every_manifest_block(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "pack"
            shutil.copytree(EXAMPLES / "company-starter", pack)
            manifest_path = pack / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["flow"]["sequence"] = manifest["flow"]["sequence"][:-1]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            moc_path = pack / "mocs" / "company-operations.json"
            moc = json.loads(moc_path.read_text(encoding="utf-8"))
            moc["refs"] = moc["refs"][:-1]
            moc_path.write_text(json.dumps(moc), encoding="utf-8")
            result = self.run_pack(pack)

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn(
            "manifest flow sequence must contain every manifest block exactly once",
            summary["errors"],
        )

    def test_flow_references_must_use_schema_valid_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "pack"
            shutil.copytree(EXAMPLES / "company-starter", pack)
            manifest_path = pack / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["flow"]["sequence"][0] = "Invalid Block"
            manifest["flow"]["moc_ref"] = "Invalid MOC"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_pack(pack)

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn(
            "manifest flow.sequence item has invalid id format: Invalid Block",
            summary["errors"],
        )
        self.assertIn(
            "manifest flow.moc_ref has invalid id format: Invalid MOC",
            summary["errors"],
        )

    def test_malformed_flow_shape_returns_a_structured_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "pack"
            shutil.copytree(EXAMPLES / "company-starter", pack)
            manifest_path = pack / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["flow"] = "not-an-object"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_pack(pack)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "FAIL")
        self.assertIn("manifest field flow must be an object", summary["errors"])

    def test_parent_directory_reference_is_rejected(self) -> None:
        result = self.run_validator("invalid-traversal")

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "FAIL")
        self.assertIn(
            "unsafe relative path: ../outside.json",
            summary["errors"],
        )

    def test_symlink_reference_cannot_escape_pack_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            pack = temporary_path / "pack"
            shutil.copytree(FIXTURES / "valid-pack", pack)
            link = pack / "blocks" / "work-order.json"
            outside = temporary_path / "outside.json"
            outside.write_text(link.read_text(encoding="utf-8"), encoding="utf-8")
            link.unlink()
            try:
                link.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            result = self.run_pack(pack)

        self.assertEqual(result.returncode, 1, result.stderr)
        summary = json.loads(result.stdout)
        self.assertIn(
            "referenced path escapes pack root: blocks/work-order.json",
            summary["errors"],
        )

    def test_secret_bearing_key_is_rejected(self) -> None:
        result = self.run_validator("invalid-secret")

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn("secret-bearing key is forbidden: $.api_token", summary["errors"])

    def test_template_cannot_claim_promotion_or_public_go(self) -> None:
        result = self.run_validator("invalid-promotion")

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn("manifest status is not allowed: promoted", summary["errors"])
        self.assertIn(
            "public_beta must remain NO_GO_UNPUBLISHED",
            summary["errors"],
        )

    def test_template_blocks_and_records_cannot_output_governed_terminal_state(self) -> None:
        forbidden = (
            "capability_grant",
            "promotion",
            "promoted",
            "current_truth",
            "public_go",
            "final_human_go",
        )
        for artifact in forbidden:
            with self.subTest(artifact=artifact):
                with tempfile.TemporaryDirectory() as temporary:
                    pack = Path(temporary) / "pack"
                    shutil.copytree(EXAMPLES / "company-starter", pack)
                    block_path = pack / "blocks" / "source-intake.json"
                    block = json.loads(block_path.read_text(encoding="utf-8"))
                    block["outputs"] = [artifact]
                    block_path.write_text(json.dumps(block), encoding="utf-8")
                    record_path = pack / "records" / "source-record.json"
                    record = json.loads(record_path.read_text(encoding="utf-8"))
                    record["artifact"] = artifact
                    record_path.write_text(json.dumps(record), encoding="utf-8")
                    result = self.run_pack(pack)

            self.assertEqual(result.returncode, 1)
            summary = json.loads(result.stdout)
            self.assertIn(
                f"blocks/source-intake.json forbidden output artifact: {artifact}",
                summary["errors"],
            )
            self.assertIn(
                f"records/source-record.json forbidden record artifact: {artifact}",
                summary["errors"],
            )

    def test_moc_is_navigation_only_and_references_known_ids(self) -> None:
        result = self.run_validator("invalid-moc")

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn(
            "mocs/company-operations.json authority must be navigation_only",
            summary["errors"],
        )
        self.assertIn(
            "mocs/company-operations.json references unknown id: missing-block",
            summary["errors"],
        )

    def test_block_requires_rollback_contract(self) -> None:
        result = self.run_validator("invalid-block")

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn(
            "blocks/work-order.json missing required field: rollback",
            summary["errors"],
        )

    def test_manifest_requires_governance_and_denial_contracts(self) -> None:
        result = self.run_validator("invalid-manifest")

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn("manifest missing required field: denied_actions", summary["errors"])
        self.assertIn("manifest missing required field: human_intent_ref", summary["errors"])

    def test_manifest_requires_each_governance_owner(self) -> None:
        result = self.run_validator("invalid-governance-owners")

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn(
            "manifest missing canonical owner: work_orders",
            summary["errors"],
        )
        self.assertIn(
            "manifest missing canonical owner: current_truth",
            summary["errors"],
        )

    def test_manifest_cannot_omit_mandatory_denials(self) -> None:
        result = self.run_validator("invalid-denials")

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn("manifest missing mandatory denial: self_promotion", summary["errors"])

    def test_manifest_collection_fields_have_strict_types(self) -> None:
        result = self.run_validator("invalid-types")

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn("manifest field blocks must be an array", summary["errors"])
        self.assertIn("manifest field denied_actions must be an array", summary["errors"])

    def test_manifest_collection_items_fail_closed_without_crashing(self) -> None:
        result = self.run_validator("invalid-collection-item")

        self.assertEqual(result.returncode, 1, result.stderr)
        summary = json.loads(result.stdout)
        self.assertIn(
            "manifest field denied_actions must contain only strings",
            summary["errors"],
        )

    def test_referenced_document_kind_must_match_its_manifest_lane(self) -> None:
        result = self.run_validator("invalid-kind")

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn("blocks/work-order.json kind must be block", summary["errors"])

    def test_nested_block_contracts_are_enforced(self) -> None:
        result = self.run_validator("invalid-nested-block")

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn(
            "blocks/work-order.json rollback missing required field: action",
            summary["errors"],
        )

    def test_block_cannot_allow_self_promotion_or_public_go(self) -> None:
        result = self.run_validator("invalid-block-authority")

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn(
            "blocks/work-order.json forbidden allowed action: self_promotion",
            summary["errors"],
        )

    def test_profile_must_be_supported_and_non_empty(self) -> None:
        result = self.run_validator("invalid-profile")

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn("manifest unsupported profile: unknown_runtime", summary["errors"])

    def test_manifest_id_must_match_schema_pattern(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "pack"
            shutil.copytree(FIXTURES / "valid-pack", pack)
            manifest_path = pack / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["id"] = "Invalid ID"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_pack(pack)

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn("manifest field id has an invalid format: Invalid ID", summary["errors"])

    def test_manifest_collections_reject_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "pack"
            shutil.copytree(FIXTURES / "valid-pack", pack)
            manifest_path = pack / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["profiles"] = ["compose_minimum", "compose_minimum"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_pack(pack)

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn("manifest field profiles must contain unique items", summary["errors"])

    def test_manifest_paths_match_schema_pattern(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "pack"
            shutil.copytree(FIXTURES / "valid-pack", pack)
            manifest_path = pack / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["blocks"] = ["blocks/work order.json"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_pack(pack)

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn("unsafe relative path: blocks/work order.json", summary["errors"])

    def test_block_expiry_must_be_timezone_aware_iso8601(self) -> None:
        result = self.run_validator("invalid-expiry")

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn(
            "blocks/work-order.json authority.expires_at must be a timezone-aware ISO-8601 date-time",
            summary["errors"],
        )

    def test_moc_refs_must_be_a_string_array(self) -> None:
        result = self.run_validator("invalid-moc-shape")

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn("mocs/company.json field refs must be an array", summary["errors"])

    def test_unknown_spec_version_is_rejected(self) -> None:
        result = self.run_validator("invalid-spec-version")

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn("manifest spec_version must be 0.1", summary["errors"])

    def test_ids_are_unique_across_the_pack(self) -> None:
        result = self.run_validator("invalid-duplicate-id")

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn("duplicate id: duplicate-company", summary["errors"])

    def test_non_string_id_returns_structured_failure(self) -> None:
        result = self.run_validator("invalid-id-type")

        self.assertEqual(result.returncode, 1, result.stderr)
        summary = json.loads(result.stdout)
        self.assertIn("manifest field id must be a non-empty string", summary["errors"])

    def test_secret_key_variants_are_rejected(self) -> None:
        result = self.run_validator("invalid-secret-variants")

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn("secret-bearing key is forbidden: $.client_secret", summary["errors"])
        self.assertIn("secret-bearing key is forbidden: $.nested.apiKey", summary["errors"])

    def test_unreferenced_json_is_included_in_secret_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "pack"
            shutil.copytree(FIXTURES / "valid-pack", pack)
            (pack / "unlisted.json").write_text(
                json.dumps({"api_token": "placeholder"}), encoding="utf-8"
            )
            result = self.run_pack(pack)

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn(
            "secret-bearing key is forbidden: $unlisted.json.api_token",
            summary["errors"],
        )

    def test_manifest_path_schema_rejects_unsafe_relative_paths(self) -> None:
        schema = json.loads(
            (ROOT / "schemas" / "company-manifest.schema.json").read_text(
                encoding="utf-8"
            )
        )
        for collection in ("blocks", "mocs", "records"):
            pattern = re.compile(schema["properties"][collection]["items"]["pattern"])
            self.assertIsNotNone(pattern.fullmatch(f"{collection}/item.json"))
            for unsafe in (
                "../outside.json",
                "/absolute.json",
                f"{collection}/../outside.json",
                f"{collection}//item.json",
            ):
                self.assertIsNone(pattern.fullmatch(unsafe), (collection, unsafe))


if __name__ == "__main__":
    unittest.main()
