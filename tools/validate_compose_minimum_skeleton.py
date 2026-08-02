#!/usr/bin/env python3
"""Validate the exact, secret-free Compose minimum data-plane skeleton."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any


TOP_FIELDS = {
    "kind",
    "spec_version",
    "id",
    "status",
    "profile",
    "scope",
    "security",
    "services",
    "bindings",
    "claims",
    "public_beta",
}
SECURITY_FIELDS = {
    "host_ports_forbidden",
    "networks_internal_and_separate",
    "volumes_separate",
    "image_reference",
    "image_pull",
    "database_passwords",
    "application_login_roles",
    "large_evidence_bytes_backend",
}
SERVICE_FIELDS = {
    "id",
    "role",
    "network",
    "volume",
    "migration",
    "owner_role",
    "reader_role",
    "writer_role",
    "host_ports",
    "external_network",
}
BINDING_FIELDS = {"path", "sha256", "bytes"}
CLAIM_FIELDS = {
    "clean_install_verified",
    "services_started",
    "migrations_applied",
    "health_verified",
    "restart_verified",
    "backup_verified",
    "restore_verified",
    "application_least_privilege_verified",
    "promotion_verified",
    "current_truth_changed",
    "final_human_go",
    "public_beta_go",
}
EXPECTED_SECURITY = {
    "host_ports_forbidden": True,
    "networks_internal_and_separate": True,
    "volumes_separate": True,
    "image_reference": "required_digest_environment",
    "image_pull": "never",
    "database_passwords": "required_private_environment",
    "application_login_roles": "not_included",
    "large_evidence_bytes_backend": "not_included",
}
EXPECTED_SERVICES = {
    "company-db": {
        "role": "company_db",
        "network": "company-data",
        "volume": "company-db-data",
        "migration": "company-db/001-company-core.sql",
        "owner_role": "kotodama_company_owner",
        "reader_role": "kotodama_company_reader",
        "writer_role": "kotodama_company_writer",
    },
    "evidence-store": {
        "role": "evidence_metadata_store",
        "network": "evidence-data",
        "volume": "evidence-store-data",
        "migration": "evidence-store/001-evidence-core.sql",
        "owner_role": "kotodama_evidence_owner",
        "reader_role": "kotodama_evidence_reader",
        "writer_role": "kotodama_evidence_writer",
    },
}
CORE_SQL_TABLES = {
    "company-db/001-company-core.sql": (
        "company.schema_migration",
        "company.record",
        "company.event",
        "company.link",
    ),
    "evidence-store/001-evidence-core.sql": (
        "evidence.schema_migration",
        "evidence.object",
        "evidence.receipt",
        "evidence.receipt_object",
    ),
}
EXPECTED_BOUND_FILES = {
    "README.md",
    "compose.yaml",
    *CORE_SQL_TABLES.keys(),
}
CANONICAL_BINDINGS = {
    "README.md": (
        "753f170fe2f7d633d8fe7dbfba356a4a1410c0ce6e0cb6efe271b8767fd7c441",
        3270,
    ),
    "company-db/001-company-core.sql": (
        "be610d52832aa23d0cae31414a4734360302dd6b0b4ae8f70153985866ee611f",
        2075,
    ),
    "compose.yaml": (
        "da234d23055a6a37be03bb219b8557bba24fdfbc4b1e4908f4637fcaaf431920",
        2087,
    ),
    "evidence-store/001-evidence-core.sql": (
        "0131802552db4f02010448c11d3cd3e06f8a47ee4f106751a8261cc3e892d80d",
        2067,
    ),
}
SAFE_PATH_PATTERN = re.compile(r"^[A-Za-z0-9._/-]+$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SECRET_VALUE_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/", re.I),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
REQUIRED_IMAGE = (
    'image: "${KOTODAMA_POSTGRES_IMAGE:?set a digest-pinned PostgreSQL image reference}"'
)
REQUIRED_PASSWORDS = {
    "company-db": (
        'POSTGRES_PASSWORD: "${KOTODAMA_COMPANY_DB_PASSWORD:?set in private environment}"'
    ),
    "evidence-store": (
        'POSTGRES_PASSWORD: "${KOTODAMA_EVIDENCE_DB_PASSWORD:?set in private environment}"'
    ),
}
REQUIRED_MIGRATION_MOUNTS = {
    "company-db": "./company-db/001-company-core.sql:/docker-entrypoint-initdb.d/001-company-core.sql:ro",
    "evidence-store": "./evidence-store/001-evidence-core.sql:/docker-entrypoint-initdb.d/001-evidence-core.sql:ro",
}
REQUIRED_HEALTHCHECKS = {
    "company-db": "pg_isready -U kotodama_company_owner -d kotodama_company",
    "evidence-store": "pg_isready -U kotodama_evidence_owner -d kotodama_evidence",
}


class StrictJsonError(ValueError):
    """Raised for ambiguous or non-standard JSON."""


def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StrictJsonError("duplicate key")
        result[key] = value
    return result


def reject_non_finite(_value: str) -> None:
    raise StrictJsonError("non-finite number")


def load_strict_json(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_pairs,
        parse_constant=reject_non_finite,
    )
    if not isinstance(value, dict):
        raise StrictJsonError("top-level value must be an object")
    return value


def require_fields(
    value: dict[str, Any], required: set[str], location: str, errors: list[str]
) -> None:
    for field in sorted(required - value.keys()):
        errors.append(f"{location} missing required field: {field}")


def reject_unknown(
    value: dict[str, Any], allowed: set[str], location: str, errors: list[str]
) -> None:
    for field in sorted(value.keys() - allowed):
        errors.append(f"{location} contains unknown field: {field}")


def safe_relative_path(value: object) -> bool:
    if not isinstance(value, str) or SAFE_PATH_PATTERN.fullmatch(value) is None:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and "" not in path.parts


def validate_security(manifest: dict[str, Any], errors: list[str]) -> None:
    security = manifest.get("security")
    if not isinstance(security, dict):
        errors.append("skeleton field security must be an object")
        return
    require_fields(security, SECURITY_FIELDS, "security", errors)
    reject_unknown(security, SECURITY_FIELDS, "security", errors)
    for field, expected in EXPECTED_SECURITY.items():
        if security.get(field) != expected:
            errors.append(f"security.{field} does not match the safe skeleton contract")


def validate_services(manifest: dict[str, Any], errors: list[str]) -> None:
    services = manifest.get("services")
    if not isinstance(services, list):
        errors.append("skeleton field services must be an array")
        return
    if len(services) != 2:
        errors.append("services must contain exactly company-db and evidence-store")
    valid_services = [item for item in services if isinstance(item, dict)]
    if len(valid_services) != len(services):
        errors.append("services must contain only objects")
    ids = [item.get("id") for item in valid_services]
    if ids != ["company-db", "evidence-store"]:
        errors.append("services must use the required order: company-db, evidence-store")
    for service in valid_services:
        service_id = service.get("id")
        location = f"service {service_id}" if isinstance(service_id, str) else "service"
        require_fields(service, SERVICE_FIELDS, location, errors)
        reject_unknown(service, SERVICE_FIELDS, location, errors)
        expected = EXPECTED_SERVICES.get(service_id)
        if expected is None:
            errors.append(f"{location} is not allowed")
            continue
        for field, expected_value in expected.items():
            if service.get(field) != expected_value:
                errors.append(f"{location}.{field} does not match the contract")
        if service.get("host_ports") is not False:
            errors.append(f"{location}.host_ports must remain false")
        if service.get("external_network") is not False:
            errors.append(f"{location}.external_network must remain false")
    networks = [service.get("network") for service in valid_services]
    volumes = [service.get("volume") for service in valid_services]
    if len(networks) != len(set(networks)):
        errors.append("service networks must be distinct")
    if len(volumes) != len(set(volumes)):
        errors.append("service volumes must be distinct")


def enumerate_files(root: Path, errors: list[str]) -> set[str]:
    found: set[str] = set()
    resolved_root = root.resolve()
    try:
        candidates = list(root.rglob("*"))
    except OSError:
        errors.append("skeleton directory could not be enumerated")
        return found
    for path in candidates:
        try:
            if not path.is_file():
                continue
            resolved = path.resolve()
            resolved.relative_to(resolved_root)
            relative = path.relative_to(root).as_posix()
            found.add(relative)
        except (OSError, ValueError):
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                relative = "unknown"
            errors.append(f"referenced path escapes skeleton root: {relative}")
    return found


def validate_bindings(
    root: Path, manifest: dict[str, Any], errors: list[str]
) -> dict[str, bytes]:
    bound_bytes: dict[str, bytes] = {}
    bindings = manifest.get("bindings")
    if not isinstance(bindings, list):
        errors.append("skeleton field bindings must be an array")
        return bound_bytes
    paths: list[str] = []
    for index, binding in enumerate(bindings):
        location = f"binding[{index}]"
        if not isinstance(binding, dict):
            errors.append(f"{location} must be an object")
            continue
        require_fields(binding, BINDING_FIELDS, location, errors)
        reject_unknown(binding, BINDING_FIELDS, location, errors)
        relative = binding.get("path")
        if not safe_relative_path(relative):
            errors.append(f"{location}.path must be a safe relative path")
            continue
        paths.append(relative)
        sha256 = binding.get("sha256")
        byte_count = binding.get("bytes")
        if not isinstance(sha256, str) or SHA256_PATTERN.fullmatch(sha256) is None:
            errors.append(f"{location}.sha256 must be lowercase SHA-256")
        if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count < 0:
            errors.append(f"{location}.bytes must be a non-negative integer")
        path = root / Path(*PurePosixPath(relative).parts)
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root.resolve())
            content = path.read_bytes()
        except (OSError, ValueError):
            errors.append(f"bound file unavailable or unsafe: {relative}")
            continue
        bound_bytes[relative] = content
        if (
            hashlib.sha256(content).hexdigest() != sha256
            or len(content) != byte_count
        ):
            errors.append(f"binding mismatch: {relative}")
        canonical = CANONICAL_BINDINGS.get(relative)
        if canonical is None or (sha256, byte_count) != canonical:
            errors.append(f"binding is not the shipped skeleton revision: {relative}")
    if len(paths) != len(set(paths)):
        errors.append("binding paths must be unique")
    if paths != sorted(paths):
        errors.append("bindings must be sorted by path")
    if set(paths) != EXPECTED_BOUND_FILES:
        for missing in sorted(EXPECTED_BOUND_FILES - set(paths)):
            errors.append(f"missing binding: {missing}")
        for unexpected in sorted(set(paths) - EXPECTED_BOUND_FILES):
            errors.append(f"unexpected binding: {unexpected}")
    actual_files = enumerate_files(root, errors)
    allowed_files = set(paths) | {"skeleton.json"}
    for extra in sorted(actual_files - allowed_files):
        errors.append(f"unbound file: {extra}")
    return bound_bytes


def compose_service_ids(compose: str) -> list[str]:
    lines = compose.splitlines()
    try:
        start = lines.index("services:") + 1
        end = lines.index("networks:")
    except ValueError:
        return []
    ids: list[str] = []
    for line in lines[start:end]:
        match = re.fullmatch(r"  ([a-z0-9-]+):", line)
        if match:
            ids.append(match.group(1))
    return ids


def compose_service_block(compose: str, service_id: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(service_id)}:\s*$\n(.*?)(?=^  [a-z0-9-]+:\s*$|^networks:\s*$)",
        compose,
    )
    return match.group(1) if match else ""


def validate_compose(content: bytes | None, errors: list[str]) -> None:
    if content is None:
        return
    try:
        compose = content.decode("utf-8")
    except UnicodeDecodeError:
        errors.append("compose.yaml must be UTF-8")
        return
    if "#" in compose:
        errors.append("compose comments are forbidden in the canonical skeleton")
    if compose_service_ids(compose) != ["company-db", "evidence-store"]:
        errors.append("compose services must be exactly company-db and evidence-store")
    company_block = compose_service_block(compose, "company-db")
    evidence_block = compose_service_block(compose, "evidence-store")
    service_blocks = {
        "company-db": company_block,
        "evidence-store": evidence_block,
    }
    expected_network_lines = {
        "company-db": "company-data",
        "evidence-store": "evidence-data",
    }
    expected_volume_prefixes = {
        "company-db": "company-db-data:/var/lib/postgresql/data",
        "evidence-store": "evidence-store-data:/var/lib/postgresql/data",
    }
    network_binding_valid = True
    volume_binding_valid = True
    for service_id, block in (
        ("company-db", company_block),
        ("evidence-store", evidence_block),
    ):
        network = expected_network_lines[service_id]
        volume = expected_volume_prefixes[service_id]
        if re.search(rf"(?m)^\s+- {re.escape(network)}\s*$", block) is None:
            network_binding_valid = False
        if re.search(rf"(?m)^\s+- {re.escape(volume)}\s*$", block) is None:
            volume_binding_valid = False
    if not network_binding_valid:
        errors.append("compose service networks must be distinct and role bound")
    if not volume_binding_valid:
        errors.append("compose service volumes must be distinct and role bound")
    if len(re.findall(r"(?m)^\s+ports:\s*$", compose)) > 0:
        errors.append("compose host port publication is forbidden")
    image_lines = re.findall(r"(?m)^\s+image:\s*.+$", compose)
    if len(image_lines) != 2 or any(REQUIRED_IMAGE not in line for line in image_lines):
        errors.append("compose images must use the required digest-pinned environment reference")
    if len(re.findall(r"(?m)^\s+pull_policy:\s+never\s*$", compose)) != 2:
        errors.append("compose pull_policy must remain never for both services")
    if len(re.findall(r"(?m)^\s+internal:\s+true\s*$", compose)) != 2:
        errors.append("compose networks must both remain internal")
    password_binding_valid = True
    migration_binding_valid = True
    healthcheck_binding_valid = True
    for service_id, required in REQUIRED_PASSWORDS.items():
        block = service_blocks[service_id]
        password_lines = re.findall(r"(?m)^\s+POSTGRES_PASSWORD:\s*.*$", block)
        if len(password_lines) != 1 or password_lines[0].strip() != required:
            password_binding_valid = False
            errors.append(
                f"compose {service_id} POSTGRES_PASSWORD must use its required private environment reference"
            )
        migration_lines = re.findall(
            r"(?m)^\s+-\s+\./[^\s:]+:/docker-entrypoint-initdb\.d/[^\s:]+:[a-z]+\s*$",
            block,
        )
        if (
            len(migration_lines) != 1
            or migration_lines[0].strip()
            != "- " + REQUIRED_MIGRATION_MOUNTS[service_id]
        ):
            migration_binding_valid = False
        healthcheck_lines = re.findall(r"(?m)^\s+test:\s*.*$", block)
        expected_healthcheck = (
            'test: ["CMD-SHELL", "'
            + REQUIRED_HEALTHCHECKS[service_id]
            + '"]'
        )
        if (
            len(healthcheck_lines) != 1
            or healthcheck_lines[0].strip() != expected_healthcheck
        ):
            healthcheck_binding_valid = False
    if not password_binding_valid:
        errors.append("compose database password references must be role bound")
    if not migration_binding_valid:
        errors.append("compose migrations must be role bound and read-only")
    if not healthcheck_binding_valid:
        errors.append("compose healthchecks must be role bound")
    for pattern in SECRET_VALUE_PATTERNS:
        if pattern.search(compose):
            errors.append("compose contains a secret-like value")
            break


def validate_sql(relative: str, content: bytes | None, errors: list[str]) -> None:
    if content is None:
        return
    label = "company-db" if relative.startswith("company-db/") else "evidence-store"
    try:
        sql = content.decode("utf-8")
    except UnicodeDecodeError:
        errors.append(f"{label} SQL must be UTF-8")
        return
    if re.search(r"(?m)^\s*--|/\*|\*/", sql):
        errors.append(f"{label} SQL comments are forbidden")
    if not sql.startswith("BEGIN;") or not sql.rstrip().endswith("COMMIT;"):
        errors.append(f"{label} SQL must be transaction bounded")
    if len(re.findall(r"(?im)^\s*CREATE ROLE\s+\S+\s+NOLOGIN;", sql)) != 2:
        errors.append(f"{label} SQL must define NOLOGIN roles")
    for table in CORE_SQL_TABLES[relative]:
        if re.search(
            rf"(?im)^\s*CREATE\s+TABLE\s+{re.escape(table)}\s*\(", sql
        ) is None:
            errors.append(f"{label} SQL missing core table: {table}")
    if re.search(r"(?im)^\s*(DROP|TRUNCATE)\s+", sql):
        errors.append(f"{label} SQL contains a destructive statement")
    if re.search(r"(?i)PASSWORD\s+['\"]", sql):
        errors.append(f"{label} SQL contains a password literal")
    if relative.startswith("company-db/") and re.search(
        r"(?i)promoted|current_truth", sql
    ):
        errors.append("company-db SQL cannot define Promotion or Current Truth state")
    for pattern in SECRET_VALUE_PATTERNS:
        if pattern.search(sql):
            errors.append(f"{label} SQL contains a secret-like value")
            break


def validate_manifest(root: Path, manifest: dict[str, Any]) -> tuple[list[str], int]:
    errors: list[str] = []
    require_fields(manifest, TOP_FIELDS, "skeleton", errors)
    reject_unknown(manifest, TOP_FIELDS, "skeleton", errors)
    if manifest.get("kind") != "compose_minimum_skeleton":
        errors.append("kind must be compose_minimum_skeleton")
    if manifest.get("spec_version") != "0.1":
        errors.append("spec_version must be 0.1")
    if manifest.get("id") != "kotodama-compose-data-plane":
        errors.append("id must be kotodama-compose-data-plane")
    if manifest.get("status") != "example":
        errors.append("status must remain example")
    if manifest.get("profile") != "compose_minimum":
        errors.append("profile must be compose_minimum")
    if manifest.get("scope") != "company_db_and_evidence_metadata_only":
        errors.append("scope must remain company_db_and_evidence_metadata_only")
    validate_security(manifest, errors)
    validate_services(manifest, errors)
    contents = validate_bindings(root, manifest, errors)
    validate_compose(contents.get("compose.yaml"), errors)
    for relative in CORE_SQL_TABLES:
        validate_sql(relative, contents.get(relative), errors)
    claims = manifest.get("claims")
    if not isinstance(claims, dict):
        errors.append("skeleton field claims must be an object")
    else:
        require_fields(claims, CLAIM_FIELDS, "claims", errors)
        reject_unknown(claims, CLAIM_FIELDS, "claims", errors)
        for claim in sorted(CLAIM_FIELDS):
            if claims.get(claim) is not False:
                errors.append(f"claim {claim} must remain false")
    if manifest.get("public_beta") != "NO_GO_UNPUBLISHED":
        errors.append("public_beta must remain NO_GO_UNPUBLISHED")
    return sorted(set(errors)), len(contents)


def false_claims() -> dict[str, bool]:
    return {claim: False for claim in sorted(CLAIM_FIELDS)}


def report(
    manifest: dict[str, Any] | None, errors: list[str], validated_files: int
) -> dict[str, Any]:
    skeleton_id = manifest.get("id") if isinstance(manifest, dict) else None
    if skeleton_id != "kotodama-compose-data-plane":
        skeleton_id = None
    return {
        "kind": "compose_minimum_skeleton_validation",
        "version": "1.0",
        "status": "FAIL" if errors else "PASS",
        "skeleton_id": skeleton_id,
        "validated_files": validated_files,
        "errors": errors,
        "claims": false_claims(),
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: validate_compose_minimum_skeleton.py SKELETON_DIRECTORY", file=sys.stderr)
        return 2
    root = Path(argv[1])
    try:
        manifest = load_strict_json(root / "skeleton.json")
    except (OSError, UnicodeError, json.JSONDecodeError, StrictJsonError, ValueError):
        print(json.dumps(report(None, ["skeleton JSON is invalid"], 0), sort_keys=True))
        return 1
    errors, validated_files = validate_manifest(root, manifest)
    print(json.dumps(report(manifest, errors, validated_files), sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
