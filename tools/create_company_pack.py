#!/usr/bin/env python3
"""Create a validated working copy of the shipped Company starter."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from check_company_pack_customization import REFERENCE_PLACEHOLDER, check_customization
from validate_template_pack import ID_PATTERN, SECRET_VALUE_PATTERNS, validate_pack


ROOT = Path(__file__).resolve().parents[1]
STARTER = ROOT / "examples" / "company-starter"
HUMAN_INTENT_LOCATOR_PATTERN = re.compile(
    r"^human-intent:[a-z0-9][a-z0-9._/-]{1,127}$"
)
RETENTION_POLICY_LOCATOR_PATTERN = re.compile(
    r"^retention-policy:[a-z0-9][a-z0-9._/-]{1,127}$"
)
MAX_AUTHORITY_WINDOW = timedelta(days=30)


@dataclass(frozen=True)
class StaticCustomization:
    human_intent_ref: str
    authority_expires_at: str
    retention_policy_ref: str


def validate_static_customization(
    customization: StaticCustomization,
    now: datetime | None = None,
) -> str | None:
    if (
        HUMAN_INTENT_LOCATOR_PATTERN.fullmatch(customization.human_intent_ref)
        is None
        or REFERENCE_PLACEHOLDER in customization.human_intent_ref
    ):
        return "HUMAN_INTENT_LOCATOR_INVALID"
    if (
        RETENTION_POLICY_LOCATOR_PATTERN.fullmatch(
            customization.retention_policy_ref
        )
        is None
        or REFERENCE_PLACEHOLDER in customization.retention_policy_ref
    ):
        return "RETENTION_POLICY_LOCATOR_INVALID"
    if any(
        pattern.search(locator)
        for locator in (
            customization.human_intent_ref,
            customization.retention_policy_ref,
        )
        for pattern in SECRET_VALUE_PATTERNS
    ):
        return "SECRET_LIKE_LOCATOR"

    try:
        expires_at = datetime.fromisoformat(
            customization.authority_expires_at.replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return "AUTHORITY_EXPIRY_INVALID"
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        return "AUTHORITY_EXPIRY_INVALID"

    evaluated_at = now or datetime.now(timezone.utc)
    expires_at = expires_at.astimezone(timezone.utc)
    evaluated_at = evaluated_at.astimezone(timezone.utc)
    if expires_at <= evaluated_at:
        return "AUTHORITY_EXPIRY_NOT_FUTURE"
    if expires_at - evaluated_at > MAX_AUTHORITY_WINDOW:
        return "AUTHORITY_EXPIRY_EXCEEDS_30_DAYS"
    return None


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def failure(pack_id: str, target: Path, message: str) -> dict[str, Any]:
    safe_pack_id = (
        pack_id
        if ID_PATTERN.fullmatch(pack_id) is not None
        and not any(pattern.search(pack_id) for pattern in SECRET_VALUE_PATTERNS)
        else None
    )
    return {
        "kind": "company_pack_creation_report",
        "version": "1.0",
        "status": "FAIL",
        "pack_id": safe_pack_id,
        "target": None,
        "validated_files": 0,
        "rebound_mocs": 0,
        "draft_documents": 0,
        "static_customizations_applied": 0,
        "customization_status": None,
        "claims": {
            "human_intent_authenticated": False,
            "human_approval_verified": False,
            "authority_assignment_verified": False,
            "retention_policy_verified": False,
            "promotion_verified": False,
            "current_truth_changed": False,
        },
        "public_beta": "NO_GO_UNPUBLISHED",
        "errors": [message],
    }


def create_company_pack(
    pack_id: str,
    target: Path,
    customization: StaticCustomization | None = None,
) -> dict[str, Any]:
    if ID_PATTERN.fullmatch(pack_id) is None:
        return failure(
            pack_id,
            target,
            "pack id must match ^[a-z0-9][a-z0-9-]{1,62}$",
        )
    if customization is not None:
        customization_error = validate_static_customization(customization)
        if customization_error is not None:
            return failure(
                pack_id,
                target,
                f"guided customization input refused: {customization_error}",
            )

    try:
        source = STARTER.resolve(strict=True)
        parent = target.parent.resolve(strict=True)
        destination = parent / target.name
    except OSError:
        return failure(pack_id, target, "target parent is unavailable")

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
        if customization is not None:
            manifest["human_intent_ref"] = customization.human_intent_ref
        write_json(manifest_path, manifest)

        rebound_mocs = 0
        draft_documents = 1
        static_customizations_applied = 1 if customization is not None else 0
        for collection in ("blocks", "mocs", "records"):
            for relative in manifest[collection]:
                document_path = destination / relative
                document = json.loads(document_path.read_text(encoding="utf-8"))
                document["status"] = "draft"
                if customization is not None and collection == "blocks":
                    document["authority"]["expires_at"] = (
                        customization.authority_expires_at
                    )
                    static_customizations_applied += 1
                if customization is not None and collection == "records":
                    document["retention"]["policy_ref"] = (
                        customization.retention_policy_ref
                    )
                    static_customizations_applied += 1
                if collection == "mocs":
                    refs = document.get("refs")
                    if isinstance(refs, list) and refs and refs[0] == source_id:
                        refs[0] = pack_id
                        rebound_mocs += 1
                write_json(document_path, document)
                draft_documents += 1

        validation = validate_pack(destination)
        if validation["status"] != "PASS":
            raise ValueError("generated pack failed validation")

        customization_report = check_customization(destination)
        expected_status = (
            "READY_FOR_GOVERNED_REVIEW"
            if customization is not None
            else "CUSTOMIZATION_REQUIRED"
        )
        if customization_report["status"] != expected_status:
            raise ValueError("generated pack failed customization post-check")

        return {
            "kind": "company_pack_creation_report",
            "version": "1.0",
            "status": "PASS",
            "pack_id": pack_id,
            "target": str(target),
            "validated_files": validation["validated_files"],
            "rebound_mocs": rebound_mocs,
            "draft_documents": draft_documents,
            "static_customizations_applied": static_customizations_applied,
            "customization_status": customization_report["status"],
            "claims": {
                "human_intent_authenticated": False,
                "human_approval_verified": False,
                "authority_assignment_verified": False,
                "retention_policy_verified": False,
                "promotion_verified": False,
                "current_truth_changed": False,
            },
            "public_beta": "NO_GO_UNPUBLISHED",
            "errors": [],
        }
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        if created_destination and destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        return failure(pack_id, target, "pack generation failed safely")


def write_stdout_utf8(value: str) -> None:
    encoded = (value + "\n").encode("utf-8")
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(encoded)
        buffer.flush()
    else:
        sys.stdout.write(encoded.decode("utf-8"))
        sys.stdout.flush()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="create_company_pack.py",
        description="Create a validated working copy of the Company starter.",
    )
    parser.add_argument("pack_id", metavar="PACK_ID")
    parser.add_argument("target", metavar="TARGET_DIRECTORY", type=Path)
    parser.add_argument("--human-intent-ref")
    parser.add_argument("--authority-expires-at")
    parser.add_argument("--retention-policy-ref")
    return parser.parse_args(argv[1:])


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    supplied = (
        args.human_intent_ref,
        args.authority_expires_at,
        args.retention_policy_ref,
    )
    if any(value is not None for value in supplied) and not all(
        value is not None for value in supplied
    ):
        print(
            "create_company_pack.py: error: guided customization options "
            "must be supplied together",
            file=sys.stderr,
        )
        return 2
    customization = (
        StaticCustomization(*supplied)
        if all(value is not None for value in supplied)
        else None
    )
    summary = create_company_pack(args.pack_id, args.target, customization)
    write_stdout_utf8(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
