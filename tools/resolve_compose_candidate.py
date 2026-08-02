#!/usr/bin/env python3
"""Resolve the shipped Compose skeleton into a credential-free candidate."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from safe_json_output import emit_json, output_target_available
from validate_compose_minimum_skeleton import load_strict_json, validate_manifest
from validate_resolved_compose_candidate import (
    EXPECTED_SERVICE_BASE,
    PROJECT_PATTERN,
    canonical_sha256,
    false_claims,
    shipped_source,
    validate_candidate,
)


ROOT = Path(__file__).resolve().parents[1]
SKELETON_ROOT = ROOT / "runtime" / "compose-minimum"
COMPOSE_FILE = SKELETON_ROOT / "compose.yaml"
IMAGE_PATTERN = re.compile(r"^[^@\s]+@(sha256:[0-9a-f]{64})$")
EXPECTED_SERVICE_IDS = ["company-db", "evidence-store"]
EXPECTED_NETWORK_IDS = ["company-data", "evidence-data"]
EXPECTED_VOLUME_IDS = ["company-db-data", "evidence-store-data"]
EXPECTED_DATABASES = {
    "company-db": ("kotodama_company", "kotodama_company_owner"),
    "evidence-store": ("kotodama_evidence", "kotodama_evidence_owner"),
}


def refusal(reason: str) -> dict[str, Any]:
    return {
        "kind": "resolved_compose_candidate_refusal",
        "version": "1.0",
        "status": "REFUSED",
        "reason": reason,
        "claims": false_claims(),
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def refuse(reason: str) -> int:
    print(json.dumps(refusal(reason), sort_keys=True))
    return 1


def exact_keys(value: object, expected: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == expected


def validate_resolved_config(
    resolved: dict[str, Any],
    project_name: str,
    image_reference: str,
    company_secret: str,
    evidence_secret: str,
) -> bool:
    if resolved.get("name") != project_name:
        return False
    services = resolved.get("services")
    networks = resolved.get("networks")
    volumes = resolved.get("volumes")
    if not exact_keys(services, set(EXPECTED_SERVICE_IDS)):
        return False
    if not exact_keys(networks, set(EXPECTED_NETWORK_IDS)):
        return False
    if not exact_keys(volumes, set(EXPECTED_VOLUME_IDS)):
        return False
    if any(networks[item].get("internal") is not True for item in EXPECTED_NETWORK_IDS):
        return False
    expected_secrets = {
        "company-db": company_secret,
        "evidence-store": evidence_secret,
    }
    for service_id in EXPECTED_SERVICE_IDS:
        service = services[service_id]
        expected = EXPECTED_SERVICE_BASE[service_id]
        database, owner = EXPECTED_DATABASES[service_id]
        if service.get("image") != image_reference or service.get("pull_policy") != "never":
            return False
        if "ports" in service or service.get("restart") != "no":
            return False
        if set(service.get("networks", {})) != {expected["network"]}:
            return False
        environment = service.get("environment")
        if not isinstance(environment, dict):
            return False
        if environment.get("POSTGRES_DB") != database or environment.get("POSTGRES_USER") != owner:
            return False
        if environment.get("POSTGRES_PASSWORD") != expected_secrets[service_id]:
            return False
        healthcheck = service.get("healthcheck")
        if not isinstance(healthcheck, dict) or healthcheck.get("test") != ["CMD-SHELL", expected["healthcheck"]]:
            return False
        if service.get("security_opt") != ["no-new-privileges:true"]:
            return False
        service_volumes = service.get("volumes")
        if not isinstance(service_volumes, list) or len(service_volumes) != 2:
            return False
        data = [item for item in service_volumes if item.get("target") == "/var/lib/postgresql/data"]
        migration_target = "/docker-entrypoint-initdb.d/" + Path(expected["migration"]).name
        migration = [item for item in service_volumes if item.get("target") == migration_target]
        if len(data) != 1 or data[0].get("type") != "volume" or data[0].get("source") != expected["volume"]:
            return False
        if len(migration) != 1 or migration[0].get("type") != "bind" or migration[0].get("read_only") is not True:
            return False
        try:
            migration_source = Path(migration[0]["source"]).resolve(strict=True)
        except (KeyError, OSError, TypeError, ValueError):
            return False
        if migration_source != (SKELETON_ROOT / expected["migration"]).resolve():
            return False
    return True


def build_candidate(project_name: str, image_digest: str) -> dict[str, Any]:
    source = shipped_source()
    binding_hashes = {item["path"]: item["sha256"] for item in source["bindings"]}
    services = []
    for service_id in EXPECTED_SERVICE_IDS:
        expected = EXPECTED_SERVICE_BASE[service_id]
        services.append(
            {
                "id": service_id,
                "role": expected["role"],
                "image_digest": image_digest,
                "network": expected["network"],
                "volume": expected["volume"],
                "migration": expected["migration"],
                "migration_sha256": binding_hashes[expected["migration"]],
                "healthcheck_sha256": hashlib.sha256(expected["healthcheck"].encode("utf-8")).hexdigest(),
            }
        )
    networks = [
        {"id": "company-data", "internal": True},
        {"id": "evidence-data", "internal": True},
    ]
    safe_projection = {
        "project_name": project_name,
        "networks": networks,
        "services": services,
    }
    return {
        "kind": "resolved_compose_candidate",
        "version": "1.0",
        "status": "CANDIDATE_READY_FOR_RUNTIME_PREFLIGHT",
        "project_name": project_name,
        "source": source,
        "resolved": {
            "credential_contract": {
                "source": "process_environment",
                "both_present_observed": True,
                "distinct_values_observed": True,
                "values_emitted": False,
                "password_derived_digest": False,
            },
            "networks": networks,
            "services": services,
            "resolved_contract_sha256": canonical_sha256(safe_projection),
        },
        "claims": false_claims(),
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def main(argv: list[str]) -> int:
    if (
        len(argv) not in (2, 4)
        or PROJECT_PATTERN.fullmatch(argv[1]) is None
        or (len(argv) == 4 and argv[2] != "--output")
    ):
        print("usage: resolve_compose_candidate.py SAFE_PROJECT_NAME [--output NEW_JSON_FILE]", file=sys.stderr)
        return 2
    project_name = argv[1]
    output_path = Path(argv[3]) if len(argv) == 4 else None
    if not output_target_available(output_path):
        return refuse("OUTPUT_REFUSED")
    image_reference = os.environ.get("KOTODAMA_POSTGRES_IMAGE", "")
    company_secret = os.environ.get("KOTODAMA_COMPANY_DB_PASSWORD", "")
    evidence_secret = os.environ.get("KOTODAMA_EVIDENCE_DB_PASSWORD", "")
    if not company_secret or not evidence_secret:
        return refuse("RESOLUTION_REFUSED")
    if company_secret == evidence_secret:
        return refuse("CREDENTIAL_CONTRACT_REFUSED")
    image_match = IMAGE_PATTERN.fullmatch(image_reference)
    if image_match is None:
        return refuse("IMAGE_NOT_DIGEST_PINNED")
    try:
        manifest = load_strict_json(SKELETON_ROOT / "skeleton.json")
        skeleton_errors, _ = validate_manifest(SKELETON_ROOT, manifest)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return refuse("SHIPPED_SKELETON_REFUSED")
    if skeleton_errors:
        return refuse("SHIPPED_SKELETON_REFUSED")
    docker = shutil.which("docker")
    if docker is None:
        return refuse("COMPOSE_CLI_UNAVAILABLE")
    try:
        process = subprocess.run(
            [
                docker,
                "compose",
                "--project-name",
                project_name,
                "--file",
                str(COMPOSE_FILE),
                "config",
                "--format",
                "json",
            ],
            cwd=ROOT,
            env=os.environ.copy(),
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return refuse("RESOLUTION_REFUSED")
    if process.returncode != 0:
        return refuse("RESOLUTION_REFUSED")
    try:
        resolved = json.loads(process.stdout)
    except (json.JSONDecodeError, TypeError, ValueError):
        return refuse("RESOLVED_CONTRACT_REFUSED")
    if not isinstance(resolved, dict) or not validate_resolved_config(
        resolved,
        project_name,
        image_reference,
        company_secret,
        evidence_secret,
    ):
        return refuse("RESOLVED_CONTRACT_REFUSED")
    candidate = build_candidate(project_name, image_match.group(1))
    if validate_candidate(candidate):
        return refuse("CANDIDATE_SELF_VALIDATION_REFUSED")
    if not emit_json(candidate, output_path):
        return refuse("OUTPUT_REFUSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
