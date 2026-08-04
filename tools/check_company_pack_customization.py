#!/usr/bin/env python3
"""Report static Company pack customization work without granting authority."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from validate_template_pack import emit_help_if_requested, validate_pack


STARTER_PACK_ID = "kotodama-company-starter"
REFERENCE_PLACEHOLDER = "replace-with-governed-reference"
EXPIRY_PLACEHOLDER = "2099-01-01T00:00:00Z"


def checklist_item(
    item_id: str, category: str, path: str, reason: str
) -> dict[str, str]:
    return {
        "id": item_id,
        "category": category,
        "path": path,
        "reason": reason,
    }


def empty_claims() -> dict[str, bool]:
    return {
        "human_intent_authenticated": False,
        "human_approval_verified": False,
        "authority_assignment_verified": False,
        "retention_policy_verified": False,
        "promotion_verified": False,
        "current_truth_changed": False,
    }


def invalid_report(validation: dict[str, Any]) -> dict[str, Any]:
    reported_pack_id = validation.get("pack_id")
    if not isinstance(reported_pack_id, str) or not reported_pack_id:
        reported_pack_id = None
    safe_validation = {**validation, "pack_id": reported_pack_id}
    return {
        "kind": "company_pack_customization_report",
        "version": "1.0",
        "status": "INVALID_PACK",
        "pack_id": reported_pack_id,
        "structural_validation": safe_validation,
        "counts": {
            "replacement_required": 0,
            "review_required": 0,
            "evidence_required": 0,
        },
        "items": [],
        "claims": empty_claims(),
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def check_customization(pack_dir: Path) -> dict[str, Any]:
    pack_dir = pack_dir.resolve()
    validation = validate_pack(pack_dir)
    if validation["status"] != "PASS":
        return invalid_report(validation)

    manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    documents: list[tuple[str, dict[str, Any]]] = []
    for collection in ("blocks", "mocs", "records"):
        for relative in manifest.get(collection, []):
            document = json.loads((pack_dir / relative).read_text(encoding="utf-8"))
            documents.append((relative, document))

    items: list[dict[str, str]] = []
    if manifest.get("id") == STARTER_PACK_ID:
        items.append(
            checklist_item(
                "replace-starter-pack-id",
                "replacement_required",
                "manifest.json#/id",
                "replace the shipped starter ID with an organization-specific pack ID",
            )
        )

    status_documents = [("manifest.json", manifest), *documents]
    for relative, document in status_documents:
        if document.get("status") == "example":
            items.append(
                checklist_item(
                    f"set-working-status:{relative}",
                    "replacement_required",
                    f"{relative}#/status",
                    "change example to an honest working status such as draft or candidate_only",
                )
            )

    human_intent_ref = manifest.get("human_intent_ref")
    if isinstance(human_intent_ref, str) and REFERENCE_PLACEHOLDER in human_intent_ref:
        items.append(
            checklist_item(
                "replace-human-intent-reference",
                "replacement_required",
                "manifest.json#/human_intent_ref",
                "replace the placeholder with a governed Human Intent locator",
            )
        )

    block_paths = set(manifest.get("blocks", []))
    record_paths = set(manifest.get("records", []))
    for relative, document in documents:
        if relative in block_paths:
            authority = document.get("authority", {})
            if authority.get("expires_at") == EXPIRY_PLACEHOLDER:
                items.append(
                    checklist_item(
                        f"replace-expiry:{relative}",
                        "replacement_required",
                        f"{relative}#/authority/expires_at",
                        "replace the example expiry with a bounded working window",
                    )
                )
        if relative in record_paths:
            retention = document.get("retention", {})
            policy_ref = retention.get("policy_ref")
            if isinstance(policy_ref, str) and REFERENCE_PLACEHOLDER in policy_ref:
                items.append(
                    checklist_item(
                        f"replace-retention-policy:{relative}",
                        "replacement_required",
                        f"{relative}#/retention/policy_ref",
                        "replace the placeholder with a governed retention policy locator",
                    )
                )

    for owner_family in sorted(manifest.get("canonical_owners", {})):
        items.append(
            checklist_item(
                f"review-canonical-owner:{owner_family}",
                "review_required",
                f"manifest.json#/canonical_owners/{owner_family}",
                "confirm this fact family has exactly one accepted canonical owner",
            )
        )
    for index, _profile in enumerate(manifest.get("profiles", [])):
        items.append(
            checklist_item(
                f"review-runtime-profile:{index}",
                "review_required",
                f"manifest.json#/profiles/{index}",
                "confirm the selected profile matches the intended deployment boundary",
            )
        )
    for relative, document in documents:
        if relative in block_paths:
            items.append(
                checklist_item(
                    f"review-block-owner-role:{relative}",
                    "review_required",
                    f"{relative}#/authority/owner_role",
                    "confirm the role exists and has authority for this Block",
                )
            )
        if relative in record_paths:
            items.extend(
                [
                    checklist_item(
                        f"review-record-owner:{relative}",
                        "review_required",
                        f"{relative}#/canonical_owner",
                        "confirm the Record fact family has one accepted canonical owner",
                    ),
                    checklist_item(
                        f"review-record-creator-role:{relative}",
                        "review_required",
                        f"{relative}#/authority/creator_role",
                        "confirm the creator role exists and is assigned",
                    ),
                    checklist_item(
                        f"review-record-verifier-role:{relative}",
                        "review_required",
                        f"{relative}#/authority/verifier_role",
                        "confirm the verifier role exists, is assigned, and meets independence rules",
                    ),
                ]
            )

    evidence_requirements = [
        (
            "evidence-human-intent-authenticity",
            "manifest.json#/human_intent_ref",
            "static checking cannot authenticate the referenced Human Intent",
        ),
        (
            "evidence-canonical-owner-acceptance",
            "manifest.json#/canonical_owners",
            "static checking cannot prove owner acceptance or authority",
        ),
        (
            "evidence-role-assignment-independence",
            "manifest.json#/blocks",
            "static checking cannot prove real role assignment or person independence",
        ),
        (
            "evidence-retention-policy",
            "manifest.json#/records",
            "static checking cannot prove retention policy existence or enforcement",
        ),
        (
            "evidence-candidate-bound-human-decision",
            "manifest.json",
            "placeholder replacement is not Human approval, Promotion, or Current Truth",
        ),
    ]
    for item_id, path, reason in evidence_requirements:
        items.append(checklist_item(item_id, "evidence_required", path, reason))

    counts = {
        category: sum(item["category"] == category for item in items)
        for category in (
            "replacement_required",
            "review_required",
            "evidence_required",
        )
    }
    return {
        "kind": "company_pack_customization_report",
        "version": "1.0",
        "status": (
            "CUSTOMIZATION_REQUIRED"
            if counts["replacement_required"]
            else "READY_FOR_GOVERNED_REVIEW"
        ),
        "pack_id": manifest["id"],
        "structural_validation": validation,
        "counts": counts,
        "items": items,
        "claims": empty_claims(),
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def main(argv: list[str]) -> int:
    if emit_help_if_requested(
        argv,
        usage="usage: check_company_pack_customization.py PACK_DIRECTORY",
        purpose=(
            "Inspect Company Pack customization without changing its files."
        ),
    ):
        return 0
    if len(argv) != 2:
        print(
            "usage: check_company_pack_customization.py PACK_DIRECTORY",
            file=sys.stderr,
        )
        return 2
    report = check_customization(Path(argv[1]))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "READY_FOR_GOVERNED_REVIEW" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
