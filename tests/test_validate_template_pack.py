import json
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
        self.assertEqual(summary["validated_files"], 8)

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
                "blocks/verification-receipt.json",
                "blocks/promotion-gate.json",
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
                "verification-receipt-starter",
                "promotion-gate-starter",
            ],
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
                    "candidate_revision",
                ],
                "sequence": [
                    "source-intake-starter",
                    "intent-candidate-starter",
                    "human-decision-starter",
                    "work-order-starter",
                    "verification-receipt-starter",
                    "promotion-gate-starter",
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
                "verification-receipt-starter",
                "promotion-gate-starter",
            ]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_pack(pack)

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn(
            "manifest flow block work-order-starter has unavailable input: decision_record",
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


if __name__ == "__main__":
    unittest.main()
