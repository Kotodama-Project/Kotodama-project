import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLANNER = ROOT / "tools" / "plan_company_pack_next_steps.py"
CREATOR = ROOT / "tools" / "create_company_pack.py"
STARTER = ROOT / "examples" / "company-starter"


class CompanyPackNextStepsCliTests(unittest.TestCase):
    def run_planner(
        self, pack: Path, *arguments: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(PLANNER), str(pack), *arguments],
            cwd=ROOT,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

    def create_working_copy(self, parent: Path) -> Path:
        pack = parent / "my-company"
        creation = subprocess.run(
            [sys.executable, str(CREATOR), "my-company", str(pack)],
            cwd=ROOT,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(creation.returncode, 0, creation.stdout)
        return pack

    def close_static_replacements(self, pack: Path) -> None:
        manifest_path = pack / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["human_intent_ref"] = "human-intent:governed-alpha"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        for relative in manifest["blocks"]:
            path = pack / relative
            document = json.loads(path.read_text(encoding="utf-8"))
            document["authority"]["expires_at"] = "2026-08-04T00:00:00Z"
            path.write_text(json.dumps(document), encoding="utf-8")
        for relative in manifest["records"]:
            path = pack / relative
            document = json.loads(path.read_text(encoding="utf-8"))
            document["retention"]["policy_ref"] = "retention:governed-v1"
            path.write_text(json.dumps(document), encoding="utf-8")

    def test_initialized_pack_reports_current_stage_ideal_flow_and_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            pack = self.create_working_copy(parent)
            result = self.run_planner(pack)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        plan = json.loads(result.stdout)
        self.assertEqual(plan["kind"], "company_pack_next_steps_plan")
        self.assertEqual(plan["status"], "CUSTOMIZATION_REQUIRED")
        self.assertEqual(plan["pack_id"], "my-company")
        self.assertEqual(plan["current_state"]["stage"], "STATIC_CUSTOMIZATION")
        self.assertEqual(
            plan["current_state"]["counts"],
            {
                "replacement_required": 19,
                "review_required": 46,
                "evidence_required": 5,
            },
        )
        self.assertEqual(
            [step["id"] for step in plan["ideal_flow"]],
            [
                "create_draft_copy",
                "replace_static_placeholders",
                "validate_candidate",
                "bind_exact_review_candidate",
                "governed_review",
                "collect_external_evidence",
                "separate_promotion",
            ],
        )
        self.assertEqual(
            plan["recommended_next"]["action"],
            "REPLACE_STATIC_PLACEHOLDERS",
        )
        self.assertEqual(
            plan["recommended_next"]["command"],
            "python tools/check_company_pack_customization.py PACK_DIRECTORY",
        )
        group_counts = {group["id"]: group["count"] for group in plan["groups"]}
        self.assertEqual(group_counts["human_intent_locator"], 1)
        self.assertEqual(group_counts["block_authority_windows"], 9)
        self.assertEqual(group_counts["record_retention_policies"], 9)
        self.assertEqual(group_counts["canonical_owner_review"], 9)
        self.assertEqual(group_counts["record_authority_review"], 27)
        self.assertEqual(group_counts["external_evidence"], 5)
        self.assertTrue(all(not value for value in plan["claims"].values()))
        self.assertEqual(plan["public_beta"], "NO_GO_UNPUBLISHED")

    def test_group_counts_preserve_every_checker_item(self) -> None:
        result = self.run_planner(STARTER)

        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        for category, expected in plan["current_state"]["counts"].items():
            actual = sum(
                group["count"]
                for group in plan["groups"]
                if group["category"] == category
            )
            self.assertEqual(actual, expected, category)

    def test_review_ready_pack_recommends_exact_candidate_binding_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = self.create_working_copy(Path(temporary))
            self.close_static_replacements(pack)
            result = self.run_planner(pack)

        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["status"], "READY_FOR_GOVERNED_REVIEW")
        self.assertEqual(plan["current_state"]["stage"], "CANDIDATE_BINDING")
        self.assertEqual(plan["current_state"]["counts"]["replacement_required"], 0)
        self.assertEqual(
            plan["recommended_next"]["action"], "BUILD_EXACT_REVIEW_BUNDLE"
        )
        self.assertEqual(
            plan["recommended_next"]["command"],
            "python tools/build_company_pack_review_bundle.py PACK_DIRECTORY",
        )
        self.assertFalse(plan["claims"]["human_approval_verified"])
        self.assertFalse(plan["claims"]["promotion_verified"])
        self.assertFalse(plan["claims"]["current_truth_changed"])

    def test_markdown_format_is_concise_and_names_current_ideal_and_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = self.create_working_copy(Path(temporary))
            result = self.run_planner(pack, "--format", "markdown")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("# Company Pack Next Steps", result.stdout)
        self.assertIn("現在地: `STATIC_CUSTOMIZATION`", result.stdout)
        self.assertIn("理想の流れ", result.stdout)
        self.assertIn("Human Intent locator", result.stdout)
        self.assertIn("Block authority windows", result.stdout)
        self.assertIn("Governed Record retention policies", result.stdout)
        self.assertIn(
            "python tools/check_company_pack_customization.py PACK_DIRECTORY",
            result.stdout,
        )
        self.assertIn("`NO_GO_UNPUBLISHED`", result.stdout)
        self.assertLess(len(result.stdout.splitlines()), 70)

    def test_invalid_pack_fails_closed_without_echoing_private_locator(self) -> None:
        private_locator = "human-intent:private-sensitive-client"
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
            result = self.run_planner(pack)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        self.assertNotIn(private_locator, result.stdout)
        self.assertNotIn(private_pack_id, result.stdout)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["status"], "INVALID_PACK")
        self.assertIsNone(plan["pack_id"])
        self.assertEqual(plan["current_state"]["stage"], "STRUCTURAL_REPAIR")
        self.assertEqual(plan["current_state"]["structural_status"], "FAIL")
        self.assertEqual(plan["recommended_next"]["action"], "FIX_STRUCTURE")
        self.assertEqual(
            plan["recommended_next"]["command"],
            "python tools/validate_template_pack.py PACK_DIRECTORY",
        )

    def test_markdown_is_always_written_as_utf8_despite_legacy_console_encoding(self) -> None:
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "cp1252"
        result = subprocess.run(
            [
                sys.executable,
                str(PLANNER),
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
        self.assertEqual(result.stderr, b"")
        markdown = result.stdout.decode("utf-8")
        self.assertIn("現在地", markdown)
        self.assertIn("理想の流れ", markdown)
        self.assertIn("NO_GO_UNPUBLISHED", markdown)

    def test_read_only_run_does_not_change_pack_or_create_bytecode_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            replica = Path(temporary) / "replica"
            tools = replica / "tools"
            starter = replica / "examples" / "company-starter"
            tools.mkdir(parents=True)
            for name in (
                "plan_company_pack_next_steps.py",
                "check_company_pack_customization.py",
                "validate_template_pack.py",
            ):
                shutil.copy2(ROOT / "tools" / name, tools / name)
            shutil.copytree(STARTER, starter)
            before = {
                path.relative_to(starter).as_posix(): path.read_bytes()
                for path in starter.rglob("*")
                if path.is_file()
            }

            result = subprocess.run(
                [sys.executable, str(tools / PLANNER.name), str(starter)],
                cwd=replica,
                capture_output=True,
                check=False,
            )

            after = {
                path.relative_to(starter).as_posix(): path.read_bytes()
                for path in starter.rglob("*")
                if path.is_file()
            }
            caches = list(replica.rglob("__pycache__")) + list(
                replica.rglob("*.pyc")
            )

        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(before, after)
        self.assertEqual(caches, [])

    def test_json_output_matches_closed_public_schema_shape_and_is_deterministic(self) -> None:
        first = self.run_planner(STARTER)
        second = self.run_planner(STARTER)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        plan = json.loads(first.stdout)
        schema = json.loads(
            (
                ROOT / "schemas" / "company-pack-next-steps.schema.json"
            ).read_text(encoding="utf-8")
        )

        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), set(plan))
        self.assertEqual(
            set(schema["properties"]["current_state"]["required"]),
            set(plan["current_state"]),
        )
        self.assertEqual(
            set(schema["properties"]["recommended_next"]["required"]),
            set(plan["recommended_next"]),
        )
        self.assertEqual(
            schema["properties"]["public_beta"]["const"],
            "NO_GO_UNPUBLISHED",
        )

    def test_usage_error_returns_two(self) -> None:
        result = subprocess.run(
            [sys.executable, str(PLANNER)],
            cwd=ROOT,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("usage:", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
