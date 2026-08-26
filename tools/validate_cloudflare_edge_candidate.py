#!/usr/bin/env python3
"""Fail-closed static validation for the Cloudflare edge candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILE = ROOT / "runtime" / "cloudflare-edge"
CONFIG = PROFILE / "wrangler.jsonc"
WORKER = PROFILE / "src" / "index.js"
WORKFLOW = ROOT / ".github" / "workflows" / "cloudflare-edge-preview.yml"
WRANGLER_INTEGRITY = PROFILE / "wrangler-integrity.json"

VERIFIED_COMPATIBILITY_DATE = "2026-08-07"
VERIFIED_CONFIG_SHA256 = "a75caf3b6cf486acdfc1d7a11dbce0734ac0473797a3c538906a0aff1c609bac"
VERIFIED_WORKER_SHA256 = "a5ffc50af4aa598ee63b12d32ae61c65d9ff81e508d23de588991efa5bd9bca8"
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


def candidate_paths(root: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path, pathlib.Path, pathlib.Path]:
    profile = root / "runtime" / "cloudflare-edge"
    return (
        profile,
        profile / "wrangler.jsonc",
        profile / "src" / "index.js",
        root / ".github" / "workflows" / "cloudflare-edge-preview.yml",
        profile / "wrangler-integrity.json",
    )


def validate(root: pathlib.Path = ROOT) -> list[str]:
    root = root.resolve()
    profile, config_path, worker_path, workflow_path, integrity_path = candidate_paths(root)
    errors: list[str] = []
    for path in (
        config_path,
        worker_path,
        workflow_path,
        integrity_path,
        profile / "README.md",
    ):
        if not path.is_file():
            errors.append(f"missing required file: {path.relative_to(root)}")
    if errors:
        return errors

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
        "npm install --ignore-scripts",
        'node "$RUNNER_TEMP/wrangler-verified/node_modules/wrangler/bin/wrangler.js"',
        "candidate_sha",
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_ID",
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
    upload_command = workflow.find("versions upload --env preview")
    secret_exposure = workflow.find("CLOUDFLARE_API_TOKEN")
    if not (
        0 <= integrity_verification < upload_command
        and 0 <= integrity_verification < secret_exposure
    ):
        errors.append("workflow must verify Wrangler before upload secrets or execution")
    for forbidden in (
        "git merge-base --is-ancestor",
        "cloudflare/wrangler-action@",
        "npx wrangler",
        "npm exec wrangler",
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
