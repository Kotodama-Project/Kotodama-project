from __future__ import annotations

import importlib.util
import json
import pathlib
import shutil
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "validate_cloudflare_edge_candidate.py"
SPEC = importlib.util.spec_from_file_location("cloudflare_edge_validator", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class CloudflareEdgeCandidateTests(unittest.TestCase):
    def test_candidate_is_fail_closed_and_non_production(self) -> None:
        self.assertEqual([], MODULE.validate())

    def test_runtime_contract_is_date_safe_and_logging_disabled(self) -> None:
        config = MODULE.load_jsonc(MODULE.CONFIG)
        self.assertEqual("2026-08-07", config["compatibility_date"])
        self.assertFalse(config["observability"]["enabled"])
        self.assertFalse(config["observability"]["logs"]["enabled"])

    def test_wrangler_supply_chain_binding_is_exact(self) -> None:
        integrity = json.loads(MODULE.WRANGLER_INTEGRITY.read_text(encoding="utf-8"))
        self.assertEqual("4.120.0", integrity["version"])
        self.assertEqual(
            "sha512-cBmu/MeaB/fPacC0JpATs4duTOCagBxrZo+vBzuTX06tLzwSyAHE1drlHUZ8rP0VqVz1fy3ReGYTiHdKkoHltg==",
            integrity["npm_integrity"],
        )
        self.assertEqual("pkg:npm/wrangler@4.120.0", integrity["slsa_subject"])

    def test_only_manual_preview_upload_is_declared(self) -> None:
        workflow = MODULE.WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("versions upload --env preview", workflow)
        self.assertIn('wranglerVersion: "4.120.0"', workflow)
        self.assertNotIn("wrangler deploy", workflow)
        self.assertNotIn("versions deploy", workflow)

    def test_workflow_uses_trusted_validation_before_environment_upload(self) -> None:
        workflow = MODULE.WORKFLOW.read_text(encoding="utf-8")
        for guard in (
            "refs/heads/main",
            "^[0-9a-f]{40}$",
            "refs/remotes/origin/codex/cloudflare-os-foundation",
            "path: trusted",
            "path: candidate",
            "trusted/tools/validate_cloudflare_edge_candidate.py --root candidate",
            "needs: validate-candidate",
            "environment: cloudflare-preview",
        ):
            self.assertIn(guard, workflow)

    def test_workflow_refuses_historical_allowed_branch_ancestors(self) -> None:
        workflow = MODULE.WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(
            2,
            workflow.count(
                'test "$(git rev-parse refs/remotes/origin/codex/cloudflare-os-foundation)" '
                '= "$CANDIDATE_SHA"',
            ),
        )
        validation_job, upload_job = workflow.split("  upload-preview-version:", 1)
        self.assertEqual(1, validation_job.count("git rev-parse refs/remotes/origin/codex/cloudflare-os-foundation"))
        self.assertEqual(1, upload_job.count("git rev-parse refs/remotes/origin/codex/cloudflare-os-foundation"))
        self.assertNotIn("git merge-base --is-ancestor", workflow)

    def test_validator_refuses_ancestor_only_branch_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = pathlib.Path(temporary)
            shutil.copytree(ROOT / "runtime", candidate / "runtime")
            shutil.copytree(ROOT / ".github", candidate / ".github")
            workflow_path = candidate / ".github" / "workflows" / "cloudflare-edge-preview.yml"
            workflow = workflow_path.read_text(encoding="utf-8")
            exact_tip_guard = (
                'test "$(git rev-parse refs/remotes/origin/codex/cloudflare-os-foundation)" '
                '= "$CANDIDATE_SHA"'
            )
            workflow_path.write_text(
                workflow.replace(exact_tip_guard, "git merge-base --is-ancestor", 1),
                encoding="utf-8",
            )
            errors = MODULE.validate(candidate)
            self.assertIn(
                "workflow must bind both validation and upload jobs to the exact allowed branch tip",
                errors,
            )
            self.assertIn(
                "workflow must place one exact allowed-branch-tip guard in each validation and upload job",
                errors,
            )
            self.assertIn(
                "workflow contains forbidden automatic/production action: git merge-base --is-ancestor",
                errors,
            )

    def test_validator_refuses_future_compatibility_date(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = pathlib.Path(temporary)
            shutil.copytree(ROOT / "runtime", candidate / "runtime")
            shutil.copytree(ROOT / ".github", candidate / ".github")
            config_path = candidate / "runtime" / "cloudflare-edge" / "wrangler.jsonc"
            config = MODULE.load_jsonc(config_path)
            config["compatibility_date"] = "2026-08-08"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            self.assertIn(
                "compatibility_date must equal the verified UTC-safe date 2026-08-07",
                MODULE.validate(candidate),
            )

    def test_validator_refuses_wrangler_integrity_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = pathlib.Path(temporary)
            shutil.copytree(ROOT / "runtime", candidate / "runtime")
            shutil.copytree(ROOT / ".github", candidate / ".github")
            integrity_path = candidate / "runtime" / "cloudflare-edge" / "wrangler-integrity.json"
            integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
            integrity["version"] = "4.119.0"
            integrity_path.write_text(json.dumps(integrity), encoding="utf-8")
            self.assertIn(
                "Wrangler supply-chain binding does not match verified 4.120.0 metadata",
                MODULE.validate(candidate),
            )


if __name__ == "__main__":
    unittest.main()
