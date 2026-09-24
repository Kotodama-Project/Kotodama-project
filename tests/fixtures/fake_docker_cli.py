#!/usr/bin/env python3
"""Public-seam Docker CLI fixture for read-only preflight tests."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


MANIFEST_DIGEST = "sha256:" + "0" * 64
IMAGE_ID = "sha256:" + "1" * 64
SECOND_IMAGE_ID = "sha256:" + "2" * 64
PRIVATE_REPOSITORY = "private.invalid/internal/postgres"


def record(argv: list[str]) -> None:
    path = os.environ.get("KOTODAMA_FAKE_DOCKER_LOG")
    if path:
        with Path(path).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(argv) + "\n")


def compose_config(argv: list[str]) -> int:
    project_name = argv[argv.index("--project-name") + 1]
    root = Path.cwd() / "runtime" / "compose-minimum"
    image = os.environ["KOTODAMA_POSTGRES_IMAGE"]
    contracts = {
        "company-db": {
            "database": "kotodama_company",
            "owner": "kotodama_company_owner",
            "password": os.environ["KOTODAMA_COMPANY_DB_PASSWORD"],
            "network": "company-data",
            "volume": "company-db-data",
            "migration": "company-db/001-company-core.sql",
            "health": "pg_isready -U kotodama_company_owner -d kotodama_company",
        },
        "evidence-store": {
            "database": "kotodama_evidence",
            "owner": "kotodama_evidence_owner",
            "password": os.environ["KOTODAMA_EVIDENCE_DB_PASSWORD"],
            "network": "evidence-data",
            "volume": "evidence-store-data",
            "migration": "evidence-store/001-evidence-core.sql",
            "health": "pg_isready -U kotodama_evidence_owner -d kotodama_evidence",
        },
    }
    services = {}
    for service_id, contract in contracts.items():
        migration_name = Path(contract["migration"]).name
        services[service_id] = {
            "environment": {
                "POSTGRES_DB": contract["database"],
                "POSTGRES_USER": contract["owner"],
                "POSTGRES_" "PASSWORD": contract["password"],
            },
            "healthcheck": {"test": ["CMD-SHELL", contract["health"]]},
            "image": image,
            "networks": {contract["network"]: None},
            "pull_policy": "never",
            "restart": "no",
            "security_opt": ["no-new-privileges:true"],
            "volumes": [
                {
                    "type": "volume",
                    "source": contract["volume"],
                    "target": "/var/lib/postgresql/data",
                },
                {
                    "type": "bind",
                    "source": str((root / contract["migration"]).resolve()),
                    "target": "/docker-entrypoint-initdb.d/" + migration_name,
                    "read_only": True,
                },
            ],
        }
    print(
        json.dumps(
            {
                "name": project_name,
                "services": services,
                "networks": {
                    "company-data": {"internal": True},
                    "evidence-data": {"internal": True},
                },
                "volumes": {"company-db-data": {}, "evidence-store-data": {}},
            }
        )
    )
    return 0


def docker_info(mode: str) -> int:
    if mode == "daemon-unavailable":
        print("private-daemon-error-must-not-leak", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "ID": "FAKE-PRIVATE-DAEMON-ID-R14",
                "ServerVersion": "29.6.1",
                "OSType": "linux",
                "Architecture": "x86_64",
                "Name": "private-hostname-must-not-leak",
            }
        )
    )
    return 0


def image_list(mode: str) -> int:
    if mode == "image-absent":
        return 0
    digest = MANIFEST_DIGEST if mode != "digest-mismatch" else "sha256:" + "9" * 64
    print(
        json.dumps(
            {
                "Repository": PRIVATE_REPOSITORY,
                "Tag": "private-tag-must-not-leak",
                "Digest": digest,
                "ID": IMAGE_ID,
            }
        )
    )
    if mode == "ambiguous-image":
        print(
            json.dumps(
                {
                    "Repository": PRIVATE_REPOSITORY + "-second",
                    "Tag": "second-private-tag",
                    "Digest": MANIFEST_DIGEST,
                    "ID": SECOND_IMAGE_ID,
                }
            )
        )
    return 0


def image_inspect(argv: list[str], mode: str) -> int:
    if mode == "inspect-failure":
        print("private-inspect-error-must-not-leak", file=sys.stderr)
        return 1
    image_id = argv[-1]
    repo_digest = MANIFEST_DIGEST if mode != "inspect-digest-mismatch" else "sha256:" + "8" * 64
    print(
        json.dumps(
            {
                "Id": image_id,
                "RepoDigests": [PRIVATE_REPOSITORY + "@" + repo_digest],
                "Size": 123456789,
                "Os": "linux",
                "Architecture": "amd64",
                "RootFS": {
                    "Type": "layers",
                    "Layers": ["sha256:" + "3" * 64, "sha256:" + "4" * 64],
                },
            }
        )
    )
    return 0


def main(argv: list[str]) -> int:
    args = argv[1:]
    record(args)
    mode = os.environ.get("KOTODAMA_FAKE_DOCKER_MODE", "success")
    if args and args[0] == "compose":
        return compose_config(args)
    if args[:2] == ["info", "--format"]:
        return docker_info(mode)
    if args[:2] == ["image", "ls"]:
        return image_list(mode)
    if args[:2] == ["image", "inspect"]:
        return image_inspect(args, mode)
    print("unexpected fake Docker command", file=sys.stderr)
    return 64


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
