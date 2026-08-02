#!/usr/bin/env python3
"""Create a validated working copy of the shipped Company starter."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

from validate_template_pack import ID_PATTERN, validate_pack


ROOT = Path(__file__).resolve().parents[1]
STARTER = ROOT / "examples" / "company-starter"


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def failure(pack_id: str, target: Path, message: str) -> dict[str, Any]:
    return {
        "status": "FAIL",
        "pack_id": pack_id,
        "target": str(target),
        "validated_files": 0,
        "rebound_mocs": 0,
        "draft_documents": 0,
        "errors": [message],
    }


def create_company_pack(pack_id: str, target: Path) -> dict[str, Any]:
    if ID_PATTERN.fullmatch(pack_id) is None:
        return failure(
            pack_id,
            target,
            "pack id must match ^[a-z0-9][a-z0-9-]{1,62}$",
        )

    try:
        source = STARTER.resolve(strict=True)
        parent = target.parent.resolve(strict=True)
        destination = parent / target.name
    except OSError as exc:
        return failure(pack_id, target, f"target parent is unavailable: {exc}")

    if not parent.is_dir():
        return failure(pack_id, target, "target parent must be an existing directory")
    if destination.exists() or destination.is_symlink():
        return failure(pack_id, target, "target already exists; no files were changed")
    if destination == source or source in destination.parents:
        return failure(pack_id, target, "target must be outside the shipped starter")

    source_validation = validate_pack(source)
    if source_validation["status"] != "PASS":
        return failure(pack_id, target, "shipped starter failed pre-copy validation")

    created_destination = False
    try:
        destination.mkdir()
        created_destination = True
        shutil.copytree(source, destination, dirs_exist_ok=True, symlinks=True)

        manifest_path = destination / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        source_id = manifest["id"]
        manifest["id"] = pack_id
        manifest["status"] = "draft"
        write_json(manifest_path, manifest)

        rebound_mocs = 0
        draft_documents = 1
        for collection in ("blocks", "mocs", "records"):
            for relative in manifest[collection]:
                document_path = destination / relative
                document = json.loads(document_path.read_text(encoding="utf-8"))
                document["status"] = "draft"
                if collection == "mocs":
                    refs = document.get("refs")
                    if isinstance(refs, list) and refs and refs[0] == source_id:
                        refs[0] = pack_id
                        rebound_mocs += 1
                write_json(document_path, document)
                draft_documents += 1

        validation = validate_pack(destination)
        if validation["status"] != "PASS":
            raise ValueError(
                "generated pack failed validation: " + "; ".join(validation["errors"])
            )

        return {
            "status": "PASS",
            "pack_id": pack_id,
            "target": str(target),
            "validated_files": validation["validated_files"],
            "rebound_mocs": rebound_mocs,
            "draft_documents": draft_documents,
            "errors": [],
        }
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        if created_destination and destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        return failure(pack_id, target, str(exc))


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            "usage: create_company_pack.py PACK_ID TARGET_DIRECTORY",
            file=sys.stderr,
        )
        return 2
    summary = create_company_pack(argv[1], Path(argv[2]))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
