from __future__ import annotations

import json
import subprocess
import shutil
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "smoke_company_pack_review_chain.py"
SCHEMA = ROOT / "schemas" / "company-pack-review-chain-smoke.schema.json"
STEP_IDS = (
    "create",
    "validate",
    "catalog",
    "customization",
    "public_preview",
    "next_steps",
    "review_bundle",
    "review_bundle_verify",
    "review_request",
    "review_response",
    "review_response_verify",
    "decision_handoff",
    "decision_handoff_verify",
)


class CompanyPackReviewChainSmokeCliTests(unittest.TestCase):
    def run_smoke(self, *arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-S", "-B", str(TOOL), *arguments],
            cwd=cwd,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
            timeout=60,
        )

    def test_one_command_runs_the_closed_chain_without_caller_writes(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)

        with tempfile.TemporaryDirectory() as temporary:
            caller = Path(temporary)
            before = tuple(caller.iterdir())
            result = self.run_smoke(cwd=caller)
            after = tuple(caller.iterdir())
            repeated = self.run_smoke(cwd=caller)
            after_repeated = tuple(caller.iterdir())

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(before, after)
        self.assertEqual(before, after_repeated)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(repeated.stderr, "")
        self.assertEqual(repeated.stdout, result.stdout)
        self.assertEqual(len(result.stdout.splitlines()), 1)
        report = json.loads(result.stdout)
        Draft202012Validator(schema).validate(report)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(
            [step["id"] for step in report["steps"]], list(STEP_IDS)
        )
        self.assertTrue(all(step["status"] == "PASS" for step in report["steps"]))
        self.assertIsNone(report["failed_step"])
        self.assertIsNone(report["refusal_reason"])
        self.assertTrue(report["temporary_workspace_deleted"])
        self.assertFalse(report["artifacts_persisted"])
        self.assertFalse(any(report["claims"].values()))
        self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")
        self.assertNotIn(str(ROOT), result.stdout)
        self.assertNotIn(temporary, result.stdout)

    def test_help_and_malformed_argv_are_fixed_and_side_effect_free(self) -> None:
        boundary = (
            "Boundary: read-only/candidate-only; Public Beta remains "
            "NO_GO_UNPUBLISHED."
        )
        with tempfile.TemporaryDirectory() as temporary:
            caller = Path(temporary)
            for flag in ("-h", "--help"):
                with self.subTest(flag=flag):
                    before = tuple(caller.iterdir())
                    result = self.run_smoke(flag, cwd=caller)
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(result.stderr, "")
                    self.assertIn(boundary, result.stdout)
                    self.assertEqual(tuple(caller.iterdir()), before)

            secret_like = "api_key=do-not-reflect-this"
            before = tuple(caller.iterdir())
            malformed = self.run_smoke(secret_like, cwd=caller)
            self.assertEqual(malformed.returncode, 2)
            self.assertEqual(malformed.stdout, "")
            self.assertIn("usage: smoke_company_pack_review_chain.py", malformed.stderr)
            self.assertNotIn(secret_like, malformed.stderr)
            self.assertEqual(tuple(caller.iterdir()), before)

    def test_schema_rejects_reordered_overclaiming_or_incoherent_reports(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        with tempfile.TemporaryDirectory() as temporary:
            result = self.run_smoke(cwd=Path(temporary))
        report = json.loads(result.stdout)

        mutations = []
        reordered = deepcopy(report)
        reordered["steps"][0], reordered["steps"][1] = (
            reordered["steps"][1],
            reordered["steps"][0],
        )
        mutations.append(reordered)
        overclaim = deepcopy(report)
        overclaim["claims"]["human_approval_verified"] = True
        mutations.append(overclaim)
        incomplete_pass = deepcopy(report)
        incomplete_pass["steps"][-1]["status"] = "NOT_RUN"
        mutations.append(incomplete_pass)
        incoherent_refusal = deepcopy(report)
        incoherent_refusal["status"] = "REFUSED"
        mutations.append(incoherent_refusal)

        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.assertTrue(list(validator.iter_errors(mutation)))

    def test_public_docs_expose_the_one_command_smoke_and_boundaries(self) -> None:
        surfaces = {
            "README.md": (ROOT / "README.md").read_text(encoding="utf-8"),
            "docs/STARTER-WALKTHROUGH.md": (
                ROOT / "docs" / "STARTER-WALKTHROUGH.md"
            ).read_text(encoding="utf-8"),
            "docs/SCHEMA-VALIDATOR-MATRIX.md": (
                ROOT / "docs" / "SCHEMA-VALIDATOR-MATRIX.md"
            ).read_text(encoding="utf-8"),
        }
        commands = (
            "python -S -B tools/smoke_company_pack_review_chain.py",
            "python3 -S -B tools/smoke_company_pack_review_chain.py",
        )
        for path, document in surfaces.items():
            with self.subTest(path=path):
                for command in commands:
                    self.assertIn(command, document)
                for marker in (
                    "13",
                    "temporary",
                    "NO_GO_UNPUBLISHED",
                    "Human approval",
                    "runtime",
                    "Promotion",
                    "Current Truth",
                    "Public Beta GO",
                ):
                    self.assertIn(marker, document)

        matrix = surfaces["docs/SCHEMA-VALIDATOR-MATRIX.md"]
        for relative in (
            "../tools/smoke_company_pack_review_chain.py",
            "../schemas/company-pack-review-chain-smoke.schema.json",
            "../tests/test_company_pack_review_chain_smoke_cli.py",
        ):
            self.assertIn(relative, matrix)
            self.assertTrue((ROOT / "docs" / relative).resolve().is_file())

    def test_missing_child_is_a_closed_refusal_after_temporary_cleanup(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            replica = Path(temporary) / "replica"
            replica.mkdir()
            for directory in ("tools", "schemas", "examples"):
                shutil.copytree(ROOT / directory, replica / directory)
            (replica / "tools" / "catalog_company_pack.py").unlink()
            caller = Path(temporary) / "caller"
            caller.mkdir()
            before = tuple(caller.iterdir())
            result = subprocess.run(
                [
                    sys.executable,
                    "-S",
                    "-B",
                    str(replica / "tools" / "smoke_company_pack_review_chain.py"),
                ],
                cwd=caller,
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
                timeout=60,
            )
            after = tuple(caller.iterdir())

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        self.assertEqual(before, after)
        report = json.loads(result.stdout)
        Draft202012Validator(schema).validate(report)
        self.assertEqual(report["status"], "REFUSED")
        self.assertEqual(report["failed_step"], "catalog")
        self.assertEqual(report["refusal_reason"], "CHILD_REFUSED")
        self.assertTrue(report["temporary_workspace_deleted"])
        self.assertFalse(report["artifacts_persisted"])
        self.assertFalse(any(report["claims"].values()))
        self.assertNotIn(str(replica), result.stdout)
        self.assertNotIn(str(caller), result.stdout)

    def test_oversized_child_output_is_bounded_and_never_reflected(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            replica = Path(temporary) / "replica"
            replica.mkdir()
            for directory in ("tools", "schemas", "examples"):
                shutil.copytree(ROOT / directory, replica / directory)
            catalog = replica / "tools" / "catalog_company_pack.py"
            catalog.write_text(
                "import sys\nsys.stdout.buffer.write(b'x' * (2 * 1024 * 1024))\n",
                encoding="utf-8",
            )
            caller = Path(temporary) / "caller"
            caller.mkdir()
            before = tuple(caller.iterdir())
            result = subprocess.run(
                [
                    sys.executable,
                    "-S",
                    "-B",
                    str(replica / "tools" / "smoke_company_pack_review_chain.py"),
                ],
                cwd=caller,
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
                timeout=60,
            )
            after = tuple(caller.iterdir())

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        self.assertEqual(before, after)
        self.assertLess(len(result.stdout.encode("utf-8")), 4096)
        report = json.loads(result.stdout)
        Draft202012Validator(schema).validate(report)
        self.assertEqual(report["status"], "REFUSED")
        self.assertEqual(report["failed_step"], "catalog")
        self.assertEqual(report["refusal_reason"], "CHILD_OUTPUT_LIMIT")
        self.assertTrue(report["temporary_workspace_deleted"])
        self.assertNotIn("x" * 32, result.stdout)


if __name__ == "__main__":
    unittest.main()
