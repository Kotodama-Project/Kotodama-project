import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "check_company_pack_public_preview.py"
CREATOR = ROOT / "tools" / "create_company_pack.py"
SCHEMA = ROOT / "schemas" / "company-pack-public-preview-check.schema.json"
STARTER = ROOT / "examples" / "company-starter"
INVALID = ROOT / "tests" / "fixtures" / "invalid-manifest"


class PublicPreviewCheckTests(unittest.TestCase):
    def run_tool(self, pack: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TOOL), str(pack), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_valid_starter_is_checked_without_authority_or_runtime_claims(self) -> None:
        before = {
            path.relative_to(STARTER).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in STARTER.rglob("*")
            if path.is_file()
        }
        result = self.run_tool(STARTER)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)

        self.assertEqual(
            set(report),
            {
                "kind",
                "version",
                "status",
                "counts",
                "checks",
                "refusal_reason",
                "claims",
                "public_beta",
            },
        )
        self.assertEqual(report["kind"], "company_pack_public_preview_check")
        self.assertEqual(report["version"], "1.0")
        self.assertEqual(report["status"], "PASS")
        self.assertIsNone(report["refusal_reason"])
        self.assertEqual(
            report["counts"],
            {
                "validated_files": 22,
                "blocks": 9,
                "records": 9,
                "mocs": 3,
                "replacement_required": 42,
                "review_required": 46,
                "evidence_required": 5,
            },
        )
        self.assertEqual(
            report["checks"],
            [
                {"id": "pack_structure", "status": "PASS"},
                {"id": "catalog_projection", "status": "PASS"},
                {"id": "customization_boundary", "status": "PASS"},
                {"id": "claim_boundary", "status": "PASS"},
            ],
        )
        self.assertTrue(all(not value for value in report["claims"].values()))
        self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")
        self.assertNotIn(str(STARTER), result.stdout)
        self.assertEqual(
            before,
            {
                path.relative_to(STARTER).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in STARTER.rglob("*")
                if path.is_file()
            },
        )

    def test_output_is_deterministic_and_schema_valid(self) -> None:
        first = self.run_tool(STARTER)
        second = self.run_tool(STARTER)
        self.assertEqual(first.returncode, 0)
        self.assertEqual(second.returncode, 0)
        self.assertEqual(first.stdout, second.stdout)

        report = json.loads(first.stdout)
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(report)

    def test_generated_working_copy_exposes_the_nineteen_static_replacements(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "my-company"
            created = subprocess.run(
                [sys.executable, str(CREATOR), "my-company", str(target)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            result = self.run_tool(target)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["counts"]["replacement_required"], 19)
            self.assertEqual(report["counts"]["review_required"], 46)
            self.assertEqual(report["counts"]["evidence_required"], 5)

    def test_invalid_pack_refuses_without_echoing_path_or_validation_detail(self) -> None:
        result = self.run_tool(INVALID)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(report)
        self.assertEqual(report["status"], "REFUSED")
        self.assertEqual(report["refusal_reason"], "INVALID_PACK")
        self.assertEqual(report["counts"], {key: 0 for key in report["counts"]})
        self.assertTrue(all(check["status"] == "REFUSED" for check in report["checks"]))
        self.assertNotIn(str(INVALID), result.stdout)
        self.assertNotIn("manifest", result.stdout)
        self.assertTrue(all(not value for value in report["claims"].values()))
        self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")

    def test_non_directory_refuses_without_creating_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "not-a-directory.json"
            target.write_text("{}", encoding="utf-8")
            result = self.run_tool(target)
            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "REFUSED")
            self.assertEqual(report["refusal_reason"], "INPUT_NOT_DIRECTORY")
            self.assertNotIn(str(target), result.stdout)
            self.assertEqual(target.read_text(encoding="utf-8"), "{}")

    def test_usage_error_does_not_echo_untrusted_argument(self) -> None:
        secret_like = "sk-abcdefghijklmnopqrstuvwxyz123456"
        result = subprocess.run(
            [sys.executable, str(TOOL), secret_like],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(secret_like, result.stdout + result.stderr)

    def test_public_docs_expose_the_self_check_from_each_onboarding_surface(self) -> None:
        expected = {
            ROOT / "README.md": "docs/PUBLIC-PREVIEW-SELF-CHECK.md",
            ROOT / "STATUS.md": "docs/PUBLIC-PREVIEW-SELF-CHECK.md",
            ROOT / "docs" / "TEMPLATE-GUIDE.md": "PUBLIC-PREVIEW-SELF-CHECK.md",
            ROOT / "docs" / "STARTER-WALKTHROUGH.md": "check_company_pack_public_preview.py",
            ROOT / "docs" / "COMPANY-PACK-CATALOG.md": "PUBLIC-PREVIEW-SELF-CHECK.md",
            ROOT / "templates" / "README.md": "PUBLIC-PREVIEW-SELF-CHECK.md",
            ROOT / "examples" / "company-starter" / "README.md": "PUBLIC-PREVIEW-SELF-CHECK.md",
        }
        for path, marker in expected.items():
            with self.subTest(path=path):
                self.assertIn(marker, path.read_text(encoding="utf-8"))
        self.assertTrue((ROOT / "docs" / "PUBLIC-PREVIEW-SELF-CHECK.md").is_file())


if __name__ == "__main__":
    unittest.main()
