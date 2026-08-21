#!/usr/bin/env python3
"""Read-only, fail-closed validator for the A022 public architecture candidate."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path("migration/a022-public-architecture.manifest.json")
LICENSE_PATH = Path("LICENSES/MIT.txt")
SOURCE_COMMIT = "2fc1bf60b0dc8721c96875788447e34adc4c7216"
SOURCE_LICENSE_BLOB = "8294a2a3706f3fd652b8c1bae22a1024ade9406c"
SOURCE_PACKAGE_BLOB = "39804f52b523024c8b62eae678f897166ae0a47a"
SOURCE_MAPPING_DIGEST = "48dd3a64e4d2e18288445e08c2921028d4a6909e9d7333eafee0d73c225dceb5"

DESTINATIONS = {
    "docs/architecture/README.md": "f7e40d2803a97c151a338ff5c52b7d2a78ae854f",
    "docs/architecture/multi-agent-coordination.md": "a6adf2717798dc742e627e3e35226c2695ec206e",
    "docs/architecture/plan-runtime.md": "25f7484d6c17e50dfcfb690dedf51d9383748748",
    "docs/architecture/supervision-contract.md": "f7ca884b5cd34fb890842f668ca2af4d57f4edff",
}
CONSOLIDATIONS = {
    "coordination": ("docs/architecture/multi-agent-coordination.md", 2),
    "plan-lifecycle": ("docs/architecture/plan-runtime.md", 1),
    "principles-boundaries": ("docs/architecture/README.md", 2),
    "supervision": ("docs/architecture/supervision-contract.md", 1),
}
SUPERSEDED_REFS = {
    "CONTRIBUTING.md": (
        "173a73643f5273b0a7bc104b66b0caa6b7e67286",
        "fbb6da377edd2b726a854912eb17c964a1ec01e9:CONTRIBUTING.md",
    ),
    "STATUS.md": (
        "71877969c3eae7f32d928884a9e7766a6945a0ea",
        "fbb6da377edd2b726a854912eb17c964a1ec01e9:STATUS.md",
    ),
}
REQUIRED_PATHS = {
    MANIFEST_PATH,
    LICENSE_PATH,
    Path("tools/validate_migration_batch_a022.py"),
    Path("tests/test_migration_batch_a022.py"),
    *(Path(path) for path in DESTINATIONS),
}
MAPPING_DIGEST_KEYS = (
    "source_path",
    "source_blob_sha",
    "source_mode",
    "decision",
    "destination_path",
    "destination_blob_sha",
    "consolidation_group",
    "body_exported",
    "semantic_coverage",
    "rationale",
)

SECRET_DETECTORS = {
    "aws_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "scm_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "model_api_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "assigned_credential": re.compile(
        r"(?i)\b(?:api[_-]?key|password|credential|auth[_-]?token)\b"
        r"\s*[:=]\s*[\"']?[A-Za-z0-9/+_.-]{12,}"
    ),
}
PII_DETECTORS = {
    "email": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    "ipv4": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "phone_like": re.compile(r"(?<!\w)(?:\+?\d[\d ()-]{8,}\d)(?!\w)"),
    "absolute_user_path": re.compile(r"(?:/(?:home|Users|root)/|[A-Za-z]:\\Users\\)"),
}
PRIVATE_CATEGORY_DETECTORS = {
    "named_provider": re.compile(
        r"\b(?:OpenClaw|Cloudflare|Discord|Proxmox|n8n)\b", re.I
    ),
    "private_repository_area": re.compile(
        r"(?:\.claude/|\.cursor/|\.kotodama/|\bplatform/|\bregistry/|\bknowledge/|\bforest/)",
        re.I,
    ),
    "live_connection_url": re.compile(
        r"\b(?:https?|wss?|postgres(?:ql)?|redis|ssh)://[^\s<>()]+", re.I
    ),
}


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()  # noqa: S324 - Git identity


def _read_bounded(root: Path, relative: Path, errors: list[str]) -> bytes | None:
    try:
        resolved = (root / relative).resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        errors.append(f"missing or escaping path: {relative.as_posix()}")
        return None
    if not resolved.is_file():
        errors.append(f"not a regular file: {relative.as_posix()}")
        return None
    data = resolved.read_bytes()
    if len(data) > 256 * 1024:
        errors.append(f"file exceeds 262144 bytes: {relative.as_posix()}")
        return None
    return data


def _load_json(root: Path, relative: Path, errors: list[str]) -> Any:
    data = _read_bounded(root, relative, errors)
    if data is None:
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        errors.append(f"invalid UTF-8 JSON: {relative.as_posix()}")
        return None


def _mapping_digest(entries: list[dict[str, Any]]) -> str:
    rows = [{key: entry.get(key) for key in MAPPING_DIGEST_KEYS} for entry in entries]
    payload = json.dumps(
        rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _scan_text(relative: Path, text: str) -> list[str]:
    findings: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for detector, pattern in {
            **SECRET_DETECTORS,
            **PII_DETECTORS,
            **PRIVATE_CATEGORY_DETECTORS,
        }.items():
            if pattern.search(line):
                findings.append(
                    f"candidate scan finding {detector}: {relative.as_posix()}:{line_number}"
                )
    return findings


def _scan_manifest_strings(value: Any, path: tuple[str, ...] = ()) -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "source_path":
                continue
            findings.extend(_scan_manifest_strings(child, (*path, key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_scan_manifest_strings(child, (*path, str(index))))
    elif isinstance(value, str):
        label = ".".join(path) or "manifest"
        for detector, pattern in {
            **SECRET_DETECTORS,
            **PII_DETECTORS,
            **PRIVATE_CATEGORY_DETECTORS,
        }.items():
            if pattern.search(value):
                findings.append(f"candidate scan finding {detector}: manifest:{label}")
    return findings


def validate(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    errors: list[str] = []
    manifest = _load_json(root, MANIFEST_PATH, errors)
    if not isinstance(manifest, dict):
        manifest = {}

    if manifest.get("schema_version") != "kotodama.public-migration-batch.v1":
        errors.append("unexpected manifest schema_version")
    if manifest.get("batch_id") != "A022":
        errors.append("unexpected batch_id")
    if manifest.get("status") != "CANDIDATE_ONLY":
        errors.append("batch status must remain CANDIDATE_ONLY")
    if manifest.get("publication_state") != "NO_GO_UNPUBLISHED":
        errors.append("publication state must remain NO_GO_UNPUBLISHED")

    expected_source = {
        "fixed_commit": SOURCE_COMMIT,
        "expected_entries": 16,
        "git_history_imported": False,
        "source_bodies_copied_unchanged": False,
        "license_expression": "MIT",
        "license_blob_sha": SOURCE_LICENSE_BLOB,
        "package_metadata_blob_sha": SOURCE_PACKAGE_BLOB,
    }
    if manifest.get("source") != expected_source:
        errors.append("source fixed-point contract mismatch")

    if manifest.get("decision_contract") != {
        "PUBLIC_REAUTHOR": 6,
        "PRIVATE_RETAIN": 8,
        "SUPERSEDED": 2,
        "unique_reauthored_destinations": 4,
    }:
        errors.append("decision count contract mismatch")

    if manifest.get("component_license") != {
        "expression": "MIT",
        "notice": "Copyright (c) 2026 Kotodama Project",
        "license_file": "LICENSES/MIT.txt",
        "license_blob_sha": SOURCE_LICENSE_BLOB,
        "source_derived_scope": ["docs/architecture/**"],
        "license_and_provenance_gate": "BLOCKED_ISSUE_25",
        "apache_pr18_relicenses_component": False,
    }:
        errors.append("component MIT scope or provenance boundary mismatch")

    expected_gates = {
        "license_and_provenance": "BLOCKED_ISSUE_25",
        "applicable_source_history_secret_pii": "BLOCKED_MISSING_A022_PRIVATE_RECEIPT",
        "candidate_privacy_secret": "REQUIRED_EXACT_HEAD",
        "independent_review": "PENDING",
        "public_governance": "BLOCKED_PR_18_AND_ISSUE_19",
        "dependency_review": "BLOCKED_UNTIL_RETARGET_TO_MAIN",
    }
    if manifest.get("admission_gates") != expected_gates:
        errors.append("admission gates must remain fail closed")

    raw_entries = manifest.get("entries")
    if not isinstance(raw_entries, list) or any(
        not isinstance(entry, dict) for entry in raw_entries
    ):
        errors.append("manifest entries must be an object array")
        entries: list[dict[str, Any]] = []
    else:
        entries = raw_entries

    if len(entries) != 16:
        errors.append("manifest must contain exactly 16 source entries")
    source_paths = [entry.get("source_path") for entry in entries]
    if source_paths != sorted(source_paths):
        errors.append("source entries must be sorted by exact path")
    if len(source_paths) != len(set(source_paths)):
        errors.append("duplicate source paths")
    if _mapping_digest(entries) != SOURCE_MAPPING_DIGEST:
        errors.append("exact source path/blob/mode/decision mapping digest mismatch")
    if any(entry.get("source_mode") != "100644" for entry in entries):
        errors.append("every source mode must remain 100644")
    if any(
        not isinstance(entry.get("source_blob_sha"), str)
        or not re.fullmatch(r"[0-9a-f]{40}", entry["source_blob_sha"])
        for entry in entries
    ):
        errors.append("invalid source blob SHA")

    source_blob_shas = {entry.get("source_blob_sha") for entry in entries}
    decisions = Counter(entry.get("decision") for entry in entries)
    if decisions != Counter({"PUBLIC_REAUTHOR": 6, "PRIVATE_RETAIN": 8, "SUPERSEDED": 2}):
        errors.append("actual decision counts mismatch")

    reauthored = [entry for entry in entries if entry.get("decision") == "PUBLIC_REAUTHOR"]
    private = [entry for entry in entries if entry.get("decision") == "PRIVATE_RETAIN"]
    superseded = [entry for entry in entries if entry.get("decision") == "SUPERSEDED"]

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in reauthored:
        group = entry.get("consolidation_group")
        if group not in CONSOLIDATIONS:
            errors.append("unknown PUBLIC_REAUTHOR consolidation group")
            continue
        groups[group].append(entry)
        expected_destination, _ = CONSOLIDATIONS[group]
        if entry.get("destination_path") != expected_destination:
            errors.append(f"consolidation destination mismatch: {group}")
        if entry.get("destination_blob_sha") != DESTINATIONS[expected_destination]:
            errors.append(f"consolidation blob mismatch: {group}")
        if entry.get("body_exported") is not False:
            errors.append(f"source body export flag must be false: {group}")
        coverage = entry.get("semantic_coverage")
        if not isinstance(coverage, list) or not coverage or len(coverage) != len(set(coverage)):
            errors.append(f"invalid semantic coverage: {group}")

    if set(groups) != set(CONSOLIDATIONS):
        errors.append("consolidation group set mismatch")
    for group, (destination, expected_count) in CONSOLIDATIONS.items():
        group_entries = groups.get(group, [])
        if len(group_entries) != expected_count:
            errors.append(f"consolidation source count mismatch: {group}")
        coverage_sets = [set(entry.get("semantic_coverage", [])) for entry in group_entries]
        for index, left in enumerate(coverage_sets):
            for right in coverage_sets[index + 1 :]:
                if left & right:
                    errors.append(f"consolidated source coverage overlaps: {group}")
        if destination not in DESTINATIONS:
            errors.append(f"unrecognized consolidation destination: {group}")

    public_destinations = {entry.get("destination_path") for entry in reauthored}
    if public_destinations != set(DESTINATIONS):
        errors.append("PUBLIC_REAUTHOR destination set mismatch")

    for entry in private:
        if entry.get("destination_path") is not None or entry.get("destination_blob_sha") is not None:
            errors.append("PRIVATE_RETAIN entry has a public destination")
        if entry.get("consolidation_group") is not None:
            errors.append("PRIVATE_RETAIN entry has a consolidation group")
        if entry.get("body_exported") is not False:
            errors.append("PRIVATE_RETAIN body export flag must remain false")

    seen_superseded: set[str] = set()
    for entry in superseded:
        destination = entry.get("destination_path")
        if destination not in SUPERSEDED_REFS:
            errors.append("SUPERSEDED entry lacks an exact existing public destination")
            continue
        expected_blob, expected_ref = SUPERSEDED_REFS[destination]
        seen_superseded.add(destination)
        if entry.get("destination_blob_sha") != expected_blob:
            errors.append(f"SUPERSEDED blob mismatch: {destination}")
        if entry.get("superseded_ref") != expected_ref:
            errors.append(f"SUPERSEDED immutable ref mismatch: {destination}")
        if entry.get("body_exported") is not False:
            errors.append(f"SUPERSEDED body export flag must be false: {destination}")
    if seen_superseded != set(SUPERSEDED_REFS):
        errors.append("SUPERSEDED destination set mismatch")

    manifest_consolidations = manifest.get("consolidations")
    if not isinstance(manifest_consolidations, list):
        errors.append("consolidations must be an array")
    else:
        normalized = {
            item.get("group"): (
                item.get("destination_path"),
                item.get("destination_blob_sha"),
                item.get("source_count"),
                item.get("coverage_rule"),
            )
            for item in manifest_consolidations
            if isinstance(item, dict)
        }
        expected = {
            group: (destination, DESTINATIONS[destination], count, "DISTINCT_PER_SOURCE")
            for group, (destination, count) in CONSOLIDATIONS.items()
        }
        if normalized != expected or len(manifest_consolidations) != len(expected):
            errors.append("manifest consolidation contract mismatch")

    source_blob_reuse_paths: list[str] = []
    for relative in sorted(REQUIRED_PATHS):
        data = _read_bounded(root, relative, errors)
        if data is not None and git_blob_sha(data) in source_blob_shas:
            source_blob_reuse_paths.append(relative.as_posix())
            errors.append(
                f"source architecture blob copied unchanged: {relative.as_posix()}"
            )

    for path, expected_sha in DESTINATIONS.items():
        data = _read_bounded(root, Path(path), errors)
        if data is None:
            continue
        actual_sha = git_blob_sha(data)
        if actual_sha != expected_sha:
            errors.append(f"destination blob mismatch: {path}")
        try:
            text = data.decode("utf-8")
        except UnicodeError:
            errors.append(f"invalid UTF-8 architecture document: {path}")
            continue
        for phrase in ("NO_GO_UNPUBLISHED", "Source-derived architecture component: MIT"):
            if phrase not in text:
                errors.append(f"architecture boundary missing from {path}: {phrase}")
        errors.extend(_scan_text(Path(path), text))

    license_data = _read_bounded(root, LICENSE_PATH, errors)
    if license_data is not None and git_blob_sha(license_data) != SOURCE_LICENSE_BLOB:
        errors.append("MIT license bytes do not match pinned source license blob")

    # Exact private source paths are allowed once in the manifest allowlist only.
    private_source_paths = [entry.get("source_path") for entry in private]
    manifest_data = _read_bounded(root, MANIFEST_PATH, errors)
    non_manifest_paths = REQUIRED_PATHS - {MANIFEST_PATH}
    private_path_leaks = 0
    for source_path in private_source_paths:
        if not isinstance(source_path, str):
            continue
        if manifest_data is None or manifest_data.decode("utf-8", errors="replace").count(source_path) != 1:
            errors.append("private source path must appear exactly once in manifest")
        for relative in non_manifest_paths:
            data = _read_bounded(root, relative, errors)
            if data is not None and source_path.encode("utf-8") in data:
                private_path_leaks += 1
                errors.append(f"private source path leaked outside manifest: {relative.as_posix()}")

    errors.extend(_scan_manifest_strings(manifest))

    errors = sorted(set(errors))
    return {
        "schema_version": "kotodama.public-migration-validation.v1",
        "batch_id": "A022",
        "status": "PASS" if not errors else "FAIL",
        "changed": False,
        "source_fixed_commit": SOURCE_COMMIT,
        "source_entries": len(entries),
        "decisions": dict(sorted(decisions.items())),
        "unique_reauthored_destinations": len(public_destinations),
        "source_architecture_blob_reuse": len(source_blob_reuse_paths),
        "private_source_path_leakage": private_path_leaks,
        "candidate_scan_findings": sum(
            1 for error in errors if error.startswith("candidate scan finding ")
        ),
        "component_license": "MIT",
        "license_blob_sha": SOURCE_LICENSE_BLOB,
        "admission_status": "BLOCKED",
        "no_go_reasons": [
            "ISSUE_25_LICENSE_PROVENANCE",
            "MISSING_APPLICABLE_A022_PRIVATE_SOURCE_HISTORY_RECEIPT",
            "INDEPENDENT_REVIEW_PENDING",
            "PR18_AND_ISSUE19_GOVERNANCE_PENDING",
            "DEPENDENCY_REVIEW_AFTER_RETARGET_PENDING",
        ],
        "errors": errors,
    }


def main() -> int:
    result = validate()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
