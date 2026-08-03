#!/usr/bin/env python3
"""Emit a deterministic, read-only inventory of a Kotodama Company Pack."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from validate_template_pack import validate_pack


CLAIMS = {
    "catalog_is_authoritative": False,
    "human_approval_verified": False,
    "runtime_verified": False,
    "promotion_verified": False,
    "current_truth_changed": False,
}


class SafeArgumentParser(argparse.ArgumentParser):
    """Reject malformed CLI input without reflecting the untrusted value."""

    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: invalid command-line arguments\n")


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    return value


def empty_catalog(validation: dict[str, Any]) -> dict[str, Any]:
    errors = validation.get("errors", [])
    error_count = len(errors) if isinstance(errors, list) else 1
    validated_files = validation.get("validated_files", 0)
    if not isinstance(validated_files, int) or validated_files < 0:
        validated_files = 0
    return {
        "kind": "company_pack_catalog",
        "version": "1.0",
        "status": "INVALID_PACK",
        "pack_id": None,
        "profiles": [],
        "counts": {
            "blocks": 0,
            "records": 0,
            "mocs": 0,
            "validated_files": validated_files,
        },
        "validation": {
            "structural_status": "FAIL",
            "validated_files": validated_files,
            "error_count": error_count,
        },
        "flow": [],
        "blocks": [],
        "records": [],
        "mocs": [],
        "claims": dict(CLAIMS),
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def build_catalog(pack_directory: Path) -> dict[str, Any]:
    validation = validate_pack(pack_directory)
    if validation.get("status") != "PASS":
        return empty_catalog(validation)

    manifest = read_json(pack_directory / "manifest.json")
    block_documents = {
        relative: read_json(pack_directory / relative)
        for relative in manifest["blocks"]
    }
    record_documents = {
        relative: read_json(pack_directory / relative)
        for relative in manifest["records"]
    }
    moc_documents = {
        relative: read_json(pack_directory / relative)
        for relative in manifest["mocs"]
    }
    blocks_by_id = {
        document["id"]: (relative, document)
        for relative, document in block_documents.items()
    }
    sequence = manifest["flow"]["sequence"]
    positions = {block_id: index for index, block_id in enumerate(sequence, start=1)}
    positions[manifest["id"]] = 1

    flow: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    for position, block_id in enumerate(sequence, start=1):
        relative, block = blocks_by_id[block_id]
        outputs = list(block["outputs"])
        flow.append(
            {
                "position": position,
                "block_id": block_id,
                "purpose": block["purpose"],
                "inputs": list(block["inputs"]),
                "outputs": outputs,
                "record_artifacts": outputs,
            }
        )
        blocks.append(
            {
                "position": position,
                "id": block_id,
                "path": relative.replace("\\", "/"),
                "purpose": block["purpose"],
                "inputs": list(block["inputs"]),
                "outputs": outputs,
                "record_artifacts": outputs,
                "owner_role": block["authority"]["owner_role"],
                "allowed_actions": list(block["authority"]["allowed_actions"]),
                "denied_actions": list(block["authority"]["denied_actions"]),
                "receipt_required": block["verification"]["receipt_required"],
            }
        )

    records = []
    for relative, record in record_documents.items():
        records.append(
            {
                "id": record["id"],
                "path": relative.replace("\\", "/"),
                "artifact": record["artifact"],
                "purpose": record["purpose"],
                "canonical_owner": record["canonical_owner"],
                "creator_role": record["authority"]["creator_role"],
                "verifier_role": record["authority"]["verifier_role"],
                "promotion_required_for_current_truth": record["authority"][
                    "promotion_required_for_current_truth"
                ],
                "retention_policy_ref": record["retention"]["policy_ref"],
            }
        )

    primary_moc_id = manifest["flow"]["moc_ref"]
    mocs = []
    for relative, moc in moc_documents.items():
        refs = list(moc["refs"])
        flow_positions: list[int] = []
        for ref in refs:
            if ref not in positions:
                continue
            position = positions[ref]
            if position not in flow_positions:
                flow_positions.append(position)
        mocs.append(
            {
                "id": moc["id"],
                "path": relative.replace("\\", "/"),
                "title": moc["title"],
                "authority": moc["authority"],
                "projection": (
                    "flow_sequence"
                    if moc["id"] == primary_moc_id
                    else moc.get("projection", "flow_subsequence")
                ),
                "refs": refs,
                "flow_positions": flow_positions,
            }
        )

    validated_files = validation["validated_files"]
    return {
        "kind": "company_pack_catalog",
        "version": "1.0",
        "status": "PASS",
        "pack_id": manifest["id"],
        "profiles": list(manifest["profiles"]),
        "counts": {
            "blocks": len(blocks),
            "records": len(records),
            "mocs": len(mocs),
            "validated_files": validated_files,
        },
        "validation": {
            "structural_status": "PASS",
            "validated_files": validated_files,
            "error_count": 0,
        },
        "flow": flow,
        "blocks": blocks,
        "records": records,
        "mocs": mocs,
        "claims": dict(CLAIMS),
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def render_markdown(catalog: dict[str, Any]) -> str:
    lines = [
        "# Company Pack Catalog",
        "",
        f"- Pack: {catalog['pack_id'] or 'unknown'}",
        f"- Status: {catalog['status']}",
        f"- Blocks: {catalog['counts']['blocks']}",
        f"- Records: {catalog['counts']['records']}",
        f"- MOCs: {catalog['counts']['mocs']}",
        f"- Validated files: {catalog['counts']['validated_files']}",
        "",
    ]
    if catalog["status"] == "INVALID_PACK":
        lines.extend(
            [
                "現在地: structural validation failed; the catalog is intentionally empty.",
                f"Validation errors: {catalog['validation']['error_count']}",
                "",
                "This output does not echo manifest values or private locator details.",
                "Public Beta: NO_GO_UNPUBLISHED",
            ]
        )
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "## Flow",
            "",
            "| Position | Block | Purpose | Record artifacts |",
            "| ---: | --- | --- | --- |",
        ]
    )
    for entry in catalog["flow"]:
        artifacts = ", ".join(entry["record_artifacts"])
        lines.append(
            f"| {entry['position']} | {entry['block_id']} | "
            f"{entry['purpose']} | {artifacts} |"
        )
    lines.extend(
        [
            "",
            "## MOCs",
            "",
            "| MOC | Projection | Flow positions |",
            "| --- | --- | --- |",
        ]
    )
    for entry in catalog["mocs"]:
        positions = ", ".join(str(position) for position in entry["flow_positions"])
        lines.append(
            f"| {entry['title']} ({entry['id']}) | "
            f"{entry['projection']} | {positions} |"
        )
    lines.extend(
        [
            "",
            "現在地: this is a read-only navigation projection for choosing Blocks, "
            "Records, and MOCs.",
            "Human approval, Capability Grant, runtime verification, Promotion, "
            "and Current Truth are not asserted.",
            "Human approval is required before any governed activation or publication.",
            "Public Beta: NO_GO_UNPUBLISHED",
        ]
    )
    return "\n".join(lines) + "\n"


def write_stdout_utf8(value: str) -> None:
    data = value.encode("utf-8")
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(value)
    else:
        buffer.write(data)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = SafeArgumentParser(
        description="Print a deterministic read-only Company Pack catalog."
    )
    parser.add_argument("pack_directory", type=Path)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    return parser.parse_args(argv[1:])


def main(argv: list[str]) -> int:
    arguments = parse_args(argv)
    catalog = build_catalog(arguments.pack_directory.resolve())
    if arguments.format == "markdown":
        write_stdout_utf8(render_markdown(catalog))
    else:
        write_stdout_utf8(
            json.dumps(catalog, ensure_ascii=False, sort_keys=True) + "\n"
        )
    return 0 if catalog["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
