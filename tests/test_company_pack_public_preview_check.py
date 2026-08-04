import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError


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

    def test_schema_rejects_inconsistent_status_shape(self) -> None:
        result = self.run_tool(STARTER)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema, format_checker=FormatChecker())

        tampered_cases = (
            {"status": "REFUSED"},
            {"refusal_reason": "INVALID_PACK"},
            {"checks": [{"id": "pack_structure", "status": "REFUSED"}]},
            {"counts": {"blocks": 0}},
        )
        for mutation in tampered_cases:
            with self.subTest(mutation=mutation):
                tampered = json.loads(json.dumps(report))
                if "checks" in mutation:
                    tampered["checks"][0] = mutation["checks"][0]
                elif "counts" in mutation:
                    tampered["counts"].update(mutation["counts"])
                else:
                    tampered.update(mutation)
                with self.assertRaises(ValidationError):
                    validator.validate(tampered)

    def test_markdown_output_is_deterministic_and_preserves_claim_boundary(self) -> None:
        first = self.run_tool(STARTER, "--format", "markdown")
        second = self.run_tool(STARTER, "--format", "markdown")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertTrue(first.stdout.startswith("# Company Pack Public Preview self-check\n"))
        for marker in (
            "- Status: `PASS`",
            "- Public Beta: `NO_GO_UNPUBLISHED`",
            "## Counts",
            "| `validated_files` | 22 |",
            "| `blocks` | 9 |",
            "| `records` | 9 |",
            "| `mocs` | 3 |",
            "## Checks",
            "| `pack_structure` | `PASS` |",
            "| `claim_boundary` | `PASS` |",
            "## Claims",
            "| `human_approval_verified` | `false` |",
            "| `public_beta_go` | `false` |",
            "read-only",
        ):
            self.assertIn(marker, first.stdout)
        self.assertNotIn(str(STARTER), first.stdout)

    def test_markdown_refusal_is_fixed_and_does_not_echo_input(self) -> None:
        result = self.run_tool(INVALID, "--format", "markdown")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        self.assertTrue(result.stdout.startswith("# Company Pack Public Preview self-check\n"))
        self.assertIn("- Status: `REFUSED`", result.stdout)
        self.assertIn("- Refusal reason: `INVALID_PACK`", result.stdout)
        self.assertIn("| `validated_files` | 0 |", result.stdout)
        self.assertIn("| `pack_structure` | `REFUSED` |", result.stdout)
        self.assertIn("| `public_beta_go` | `false` |", result.stdout)
        self.assertNotIn(str(INVALID), result.stdout)
        self.assertNotIn("manifest", result.stdout)

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

    def test_validator_pass_recordless_pack_remains_preview_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "recordless-company"
            shutil.copytree(STARTER, pack)
            manifest_path = pack / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.pop("records")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            result = self.run_tool(pack)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator(schema=schema).validate(report)
        self.assertIn("may omit optional manifest.records", schema["$comment"])
        self.assertEqual(report["status"], "PASS")
        self.assertIsNone(report["refusal_reason"])
        self.assertEqual(report["counts"]["records"], 0)
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
        self.assertNotIn(str(pack), result.stdout)

    def test_validator_pass_recordless_markdown_preserves_preview_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "recordless-company"
            shutil.copytree(STARTER, pack)
            manifest_path = pack / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.pop("records")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            before = {
                path.relative_to(pack).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in pack.rglob("*")
                if path.is_file()
            }

            result = subprocess.run(
                [sys.executable, str(TOOL), str(pack), "--format", "markdown"],
                cwd=ROOT,
                capture_output=True,
                check=False,
            )
            markdown = result.stdout.decode("utf-8")
            stderr = result.stderr.decode("utf-8")
            after = {
                path.relative_to(pack).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in pack.rglob("*")
                if path.is_file()
            }

        self.assertEqual(result.returncode, 0, stderr)
        self.assertEqual(stderr, "")
        self.assertIn("- Status: `PASS`", markdown)
        self.assertIn("- Public Beta: `NO_GO_UNPUBLISHED`", markdown)
        self.assertIn("| `records` | 0 |", markdown)
        self.assertEqual(markdown.count("| `PASS` |"), 4)
        for claim in (
            "human_approval_verified",
            "runtime_verified",
            "promotion_verified",
            "current_truth_changed",
            "public_beta_go",
        ):
            self.assertIn(f"| `{claim}` | `false` |", markdown)
        self.assertNotIn(str(pack), markdown)
        self.assertNotIn("manifest", markdown)
        self.assertEqual(before, after)

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

    def test_unknown_output_format_is_usage_error_without_echo(self) -> None:
        secret_like = "sk-unknown-format-secret"
        result = self.run_tool(STARTER, "--format", secret_like)
        self.assertEqual(result.returncode, 2)
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
        for path in (
            ROOT / "README.md",
            ROOT / "STATUS.md",
            ROOT / "docs" / "PUBLIC-PREVIEW-SELF-CHECK.md",
            ROOT / "docs" / "STARTER-WALKTHROUGH.md",
            ROOT / "docs" / "TEMPLATE-GUIDE.md",
            ROOT / "docs" / "COMPANY-PACK-CATALOG.md",
            ROOT / "examples" / "company-starter" / "README.md",
        ):
            with self.subTest(markdown_surface=path):
                self.assertIn("--format markdown", path.read_text(encoding="utf-8"))

    def test_template_guide_and_self_check_expose_guided_next_steps(self) -> None:
        expected = {
            ROOT / "docs" / "TEMPLATE-GUIDE.md": "[Company Pack Guided Next Steps](COMPANY-PACK-NEXT-STEPS.md)",
            ROOT / "docs" / "PUBLIC-PREVIEW-SELF-CHECK.md": "[Company Pack Guided Next Steps](COMPANY-PACK-NEXT-STEPS.md)",
        }
        for path, marker in expected.items():
            with self.subTest(path=path):
                document = path.read_text(encoding="utf-8")
                self.assertIn(marker, document)
                self.assertIn("read-only/candidate-only", document)
                self.assertIn("NO_GO_UNPUBLISHED", document)
                self.assertTrue((path.parent / "COMPANY-PACK-NEXT-STEPS.md").is_file())

        guide = (ROOT / "docs" / "TEMPLATE-GUIDE.md").read_text(encoding="utf-8")
        self_check = (ROOT / "docs" / "PUBLIC-PREVIEW-SELF-CHECK.md").read_text(
            encoding="utf-8"
        )
        ordered_markers = (
            "[Company Pack Catalog](COMPANY-PACK-CATALOG.md)",
            "[Company Pack Guided Next Steps](COMPANY-PACK-NEXT-STEPS.md)",
            "[Starter Walkthrough](STARTER-WALKTHROUGH.md)",
        )
        for name, document in (("template guide", guide), ("self-check", self_check)):
            with self.subTest(surface=name):
                positions = [document.index(marker) for marker in ordered_markers]
                self.assertEqual(positions, sorted(positions))

    def test_public_preview_self_check_has_posix_working_copy_and_markdown_parity(self) -> None:
        runbook = (ROOT / "docs" / "PUBLIC-PREVIEW-SELF-CHECK.md").read_text(
            encoding="utf-8"
        )
        command_pairs = (
            (
                r"python tools\check_company_pack_public_preview.py examples\company-starter --format markdown",
                "python3 tools/check_company_pack_public_preview.py examples/company-starter --format markdown",
            ),
            (
                r"python tools\create_company_pack.py my-company work\my-company",
                "python3 tools/create_company_pack.py my-company work/my-company",
            ),
            (
                r"python tools\check_company_pack_public_preview.py work\my-company",
                "python3 tools/check_company_pack_public_preview.py work/my-company",
            ),
        )
        for powershell_command, posix_command in command_pairs:
            with self.subTest(powershell_command=powershell_command):
                self.assertIn(powershell_command, runbook)
                self.assertIn(posix_command, runbook)

        self.assertIn("New-Item -ItemType Directory -Force work | Out-Null", runbook)
        self.assertIn("mkdir -p work", runbook)
        self.assertIn("POSIX shell", runbook)
        self.assertIn("NO_GO_UNPUBLISHED", runbook)

        ordered_markers = (
            "python3 tools/check_company_pack_public_preview.py examples/company-starter --format markdown",
            "python3 tools/create_company_pack.py my-company work/my-company",
            "python3 tools/check_company_pack_public_preview.py work/my-company",
        )
        positions = [runbook.index(marker) for marker in ordered_markers]
        self.assertEqual(positions, sorted(positions))


if __name__ == "__main__":
    unittest.main()
