#!/usr/bin/env python3
"""Validate a secret-free Kotodama template pack using only the stdlib."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


FORBIDDEN_SECRET_KEY_MARKERS = {
    "apikey",
    "accesskey",
    "token",
    "secret",
    "password",
    "cookie",
    "webhookurl",
    "privatekey",
    "credential",
}
SECRET_VALUE_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/", re.I),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
SAFE_RELATIVE_JSON_PATH_PATTERN = re.compile(r"^[A-Za-z0-9._/-]+\.json$")
ALLOWED_TEMPLATE_STATUSES = {"example", "draft", "candidate_only", "locally_verified"}
ALLOWED_PROFILES = {"compose_minimum", "proxmox_segmented"}
ALLOWED_BLOCK_ACTIONS = {
    "local_preview",
    "synthetic_validation",
    "read_only",
    "draft",
    "analyze",
}
FORBIDDEN_TERMINAL_ARTIFACTS = {
    "capability_grant",
    "promotion",
    "promoted",
    "current_truth",
    "public_go",
    "final_human_go",
}
REQUIRED_MANIFEST_FIELDS = {
    "kind",
    "spec_version",
    "id",
    "status",
    "human_intent_ref",
    "canonical_owners",
    "profiles",
    "blocks",
    "mocs",
    "denied_actions",
    "public_beta",
}
ALLOWED_MANIFEST_FIELDS = REQUIRED_MANIFEST_FIELDS | {"flow", "records"}
REQUIRED_FLOW_FIELDS = {"entry_inputs", "sequence", "moc_ref"}
MANDATORY_DENIALS = {
    "unbound_external_write",
    "credential_permission_change",
    "self_promotion",
    "destructive_delete_without_rollback",
}
REQUIRED_CANONICAL_OWNERS = {
    "human_intent",
    "decisions",
    "work_orders",
    "capability_grants",
    "verification_receipts",
    "promotions",
    "current_truth",
}
REQUIRED_BLOCK_FIELDS = {
    "kind",
    "spec_version",
    "id",
    "status",
    "purpose",
    "inputs",
    "outputs",
    "authority",
    "verification",
    "rollback",
    "stop_conditions",
}
REQUIRED_AUTHORITY_FIELDS = {
    "owner_role",
    "allowed_actions",
    "denied_actions",
    "expires_at",
}
REQUIRED_VERIFICATION_FIELDS = {
    "success_conditions",
    "negative_tests",
    "receipt_required",
}
REQUIRED_ROLLBACK_FIELDS = {"action", "verify"}
REQUIRED_MOC_FIELDS = {
    "kind",
    "spec_version",
    "id",
    "status",
    "authority",
    "title",
    "refs",
}
REQUIRED_RECORD_FIELDS = {
    "kind",
    "spec_version",
    "id",
    "status",
    "artifact",
    "purpose",
    "canonical_owner",
    "required_fields",
    "authority",
    "retention",
    "denied_claims",
}
REQUIRED_RECORD_AUTHORITY_FIELDS = {
    "creator_role",
    "verifier_role",
    "promotion_required_for_current_truth",
}
REQUIRED_RECORD_RETENTION_FIELDS = {"mode", "policy_ref"}
MANDATORY_RECORD_DENIED_CLAIMS = {
    "self_approval",
    "self_promotion",
    "current_truth_without_promotion",
}
ARTIFACT_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,62}$")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def is_safe_relative_json_path(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = Path(value)
    return (
        SAFE_RELATIVE_JSON_PATH_PATTERN.fullmatch(value) is not None
        and not path.is_absolute()
        and ".." not in path.parts
        and path.suffix.lower() == ".json"
    )


def is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def has_valid_id_format(value: object) -> bool:
    return isinstance(value, str) and ID_PATTERN.fullmatch(value) is not None


def is_timezone_aware_iso8601(value: object) -> bool:
    if not is_non_empty_string(value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def require_string_list(
    document: dict[str, Any],
    field: str,
    errors: list[str],
    location: str,
    *,
    minimum: int = 0,
    unique: bool = False,
) -> list[str]:
    value = document.get(field)
    if not isinstance(value, list):
        errors.append(f"{location} field {field} must be an array")
        return []
    if not all(is_non_empty_string(item) for item in value):
        errors.append(f"{location} field {field} must contain only strings")
    strings = [item for item in value if is_non_empty_string(item)]
    if len(strings) < minimum:
        errors.append(f"{location} field {field} must contain at least {minimum} item(s)")
    if unique and len(strings) != len(set(strings)):
        errors.append(f"{location} field {field} must contain unique items")
    return strings


def require_object(
    document: dict[str, Any], field: str, errors: list[str], location: str
) -> dict[str, Any]:
    value = document.get(field)
    if not isinstance(value, dict):
        errors.append(f"{location} field {field} must be an object")
        return {}
    return value


def require_fields(
    document: dict[str, Any], required: set[str], errors: list[str], location: str
) -> None:
    for field in sorted(required - document.keys()):
        errors.append(f"{location} missing required field: {field}")


def reject_unknown_fields(
    document: dict[str, Any], allowed: set[str], errors: list[str], location: str
) -> None:
    for field in sorted(document.keys() - allowed):
        errors.append(f"{location} contains unknown field: {field}")


def find_secret_keys(value: object, location: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_location = f"{location}.{key}"
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            is_reference = normalized.endswith(("ref", "reference", "locator"))
            if not is_reference and any(
                marker in normalized for marker in FORBIDDEN_SECRET_KEY_MARKERS
            ):
                errors.append(f"secret-bearing key is forbidden: {child_location}")
            errors.extend(find_secret_keys(child, child_location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(find_secret_keys(child, f"{location}[{index}]"))
    elif isinstance(value, str):
        if any(pattern.search(value) for pattern in SECRET_VALUE_PATTERNS):
            errors.append(f"secret-like value is forbidden: {location}")
    return errors


def validate_manifest(manifest: dict[str, Any], errors: list[str]) -> dict[str, list[str]]:
    require_fields(manifest, REQUIRED_MANIFEST_FIELDS, errors, "manifest")
    reject_unknown_fields(manifest, ALLOWED_MANIFEST_FIELDS, errors, "manifest")
    collections = {
        "profiles": require_string_list(
            manifest, "profiles", errors, "manifest", minimum=1, unique=True
        ),
        "blocks": require_string_list(
            manifest, "blocks", errors, "manifest", unique=True
        ),
        "mocs": require_string_list(
            manifest, "mocs", errors, "manifest", unique=True
        ),
        "records": require_string_list(
            manifest, "records", errors, "manifest", unique=True
        )
        if "records" in manifest
        else [],
        "denied_actions": require_string_list(
            manifest, "denied_actions", errors, "manifest", unique=True
        ),
        "flow_entry_inputs": [],
        "flow_sequence": [],
        "flow_moc_ref": [],
    }
    if "flow" in manifest:
        flow = require_object(manifest, "flow", errors, "manifest")
        require_fields(flow, REQUIRED_FLOW_FIELDS, errors, "manifest flow")
        reject_unknown_fields(flow, REQUIRED_FLOW_FIELDS, errors, "manifest flow")
        collections["flow_entry_inputs"] = require_string_list(
            flow,
            "entry_inputs",
            errors,
            "manifest flow",
            minimum=1,
            unique=True,
        )
        collections["flow_sequence"] = require_string_list(
            flow, "sequence", errors, "manifest flow", minimum=1, unique=True
        )
        for block_id in collections["flow_sequence"]:
            if not has_valid_id_format(block_id):
                errors.append(
                    f"manifest flow.sequence item has invalid id format: {block_id}"
                )
        moc_ref = flow.get("moc_ref")
        if not is_non_empty_string(moc_ref):
            errors.append("manifest flow.moc_ref must be a non-empty string")
        else:
            collections["flow_moc_ref"] = [moc_ref]
            if not has_valid_id_format(moc_ref):
                errors.append(f"manifest flow.moc_ref has invalid id format: {moc_ref}")
    if not is_non_empty_string(manifest.get("id")):
        errors.append("manifest field id must be a non-empty string")
    elif not has_valid_id_format(manifest.get("id")):
        errors.append(f"manifest field id has an invalid format: {manifest.get('id')}")
    if not is_non_empty_string(manifest.get("human_intent_ref")):
        errors.append("manifest field human_intent_ref must be a non-empty string")
    owners = require_object(manifest, "canonical_owners", errors, "manifest")
    for owner in sorted(REQUIRED_CANONICAL_OWNERS - owners.keys()):
        errors.append(f"manifest missing canonical owner: {owner}")
    for owner, value in owners.items():
        if not is_non_empty_string(value):
            errors.append(f"manifest canonical owner {owner} must be a non-empty string")
    if manifest.get("status") not in ALLOWED_TEMPLATE_STATUSES:
        errors.append(f"manifest status is not allowed: {manifest.get('status')}")
    if manifest.get("kind") != "company_template":
        errors.append("manifest kind must be company_template")
    if manifest.get("spec_version") != "0.1":
        errors.append("manifest spec_version must be 0.1")
    if manifest.get("public_beta") != "NO_GO_UNPUBLISHED":
        errors.append("public_beta must remain NO_GO_UNPUBLISHED")
    for profile in collections["profiles"]:
        if profile not in ALLOWED_PROFILES:
            errors.append(f"manifest unsupported profile: {profile}")
    for denial in sorted(MANDATORY_DENIALS - set(collections["denied_actions"])):
        errors.append(f"manifest missing mandatory denial: {denial}")
    return collections


def validate_block(relative: str, document: dict[str, Any], errors: list[str]) -> None:
    require_fields(document, REQUIRED_BLOCK_FIELDS, errors, relative)
    reject_unknown_fields(document, REQUIRED_BLOCK_FIELDS, errors, relative)
    if document.get("kind") != "block":
        errors.append(f"{relative} kind must be block")
    if document.get("spec_version") != "0.1":
        errors.append(f"{relative} spec_version must be 0.1")
    if not is_non_empty_string(document.get("id")):
        errors.append(f"{relative} field id must be a non-empty string")
    elif not has_valid_id_format(document.get("id")):
        errors.append(f"{relative} field id has an invalid format: {document.get('id')}")
    if document.get("status") not in ALLOWED_TEMPLATE_STATUSES:
        errors.append(f"{relative} status is not allowed: {document.get('status')}")
    if not is_non_empty_string(document.get("purpose")):
        errors.append(f"{relative} field purpose must be a non-empty string")
    require_string_list(document, "inputs", errors, relative, minimum=1, unique=True)
    outputs = require_string_list(
        document, "outputs", errors, relative, minimum=1, unique=True
    )
    for output in outputs:
        if output in FORBIDDEN_TERMINAL_ARTIFACTS:
            errors.append(f"{relative} forbidden output artifact: {output}")
    require_string_list(
        document, "stop_conditions", errors, relative, minimum=1, unique=True
    )

    authority = require_object(document, "authority", errors, relative)
    authority_location = f"{relative} authority"
    require_fields(authority, REQUIRED_AUTHORITY_FIELDS, errors, authority_location)
    reject_unknown_fields(authority, REQUIRED_AUTHORITY_FIELDS, errors, authority_location)
    if not is_non_empty_string(authority.get("owner_role")):
        errors.append(f"{authority_location}.owner_role must be a non-empty string")
    allowed_actions = require_string_list(
        authority, "allowed_actions", errors, authority_location, unique=True
    )
    for action in allowed_actions:
        if action not in ALLOWED_BLOCK_ACTIONS:
            errors.append(f"{relative} forbidden allowed action: {action}")
    require_string_list(
        authority,
        "denied_actions",
        errors,
        authority_location,
        minimum=1,
        unique=True,
    )
    if not is_timezone_aware_iso8601(authority.get("expires_at")):
        errors.append(
            f"{authority_location}.expires_at must be a timezone-aware ISO-8601 date-time"
        )

    verification = require_object(document, "verification", errors, relative)
    verification_location = f"{relative} verification"
    require_fields(verification, REQUIRED_VERIFICATION_FIELDS, errors, verification_location)
    reject_unknown_fields(
        verification, REQUIRED_VERIFICATION_FIELDS, errors, verification_location
    )
    require_string_list(
        verification, "success_conditions", errors, verification_location, minimum=1
    )
    require_string_list(
        verification, "negative_tests", errors, verification_location, minimum=1
    )
    if verification.get("receipt_required") is not True:
        errors.append(f"{relative} verification.receipt_required must be true")

    rollback = require_object(document, "rollback", errors, relative)
    rollback_location = f"{relative} rollback"
    require_fields(rollback, REQUIRED_ROLLBACK_FIELDS, errors, rollback_location)
    reject_unknown_fields(rollback, REQUIRED_ROLLBACK_FIELDS, errors, rollback_location)
    for field in sorted(REQUIRED_ROLLBACK_FIELDS):
        if not is_non_empty_string(rollback.get(field)):
            errors.append(f"{rollback_location}.{field} must be a non-empty string")


def validate_moc(
    relative: str,
    document: dict[str, Any],
    known_ids: set[str],
    errors: list[str],
) -> None:
    require_fields(document, REQUIRED_MOC_FIELDS, errors, relative)
    reject_unknown_fields(document, REQUIRED_MOC_FIELDS, errors, relative)
    if document.get("kind") != "moc":
        errors.append(f"{relative} kind must be moc")
    if document.get("spec_version") != "0.1":
        errors.append(f"{relative} spec_version must be 0.1")
    if not is_non_empty_string(document.get("id")):
        errors.append(f"{relative} field id must be a non-empty string")
    elif not has_valid_id_format(document.get("id")):
        errors.append(f"{relative} field id has an invalid format: {document.get('id')}")
    if document.get("status") not in ALLOWED_TEMPLATE_STATUSES:
        errors.append(f"{relative} status is not allowed: {document.get('status')}")
    if document.get("authority") != "navigation_only":
        errors.append(f"{relative} authority must be navigation_only")
    if not is_non_empty_string(document.get("title")):
        errors.append(f"{relative} field title must be a non-empty string")
    for reference in require_string_list(
        document, "refs", errors, relative, minimum=1, unique=True
    ):
        if reference not in known_ids:
            errors.append(f"{relative} references unknown id: {reference}")


def validate_record(relative: str, document: dict[str, Any], errors: list[str]) -> None:
    require_fields(document, REQUIRED_RECORD_FIELDS, errors, relative)
    reject_unknown_fields(document, REQUIRED_RECORD_FIELDS, errors, relative)
    if document.get("kind") != "record_template":
        errors.append(f"{relative} kind must be record_template")
    if document.get("spec_version") != "0.1":
        errors.append(f"{relative} spec_version must be 0.1")
    if not is_non_empty_string(document.get("id")):
        errors.append(f"{relative} field id must be a non-empty string")
    elif not has_valid_id_format(document.get("id")):
        errors.append(f"{relative} field id has an invalid format: {document.get('id')}")
    if document.get("status") not in ALLOWED_TEMPLATE_STATUSES:
        errors.append(f"{relative} status is not allowed: {document.get('status')}")
    artifact = document.get("artifact")
    if not is_non_empty_string(artifact) or ARTIFACT_PATTERN.fullmatch(artifact) is None:
        errors.append(f"{relative} field artifact must use snake_case")
    elif artifact in FORBIDDEN_TERMINAL_ARTIFACTS:
        errors.append(f"{relative} forbidden record artifact: {artifact}")
    for field in ("purpose", "canonical_owner"):
        if not is_non_empty_string(document.get(field)):
            errors.append(f"{relative} field {field} must be a non-empty string")
    required_fields = require_string_list(
        document, "required_fields", errors, relative, minimum=1, unique=True
    )
    for field in required_fields:
        if ARTIFACT_PATTERN.fullmatch(field) is None:
            errors.append(f"{relative} required field must use snake_case: {field}")

    authority = require_object(document, "authority", errors, relative)
    authority_location = f"{relative} authority"
    require_fields(
        authority, REQUIRED_RECORD_AUTHORITY_FIELDS, errors, authority_location
    )
    reject_unknown_fields(
        authority, REQUIRED_RECORD_AUTHORITY_FIELDS, errors, authority_location
    )
    for field in ("creator_role", "verifier_role"):
        if not is_non_empty_string(authority.get(field)):
            errors.append(f"{authority_location}.{field} must be a non-empty string")
    if (
        is_non_empty_string(authority.get("creator_role"))
        and is_non_empty_string(authority.get("verifier_role"))
        and authority["creator_role"] == authority["verifier_role"]
    ):
        errors.append(
            f"{authority_location} creator_role and verifier_role must differ"
        )
    if authority.get("promotion_required_for_current_truth") is not True:
        errors.append(
            f"{authority_location}.promotion_required_for_current_truth must be true"
        )

    retention = require_object(document, "retention", errors, relative)
    retention_location = f"{relative} retention"
    require_fields(
        retention, REQUIRED_RECORD_RETENTION_FIELDS, errors, retention_location
    )
    reject_unknown_fields(
        retention, REQUIRED_RECORD_RETENTION_FIELDS, errors, retention_location
    )
    if retention.get("mode") != "policy_ref":
        errors.append(f"{retention_location}.mode must be policy_ref")
    if not is_non_empty_string(retention.get("policy_ref")):
        errors.append(f"{retention_location}.policy_ref must be a non-empty string")

    denied_claims = set(
        require_string_list(
            document, "denied_claims", errors, relative, minimum=1, unique=True
        )
    )
    for claim in sorted(MANDATORY_RECORD_DENIED_CLAIMS - denied_claims):
        errors.append(f"{relative} missing mandatory denied claim: {claim}")


def validate_flow_dataflow(
    manifest_id: object,
    collections: dict[str, list[str]],
    documents: list[tuple[str, dict[str, Any]]],
    errors: list[str],
) -> None:
    sequence = collections["flow_sequence"]
    if not sequence:
        return
    blocks_by_id = {
        document["id"]: document
        for relative, document in documents
        if relative in collections["blocks"] and has_valid_id_format(document.get("id"))
    }
    if len(sequence) != len(blocks_by_id) or set(sequence) != set(blocks_by_id):
        errors.append(
            "manifest flow sequence must contain every manifest block exactly once"
        )
    declared_outputs = {
        output
        for block in blocks_by_id.values()
        if isinstance(block.get("outputs"), list)
        for output in block["outputs"]
        if is_non_empty_string(output)
    }
    entry_inputs = set(collections["flow_entry_inputs"])
    for shadowed in sorted(entry_inputs & declared_outputs):
        errors.append(f"manifest flow entry input shadows Block output: {shadowed}")
    available = entry_inputs - declared_outputs
    for block_id in sequence:
        block = blocks_by_id.get(block_id)
        if block is None:
            errors.append(f"manifest flow references unknown block: {block_id}")
            continue
        inputs = block.get("inputs")
        if isinstance(inputs, list):
            for input_name in inputs:
                if is_non_empty_string(input_name) and input_name not in available:
                    errors.append(
                        f"manifest flow block {block_id} has unavailable input: {input_name}"
                    )
        outputs = block.get("outputs")
        if isinstance(outputs, list):
            available.update(
                output for output in outputs if is_non_empty_string(output)
            )
    moc_ref = collections["flow_moc_ref"]
    if not moc_ref:
        return
    mocs_by_id = {
        document["id"]: document
        for relative, document in documents
        if relative in collections["mocs"] and has_valid_id_format(document.get("id"))
    }
    moc_id = moc_ref[0]
    moc = mocs_by_id.get(moc_id)
    if moc is None:
        errors.append(f"manifest flow references unknown MOC: {moc_id}")
        return
    expected_refs = [manifest_id, *sequence]
    if moc.get("refs") != expected_refs:
        errors.append(
            f"manifest flow MOC {moc_id} refs must equal manifest id followed by flow sequence"
        )


def validate_record_coverage(
    records_declared: bool,
    collections: dict[str, list[str]],
    documents: list[tuple[str, dict[str, Any]]],
    errors: list[str],
) -> None:
    if not records_declared:
        return
    block_outputs: list[str] = []
    record_artifacts: list[str] = []
    for relative, document in documents:
        if relative in collections["blocks"] and isinstance(
            document.get("outputs"), list
        ):
            block_outputs.extend(
                output
                for output in document["outputs"]
                if is_non_empty_string(output)
            )
        if relative in collections["records"] and is_non_empty_string(
            document.get("artifact")
        ):
            record_artifacts.append(document["artifact"])
    for artifact in sorted(
        artifact
        for artifact in set(record_artifacts)
        if record_artifacts.count(artifact) > 1
    ):
        errors.append(f"duplicate record artifact: {artifact}")
    if sorted(record_artifacts) != sorted(block_outputs) or len(record_artifacts) != len(
        set(record_artifacts)
    ):
        errors.append("manifest records must cover every Block output exactly once")


def scan_unreferenced_json_secrets(
    pack_dir: Path,
    pack_root: Path,
    already_scanned: set[str],
    errors: list[str],
) -> None:
    for path in sorted(pack_dir.rglob("*.json")):
        relative = path.relative_to(pack_dir).as_posix()
        if relative in already_scanned:
            continue
        try:
            resolved_path = path.resolve(strict=True)
            try:
                resolved_path.relative_to(pack_root)
            except ValueError:
                errors.append(f"unreferenced JSON path escapes pack root: {relative}")
                continue
            with resolved_path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            errors.extend(find_secret_keys(value, f"${relative}"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{relative}: {exc}")


def validate_pack(pack_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    manifest_path = pack_dir / "manifest.json"
    if not manifest_path.is_file():
        return {
            "status": "FAIL",
            "pack_id": None,
            "validated_files": 0,
            "errors": ["manifest.json is required"],
        }

    try:
        manifest = load_json(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "FAIL",
            "pack_id": None,
            "validated_files": 0,
            "errors": [str(exc)],
        }

    collections = validate_manifest(manifest, errors)
    referenced_paths = [
        *collections["blocks"],
        *collections["mocs"],
        *collections["records"],
    ]
    errors.extend(find_secret_keys(manifest))
    validated_files = 1
    documents: list[tuple[str, dict[str, Any]]] = []
    pack_root = pack_dir.resolve()
    for relative in referenced_paths:
        if not is_safe_relative_json_path(relative):
            errors.append(f"unsafe relative path: {relative}")
            continue
        path = pack_dir / relative
        if not path.is_file():
            errors.append(f"referenced file is missing: {relative}")
            continue
        try:
            resolved_path = path.resolve(strict=True)
            try:
                resolved_path.relative_to(pack_root)
            except ValueError:
                errors.append(f"referenced path escapes pack root: {relative}")
                continue
            document = load_json(resolved_path)
            errors.extend(find_secret_keys(document, f"${relative}"))
            documents.append((relative, document))
            validated_files += 1
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{relative}: {exc}")

    scan_unreferenced_json_secrets(
        pack_dir,
        pack_root,
        {"manifest.json", *referenced_paths},
        errors,
    )

    all_ids = [manifest.get("id"), *(document.get("id") for _, document in documents)]
    known_ids: set[str] = set()
    for document_id in all_ids:
        if not is_non_empty_string(document_id):
            continue
        if document_id in known_ids:
            errors.append(f"duplicate id: {document_id}")
        known_ids.add(document_id)
    for relative, document in documents:
        if relative in collections["blocks"]:
            validate_block(relative, document, errors)
        if relative in collections["mocs"]:
            validate_moc(relative, document, known_ids, errors)
        if relative in collections["records"]:
            validate_record(relative, document, errors)
    validate_flow_dataflow(manifest.get("id"), collections, documents, errors)
    validate_record_coverage("records" in manifest, collections, documents, errors)

    return {
        "status": "PASS" if not errors else "FAIL",
        "pack_id": manifest.get("id"),
        "validated_files": validated_files,
        "errors": errors,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: validate_template_pack.py PACK_DIRECTORY", file=sys.stderr)
        return 2
    summary = validate_pack(Path(argv[1]).resolve())
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
