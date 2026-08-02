import json
import shutil
import tempfile
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "tools" / "check_company_pack_customization.py"
CREATOR = ROOT / "tools" / "create_company_pack.py"
STARTER = ROOT / "examples" / "company-starter"


class CompanyPackCustomizationCliTests(unittest.TestCase):
    def run_checker(self, pack: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHECKER), str(pack)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_shipped_starter_reports_every_required_customization(self) -> None:
        result = self.run_checker(STARTER)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(report["kind"], "company_pack_customization_report")
        self.assertEqual(report["status"], "CUSTOMIZATION_REQUIRED")
        self.assertEqual(report["pack_id"], "kotodama-company-starter")
        self.assertEqual(report["structural_validation"]["status"], "PASS")
        self.assertEqual(report["structural_validation"]["validated_files"], 22)
        self.assertEqual(
            report["counts"],
            {
                "replacement_required": 42,
                "review_required": 46,
                "evidence_required": 5,
            },
        )
        replacement_paths = {
            item["path"]
            for item in report["items"]
            if item["category"] == "replacement_required"
        }
        self.assertIn("manifest.json#/id", replacement_paths)
        self.assertIn("manifest.json#/human_intent_ref", replacement_paths)
        self.assertIn(
            "blocks/source-intake.json#/authority/expires_at", replacement_paths
        )
        self.assertIn(
            "records/source-record.json#/retention/policy_ref", replacement_paths
        )
        self.assertFalse(report["claims"]["human_approval_verified"])
        self.assertFalse(report["claims"]["promotion_verified"])
        self.assertFalse(report["claims"]["current_truth_changed"])
        self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")

    def test_replaced_placeholders_only_reach_governed_review(self) -> None:
        private_locator = "human-intent:internal-project-alpha"
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "work"
            parent.mkdir()
            pack = parent / "my-company"
            creation = subprocess.run(
                [sys.executable, str(CREATOR), "my-company", str(pack)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(creation.returncode, 0, creation.stdout)

            manifest_path = pack / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["status"] = "draft"
            manifest["human_intent_ref"] = private_locator
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            for collection in ("blocks", "mocs", "records"):
                for relative in manifest[collection]:
                    path = pack / relative
                    document = json.loads(path.read_text(encoding="utf-8"))
                    document["status"] = "draft"
                    if collection == "blocks":
                        document["authority"]["expires_at"] = (
                            "2026-09-01T00:00:00Z"
                        )
                    if collection == "records":
                        document["retention"]["policy_ref"] = (
                            "retention-policy:internal-v1"
                        )
                    path.write_text(json.dumps(document), encoding="utf-8")

            result = self.run_checker(pack)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn(private_locator, result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "READY_FOR_GOVERNED_REVIEW")
        self.assertEqual(
            report["counts"],
            {
                "replacement_required": 0,
                "review_required": 46,
                "evidence_required": 5,
            },
        )
        self.assertTrue(all(not value for value in report["claims"].values()))
        self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")

    def test_initialized_working_copy_only_has_organization_specific_replacements(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "work"
            parent.mkdir()
            pack = parent / "my-company"
            creation = subprocess.run(
                [sys.executable, str(CREATOR), "my-company", str(pack)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(creation.returncode, 0, creation.stdout)
            result = self.run_checker(pack)

        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "CUSTOMIZATION_REQUIRED")
        self.assertEqual(
            report["counts"],
            {
                "replacement_required": 19,
                "review_required": 46,
                "evidence_required": 5,
            },
        )
        self.assertTrue(
            all(
                not item["path"].endswith("#/status")
                for item in report["items"]
                if item["category"] == "replacement_required"
            )
        )

    def test_customization_report_schema_matches_the_public_output(self) -> None:
        result = self.run_checker(STARTER)
        report = json.loads(result.stdout)
        schema = json.loads(
            (
                ROOT / "schemas" / "customization-report.schema.json"
            ).read_text(encoding="utf-8")
        )

        self.assertEqual(set(schema["required"]), set(report))
        self.assertEqual(
            set(schema["properties"]["counts"]["required"]),
            set(report["counts"]),
        )
        self.assertEqual(
            set(schema["properties"]["claims"]["required"]),
            set(report["claims"]),
        )
        self.assertEqual(
            schema["properties"]["public_beta"]["const"],
            "NO_GO_UNPUBLISHED",
        )

    def test_structurally_invalid_pack_stops_before_customization_review(self) -> None:
        private_locator = "human-intent:private-sensitive-client"
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "pack"
            shutil.copytree(STARTER, pack)
            manifest_path = pack / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["human_intent_ref"] = private_locator
            del manifest["profiles"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_checker(pack)

        self.assertEqual(result.returncode, 1)
        self.assertNotIn(private_locator, result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "INVALID_PACK")
        self.assertEqual(report["structural_validation"]["status"], "FAIL")
        self.assertEqual(
            report["counts"],
            {
                "replacement_required": 0,
                "review_required": 0,
                "evidence_required": 0,
            },
        )
        self.assertEqual(report["items"], [])
        self.assertTrue(all(not value for value in report["claims"].values()))

    def test_invalid_non_string_pack_id_is_redacted_to_null(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "pack"
            shutil.copytree(STARTER, pack)
            manifest_path = pack / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["id"] = ["private", "unexpected"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_checker(pack)

        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "INVALID_PACK")
        self.assertIsNone(report["pack_id"])
        self.assertIsNone(report["structural_validation"]["pack_id"])


if __name__ == "__main__":
    unittest.main()
