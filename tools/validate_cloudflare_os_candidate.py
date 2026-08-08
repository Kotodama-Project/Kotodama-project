#!/usr/bin/env python3
"""Validate the source-only official Cloudflare OS candidate."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import re
import sys
from typing import Any
from urllib.parse import urlparse

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # pragma: no cover - explicit environment error
    Draft202012Validator = None
    FormatChecker = None


ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "runtime" / "cloudflare-os" / "upstream-pin.json"
SCHEMA = ROOT / "schemas" / "cloudflare-os-upstream-pin.schema.json"
ADAPTER = ROOT / "tools" / "cloudflare_os_gatekeeper_adapter.py"
DOC = ROOT / "docs" / "CLOUDFLARE-OS-ADOPTION.md"
RUNTIME_README = ROOT / "runtime" / "cloudflare-os" / "README.md"

CORE_COMMIT = "1cb5e3d9096589e38f3fcfaf3f2191aa95a4c592"
CORE_TREE = "2f1eb7b69cf6cbc0e0da159bf2cd09ef9a2ce7e7"
STARTER_COMMIT = "9c18a2e8b0c3741e5f4813546bbf24be5bbb98ee"
STARTER_TREE = "9d34f65f4f34b98febc57f8da86cfc045da0736e"
PINNED_CORE_COMMIT = "bf7f762d7fa73553284d731ab6a978d3ea17be24"
PINNED_CORE_TREE = "023da57719fa9744a4ca909f9c3863c93cb614fa"
REQUIRED_PRODUCTS = {
    "Workers",
    "KV",
    "R2",
    "Browser Rendering",
    "Dynamic Worker Loaders",
}
SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:sk|rk|pk)-[a-z0-9_-]{12,}\b"),
    re.compile(r"(?i)\bbearer\s+[a-z0-9_./+=-]{12,}\b"),
    re.compile(
        r"(?i)\b(?:api[_-]?token|access[_-]?token|client[_-]?secret)"
        r"\s*[:=]\s*['\"]?[a-z0-9_./+=-]{8,}"
    ),
)


class CandidateViolation(ValueError):
    """The public candidate failed closed."""


def load_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateViolation(f"cannot load JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CandidateViolation(f"JSON root must be an object: {path}")
    return value


def load_adapter(path: pathlib.Path = ADAPTER) -> Any:
    spec = importlib.util.spec_from_file_location("cloudflare_os_gatekeeper_adapter", path)
    if spec is None or spec.loader is None:
        raise CandidateViolation("cannot load adapter")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_schema(data: dict[str, Any], schema: dict[str, Any]) -> None:
    if Draft202012Validator is None or FormatChecker is None:
        raise CandidateViolation("jsonschema[format-nongpl] is required")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(data), key=lambda error: list(error.absolute_path))
    if errors:
        rendered = "; ".join(error.message for error in errors[:20])
        raise CandidateViolation(f"schema validation failed: {rendered}")


def scan_public_text(text: str, label: str) -> None:
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            raise CandidateViolation(f"secret-shaped value in {label}")
    lowered = text.lower().replace("/", "\\")
    for marker in ("source_thread_id", "<private-source-body>", ".codex\\attachments"):
        if marker in lowered:
            raise CandidateViolation(f"private source marker in {label}")


def validate_source_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
        raise CandidateViolation(f"unsafe source URL: {value}")
    host = parsed.hostname or ""
    if host == "os.cloudflare.app" and parsed.path in {"", "/"}:
        return
    if host == "github.com" and parsed.path.rstrip("/") in {
        "/cloudflare/cloudflare-os",
        "/cloudflare/cloudflare-os-starter",
    }:
        return
    if host == "developers.cloudflare.com" and parsed.path.rstrip("/") == "/dynamic-workers/pricing":
        return
    if host == "raw.githubusercontent.com" and parsed.path.startswith(
        (
            f"/cloudflare/cloudflare-os/{PINNED_CORE_COMMIT}/",
            f"/cloudflare/cloudflare-os-starter/{STARTER_COMMIT}/",
        )
    ):
        return
    raise CandidateViolation(f"source URL is not official and revision-bound: {value}")


def validate_manifest(data: dict[str, Any]) -> None:
    expected = {
        ("starter", "commit"): STARTER_COMMIT,
        ("starter", "tree"): STARTER_TREE,
        ("starter_core_gitlink", "commit"): PINNED_CORE_COMMIT,
        ("starter_core_gitlink", "tree"): PINNED_CORE_TREE,
        ("current_core_observation", "commit"): CORE_COMMIT,
        ("current_core_observation", "tree"): CORE_TREE,
    }
    for (section, field), value in expected.items():
        if data[section][field] != value:
            raise CandidateViolation(f"snapshot drift: {section}.{field}")
    if data["starter_core_gitlink"]["commit"] == data["current_core_observation"]["commit"]:
        raise CandidateViolation("starter gitlink and current core were conflated")
    if data["selected_baseline"]["drift_review_required"] is not True:
        raise CandidateViolation("upstream drift review must remain required")
    if data["selected_baseline"]["exact_install_integrity_proven"] is not False:
        raise CandidateViolation("source pin cannot prove installed integrity")
    if set(data["runtime_observations"]["required_products"]) != REQUIRED_PRODUCTS:
        raise CandidateViolation("required Cloudflare product set drifted")
    if data["public_beta"] != "NO_GO_UNPUBLISHED":
        raise CandidateViolation("Public Beta must remain NO_GO_UNPUBLISHED")
    if any(value != 0 for value in data["effects"].values()):
        raise CandidateViolation("source-only effects must all remain zero")
    if any(data["authority_boundary"][field] is not False for field in (
        "provider_deploy_authorized",
        "promotion_authorized",
        "current_truth_change_authorized",
    )):
        raise CandidateViolation("source pin cannot authorize provider or promotion effects")
    for source in data["official_sources"]:
        validate_source_url(source)
    joined_sources = "\n".join(data["official_sources"])
    for revision in (STARTER_COMMIT, PINNED_CORE_COMMIT):
        if revision not in joined_sources:
            raise CandidateViolation(f"missing revision-bound official source: {revision}")
    scan_public_text(json.dumps(data, ensure_ascii=False, sort_keys=True), "source pin")


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def make_event(kind: str, *, protected: bool = False) -> dict[str, Any]:
    action = kind != "observation"
    decision = kind in {"action_rejected", "action_applied"}
    states = {
        "observation": ("not_required", "none", 0),
        "action_submitted": ("pending", "none", 0),
        "action_simulated": ("pending", "simulated", 0),
        "action_rejected": ("rejected", "none", 0),
        "action_applied": ("approved", "applied", 1),
    }
    approval, effect, count = states[kind]
    return {
        "schema": "kotodama/cloudflare-os-gatekeeper-event/v1",
        "event_kind": kind,
        "data_class": "protected_context_metadata" if protected else "public_metadata",
        "actor_binding_sha256": digest("actor"),
        "resource_scope_sha256": digest("resource"),
        "request_binding_sha256": digest(f"request:{kind}:{protected}"),
        "candidate_sha256": digest(f"candidate:{kind}") if action else None,
        "gatekeeper_revision": PINNED_CORE_COMMIT,
        "observed_at": "2026-08-09T07:00:00Z",
        "approval_state": approval,
        "effect_state": effect,
        "effect_count": count,
        "work_order_sha256": digest(f"work-order:{kind}") if action else None,
        "capability_grant_sha256": digest(f"grant:{kind}") if action else None,
        "human_decision_sha256": digest(f"decision:{kind}") if decision else None,
        "external_action_receipt_sha256": digest("receipt") if kind == "action_applied" else None,
        "context_admission_sha256": digest("context-admission") if protected else None,
        "corpus_scope_sha256": digest("corpus-scope") if protected else None,
        "redaction_profile": "metadata-only-v1",
        "edge_retention": "none",
        "private_body_included": False,
    }


def validate_adapter(module: Any) -> dict[str, Any]:
    cases = [
        ("observation", False),
        ("observation", True),
        ("action_submitted", False),
        ("action_simulated", False),
        ("action_rejected", False),
        ("action_applied", False),
    ]
    projections: dict[str, dict[str, Any]] = {}
    for kind, protected in cases:
        label = f"{kind}:{protected}"
        event = make_event(kind, protected=protected)
        projection = module.project_event(event, expected_gatekeeper_revision=PINNED_CORE_COMMIT)
        repeated = module.project_event(event, expected_gatekeeper_revision=PINNED_CORE_COMMIT)
        if projection != repeated:
            raise CandidateViolation(f"non-deterministic projection: {label}")
        if projection["execution_authorized"] or projection["promotion_authorized"]:
            raise CandidateViolation(f"projection self-authorized: {label}")
        projections[label] = projection
    canonical = json.dumps(projections, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return {
        "cases": len(cases),
        "projection_set_sha256": hashlib.sha256(canonical.encode("ascii")).hexdigest(),
    }


def validate(root: pathlib.Path = ROOT) -> tuple[list[str], dict[str, Any]]:
    root = root.resolve()
    paths = {
        "manifest": root / "runtime" / "cloudflare-os" / "upstream-pin.json",
        "schema": root / "schemas" / "cloudflare-os-upstream-pin.schema.json",
        "adapter": root / "tools" / "cloudflare_os_gatekeeper_adapter.py",
        "doc": root / "docs" / "CLOUDFLARE-OS-ADOPTION.md",
        "readme": root / "runtime" / "cloudflare-os" / "README.md",
    }
    errors: list[str] = []
    adapter_result: dict[str, Any] = {"cases": 0, "projection_set_sha256": None}
    for label, path in paths.items():
        if not path.is_file():
            errors.append(f"missing {label}: {path.relative_to(root)}")
    if errors:
        return errors, adapter_result
    try:
        data = load_json(paths["manifest"])
        validate_schema(data, load_json(paths["schema"]))
        validate_manifest(data)
        module = load_adapter(paths["adapter"])
        adapter_result = validate_adapter(module)
        for label in ("doc", "readme", "adapter", "schema"):
            text = paths[label].read_text(encoding="utf-8")
            scan_public_text(text, label)
        for label in ("doc", "readme"):
            text = paths[label].read_text(encoding="utf-8")
            for marker in ("NO_GO_UNPUBLISHED", "Context Gateway", "Proxmox", "Human Intent"):
                if marker not in text:
                    raise CandidateViolation(f"{label} missing boundary marker: {marker}")
    except (CandidateViolation, ValueError) as exc:
        errors.append(str(exc))
    return errors, adapter_result


def main() -> int:
    errors, adapter_result = validate()
    report = {
        "kind": "cloudflare_os_source_candidate_validation",
        "status": "PASS_LOCAL_SOURCE_AND_SYNTHETIC_ONLY" if not errors else "REFUSED",
        "errors": errors,
        "source_repositories": 2,
        "adapter_cases": adapter_result["cases"],
        "projection_set_sha256": adapter_result["projection_set_sha256"],
        "effects": {
            "upstream_executed": False,
            "provider_authenticated": False,
            "provider_mutated": False,
            "deployed": False,
            "promoted": False,
        },
        "public_beta": "NO_GO_UNPUBLISHED",
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
