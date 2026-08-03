#!/usr/bin/env python3
"""Turn the static Company pack checklist into a concise, non-authorizing plan."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from check_company_pack_customization import check_customization


ItemMatcher = Callable[[dict[str, str]], bool]


GROUP_DEFINITIONS: tuple[
    tuple[str, str, str, str, ItemMatcher], ...
] = (
    (
        "pack_identity_and_status",
        "replacement_required",
        "Pack identity and working status",
        "use an organization-specific ID and honest draft/candidate status",
        lambda item: item["id"] == "replace-starter-pack-id"
        or item["id"].startswith("set-working-status:"),
    ),
    (
        "human_intent_locator",
        "replacement_required",
        "Human Intent locator",
        "point to governed Human Intent without copying its body or secrets",
        lambda item: item["id"] == "replace-human-intent-reference",
    ),
    (
        "block_authority_windows",
        "replacement_required",
        "Block authority windows",
        "replace example expiry values with bounded working windows",
        lambda item: item["id"].startswith("replace-expiry:"),
    ),
    (
        "record_retention_policies",
        "replacement_required",
        "Governed Record retention policies",
        "point each Record contract to a governed retention policy",
        lambda item: item["id"].startswith("replace-retention-policy:"),
    ),
    (
        "other_static_customization",
        "replacement_required",
        "Other static customization",
        "close any new static placeholder category reported by the checker",
        lambda item: item["category"] == "replacement_required",
    ),
    (
        "canonical_owner_review",
        "review_required",
        "Canonical owner review",
        "confirm one accepted owner for each fact family",
        lambda item: item["id"].startswith("review-canonical-owner:"),
    ),
    (
        "runtime_profile_review",
        "review_required",
        "Runtime profile review",
        "confirm the profile matches the intended deployment boundary",
        lambda item: item["id"].startswith("review-runtime-profile:"),
    ),
    (
        "block_owner_role_review",
        "review_required",
        "Block owner role review",
        "confirm each Block owner role exists and has bounded authority",
        lambda item: item["id"].startswith("review-block-owner-role:"),
    ),
    (
        "record_authority_review",
        "review_required",
        "Governed Record authority review",
        "confirm Record owners and independent creator/verifier roles",
        lambda item: item["id"].startswith("review-record-"),
    ),
    (
        "other_governed_review",
        "review_required",
        "Other governed review",
        "review any new authority question reported by the checker",
        lambda item: item["category"] == "review_required",
    ),
    (
        "external_evidence",
        "evidence_required",
        "External evidence",
        "collect candidate-bound Human, authority, retention, and separation evidence",
        lambda item: item["category"] == "evidence_required",
    ),
)


IDEAL_FLOW = (
    (
        "create_draft_copy",
        "organization-specific draft Pack",
        "copying and rebinding do not adopt the Pack",
    ),
    (
        "replace_static_placeholders",
        "static organization fields completed",
        "text replacement does not prove authority",
    ),
    (
        "validate_candidate",
        "schema and cross-file contract PASS",
        "static PASS does not prove runtime behavior",
    ),
    (
        "bind_exact_review_candidate",
        "candidate bound by digest and byte size for the current validated file set",
        "binding does not equal approval",
    ),
    (
        "governed_review",
        "owner, profile, and role decisions recorded",
        "review must be performed under real organizational authority",
    ),
    (
        "collect_external_evidence",
        "candidate-bound evidence gaps closed",
        "this local planner cannot authenticate external evidence",
    ),
    (
        "separate_promotion",
        "approved candidate may enter a separate Promotion process",
        "the Pack and this planner never change Current Truth",
    ),
)


def build_groups(items: list[dict[str, str]]) -> list[dict[str, Any]]:
    counts = {definition[0]: 0 for definition in GROUP_DEFINITIONS}
    for item in items:
        for group_id, category, _label, _purpose, matcher in GROUP_DEFINITIONS:
            if item["category"] == category and matcher(item):
                counts[group_id] += 1
                break

    groups: list[dict[str, Any]] = []
    for group_id, category, label, purpose, _matcher in GROUP_DEFINITIONS:
        count = counts[group_id]
        groups.append(
            {
                "id": group_id,
                "category": category,
                "label": label,
                "purpose": purpose,
                "count": count,
                "state": "COMPLETE" if count == 0 else "ACTION_REQUIRED",
            }
        )
    return groups


def build_plan(pack_dir: Path) -> dict[str, Any]:
    report = check_customization(pack_dir)
    counts = report["counts"]
    validation = report["structural_validation"]
    if report["status"] == "INVALID_PACK":
        stage = "STRUCTURAL_REPAIR"
        recommended_next = {
            "action": "FIX_STRUCTURE",
            "command": "python tools/validate_template_pack.py PACK_DIRECTORY",
            "rationale": "repair structural errors before interpreting customization work",
        }
    elif counts["replacement_required"]:
        stage = "STATIC_CUSTOMIZATION"
        recommended_next = {
            "action": "REPLACE_STATIC_PLACEHOLDERS",
            "command": "python tools/check_company_pack_customization.py PACK_DIRECTORY",
            "rationale": "replace the grouped static fields, then rerun the source checklist",
        }
    else:
        stage = "CANDIDATE_BINDING"
        recommended_next = {
            "action": "BUILD_EXACT_REVIEW_BUNDLE",
            "command": "python tools/build_company_pack_review_bundle.py PACK_DIRECTORY",
            "rationale": (
                "bind the review-ready "
                f"{validation['validated_files']}-file Pack before governed review"
            ),
        }

    return {
        "kind": "company_pack_next_steps_plan",
        "version": "1.0",
        "status": report["status"],
        "pack_id": (
            None if report["status"] == "INVALID_PACK" else report["pack_id"]
        ),
        "current_state": {
            "stage": stage,
            "structural_status": validation["status"],
            "validated_files": validation["validated_files"],
            "counts": counts,
        },
        "ideal_flow": [
            {
                "id": step_id,
                "outcome": outcome,
                "authority_boundary": authority_boundary,
            }
            for step_id, outcome, authority_boundary in IDEAL_FLOW
        ],
        "groups": build_groups(report["items"]),
        "recommended_next": recommended_next,
        "claims": report["claims"],
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def render_markdown(plan: dict[str, Any]) -> str:
    pack_id = plan["pack_id"] if plan["pack_id"] is not None else "unknown"
    counts = plan["current_state"]["counts"]
    lines = [
        "# Company Pack Next Steps",
        "",
        f"- Pack: `{pack_id}`",
        f"- 現在地: `{plan['current_state']['stage']}`",
        f"- Checker status: `{plan['status']}`",
        f"- Structural validation: `{plan['current_state']['structural_status']}`",
        "",
        "## 現在の内訳",
        "",
        "| Group | Category | Count | State |",
        "|---|---|---:|---|",
    ]
    for group in plan["groups"]:
        if group["count"]:
            lines.append(
                f"| {group['label']} | `{group['category']}` | "
                f"{group['count']} | `{group['state']}` |"
            )
    if not sum(counts.values()):
        lines.append("| No open checklist items | - | 0 | `COMPLETE` |")

    next_step = plan["recommended_next"]
    lines.extend(
        [
            "",
            "## 次にすること",
            "",
            f"`{next_step['action']}`: {next_step['rationale']}。",
            "",
            "```text",
            next_step["command"],
            "```",
            "",
            "## 理想の流れ",
            "",
        ]
    )
    for index, step in enumerate(plan["ideal_flow"], start=1):
        lines.append(
            f"{index}. `{step['id']}` - {step['outcome']}。"
            f" Boundary: {step['authority_boundary']}。"
        )

    lines.extend(
        [
            "",
            "## 境界",
            "",
            "このplanは静的checkerの集約です。Human approval、authority assignment、",
            "external evidence、Promotion、Current Truth、runtime readinessを証明しません。",
            f"Public Betaは `{plan['public_beta']}` のままです。",
            "",
        ]
    )
    return "\n".join(lines)


class SafeArgumentParser(argparse.ArgumentParser):
    """Reject malformed CLI input without reflecting the untrusted value."""

    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: invalid command-line arguments\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = SafeArgumentParser(
        description="Summarize Company Pack current state, ideal flow, and next action."
    )
    parser.add_argument("pack_directory", type=Path)
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        dest="output_format",
    )
    return parser.parse_args(argv)


def write_stdout_utf8(value: str) -> None:
    encoded = value.encode("utf-8")
    binary_stdout = getattr(sys.stdout, "buffer", None)
    if binary_stdout is not None:
        binary_stdout.write(encoded)
        binary_stdout.flush()
        return
    sys.stdout.write(value)


def main(argv: list[str] | None = None) -> int:
    arguments = parse_args(argv)
    plan = build_plan(arguments.pack_directory)
    if arguments.output_format == "markdown":
        output = render_markdown(plan)
    else:
        output = json.dumps(plan, ensure_ascii=False, sort_keys=True) + "\n"
    write_stdout_utf8(output)
    return 1 if plan["status"] == "INVALID_PACK" else 0


if __name__ == "__main__":
    raise SystemExit(main())
