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
    def copy_candidate(self, temporary: str) -> pathlib.Path:
        candidate = pathlib.Path(temporary)
        shutil.copytree(ROOT / "runtime", candidate / "runtime")
        shutil.copytree(ROOT / ".github", candidate / ".github")
        return candidate

    def test_candidate_is_fail_closed_and_non_production(self) -> None:
        self.assertEqual([], MODULE.validate())

    def test_runtime_contract_is_exact_and_logging_disabled(self) -> None:
        config = MODULE.load_jsonc(MODULE.CONFIG)
        self.assertEqual(MODULE.VERIFIED_CONFIG, config)
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

    def test_only_manual_hardened_preview_upload_is_declared(self) -> None:
        workflow = MODULE.WORKFLOW.read_text(encoding="utf-8")
        command = (
            "versions upload --config wrangler.jsonc --env preview --no-bundle --strict "
            "--x-provision=false --x-auto-create=false"
        )
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn(command, workflow)
        self.assertIn('wranglerVersion: "4.120.0"', workflow)
        self.assertIn("packageManager: npm", workflow)
        self.assertNotIn("--preview-alias", workflow)
        self.assertNotIn("wrangler deploy", workflow)
        self.assertNotIn("versions deploy", workflow)

    def test_worker_surface_is_content_free_and_voice_closed(self) -> None:
        worker = MODULE.WORKER.read_text(encoding="utf-8")
        for marker in (
            '"/healthz"',
            '"/version"',
            '"runtime_configuration_denied"',
            '"NO_GO_UNPUBLISHED"',
            "current_truth_mutation: false",
        ):
            self.assertIn(marker, worker)
        for marker in (
            '"/voice/review"',
            "CONTEXT_GATEWAY",
            "cf-access-jwt-assertion",
            "fetch(",
            "request.arrayBuffer(",
        ):
            self.assertNotIn(marker, worker)

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

    def test_trusted_validator_is_bound_to_the_dispatch_revision(self) -> None:
        workflow = MODULE.WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("ref: ${{ github.sha }}", workflow)
        self.assertNotIn("github.event.repository.default_branch", workflow)

    def test_workflow_refuses_historical_allowed_branch_ancestors(self) -> None:
        workflow = MODULE.WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(
            2,
            workflow.count(
                'test "$(git rev-parse refs/remotes/origin/codex/cloudflare-os-foundation)" '
                '= "$CANDIDATE_SHA"'
            ),
        )
        validation_job, upload_job = workflow.split("  upload-preview-version:", 1)
        self.assertEqual(1, validation_job.count("git rev-parse refs/remotes/origin/codex/cloudflare-os-foundation"))
        self.assertEqual(1, upload_job.count("git rev-parse refs/remotes/origin/codex/cloudflare-os-foundation"))
        self.assertNotIn("git merge-base --is-ancestor", workflow)

    def test_validator_refuses_ancestor_only_branch_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = self.copy_candidate(temporary)
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
            candidate = self.copy_candidate(temporary)
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
            candidate = self.copy_candidate(temporary)
            integrity_path = candidate / "runtime" / "cloudflare-edge" / "wrangler-integrity.json"
            integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
            integrity["version"] = "4.119.0"
            integrity_path.write_text(json.dumps(integrity), encoding="utf-8")
            self.assertIn(
                "Wrangler supply-chain binding does not match verified 4.120.0 metadata",
                MODULE.validate(candidate),
            )

    def test_validator_refuses_preview_environment_provider_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = self.copy_candidate(temporary)
            config_path = candidate / "runtime" / "cloudflare-edge" / "wrangler.jsonc"
            config = MODULE.load_jsonc(config_path)
            config["env"]["preview"]["r2_buckets"] = [
                {"binding": "PRIVATE_DATA", "bucket_name": "private-data"}
            ]
            config_path.write_text(json.dumps(config), encoding="utf-8")
            self.assertIn(
                "preview environment contains forbidden provider/data/build bindings: ['r2_buckets']",
                MODULE.validate(candidate),
            )

    def test_validator_refuses_preview_environment_observability_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = self.copy_candidate(temporary)
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

    def test_validator_refuses_generated_config_redirect_at_each_candidate_ancestor(self) -> None:
        for relative in (pathlib.Path(".wrangler"), pathlib.Path("runtime") / ".wrangler"):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temporary:
                candidate = self.copy_candidate(temporary)
                redirect = candidate / relative / "deploy" / "config.json"
                redirect.parent.mkdir(parents=True)
                redirect.write_text('{"configPath":"malicious.jsonc"}', encoding="utf-8")
                self.assertIn(
                    "candidate-controlled Wrangler/build path is forbidden: "
                    f"{relative.as_posix()}",
                    MODULE.validate(candidate),
                )

    def test_validator_refuses_ancestor_node_modules_and_npm_shrinkwrap(self) -> None:
        for relative in (
            pathlib.Path("node_modules"),
            pathlib.Path("runtime") / "npm-shrinkwrap.json",
        ):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temporary:
                candidate = self.copy_candidate(temporary)
                path = candidate / relative
                if path.suffix:
                    path.write_text('{"scripts":{"preinstall":"printenv"}}', encoding="utf-8")
                else:
                    path.mkdir()
                self.assertIn(
                    "candidate-controlled Wrangler/build path is forbidden: "
                    f"{relative.as_posix()}",
                    MODULE.validate(candidate),
                )

    def test_validator_refuses_custom_build_and_additional_provider_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = self.copy_candidate(temporary)
            config_path = candidate / "runtime" / "cloudflare-edge" / "wrangler.jsonc"
            config = MODULE.load_jsonc(config_path)
            config["build"] = {"command": "printenv"}
            config["analytics_engine_datasets"] = [{"binding": "EVENTS", "dataset": "events"}]
            config_path.write_text(json.dumps(config), encoding="utf-8")
            errors = MODULE.validate(candidate)
            self.assertIn(
                "top-level provider/data/build bindings are forbidden: "
                "['analytics_engine_datasets', 'build']",
                errors,
            )
            self.assertIn("Wrangler config must match the closed content-free preview shape", errors)

    def test_validator_refuses_extra_deploy_surface_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = self.copy_candidate(temporary)
            package = candidate / "runtime" / "cloudflare-edge" / "package.json"
            package.write_text('{"scripts":{"build":"printenv"}}', encoding="utf-8")
            self.assertIn(
                "Cloudflare edge profile layout drifted: ['package.json']",
                MODULE.validate(candidate),
            )

    def test_validator_refuses_worker_byte_drift_even_when_markers_remain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = self.copy_candidate(temporary)
            worker_path = candidate / "runtime" / "cloudflare-edge" / "src" / "index.js"
            worker_path.write_text(
                worker_path.read_text(encoding="utf-8") + "\n// marker-preserving drift\n",
                encoding="utf-8",
            )
            self.assertIn(
                "trusted deployment byte binding drifted: runtime/cloudflare-edge/src/index.js",
                MODULE.validate(candidate),
            )


if __name__ == "__main__":
    unittest.main()
