#!/usr/bin/env python3
"""Fail-closed static validation for the Cloudflare edge candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import stat
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILE = ROOT / "runtime" / "cloudflare-edge"
CONFIG = PROFILE / "wrangler.jsonc"
WORKER = PROFILE / "src" / "index.js"
WORKFLOW = ROOT / ".github" / "workflows" / "cloudflare-edge-preview.yml"
WRANGLER_INTEGRITY = PROFILE / "wrangler-integrity.json"
WRANGLER_RUNNER_PACKAGE = PROFILE / "wrangler-runner-package.json"
WRANGLER_RUNNER_LOCK = PROFILE / "wrangler-runner-package-lock.json"

VERIFIED_COMPATIBILITY_DATE = "2026-08-07"
VERIFIED_CONFIG_SHA256 = "88c6a3cd7ebdedff1add9d0c4d8d2a622dd70fcb7ca04362b6931c86cd89b63d"
VERIFIED_WORKER_SHA256 = "3c2150d2fb79cf086680467f360e357888c21669e313fe1a5ed231c44c2c76a7"
VERIFIED_WRANGLER_RUNNER_PACKAGE_SHA256 = "78050f0fc214eda989a097930c1daf53ef608259d9d861a128651ed94e0cdf74"
VERIFIED_WRANGLER_RUNNER_LOCK_SHA256 = "e86ede152f4135397ee58a22023dbf029e36aa361b64d767c5cc33dae97a4cc4"
EXPECTED_WRANGLER_RUNNER_DEPENDENCY = "file:wrangler-4.120.0.tgz"
WRANGLER_CONFIG_FILENAMES = ("wrangler.json", "wrangler.jsonc", "wrangler.toml")
WRANGLER_DEPLOY_CONFIG_RELATIVE = pathlib.Path(".wrangler") / "deploy" / "config.json"
REQUIRED_PREVIEW_RUNTIME_BINDINGS = (
    "ACCESS_AUD",
    "ACCESS_ISSUER",
    "CONTEXT_GATEWAY_CLIENT_ID",
    "CONTEXT_GATEWAY_CLIENT_SECRET",
    "CONTEXT_GATEWAY_ORIGIN",
    "PREVIEW_HOST",
)
VERIFIED_WRANGLER = {
    "kind": "npm_supply_chain_binding",
    "package": "wrangler",
    "version": "4.120.0",
    "npm_tarball": "https://registry.npmjs.org/wrangler/-/wrangler-4.120.0.tgz",
    "npm_integrity": "sha512-cBmu/MeaB/fPacC0JpATs4duTOCagBxrZo+vBzuTX06tLzwSyAHE1drlHUZ8rP0VqVz1fy3ReGYTiHdKkoHltg==",
    "npm_shasum": "8fe91bbdefb7c2bec861d76ed8a697c5ff6dea5d",
    "slsa_subject": "pkg:npm/wrangler@4.120.0",
    "slsa_subject_sha512": "7019aefcc79a07f7cf69c0b4269013b3876e4ce09a801c6b668faf073b935f4ead2f3c12c801c4d5dae51d467cacfd15a95cf57f2dd178661388774a9281e5b6",
    "slsa_predicate_type": "https://slsa.dev/provenance/v1",
    "observed_utc": "2026-08-07",
}


def load_jsonc(path: pathlib.Path) -> dict:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"//.*$", "", text, flags=re.MULTILINE)
    return json.loads(text)


def path_kind(path: pathlib.Path) -> str | None:
    """Return a fail-closed kind for a path without following symlinks."""
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return None
    except OSError:
        return "unreadable"
    if stat.S_ISREG(mode):
        return "regular"
    return "non_regular"


def relative_candidate_path(root: pathlib.Path, path: pathlib.Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return "<outside candidate root>"


def discovery_directories(root: pathlib.Path, profile: pathlib.Path):
    """Yield every directory Wrangler can search from the upload cwd."""
    current = profile
    while True:
        yield current
        if current == root:
            return
        if root not in current.parents:
            return
        current = current.parent


def validate_wrangler_discovery_surface(
    root: pathlib.Path, profile: pathlib.Path, config_path: pathlib.Path
) -> list[str]:
    errors: list[str] = []
    canonical_config = config_path
    for directory in discovery_directories(root, profile):
        for filename in WRANGLER_CONFIG_FILENAMES:
            candidate = directory / filename
            if candidate == canonical_config:
                continue
            kind = path_kind(candidate)
            if kind is None:
                continue
            if kind == "unreadable":
                errors.append(
                    "unable to inspect alternate Wrangler configuration: "
                    f"{relative_candidate_path(root, candidate)}"
                )
            else:
                errors.append(
                    "alternate Wrangler configuration is forbidden: "
                    f"{relative_candidate_path(root, candidate)}"
                )

        deploy_config = directory / WRANGLER_DEPLOY_CONFIG_RELATIVE
        deploy_kind = path_kind(deploy_config)
        if deploy_kind is None:
            continue
        deploy_relative = relative_candidate_path(root, deploy_config)
        if deploy_kind == "unreadable":
            errors.append(
                "unable to inspect Wrangler deploy redirect configuration: "
                f"{deploy_relative}"
            )
            continue
        errors.append(
            "Wrangler deploy redirect configuration is forbidden: "
            f"{deploy_relative}"
        )
        if deploy_kind != "regular":
            continue
        try:
            deploy_config_data = load_jsonc(deploy_config)
        except (OSError, UnicodeError, json.JSONDecodeError):
            errors.append(
                "Wrangler deploy redirect configuration is not valid JSON: "
                f"{deploy_relative}"
            )
            continue
        if not isinstance(deploy_config_data, dict):
            errors.append(
                "Wrangler deploy redirect configuration must be a JSON object: "
                f"{deploy_relative}"
            )
            continue
        redirect = deploy_config_data.get("configPath")
        if not isinstance(redirect, str) or not redirect.strip():
            continue
        try:
            redirect_target = (deploy_config.parent / redirect).resolve()
        except (OSError, RuntimeError, ValueError):
            errors.append(
                "Wrangler deploy redirect target could not be resolved: "
                f"{deploy_relative}"
            )
            continue
        if path_kind(redirect_target) is None:
            continue
        errors.append(
            "Wrangler deploy redirect target is forbidden: "
            f"{relative_candidate_path(root, redirect_target)}"
        )
    return errors


def candidate_paths(
    root: pathlib.Path,
) -> tuple[
    pathlib.Path,
    pathlib.Path,
    pathlib.Path,
    pathlib.Path,
    pathlib.Path,
    pathlib.Path,
    pathlib.Path,
]:
    profile = root / "runtime" / "cloudflare-edge"
    return (
        profile,
        profile / "wrangler.jsonc",
        profile / "src" / "index.js",
        root / ".github" / "workflows" / "cloudflare-edge-preview.yml",
        profile / "wrangler-integrity.json",
        profile / "wrangler-runner-package.json",
        profile / "wrangler-runner-package-lock.json",
    )


def validate(root: pathlib.Path = ROOT) -> list[str]:
    root = root.resolve()
    (
        profile,
        config_path,
        worker_path,
        workflow_path,
        integrity_path,
        runner_package_path,
        runner_lock_path,
    ) = candidate_paths(root)
    errors: list[str] = []
    for path in (
        config_path,
        worker_path,
        workflow_path,
        integrity_path,
        runner_package_path,
        runner_lock_path,
        profile / "README.md",
    ):
        kind = path_kind(path)
        if kind is None:
            errors.append(f"missing required file: {path.relative_to(root)}")
        elif kind != "regular":
            errors.append(
                "required candidate file must be a regular non-symlink file: "
                f"{path.relative_to(root).as_posix()}"
            )
    if errors:
        return errors

    errors.extend(validate_wrangler_discovery_surface(root, profile, config_path))

    if hashlib.sha256(config_path.read_bytes()).hexdigest() != VERIFIED_CONFIG_SHA256:
        errors.append("Wrangler configuration digest does not match the reviewed artifact")
    config = load_jsonc(config_path)
    executable_config = sorted({"build"}.intersection(config))
    if executable_config:
        errors.append(f"executable Wrangler configuration is forbidden: {executable_config}")
    forbidden_bindings = {
        "ai", "ai_search", "d1_databases", "durable_objects", "kv_namespaces",
        "queues", "r2_buckets", "routes", "services", "vectorize",
    }
    present = sorted(forbidden_bindings.intersection(config))
    if present:
        errors.append(f"top-level provider/data bindings are forbidden: {present}")
    if config.get("workers_dev") is not False or config.get("preview_urls") is not False:
        errors.append("production/default environment must have workers_dev and preview_urls disabled")
    if config.get("send_metrics") is not False:
        errors.append("send_metrics must be disabled")
    if config.get("compatibility_date") != VERIFIED_COMPATIBILITY_DATE:
        errors.append(
            f"compatibility_date must equal the verified UTC-safe date {VERIFIED_COMPATIBILITY_DATE}"
        )
    observability = config.get("observability", {})
    if observability.get("enabled") is not False:
        errors.append("observability must remain disabled until provider retention is verified")
    if observability.get("logs", {}).get("enabled") is not False:
        errors.append("Workers logs must remain disabled until content-free readback is verified")
    if config.get("vars", {}).get("PUBLIC_BETA_STATUS") != "NO_GO_UNPUBLISHED":
        errors.append("default environment must preserve NO_GO_UNPUBLISHED")

    environments = config.get("env", {})
    if not isinstance(environments, dict):
        errors.append("env must be an object")
        environments = {}
    for environment_name, environment in environments.items():
        if not isinstance(environment_name, str) or not isinstance(environment, dict):
            errors.append("each named environment must be an object")
            continue
        environment_bindings = sorted(forbidden_bindings.intersection(environment))
        if environment_bindings:
            errors.append(
                f"{environment_name} environment contains forbidden provider/data bindings: "
                f"{environment_bindings}"
            )

    preview = environments.get("preview", {})
    if preview.get("workers_dev") is not False or preview.get("preview_urls") is not True:
        errors.append("preview must disable the base workers.dev route and explicitly enable preview URLs")
    if preview.get("vars", {}).get("PUBLIC_BETA_STATUS") != "NO_GO_UNPUBLISHED":
        errors.append("preview environment must preserve NO_GO_UNPUBLISHED")
    preview_required_secrets = preview.get("secrets", {}).get("required")
    if (
        not isinstance(preview_required_secrets, list)
        or sorted(preview_required_secrets) != list(REQUIRED_PREVIEW_RUNTIME_BINDINGS)
    ):
        errors.append("preview environment must require the exact protected runtime bindings")
    preview_observability = preview.get("observability", observability)
    if not isinstance(preview_observability, dict) or preview_observability.get("enabled") is not False:
        errors.append("preview observability must remain disabled until provider retention is verified")
    preview_logs = (
        preview_observability.get("logs", {})
        if isinstance(preview_observability, dict)
        else {}
    )
    if not isinstance(preview_logs, dict) or preview_logs.get("enabled") is not False:
        errors.append("preview logs must remain disabled until content-free readback is verified")

    integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
    if integrity != VERIFIED_WRANGLER:
        errors.append("Wrangler supply-chain binding does not match verified 4.120.0 metadata")

    for path, expected, description in (
        (
            runner_package_path,
            VERIFIED_WRANGLER_RUNNER_PACKAGE_SHA256,
            "Wrangler runner manifest",
        ),
        (
            runner_lock_path,
            VERIFIED_WRANGLER_RUNNER_LOCK_SHA256,
            "Wrangler runner lockfile",
        ),
    ):
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            errors.append(f"{description} digest does not match the reviewed artifact")

    try:
        runner_manifest = json.loads(runner_package_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        runner_manifest = None
        errors.append(f"Wrangler runner manifest is not valid JSON: {exc}")
    if not isinstance(runner_manifest, dict):
        if runner_manifest is not None:
            errors.append("Wrangler runner manifest must be a JSON object")
        runner_manifest = {}
    manifest_dependencies = runner_manifest.get("dependencies")
    if (
        not isinstance(manifest_dependencies, dict)
        or manifest_dependencies.get("wrangler") != EXPECTED_WRANGLER_RUNNER_DEPENDENCY
    ):
        errors.append(
            "Wrangler runner manifest must pin wrangler to "
            "file:wrangler-4.120.0.tgz"
        )
    if runner_manifest.get("private") is not True:
        errors.append("Wrangler runner manifest must be private")

    try:
        runner_lock = json.loads(runner_lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        runner_lock = None
        errors.append(f"Wrangler runner lockfile is not valid JSON: {exc}")
    if not isinstance(runner_lock, dict):
        if runner_lock is not None:
            errors.append("Wrangler runner lockfile must be a JSON object")
        runner_lock = {}
    if runner_lock.get("lockfileVersion") != 3:
        errors.append("Wrangler runner lockfile must use lockfileVersion 3")
    lock_packages = runner_lock.get("packages")
    if not isinstance(lock_packages, dict):
        errors.append("Wrangler runner lockfile packages must be an object")
        lock_packages = {}
    root_lock_package = lock_packages.get("")
    if not isinstance(root_lock_package, dict):
        errors.append("Wrangler runner lockfile must contain a root package entry")
        root_lock_package = {}
    if root_lock_package.get("dependencies") != manifest_dependencies:
        errors.append("Wrangler runner lock root dependencies must match its manifest")

    expected_npm_integrity = (
        integrity.get("npm_integrity") if isinstance(integrity, dict) else None
    )
    wrangler_lock_package = lock_packages.get("node_modules/wrangler")
    if not isinstance(wrangler_lock_package, dict):
        errors.append("Wrangler runner lockfile must contain node_modules/wrangler")
    else:
        if wrangler_lock_package.get("resolved") != EXPECTED_WRANGLER_RUNNER_DEPENDENCY:
            errors.append(
                "Wrangler runner lock node_modules/wrangler resolved must be "
                "file:wrangler-4.120.0.tgz"
            )
        if wrangler_lock_package.get("integrity") != expected_npm_integrity:
            errors.append(
                "Wrangler runner lock node_modules/wrangler integrity must match "
                "wrangler-integrity.json"
            )

    integrity_pattern = re.compile(r"sha(?:512|384|256)-[A-Za-z0-9+/=]+$")
    for package_path, package in lock_packages.items():
        if package_path == "":
            continue
        if not isinstance(package, dict):
            errors.append(f"Wrangler runner lock package {package_path} must be an object")
            continue
        if package.get("link") is True:
            if package_path == "node_modules/wrangler":
                errors.append("Wrangler runner lock node_modules/wrangler must not be a link")
            continue
        resolved = package.get("resolved")
        if not isinstance(resolved, str) or not resolved:
            errors.append(f"Wrangler runner lock package {package_path} is missing resolved")
        elif package_path != "node_modules/wrangler" and not resolved.startswith(
            "https://registry.npmjs.org/"
        ):
            errors.append(
                f"Wrangler runner lock package {package_path} must resolve from the npm registry"
            )
        package_integrity = package.get("integrity")
        if not isinstance(package_integrity, str) or not integrity_pattern.fullmatch(
            package_integrity
        ):
            errors.append(f"Wrangler runner lock package {package_path} is missing integrity")

    worker_bytes = worker_path.read_bytes()
    if hashlib.sha256(worker_bytes).hexdigest() != VERIFIED_WORKER_SHA256:
        errors.append("Worker implementation digest does not match the reviewed artifact")
    worker = worker_bytes.decode("utf-8")
    for forbidden in (
        "Authorization",
        "request.text(",
        "request.json(",
        "request.arrayBuffer(",
        "console.log",
        "await fetch(",
        "return fetch(",
        "SEARCH_ORIGIN",
        "VECTORIZE",
        "api.openai.com",
    ):
        if forbidden in worker:
            errors.append(f"worker contains forbidden content/origin operation: {forbidden}")
    for required in (
        '"/healthz"',
        '"/version"',
        '"not_found"',
        '"no-store"',
        '"/voice/review"',
        '"cf-access-jwt-assertion"',
        "/cdn-cgi/access/certs",
        "refreshAccessJwks(config)",
        '"RSASSA-PKCS1-v1_5"',
        "normalizedHostname(env?.PREVIEW_HOST)",
        '"direct_origin_denied"',
        "normalizedHttpsOrigin(env?.CONTEXT_GATEWAY_ORIGIN)",
        "/v1/voice/handoffs",
        '"x-kotodama-access-subject"',
        '"x-kotodama-access-email"',
        "request.body.getReader()",
        'reader.cancel("body_limit_exceeded")',
        "hasForbiddenGatewayKey",
        "raw_audio_transferred: false",
        "private_transcript_transferred: false",
        "context_gateway_bypass: false",
    ):
        if required not in worker:
            errors.append(f"worker missing fail-closed marker: {required}")
    if worker.count("await fetchImpl(new Request(") != 2:
        errors.append("worker must have exactly two bounded fetch sites: Access JWKS and Context Gateway")

    workflow = workflow_path.read_text(encoding="utf-8")
    required_workflow = (
        "workflow_dispatch:",
        "refs/heads/main",
        "^[0-9a-f]{40}$",
        "refs/remotes/origin/codex/cloudflare-os-foundation-rebased-20260824",
        "path: trusted",
        "path: candidate",
        "ref: ${{ github.sha }}",
        "trusted/tools/validate_cloudflare_edge_candidate.py --root candidate",
        "needs: validate-candidate",
        "environment: cloudflare-preview",
        "persist-credentials: false",
        "versions upload --env preview",
        "--preview-alias voice-review",
        "python trusted/tools/verify_wrangler_artifact.py",
        "trusted/runtime/cloudflare-edge/wrangler-integrity.json",
        "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020",
        'node-version: "24.14.0"',
        "curl --fail --location --proto '=https' --tlsv1.2",
        "trusted/runtime/cloudflare-edge/wrangler-runner-package.json",
        "trusted/runtime/cloudflare-edge/wrangler-runner-package-lock.json",
        'cp trusted/runtime/cloudflare-edge/wrangler-runner-package.json "$RUNNER_TEMP/wrangler-verified/package.json"',
        'cp trusted/runtime/cloudflare-edge/wrangler-runner-package-lock.json "$RUNNER_TEMP/wrangler-verified/package-lock.json"',
        'cp "$wrangler_tarball" "$RUNNER_TEMP/wrangler-verified/wrangler-4.120.0.tgz"',
        'npm ci --ignore-scripts --no-audit --no-fund --prefix "$RUNNER_TEMP/wrangler-verified"',
        'node "$RUNNER_TEMP/wrangler-verified/node_modules/wrangler/bin/wrangler.js"',
        'candidate_config="$GITHUB_WORKSPACE/candidate/runtime/cloudflare-edge/wrangler.jsonc"',
        '--config "$candidate_config"',
        "candidate_sha",
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_ID",
        'preview_secrets_file="$RUNNER_TEMP/kotodama-preview-secrets.json"',
        'trap \'rm -f "$KOTODAMA_PREVIEW_SECRETS_FILE"\' EXIT',
        "umask 077",
        'os.environ.get(name, "")',
        "missing required preview runtime bindings",
        '--secrets-file "$KOTODAMA_PREVIEW_SECRETS_FILE"',
    )
    required_workflow += tuple(
        f"{binding}: ${{{{ secrets.{binding} }}}}"
        for binding in REQUIRED_PREVIEW_RUNTIME_BINDINGS
    )
    for required in required_workflow:
        if required not in workflow:
            errors.append(f"workflow missing required guard: {required}")
    exact_tip_guard = (
        'test "$(git rev-parse refs/remotes/origin/codex/cloudflare-os-foundation-rebased-20260824)" '
        '= "$CANDIDATE_SHA"'
    )
    upload_job_marker = "  upload-preview-version:"
    if workflow.count(upload_job_marker) != 1:
        errors.append("workflow must contain exactly one upload-preview-version job")
    else:
        validation_job, upload_job = workflow.split(upload_job_marker, 1)
        if validation_job.count(exact_tip_guard) != 1 or upload_job.count(exact_tip_guard) != 1:
            errors.append(
                "workflow must place one exact allowed-branch-tip guard in each validation and upload job"
            )
    if workflow.count(exact_tip_guard) != 2:
        errors.append("workflow must bind both validation and upload jobs to the exact allowed branch tip")
    integrity_verification = workflow.find("python trusted/tools/verify_wrangler_artifact.py")
    runner_manifest_copy = workflow.find(
        'cp trusted/runtime/cloudflare-edge/wrangler-runner-package.json '
        '"$RUNNER_TEMP/wrangler-verified/package.json"'
    )
    runner_lock_copy = workflow.find(
        'cp trusted/runtime/cloudflare-edge/wrangler-runner-package-lock.json '
        '"$RUNNER_TEMP/wrangler-verified/package-lock.json"'
    )
    runner_tarball_copy = workflow.find(
        'cp "$wrangler_tarball" "$RUNNER_TEMP/wrangler-verified/wrangler-4.120.0.tgz"'
    )
    npm_ci = workflow.find(
        'npm ci --ignore-scripts --no-audit --no-fund --prefix '
        '"$RUNNER_TEMP/wrangler-verified"'
    )
    upload_command = workflow.find("versions upload --env preview")
    candidate_config = workflow.find(
        'candidate_config="$GITHUB_WORKSPACE/candidate/runtime/cloudflare-edge/wrangler.jsonc"'
    )
    config_argument = workflow.find('--config "$candidate_config"')
    secret_markers = (
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_ID",
        *REQUIRED_PREVIEW_RUNTIME_BINDINGS,
    )
    secret_positions = [workflow.find(marker) for marker in secret_markers]
    secret_exposure = min(
        (position for position in secret_positions if position >= 0), default=-1
    )
    if not (
        0 <= integrity_verification < upload_command
        and 0 <= integrity_verification < secret_exposure
    ):
        errors.append("workflow must verify Wrangler before upload secrets or execution")
    if not (0 <= candidate_config < config_argument < upload_command):
        errors.append(
            "workflow must invoke Wrangler with the absolute candidate wrangler.jsonc "
            "before versions upload"
        )
    if not (
        0 <= integrity_verification < runner_manifest_copy < npm_ci < secret_exposure
        and 0 <= integrity_verification < runner_lock_copy < npm_ci
        and 0 <= integrity_verification < runner_tarball_copy < npm_ci
    ):
        errors.append(
            "workflow must copy trusted Wrangler runner inputs and run npm ci after artifact verification"
        )
    if workflow.count("npm ci --ignore-scripts") != 1:
        errors.append("workflow must contain exactly one npm ci runner installation")
    if workflow.count("--secrets-file") != 1:
        errors.append("workflow must contain exactly one protected version secrets file")
    for forbidden in (
        "git merge-base --is-ancestor",
        "cloudflare/wrangler-action@",
        "npx wrangler",
        "npm exec wrangler",
        "npm install",
        "--no-package-lock",
        "pnpm dlx",
        "wrangler deploy",
        "versions deploy",
        "pull_request:",
        "push:",
        "github.event.repository.default_branch",
    ):
        if forbidden in workflow:
            errors.append(f"workflow contains forbidden automatic/production action: {forbidden}")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=pathlib.Path,
        default=ROOT,
        help="candidate repository root to inspect without executing candidate code",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    errors = validate(args.root)
    report = {
        "kind": "cloudflare_edge_candidate_validation",
        "status": "PASS" if not errors else "REFUSED",
        "errors": errors,
        "claims": {
            "provider_authenticated": False,
            "preview_deployed": False,
            "production_deployed": False,
            "public_beta_go": False,
        },
        "public_beta": "NO_GO_UNPUBLISHED",
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
