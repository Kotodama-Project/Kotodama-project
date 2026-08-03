#!/usr/bin/env python3
"""Run a deterministic, read-only self-check for a public Company Pack preview."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from catalog_company_pack import build_catalog
from check_company_pack_customization import check_customization
from validate_template_pack import validate_pack


CLAIMS = {
    "human_approval_verified": False,
    "runtime_verified": False,
    "promotion_verified": False,
    "current_truth_changed": False,
    "public_beta_go": False,
}
CATALOG_CLAIMS = {
    "catalog_is_authoritative": False,
    "human_approval_verified": False,
    "runtime_verified": False,
    "promotion_verified": False,
    "current_truth_changed": False,
}
CUSTOMIZATION_CLAIM_KEYS = {
    "human_intent_authenticated",
    "human_approval_verified",
    "authority_assignment_verified",
    "retention_policy_verified",
    "promotion_verified",
    "current_truth_changed",
}
CHECK_IDS = (
    "pack_structure",
    "catalog_projection",
    "customization_boundary",
    "claim_boundary",
)
OUTPUT_FORMATS = {"json", "markdown"}
REFUSAL_REASONS = {
    "INPUT_NOT_DIRECTORY",
    "INVALID_PACK",
    "INTERNAL_CONTRACT_REFUSAL",
}


def zero_counts() -> dict[str, int]:
    return {
        "validated_files": 0,
        "blocks": 0,
        "records": 0,
        "mocs": 0,
        "replacement_required": 0,
        "review_required": 0,
        "evidence_required": 0,
    }


def report(
    status: str,
    counts: dict[str, int] | None = None,
    check_status: str = "REFUSED",
    refusal_reason: str | None = None,
) -> dict[str, Any]:
    if refusal_reason is not None and refusal_reason not in REFUSAL_REASONS:
        raise ValueError("unsupported refusal reason")
    return {
        "kind": "company_pack_public_preview_check",
        "version": "1.0",
        "status": status,
        "counts": counts or zero_counts(),
        "checks": [{"id": check_id, "status": check_status} for check_id in CHECK_IDS],
        "refusal_reason": refusal_reason,
        "claims": dict(CLAIMS),
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def non_negative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def build_check(pack_directory: Path) -> dict[str, Any]:
    try:
        if not pack_directory.is_dir():
            return report("REFUSED", refusal_reason="INPUT_NOT_DIRECTORY")
        validation = validate_pack(pack_directory)
        if validation.get("status") != "PASS":
            return report("REFUSED", refusal_reason="INVALID_PACK")

        catalog = build_catalog(pack_directory)
        customization = check_customization(pack_directory)
        if catalog.get("status") != "PASS":
            return report("REFUSED", refusal_reason="INTERNAL_CONTRACT_REFUSAL")
        if customization.get("status") not in {
            "CUSTOMIZATION_REQUIRED",
            "READY_FOR_GOVERNED_REVIEW",
        }:
            return report("REFUSED", refusal_reason="INTERNAL_CONTRACT_REFUSAL")

        catalog_counts = catalog.get("counts", {})
        customization_counts = customization.get("counts", {})
        values = {
            "validated_files": catalog_counts.get("validated_files"),
            "blocks": catalog_counts.get("blocks"),
            "records": catalog_counts.get("records"),
            "mocs": catalog_counts.get("mocs"),
            "replacement_required": customization_counts.get("replacement_required"),
            "review_required": customization_counts.get("review_required"),
            "evidence_required": customization_counts.get("evidence_required"),
        }
        counts: dict[str, int] = {}
        for key, value in values.items():
            normalized = non_negative_int(value)
            if normalized is None:
                return report("REFUSED", refusal_reason="INTERNAL_CONTRACT_REFUSAL")
            counts[key] = normalized

        customization_claims = customization.get("claims")
        claims_are_false = (
            isinstance(customization_claims, dict)
            and set(customization_claims) == CUSTOMIZATION_CLAIM_KEYS
            and not any(customization_claims.values())
        )

        catalog_validation = catalog.get("validation", {})
        if (
            counts["validated_files"] == 0
            or counts["blocks"] == 0
            or counts["records"] == 0
            or counts["mocs"] == 0
            or catalog_validation.get("structural_status") != "PASS"
            or len(catalog.get("flow", [])) != counts["blocks"]
            or len(catalog.get("blocks", [])) != counts["blocks"]
            or len(catalog.get("records", [])) != counts["records"]
            or len(catalog.get("mocs", [])) != counts["mocs"]
            or catalog.get("claims") != CATALOG_CLAIMS
            or catalog.get("public_beta") != "NO_GO_UNPUBLISHED"
            or not claims_are_false
            or customization.get("public_beta") != "NO_GO_UNPUBLISHED"
        ):
            return report("REFUSED", refusal_reason="INTERNAL_CONTRACT_REFUSAL")

        return report("PASS", counts=counts, check_status="PASS")
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, json.JSONDecodeError, RecursionError):
        return report("REFUSED", refusal_reason="INTERNAL_CONTRACT_REFUSAL")


def write_stdout(value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n"
    data = payload.encode("utf-8")
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(payload)
    else:
        buffer.write(data)
        buffer.flush()


def render_markdown(value: dict[str, Any]) -> str:
    """Render the fixed report as a human-readable, path-free summary."""
    lines = [
        "# Company Pack Public Preview self-check",
        "",
        f"- Status: `{value['status']}`",
        f"- Public Beta: `{value['public_beta']}`",
        f"- Refusal reason: `{value['refusal_reason'] or 'none'}`",
        "",
        "## Counts",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key in (
        "validated_files",
        "blocks",
        "records",
        "mocs",
        "replacement_required",
        "review_required",
        "evidence_required",
    ):
        lines.append(f"| `{key}` | {value['counts'][key]} |")

    lines.extend(["", "## Checks", "", "| Check | Status |", "| --- | --- |"])
    for check in value["checks"]:
        lines.append(f"| `{check['id']}` | `{check['status']}` |")

    lines.extend(["", "## Claims", "", "| Claim | Verified |", "| --- | --- |"])
    for key, claim in value["claims"].items():
        lines.append(f"| `{key}` | `{str(claim).lower()}` |")

    lines.extend(
        [
            "",
            "This is a deterministic, read-only summary. It does not authenticate",
            "Human approval, verify runtime/provider/deployment state, promote a",
            "candidate, or change Current Truth. Public Beta remains NO_GO_UNPUBLISHED.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_invocation(argv: list[str]) -> tuple[str, str] | None:
    if len(argv) == 2:
        return argv[1], "json"
    if len(argv) == 4 and argv[2] == "--format" and argv[3] in OUTPUT_FORMATS:
        return argv[1], argv[3]
    return None


def main(argv: list[str]) -> int:
    invocation = parse_invocation(argv)
    if invocation is None:
        print(
            "usage: check_company_pack_public_preview.py PACK_DIRECTORY [--format json|markdown]",
            file=sys.stderr,
        )
        return 2
    pack_directory, output_format = invocation
    result = build_check(Path(pack_directory).resolve())
    if output_format == "markdown":
        payload = render_markdown(result).encode("utf-8")
        buffer = getattr(sys.stdout, "buffer", None)
        if buffer is None:
            sys.stdout.write(payload.decode("utf-8"))
        else:
            buffer.write(payload)
            buffer.flush()
    else:
        write_stdout(result)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
