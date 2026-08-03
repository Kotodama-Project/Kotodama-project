import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "tools" / "catalog_company_pack.py"
SCHEMA = ROOT / "schemas" / "company-pack-catalog.schema.json"
STARTER = ROOT / "examples" / "company-starter"


class CompanyPackCatalogCliTests(unittest.TestCase):
    def run_catalog(
        self, pack: Path, *arguments: str, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CATALOG), str(pack), *arguments],
            cwd=ROOT,
            encoding="utf-8",
            capture_output=True,
            check=False,
            env=env,
        )

    def test_shipped_starter_catalog_is_closed_and_schema_valid(self) -> None:
        result = self.run_catalog(STARTER)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        catalog = json.loads(result.stdout)
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(catalog)

        self.assertEqual(catalog["kind"], "company_pack_catalog")
        self.assertEqual(catalog["version"], "1.0")
        self.assertEqual(catalog["status"], "PASS")
        self.assertEqual(catalog["pack_id"], "kotodama-company-starter")
        self.assertEqual(catalog["counts"], {
            "blocks": 9,
            "records": 9,
            "mocs": 3,
            "validated_files": 22,
        })
        self.assertEqual(
            [entry["block_id"] for entry in catalog["flow"]],
            [
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
        self.assertEqual(
            [entry["position"] for entry in catalog["flow"]],
            list(range(1, 10)),
        )
        self.assertEqual(
            {entry["artifact"] for entry in catalog["records"]},
            {
                "source_record",
                "intent_candidate",
                "decision_record",
                "work_order_candidate",
                "capability_grant_candidate",
                "change_candidate",
                "verification_receipt",
                "promotion_candidate",
                "promotion_decision_record",
            },
        )
        self.assertFalse(any(catalog["claims"].values()))
        self.assertEqual(catalog["public_beta"], "NO_GO_UNPUBLISHED")

    def test_catalog_is_deterministic_and_does_not_change_pack(self) -> None:
        before = {
            path.relative_to(STARTER).as_posix(): path.read_bytes()
            for path in STARTER.rglob("*")
            if path.is_file()
        }
        first = self.run_catalog(STARTER)
        second = self.run_catalog(STARTER)
        after = {
            path.relative_to(STARTER).as_posix(): path.read_bytes()
            for path in STARTER.rglob("*")
            if path.is_file()
        }

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(before, after)
        self.assertEqual(
            list(STARTER.rglob("__pycache__")) + list(STARTER.rglob("*.pyc")),
            [],
        )

    def test_catalog_exposes_moc_navigation_positions_and_record_mapping(self) -> None:
        result = self.run_catalog(STARTER)
        catalog = json.loads(result.stdout)

        mocs = {entry["id"]: entry for entry in catalog["mocs"]}
        self.assertEqual(mocs["company-operations-starter"]["flow_positions"], list(range(1, 10)))
        self.assertEqual(
            mocs["public-release-starter"]["flow_positions"],
            [1, 3, 4, 5, 6, 7, 8, 9],
        )
        self.assertEqual(
            mocs["incident-recovery-starter"]["flow_positions"],
            [1, 4, 5, 6, 7],
        )
        by_block = {entry["block_id"]: entry for entry in catalog["flow"]}
        self.assertEqual(
            by_block["source-intake-starter"]["record_artifacts"],
            ["source_record"],
        )
        self.assertEqual(
            by_block["promotion-decision-starter"]["record_artifacts"],
            ["promotion_decision_record"],
        )

    def test_markdown_catalog_is_human_oriented_and_explicitly_non_authorizing(self) -> None:
        result = self.run_catalog(STARTER, "--format", "markdown")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# Company Pack Catalog", result.stdout)
        self.assertIn("Blocks:", result.stdout)
        self.assertIn("Records:", result.stdout)
        self.assertIn("MOCs:", result.stdout)
        self.assertIn("source-intake-starter", result.stdout)
        self.assertIn("Public Release Review Starter", result.stdout)
        self.assertIn("Human approval", result.stdout)
        self.assertIn("NO_GO_UNPUBLISHED", result.stdout)
        self.assertLess(len(result.stdout.splitlines()), 100)

    def test_invalid_pack_fails_closed_without_echoing_private_values(self) -> None:
        private_locator = "human-intent:private-catalog-source"
        private_pack_id = "sk-AAAAAAAAAAAAAAAAAAAA"
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "pack"
            shutil.copytree(STARTER, pack)
            manifest_path = pack / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["id"] = private_pack_id
            manifest["human_intent_ref"] = private_locator
            del manifest["profiles"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_catalog(pack)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        self.assertNotIn(private_locator, result.stdout)
        self.assertNotIn(private_pack_id, result.stdout)
        catalog = json.loads(result.stdout)
        self.assertEqual(catalog["status"], "INVALID_PACK")
        self.assertIsNone(catalog["pack_id"])
        self.assertEqual(catalog["blocks"], [])
        self.assertEqual(catalog["mocs"], [])
        self.assertEqual(catalog["records"], [])
        self.assertGreater(catalog["validation"]["error_count"], 0)
        self.assertFalse(any(catalog["claims"].values()))

    def test_markdown_output_is_utf8_even_when_console_encoding_is_legacy(self) -> None:
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "cp1252"
        result = subprocess.run(
            [
                sys.executable,
                str(CATALOG),
                str(STARTER),
                "--format",
                "markdown",
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        markdown = result.stdout.decode("utf-8")
        self.assertIn("現在地", markdown)
        self.assertIn("MOCs", markdown)

    def test_usage_error_returns_two_without_catalog_output(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CATALOG)],
            cwd=ROOT,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("usage:", result.stderr.lower())

    def test_unknown_format_is_usage_error_without_echoing_secret_like_argument(self) -> None:
        secret_like = "sk-r39-catalog-secret"
        result = subprocess.run(
            [
                sys.executable,
                str(CATALOG),
                str(STARTER),
                "--format",
                secret_like,
            ],
            cwd=ROOT,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("usage:", result.stderr.lower())
        self.assertIn("invalid command-line arguments", result.stderr)
        self.assertNotIn(secret_like, result.stderr)

    def test_schema_is_closed_at_top_level(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["public_beta"]["const"], "NO_GO_UNPUBLISHED")
        self.assertEqual(
            set(schema["properties"]["claims"]["properties"]),
            {
                "catalog_is_authoritative",
                "human_approval_verified",
                "runtime_verified",
                "promotion_verified",
                "current_truth_changed",
            },
        )

    def test_catalog_runbook_and_starter_links_are_discoverable(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        starter_readme = (STARTER / "README.md").read_text(encoding="utf-8")
        runbook_path = ROOT / "docs" / "COMPANY-PACK-CATALOG.md"
        runbook = runbook_path.read_text(encoding="utf-8")

        self.assertIn("tools/catalog_company_pack.py", readme)
        self.assertIn("docs/COMPANY-PACK-CATALOG.md", readme)
        self.assertIn("tools/catalog_company_pack.py", starter_readme)
        self.assertIn("../../docs/COMPANY-PACK-CATALOG.md", starter_readme)
        self.assertIn("read-only", runbook)
        self.assertIn("NO_GO_UNPUBLISHED", runbook)
        self.assertIn("invalid command-line arguments", runbook)
        self.assertIn("Blocks", runbook)
        self.assertIn("MOCs", runbook)


if __name__ == "__main__":
    unittest.main()
