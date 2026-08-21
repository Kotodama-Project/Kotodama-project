#!/usr/bin/env python3
"""Fail-closed, byte-bound Cloudflare OS security overlay preflight.

This module does not modify an upstream checkout.  It proves only that one
reviewable parent-scoped pnpm override has a deterministic workspace transform
for the pinned upstream Git blobs, and can verify separately supplied bytes
against one observed exact-pnpm lock binding.  It never synthesizes or edits a
lockfile.  Package-manager provenance, install, audit, tests, review,
deployment, and remediation remain separate gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "runtime" / "cloudflare-os" / "security-overlay.json"

KIND = "kotodama/cloudflare-os-security-overlay/v1"
STATUS = "LOCAL_MATERIALIZATION_VERIFIED_NOT_DEPLOYED"
PUBLIC_BETA = "NO_GO_UNPUBLISHED"
PINNED_COMMIT = "bf7f762d7fa73553284d731ab6a978d3ea17be24"
PINNED_TREE = "023da57719fa9744a4ca909f9c3863c93cb614fa"
CURRENT_COMMIT = "1cb5e3d9096589e38f3fcfaf3f2191aa95a4c592"
CURRENT_TREE = "2f1eb7b69cf6cbc0e0da159bf2cd09ef9a2ce7e7"
WORKSPACE_BLOB = "a6d915454aad18b607cd5242b7c8e31369cd248d"
LOCK_BLOB = "df0720a64cbda3efbc598fcbfdef2c7bf8977edc"
WORKSPACE_SHA256 = "ce7204ec08398d097c98b3b4f953d5a80e6d0572ffd848b77c70def1e2976843"
WORKSPACE_BYTES = 1066
LOCK_SHA256 = "efd6eb15379a2d02b1bdf0db776c50d421193ef78199baa043f93d99a1307258"
LOCK_BYTES = 285775
WORKSPACE_OUTPUT_SHA256 = "1fab3067c776f02e5b86e6dd78428ddba73ec25e0ccde91828743f79f86caff5"
WORKSPACE_OUTPUT_BYTES = 1159
LOCK_OUTPUT_SHA256 = "1e5d81f81c5a65bf797780148cb1f2bc806455330a541263751857a9275a81d5"
LOCK_OUTPUT_BYTES = 268881
LOCK_OUTPUT_LINES = 8040
GRAPH_MULTISET_SHA256 = "1d4a74b72bd8d7decd26c2a7c1fbb7786017ad35a385f4360f0762618b25d326"
REFERENCE_COMMIT = "9c18a2e8b0c3741e5f4813546bbf24be5bbb98ee"
REFERENCE_TREE = "9d34f65f4f34b98febc57f8da86cfc045da0736e"
REFERENCE_BLOB = "784ad17e03f89902eaaf611eba10635ba941933d"
REFERENCE_SHA256 = "48154f079d3710a518878a29a1a149c037f39a15e0fd03f4dd325c508fefecfc"
SELECTOR = "postcss@8.5.25>nanoid"
INSTALLED_VERSION = "3.3.16"
TARGET_VERSION = "3.3.18"
BROWSER_SELECTOR = "@cloudflare/puppeteer@1.2.0>@puppeteer/browsers"
BROWSER_SOURCE_VERSION = "2.2.4"
BROWSER_TARGET_VERSION = "3.0.4"
BROWSER_TARGET_INTEGRITY = "sha512-HGM8iAmGTf+Y7t0373szVbTmt3d7vPkYL/1bpOkOFO0YUYLgSeuYBCzESklogNPvOBnZ/MRD5f07OkpqH1trtA=="
ARCHIVE_TARGET_PACKAGE = "modern-tar"
ARCHIVE_TARGET_VERSION = "0.7.7"
ARCHIVE_TARGET_INTEGRITY = "sha512-t9VmxaqrmANnEOBhpSDI6HD192Ge48k8vmWqQQL7hSFEqHEYwZbbsu49+aKLWZeRvFs3j1pMhXOqqF4kPlvjkQ=="
PACKAGE_MANAGER = "pnpm@11.9.0"
OLD_INTEGRITY = "sha512-bzlKTyNJ7+LdGIIwy8ijFpIqEQIvafahV7eYykJ8Cvh42EdJeODoJ6gUJXpQJvej1BddH8OqTXZNE/KfbWAu8Q=="
NEW_INTEGRITY = "sha512-DTg4MJbGMWkfi6VZFdNt2/caMbQy4Ou+Op/hJQvGEWcnVfoA1QA+xzRKAzw9jD6+GVOOeYr/mIcuDSdug6F6+w=="
UNPROVEN = [
    "independent review of exact candidate bytes",
    "provider deployment or production remediation",
]
OVERRIDE_LINE = (
    f"  '{SELECTOR}': {TARGET_VERSION}\n"
    f"  '{BROWSER_SELECTOR}': {BROWSER_TARGET_VERSION}\n"
).encode("ascii")
OVERRIDES_ANCHOR = b"overrides:\n"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:sk|rk|pk)-[a-z0-9_-]{12,}\b"),
    re.compile(r"(?i)\bbearer\s+[a-z0-9_./+=-]{12,}\b"),
    re.compile(
        r"(?i)\b(?:api[_-]?token|access[_-]?token|client[_-]?secret)"
        r"\s*[:=]\s*['\"]?[a-z0-9_./+=-]{8,}"
    ),
)


class SecurityOverlayViolation(ValueError):
    """The candidate drifted or attempted to overclaim a closed gate."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SecurityOverlayViolation(message)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    _require(isinstance(value, dict), f"{label} must be an object")
    return value


def _require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    _require(actual == expected, f"{label} keys drifted: {sorted(actual ^ expected)}")


def _require_hex(value: Any, pattern: re.Pattern[str], label: str) -> None:
    _require(isinstance(value, str) and pattern.fullmatch(value) is not None, f"invalid {label}")


def load_spec(path: pathlib.Path = SPEC_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SecurityOverlayViolation(f"cannot load security overlay spec: {exc}") from exc
    return _require_mapping(value, "spec")


def _scan_public_spec(spec: dict[str, Any]) -> None:
    rendered = json.dumps(spec, ensure_ascii=False, sort_keys=True)
    for pattern in SECRET_PATTERNS:
        _require(pattern.search(rendered) is None, "secret-shaped value in security overlay spec")
    lowered = rendered.lower().replace("/", "\\")
    for marker in (
        "source_thread_id",
        ".codex\\attachments",
        "appdata\\local\\temp",
        "account_id",
        "api_token",
        "@gmail.com",
    ):
        _require(marker not in lowered, f"private or provider identifier marker in spec: {marker}")


def _validate_spec(spec: dict[str, Any], *, bind_exact_bytes: bool) -> None:
    _require_exact_keys(
        spec,
        {
            "kind",
            "status",
            "observed_at",
            "source",
            "graph",
            "remediation",
            "gates",
            "effects",
            "unproven",
            "public_beta",
        },
        "spec",
    )
    _require(spec["kind"] == KIND, "security overlay kind drifted")
    _require(spec["status"] == STATUS, "security overlay must remain a non-remediated candidate")
    _require(spec["public_beta"] == PUBLIC_BETA, "Public Beta must remain NO_GO_UNPUBLISHED")
    _require(
        isinstance(spec["observed_at"], str)
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", spec["observed_at"]) is not None,
        "observed_at must be a UTC second timestamp",
    )

    source = _require_mapping(spec["source"], "source")
    _require_exact_keys(
        source,
        {"pinned_core", "current_core_observation", "workspace", "lock", "target_integrity_reference"},
        "source",
    )
    pinned = _require_mapping(source.get("pinned_core"), "source.pinned_core")
    current = _require_mapping(source.get("current_core_observation"), "source.current_core_observation")
    _require(pinned == {"commit": PINNED_COMMIT, "tree": PINNED_TREE}, "pinned core drifted")
    _require(
        current
        == {"commit": CURRENT_COMMIT, "tree": CURRENT_TREE, "still_vulnerable": True},
        "current core observation drifted",
    )
    _require(PINNED_COMMIT != CURRENT_COMMIT, "pinned and observed-current core were conflated")

    expected_sources = {
        "workspace": (WORKSPACE_BLOB, WORKSPACE_SHA256, WORKSPACE_BYTES),
        "lock": (LOCK_BLOB, LOCK_SHA256, LOCK_BYTES),
    }
    for label in ("workspace", "lock"):
        item = _require_mapping(source.get(label), f"source.{label}")
        _require_exact_keys(
            item,
            {"path", "blob_oid", "canonical_sha256", "canonical_bytes", "line_endings"},
            f"source.{label}",
        )
        _require_hex(item.get("blob_oid"), HEX40, f"source.{label}.blob_oid")
        expected_blob, expected_sha, expected_bytes = expected_sources[label]
        _require(item["blob_oid"] == expected_blob, f"source.{label}.blob_oid drifted")
        _require_hex(item.get("canonical_sha256"), HEX64, f"source.{label}.canonical_sha256")
        _require(type(item.get("canonical_bytes")) is int and item["canonical_bytes"] > 0, f"invalid {label} byte count")
        _require(item.get("line_endings") == "LF", f"{label} must bind canonical Git LF bytes")
        if bind_exact_bytes:
            _require(item["canonical_sha256"] == expected_sha, f"source.{label}.canonical_sha256 drifted")
            _require(item["canonical_bytes"] == expected_bytes, f"source.{label}.canonical_bytes drifted")
    _require(source["workspace"]["path"] == "pnpm-workspace.yaml", "workspace path drifted")
    _require(source["lock"]["path"] == "pnpm-lock.yaml", "lock path drifted")

    reference = _require_mapping(source.get("target_integrity_reference"), "target_integrity_reference")
    _require(
        reference
        == {
            "repository": "cloudflare/cloudflare-os-starter",
            "commit": REFERENCE_COMMIT,
            "tree": REFERENCE_TREE,
            "path": "pnpm-lock.yaml",
            "blob_oid": REFERENCE_BLOB,
            "canonical_sha256": REFERENCE_SHA256,
        },
        "target integrity reference drifted",
    )

    graph = _require_mapping(spec["graph"], "graph")
    _require_exact_keys(
        graph,
        {
            "package",
            "installed_version",
            "parent_package",
            "parent_version",
            "route_tail",
            "affected_paths",
            "unique_projects",
            "package_path_multiset_sha256",
            "advisory",
        },
        "graph",
    )
    _require(graph.get("package") == "nanoid", "package drifted")
    _require(graph.get("installed_version") == INSTALLED_VERSION, "installed version drifted")
    _require(graph.get("parent_package") == "postcss", "parent package drifted")
    _require(graph.get("parent_version") == "8.5.25", "parent version drifted")
    _require(graph.get("route_tail") == "vite", "dependency route tail drifted")
    _require(graph.get("affected_paths") == 19, "affected path denominator drifted")
    _require(graph.get("unique_projects") == 18, "affected project denominator drifted")
    _require_hex(graph.get("package_path_multiset_sha256"), HEX64, "package path multiset hash")
    _require(graph["package_path_multiset_sha256"] == GRAPH_MULTISET_SHA256, "package path multiset hash drifted")
    advisory = _require_mapping(graph.get("advisory"), "graph.advisory")
    _require(
        advisory
        == {
            "id": "GHSA-2v37-7h3g-55p8",
            "severity": "high",
            "vulnerable_range": "<3.3.18",
            "url": "https://github.com/advisories/GHSA-2v37-7h3g-55p8",
        },
        "advisory binding drifted",
    )

    remediation = _require_mapping(spec["remediation"], "remediation")
    _require_exact_keys(
        remediation,
        {
            "strategy",
            "selector",
            "target_version",
            "package_manager",
            "old_integrity",
            "new_integrity",
            "ambient_latest_allowed",
            "manual_lock_edit_accepted",
            "companion",
            "expected_input",
            "expected_workspace_output",
            "observed_generated_lock",
        },
        "remediation",
    )
    _require(remediation.get("strategy") == "ROOT_PARENT_SCOPED_PNPM_OVERRIDE_AND_GENERATED_FROZEN_LOCK", "strategy drifted")
    _require(remediation.get("selector") == SELECTOR, "override must remain parent-scoped")
    _require(remediation.get("target_version") == TARGET_VERSION, "target must remain the first patched version")
    _require(remediation.get("package_manager") == PACKAGE_MANAGER, "package manager must remain exactly pinned")
    _require(remediation.get("ambient_latest_allowed") is False, "ambient latest is forbidden")
    _require(remediation.get("manual_lock_edit_accepted") is False, "manual lock editing cannot prove remediation")
    _require(remediation.get("old_integrity") == OLD_INTEGRITY, "old integrity binding drifted")
    _require(remediation.get("new_integrity") == NEW_INTEGRITY, "new integrity binding drifted")

    companion = _require_mapping(remediation.get("companion"), "companion")
    _require(
        companion
        == {
            "advisory": {
                "id": "GHSA-jmr9-qjv8-65gv",
                "severity": "high",
                "vulnerable_range": "<=2.0.1",
                "patched_direct_versions": [],
                "url": "https://github.com/advisories/GHSA-jmr9-qjv8-65gv",
            },
            "vulnerable_package": "extract-zip",
            "installed_version": "2.0.1",
            "parent_package": "@puppeteer/browsers",
            "parent_version": BROWSER_SOURCE_VERSION,
            "strategy": "PARENT_SCOPED_PARENT_REPLACEMENT_NO_PATCHED_DIRECT_RELEASE",
            "selector": BROWSER_SELECTOR,
            "target_package": "@puppeteer/browsers",
            "target_version": BROWSER_TARGET_VERSION,
            "target_integrity": BROWSER_TARGET_INTEGRITY,
            "target_archive_package": ARCHIVE_TARGET_PACKAGE,
            "target_archive_version": ARCHIVE_TARGET_VERSION,
            "target_archive_integrity": ARCHIVE_TARGET_INTEGRITY,
        },
        "companion remediation binding drifted",
    )

    expected_input = _require_mapping(remediation.get("expected_input"), "expected_input")
    _require(
        expected_input
        == {
            "workspace_override": 0,
            "companion_workspace_override": 0,
            "lock_override": 0,
            "companion_lock_override": 0,
            "vulnerable_lock_markers": 4,
            "target_lock_markers": 0,
            "source_browser_package_key_markers": 2,
            "source_browser_dependency_edge_markers": 1,
            "vulnerable_extract_zip_package_key_markers": 2,
            "vulnerable_extract_zip_dependency_edge_markers": 1,
        },
        "expected input counts drifted",
    )
    expected_workspace = _require_mapping(
        remediation.get("expected_workspace_output"), "expected_workspace_output"
    )
    _require_exact_keys(
        expected_workspace,
        {
            "workspace_override",
            "companion_workspace_override",
            "canonical_sha256",
            "canonical_bytes",
        },
        "expected_workspace_output",
    )
    _require(expected_workspace.get("workspace_override") == 1, "workspace output override count drifted")
    _require(
        expected_workspace.get("companion_workspace_override") == 1,
        "companion workspace output override count drifted",
    )
    _require_hex(expected_workspace.get("canonical_sha256"), HEX64, "expected workspace output hash")
    _require(
        type(expected_workspace.get("canonical_bytes")) is int
        and expected_workspace["canonical_bytes"] > 0,
        "invalid expected workspace output byte count",
    )

    generated = _require_mapping(
        remediation.get("observed_generated_lock"), "observed_generated_lock"
    )
    _require_exact_keys(
        generated,
        {
            "evidence_status",
            "package_manager",
            "generation_mode",
            "registry",
            "generated_at",
            "node",
            "package_manager_archive_sha1",
            "package_manager_archive_sha512",
            "frozen_install_ignore_scripts",
            "production_audit_high",
            "recursive_build_projects",
            "focused_test_passed",
            "focused_test_skipped",
            "lock_override",
            "companion_lock_override",
            "vulnerable_lock_markers",
            "target_lock_markers",
            "new_package_key_markers",
            "new_dependency_edge_markers",
            "new_integrity_markers",
            "source_browser_package_key_markers",
            "source_browser_dependency_edge_markers",
            "vulnerable_extract_zip_package_key_markers",
            "vulnerable_extract_zip_dependency_edge_markers",
            "target_browser_package_key_markers",
            "target_browser_dependency_edge_markers",
            "target_browser_integrity_markers",
            "target_archive_package_key_markers",
            "target_archive_dependency_edge_markers",
            "target_archive_integrity_markers",
            "canonical_sha256",
            "canonical_bytes",
            "canonical_lines",
        },
        "observed_generated_lock",
    )
    _require(
        generated.get("evidence_status") == "EXACT_PNPM_11_9_LOCAL_OUTPUT_BOUND_WITH_PROVENANCE_RECEIPT",
        "generated lock evidence status drifted",
    )
    _require(generated.get("package_manager") == PACKAGE_MANAGER, "generated lock package manager drifted")
    _require(
        generated.get("generation_mode")
        == "LOCKFILE_ONLY_PREFER_OFFLINE_FIXED_PUBLIC_REGISTRY_IGNORE_SCRIPTS_NO_RUNTIME",
        "generated lock mode drifted",
    )
    _require(generated.get("registry") == "https://registry.npmjs.org/", "registry binding drifted")
    _require(generated.get("generated_at") == "2026-08-21T00:00:49Z", "generation time drifted")
    _require(generated.get("node") == "24.19.0", "Node binding drifted")
    _require(
        generated.get("package_manager_archive_sha1")
        == "10da06e30a629cc94ecf7ca009c6ce696f55fbf1",
        "package manager SHA-1 drifted",
    )
    _require(
        generated.get("package_manager_archive_sha512")
        == "bd682d5d03fe525ef7c9fd6780c6884d1e756ac4c9c9fe00c538782824310dcf90e3ddc4f53835f06dfaebd5085e41855e0bcbb3b60de2ac5bbab89e5036f03b",
        "package manager SHA-512 drifted",
    )
    _require(generated.get("frozen_install_ignore_scripts") is True, "frozen install evidence drifted")
    _require(generated.get("production_audit_high") == 0, "production audit high count drifted")
    _require(generated.get("recursive_build_projects") == 26, "recursive build denominator drifted")
    _require(generated.get("focused_test_passed") == 279, "focused test pass count drifted")
    _require(generated.get("focused_test_skipped") == 4, "focused test skip count drifted")
    for field, value in {
        "lock_override": 1,
        "companion_lock_override": 1,
        "vulnerable_lock_markers": 0,
        "target_lock_markers": 5,
        "new_package_key_markers": 2,
        "new_dependency_edge_markers": 2,
        "new_integrity_markers": 1,
        "source_browser_package_key_markers": 0,
        "source_browser_dependency_edge_markers": 0,
        "vulnerable_extract_zip_package_key_markers": 0,
        "vulnerable_extract_zip_dependency_edge_markers": 0,
        "target_browser_package_key_markers": 2,
        "target_browser_dependency_edge_markers": 1,
        "target_browser_integrity_markers": 1,
        "target_archive_package_key_markers": 2,
        "target_archive_dependency_edge_markers": 1,
        "target_archive_integrity_markers": 1,
    }.items():
        _require(generated.get(field) == value, f"generated lock count drifted: {field}")
    _require_hex(generated.get("canonical_sha256"), HEX64, "observed generated lock hash")
    for field in ("canonical_bytes", "canonical_lines"):
        _require(type(generated.get(field)) is int and generated[field] > 0, f"invalid generated lock {field}")
    if bind_exact_bytes:
        _require(
            expected_workspace["canonical_sha256"] == WORKSPACE_OUTPUT_SHA256,
            "expected workspace output hash drifted",
        )
        _require(expected_workspace["canonical_bytes"] == WORKSPACE_OUTPUT_BYTES, "expected workspace output bytes drifted")
        _require(generated["canonical_sha256"] == LOCK_OUTPUT_SHA256, "observed generated lock hash drifted")
        _require(generated["canonical_bytes"] == LOCK_OUTPUT_BYTES, "observed generated lock bytes drifted")
        _require(generated["canonical_lines"] == LOCK_OUTPUT_LINES, "observed generated lock lines drifted")

    gates = _require_mapping(spec["gates"], "gates")
    _require_exact_keys(
        gates,
        {
            "preflight",
            "materialized",
            "pinned_pnpm_11_9",
            "generated_lock_verified",
            "frozen_lock_install_ignore_scripts",
            "production_audit_zero_high",
            "focused_tests_and_build",
            "independent_review",
        },
        "gates",
    )
    _require(
        gates
        == {
            "preflight": True,
            "materialized": True,
            "pinned_pnpm_11_9": True,
            "generated_lock_verified": True,
            "frozen_lock_install_ignore_scripts": True,
            "production_audit_zero_high": True,
            "focused_tests_and_build": True,
            "independent_review": False,
        },
        "local verification gates drifted",
    )

    effects = _require_mapping(spec["effects"], "effects")
    _require_exact_keys(
        effects,
        {
            "dependency_update",
            "source_write",
            "install",
            "provider_call",
            "workflow_run",
            "deploy",
            "merge",
            "promotion",
            "current_truth_change",
        },
        "effects",
    )
    _require(
        effects
        == {
            "dependency_update": 0,
            "source_write": 0,
            "install": 1,
            "provider_call": 0,
            "workflow_run": 0,
            "deploy": 0,
            "merge": 0,
            "promotion": 0,
            "current_truth_change": 0,
        },
        "effect receipt drifted",
    )
    _require(spec["unproven"] == UNPROVEN, "unproven boundary drifted")
    _scan_public_spec(spec)


def validate_spec(spec: dict[str, Any]) -> None:
    """Validate the authoritative public spec against immutable known bindings."""

    _validate_spec(spec, bind_exact_bytes=True)


def _markers(lock_bytes: bytes, spec: dict[str, Any]) -> dict[str, int]:
    remediation = spec["remediation"]
    old_integrity = remediation["old_integrity"].encode("ascii")
    new_integrity = remediation["new_integrity"].encode("ascii")
    old_key = f"nanoid@{INSTALLED_VERSION}:".encode("ascii")
    new_key = f"nanoid@{TARGET_VERSION}:".encode("ascii")
    old_edge = f"nanoid: {INSTALLED_VERSION}".encode("ascii")
    new_edge = f"nanoid: {TARGET_VERSION}".encode("ascii")
    source_browser_key = f"@puppeteer/browsers@{BROWSER_SOURCE_VERSION}".encode("ascii")
    source_browser_edge = f"'@puppeteer/browsers': {BROWSER_SOURCE_VERSION}".encode("ascii")
    vulnerable_extract_zip_key = b"extract-zip@2.0.1"
    vulnerable_extract_zip_edge = b"extract-zip: 2.0.1"
    target_browser_key = f"@puppeteer/browsers@{BROWSER_TARGET_VERSION}".encode("ascii")
    target_browser_edge = f"'@puppeteer/browsers': {BROWSER_TARGET_VERSION}".encode("ascii")
    target_browser_integrity = BROWSER_TARGET_INTEGRITY.encode("ascii")
    target_archive_key = f"{ARCHIVE_TARGET_PACKAGE}@{ARCHIVE_TARGET_VERSION}:".encode("ascii")
    target_archive_edge = f"{ARCHIVE_TARGET_PACKAGE}: {ARCHIVE_TARGET_VERSION}".encode("ascii")
    target_archive_integrity = ARCHIVE_TARGET_INTEGRITY.encode("ascii")
    vulnerable = lock_bytes.count(old_key) + lock_bytes.count(old_edge) + lock_bytes.count(old_integrity)
    target = lock_bytes.count(new_key) + lock_bytes.count(new_edge) + lock_bytes.count(new_integrity)
    return {
        "vulnerable_lock_markers": vulnerable,
        "target_lock_markers": target,
        "old_key": lock_bytes.count(old_key),
        "old_edge": lock_bytes.count(old_edge),
        "old_integrity": lock_bytes.count(old_integrity),
        "new_key": lock_bytes.count(new_key),
        "new_edge": lock_bytes.count(new_edge),
        "new_integrity": lock_bytes.count(new_integrity),
        "source_browser_key": lock_bytes.count(source_browser_key),
        "source_browser_edge": lock_bytes.count(source_browser_edge),
        "vulnerable_extract_zip_key": lock_bytes.count(vulnerable_extract_zip_key),
        "vulnerable_extract_zip_edge": lock_bytes.count(vulnerable_extract_zip_edge),
        "target_browser_key": lock_bytes.count(target_browser_key),
        "target_browser_edge": lock_bytes.count(target_browser_edge),
        "target_browser_integrity": lock_bytes.count(target_browser_integrity),
        "target_archive_key": lock_bytes.count(target_archive_key),
        "target_archive_edge": lock_bytes.count(target_archive_edge),
        "target_archive_integrity": lock_bytes.count(target_archive_integrity),
    }


def apply_workspace_overlay(
    workspace_bytes: bytes, lock_bytes: bytes, spec: dict[str, Any]
) -> tuple[bytes, dict[str, Any]]:
    """Return only transformed workspace bytes; never synthesize a lockfile."""

    _validate_spec(spec, bind_exact_bytes=False)
    _require(isinstance(workspace_bytes, bytes) and isinstance(lock_bytes, bytes), "inputs must be bytes")
    _require(b"\r" not in workspace_bytes and b"\r" not in lock_bytes, "only canonical LF Git bytes are accepted")
    _require(workspace_bytes.count(OVERRIDES_ANCHOR) == 1, "workspace overrides anchor drifted")
    _require(lock_bytes.count(OVERRIDES_ANCHOR) == 1, "lock overrides anchor drifted")
    _require(workspace_bytes.count(SELECTOR.encode("ascii")) == 0, "workspace overlay already applied")
    _require(lock_bytes.count(SELECTOR.encode("ascii")) == 0, "lock overlay already applied")
    _require(
        workspace_bytes.count(BROWSER_SELECTOR.encode("ascii")) == 0,
        "companion workspace overlay already applied",
    )
    _require(
        lock_bytes.count(BROWSER_SELECTOR.encode("ascii")) == 0,
        "companion lock overlay already applied",
    )

    before_markers = _markers(lock_bytes, spec)
    expected_before = spec["remediation"]["expected_input"]
    _require(before_markers["old_key"] == 2, "vulnerable package-key count drifted")
    _require(before_markers["old_edge"] == 1, "vulnerable dependency-edge count drifted")
    _require(before_markers["old_integrity"] == 1, "vulnerable integrity count drifted")
    _require(before_markers["vulnerable_lock_markers"] == expected_before["vulnerable_lock_markers"], "vulnerable marker denominator drifted")
    _require(before_markers["target_lock_markers"] == expected_before["target_lock_markers"], "target marker precondition drifted")
    for marker, expected_field in {
        "source_browser_key": "source_browser_package_key_markers",
        "source_browser_edge": "source_browser_dependency_edge_markers",
        "vulnerable_extract_zip_key": "vulnerable_extract_zip_package_key_markers",
        "vulnerable_extract_zip_edge": "vulnerable_extract_zip_dependency_edge_markers",
    }.items():
        _require(
            before_markers[marker] == expected_before[expected_field],
            f"companion input marker drifted: {expected_field}",
        )

    workspace_out = workspace_bytes.replace(OVERRIDES_ANCHOR, OVERRIDES_ANCHOR + OVERRIDE_LINE, 1)
    expected_after = spec["remediation"]["expected_workspace_output"]
    workspace_override = workspace_out.count(SELECTOR.encode("ascii"))
    companion_workspace_override = workspace_out.count(BROWSER_SELECTOR.encode("ascii"))
    _require(workspace_override == expected_after["workspace_override"], "workspace output override count drifted")
    _require(
        companion_workspace_override == expected_after["companion_workspace_override"],
        "companion workspace output override count drifted",
    )

    report = {
        "before": {
            "workspace_override": 0,
            "companion_workspace_override": 0,
            "lock_override": 0,
            "companion_lock_override": 0,
            "vulnerable_lock_markers": before_markers["vulnerable_lock_markers"],
            "target_lock_markers": before_markers["target_lock_markers"],
        },
        "after": {
            "workspace_override": workspace_override,
            "companion_workspace_override": companion_workspace_override,
            "lock_writes": 0,
            "source_lock_sha256": _sha256(lock_bytes),
        },
    }
    return workspace_out, report


def verify_observed_generated_lock(
    workspace_bytes: bytes, lock_bytes: bytes, spec: dict[str, Any]
) -> dict[str, Any]:
    """Verify exact bound output bytes without asserting who generated them."""

    _validate_spec(spec, bind_exact_bytes=False)
    _require(isinstance(workspace_bytes, bytes) and isinstance(lock_bytes, bytes), "inputs must be bytes")
    _require(b"\r" not in workspace_bytes and b"\r" not in lock_bytes, "only canonical LF bytes are accepted")
    workspace = spec["remediation"]["expected_workspace_output"]
    generated = spec["remediation"]["observed_generated_lock"]
    _require(len(workspace_bytes) == workspace["canonical_bytes"], "workspace output byte count drifted")
    _require(_sha256(workspace_bytes) == workspace["canonical_sha256"], "workspace output hash drifted")
    _require(len(lock_bytes) == generated["canonical_bytes"], "generated lock byte count drifted")
    _require(_sha256(lock_bytes) == generated["canonical_sha256"], "generated lock hash drifted")
    _require(lock_bytes.count(b"\n") == generated["canonical_lines"], "generated lock line count drifted")
    _require(workspace_bytes.count(SELECTOR.encode("ascii")) == 1, "workspace selector count drifted")
    _require(lock_bytes.count(SELECTOR.encode("ascii")) == generated["lock_override"], "lock selector count drifted")
    _require(
        workspace_bytes.count(BROWSER_SELECTOR.encode("ascii")) == 1,
        "companion workspace selector count drifted",
    )
    _require(
        lock_bytes.count(BROWSER_SELECTOR.encode("ascii")) == generated["companion_lock_override"],
        "companion lock selector count drifted",
    )
    markers = _markers(lock_bytes, spec)
    _require(
        markers["vulnerable_lock_markers"] == generated["vulnerable_lock_markers"],
        "generated lock retains vulnerable markers",
    )
    _require(
        markers["target_lock_markers"] == generated["target_lock_markers"],
        "generated lock target marker count drifted",
    )
    _require(markers["new_key"] == generated["new_package_key_markers"], "generated package-key count drifted")
    _require(markers["new_edge"] == generated["new_dependency_edge_markers"], "generated dependency-edge count drifted")
    _require(markers["new_integrity"] == generated["new_integrity_markers"], "generated integrity count drifted")
    for marker, generated_field in {
        "source_browser_key": "source_browser_package_key_markers",
        "source_browser_edge": "source_browser_dependency_edge_markers",
        "vulnerable_extract_zip_key": "vulnerable_extract_zip_package_key_markers",
        "vulnerable_extract_zip_edge": "vulnerable_extract_zip_dependency_edge_markers",
        "target_browser_key": "target_browser_package_key_markers",
        "target_browser_edge": "target_browser_dependency_edge_markers",
        "target_browser_integrity": "target_browser_integrity_markers",
        "target_archive_key": "target_archive_package_key_markers",
        "target_archive_edge": "target_archive_dependency_edge_markers",
        "target_archive_integrity": "target_archive_integrity_markers",
    }.items():
        _require(
            markers[marker] == generated[generated_field],
            f"generated companion marker count drifted: {generated_field}",
        )
    return {
        "status": "PASS_BOUND_GENERATED_LOCK_BYTES_NO_PROVENANCE",
        "workspace_sha256": _sha256(workspace_bytes),
        "lock_sha256": _sha256(lock_bytes),
        "vulnerable_lock_markers": markers["vulnerable_lock_markers"],
        "target_lock_markers": markers["target_lock_markers"],
        "package_manager_provenance_recorded": True,
        "package_manager_provenance_verified_by_bytes": False,
        "remediation_proven": False,
        "public_beta": PUBLIC_BETA,
    }


def evaluate_source_bytes(workspace_bytes: bytes, lock_bytes: bytes, spec: dict[str, Any]) -> dict[str, Any]:
    """Evaluate exact source bytes; never claim package-manager materialization."""

    validate_spec(spec)
    for label, value in (("workspace", workspace_bytes), ("lock", lock_bytes)):
        source = spec["source"][label]
        _require(len(value) == source["canonical_bytes"], f"{label} input byte count drifted")
        _require(_sha256(value) == source["canonical_sha256"], f"{label} input hash drifted")

    workspace_out, report = apply_workspace_overlay(workspace_bytes, lock_bytes, spec)
    expected = spec["remediation"]["expected_workspace_output"]
    _require(len(workspace_out) == expected["canonical_bytes"], "workspace output byte count drifted")
    _require(_sha256(workspace_out) == expected["canonical_sha256"], "workspace output hash drifted")
    report.update(
        {
            "status": "PASS_WORKSPACE_OVERLAY_PREFLIGHT",
            "materialized": False,
            "remediation_proven": False,
            "workspace_output_sha256": _sha256(workspace_out),
            "observed_generated_lock_sha256": spec["remediation"]["observed_generated_lock"]["canonical_sha256"],
            "manual_lock_bytes_generated": 0,
            "effects": dict(spec["effects"]),
            "public_beta": PUBLIC_BETA,
        }
    )
    return report


def _git_blob(repo: pathlib.Path, commit: str, path: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "blob", f"{commit}:{path}"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SecurityOverlayViolation(f"cannot read bound Git blob: {path}") from exc
    return result.stdout


def _git_oid(repo: pathlib.Path, expression: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", expression],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SecurityOverlayViolation("cannot resolve bound Git object") from exc
    value = result.stdout.strip()
    _require(HEX40.fullmatch(value) is not None, "resolved Git object is not an OID")
    return value


def evaluate_git_source(repo: pathlib.Path, spec: dict[str, Any]) -> dict[str, Any]:
    """Read authoritative bytes from the pinned commit, not a dirty worktree."""

    validate_spec(spec)
    repo = repo.resolve()
    _require((repo / ".git").exists(), "core repository is not a Git checkout")
    commit = spec["source"]["pinned_core"]["commit"]
    _require(_git_oid(repo, f"{commit}^{{tree}}") == spec["source"]["pinned_core"]["tree"], "pinned tree OID drifted")
    for label in ("workspace", "lock"):
        item = spec["source"][label]
        _require(_git_oid(repo, f"{commit}:{item['path']}") == item["blob_oid"], f"{label} blob OID drifted")
    workspace = _git_blob(repo, commit, spec["source"]["workspace"]["path"])
    lock = _git_blob(repo, commit, spec["source"]["lock"]["path"])
    return evaluate_source_bytes(workspace, lock, spec)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-repo", type=pathlib.Path, help="read exact pinned blobs from this local Git checkout")
    args = parser.parse_args(argv)
    try:
        spec = load_spec()
        validate_spec(spec)
        if args.core_repo is None:
            result: dict[str, Any] = {
                "status": "PASS_SPEC_ONLY",
                "materialized": False,
                "remediation_proven": False,
                "effects": dict(spec["effects"]),
                "public_beta": PUBLIC_BETA,
            }
        else:
            result = evaluate_git_source(args.core_repo, spec)
    except SecurityOverlayViolation as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
