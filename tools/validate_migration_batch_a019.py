#!/usr/bin/env python3
"""Read-only, fail-closed validator for the A019 public schema candidate."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

try:
    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry, Resource
except ImportError:  # pragma: no cover - exercised by the fail-closed CLI path
    Draft202012Validator = None  # type: ignore[assignment]
    FormatChecker = None  # type: ignore[assignment]
    Registry = None  # type: ignore[assignment]
    Resource = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path("migration/a019-registry-contracts.manifest.json")
LICENSE_PATH = Path("LICENSES/MIT.txt")
SOURCE_COMMIT = "2fc1bf60b0dc8721c96875788447e34adc4c7216"
SOURCE_LICENSE_BLOB = "8294a2a3706f3fd652b8c1bae22a1024ade9406c"
SOURCE_PACKAGE_BLOB = "39804f52b523024c8b62eae678f897166ae0a47a"
SOURCE_MAPPING_DIGEST = "6dcc74faa7736f38db8d8759214a579a2fee4e206d86832d0eade465af67aeeb"
SOURCE_BLOBS = {
    "d96bc760b22eaa06a0729b6a1e1cd915b160dbf3",
    "f682d97d07ea6d3cf87d776d226e32921fdb2306",
    "3529f688fb222135a5c352d73b5c5117e4a7ef87",
    "2ae3797052c82cbf67d5c720603476557dee4ff9",
    "5275c648c1a87dc8b1b5e0bac5216003c38f4ff7",
    "f38733322c79be02f5a75a7709fa932eaa9a4afa",
}

DESTINATIONS = {
    "schemas/task-contract.schema.json": "efbf457f8d71581525250f0a187bfb102e059342",
    "schemas/task-decomposition.schema.json": "24da61da50dda406bdba3da6c20f669a313077a4",
    "schemas/worker-capability-catalog.schema.json": "e3d7dc72a46196354f58e140a63e4d437c37b6fd",
    "schemas/worker-result.schema.json": "68767aa92a1415e6f9e7dcaeeba32c830eb142c7",
}
SCHEMA_IDS = {
    path: f"https://github.com/Kotodama-Project/Kotodama-project/{path}"
    for path in DESTINATIONS
}
REQUIRED_PATHS = {
    MANIFEST_PATH,
    LICENSE_PATH,
    Path("tools/validate_migration_batch_a019.py"),
    Path("tests/test_migration_batch_a019.py"),
    *(Path(path) for path in DESTINATIONS),
}
MAPPING_DIGEST_KEYS = (
    "source_path",
    "source_blob_sha",
    "source_mode",
    "decision",
    "destination_path",
    "destination_blob_sha",
    "body_exported",
    "semantic_coverage",
    "rationale",
)
MANIFEST_ENTRY_KEYS = frozenset(MAPPING_DIGEST_KEYS)
IGNORED_SCAN_DIRECTORIES = {".git", "__pycache__"}

EXPECTED_GATES = {
    "license_and_provenance": "BLOCKED_ISSUE_25",
    "applicable_source_history_secret_pii": (
        "BLOCKED_MISSING_A019_PRIVATE_RECEIPT_ISSUE_251_OR_257"
    ),
    "candidate_privacy_secret": "REQUIRED_EXACT_HEAD",
    "independent_review": "PENDING_LATEST_PUSH",
    "public_governance": "BLOCKED_PR_18_AND_ISSUE_19",
    "sibling_integration": "BLOCKED_ISSUE_30",
    "dependency_review": "BLOCKED_UNTIL_RETARGET_TO_MAIN",
}

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
    "phone_like": re.compile(
        r"(?<!\w)(?=\+?\d[\d ()-]{8,}\d(?!\w))"
        r"(?=\+?\d[\d ()-]*[ ()-])\+?\d[\d ()-]{8,}\d(?!\w)"
    ),
    "absolute_user_path": re.compile(r"(?:/(?:home|Users|root)/|[A-Za-z]:\\Users\\)"),
}
PRIVATE_VALUE_DETECTORS = {
    "named_provider": re.compile(r"\b(?:OpenClaw|Cloudflare|Discord|Proxmox|n8n)\b", re.I),
    "identity_semantics": re.compile(
        r"\b(?:speaker|voice|security[_ -]?tier|private[_ -]?tier)\b", re.I
    ),
    "live_connection_url": re.compile(
        r"\b(?:https?|wss?|postgres(?:ql)?|redis|ssh)://[^\s<>()\"']+", re.I
    ),
}
BANNED_SCHEMA_FIELD = re.compile(
    r"(?:provider|endpoint|deployment|speaker|voice|security.?tier|private.?tier|"
    r"credential|auth.?token|api.?key|model.?id)",
    re.I,
)
ALLOWED_PUBLIC_URLS = {
    "https://json-schema.org/draft/2020-12/schema",
    *SCHEMA_IDS.values(),
}


class CandidateScopeError(RuntimeError):
    pass


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
    if len(data) > 512 * 1024:
        errors.append(f"file exceeds 524288 bytes: {relative.as_posix()}")
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


def _filesystem_paths(root: Path, errors: list[str]) -> set[Path]:
    paths: set[Path] = set()
    try:
        candidates = root.rglob("*")
        for candidate in candidates:
            relative = candidate.relative_to(root)
            if any(part in IGNORED_SCAN_DIRECTORIES for part in relative.parts):
                continue
            if candidate.is_file() or candidate.is_symlink():
                paths.add(relative)
    except (OSError, ValueError) as exc:
        errors.append(f"candidate path scan failed: {type(exc).__name__}")
    return paths


def _git_candidate_paths(root: Path) -> set[Path] | None:
    if not (root / ".git").exists():
        return None

    def git_bytes(*arguments: str) -> bytes:
        return subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True,
            check=True,
        ).stdout

    try:
        if git_bytes("rev-parse", "--is-shallow-repository").strip() == b"true":
            raise CandidateScopeError("shallow repository")
        head_parts = git_bytes(
            "rev-list", "--parents", "-n", "1", "HEAD"
        ).decode("ascii").split()
        parents = head_parts[1:]
        if len(parents) == 2:
            base_commit = git_bytes("merge-base", parents[0], parents[1])
            base_commit = base_commit.decode("ascii").strip()
            candidate_commit = parents[1]
        elif len(parents) == 1:
            manifest_commit = git_bytes(
                "log",
                "-n",
                "1",
                "--format=%H",
                "--diff-filter=A",
                "--",
                MANIFEST_PATH.as_posix(),
            ).decode("utf-8").strip()
            if not manifest_commit:
                return None
            base_commit = git_bytes("rev-parse", f"{manifest_commit}^")
            base_commit = base_commit.decode("ascii").strip()
            candidate_commit = "HEAD"
        else:
            return None
        changed = git_bytes(
            "diff",
            "--name-only",
            "--diff-filter=ACMRTUXB",
            "-z",
            f"{base_commit}..{candidate_commit}",
        )
        untracked = git_bytes("ls-files", "--others", "--exclude-standard", "-z")
    except CandidateScopeError:
        raise
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise CandidateScopeError(type(exc).__name__) from exc

    paths: set[Path] = set()
    for raw in (*changed.split(b"\0"), *untracked.split(b"\0")):
        if not raw:
            continue
        try:
            relative = Path(raw.decode("utf-8"))
        except UnicodeError:
            continue
        if not relative.is_absolute() and not any(
            part in IGNORED_SCAN_DIRECTORIES for part in relative.parts
        ):
            paths.add(relative)
    return paths


def _candidate_scan_paths(root: Path, errors: list[str]) -> set[Path]:
    paths = set(REQUIRED_PATHS)
    try:
        discovered = _git_candidate_paths(root)
    except CandidateScopeError:
        errors.append("candidate Git scope unavailable or shallow")
        discovered = set()
    if discovered is None:
        discovered = _filesystem_paths(root, errors)
    paths.update(discovered)
    return {
        relative
        for relative in paths
        if not any(part in IGNORED_SCAN_DIRECTORIES for part in relative.parts)
    }


def _mapping_digest(entries: list[dict[str, Any]]) -> str:
    rows = [{key: entry.get(key) for key in MAPPING_DIGEST_KEYS} for entry in entries]
    payload = json.dumps(
        rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _scrub_allowed_urls(text: str) -> str:
    for url in ALLOWED_PUBLIC_URLS:
        text = text.replace(url, "")
    return text


def _scan_text(relative: Path, text: str, *, private_values: bool) -> list[str]:
    findings: list[str] = []
    detectors = {**SECRET_DETECTORS, **PII_DETECTORS}
    if private_values:
        detectors.update(PRIVATE_VALUE_DETECTORS)
    for line_number, line in enumerate(text.splitlines(), start=1):
        candidate = _scrub_allowed_urls(line)
        for detector, pattern in detectors.items():
            if pattern.search(candidate):
                findings.append(
                    f"candidate scan finding {detector}: "
                    f"{relative.as_posix()}:{line_number}"
                )
    return findings


def _scan_manifest_strings(value: Any, path: tuple[str, ...] = ()) -> list[str]:
    findings: list[str] = []
    ignored = {
        "source_path",
        "source_blob_sha",
        "destination_blob_sha",
        "blob_sha",
        "license_blob_sha",
        "package_metadata_blob_sha",
        "fixed_commit",
        "source_mapping_digest_sha256",
    }
    if isinstance(value, dict):
        for key, child in value.items():
            if key not in ignored:
                findings.extend(_scan_manifest_strings(child, (*path, key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_scan_manifest_strings(child, (*path, str(index))))
    elif isinstance(value, str):
        candidate = _scrub_allowed_urls(value)
        label = ".".join(path) or "manifest"
        for detector, pattern in {
            **SECRET_DETECTORS,
            **PII_DETECTORS,
            **PRIVATE_VALUE_DETECTORS,
        }.items():
            if pattern.search(candidate):
                findings.append(f"candidate scan finding {detector}: manifest:{label}")
    return findings


def _iter_schema_nodes(value: Any, pointer: str = "") -> Iterable[tuple[str, dict[str, Any]]]:
    if isinstance(value, dict):
        yield pointer or "/", value
        for key, child in value.items():
            escaped = key.replace("~", "~0").replace("/", "~1")
            yield from _iter_schema_nodes(child, f"{pointer}/{escaped}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _iter_schema_nodes(child, f"{pointer}/{index}")


def _json_pointer(document: Any, fragment: str) -> Any:
    if fragment == "":
        return document
    pointer = unquote(fragment)
    if not pointer.startswith("/"):
        raise KeyError("non-pointer fragment")
    current = document
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(token)]
        else:
            current = current[token]
    return current


def _offline_ref_errors(schemas: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    by_id: dict[str, dict[str, Any]] = {}
    for schema in schemas.values():
        schema_id = schema.get("$id")
        if not isinstance(schema_id, str):
            errors.append("schema resource ID must be a string")
            continue
        by_id[schema_id] = schema
    expected_ids = set(SCHEMA_IDS.values())
    if set(by_id) != expected_ids:
        return ["schema resource ID set mismatch"]
    for path, schema in schemas.items():
        base = schema.get("$id")
        if not isinstance(base, str):
            continue
        for pointer, node in _iter_schema_nodes(schema):
            reference = node.get("$ref")
            if not isinstance(reference, str):
                continue
            target = urljoin(base, reference)
            parts = urlsplit(target)
            document_id = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
            if document_id not in by_id:
                errors.append(f"non-offline schema reference: {path}:{pointer}")
                continue
            try:
                _json_pointer(by_id[document_id], parts.fragment)
            except (KeyError, IndexError, TypeError, ValueError):
                errors.append(f"unresolved schema reference: {path}:{pointer}")
    return errors


def _schema_validators(
    schemas: dict[str, dict[str, Any]], errors: list[str]
) -> dict[str, Any]:
    if (
        Draft202012Validator is None
        or FormatChecker is None
        or Registry is None
        or Resource is None
    ):
        errors.append("jsonschema 2020-12 validation dependency unavailable")
        return {}
    try:
        registry = Registry().with_resources(
            (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
        )
    except Exception as exc:  # fail closed without serializing schema contents
        errors.append(f"schema registry construction failed: {type(exc).__name__}")
        return {}
    validators: dict[str, Any] = {}
    for path, schema in schemas.items():
        try:
            Draft202012Validator.check_schema(schema)
            validators[path] = Draft202012Validator(
                schema,
                registry=registry,
                format_checker=FormatChecker(),
            )
        except Exception as exc:  # fail closed without serializing schema contents
            errors.append(f"JSON Schema 2020-12 meta-validation failed: {path}:{type(exc).__name__}")
    return validators


def _task_semantic_errors(task: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    task_id = task.get("task_id")
    dependencies = task.get("dependency_task_ids", [])
    if task_id in dependencies:
        errors.append("task cannot depend on itself")
    authority = task.get("authority", {})
    allowed = set(authority.get("allowed_actions", []))
    denied = set(authority.get("denied_actions", []))
    if allowed & denied:
        errors.append("allowed and denied actions overlap")
    scope = task.get("scope", {})
    if set(scope.get("resources", [])) & set(scope.get("excluded_resources", [])):
        errors.append("included and excluded resources overlap")
    check_ids = [
        check.get("check_id")
        for check in task.get("acceptance_checks", [])
        if isinstance(check, dict)
    ]
    if len(check_ids) != len(set(check_ids)):
        errors.append("duplicate acceptance check IDs")
    rollback = task.get("rollback", {})
    reversible = rollback.get("reversible")
    strategy = rollback.get("strategy")
    steps = rollback.get("steps", [])
    if reversible is False and (strategy != "not_applicable" or steps):
        errors.append("irreversible task must use not_applicable with no rollback steps")
    if reversible is True and (strategy == "not_applicable" or not steps):
        errors.append("reversible task must define a rollback strategy and steps")
    return errors


def _decomposition_semantic_errors(instance: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    tasks = instance.get("tasks", [])
    if not isinstance(tasks, list) or any(not isinstance(task, dict) for task in tasks):
        return ["decomposition tasks are not objects"]
    ids = [task.get("task_id") for task in tasks]
    known = set(ids)
    if len(ids) != len(known):
        errors.append("duplicate task IDs")
    if instance.get("root_task_id") not in known:
        errors.append("unknown root task ID")
    expected_edges = {
        (task.get("task_id"), dependency, "requires")
        for task in tasks
        for dependency in task.get("dependency_task_ids", [])
    }
    actual_edges: list[tuple[Any, Any, Any]] = []
    for edge in instance.get("edges", []):
        if not isinstance(edge, dict):
            errors.append("decomposition edge is not an object")
            continue
        item = (edge.get("from_task_id"), edge.get("to_task_id"), edge.get("relation"))
        actual_edges.append(item)
        if item[0] not in known or item[1] not in known:
            errors.append("unknown dependency reference")
        if item[0] == item[1]:
            errors.append("self dependency edge")
    if len(actual_edges) != len(set(actual_edges)):
        errors.append("duplicate dependency edge")
    if set(actual_edges) != expected_edges:
        errors.append("dependency edges do not match task dependency IDs")

    graph = {
        task.get("task_id"): list(task.get("dependency_task_ids", [])) for task in tasks
    }
    visiting: set[Any] = set()
    visited: set[Any] = set()

    def visit(node: Any) -> None:
        if node in visiting:
            errors.append("cyclic dependency graph")
            return
        if node in visited or node not in graph:
            return
        visiting.add(node)
        for dependency in graph[node]:
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for task_id in ids:
        visit(task_id)
    for task in tasks:
        errors.extend(_task_semantic_errors(task))
    return errors


def _catalog_semantic_errors(instance: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    workers = instance.get("workers", [])
    worker_ids = [worker.get("worker_id") for worker in workers if isinstance(worker, dict)]
    if len(worker_ids) != len(set(worker_ids)):
        errors.append("duplicate worker IDs")
    capability_ids = [
        capability.get("capability_id")
        for worker in workers
        if isinstance(worker, dict)
        for capability in worker.get("capabilities", [])
        if isinstance(capability, dict)
    ]
    if len(capability_ids) != len(set(capability_ids)):
        errors.append("duplicate capability IDs")
    for worker in workers:
        if not isinstance(worker, dict):
            continue
        for capability in worker.get("capabilities", []):
            if not isinstance(capability, dict):
                continue
            if (
                capability.get("risk_class") != "inspect"
                and capability.get("evidence_required") is not True
            ):
                errors.append("mutation capability must require evidence")
    return errors


def _result_semantic_errors(instance: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    checks = instance.get("checks", [])
    check_ids = [
        check.get("check_id") for check in checks if isinstance(check, dict)
    ]
    if len(check_ids) != len(set(check_ids)):
        errors.append("duplicate result check IDs")

    status = instance.get("status")
    evidence = instance.get("evidence_refs", [])
    omitted = instance.get("omitted_work", [])
    if status == "succeeded":
        if not evidence:
            errors.append("succeeded result must bind evidence")
        if not checks or any(
            not isinstance(check, dict) or check.get("status") != "pass"
            for check in checks
        ):
            errors.append("succeeded result requires every check to pass")
        if omitted:
            errors.append("succeeded result cannot omit work")
        if "error_category" in instance:
            errors.append("succeeded result cannot include an error category")
    elif status in {"failed", "blocked"}:
        if "error_category" not in instance:
            errors.append("failed or blocked result requires an error category")
        failed_check = any(
            isinstance(check, dict) and check.get("status") == "fail"
            for check in checks
        )
        if not omitted and not failed_check:
            errors.append("failed or blocked result requires omitted work or a failed check")

    claims = instance.get("authority_claims")
    if claims != {"promotion": False, "current_truth": False, "release": False}:
        errors.append("result authority claims must all remain false")

    rollback = instance.get("rollback", {})
    rollback_status = rollback.get("status")
    receipts = rollback.get("receipt_refs", [])
    if rollback_status in {"available", "executed", "failed"} and not receipts:
        errors.append("rollback status requires a receipt")
    if rollback_status == "not_required" and receipts:
        errors.append("not_required rollback cannot bind receipts")
    return errors


def validate_instance(
    schema_path: str,
    instance: dict[str, Any],
    schemas: dict[str, dict[str, Any]],
    validators: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    validator = validators.get(schema_path)
    if validator is None:
        return [f"schema validator unavailable: {schema_path}"]
    try:
        schema_errors = list(validator.iter_errors(instance))
    except Exception as exc:  # fail closed without serializing instance contents
        errors.append(f"schema validation failed: {type(exc).__name__}")
    else:
        errors.extend(
            f"schema validation failed at {'/'.join(str(part) for part in error.path) or '/'}"
            for error in schema_errors
        )
    try:
        if schema_path == "schemas/task-contract.schema.json":
            errors.extend(_task_semantic_errors(instance))
        elif schema_path == "schemas/task-decomposition.schema.json":
            errors.extend(_decomposition_semantic_errors(instance))
        elif schema_path == "schemas/worker-capability-catalog.schema.json":
            errors.extend(_catalog_semantic_errors(instance))
        elif schema_path == "schemas/worker-result.schema.json":
            errors.extend(_result_semantic_errors(instance))
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        errors.append(f"semantic validation failed closed: {type(exc).__name__}")
    return sorted(set(errors))


def positive_instances() -> dict[str, dict[str, Any]]:
    catalog = {
        "kind": "worker_capability_catalog",
        "schema_version": "1.0",
        "candidate_status": "candidate_only",
        "catalog_id": "catalog.public",
        "revision": 1,
        "evidence_refs": [],
        "workers": [
            {
                "worker_id": "worker.alpha",
                "label": "General reviewer",
                "candidate_status": "candidate_only",
                "capabilities": [
                    {
                        "capability_id": "inspect.record",
                        "name": "Record inspection",
                        "description": "Inspect a bounded record and return evidence.",
                        "input_kinds": ["record.input"],
                        "output_kinds": ["record.finding"],
                        "risk_class": "inspect",
                        "evidence_required": True,
                        "max_concurrency": 1,
                    }
                ],
            }
        ],
    }

    def task(task_id: str, dependencies: list[str]) -> dict[str, Any]:
        return {
            "kind": "task_contract",
            "schema_version": "1.0",
            "candidate_status": "candidate_only",
            "task_id": task_id,
            "revision": 1,
            "state": "draft",
            "objective": "Inspect the bounded candidate record.",
            "scope": {
                "resources": [f"urn:resource/{task_id}"],
                "excluded_resources": [],
            },
            "input_refs": [],
            "dependency_task_ids": dependencies,
            "required_capability_ids": ["inspect.record"],
            "acceptance_checks": [
                {
                    "check_id": "evidence.bound",
                    "description": "The result binds review evidence.",
                    "evidence_required": True,
                }
            ],
            "authority": {
                "owner_role": "reviewer.role",
                "grants_execution": False,
                "allowed_actions": ["inspect.record"],
                "denied_actions": ["publish.record"],
            },
            "budgets": {"max_attempts": 1, "timeout_seconds": 300},
            "stop_conditions": ["Stop when evidence cannot be produced."],
            "rollback": {
                "reversible": False,
                "strategy": "not_applicable",
                "steps": [],
            },
        }

    child = task("task.child", [])
    root = task("task.root", ["task.child"])
    decomposition = {
        "kind": "task_decomposition",
        "schema_version": "1.0",
        "candidate_status": "candidate_only",
        "decomposition_id": "decomposition.public",
        "root_task_id": "task.root",
        "tasks": [root, child],
        "edges": [
            {
                "from_task_id": "task.root",
                "to_task_id": "task.child",
                "relation": "requires",
            }
        ],
    }
    result = {
        "kind": "worker_result",
        "schema_version": "1.0",
        "candidate_status": "candidate_only",
        "result_id": "result.public",
        "task_ref": "task.root",
        "worker_ref": "worker.alpha",
        "capability_ref": "inspect.record",
        "attempt": 1,
        "status": "succeeded",
        "candidate_refs": ["urn:candidate/result"],
        "evidence_refs": ["urn:evidence/result"],
        "checks": [
            {
                "check_id": "evidence.bound",
                "status": "pass",
                "evidence_ref": "urn:evidence/check",
            }
        ],
        "omitted_work": [],
        "authority_claims": {
            "promotion": False,
            "current_truth": False,
            "release": False,
        },
        "rollback": {"status": "not_required", "receipt_refs": []},
    }
    return {
        "schemas/task-contract.schema.json": child,
        "schemas/task-decomposition.schema.json": decomposition,
        "schemas/worker-capability-catalog.schema.json": catalog,
        "schemas/worker-result.schema.json": result,
    }


def validate(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    errors: list[str] = []
    manifest = _load_json(root, MANIFEST_PATH, errors)
    if not isinstance(manifest, dict):
        manifest = {}

    if manifest.get("schema_version") != "kotodama.public-migration-batch.v1":
        errors.append("unexpected manifest schema_version")
    if manifest.get("batch_id") != "A019":
        errors.append("unexpected batch_id")
    if manifest.get("status") != "CANDIDATE_ONLY":
        errors.append("batch status must remain CANDIDATE_ONLY")
    if manifest.get("publication_state") != "NO_GO_UNPUBLISHED":
        errors.append("publication state must remain NO_GO_UNPUBLISHED")

    expected_source = {
        "fixed_commit": SOURCE_COMMIT,
        "expected_entries": 6,
        "source_mapping_digest_sha256": SOURCE_MAPPING_DIGEST,
        "git_history_imported": False,
        "source_bodies_copied_unchanged": False,
        "license_expression": "MIT",
        "license_blob_sha": SOURCE_LICENSE_BLOB,
        "package_metadata_blob_sha": SOURCE_PACKAGE_BLOB,
    }
    source = manifest.get("source")
    if source != expected_source:
        errors.append("source fixed-point contract mismatch")
    if manifest.get("decision_contract") != {
        "PUBLIC_REAUTHOR": 4,
        "PRIVATE_RETAIN": 2,
        "SUPERSEDED": 0,
        "unique_reauthored_destinations": 4,
    }:
        errors.append("decision count contract mismatch")
    if manifest.get("component_license") != {
        "expression": "MIT",
        "notice": "Copyright (c) 2026 Kotodama Project",
        "license_file": "LICENSES/MIT.txt",
        "license_blob_sha": SOURCE_LICENSE_BLOB,
        "source_derived_scope": sorted(DESTINATIONS),
        "license_and_provenance_gate": "BLOCKED_ISSUE_25",
        "apache_pr18_relicenses_component": False,
    }:
        errors.append("component MIT scope or provenance boundary mismatch")
    if manifest.get("admission_gates") != EXPECTED_GATES:
        errors.append("admission gates must remain fail closed")

    raw_entries = manifest.get("entries")
    if not isinstance(raw_entries, list) or any(
        not isinstance(entry, dict) for entry in raw_entries
    ):
        errors.append("manifest entries must be an object array")
        entries: list[dict[str, Any]] = []
    else:
        entries = raw_entries
    if len(entries) != 6:
        errors.append("manifest must contain exactly 6 source entries")
    source_paths = [entry.get("source_path") for entry in entries]
    if not all(isinstance(source_path, str) for source_path in source_paths):
        errors.append("every source path must be a string")
    else:
        if source_paths != sorted(source_paths):
            errors.append("source entries must be sorted by exact path")
        if len(source_paths) != len(set(source_paths)):
            errors.append("duplicate source paths")
    mapping_digest = _mapping_digest(entries)
    if mapping_digest != SOURCE_MAPPING_DIGEST:
        errors.append("exact source path/blob/mode/decision mapping digest mismatch")
    source_mapping_digest = (
        source.get("source_mapping_digest_sha256") if isinstance(source, dict) else None
    )
    if source_mapping_digest != mapping_digest:
        errors.append("manifest source mapping digest is not self-consistent")
    if any(entry.get("source_mode") != "100644" for entry in entries):
        errors.append("every source mode must remain 100644")
    source_blob_values = [entry.get("source_blob_sha") for entry in entries]
    source_blobs = {
        source_blob
        for source_blob in source_blob_values
        if isinstance(source_blob, str)
    }
    if len(source_blobs) != len(source_blob_values) or source_blobs != SOURCE_BLOBS:
        errors.append("exact current source-blob coverage mismatch")
    if any(entry.get("body_exported") is not False for entry in entries):
        errors.append("every source body export flag must remain false")
    for entry in entries:
        unknown_fields = sorted(set(entry) - MANIFEST_ENTRY_KEYS)
        missing_fields = sorted(MANIFEST_ENTRY_KEYS - set(entry))
        for field in unknown_fields:
            errors.append(f"unknown manifest entry field: {field}")
        for field in missing_fields:
            errors.append(f"manifest entry missing field: {field}")
        coverage = entry.get("semantic_coverage")
        if (
            not isinstance(coverage, list)
            or not coverage
            or any(not isinstance(item, str) for item in coverage)
            or coverage != sorted(coverage)
            or len(coverage) != len(set(coverage))
        ):
            errors.append("semantic coverage must be non-empty, unique, and sorted")
        rationale = entry.get("rationale")
        if not isinstance(rationale, str) or not 1 <= len(rationale) <= 512:
            errors.append("invalid decision rationale")

    decision_values = [entry.get("decision") for entry in entries]
    decisions = Counter(
        decision for decision in decision_values if isinstance(decision, str)
    )
    if any(not isinstance(decision, str) for decision in decision_values):
        errors.append("every decision must be a string")
    if decisions != Counter({"PUBLIC_REAUTHOR": 4, "PRIVATE_RETAIN": 2}):
        errors.append("actual decision counts mismatch")
    public = [entry for entry in entries if entry.get("decision") == "PUBLIC_REAUTHOR"]
    private = [entry for entry in entries if entry.get("decision") == "PRIVATE_RETAIN"]
    public_destinations = [entry.get("destination_path") for entry in public]
    public_destination_set = {
        destination
        for destination in public_destinations
        if isinstance(destination, str)
    }
    if len(public_destination_set) != len(public_destinations):
        errors.append("PUBLIC_REAUTHOR destinations must be strings")
    if public_destination_set != set(DESTINATIONS) or len(public_destinations) != 4:
        errors.append("PUBLIC_REAUTHOR destination set or uniqueness mismatch")
    for entry in public:
        destination = entry.get("destination_path")
        if (
            isinstance(destination, str)
            and destination in DESTINATIONS
            and entry.get("destination_blob_sha") != DESTINATIONS[destination]
        ):
            errors.append(f"PUBLIC_REAUTHOR destination blob mismatch: {destination}")
    for entry in private:
        if entry.get("destination_path") is not None or entry.get("destination_blob_sha") is not None:
            errors.append("PRIVATE_RETAIN entry has a public destination")

    expected_destination_contract = [
        {
            "path": path,
            "blob_sha": blob_sha,
            "schema_id": SCHEMA_IDS[path],
            "candidate_status": "candidate_only",
        }
        for path, blob_sha in sorted(DESTINATIONS.items())
    ]
    if manifest.get("destination_contract") != expected_destination_contract:
        errors.append("destination contract fixed-point mismatch")

    candidate_scan_paths = _candidate_scan_paths(root, errors)
    source_blob_reuse_paths: list[str] = []
    for relative in sorted(candidate_scan_paths):
        data = _read_bounded(root, relative, errors)
        if data is not None and git_blob_sha(data) in SOURCE_BLOBS:
            source_blob_reuse_paths.append(relative.as_posix())
            errors.append(f"source registry blob copied unchanged: {relative.as_posix()}")

    destination_blobs_verified = 0
    schemas: dict[str, dict[str, Any]] = {}
    for path, expected_sha in DESTINATIONS.items():
        data = _read_bounded(root, Path(path), errors)
        if data is None:
            continue
        if git_blob_sha(data) != expected_sha:
            errors.append(f"destination blob mismatch: {path}")
        else:
            destination_blobs_verified += 1
        try:
            schema = json.loads(data.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            errors.append(f"invalid UTF-8 schema JSON: {path}")
            continue
        if not isinstance(schema, dict):
            errors.append(f"schema root must be an object: {path}")
            continue
        schemas[path] = schema
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            errors.append(f"schema draft mismatch: {path}")
        if schema.get("$id") != SCHEMA_IDS[path]:
            errors.append(f"schema ID mismatch: {path}")
        if schema.get("additionalProperties") is not False:
            errors.append(f"schema root must be closed: {path}")
        properties = schema.get("properties")
        candidate_property = (
            properties.get("candidate_status", {})
            if isinstance(properties, dict)
            else {}
        )
        if candidate_property.get("const") != "candidate_only":
            errors.append(f"schema must remain candidate-only: {path}")
        for pointer, node in _iter_schema_nodes(schema):
            if (
                node.get("type") == "object"
                and "/contains" not in pointer
                and node.get("additionalProperties") is not False
            ):
                errors.append(f"open object schema: {path}:{pointer}")
            properties = node.get("properties")
            if isinstance(properties, dict):
                for field in properties:
                    if BANNED_SCHEMA_FIELD.search(field):
                        errors.append(f"private or provider field rejected: {path}:{pointer}")

    errors.extend(_offline_ref_errors(schemas))
    validators = _schema_validators(schemas, errors)
    for path, instance in positive_instances().items():
        for error in validate_instance(path, instance, schemas, validators):
            errors.append(f"positive contract invalid: {path}:{error}")

    license_data = _read_bounded(root, LICENSE_PATH, errors)
    if license_data is not None and git_blob_sha(license_data) != SOURCE_LICENSE_BLOB:
        errors.append("MIT license bytes do not match pinned source license blob")

    manifest_data = _read_bounded(root, MANIFEST_PATH, errors)
    source_path_leaks = 0
    for source_path in source_paths:
        if not isinstance(source_path, str):
            continue
        if manifest_data is None or manifest_data.decode("utf-8", errors="replace").count(source_path) != 1:
            errors.append("source path must appear exactly once in manifest")
        for relative in candidate_scan_paths - {MANIFEST_PATH}:
            data = _read_bounded(root, relative, errors)
            if data is not None and source_path.encode("utf-8") in data:
                source_path_leaks += 1
                errors.append(f"source path leaked outside manifest: {relative.as_posix()}")

    errors.extend(_scan_manifest_strings(manifest))
    for relative in candidate_scan_paths - {MANIFEST_PATH}:
        data = _read_bounded(root, relative, errors)
        if data is None:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeError:
            errors.append(f"invalid UTF-8 candidate file: {relative.as_posix()}")
            continue
        errors.extend(
            _scan_text(relative, text, private_values=relative.as_posix() in DESTINATIONS)
        )

    errors = sorted(set(errors))
    return {
        "schema_version": "kotodama.public-migration-validation.v1",
        "batch_id": "A019",
        "status": "PASS" if not errors else "FAIL",
        "changed": False,
        "source_fixed_commit": SOURCE_COMMIT,
        "source_entries": len(entries),
        "source_mapping_digest_sha256": mapping_digest,
        "decisions": dict(sorted(decisions.items())),
        "unique_reauthored_destinations": len(
            {
                destination
                for destination in public_destinations
                if isinstance(destination, str)
            }
        ),
        "destination_blobs_verified": destination_blobs_verified,
        "schemas_meta_validated": len(validators),
        "offline_refs_resolved": not any("schema reference" in error for error in errors),
        "source_registry_blob_reuse": len(source_blob_reuse_paths),
        "source_path_leakage": source_path_leaks,
        "candidate_scan_findings": sum(
            1 for error in errors if error.startswith("candidate scan finding ")
        ),
        "component_license": "MIT",
        "license_blob_sha": SOURCE_LICENSE_BLOB,
        "admission_status": "BLOCKED",
        "no_go_reasons": [
            "ISSUE_25_LICENSE_PROVENANCE",
            "MISSING_APPLICABLE_A019_PRIVATE_SOURCE_HISTORY_RECEIPT",
            "INDEPENDENT_LATEST_PUSH_REVIEW_PENDING",
            "PR18_AND_ISSUE19_GOVERNANCE_PENDING",
            "ISSUE30_SIBLING_INTEGRATION_PENDING",
            "DEPENDENCY_REVIEW_AFTER_RETARGET_PENDING",
        ],
        "errors": errors,
    }


def main() -> int:
    result = validate(ROOT)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
