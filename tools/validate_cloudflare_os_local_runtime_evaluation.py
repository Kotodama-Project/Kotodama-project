#!/usr/bin/env python3
"""Validate the public-safe Cloudflare OS local runtime evaluation receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
from collections import Counter
from typing import Any

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # pragma: no cover - explicit dependency boundary
    Draft202012Validator = None
    FormatChecker = None


ROOT = pathlib.Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "runtime" / "cloudflare-os" / "local-runtime-evaluation.json"
SCHEMA = ROOT / "schemas" / "cloudflare-os-local-runtime-evaluation.schema.json"
UPSTREAM_PIN = ROOT / "runtime" / "cloudflare-os" / "upstream-pin.json"
SHIM = ROOT / "tools" / "cfos_pnpm_runtime_windows_shim.cs"
DOC = ROOT / "docs" / "CLOUDFLARE-OS-LOCAL-RUNTIME-EVALUATION.md"
RUNTIME_README = ROOT / "runtime" / "cloudflare-os" / "README.md"

EXPECTED_EFFECT_KEYS = {
    "provider_api_mutations",
    "deployments",
    "uploads",
    "dns_changes",
    "access_changes",
    "credential_changes",
    "billing_changes",
    "external_posts",
    "merges",
}
EXPECTED_FINDINGS = {
    "CFOS-DRIFT-REVIEW": "P1",
    "CFOS-AUDIT-NANOID": "P1",
    "CFOS-WINDOWS-LAUNCHER": "P1",
    "CFOS-OBSERVABILITY-DEFAULT": "P1",
    "CFOS-PROVIDER-E2E": "P1",
    "CFOS-SUPPLY-ATTESTATION": "P1",
    "CFOS-FRONTEND-SIZE": "P2",
    "CFOS-LINT-WARNINGS": "P2",
}
SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:sk|rk|pk)-[a-z0-9_-]{12,}\b"),
    re.compile(r"(?i)\bbearer\s+[a-z0-9_./+=-]{12,}\b"),
    re.compile(
        r"(?i)\b(?:api[_-]?token|access[_-]?token|client[_-]?secret)"
        r"\s*[:=]\s*['\"]?[a-z0-9_./+=-]{8,}"
    ),
)
LOCAL_PATH_PATTERNS = (
    re.compile(r"(?i)\b[a-z]:[\\/]+(?:users|documents|appdata)[\\/]+"),
    re.compile(r"/(?:home|users)/[^/\s]+/"),
)
RAW_DISCORD_ID = re.compile(r"(?<![0-9a-f])\d{17,20}(?![0-9a-f])")


class RuntimeEvaluationViolation(ValueError):
    """The evaluation receipt failed closed."""


def load_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeEvaluationViolation(f"cannot load JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeEvaluationViolation(f"JSON root must be an object: {path}")
    return value


def validate_schema(data: dict[str, Any], schema: dict[str, Any]) -> None:
    if Draft202012Validator is None or FormatChecker is None:
        raise RuntimeEvaluationViolation("jsonschema[format-nongpl] is required")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(data), key=lambda error: list(error.absolute_path))
    if errors:
        first = errors[0]
        location = "/".join(str(part) for part in first.absolute_path) or "$"
        raise RuntimeEvaluationViolation(f"schema validation failed at {location}: {first.message}")


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeEvaluationViolation(message)


def validate_source_binding(data: dict[str, Any], upstream: dict[str, Any]) -> None:
    source = data["source"]
    expected = {
        "starter": upstream["starter"],
        "pinned_core": upstream["starter_core_gitlink"],
        "observed_current_core": upstream["current_core_observation"],
    }
    for name, pin in expected.items():
        _require(source[name]["commit"] == pin["commit"], f"{name} commit drifted")
        _require(source[name]["tree"] == pin["tree"], f"{name} tree drifted")
    _require(data["toolchain"]["pnpm"] == "11.9.0", "pnpm version drifted")
    _require(upstream["starter"]["package_manager"] == "pnpm@11.9.0", "upstream pin pnpm drifted")


def validate_semantics(data: dict[str, Any], shim_path: pathlib.Path = SHIM) -> None:
    _require(data["status"] == "PASS_LOCAL_RUNTIME_WITH_GAPS", "status widened")
    _require(data["public_beta"] == "NO_GO_UNPUBLISHED", "Public Beta boundary widened")
    _require(data["content_policy"] == "CONTENT_FREE_SYNTHETIC_ONLY", "content policy widened")

    effects = data["effects"]
    _require(set(effects) == EXPECTED_EFFECT_KEYS, "effect key set drifted")
    _require(all(type(value) is int and value == 0 for value in effects.values()), "nonzero external effect")

    decision = data["decision"]
    _require(decision["adoption"] == "ADOPT_BOUNDED", "adoption widened")
    _require(decision["local_runtime_candidate"] == "PASS_WITH_GAPS", "local result widened")
    _require(decision["provider_preview_ready"] is False, "provider preview cannot be ready")
    _require(decision["production_ready"] is False, "production cannot be ready")

    source = data["source"]
    _require(source["drift"]["files_changed"] == 99, "upstream drift count changed")
    _require(source["drift"]["independent_review"] == "PENDING", "independent review is not proven")

    integrity = data["integrity"]
    _require(integrity["starter_lock_integrity_entries"] == 198, "starter lock integrity count drifted")
    _require(integrity["core_lock_integrity_entries"] == 802, "core lock integrity count drifted")
    _require(integrity["pnpm_tarball"]["traversal_entries"] == 0, "tar traversal was observed")
    _require(integrity["escaping_symlinks"] == 0, "escaping source symlink was observed")
    _require(integrity["pnpm_tarball"]["attestation_signature_verified"] is False,
             "attestation cannot be promoted without a separate verifier receipt")

    toolchain = data["toolchain"]
    _require(
        (toolchain["node"], toolchain["pnpm"], toolchain["wrangler"], toolchain["workerd"])
        == ("24.14.0", "11.9.0", "4.115.0", "1.20260731.1"),
        "toolchain binding drifted",
    )

    installation = data["verification"]["installation"]
    _require(installation["starter_packages"] == 97 and installation["core_packages"] == 663,
             "installation package count drifted")
    _require(
        installation["frozen_lockfile"] is True
        and installation["ignore_scripts"] is True
        and installation["credential_scrubbed"] is True,
        "installation safety boundary drifted",
    )

    tests = data["verification"]["tests"]
    _require(tests["passed"] == 1060 and tests["failed"] == 0 and tests["skipped"] == 7,
             "test totals drifted")
    build = data["verification"]["build"]
    _require(build["workspace_packages"] == 26, "build package count drifted")
    _require(build["official_recursive_passed"] + build["windows_adapter_passed"] == 26,
             "build coverage is incomplete")
    _require(build["failed"] == 0 and build["provider_mutation_commands"] == 0,
             "build receipt contains a failure or provider command")
    lint = data["verification"]["lint"]
    _require(lint["errors"] == 0 and lint["warnings"] == 64 and lint["unique_rules"] == 4,
             "lint receipt drifted")

    audit = data["verification"]["production_audit"]
    _require(audit["core_high"] == 1 and audit["core_critical"] == 0,
             "open production advisory must remain visible")
    _require(audit["affected_package"] == "nanoid" and audit["installed_version"] == "3.3.16",
             "production advisory binding drifted")

    runtime = data["verification"]["runtime"]
    _require(runtime["network_scope"] == "LOOPBACK_ONLY", "runtime was not loopback-only")
    _require(runtime["stable_headers_only_http_200"] == 3, "stable HTTP readback count drifted")
    _require(runtime["response_body_read"] is False, "runtime response body was read")
    _require(runtime["dev_vars_absent"] is True and runtime["credentials_scrubbed"] is True,
             "runtime credential boundary drifted")
    cleanup = runtime["cleanup"]
    _require(cleanup["remaining_processes"] == 0 and cleanup["remaining_listeners"] == 0,
             "runtime cleanup is incomplete")

    findings = data["findings"]
    items = findings["items"]
    ids = [item["id"] for item in items]
    _require(len(ids) == len(set(ids)), "duplicate finding id")
    observed = {item["id"]: item["severity"] for item in items}
    _require(observed == EXPECTED_FINDINGS, "finding inventory drifted")
    counts = Counter(item["severity"].lower() for item in items)
    _require(findings["p0"] == counts["p0"] == 0, "P0 count drifted")
    _require(findings["p1"] == counts["p1"] == 6, "P1 count drifted")
    _require(findings["p2"] == counts["p2"] == 2, "P2 count drifted")

    adapter = data["toolchain"]["windows_adapter"]
    _require(adapter["install_exit"] == 64 and adapter["remote_wrangler_exit"] == 64,
             "Windows adapter rejection contract drifted")
    _require(adapter["source_sha256"] == sha256_file(shim_path), "Windows adapter source hash drifted")
    shim_text = shim_path.read_text(encoding="utf-8")
    for marker in (
        "CFOS_EXACT_NODE_EXE",
        "CFOS_EVALUATION_ROOT",
        "IsExactViteBuild",
        "IsExactCapnwebBuild",
        "IsExactWorkshopBuildWorker",
        "IsLocalWranglerDev",
        "--remote",
        "RejectedCommand = 64",
    ):
        _require(marker in shim_text, f"Windows adapter marker missing: {marker}")


def validate_public_safety(data: dict[str, Any], paths: tuple[pathlib.Path, ...]) -> None:
    chunks = [json.dumps(data, ensure_ascii=False, sort_keys=True)]
    for path in paths:
        chunks.append(path.read_text(encoding="utf-8"))
    text = "\n".join(chunks)
    for pattern in SECRET_PATTERNS:
        _require(pattern.search(text) is None, "secret-shaped value found")
    for pattern in LOCAL_PATH_PATTERNS:
        _require(pattern.search(text) is None, "local absolute path found")
    _require(RAW_DISCORD_ID.search(text) is None, "raw Discord identifier found")
    _require("account_id" not in text.lower(), "raw provider account identifier field found")


def validate_docs(paths: tuple[pathlib.Path, ...] = (DOC, RUNTIME_README)) -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    for marker in (
        "1060",
        "P1",
        "nanoid",
        "independent review",
        "LOOPBACK_ONLY",
        "provider",
        "NO_GO_UNPUBLISHED",
    ):
        _require(marker in text, f"public runtime documentation marker missing: {marker}")


def validate(
    receipt_path: pathlib.Path = RECEIPT,
    schema_path: pathlib.Path = SCHEMA,
    upstream_path: pathlib.Path = UPSTREAM_PIN,
    shim_path: pathlib.Path = SHIM,
) -> dict[str, Any]:
    data = load_json(receipt_path)
    validate_schema(data, load_json(schema_path))
    validate_source_binding(data, load_json(upstream_path))
    validate_semantics(data, shim_path)
    validate_docs()
    validate_public_safety(data, (receipt_path, schema_path, shim_path, DOC, RUNTIME_README))
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "status": "PASS_LOCAL_RUNTIME_WITH_GAPS",
        "receipt_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "tests_passed": data["verification"]["tests"]["passed"],
        "tests_skipped": data["verification"]["tests"]["skipped"],
        "p0": data["findings"]["p0"],
        "p1": data["findings"]["p1"],
        "p2": data["findings"]["p2"],
        "external_effects": sum(data["effects"].values()),
        "public_beta": data["public_beta"],
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=pathlib.Path, default=RECEIPT)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        result = validate(receipt_path=args.receipt)
    except RuntimeEvaluationViolation as exc:
        if args.json:
            print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"FAIL {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(
            "PASS_LOCAL_RUNTIME_WITH_GAPS "
            f"tests={result['tests_passed']} skips={result['tests_skipped']} "
            f"P0/P1/P2={result['p0']}/{result['p1']}/{result['p2']} "
            f"effects={result['external_effects']} public_beta={result['public_beta']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
