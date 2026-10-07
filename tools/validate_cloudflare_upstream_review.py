#!/usr/bin/env python3
"""Check a fixed upstream reader packet without treating it as an approval."""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import subprocess

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "runtime/cloudflare-os/upstream-drift-review.json"
SCHEMA = ROOT / "schemas/cloudflare-os-upstream-drift-review.schema.json"
BASE = "bf7f762d7fa73553284d731ab6a978d3ea17be24"
TARGET = "1cb5e3d9096589e38f3fcfaf3f2191aa95a4c592"


class ReviewViolation(ValueError):
    """The packet cannot support its declared coverage or fixed inventory."""


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ReviewViolation("duplicate JSON field")
        value[key] = item
    return value


def load_packet(path: Path = PACKET) -> dict:
    with path.open("rb") as stream:
        raw = stream.read(256 * 1024 + 1)
    if len(raw) > 256 * 1024:
        raise ReviewViolation("packet byte bound exceeded")
    return json.loads(raw, object_pairs_hook=unique_object)


def validate_packet(packet: dict) -> dict:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    if next(Draft202012Validator(schema).iter_errors(packet), None) is not None:
        raise ReviewViolation("packet schema mismatch")
    summary, rows = packet["summary"], packet["files"]
    paths = [row["path"] for row in rows]
    if paths != sorted(set(paths)) or any(PurePosixPath(p).is_absolute() or ".." in PurePosixPath(p).parts for p in paths):
        raise ReviewViolation("paths must be unique, sorted repository-relative paths")
    partial = [row["path"] for row in rows if not row["read_complete"]]
    if (summary["inventoried_count"] != len(rows) or summary["actual_read_count"] != len(rows) - len(partial)
            or summary["partial_read_count"] != len(partial) or summary["coverage_gaps"] != partial):
        raise ReviewViolation("declared read coverage does not match every file")
    if sum(row["added_lines"] for row in rows) != 19090 or sum(row["deleted_lines"] for row in rows) != 1627:
        raise ReviewViolation("diff line totals mismatch")
    for row in rows:
        if row["read_complete"] != (row["review_mode"] == "complete_fixed_endpoint_diff"):
            raise ReviewViolation("partial review relabelled as complete")
        if not row["read_complete"] and not row["unresolved"]:
            raise ReviewViolation("partial review must retain its gap")
        before, after = row["old_blob"], row["new_blob"]
        if (row["change_type"] == "A") != (before == "0" * 40) or (row["change_type"] == "D") != (after == "0" * 40) or before == after:
            raise ReviewViolation("change type and blob identities mismatch")
    return {"files": len(rows), "declared_complete_diff_reads": len(rows) - len(partial), "declared_partial_diff_reads": len(partial)}


def git(repo: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-c", "core.quotepath=false", "-C", str(repo), *args],
                              check=True, capture_output=True, text=True, encoding="utf-8", timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        raise ReviewViolation("fixed Git object read failed") from None


def verify_inventory(repo: Path, packet: dict) -> None:
    for key, commit in (("baseline", BASE), ("source", TARGET)):
        if git(repo, "rev-parse", f"{commit}^{{tree}}").strip() != packet["summary"][key]["tree"]:
            raise ReviewViolation("fixed Git tree mismatch")
    actual = {}
    for line in git(repo, "diff", "--no-ext-diff", "--no-textconv", "--raw", "--no-renames", "--abbrev=40", BASE, TARGET).splitlines():
        metadata, path = line.split("\t", 1)
        _, _, before, after, kind = metadata.split()
        actual[path] = (before, after, kind)
    expected = {row["path"]: (row["old_blob"], row["new_blob"], row["change_type"]) for row in packet["files"]}
    if actual != expected:
        raise ReviewViolation("fixed Git path/blob inventory mismatch")
    counts = {}
    for line in git(repo, "diff", "--no-ext-diff", "--no-textconv", "--numstat", "--no-renames", BASE, TARGET).splitlines():
        added, deleted, path = line.split("\t", 2)
        counts[path] = (int(added), int(deleted))
    if counts != {row["path"]: (row["added_lines"], row["deleted_lines"]) for row in packet["files"]}:
        raise ReviewViolation("fixed Git per-path line counts mismatch")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, default=PACKET)
    parser.add_argument("--core-repo", type=Path)
    args = parser.parse_args(argv)
    try:
        packet = load_packet(args.packet)
        result = validate_packet(packet)
        if args.core_repo:
            verify_inventory(args.core_repo, packet)
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc) if isinstance(exc, ReviewViolation) else "packet cannot be read or parsed"}))
        return 1
    print(json.dumps({"status": "REVIEW_PACKET_CONTRACT_VALID", **result, "git_inventory_verified": args.core_repo is not None,
                      "semantic_read_verified": False, "reviewer_identity_verified": False, "independent_approval_verified": False,
                      "runtime_verified": False, "pin_changed": False, "public_beta": "NO_GO_UNPUBLISHED"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
