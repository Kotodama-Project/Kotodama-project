#!/usr/bin/env python3
"""Execute one explicitly authorized local Company Pack operation, not Task state."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any

from create_company_pack import (
    ROOT, STARTER, SafeArgumentParser, StaticCustomization, create_company_pack,
    empty_claims, validate_static_customization, write_stdout_utf8,
)
from validate_template_pack import ID_PATTERN, PUBLIC_PREVIEW_BOUNDARY, SECRET_VALUE_PATTERNS

MAX_BYTES = 1024 * 1024
MAX_FILES = 64
REQUEST_KEYS = {
    "kind", "operation", "operation_key", "task_ref", "work_order_ref",
    "capability_ref", "authorized_output_root", "source", "pack_id",
    "human_intent_ref", "authority_expires_at", "retention_policy_ref",
}
SOURCE_FILES = (
    "tools/run_company_pack_task.py", "tools/create_company_pack.py",
    "tools/check_company_pack_customization.py", "tools/validate_template_pack.py",
)


class Refused(Exception):
    """Only fixed, non-reflective error codes cross the CLI boundary."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise Refused(code)


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def safe_path(path: Path, *, directory: bool = False) -> Path:
    """Reject lexical escapes, links/junctions, and network roots before resolve."""
    require(path.is_absolute() and ".." not in path.parts, "ABSOLUTE_LOCAL_PATH_REQUIRED")
    require(not str(path).startswith(("\\\\", "//")), "NETWORK_ROOT_REFUSED")
    for current in (*reversed(path.parents), path):
        info = current.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not (getattr(info, "st_file_attributes", 0) & 0x400), "LINK_REFUSED")
        require(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode), "SPECIAL_FILE_REFUSED")
        if stat.S_ISREG(info.st_mode):
            require(info.st_nlink == 1, "HARDLINK_REFUSED")
    require(not directory or path.is_dir(), "DIRECTORY_REQUIRED")
    return path.resolve(strict=True)


def read_json(path: Path, limit: int = 65536) -> dict[str, Any]:
    safe_path(path)
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, "JSON_TOO_LARGE")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicates)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Refused("INVALID_JSON") from exc
    require(isinstance(value, dict), "JSON_OBJECT_REQUIRED")
    return value


def tree_bytes(directory: Path) -> dict[str, bytes]:
    safe_path(directory, directory=True)
    result: dict[str, bytes] = {}
    total = 0
    pending = [directory]
    entries = 0
    while pending:
        for path in sorted(pending.pop().iterdir()):
            entries += 1
            require(entries <= 128, "TREE_TOO_LARGE")
            safe_path(path)
            if path.is_dir():
                pending.append(path)
                continue
            require(len(result) < MAX_FILES, "TREE_TOO_LARGE")
            with path.open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
            total += len(raw)
            require(total <= MAX_BYTES, "TREE_TOO_LARGE")
            result[path.relative_to(directory).as_posix()] = raw
    return result


def byte_manifest(files: dict[str, bytes]) -> dict[str, dict[str, Any]]:
    return {name: {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)} for name, raw in sorted(files.items())}


def source_binding() -> dict[str, str]:
    revision = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
        capture_output=True, timeout=10,
    ).stdout.decode("ascii").strip()
    require(re.fullmatch(r"[a-f0-9]{40}", revision) is not None, "SOURCE_REVISION_INVALID")
    files = {"examples/company-starter/" + name: raw for name, raw in tree_bytes(STARTER).items()}
    for relative in SOURCE_FILES:
        path = ROOT / relative
        safe_path(path)
        require(path.stat().st_size <= MAX_BYTES, "SOURCE_TOO_LARGE")
        files[relative] = path.read_bytes()
    return {"revision": revision, "sha256": digest(byte_manifest(files))}


def validate_request(request: dict[str, Any], authorized_root: Path | None) -> Path:
    require(set(request) == REQUEST_KEYS, "REQUEST_FIELDS_INVALID")
    require(request["kind"] == "company_pack_task_request" and request["operation"] == "CREATE_COMPANY_PACK", "OPERATION_REFUSED")
    require(authorized_root is not None, "EXPLICIT_LOCAL_AUTHORIZATION_REQUIRED")
    for key in ("operation_key", "pack_id"):
        require(isinstance(request[key], str) and ID_PATTERN.fullmatch(request[key]) is not None, "IDENTIFIER_INVALID")
    for key, prefix in (("task_ref", "task"), ("work_order_ref", "work-order"), ("capability_ref", "capability")):
        require(isinstance(request[key], str) and re.fullmatch(prefix + r":[A-Za-z0-9][A-Za-z0-9._/-]{1,127}", request[key]) is not None, "REFERENCE_INVALID")
    for key in REQUEST_KEYS - {"source"}:
        require(isinstance(request[key], str) and not any(pattern.search(request[key]) for pattern in SECRET_VALUE_PATTERNS), "UNSAFE_INPUT")
    require(isinstance(request["source"], dict) and set(request["source"]) == {"revision", "sha256"}, "SOURCE_BINDING_INVALID")
    require(request["source"] == source_binding(), "SOURCE_DRIFT")
    customization = StaticCustomization(request["human_intent_ref"], request["authority_expires_at"], request["retention_policy_ref"])
    require(validate_static_customization(customization) is None, "CUSTOMIZATION_OR_EXPIRY_INVALID")
    root = safe_path(Path(request["authorized_output_root"]), directory=True)
    require(root == safe_path(authorized_root, directory=True), "LOCAL_AUTHORIZATION_ROOT_MISMATCH")
    require(root != STARTER and STARTER not in root.parents, "STARTER_OUTPUT_REFUSED")
    return root


def write_new_json(path: Path, value: dict[str, Any]) -> None:
    # Exclusive writes never replace unrelated or incomplete files. A torn write
    # stays visible as incomplete; recovery never trusts a partially written JSON.
    with path.open("xb") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def operation_lock(path: Path):
    if path.exists() or path.is_symlink():
        safe_path(path)
    with path.open("a+b") as stream:
        # The byte-range lock is released by the OS on crash. The file remains;
        # never unlink it, which could give two processes different lock inodes.
        if path.stat().st_size == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise Refused("OPERATION_BUSY") from exc
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise Refused("OPERATION_BUSY") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def verify_output(pack: Path, request: dict[str, Any]) -> dict[str, Any]:
    before = byte_manifest(tree_bytes(pack))
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(ROOT / "tools/validate_template_pack.py"), str(pack)],
        capture_output=True, timeout=30, check=False,
    )
    try:
        report = json.loads(result.stdout.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Refused("VALIDATOR_RESPONSE_INVALID") from exc
    require(result.returncode == 0 and isinstance(report, dict) and report.get("status") == "PASS", "OUTPUT_VALIDATION_FAILED")
    after_files = tree_bytes(pack)
    after = byte_manifest(after_files)
    require(before == after, "OUTPUT_CHANGED_DURING_VALIDATION")
    starter_files = tree_bytes(STARTER)
    require(set(after_files) == set(starter_files), "UNOWNED_OUTPUT_CONTENT")
    manifest = json.loads(after_files["manifest.json"], object_pairs_hook=no_duplicates)
    source_manifest = json.loads(starter_files["manifest.json"])
    require(manifest["id"] == request["pack_id"] and manifest["status"] == "draft" and manifest["human_intent_ref"] == request["human_intent_ref"], "OUTPUT_REQUEST_MISMATCH")
    # Check the narrowly allowed transformation without executing the generator
    # again. A valid but unrelated pack is not a recoverable operation result.
    expected_manifest = dict(source_manifest)
    expected_manifest.update(id=request["pack_id"], status="draft", human_intent_ref=request["human_intent_ref"])
    require(manifest == expected_manifest, "OUTPUT_SOURCE_MISMATCH")
    checked = {"manifest.json"}
    for collection in ("blocks", "records", "mocs"):
        for name in manifest[collection]:
            document = json.loads(after_files[name], object_pairs_hook=no_duplicates)
            expected = json.loads(starter_files[name])
            expected["status"] = "draft"
            require(document["status"] == "draft", "OUTPUT_REQUEST_MISMATCH")
            if collection == "blocks":
                require(document["authority"]["expires_at"] == request["authority_expires_at"], "OUTPUT_REQUEST_MISMATCH")
                expected["authority"]["expires_at"] = request["authority_expires_at"]
            if collection == "records":
                require(document["retention"]["policy_ref"] == request["retention_policy_ref"], "OUTPUT_REQUEST_MISMATCH")
                expected["retention"]["policy_ref"] = request["retention_policy_ref"]
            if collection == "mocs" and expected.get("refs", [None])[0] == source_manifest["id"]:
                expected["refs"][0] = request["pack_id"]
            require(document == expected, "OUTPUT_SOURCE_MISMATCH")
            checked.add(name)
    require(all(after_files[name] == starter_files[name] for name in set(after_files) - checked), "OUTPUT_SOURCE_MISMATCH")
    require(request["source"] == source_binding(), "SOURCE_DRIFT")
    require(validate_static_customization(StaticCustomization(request["human_intent_ref"], request["authority_expires_at"], request["retention_policy_ref"])) is None, "EXPIRED_DURING_EXECUTION")
    return {"files": after, "sha256": digest(after), "validated_files": report["validated_files"]}


def execute(request: dict[str, Any], authorized_root: Path | None) -> dict[str, Any]:
    root = validate_request(request, authorized_root)
    operation = root / request["operation_key"]
    owner = {"kind": "company_pack_operation_owner", "request_sha256": digest(request), "request": request}
    created = False
    try:
        operation.mkdir()
        created = True
    except FileExistsError:
        safe_path(operation, directory=True)
    # Check ownership before opening a lock in an existing directory.
    if not created:
        require(read_json(operation / "owner.json") == owner, "OPERATION_KEY_OR_OWNERSHIP_MISMATCH")
    with operation_lock(operation / ".lock"):
        if created:
            write_new_json(operation / "owner.json", owner)
        else:
            require(read_json(operation / "owner.json") == owner, "OPERATION_KEY_OR_OWNERSHIP_MISMATCH")
        require(set(path.name for path in operation.iterdir()) <= {".lock", "owner.json", "pack", "receipt.json"}, "UNOWNED_OPERATION_CONTENT")
        pack = operation / "pack"
        receipt_path = operation / "receipt.json"
        if created:
            report = create_company_pack(
                request["pack_id"], pack,
                StaticCustomization(request["human_intent_ref"], request["authority_expires_at"], request["retention_policy_ref"]),
                preserve_incomplete=True,
            )
            require(report["status"] == "PASS", "GENERATION_INCOMPLETE")
        # Existing operation = observe only, even if the pack is missing. Never
        # blindly retry a generator whose previous effect may be incomplete.
        require(pack.is_dir(), "OUTPUT_INCOMPLETE")
        output = verify_output(pack, request)
        receipt = {
            "kind": "company_pack_operation_receipt", "status": "LOCAL_PASS",
            "operation": "CREATE_COMPANY_PACK", "operation_key": request["operation_key"],
            "task_ref": request["task_ref"], "work_order_ref": request["work_order_ref"],
            "capability_ref": request["capability_ref"], "request_sha256": digest(request),
            "source": request["source"], "output": output, "claims": empty_claims(),
            "task_state_changed": False, "public_beta": "NO_GO_UNPUBLISHED",
            "authorization_basis": "explicit_caller_local_output_root",
        }
        if receipt_path.exists() or receipt_path.is_symlink():
            saved = read_json(receipt_path)
            require({key: value for key, value in saved.items() if key != "observed_at"} == receipt, "RECEIPT_OR_OUTPUT_DRIFT")
            require(isinstance(saved.get("observed_at"), str), "RECEIPT_INVALID")
            return saved
        receipt["observed_at"] = datetime.now(timezone.utc).isoformat()
        write_new_json(receipt_path, receipt)
        require(read_json(receipt_path) == receipt, "RECEIPT_READBACK_FAILED")
        return receipt


def main(argv: list[str]) -> int:
    parser = SafeArgumentParser(description=__doc__, epilog=PUBLIC_PREVIEW_BOUNDARY)
    parser.add_argument("request", nargs="?", type=Path)
    parser.add_argument("--source-binding", action="store_true")
    parser.add_argument("--authorize-local-output-root", type=Path)
    args = parser.parse_args(argv[1:])
    try:
        if args.source_binding:
            require(args.request is None and args.authorize_local_output_root is None, "ARGUMENT_COMBINATION_INVALID")
            value = source_binding()
        else:
            require(args.request is not None, "REQUEST_REQUIRED")
            value = execute(read_json(args.request.absolute()), args.authorize_local_output_root)
        write_stdout_utf8(json.dumps(value, ensure_ascii=True, sort_keys=True))
        return 0
    except (Refused, OSError, ValueError, KeyError, TypeError, RecursionError, subprocess.SubprocessError) as exc:
        code = str(exc) if isinstance(exc, Refused) else "LOCAL_OPERATION_INCOMPLETE_OR_UNAVAILABLE"
        write_stdout_utf8(json.dumps({"kind": "company_pack_operation_result", "status": "INCOMPLETE_OR_REFUSED", "error": code, "task_state_changed": False, "claims": empty_claims(), "public_beta": "NO_GO_UNPUBLISHED"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
