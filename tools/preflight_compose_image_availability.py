#!/usr/bin/env python3
"""Observe a candidate's digest-pinned image locally without pulling or starting."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from safe_json_output import emit_json, output_target_available
from validate_resolved_compose_candidate import (
    canonical_sha256,
    load_strict_json_bytes,
    validate_candidate,
)


ROOT = Path(__file__).resolve().parents[1]
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
SAFE_RUNTIME_VALUE = re.compile(r"^[A-Za-z0-9._+-]{1,64}$")
FALSE_CLAIMS = {
    "image_pulled",
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


def claims() -> dict[str, bool]:
    values = {claim: False for claim in sorted(FALSE_CLAIMS)}
    values.update(
        {
            "daemon_reachable_verified": True,
            "local_image_available_verified": True,
            "manifest_digest_match_verified": True,
        }
    )
    return dict(sorted(values.items()))


def refusal(reason: str) -> dict[str, Any]:
    refusal_claims = {claim: False for claim in sorted(FALSE_CLAIMS)}
    refusal_claims.update(
        {
            "daemon_reachable_verified": False,
            "local_image_available_verified": False,
            "manifest_digest_match_verified": False,
        }
    )
    return {
        "kind": "compose_image_availability_preflight_refusal",
        "version": "1.0",
        "status": "REFUSED",
        "reason": reason,
        "claims": dict(sorted(refusal_claims.items())),
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def refuse(reason: str) -> int:
    print(json.dumps(refusal(reason), sort_keys=True))
    return 1


def run_docker(docker: str, arguments: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            [docker, *arguments],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def load_json_object(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def parse_image_rows(text: str) -> list[dict[str, Any]] | None:
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        row = load_json_object(line)
        if row is None:
            return None
        rows.append(row)
    return rows


def safe_runtime_value(value: object) -> str | None:
    if not isinstance(value, str) or SAFE_RUNTIME_VALUE.fullmatch(value) is None:
        return None
    return value


def snapshot_digest(snapshot: dict[str, Any]) -> str:
    value = dict(snapshot)
    value.pop("preflight_sha256", None)
    return canonical_sha256(value)


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 4) or (len(argv) == 4 and argv[2] != "--output"):
        print(
            "usage: preflight_compose_image_availability.py RESOLVED_CANDIDATE_JSON [--output NEW_JSON_FILE]",
            file=sys.stderr,
        )
        return 2
    candidate_path = Path(argv[1])
    output_path = Path(argv[3]) if len(argv) == 4 else None
    if not output_target_available(output_path):
        return refuse("OUTPUT_REFUSED")
    try:
        candidate_bytes = candidate_path.read_bytes()
        candidate = load_strict_json_bytes(candidate_bytes)
        candidate_errors = validate_candidate(candidate)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return refuse("CANDIDATE_REFUSED")
    if candidate_errors:
        return refuse("CANDIDATE_REFUSED")
    try:
        services = candidate["resolved"]["services"]
        expected_digest = services[0]["image_digest"]
        if services[1]["image_digest"] != expected_digest:
            return refuse("CANDIDATE_REFUSED")
    except (KeyError, IndexError, TypeError):
        return refuse("CANDIDATE_REFUSED")
    if not isinstance(expected_digest, str) or SHA256_PATTERN.fullmatch(expected_digest) is None:
        return refuse("CANDIDATE_REFUSED")

    docker = shutil.which("docker")
    if docker is None:
        return refuse("DOCKER_CLI_UNAVAILABLE")
    try:
        docker_cli_sha256 = hashlib.sha256(Path(docker).read_bytes()).hexdigest()
    except OSError:
        return refuse("DOCKER_CLI_UNAVAILABLE")

    info_result = run_docker(docker, ["info", "--format", "{{json .}}"])
    if info_result is None or info_result.returncode != 0:
        return refuse("DAEMON_UNAVAILABLE")
    info = load_json_object(info_result.stdout)
    if info is None:
        return refuse("DAEMON_OBSERVATION_REFUSED")
    daemon_id = info.get("ID")
    server_version = safe_runtime_value(info.get("ServerVersion"))
    os_type = safe_runtime_value(info.get("OSType"))
    architecture = safe_runtime_value(info.get("Architecture"))
    if not isinstance(daemon_id, str) or not daemon_id or None in (server_version, os_type, architecture):
        return refuse("DAEMON_OBSERVATION_REFUSED")

    list_result = run_docker(
        docker,
        ["image", "ls", "--digests", "--no-trunc", "--format", "{{json .}}"],
    )
    if list_result is None or list_result.returncode != 0:
        return refuse("IMAGE_LIST_REFUSED")
    rows = parse_image_rows(list_result.stdout)
    if rows is None:
        return refuse("IMAGE_LIST_REFUSED")
    matching_ids = sorted(
        {
            row.get("ID")
            for row in rows
            if row.get("Digest") == expected_digest
            and isinstance(row.get("ID"), str)
            and SHA256_PATTERN.fullmatch(row["ID"]) is not None
        }
    )
    if not matching_ids:
        return refuse("IMAGE_NOT_AVAILABLE")
    if len(matching_ids) != 1:
        return refuse("IMAGE_DIGEST_AMBIGUOUS")
    image_id = matching_ids[0]

    inspect_result = run_docker(
        docker,
        ["image", "inspect", "--format", "{{json .}}", image_id],
    )
    if inspect_result is None or inspect_result.returncode != 0:
        return refuse("IMAGE_INSPECT_REFUSED")
    inspected = load_json_object(inspect_result.stdout)
    if inspected is None or inspected.get("Id") != image_id:
        return refuse("IMAGE_INSPECT_REFUSED")
    repo_digests = inspected.get("RepoDigests")
    if not isinstance(repo_digests, list) or not any(
        isinstance(value, str) and value.endswith("@" + expected_digest)
        for value in repo_digests
    ):
        return refuse("IMAGE_DIGEST_MISMATCH")
    size = inspected.get("Size")
    image_os = safe_runtime_value(inspected.get("Os"))
    image_architecture = safe_runtime_value(inspected.get("Architecture"))
    rootfs = inspected.get("RootFS")
    layers = rootfs.get("Layers") if isinstance(rootfs, dict) else None
    if (
        not isinstance(size, int)
        or isinstance(size, bool)
        or size < 0
        or image_os is None
        or image_architecture is None
        or not isinstance(layers, list)
        or not layers
        or any(not isinstance(layer, str) or SHA256_PATTERN.fullmatch(layer) is None for layer in layers)
    ):
        return refuse("IMAGE_INSPECT_REFUSED")

    snapshot: dict[str, Any] = {
        "kind": "compose_image_availability_preflight",
        "version": "1.0",
        "status": "LOCAL_IMAGE_AVAILABLE",
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "candidate_binding": {
            "candidate_file_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
            "project_name": candidate["project_name"],
            "resolved_contract_sha256": candidate["resolved"]["resolved_contract_sha256"],
            "image_manifest_digest": expected_digest,
        },
        "host_binding": {
            "daemon_id_sha256": hashlib.sha256(
                b"kotodama-docker-daemon-v1\0" + daemon_id.encode("utf-8")
            ).hexdigest(),
            "docker_cli_sha256": docker_cli_sha256,
            "server_version": server_version,
            "os_type": os_type,
            "architecture": architecture,
            "raw_identity_emitted": False,
        },
        "image_observation": {
            "available_locally": True,
            "repo_digest_match_observed": True,
            "image_manifest_digest": expected_digest,
            "local_image_id_digest": image_id,
            "size_bytes": size,
            "os_type": image_os,
            "architecture": image_architecture,
            "rootfs_fingerprint_sha256": canonical_sha256(layers),
            "repository_names_emitted": False,
            "layer_digests_emitted": False,
        },
        "effects": {
            "daemon_info_query": True,
            "image_list_query": True,
            "image_inspect_query": True,
            "image_pull": False,
            "image_tag": False,
            "image_remove": False,
            "container_create": False,
            "container_start": False,
            "daemon_configuration_change": False,
        },
        "claims": claims(),
        "preflight_sha256": "",
        "public_beta": "NO_GO_UNPUBLISHED",
    }
    snapshot["preflight_sha256"] = snapshot_digest(snapshot)
    if not emit_json(snapshot, output_path):
        return refuse("OUTPUT_REFUSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
