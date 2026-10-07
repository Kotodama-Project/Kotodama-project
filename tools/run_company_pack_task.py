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
import sqlite3
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
    "runtime/discord-template/src/common.mjs",
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


def resolve_records(request: dict[str, Any], root: Path, binding_path: Path | None) -> dict[str, Any]:
    """Read an operator-selected snapshot; never mint authority or update records."""
    require(binding_path is not None, "EXISTING_RECORD_BINDING_REQUIRED")
    binding = read_json(binding_path)
    if binding.get("kind") == "company_pack_discord_task_binding":
        return resolve_discord_task(request, root, binding)
    require(set(binding) == {"kind", "version", "owner_ref", "task_updated_at", "records"}, "RECORD_BINDING_INVALID")
    require(binding["kind"] == "company_pack_existing_record_binding" and binding["version"] == "1.0", "RECORD_BINDING_INVALID")
    require(isinstance(binding["owner_ref"], str) and re.fullmatch(r"ref/[A-Za-z0-9][A-Za-z0-9._/@-]*(?:/[A-Za-z0-9][A-Za-z0-9._/@-]*)*", binding["owner_ref"]) is not None and not any(pattern.search(binding["owner_ref"]) for pattern in SECRET_VALUE_PATTERNS), "RECORD_OWNER_INVALID")
    entries = binding["records"]
    require(isinstance(entries, dict) and set(entries) == {"task", "work_order", "capability"}, "RECORD_BINDING_INVALID")
    records = {}
    paths = set()
    for name, entry in entries.items():
        require(isinstance(entry, dict) and set(entry) == {"path", "sha256"}, "RECORD_BINDING_INVALID")
        require(isinstance(entry["path"], str) and isinstance(entry["sha256"], str) and re.fullmatch(r"[a-f0-9]{64}", entry["sha256"]) is not None, "RECORD_BINDING_INVALID")
        path = safe_path(Path(entry["path"]))
        require(path not in paths and root / request["operation_key"] not in path.parents, "RECORD_PATH_REFUSED")
        paths.add(path)
        with path.open("rb") as stream:
            raw = stream.read(65537)
        require(len(raw) <= 65536, "RECORD_TOO_LARGE")
        require(hashlib.sha256(raw).hexdigest() == entry["sha256"], "RECORD_DIGEST_DRIFT")
        record = json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicates)
        require(isinstance(record, dict), "RECORD_OBJECT_REQUIRED")
        records[name] = record

    task = records["task"]
    task_fields = set("$schema kind version record_status task_id project_ref phase_ref requirement_ref plan_ref lifecycle_ref title status owner_ref collaborator_refs outcome scope acceptance_criteria next_action blocker evidence_refs execution_surfaces stop_conditions rollback_ref updated_at public_beta".split())
    require(task_fields <= set(task) <= task_fields | {"boundary_snapshot", "gate_ceiling", "follow_up_wait"}, "TASK_RECORD_INVALID")
    require(task["$schema"] == "../../../schemas/task-record.schema.json" and task["project_ref"] == "../project.json" and task["lifecycle_ref"] == "../lifecycle.json", "TASK_RECORD_INVALID")
    require(task.get("kind") == "kotodama.task-record" and task.get("version") == "1.0" and task.get("record_status") == "CANDIDATE_ONLY", "TASK_RECORD_INVALID")
    require(isinstance(task.get("task_id"), str) and re.fullmatch(r"KTP-TASK-[0-9]{4}", task["task_id"]) is not None and request["task_ref"] == "task:" + task["task_id"], "TASK_REFERENCE_MISMATCH")
    require(task.get("status") in ("active", "validating") and isinstance(task.get("blocker"), dict) and task["blocker"].get("kind") == "none", "TASK_NOT_EXECUTABLE")
    require(task.get("owner_ref") == binding["owner_ref"], "TASK_OWNER_MISMATCH")
    require(task.get("updated_at") == binding["task_updated_at"] and isinstance(binding["task_updated_at"], str), "TASK_REVISION_MISMATCH")
    updated_at = datetime.fromisoformat(task["updated_at"].replace("Z", "+00:00"))
    require(updated_at.tzinfo is not None and updated_at <= datetime.now(timezone.utc), "TASK_REVISION_MISMATCH")
    require(task.get("public_beta") == "NO_GO_UNPUBLISHED", "TASK_RECORD_INVALID")
    # Task scope remains the existing free-text list shape. This narrow adapter
    # only recognizes these explicit machine-readable entries; it never infers
    # execution permission from a task's title or prose about public adoption.
    scope = task.get("scope")
    require(isinstance(scope, dict) and set(scope) == {"in_scope", "out_of_scope"}, "TASK_SCOPE_MISMATCH")
    require(scope == {"in_scope": ["CREATE_COMPANY_PACK", "output-root:" + str(root)], "out_of_scope": ["external_write", "task_state_change", "promotion"]}, "TASK_SCOPE_MISMATCH")

    target = {
        "task_ref": request["task_ref"], "task_revision": entries["task"]["sha256"],
        "owner_ref": binding["owner_ref"], "operation_key": request["operation_key"],
        "output_root": str(root), "pack_id": request["pack_id"],
        "human_intent_ref": request["human_intent_ref"], "retention_policy_ref": request["retention_policy_ref"],
    }
    for name, template_name in (("work_order", "work-order-candidate"), ("capability", "capability-grant-candidate")):
        record = records[name]
        template = read_json(STARTER / "records" / (template_name + ".json"))
        require(set(record) == set(template["required_fields"]) | {"kind", "record_status", "status"}, "BOUND_RECORD_FIELDS_INVALID")
        require(record["kind"] == template["artifact"] and record["record_status"] == "CANDIDATE_ONLY" and record["status"] == "active", "BOUND_RECORD_INACTIVE")
        require(record["target"] == target, "BOUND_RECORD_TARGET_MISMATCH")
        require(record["expires_at"] == request["authority_expires_at"], "BOUND_RECORD_EXPIRY_MISMATCH")
        expires_at = datetime.fromisoformat(record["expires_at"].replace("Z", "+00:00"))
        require(expires_at.tzinfo is not None and expires_at > datetime.now(timezone.utc), "BOUND_RECORD_EXPIRED")
        require(isinstance(record["rollback"], str) and bool(record["rollback"].strip()) and isinstance(record["stop_conditions"], list) and bool(record["stop_conditions"]) and all(isinstance(value, str) and bool(value.strip()) for value in record["stop_conditions"]), "BOUND_RECORD_SAFETY_FIELDS_INVALID")
    work_order, capability = records["work_order"], records["capability"]
    for identifier in (work_order["work_order_id"], capability["grant_id"]):
        require(isinstance(identifier, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{1,127}", identifier) is not None, "RECORD_IDENTIFIER_INVALID")
    require(request["work_order_ref"] == "work-order:" + work_order["work_order_id"], "WORK_ORDER_REFERENCE_MISMATCH")
    require(work_order["action"] == "CREATE_COMPANY_PACK" and work_order["candidate_revision"] == request["source"], "WORK_ORDER_ACTION_OR_REVISION_MISMATCH")
    require(isinstance(work_order["decision_ref"], str) and bool(work_order["decision_ref"].strip()) and work_order["effects"] == ["create_local_draft_pack_and_operation_receipt"], "WORK_ORDER_EFFECTS_INVALID")
    require(request["capability_ref"] == "capability:" + capability["grant_id"] and capability["work_order_ref"] == request["work_order_ref"], "CAPABILITY_REFERENCE_MISMATCH")
    require(capability["subject_ref"] == binding["owner_ref"], "CAPABILITY_OWNER_MISMATCH")
    require(capability["allowed_actions"] == ["CREATE_COMPANY_PACK"] and capability["denied_actions"] == ["external_write", "task_state_change", "promotion"], "CAPABILITY_ACTIONS_MISMATCH")
    require(isinstance(capability["issued_by_role"], str) and bool(capability["issued_by_role"].strip()) and capability["authority_evidence_ref"] == work_order["decision_ref"], "CAPABILITY_EVIDENCE_MISMATCH")
    require(isinstance(capability["issued_at"], str), "CAPABILITY_NOT_YET_ISSUED")
    issued_at = datetime.fromisoformat(capability["issued_at"].replace("Z", "+00:00"))
    require(issued_at.tzinfo is not None and issued_at <= datetime.now(timezone.utc), "CAPABILITY_NOT_YET_ISSUED")
    return {"sha256": digest(binding), "task_revision": entries["task"]["sha256"], "owner_ref": binding["owner_ref"], "records": entries}


def discord_source_fingerprint(source: dict[str, Any]) -> str:
    """Reuse the owner's exact JavaScript number/string canonicalization."""
    module = (ROOT / "runtime/discord-template/src/common.mjs").as_uri()
    program = ("import {readFileSync} from 'node:fs';import {sourceFingerprint} from "
               + json.dumps(module) + ";process.stdout.write(sourceFingerprint(JSON.parse(readFileSync(0,'utf8'))));")
    environment = {key: value for key, value in os.environ.items() if key.upper() not in {"NODE_OPTIONS", "NODE_PATH"}}
    try:
        result = subprocess.run(["node", "--input-type=module", "-e", program],
            input=json.dumps(source, ensure_ascii=True, allow_nan=False).encode("utf-8"),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, env=environment)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        raise Refused("DISCORD_FINGERPRINT_UNAVAILABLE") from exc
    require(result.returncode == 0 and re.fullmatch(rb"[a-f0-9]{64}", result.stdout) is not None, "DISCORD_FINGERPRINT_UNAVAILABLE")
    return result.stdout.decode("ascii")


def resolve_discord_task(request: dict[str, Any], root: Path, binding: dict[str, Any]) -> dict[str, Any]:
    """Read the existing local owner. Snapshot references do not grant authority."""
    keys = {"kind", "version", "owner_kind", "owner_ref", "database_path", "task_id",
            "task_revision", "source_key", "source_revision", "required_actions", "request_sha256"}
    require(set(binding) == keys and binding["kind"] == "company_pack_discord_task_binding" and binding["version"] == "1.0", "DISCORD_BINDING_INVALID")
    require(binding["owner_kind"] == "local", "DISCORD_LOCAL_OWNER_REQUIRED")
    require(isinstance(binding["owner_ref"], str) and re.fullmatch(r"ref/[A-Za-z0-9][A-Za-z0-9._/@-]{1,180}", binding["owner_ref"]) is not None, "RECORD_OWNER_INVALID")
    require(not any(pattern.search(binding["owner_ref"]) for pattern in SECRET_VALUE_PATTERNS), "RECORD_OWNER_INVALID")
    require(isinstance(binding["task_id"], str) and re.fullmatch(r"task-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", binding["task_id"]) is not None, "DISCORD_TASK_ID_INVALID")
    for name, minimum in (("task_revision", 1), ("source_revision", 0)):
        require(type(binding[name]) is int and minimum <= binding[name] <= 9007199254740991, "DISCORD_REVISION_INVALID")
    require(isinstance(binding["source_key"], str) and re.fullmatch(r"[a-f0-9]{64}", binding["source_key"]) is not None, "DISCORD_SOURCE_INVALID")
    require(binding["required_actions"] == ["create_company_pack"], "DISCORD_ACTION_REFUSED")
    require(binding["request_sha256"] == digest(request), "DISCORD_REQUEST_MISMATCH")
    require(request["task_ref"] == "task:" + binding["task_id"], "TASK_REFERENCE_MISMATCH")
    require(isinstance(binding["database_path"], str), "DISCORD_DATABASE_INVALID")
    database = safe_path(Path(binding["database_path"]))
    require(database.is_file() and root / request["operation_key"] not in database.parents, "RECORD_PATH_REFUSED")

    def document(row: sqlite3.Row | None, code: str) -> dict[str, Any]:
        require(row is not None and isinstance(row["body"], str) and len(row["body"].encode("utf-8")) <= 65536, code)
        value = json.loads(row["body"], object_pairs_hook=no_duplicates)
        require(isinstance(value, dict), code)
        return value

    try:
        connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            steps = 0
            def bounded_query() -> int:
                nonlocal steps
                steps += 1
                return int(steps > 200)
            connection.set_progress_handler(bounded_query, 1000)
            connection.execute("BEGIN")
            task_row = connection.execute("SELECT id,actor,room,source_key,revision,state,body FROM tasks WHERE id=?", (binding["task_id"],)).fetchone()
            task = document(task_row, "DISCORD_TASK_NOT_FOUND")
            require(task_row["state"] == "running" and task_row["revision"] == binding["task_revision"], "DISCORD_TASK_NOT_RUNNING")
            require(task.get("id") == binding["task_id"] and task.get("actor") == task_row["actor"], "DISCORD_TASK_INVALID")
            require(task_row["source_key"] == task.get("source_key") == binding["source_key"] and type(task.get("source_revision")) is int and task["source_revision"] == binding["source_revision"], "DISCORD_SOURCE_CHANGED")
            require(task.get("action") == "create_company_pack" and task.get("requiredActions") == binding["required_actions"], "DISCORD_ACTION_REFUSED")
            require(isinstance(task.get("request"), str) and task["request"].strip() == request["pack_id"], "DISCORD_PACK_REQUEST_MISMATCH")
            source_row = connection.execute("SELECT key,revision,fingerprint,body FROM sources WHERE key=?", (binding["source_key"],)).fetchone()
            source = document(source_row, "DISCORD_SOURCE_NOT_FOUND")
            require(type(source.get("revision")) is int and source_row["revision"] == source["revision"] == binding["source_revision"] and source.get("key") == binding["source_key"], "DISCORD_SOURCE_CHANGED")
            require(source.get("provider") == "discord" and source.get("final") is True and source.get("withdrawn", False) is False, "DISCORD_SOURCE_REFUSED")
            actor = task_row["actor"]
            require(isinstance(actor, str) and re.fullmatch(r"[0-9]{5,24}", actor) is not None and source.get("actorId") == actor, "DISCORD_ACTOR_MISMATCH")
            require(isinstance(source.get("readers"), list) and all(isinstance(reader, str) for reader in source["readers"]) and actor in source["readers"], "DISCORD_SOURCE_ACCESS_DENIED")
            require(source_row["fingerprint"] == discord_source_fingerprint(source), "DISCORD_SOURCE_FINGERPRINT_MISMATCH")
            require(all(isinstance(source.get(key), str) and re.fullmatch(r"[0-9]{5,24}", source[key]) is not None for key in ("guildId", "channelId")), "DISCORD_SOURCE_INVALID")
            room = f'discord:{source["guildId"]}:{source["channelId"]}'
            require(task_row["room"] == task.get("room") == room, "TASK_ROOM_MISMATCH")
            metadata = source.get("metadata")
            require(isinstance(metadata, dict), "DISCORD_EXPLICIT_COMMAND_REQUIRED")
            command = metadata.get("command")
            require(isinstance(command, dict) and command.get("action") == "create_company_pack" and command.get("request") == task["request"] == source.get("text"), "DISCORD_EXPLICIT_COMMAND_REQUIRED")
            intents = task.get("intentIds")
            require(isinstance(intents, list) and len(intents) == 1 and isinstance(intents[0], str) and re.fullmatch(r"[a-f0-9]{64}", intents[0]) is not None, "DISCORD_INTENT_INVALID")
            require(request["human_intent_ref"] == "human-intent:" + intents[0], "DISCORD_INTENT_MISMATCH")
            intent_row = connection.execute("SELECT source_key,revision,body FROM intents WHERE id=?", (intents[0],)).fetchone()
            intent = document(intent_row, "DISCORD_INTENT_NOT_FOUND")
            require(intent_row["source_key"] == intent.get("source_key") == binding["source_key"] and intent_row["revision"] == intent.get("source_revision") == binding["source_revision"], "DISCORD_INTENT_MISMATCH")
            require(intent.get("kind") == "request" and intent.get("explicit") is True and intent.get("complete") is True and intent.get("origin") in ("explicit_command", "native_correction"), "DISCORD_EXPLICIT_COMMAND_REQUIRED")
            if intent["origin"] == "native_correction":
                correction = metadata.get("manualCorrection")
                require(isinstance(correction, dict) and correction.get("surface") == "discord_native_ui" and correction.get("actor") == actor and correction.get("taskId") == binding["task_id"], "DISCORD_EXPLICIT_COMMAND_REQUIRED")
                require(isinstance(correction.get("interactionId"), str) and re.fullmatch(r"[0-9]{5,24}", correction["interactionId"]) is not None and intent.get("targetTaskId") == binding["task_id"], "DISCORD_EXPLICIT_COMMAND_REQUIRED")
            else:
                require(metadata.get("kind") in ("command", "trusted_cli"), "DISCORD_EXPLICIT_COMMAND_REQUIRED")
            require(intent.get("action") == "create_company_pack" and intent.get("request") == task["request"], "DISCORD_INTENT_MISMATCH")
            snapshot = {"task": task, "task_revision": task_row["revision"], "state": task_row["state"], "source": source, "intent": intent}
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise Refused("DISCORD_OWNER_UNAVAILABLE") from exc
    return {"kind": "discord_local_owner_readback", "sha256": digest(binding), "owner_ref": binding["owner_ref"],
            "task_revision": binding["task_revision"], "source_key": binding["source_key"],
            "source_revision": binding["source_revision"], "required_actions": binding["required_actions"],
            "owner_snapshot_sha256": digest(snapshot), "records": {"owner_database": {"path": str(database)}},
            "authority_verified": False, "task_state_changed": False}


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
        report = json.loads(result.stdout.decode("utf-8"), object_pairs_hook=no_duplicates)
    except (ValueError, UnicodeError, RecursionError, Refused) as exc:
        raise Refused("VALIDATOR_RESPONSE_INVALID") from exc
    require(result.returncode == 0 and isinstance(report, dict) and report.get("status") == "PASS", "OUTPUT_VALIDATION_FAILED")
    require(set(report) == {"status", "pack_id", "validated_files", "errors"}
            and type(report["validated_files"]) is int
            and report["errors"] == [] and report["pack_id"] == request["pack_id"],
            "VALIDATOR_RESPONSE_INVALID")
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
    require(report["validated_files"] == len(checked), "VALIDATOR_RESPONSE_INVALID")
    require(request["source"] == source_binding(), "SOURCE_DRIFT")
    require(validate_static_customization(StaticCustomization(request["human_intent_ref"], request["authority_expires_at"], request["retention_policy_ref"])) is None, "EXPIRED_DURING_EXECUTION")
    return {"files": after, "sha256": digest(after), "validated_files": report["validated_files"]}


def execute(request: dict[str, Any], authorized_root: Path | None, binding_path: Path | None = None) -> dict[str, Any]:
    root = validate_request(request, authorized_root)
    record_binding = resolve_records(request, root, binding_path)
    operation = root / request["operation_key"]
    owner = {"kind": "company_pack_operation_owner", "request_sha256": digest(request), "request": request, "record_binding": record_binding}
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
        require(resolve_records(request, root, binding_path) == record_binding, "RECORD_BINDING_DRIFT")
        receipt = {
            "kind": "company_pack_operation_receipt", "status": "LOCAL_PASS",
            "operation": "CREATE_COMPANY_PACK", "operation_key": request["operation_key"],
            "task_ref": request["task_ref"], "work_order_ref": request["work_order_ref"],
            "capability_ref": request["capability_ref"], "request_sha256": digest(request),
            "source": request["source"], "output": output, "claims": empty_claims(),
            "record_binding": record_binding,
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
    parser.add_argument("--record-binding", type=Path)
    args = parser.parse_args(argv[1:])
    try:
        if args.source_binding:
            require(args.request is None and args.authorize_local_output_root is None and args.record_binding is None, "ARGUMENT_COMBINATION_INVALID")
            value = source_binding()
        else:
            require(args.request is not None, "REQUEST_REQUIRED")
            value = execute(read_json(args.request.absolute()), args.authorize_local_output_root, args.record_binding.absolute() if args.record_binding else None)
        write_stdout_utf8(json.dumps(value, ensure_ascii=True, sort_keys=True))
        return 0
    except (Refused, OSError, ValueError, KeyError, TypeError, RecursionError, subprocess.SubprocessError) as exc:
        code = str(exc) if isinstance(exc, Refused) else "LOCAL_OPERATION_INCOMPLETE_OR_UNAVAILABLE"
        write_stdout_utf8(json.dumps({"kind": "company_pack_operation_result", "status": "INCOMPLETE_OR_REFUSED", "error": code, "task_state_changed": False, "claims": empty_claims(), "public_beta": "NO_GO_UNPUBLISHED"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
