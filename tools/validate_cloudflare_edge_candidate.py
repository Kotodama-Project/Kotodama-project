#!/usr/bin/env python3
"""Fail-closed static validation for the Cloudflare edge candidate."""

from __future__ import annotations

import argparse
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
    for path in (config_path, worker_path, workflow_path, integrity_path, profile / "README.md"):
        if not path.is_file():
            errors.append(f"missing required file: {path.relative_to(root)}")
    if errors:
        return errors

    config = load_jsonc(config_path)
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

    preview = config.get("env", {}).get("preview", {})
    if preview.get("workers_dev") is not True or preview.get("preview_urls") is not True:
        errors.append("preview environment must be the only workers.dev/preview URL surface")
    if preview.get("vars", {}).get("PUBLIC_BETA_STATUS") != "NO_GO_UNPUBLISHED":
        errors.append("preview environment must preserve NO_GO_UNPUBLISHED")

    integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
    if integrity != VERIFIED_WRANGLER:
        errors.append("Wrangler supply-chain binding does not match verified 4.120.0 metadata")

    worker = worker_path.read_text(encoding="utf-8")
    for forbidden in (
        "Authorization",
        "request.text(",
        "request.json(",
        "console.log",
        "await fetch(",
        "return fetch(",
    ):
        if forbidden in worker:
            errors.append(f"worker contains forbidden content/origin operation: {forbidden}")
    for required in ('"/healthz"', '"/version"', '"not_found"', '"no-store"'):
        if required not in worker:
            errors.append(f"worker missing fail-closed marker: {required}")

    workflow = workflow_path.read_text(encoding="utf-8")
    required_workflow = (
        "workflow_dispatch:",
        "refs/heads/main",
        "^[0-9a-f]{40}$",
        "refs/remotes/origin/codex/cloudflare-os-foundation",
        "path: trusted",
        "path: candidate",
        "trusted/tools/validate_cloudflare_edge_candidate.py --root candidate",
        "needs: validate-candidate",
        "environment: cloudflare-preview",
        "persist-credentials: false",
        "versions upload --env preview",
        'wranglerVersion: "4.120.0"',
        "candidate_sha",
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_ID",
    )
    for required in required_workflow:
        if required not in workflow:
            errors.append(f"workflow missing required guard: {required}")
    exact_tip_guard = (
        'test "$(git rev-parse refs/remotes/origin/codex/cloudflare-os-foundation)" '
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
    for forbidden in (
        "git merge-base --is-ancestor",
        "wrangler deploy",
        "versions deploy",
        "pull_request:",
        "push:",
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
