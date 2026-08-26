from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import shutil
import tempfile
import textwrap
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "validate_cloudflare_edge_candidate.py"
SPEC = importlib.util.spec_from_file_location("cloudflare_edge_validator", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

REQUIRED_PREVIEW_RUNTIME_BINDINGS = [
    "ACCESS_AUD",
    "ACCESS_ISSUER",
    "CONTEXT_GATEWAY_CLIENT_ID",
    "CONTEXT_GATEWAY_CLIENT_SECRET",
    "CONTEXT_GATEWAY_ORIGIN",
    "PREVIEW_HOST",
]


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
        self.assertEqual(
            REQUIRED_PREVIEW_RUNTIME_BINDINGS,
            sorted(config["env"]["preview"]["secrets"]["required"]),
        )

    def test_upload_uses_one_protected_version_only_secrets_file(self) -> None:
        workflow = MODULE.WORKFLOW.read_text(encoding="utf-8")
        for binding in REQUIRED_PREVIEW_RUNTIME_BINDINGS:
            self.assertIn(f"{binding}: ${{{{ secrets.{binding} }}}}", workflow)
        for marker in (
            'preview_secrets_file="$RUNNER_TEMP/kotodama-preview-secrets.json"',
            'trap \'rm -f "$KOTODAMA_PREVIEW_SECRETS_FILE"\' EXIT',
            "umask 077",
            'os.environ.get(name, "")',
            "missing required preview runtime bindings",
            '--secrets-file "$KOTODAMA_PREVIEW_SECRETS_FILE"',
        ):
            self.assertIn(marker, workflow)
        self.assertEqual(1, workflow.count("--secrets-file"))
        self.assertLess(
            workflow.index("npm ci --ignore-scripts"),
            workflow.index("ACCESS_ISSUER: ${{ secrets.ACCESS_ISSUER }}"),
        )
        self.assertLess(
            workflow.index('preview_secrets_file="$RUNNER_TEMP/kotodama-preview-secrets.json"'),
            workflow.index("versions upload --env preview"),
        )

    def test_upload_refuses_whitespace_only_preview_runtime_binding(self) -> None:
        workflow = MODULE.WORKFLOW.read_text(encoding="utf-8")
        script = workflow.split("          python - <<'PY'\n", 1)[1].split(
            "\n          PY", 1
        )[0]
        environment = {
            binding: "bounded-test-value"
            for binding in REQUIRED_PREVIEW_RUNTIME_BINDINGS
        }
        environment["ACCESS_AUD"] = "   \t"
        with tempfile.TemporaryDirectory() as temporary:
            secrets_file = pathlib.Path(temporary) / "preview-secrets.json"
            environment["KOTODAMA_PREVIEW_SECRETS_FILE"] = str(secrets_file)
            with (
                mock.patch.dict(os.environ, environment, clear=True),
                self.assertRaisesRegex(SystemExit, "ACCESS_AUD"),
            ):
                exec(compile(textwrap.dedent(script), "<preview-secrets-writer>", "exec"))
            self.assertFalse(secrets_file.exists())

    def test_validator_refuses_incomplete_preview_runtime_binding_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = pathlib.Path(temporary)
            shutil.copytree(ROOT / "runtime", candidate / "runtime")
            shutil.copytree(ROOT / ".github", candidate / ".github")
            config_path = candidate / "runtime" / "cloudflare-edge" / "wrangler.jsonc"
            config = MODULE.load_jsonc(config_path)
            config["env"]["preview"]["secrets"] = {
                "required": REQUIRED_PREVIEW_RUNTIME_BINDINGS[:-1]
            }
            config_path.write_text(json.dumps(config), encoding="utf-8")
            self.assertIn(
                "preview environment must require the exact protected runtime bindings",
                MODULE.validate(candidate),
            )

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
            'npm ci --ignore-scripts --no-audit --no-fund --prefix "$RUNNER_TEMP/wrangler-verified"',
            'node "$RUNNER_TEMP/wrangler-verified/node_modules/wrangler/bin/wrangler.js"',
        ):
            self.assertIn(marker, workflow)
        self.assertLess(
            workflow.index("python trusted/tools/verify_wrangler_artifact.py"),
            workflow.index('node "$RUNNER_TEMP/wrangler-verified/node_modules/wrangler/bin/wrangler.js"'),
        )

    def test_dedicated_wrangler_runner_manifest_and_lock_are_closed(self) -> None:
        manifest = json.loads(
            MODULE.WRANGLER_RUNNER_PACKAGE.read_text(encoding="utf-8")
        )
        lock = json.loads(
            MODULE.WRANGLER_RUNNER_LOCK.read_text(encoding="utf-8")
        )
        self.assertEqual(
            "file:wrangler-4.120.0.tgz",
            manifest["dependencies"]["wrangler"],
        )
        self.assertEqual(3, lock["lockfileVersion"])
        self.assertEqual(manifest["dependencies"], lock["packages"][""]["dependencies"])
        self.assertEqual(
            json.loads(MODULE.WRANGLER_INTEGRITY.read_text(encoding="utf-8"))["npm_integrity"],
            lock["packages"]["node_modules/wrangler"]["integrity"],
        )
        for package_path, package in lock["packages"].items():
            if package_path == "" or package.get("link"):
                continue
            resolved = package.get("resolved")
            if isinstance(resolved, str) and resolved.startswith("https://registry.npmjs.org/"):
                self.assertTrue(package.get("integrity"), package_path)

    def test_upload_uses_trusted_runner_manifest_lock_and_npm_ci(self) -> None:
        workflow = MODULE.WORKFLOW.read_text(encoding="utf-8")
        for marker in (
            "trusted/runtime/cloudflare-edge/wrangler-runner-package.json",
            "trusted/runtime/cloudflare-edge/wrangler-runner-package-lock.json",
            'cp trusted/runtime/cloudflare-edge/wrangler-runner-package.json "$RUNNER_TEMP/wrangler-verified/package.json"',
            'cp trusted/runtime/cloudflare-edge/wrangler-runner-package-lock.json "$RUNNER_TEMP/wrangler-verified/package-lock.json"',
            'cp "$wrangler_tarball" "$RUNNER_TEMP/wrangler-verified/wrangler-4.120.0.tgz"',
            'npm ci --ignore-scripts --no-audit --no-fund --prefix "$RUNNER_TEMP/wrangler-verified"',
        ):
            self.assertIn(marker, workflow)
        self.assertNotIn("npm install", workflow)
        self.assertNotIn("--no-package-lock", workflow)
        verification = workflow.index("python trusted/tools/verify_wrangler_artifact.py")
        manifest_copy = workflow.index(
            'cp trusted/runtime/cloudflare-edge/wrangler-runner-package.json'
        )
        install = workflow.index("npm ci --ignore-scripts")
        secret = workflow.index("CLOUDFLARE_API_TOKEN")
        self.assertLess(verification, manifest_copy)
        self.assertLess(manifest_copy, install)
        self.assertLess(install, secret)

    def test_validator_refuses_runner_manifest_or_lock_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = pathlib.Path(temporary)
            shutil.copytree(ROOT / "runtime", candidate / "runtime")
            shutil.copytree(ROOT / ".github", candidate / ".github")
            manifest_path = candidate / "runtime" / "cloudflare-edge" / "wrangler-runner-package.json"
            lock_path = candidate / "runtime" / "cloudflare-edge" / "wrangler-runner-package-lock.json"
            for path, marker in (
                (manifest_path, "Wrangler runner manifest digest does not match the reviewed artifact"),
                (lock_path, "Wrangler runner lockfile digest does not match the reviewed artifact"),
            ):
                with self.subTest(path=path.name):
                    path.write_bytes(path.read_bytes() + b"\n")
                    self.assertIn(marker, MODULE.validate(candidate))

    def test_validator_refuses_runner_lock_closure_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = pathlib.Path(temporary)
            shutil.copytree(ROOT / "runtime", candidate / "runtime")
            shutil.copytree(ROOT / ".github", candidate / ".github")
            lock_path = candidate / "runtime" / "cloudflare-edge" / "wrangler-runner-package-lock.json"
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["packages"]["node_modules/wrangler"]["integrity"] = "sha512-mismatch"
            lock_path.write_text(json.dumps(lock), encoding="utf-8")
            errors = MODULE.validate(candidate)
            self.assertIn(
                "Wrangler runner lockfile digest does not match the reviewed artifact",
                errors,
            )
            self.assertIn(
                "Wrangler runner lock node_modules/wrangler integrity must match wrangler-integrity.json",
                errors,
            )

    def test_validator_refuses_registry_dependency_without_resolved_or_integrity(self) -> None:
        for field, marker in (
            ("resolved", "Wrangler runner lock package node_modules/esbuild is missing resolved"),
            ("integrity", "Wrangler runner lock package node_modules/esbuild is missing integrity"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                candidate = pathlib.Path(temporary)
                shutil.copytree(ROOT / "runtime", candidate / "runtime")
                shutil.copytree(ROOT / ".github", candidate / ".github")
                lock_path = candidate / "runtime" / "cloudflare-edge" / "wrangler-runner-package-lock.json"
                lock = json.loads(lock_path.read_text(encoding="utf-8"))
                del lock["packages"]["node_modules/esbuild"][field]
                lock_path.write_text(json.dumps(lock), encoding="utf-8")
                self.assertIn(marker, MODULE.validate(candidate))

    def test_validator_rejects_non_registry_transitive_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = pathlib.Path(temporary)
            shutil.copytree(ROOT / "runtime", candidate / "runtime")
            shutil.copytree(ROOT / ".github", candidate / ".github")
            lock_path = candidate / "runtime" / "cloudflare-edge" / "wrangler-runner-package-lock.json"
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["packages"]["node_modules/esbuild"]["resolved"] = (
                "https://untrusted.example.test/esbuild.tgz"
            )
            lock_path.write_text(json.dumps(lock), encoding="utf-8")
            self.assertIn(
                "Wrangler runner lock package node_modules/esbuild must resolve from the npm registry",
                MODULE.validate(candidate),
            )

    def test_validator_allows_link_exception_without_registry_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = pathlib.Path(temporary)
            shutil.copytree(ROOT / "runtime", candidate / "runtime")
            shutil.copytree(ROOT / ".github", candidate / ".github")
            lock_path = candidate / "runtime" / "cloudflare-edge" / "wrangler-runner-package-lock.json"
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["packages"]["node_modules/local-link"] = {"link": True}
            lock_path.write_text(json.dumps(lock), encoding="utf-8")
            errors = MODULE.validate(candidate)
            self.assertNotIn(
                "Wrangler runner lock package node_modules/local-link is missing resolved",
                errors,
            )
            self.assertNotIn(
                "Wrangler runner lock package node_modules/local-link is missing integrity",
                errors,
            )

    def test_validator_rejects_npm_install_and_no_package_lock(self) -> None:
        for replacement, marker in (
            (
                'npm install --ignore-scripts --no-audit --no-fund --prefix "$RUNNER_TEMP/wrangler-verified"',
                "workflow contains forbidden automatic/production action: npm install",
            ),
            (
                'npm ci --ignore-scripts --no-audit --no-fund --no-package-lock --prefix "$RUNNER_TEMP/wrangler-verified"',
                "workflow contains forbidden automatic/production action: --no-package-lock",
            ),
        ):
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as temporary:
                candidate = pathlib.Path(temporary)
                shutil.copytree(ROOT / "runtime", candidate / "runtime")
                shutil.copytree(ROOT / ".github", candidate / ".github")
                workflow_path = candidate / ".github" / "workflows" / "cloudflare-edge-preview.yml"
                workflow = workflow_path.read_text(encoding="utf-8")
                workflow_path.write_text(
                    workflow.replace(
                        'npm ci --ignore-scripts --no-audit --no-fund --prefix "$RUNNER_TEMP/wrangler-verified"',
                        replacement,
                    ),
                    encoding="utf-8",
                )
                self.assertIn(marker, MODULE.validate(candidate))

    def test_validator_rejects_secret_exposure_before_artifact_verification(self) -> None:
        for secret_name in ("CLOUDFLARE_API_TOKEN", "ACCESS_AUD"):
            with (
                self.subTest(secret_name=secret_name),
                tempfile.TemporaryDirectory() as temporary,
            ):
                candidate = pathlib.Path(temporary)
                shutil.copytree(ROOT / "runtime", candidate / "runtime")
                shutil.copytree(ROOT / ".github", candidate / ".github")
                workflow_path = (
                    candidate / ".github" / "workflows" / "cloudflare-edge-preview.yml"
                )
                workflow = workflow_path.read_text(encoding="utf-8")
                workflow_path.write_text(
                    workflow.replace(
                        "          python trusted/tools/verify_wrangler_artifact.py \\",
                        f"          echo ${secret_name}\n"
                        "          python trusted/tools/verify_wrangler_artifact.py \\",
                        1,
                    ),
                    encoding="utf-8",
                )
                self.assertIn(
                    "workflow must verify Wrangler before upload secrets or execution",
                    MODULE.validate(candidate),
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
