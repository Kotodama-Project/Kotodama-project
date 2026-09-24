#!/usr/bin/env python3
"""Fail-closed validation for the public A017 hierarchy-template batch and its admission record."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path("migration/a017-hierarchy-templates.manifest.json")
LICENSE_PATH = Path("LICENSES/MIT.txt")
SOURCE_COMMIT = "2fc1bf60b0dc8721c96875788447e34adc4c7216"
SOURCE_LICENSE_BLOB = "8294a2a3706f3fd652b8c1bae22a1024ade9406c"
SOURCE_PACKAGE_BLOB = "39804f52b523024c8b62eae678f897166ae0a47a"
CONTEXT_SCHEMA_URI = (
    "https://github.com/Kotodama-Project/Kotodama-project/"
    "schemas/hierarchy-session-context.schema.json"
)
SCHEMA_BLOB_SHA = "d5dbb0586c700f29e7c0f5d7dafa501eea554809"
EXPECTED_ROLLBACK = {
    "strategy": "REMOVE_EXACT_CANDIDATE_COMMIT_BEFORE_MERGE",
    "verification": "RESTORE_PR18_BASE_TREE_AND_RERUN_VALIDATION",
    "source_retention": "PRIVATE_SOURCE_FIXED_POINT_UNCHANGED",
}

EXPECTED_ENTRIES = {
    "forest/_templates/INDEX_TEMPLATE.md": (
        "1aecf8880cbda4453d003bff45e386474680be74",
        "RE_AUTHORED",
        "templates/hierarchy/index.md",
        "59d6ad3e0e23f678c2274a31989e38cf358926ed",
    ),
    "forest/_templates/layers/L3_project_template.md": (
        "4d56c1702657e1c5fb352efbf7021ea233980f41",
        "RE_AUTHORED",
        "templates/hierarchy/project.md",
        "55e9def37558da2c1ebe558372c932ffab0f693e",
    ),
    "forest/_templates/layers/L4_phase_template.md": (
        "14d352bc870e4663dbb1111c42d1885ba8901ddf",
        "RE_AUTHORED",
        "templates/hierarchy/phase.md",
        "41ad19ea040d7e7aa19cf94bf7cc53ecd98e9770",
    ),
    "forest/_templates/layers/L5_requirement_template.md": (
        "4ef237072365495538028e832f75c2d6fd53163d",
        "RE_AUTHORED",
        "templates/hierarchy/requirement.md",
        "f49b9f4008eb7cc9dd69825bc5387866e8c7ca16",
    ),
    "forest/_templates/layers/L6_plan_template.md": (
        "d5b35bd67dc59fab509c64aff1ee97956f060d92",
        "RE_AUTHORED",
        "templates/hierarchy/plan.md",
        "80d3a3945e223f3f28bbcda0ce8f92eb0d54151a",
    ),
    "forest/_templates/layers/L7_task_template.md": (
        "57bab30bcd42bf3cc3eab517d6028ba9b45a7e86",
        "RE_AUTHORED",
        "templates/hierarchy/task.md",
        "6667a1db455ebd0eee3d8cf75bfa6a97dae6e4ce",
    ),
    "forest/_templates/project/README.md": (
        "c2d5cd8036cc4f75d4c53ce3a37a05645ceec11e",
        "RE_AUTHORED",
        "templates/hierarchy/README.md",
        "a9200399ff18544ae391728c01989d481a76dbd2",
    ),
    "forest/_templates/session/CONTEXT.json": (
        "74963410019e8dd3ace9c38e5464fff72770e710",
        "RE_AUTHORED",
        "templates/hierarchy/session-context.json",
        "8dcf7d13e90ca918403071bf72defcccd8d55523",
    ),
    "forest/_templates/session/REQUIREMENT.md": (
        "e1b975d7e6b450d9cbed93438a89ecd276e5d898",
        "SUPERSEDED",
        "templates/hierarchy/requirement.md",
        "f49b9f4008eb7cc9dd69825bc5387866e8c7ca16",
    ),
    "forest/_templates/session/TASK.md": (
        "07872b0190fdf6df6eea6455b02c1d4aff659569",
        "RE_AUTHORED",
        "templates/hierarchy/task.md",
        "6667a1db455ebd0eee3d8cf75bfa6a97dae6e4ce",
    ),
}

TEMPLATE_SPECS = {
    "templates/hierarchy/index.md": (
        "hierarchy_index",
        {"template_kind", "status", "owner_role", "updated_at"},
        {"## Purpose", "## Canonical entries", "## Change boundary", "## Validation and rollback", "## Projection rule"},
    ),
    "templates/hierarchy/project.md": (
        "project",
        {"template_kind", "id", "slug", "status", "owner_role", "created_at", "updated_at"},
        {"## Outcome", "## Boundary", "## Acceptance criteria", "## Phases", "## Dependencies and risks", "## Evidence and rollback"},
    ),
    "templates/hierarchy/phase.md": (
        "phase",
        {"template_kind", "id", "parent_ref", "status", "owner_role", "created_at", "updated_at"},
        {"## Outcome", "## Entry criteria", "## Exit criteria", "## Boundary", "## Requirements and deliverables", "## Evidence and rollback"},
    ),
    "templates/hierarchy/requirement.md": (
        "requirement",
        {"template_kind", "id", "parent_ref", "requirement_type", "priority", "status", "owner_role", "effort", "blocking", "created_at", "updated_at"},
        {"## Need", "## Background", "## Boundary", "## Acceptance criteria", "## Dependencies", "## Verification and evidence", "## History and rollback"},
    ),
    "templates/hierarchy/plan.md": (
        "plan",
        {"template_kind", "id", "parent_ref", "status", "owner_role", "created_at", "updated_at"},
        {"## Outcome", "## Preconditions", "## Ordered steps", "## Dependencies", "## Completion criteria", "## Stop conditions and rollback"},
    ),
    "templates/hierarchy/task.md": (
        "task",
        {"template_kind", "id", "parent_ref", "session_ref", "intent_ref", "status", "owner_role", "created_at", "updated_at"},
        {"## Outcome", "## Authorized scope", "## Acceptance criteria", "## Context references", "## Evidence and validation", "## Work log", "## Stop conditions and rollback", "## Handoff"},
    ),
}

CONTEXT_PATH = Path("templates/hierarchy/session-context.json")
SCHEMA_PATH = Path("schemas/hierarchy-session-context.schema.json")
README_PATH = Path("templates/hierarchy/README.md")
CATALOG_PATH = Path("templates/README.md")
GUIDE_PATH = Path("docs/TEMPLATE-GUIDE.md")
PROVENANCE_PATH = Path("migration/a017-hierarchy-templates.provenance.json")
RIGHTSHOLDER_RECORD = "https://github.com/Kotodama-Project/Kotodama-project/issues/25"
# Admission evidence (Issue #25, 2026-09-24): the owner recorded the
# rightsholder decision, a private source-history scan produced a receipt whose
# digest is in the provenance file, and an independent review is recorded last.
RECORDED_GATES = {
    "license_and_provenance": "RECORDED_ISSUE_25_OWNER_DECISION",
    "source_history_secret_pii": "PASSED_PRIVATE_RECEIPT",
    "candidate_privacy_secret": "REQUIRED_EXACT_HEAD",
}
REVIEW_STATES = {"PENDING", "PASSED_INDEPENDENT_REVIEW"}
PRIVATE_RESULTS = {"PASS", "PASS_AFTER_TRIAGE"}
REQUIRED_PATHS = {
    MANIFEST_PATH,
    PROVENANCE_PATH,
    LICENSE_PATH,
    README_PATH,
    CATALOG_PATH,
    GUIDE_PATH,
    CONTEXT_PATH,
    SCHEMA_PATH,
    *(Path(path) for path in TEMPLATE_SPECS),
}

SECRET_PATTERNS = {
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "scm_access_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "assigned_secret": re.compile(
        r"(?i)\b(?:api[_-]?key|token|password|secret)\b\s*[:=]\s*[\"']?[A-Za-z0-9/+_.-]{12,}"
    ),
}
PII_PATTERNS = {
    "email": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    "ipv4": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "long_numeric_identifier": re.compile(r"\b\d{15,20}\b"),
}
PRIVATE_REFERENCE_PATTERNS = {
    "absolute_user_path": re.compile(r"(?:/(?:home|Users|root)/|[A-Za-z]:\\Users\\)"),
    "private_runtime_path": re.compile(r"\b(?:runtime\.app|knowledge/|forest/(?!_templates/))", re.I),
    "tool_private_state": re.compile(r"(?:\.claude/|\.cursor/|\.kotodama/)", re.I),
    "provider_or_host_coupling": re.compile(r"\b(?:Proxmox|Discord|OpenClaw|n8n)\b", re.I),
}


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()  # noqa: S324 - Git object identity


def _read_bounded(root: Path, relative: Path, errors: list[str]) -> bytes | None:
    path = root / relative
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        errors.append(f"missing or escaping path: {relative.as_posix()}")
        return None
    if not resolved.is_file():
        errors.append(f"not a regular file: {relative.as_posix()}")
        return None
    data = resolved.read_bytes()
    if len(data) > 128 * 1024:
        errors.append(f"file exceeds 131072 bytes: {relative.as_posix()}")
        return None
    return data


def _json(root: Path, relative: Path, errors: list[str]) -> Any:
    data = _read_bounded(root, relative, errors)
    if data is None:
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        errors.append(f"invalid UTF-8 JSON: {relative.as_posix()}")
        return None


def _frontmatter(text: str) -> dict[str, str] | None:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return None
    try:
        end = lines.index("---", 1)
    except ValueError:
        return None
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        if not line or ":" not in line:
            return None
        key, value = line.split(":", 1)
        key = key.strip()
        if not re.fullmatch(r"[a-z_]+", key) or key in fields:
            return None
        fields[key] = value.strip().strip('"')
    return fields


def _scan_text(relative: Path, text: str, include_private_refs: bool) -> list[str]:
    findings: list[str] = []
    patterns = {**SECRET_PATTERNS, **PII_PATTERNS}
    if include_private_refs:
        patterns.update(PRIVATE_REFERENCE_PATTERNS)
    for line_number, line in enumerate(text.splitlines(), start=1):
        for name, pattern in patterns.items():
            if pattern.search(line):
                findings.append(f"scan finding {name}: {relative.as_posix()}:{line_number}")
    return findings


def validate(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    errors: list[str] = []
    manifest = _json(root, MANIFEST_PATH, errors)
    source_template_blobs = {item[0] for item in EXPECTED_ENTRIES.values()}
    destination_paths: set[str] = set()

    if not isinstance(manifest, dict):
        manifest = {}
    if manifest.get("schema_version") != "kotodama.public-migration-batch.v1":
        errors.append("unexpected manifest schema_version")
    if manifest.get("batch_id") != "A017":
        errors.append("unexpected batch_id")
    if manifest.get("status") != "CANDIDATE_ONLY":
        errors.append("batch status must be CANDIDATE_ONLY")
    if manifest.get("publication_state") != "NO_GO_UNPUBLISHED":
        errors.append("publication state must be NO_GO_UNPUBLISHED")

    source = manifest.get("source", {})
    expected_source = {
        "fixed_commit": SOURCE_COMMIT,
        "allowlisted_prefix": "forest/_templates/",
        "expected_entries": 10,
        "git_history_imported": False,
        "license_expression": "MIT",
        "license_blob_sha": SOURCE_LICENSE_BLOB,
        "package_metadata_blob_sha": SOURCE_PACKAGE_BLOB,
    }
    if source != expected_source:
        errors.append("source fixed-point contract mismatch")

    license_contract = manifest.get("component_license", {})
    if license_contract != {
        "expression": "MIT",
        "notice": "Copyright (c) 2026 Kotodama Project",
        "license_file": "LICENSES/MIT.txt",
        "source_derived_scope": [
            "templates/hierarchy/**",
            "schemas/hierarchy-session-context.schema.json",
        ],
    }:
        errors.append("component MIT scope or notice mismatch")

    gates = manifest.get("admission_gates")
    if not isinstance(gates, dict):
        gates = {}
    review_state = gates.get("independent_review")
    if {key: value for key, value in gates.items() if key != "independent_review"} != RECORDED_GATES:
        errors.append("admission gates must match the recorded admission evidence")
    if review_state not in REVIEW_STATES:
        errors.append("independent review gate must be PENDING or PASSED_INDEPENDENT_REVIEW")
    if manifest.get("rollback") != EXPECTED_ROLLBACK:
        errors.append("manifest rollback contract mismatch")

    entries = manifest.get("entries")
    if not isinstance(entries, list):
        entries = []
        errors.append("manifest entries must be an array")
    paths: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        source_path = entry.get("source_path")
        if not isinstance(source_path, str):
            errors.append("manifest source_path must be a string")
            continue
        paths.append(source_path)
    if paths != sorted(EXPECTED_ENTRIES):
        errors.append("source entries must be the exact sorted ten-path allowlist")
    if len(paths) != len(set(paths)):
        errors.append("duplicate source paths")

    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("manifest entry is not an object")
            continue
        source_path = entry.get("source_path")
        if not isinstance(source_path, str):
            continue
        if source_path not in EXPECTED_ENTRIES:
            errors.append(f"unexpected source path: {source_path}")
            continue
        expected_sha, expected_decision, expected_destination, expected_destination_sha = EXPECTED_ENTRIES[source_path]
        actual = (
            entry.get("source_blob_sha"),
            entry.get("decision"),
            entry.get("destination_path"),
            entry.get("destination_blob_sha"),
        )
        if actual != (expected_sha, expected_decision, expected_destination, expected_destination_sha):
            errors.append(f"source decision mismatch: {source_path}")
        if entry.get("source_mode") != "100644":
            errors.append(f"source mode mismatch: {source_path}")
        coverage = entry.get("semantic_coverage")
        if not isinstance(coverage, list) or not coverage or len(coverage) != len(set(coverage)):
            errors.append(f"invalid semantic coverage: {source_path}")
        if not isinstance(entry.get("rationale"), str) or not entry["rationale"].strip():
            errors.append(f"missing rationale: {source_path}")
        destination_paths.add(expected_destination)
        data = _read_bounded(root, Path(expected_destination), errors)
        if data is not None:
            actual_sha = git_blob_sha(data)
            if actual_sha != expected_destination_sha:
                errors.append(f"destination blob mismatch: {expected_destination}")
            if actual_sha in source_template_blobs:
                errors.append(f"source template blob copied unchanged: {expected_destination}")

    decisions = Counter(entry.get("decision") for entry in entries if isinstance(entry, dict))
    if decisions != Counter({"RE_AUTHORED": 9, "SUPERSEDED": 1}):
        errors.append("decision counts must be RE_AUTHORED=9 and SUPERSEDED=1")
    if len(destination_paths) != 8:
        errors.append("expected exactly eight unique public destinations")

    by_source = {
        entry.get("source_path"): entry
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("source_path"), str)
    }
    old_requirement = by_source.get("forest/_templates/session/REQUIREMENT.md", {})
    layer_requirement = by_source.get("forest/_templates/layers/L5_requirement_template.md", {})
    required_requirement_coverage = {
        "id", "kind", "type", "priority", "status", "parent_ref", "dependencies",
        "acceptance_criteria", "owner_role", "effort", "blocking", "created_at",
        "updated_at", "background", "scope", "verification", "history", "rollback",
    }
    if old_requirement.get("decision") != "SUPERSEDED":
        errors.append("malformed session requirement must remain SUPERSEDED")
    if set(old_requirement.get("semantic_coverage", [])) != required_requirement_coverage:
        errors.append("superseded requirement semantic coverage is incomplete")
    if set(layer_requirement.get("semantic_coverage", [])) != required_requirement_coverage:
        errors.append("canonical requirement semantic coverage is incomplete")

    task_sources = {
        "forest/_templates/layers/L7_task_template.md",
        "forest/_templates/session/TASK.md",
    }
    task_entries = [by_source.get(path, {}) for path in task_sources]
    if any(entry.get("destination_path") != "templates/hierarchy/task.md" for entry in task_entries):
        errors.append("both task sources must map explicitly to task.md")
    task_coverage = set().union(*(set(entry.get("semantic_coverage", [])) for entry in task_entries))
    if not {
        "id", "kind", "status", "parent_ref", "session_ref", "intent_ref", "outcome",
        "acceptance_criteria", "context_refs", "evidence_refs", "work_log",
        "stop_conditions", "rollback", "handoff",
    } <= task_coverage:
        errors.append("two-source task semantic coverage is incomplete")

    for path, (kind, required_fields, required_headings) in TEMPLATE_SPECS.items():
        relative = Path(path)
        data = _read_bounded(root, relative, errors)
        if data is None:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeError:
            errors.append(f"invalid UTF-8 Markdown: {path}")
            continue
        fields = _frontmatter(text)
        if fields is None:
            errors.append(f"invalid frontmatter: {path}")
        else:
            if set(fields) != required_fields:
                errors.append(f"frontmatter fields mismatch: {path}")
            if fields.get("template_kind") != kind or fields.get("status") != "draft":
                errors.append(f"template kind/status mismatch: {path}")
        missing_headings = sorted(heading for heading in required_headings if heading not in text)
        if missing_headings:
            errors.append(f"missing headings in {path}: {missing_headings}")
        if "{{" not in text or "}}" not in text:
            errors.append(f"template has no explicit placeholders: {path}")
        if re.search(r"(?i)- \[x\]", text):
            errors.append(f"template contains pre-completed acceptance item: {path}")
        if "Component license: MIT; see `../../LICENSES/MIT.txt`." not in text:
            errors.append(f"component license footer missing: {path}")
        errors.extend(_scan_text(relative, text, include_private_refs=True))

    context = _json(root, CONTEXT_PATH, errors)
    schema = _json(root, SCHEMA_PATH, errors)
    expected_context_keys = {
        "$schema", "schema_version", "kind", "session_id", "intent_ref", "owner_role",
        "created_at", "status", "worktree_enabled", "parent_refs", "evidence_refs",
    }
    if not isinstance(context, dict) or set(context) != expected_context_keys:
        errors.append("session context keys mismatch")
    else:
        expected_context_values = {
            "$schema": CONTEXT_SCHEMA_URI,
            "schema_version": "1.0",
            "kind": "session_context",
            "status": "draft",
            "worktree_enabled": False,
            "parent_refs": [],
            "evidence_refs": [],
        }
        for key, value in expected_context_values.items():
            if context.get(key) != value:
                errors.append(f"session context value mismatch: {key}")
        for key in ("session_id", "intent_ref", "owner_role", "created_at"):
            value = context.get(key)
            if not isinstance(value, str) or not re.fullmatch(r"\{\{[A-Z0-9_]+\}\}", value):
                errors.append(f"session context placeholder mismatch: {key}")
    if not isinstance(schema, dict):
        errors.append("session context schema missing")
    else:
        schema_data = _read_bounded(root, SCHEMA_PATH, errors)
        if schema_data is not None and git_blob_sha(schema_data) != SCHEMA_BLOB_SHA:
            errors.append("session context schema blob mismatch")
        if set(schema.get("required", [])) != expected_context_keys:
            errors.append("session context schema required keys mismatch")
        if set(schema.get("properties", {})) != expected_context_keys:
            errors.append("session context schema properties mismatch")
        if schema.get("additionalProperties") is not False:
            errors.append("session context schema must reject additional properties")

    provenance_data = _read_bounded(root, PROVENANCE_PATH, errors)
    if provenance_data is not None:
        try:
            provenance = json.loads(provenance_data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            provenance = {}
            errors.append("provenance file is not valid UTF-8 JSON")
        if not isinstance(provenance, dict):
            provenance = {}
        if provenance.get("schema_version") != "kotodama.public-migration-provenance.v1":
            errors.append("unexpected provenance schema_version")
        if provenance.get("batch_id") != "A017" or provenance.get("source_fixed_commit") != SOURCE_COMMIT:
            errors.append("provenance is not bound to the A017 fixed source commit")
        if provenance.get("license_expression") != "MIT":
            errors.append("provenance license expression must be MIT")
        if provenance.get("rightsholder_record") != RIGHTSHOLDER_RECORD:
            errors.append("provenance must cite the Issue #25 rightsholder record")
        digest = provenance.get("private_source_history_receipt_sha256")
        if not (isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)):
            errors.append("provenance must bind the private source-history receipt digest")
        if provenance.get("private_source_history_result") not in PRIVATE_RESULTS:
            errors.append("private source-history receipt did not pass")
        rows = provenance.get("entries")
        if not isinstance(rows, list):
            rows = []
        if sorted(row.get("source_path") for row in rows if isinstance(row, dict)) != sorted(EXPECTED_ENTRIES):
            errors.append("provenance must cover exactly the ten allowlisted sources")
        for row in rows:
            if not isinstance(row, dict):
                errors.append("provenance entries must be objects")
                continue
            handles = row.get("author_github_handles")
            if not (isinstance(row.get("commits_touching_source"), int) and row["commits_touching_source"] >= 1):
                errors.append("provenance entry must count at least one source commit")
            if not (isinstance(handles, list) and all(isinstance(h, str) and re.fullmatch(r"[A-Za-z0-9-]{1,39}", h) for h in handles)):
                errors.append("provenance authors must be GitHub handles")
            if not (isinstance(row.get("withheld_author_identities"), int) and row["withheld_author_identities"] >= 0):
                errors.append("provenance must count withheld author identities")
            if isinstance(row.get("source_path"), str) and row.get("source_blob_sha") != EXPECTED_ENTRIES.get(row["source_path"], ("",))[0]:
                errors.append("provenance source blob does not match the manifest")
        errors.extend(_scan_text(PROVENANCE_PATH, provenance_data.decode("utf-8", errors="replace"), include_private_refs=True))

    readme_data = _read_bounded(root, README_PATH, errors)
    if readme_data is not None:
        readme = readme_data.decode("utf-8", errors="replace")
        for phrase in (
            "candidate_only", "NO_GO_UNPUBLISHED", "SUPERSEDED",
            "two task sources", "Issue #25", "MIT License",
        ):
            if phrase not in readme:
                errors.append(f"hierarchy README missing boundary: {phrase}")
        errors.extend(_scan_text(README_PATH, readme, include_private_refs=True))

    catalog_data = _read_bounded(root, CATALOG_PATH, errors)
    if catalog_data is not None:
        catalog = catalog_data.decode("utf-8", errors="replace")
        if "[Hierarchy](hierarchy/README.md)" not in catalog:
            errors.append("template catalog does not link hierarchy candidate")
        if "admissionはIssue #25のowner判断と出典表で記録" not in catalog:
            errors.append("template catalog omits the hierarchy admission record")
        errors.extend(_scan_text(CATALOG_PATH, catalog, include_private_refs=False))

    guide_data = _read_bounded(root, GUIDE_PATH, errors)
    if guide_data is not None:
        guide = guide_data.decode("utf-8", errors="replace")
        if "[A017階層テンプレート候補](../templates/hierarchy/README.md)" not in guide:
            errors.append("template guide does not link the A017 hierarchy candidate")
        if "admissionはIssue #25のowner判断（2026-09-24）、出典表、private source-history receipt、独立reviewの記録で判定" not in guide:
            errors.append("template guide omits the A017 admission record")
        if "session、requirement、plan、taskといった階層テンプレート" in guide:
            errors.append("template guide still classifies the hierarchy as local-only")
        errors.extend(_scan_text(GUIDE_PATH, guide, include_private_refs=False))

    license_data = _read_bounded(root, LICENSE_PATH, errors)
    if license_data is not None and git_blob_sha(license_data) != SOURCE_LICENSE_BLOB:
        errors.append("MIT license bytes do not match pinned source license blob")

    for relative in (CONTEXT_PATH, SCHEMA_PATH, MANIFEST_PATH, LICENSE_PATH):
        data = _read_bounded(root, relative, errors)
        if data is not None:
            text = data.decode("utf-8", errors="replace")
            errors.extend(_scan_text(relative, text, include_private_refs=False))

    errors = sorted(set(errors))
    return {
        "schema_version": "kotodama.public-migration-validation.v1",
        "batch_id": "A017",
        "status": "PASS" if not errors else "FAIL",
        "changed": False,
        "source_fixed_commit": SOURCE_COMMIT,
        "source_entries": len(entries),
        "decisions": dict(sorted(decisions.items())),
        "unique_destinations": len(destination_paths),
        "source_template_blob_reuse": sum(
            1
            for path in destination_paths
            if (root / path).is_file() and git_blob_sha((root / path).read_bytes()) in source_template_blobs
        ),
        "component_license": "MIT",
        "license_blob_sha": SOURCE_LICENSE_BLOB,
        "candidate_scan_findings": sum(1 for error in errors if error.startswith("scan finding ")),
        "admission_status": "ADMITTED" if not errors and review_state == "PASSED_INDEPENDENT_REVIEW" else "BLOCKED",
        "no_go_reasons": [] if review_state == "PASSED_INDEPENDENT_REVIEW" else ["INDEPENDENT_REVIEW_PENDING"],
        "errors": errors,
    }


def main() -> int:
    result = validate()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
