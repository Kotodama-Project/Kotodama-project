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
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TOKEN = re.compile(r"(?<![\w-])(runtime(?:\.[A-Za-z_]\w*)*|kotodama_core(?:\.[A-Za-z_]\w*)*|kotodama(?:-core|-control-plane)?|ktdm)(?![\w-])")
IMPORT_ROOTS = {"runtime", "kotodama", "kotodama_core", "ktdm"}
TEXT_SUFFIXES = {".py", ".pyi", ".toml", ".lock", ".json", ".jsonl", ".yaml", ".yml", ".ini", ".cfg", ".md", ".rst", ".txt", ".sh", ".ps1", ".bat", ".cmd"}
MAX_FILE = 4 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024


def require(condition, code):
    if not condition:
        raise ValueError(code)


def git(repo, *args, input_bytes=None):
    # Object reads do not execute filters/hooks or retrieve missing private blobs over the network.
    try:
        return subprocess.run(["git", "--no-lazy-fetch", "--no-replace-objects", "-c", "core.fsmonitor=false",
                               "-C", str(repo), *args], check=True, capture_output=True, input=input_bytes, timeout=60).stdout
    except subprocess.CalledProcessError as error:
        if error.returncode == 129 and b"--no-lazy-fetch" in (error.stderr or b""):
            raise ValueError("GIT_NO_LAZY_FETCH_REQUIRED") from error
        raise


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
        claimed_literals = set()
        # This is a bounded inventory, not a Python binding interpreter. Keep
        # static imports/literals, but refuse dynamic-alias classification for
        # files whose binding/control-flow constructs are not modeled below.
        unsupported = (ast.Global, ast.Nonlocal, ast.ListComp, ast.SetComp, ast.DictComp,
                       ast.GeneratorExp, ast.Try, ast.TryStar, ast.For, ast.AsyncFor,
                       ast.While, ast.With, ast.AsyncWith, ast.Match)
        uncertain = [node for node in ast.walk(tree) if isinstance(node, unsupported)
                     or isinstance(node, ast.ImportFrom) and any(item.name == "*" for item in node.names)]
        for node in uncertain:
            findings.append({"category": "python_scope_blocked", "line": node.lineno,
                             "end_line": node.end_lineno, "column": node.col_offset, "namespaces": []})

        class Imports(ast.NodeVisitor):
            def __init__(self):
                self.bindings = {"__import__": "__import__", "eval": "eval", "exec": "exec"}
                self.function_parent = None

            def name(self, node):
                if isinstance(node, ast.Name):
                    return self.bindings.get(node.id, "") or ""
                if isinstance(node, ast.Attribute):
                    parent = self.name(node.value)
                    return parent + "." + node.attr if parent else ""
                return ""

            def visit_Import(self, node):
                for item in node.names:
                    root = item.name.split(".")[0]
                    self.bindings[item.asname or root] = item.name if item.asname else root
                    if root in IMPORT_ROOTS:
                        add("python_import", item, [root])

            def visit_ImportFrom(self, node):
                for item in node.names:
                    self.bindings[item.asname or item.name] = f"{node.module}.{item.name}" if not node.level else None
                root = (node.module or "").split(".")[0]
                if not node.level and root in IMPORT_ROOTS:
                    add("python_from_import", node, [root])
                elif node.level and "runtime" in Path(path).parts:
                    add("relative_runtime_import", node, ["runtime"])

            def visit_Name(self, node):
                if isinstance(node.ctx, (ast.Store, ast.Del)):
                    self.bindings[node.id] = None

            def visit_Assign(self, node):
                self.visit(node.value)
                for target in node.targets:
                    self.visit(target)

            def visit_NamedExpr(self, node):
                self.visit(node.value)
                self.visit(node.target)

            def visit_AnnAssign(self, node):
                if node.value is not None:
                    self.visit(node.value)
                self.visit(node.annotation)
                if node.value is not None:
                    self.visit(node.target)

            def scoped(self, node, body, arguments=None, class_scope=False):
                outer, previous_parent = self.bindings, self.function_parent
                parent = outer if class_scope or previous_parent is None else previous_parent
                self.bindings = dict(parent)
                if class_scope:
                    self.function_parent = outer
                else:
                    self.function_parent = None
                    # Python local bindings shadow outer imports throughout the
                    # function, including before their first assignment.
                    class Locals(ast.NodeVisitor):
                        def visit_Name(local, item):
                            if isinstance(item.ctx, (ast.Store, ast.Del)):
                                self.bindings[item.id] = None
                        def visit_Import(local, item):
                            for alias in item.names:
                                self.bindings[alias.asname or alias.name.split(".")[0]] = None
                        def visit_ImportFrom(local, item):
                            for alias in item.names:
                                self.bindings[alias.asname or alias.name] = None
                        def visit_FunctionDef(local, item):
                            self.bindings[item.name] = None
                        visit_AsyncFunctionDef = visit_FunctionDef
                        visit_ClassDef = visit_FunctionDef
                        def visit_Lambda(local, item):
                            pass
                    for statement in body:
                        Locals().visit(statement)
                    if arguments:
                        for arg in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs,
                                    *([arguments.vararg] if arguments.vararg else []),
                                    *([arguments.kwarg] if arguments.kwarg else [])]:
                            self.bindings[arg.arg] = None
                for statement in body:
                    self.visit(statement)
                self.bindings, self.function_parent = outer, previous_parent

            def visit_FunctionDef(self, node):
                for expression in [*node.decorator_list, *node.args.defaults,
                                   *(v for v in node.args.kw_defaults if v is not None)]:
                    self.visit(expression)
                self.bindings[node.name] = None
                self.scoped(node, node.body, node.args)
            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Lambda(self, node):
                for value in [*node.args.defaults, *(v for v in node.args.kw_defaults if v is not None)]:
                    self.visit(value)
                self.scoped(node, [node.body], node.args)

            def visit_ClassDef(self, node):
                for value in [*node.decorator_list, *node.bases, *(item.value for item in node.keywords)]:
                    self.visit(value)
                self.bindings[node.name] = None
                self.scoped(node, node.body, class_scope=True)

            def visit_If(self, node):
                self.visit(node.test)
                before = dict(self.bindings)
                outcomes = []
                for branch in (node.body, node.orelse):
                    self.bindings = dict(before)
                    for statement in branch:
                        self.visit(statement)
                    outcomes.append(self.bindings)
                self.bindings = {key: outcomes[0].get(key) if outcomes[0].get(key) == outcomes[1].get(key) else None
                                 for key in outcomes[0].keys() | outcomes[1].keys()}

            def visit_Call(self, node):
                if not uncertain and self.name(node.func) in {"__import__", "importlib.import_module", "eval", "exec"}:
                    value = node.args[0] if node.args else None
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        add("dynamic_import_literal_candidate", node, targets(value.value))
                        claimed_literals.add(id(value))
                    else:
                        findings.append({"category": "computed_import_or_execution_blocked", "line": node.lineno,
                                         "end_line": node.end_lineno, "column": node.col_offset, "namespaces": []})
                self.generic_visit(node)

        Imports().visit(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in claimed_literals:
                add("python_literal_candidate", node, targets(node.value))

    fence = None
    for line_number, line in enumerate(text.splitlines(), 1):
        if line_number in occupied:
            continue
        if Path(path).suffix in {".md", ".rst"}:
            marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
            if marker:
                run, suffix = marker.groups()
                if fence is None and (run[0] != "`" or "`" not in suffix):
                    fence = (run[0], len(run))
                    continue
                if fence and run[0] == fence[0] and len(run) >= fence[1] and not suffix.strip():
                    fence = None
                    continue
            pieces = [line] if fence else re.findall(r"`([^`]+)`", line)
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
        try:
            path = raw_path.decode("utf-8")
            path_encoding = None
        except UnicodeError:
            # Reversible opaque metadata; never pass a lossy pathname to Git.
            path = "git-path-bytes:" + raw_path.hex()
            path_encoding = "hex"
        require(re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", blob), "OBJECT_ID_INVALID")
        if path_encoding:
            reason = "path_encoding_blocked"
        elif kind != "blob" or mode not in {"100644", "100755"}:
            reason = "linked_source_blocked"
        elif Path(path).suffix not in TEXT_SUFFIXES and Path(path).name not in {"Dockerfile", "Makefile", "MANIFEST.in", ".envrc"}:
            reason = "non_text_source_uninspected"
        elif int(size) > MAX_FILE or total_bytes + int(size) > MAX_TOTAL:
            reason = "source_size_blocked"
        else:
            reason = None; total_bytes += int(size)
            selected[blob] = int(size)
        entries.append((path, mode, blob, reason, path_encoding))
    contents = read_blobs(repo, selected)
    for path, mode, blob, reason, path_encoding in entries:
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
                proposed = "BLOCKED"; blocked.add((path, path_encoding))
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
            if path_encoding:
                row["path_encoding"] = path_encoding
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


def publish_private(output, raw):
    # Link a completely written file into place without replacing any existing
    # destination. Filesystems without hard-link support refuse publication.
    fd, temporary = tempfile.mkstemp(prefix=".namespace-inventory-", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, output)
    finally:
        os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-git", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--private-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        source = args.source_git.resolve(strict=True)
        output = args.private_output.parent.resolve(strict=True) / args.private_output.name
        # git -C also accepts subdirectories and linked worktrees. Bind the
        # exclusion to the actual checkout and both metadata directories.
        roots = git(source, "rev-parse", "--path-format=absolute", "--show-toplevel",
                    "--absolute-git-dir", "--git-common-dir").decode("utf-8").splitlines()
        require(len(roots) == 3, "SOURCE_CHECKOUT_REQUIRED")
        protected = [ROOT, *(Path(root).resolve(strict=True) for root in roots)]
        require(not any(output.is_relative_to(root) for root in protected), "OUTPUT_MUST_BE_OUTSIDE_BOTH_REPOSITORIES")
        result = inventory(source, args.commit)
        raw = (json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        require(len(raw) <= 32 * 1024 * 1024, "OUTPUT_LIMIT")
        publish_private(output, raw)
        print(json.dumps({"status": "PRIVATE_INVENTORY_CANDIDATE", "rows": len(result["rows"]),
                          "category_counts": result["category_counts"], "output_sha256": hashlib.sha256(raw).hexdigest(),
                          "semantic_coverage_verified": False, "cutover_authorized": False}))
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError, RecursionError) as error:
        refusal = {"status": "NAMESPACE_INVENTORY_REFUSED"}
        if isinstance(error, ValueError) and str(error) == "GIT_NO_LAZY_FETCH_REQUIRED":
            refusal["reason_code"] = "GIT_NO_LAZY_FETCH_REQUIRED"
        print(json.dumps(refusal))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
