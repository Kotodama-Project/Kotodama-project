"""Inspect committed namespace consumers without executing or modifying the source repository."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TOKEN = re.compile(r"(?<![\w-])(runtime(?:\.[A-Za-z_]\w*)*|kotodama(?:-core|-control-plane)?|ktdm)(?![\w-])")
TEXT_SUFFIXES = {".py", ".pyi", ".toml", ".lock", ".json", ".jsonl", ".yaml", ".yml", ".ini", ".cfg", ".md", ".rst", ".txt", ".sh", ".ps1", ".bat", ".cmd"}
MAX_FILE = 4 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024


def require(condition, code):
    if not condition:
        raise ValueError(code)


def git(repo, *args, input_bytes=None):
    # Object reads do not execute filters/hooks or retrieve missing private blobs over the network.
    return subprocess.run(["git", "--no-lazy-fetch", "--no-replace-objects", "-c", "core.fsmonitor=false",
                           "-C", str(repo), *args], check=True, capture_output=True, input=input_bytes, timeout=60).stdout


def read_blobs(repo, selected):
    if not selected:
        return {}
    payload = "".join(oid + "\n" for oid in selected).encode("ascii")
    raw = git(repo, "cat-file", "--batch", input_bytes=payload)
    require(len(raw) <= MAX_TOTAL + 8 * 1024 * 1024, "BATCH_LIMIT")
    cursor, result = 0, {}
    for oid, expected_size in selected.items():
        end = raw.find(b"\n", cursor)
        require(0 <= end - cursor <= 256, "BATCH_HEADER_INVALID")
        fields = raw[cursor:end].decode("ascii").split()
        require(fields == [oid, "blob", str(expected_size)], "BLOB_BINDING_MISMATCH")
        start = end + 1; cursor = start + expected_size
        require(raw[cursor:cursor + 1] == b"\n", "BATCH_LENGTH_INVALID")
        result[oid] = raw[start:cursor]; cursor += 1
    require(cursor == len(raw), "BATCH_TRAILING_BYTES")
    return result


def targets(text):
    return sorted({match.group().split(".")[0] for match in TOKEN.finditer(text)})


def scan_text(path, raw):
    text = raw.decode("utf-8-sig")
    findings = []
    occupied = set()

    def add(category, node, names):
        if not names:
            return
        start, end = node.lineno, getattr(node, "end_lineno", node.lineno)
        findings.append({"category": category, "line": start, "end_line": end,
                         "column": node.col_offset, "namespaces": sorted(set(names))})
        occupied.update(range(start, end + 1))

    if Path(path).suffix in {".py", ".pyi"}:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return [{"category": "python_parse_blocked", "line": None, "end_line": None, "column": None, "namespaces": []}]
        aliases = {"__import__": "__import__", "eval": "eval", "exec": "exec"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for item in node.names:
                    aliases[item.asname or item.name.split(".")[0]] = item.name if item.asname else item.name.split(".")[0]
                    if item.name == "runtime" or item.name.startswith("runtime."):
                        add("python_import", item, ["runtime"])
            elif isinstance(node, ast.ImportFrom):
                for item in node.names:
                    aliases[item.asname or item.name] = f"{node.module}.{item.name}"
                if node.module == "runtime" or (node.module or "").startswith("runtime."):
                    add("python_from_import", node, ["runtime"])
                elif node.level and "runtime" in Path(path).parts:
                    add("relative_runtime_import", node, ["runtime"])

        def call_name(node):
            if isinstance(node, ast.Name):
                return aliases.get(node.id, node.id)
            if isinstance(node, ast.Attribute):
                return call_name(node.value) + "." + node.attr
            return ""

        claimed_literals = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and call_name(node.func) in {"__import__", "importlib.import_module", "eval", "exec"}:
                value = node.args[0] if node.args else None
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    add("dynamic_import_literal_candidate", node, targets(value.value))
                    claimed_literals.add(id(value))
                else:
                    findings.append({"category": "computed_import_or_execution_blocked", "line": node.lineno,
                                     "end_line": node.end_lineno, "column": node.col_offset, "namespaces": []})
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in claimed_literals:
                add("python_literal_candidate", node, targets(node.value))

    in_fence = False
    for line_number, line in enumerate(text.splitlines(), 1):
        if line_number in occupied:
            continue
        if Path(path).suffix in {".md", ".rst"}:
            if line.strip().startswith("```"):
                in_fence = not in_fence
                continue
            pieces = [line] if in_fence else re.findall(r"`([^`]+)`", line)
            value = " ".join(pieces)
            category = "document_command_candidate"
        else:
            value = line
            category = "text_config_candidate"
        found = targets(value)
        if found:
            findings.append({"category": category, "line": line_number, "end_line": line_number,
                             "column": None, "namespaces": found})
    return findings


def inventory(repo, commit):
    scanner_digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    require(re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", commit), "IMMUTABLE_COMMIT_REQUIRED")
    require(git(repo, "rev-parse", "--verify", commit + "^{commit}").decode().strip() == commit, "COMMIT_MISMATCH")
    tree = git(repo, "rev-parse", commit + "^{tree}").decode().strip()
    raw_tree = git(repo, "ls-tree", "-r", "-l", "-z", "--full-tree", commit)
    require(len(raw_tree) <= 8 * 1024 * 1024, "TREE_LIMIT")
    rows, categories, total_bytes, scanned, blocked = [], {}, 0, 0, set()
    entries, selected = [], {}
    for entry in raw_tree.split(b"\0"):
        if not entry:
            continue
        header, raw_path = entry.split(b"\t", 1)
        mode, kind, blob, size = header.decode("ascii").split()
        path = raw_path.decode("utf-8")
        require(re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", blob), "OBJECT_ID_INVALID")
        if kind != "blob" or mode not in {"100644", "100755"}:
            reason = "linked_source_blocked"
        elif Path(path).suffix not in TEXT_SUFFIXES and Path(path).name not in {"Dockerfile", "Makefile", "MANIFEST.in", ".envrc"}:
            reason = "non_text_source_uninspected"
        elif int(size) > MAX_FILE or total_bytes + int(size) > MAX_TOTAL:
            reason = "source_size_blocked"
        else:
            reason = None; total_bytes += int(size)
            selected[blob] = int(size)
        entries.append((path, mode, blob, reason))
    contents = read_blobs(repo, selected)
    for path, mode, blob, reason in entries:
        content_hash = None
        generated_hint = Path(path).name == "uv.lock"
        if reason:
            findings = [{"category": reason, "line": None, "end_line": None, "column": None, "namespaces": []}]
        else:
            raw = contents[blob]; scanned += 1
            content_hash = hashlib.sha256(raw).hexdigest()
            generated_hint = generated_hint or bool(re.search(rb"(?im)^(?:[#;]\s*)?(?:Role:\s*generated_mirror|auto-generated|autogenerated|generated file)\b", raw[:4096]))
            try:
                findings = scan_text(path, raw)
            except UnicodeError:
                findings = [{"category": "encoding_blocked", "line": None, "end_line": None, "column": None, "namespaces": []}]
        for finding in findings:
            category = finding["category"]
            if category.endswith(("blocked", "uninspected")):
                proposed = "BLOCKED"; blocked.add(path)
            elif generated_hint:
                proposed = "generated_rebuild"
            elif category == "document_command_candidate":
                proposed = "temporary_compatibility_shim"
            elif category in {"python_import", "python_from_import", "relative_runtime_import"}:
                proposed = "private_implementation_rename"
            else:
                proposed = "BLOCKED"
            row = {"path": path, "mode": mode, "blob_oid": blob, "content_sha256": content_hash, "generated_hint": generated_hint, **finding,
                   "proposed_disposition": proposed, "final_disposition": "BLOCKED", "owner_ref": None,
                   "target_release": None, "removal_release": None, "compatibility_receipt": None, "rollback_source_commit": commit}
            row["id"] = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            rows.append(row); categories[category] = categories.get(category, 0) + 1
    rows.sort(key=lambda row: (row["path"], row["line"] or 0, row["column"] or 0, row["category"]))
    require(len({row["id"] for row in rows}) == len(rows), "DUPLICATE_ROWS")
    require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == scanner_digest, "SCANNER_CHANGED_DURING_INSPECTION")
    return {"kind": "kotodama/namespace-consumer-inventory/v1", "source_commit": commit, "source_tree": tree,
            "scanner_sha256": scanner_digest, "python": sys.version.split()[0],
            "tree_inventory_sha256": hashlib.sha256(raw_tree).hexdigest(), "read_text_candidate_files": scanned,
            "tracked_entries": len(entries),
            "scanned_bytes": total_bytes, "uninspected_or_blocked_files": len(blocked), "category_counts": dict(sorted(categories.items())),
            "rows": rows, "external_consumers": {"state": "BLOCKED", "evidence": None},
            "working_tree_inspected": False, "semantic_coverage_verified": False, "cutover_authorized": False,
            "private_source_bodies_stored": False, "public_beta": "NO_GO_UNPUBLISHED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-git", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--private-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        source = args.source_git.resolve(strict=True)
        output = args.private_output.parent.resolve(strict=True) / args.private_output.name
        require(not output.is_relative_to(ROOT) and not output.is_relative_to(source), "OUTPUT_MUST_BE_OUTSIDE_BOTH_REPOSITORIES")
        result = inventory(source, args.commit)
        raw = (json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        require(len(raw) <= 32 * 1024 * 1024, "OUTPUT_LIMIT")
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
        print(json.dumps({"status": "PRIVATE_INVENTORY_CANDIDATE", "rows": len(result["rows"]),
                          "category_counts": result["category_counts"], "output_sha256": hashlib.sha256(raw).hexdigest(),
                          "semantic_coverage_verified": False, "cutover_authorized": False}))
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError, RecursionError):
        print('{"status":"NAMESPACE_INVENTORY_REFUSED"}')
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
