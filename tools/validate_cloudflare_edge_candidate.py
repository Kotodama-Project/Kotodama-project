#!/usr/bin/env python3
"""Fail-closed static validation for the Cloudflare edge candidate."""

from __future__ import annotations

import json
import pathlib
import re
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILE = ROOT / "runtime" / "cloudflare-edge"
CONFIG = PROFILE / "wrangler.jsonc"
WORKER = PROFILE / "src" / "index.js"
WORKFLOW = ROOT / ".github" / "workflows" / "cloudflare-edge-preview.yml"


def load_jsonc(path: pathlib.Path) -> dict:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"//.*$", "", text, flags=re.MULTILINE)
    return json.loads(text)


def validate() -> list[str]:
    errors: list[str] = []
    for path in (CONFIG, WORKER, WORKFLOW, PROFILE / "README.md"):
        if not path.is_file():
            errors.append(f"missing required file: {path.relative_to(ROOT)}")
    if errors:
        return errors

    config = load_jsonc(CONFIG)
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
    if config.get("vars", {}).get("PUBLIC_BETA_STATUS") != "NO_GO_UNPUBLISHED":
        errors.append("default environment must preserve NO_GO_UNPUBLISHED")

    preview = config.get("env", {}).get("preview", {})
    if preview.get("workers_dev") is not True or preview.get("preview_urls") is not True:
        errors.append("preview environment must be the only workers.dev/preview URL surface")
    if preview.get("vars", {}).get("PUBLIC_BETA_STATUS") != "NO_GO_UNPUBLISHED":
        errors.append("preview environment must preserve NO_GO_UNPUBLISHED")

    worker = WORKER.read_text(encoding="utf-8")
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

    workflow = WORKFLOW.read_text(encoding="utf-8")
    required_workflow = (
        "workflow_dispatch:",
        "environment: cloudflare-preview",
        "persist-credentials: false",
        "versions upload --env preview",
        "candidate_sha",
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_ID",
    )
    for required in required_workflow:
        if required not in workflow:
            errors.append(f"workflow missing required guard: {required}")
    for forbidden in ("wrangler deploy", "versions deploy", "pull_request:", "push:"):
        if forbidden in workflow:
            errors.append(f"workflow contains forbidden automatic/production action: {forbidden}")
    return errors


def main() -> int:
    errors = validate()
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
