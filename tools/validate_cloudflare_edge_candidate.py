#!/usr/bin/env python3
"""Fail-closed static validation for the Cloudflare edge candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
from typing import Any


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
VERIFIED_CONFIG = {
    "$schema": "../../node_modules/wrangler/config-schema.json",
    "name": "kotodama-edge-candidate",
    "main": "src/index.js",
    "compatibility_date": VERIFIED_COMPATIBILITY_DATE,
    "workers_dev": False,
    "preview_urls": False,
    "send_metrics": False,
    "observability": {
        "enabled": False,
        "logs": {"enabled": False, "invocation_logs": False},
    },
    "vars": {
        "DEPLOYMENT_STAGE": "production-disabled",
        "PUBLIC_BETA_STATUS": "NO_GO_UNPUBLISHED",
    },
    "env": {
        "preview": {
            "name": "kotodama-edge-preview-candidate",
            "workers_dev": False,
            "preview_urls": True,
            "vars": {
                "DEPLOYMENT_STAGE": "preview-candidate",
                "PUBLIC_BETA_STATUS": "NO_GO_UNPUBLISHED",
            },
        }
    },
}
VERIFIED_CANONICAL_SHA256 = {
    "runtime/cloudflare-edge/src/index.js": "c79d25133bc15826e8a9122482da2e3447cd5e487b88febdce0cab329ee9a49c",
    "runtime/cloudflare-edge/wrangler.jsonc": "a75caf3b6cf486acdfc1d7a11dbce0734ac0473797a3c538906a0aff1c609bac",
    "runtime/cloudflare-edge/wrangler-integrity.json": "336c93afdbc206dbe531ddd6753c9b6ca27c84484d44a61df68403c48d3b870b",
    ".github/workflows/cloudflare-edge-preview.yml": "cdc76d861ddbc9bd02920757a14ece195dbf6ee13a7cfc6c60c0eac62cdc3f19",
}
PROFILE_ENTRIES = {"README.md", "src", "wrangler-integrity.json", "wrangler.jsonc"}
SOURCE_ENTRIES = {"index.js"}
MAX_DIRECTORY_ENTRIES = 16
MAX_TEXT_BYTES = 131_072
DEPLOY_CONTROL_PATHS = (
    ".wrangler",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lock",
    "bun.lockb",
    "npm-shrinkwrap.json",
    "node_modules",
    ".npmrc",
)


class CandidateInputError(ValueError):
    """Candidate bytes or layout could not be inspected safely."""


def _closed_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CandidateInputError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _bounded_canonical_text(path: pathlib.Path, limit: int = MAX_TEXT_BYTES) -> str:
    if path.is_symlink() or not path.is_file():
        raise CandidateInputError(f"required regular file is missing: {path.name}")
    try:
        with path.open("rb") as handle:
            raw = handle.read(limit + 1)
    except OSError as exc:
        raise CandidateInputError(f"cannot read candidate file: {path.name}") from exc
    if len(raw) > limit:
        raise CandidateInputError(f"candidate file exceeds {limit} bytes: {path.name}")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise CandidateInputError(f"candidate file is not strict UTF-8: {path.name}") from exc
    canonical = text.replace("\r\n", "\n")
    if "\r" in canonical:
        raise CandidateInputError(f"candidate file contains a bare CR: {path.name}")
    return canonical


def _canonical_sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(_bounded_canonical_text(path).encode("utf-8")).hexdigest()


def load_jsonc(path: pathlib.Path) -> dict[str, Any]:
    text = _bounded_canonical_text(path, 65_536)
    text = re.sub(r"//.*$", "", text, flags=re.MULTILINE)
    try:
        value = json.loads(text, object_pairs_hook=_closed_object)
    except json.JSONDecodeError as exc:
        raise CandidateInputError("cannot parse closed Wrangler JSONC") from exc
    if not isinstance(value, dict):
        raise CandidateInputError("Wrangler JSONC root must be an object")
    return value


def _load_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(
            _bounded_canonical_text(path, 32_768),
            object_pairs_hook=_closed_object,
        )
    except json.JSONDecodeError as exc:
        raise CandidateInputError(f"cannot parse closed JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise CandidateInputError(f"JSON root must be an object: {path.name}")
    return value


def _bounded_directory_names(path: pathlib.Path) -> set[str]:
    if path.is_symlink() or not path.is_dir():
        raise CandidateInputError(f"required directory is missing or linked: {path.name}")
    names: set[str] = set()
    try:
        with os.scandir(path) as entries:
            for index, entry in enumerate(entries, start=1):
                if index > MAX_DIRECTORY_ENTRIES:
                    raise CandidateInputError(
                        f"candidate directory exceeds {MAX_DIRECTORY_ENTRIES} entries: {path.name}"
                    )
                if entry.is_symlink():
                    raise CandidateInputError(f"candidate deploy surface contains a symlink: {entry.name}")
                names.add(entry.name)
    except OSError as exc:
        raise CandidateInputError(f"cannot inspect candidate directory: {path.name}") from exc
    return names


def candidate_paths(
    root: pathlib.Path,
) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path, pathlib.Path, pathlib.Path]:
    profile = root / "runtime" / "cloudflare-edge"
    return (
        profile,
        profile / "wrangler.jsonc",
        profile / "src" / "index.js",
        root / ".github" / "workflows" / "cloudflare-edge-preview.yml",
        profile / "wrangler-integrity.json",
    )


def _validate_layout(root: pathlib.Path, profile: pathlib.Path) -> list[str]:
    errors: list[str] = []
    try:
        if (root / "runtime").is_symlink():
            raise CandidateInputError("runtime directory must not be a symlink")
        profile_names = _bounded_directory_names(profile)
        if profile_names != PROFILE_ENTRIES:
            errors.append(
                "Cloudflare edge profile layout drifted: "
                f"{sorted(profile_names ^ PROFILE_ENTRIES)}"
            )
        source_names = _bounded_directory_names(profile / "src")
        if source_names != SOURCE_ENTRIES:
            errors.append(
                "Cloudflare edge source layout drifted: "
                f"{sorted(source_names ^ SOURCE_ENTRIES)}"
            )
    except CandidateInputError as exc:
        errors.append(str(exc))

    for parent in (root, root / "runtime"):
        for relative in DEPLOY_CONTROL_PATHS:
            path = parent / relative
            if path.exists() or path.is_symlink():
                errors.append(
                    "candidate-controlled Wrangler/build path is forbidden: "
                    f"{path.relative_to(root).as_posix()}"
                )
    return errors


def validate(root: pathlib.Path = ROOT) -> list[str]:
    root = root.resolve()
    profile, config_path, worker_path, workflow_path, integrity_path = candidate_paths(root)
    errors = _validate_layout(root, profile)
    for path in (config_path, worker_path, workflow_path, integrity_path, profile / "README.md"):
        if path.is_symlink() or not path.is_file():
            errors.append(f"missing regular required file: {path.relative_to(root)}")
    if errors:
        return errors

    bound_paths = {
        "runtime/cloudflare-edge/src/index.js": worker_path,
        "runtime/cloudflare-edge/wrangler.jsonc": config_path,
        "runtime/cloudflare-edge/wrangler-integrity.json": integrity_path,
        ".github/workflows/cloudflare-edge-preview.yml": workflow_path,
    }
    for relative, path in bound_paths.items():
        try:
            observed = _canonical_sha256(path)
        except CandidateInputError as exc:
            errors.append(str(exc))
            continue
        if observed != VERIFIED_CANONICAL_SHA256[relative]:
            errors.append(f"trusted deployment byte binding drifted: {relative}")

    try:
        config = load_jsonc(config_path)
    except CandidateInputError as exc:
        errors.append(str(exc))
        config = {}
    if config != VERIFIED_CONFIG:
        errors.append("Wrangler config must match the closed content-free preview shape")

    forbidden_bindings = {
        "ai",
        "ai_search",
        "analytics_engine_datasets",
        "assets",
        "browser",
        "build",
        "containers",
        "d1_databases",
        "dispatch_namespaces",
        "durable_objects",
        "hyperdrive",
        "images",
        "kv_namespaces",
        "logfwdr",
        "mtls_certificates",
        "pipelines",
        "queues",
        "r2_buckets",
        "route",
        "routes",
        "secrets_store_secrets",
        "send_email",
        "services",
        "tail_consumers",
        "triggers",
        "unsafe",
        "vectorize",
    }
    present = sorted(forbidden_bindings.intersection(config))
    if present:
        errors.append(f"top-level provider/data/build bindings are forbidden: {present}")
    if config.get("workers_dev") is not False or config.get("preview_urls") is not False:
        errors.append("production/default environment must have workers_dev and preview_urls disabled")
    if config.get("send_metrics") is not False:
        errors.append("send_metrics must be disabled")
    if config.get("compatibility_date") != VERIFIED_COMPATIBILITY_DATE:
        errors.append(
            f"compatibility_date must equal the verified UTC-safe date {VERIFIED_COMPATIBILITY_DATE}"
        )
    observability = config.get("observability", {})
    if not isinstance(observability, dict) or observability.get("enabled") is not False:
        errors.append("observability must remain disabled until provider retention is verified")
    logs = observability.get("logs", {}) if isinstance(observability, dict) else {}
    if not isinstance(logs, dict) or logs.get("enabled") is not False:
        errors.append("Workers logs must remain disabled until content-free readback is verified")
    variables = config.get("vars", {})
    if not isinstance(variables, dict) or variables.get("PUBLIC_BETA_STATUS") != "NO_GO_UNPUBLISHED":
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
                f"{environment_name} environment contains forbidden provider/data/build bindings: "
                f"{environment_bindings}"
            )

    preview = environments.get("preview", {})
    if not isinstance(preview, dict):
        errors.append("preview environment must be an object")
        preview = {}
    if preview.get("workers_dev") is not False or preview.get("preview_urls") is not True:
        errors.append("preview must disable the base workers.dev route and explicitly enable preview URLs")
    preview_vars = preview.get("vars", {})
    if not isinstance(preview_vars, dict) or preview_vars.get("PUBLIC_BETA_STATUS") != "NO_GO_UNPUBLISHED":
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

    try:
        integrity = _load_json(integrity_path)
    except CandidateInputError as exc:
        errors.append(str(exc))
        integrity = {}
    if integrity != VERIFIED_WRANGLER:
        errors.append("Wrangler supply-chain binding does not match verified 4.120.0 metadata")

    try:
        worker = _bounded_canonical_text(worker_path, 65_536)
    except CandidateInputError as exc:
        errors.append(str(exc))
        worker = ""
    for forbidden in (
        '"/voice/review"',
        "ACCESS_ISSUER",
        "CONTEXT_GATEWAY",
        "cf-access-jwt-assertion",
        "request.arrayBuffer(",
        "request.text(",
        "request.json(",
        "console.",
        "fetch(",
        "SEARCH_ORIGIN",
        "VECTORIZE",
        "api.openai.com",
    ):
        if forbidden in worker:
            errors.append(f"worker contains forbidden content/origin operation: {forbidden}")
    for required in (
        '"/healthz"',
        '"/version"',
        '"method_not_allowed"',
        '"runtime_configuration_denied"',
        '"not_found"',
        '"no-store"',
        '"NO_GO_UNPUBLISHED"',
        "current_truth_mutation: false",
    ):
        if required not in worker:
            errors.append(f"worker missing fail-closed marker: {required}")

    try:
        workflow = _bounded_canonical_text(workflow_path)
    except CandidateInputError as exc:
        errors.append(str(exc))
        workflow = ""
    hardened_upload_command = (
        "versions upload --config wrangler.jsonc --env preview --no-bundle --strict "
        "--x-provision=false --x-auto-create=false"
    )
    required_workflow = (
        "workflow_dispatch:",
        "refs/heads/main",
        "^[0-9a-f]{40}$",
        "refs/remotes/origin/codex/cloudflare-os-foundation",
        "path: trusted",
        "path: candidate",
        "ref: ${{ github.sha }}",
        "trusted/tools/validate_cloudflare_edge_candidate.py --root candidate",
        "needs: validate-candidate",
        "environment: cloudflare-preview",
        "persist-credentials: false",
        hardened_upload_command,
        'wranglerVersion: "4.120.0"',
        "packageManager: npm",
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
        "--preview-alias",
        "--assets",
        "--secrets-file",
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
    try:
        errors = validate(args.root)
    except (OSError, ValueError) as exc:
        errors = [f"candidate inspection failed closed: {type(exc).__name__}"]
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
