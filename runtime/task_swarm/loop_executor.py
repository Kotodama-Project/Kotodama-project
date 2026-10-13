"""Dormant local-fixture protocol primitives, never execution or owner authority.

Callers validate the current Task/owner, authenticate the DB plan and dispatch,
and keep their current guard. This module starts no process and changes no state.
Native profiles, loop admission and backend methods remain in their old paths.
"""
from __future__ import annotations

import copy
from datetime import datetime
from functools import wraps
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys

from .protocol import SwarmError, canonical, digest, digest_ref, integer, ref
from .task_contract import MAX_INPUT_BYTES, require, shape, text
from .task_planning import SPAN_KEYS, _Sources

MODE = "local_executable_fixture"
EXECUTOR_FIELDS = {"executor_contract_version", "executor_policy_sha256"}
EXECUTOR_TEMPLATE_FIELDS = EXECUTOR_FIELDS | {"executor_owner_binding"}
MAX_POLICY_BYTES = 4096
MAX_PROOF_BYTES = 2 * 1024 * 1024
_DECLARATION = {"kind", "version", "mode", "prompt_contract_version", "visibility", "executable", "materials"}
_POLICY = _DECLARATION | {"task_id", "revision", "parent_input_digest", "initial_specification_digest", "policy_source", "owner_base"}
_MATERIAL = {"path", "source_key", "source_revision", "sha256", "bytes", "capability"}
_RECEIPT = {"actor_ref", "invocation_ref", "input_digest", "synthetic", *EXECUTOR_FIELDS,
            "prompt_contract_version", "prompt_sha256", "runtime"}
_RUNTIME = {"result", "receipt", "paths"}
_RUNTIME_HASHES = {"runtime_receipt_sha256", "runtime_rollout_sha256"}
_DIGESTS = {"schema", "command", "process", "events", "stderr", "last_message", "result", "input"}


def _pure_input(function):
    @wraps(function)
    def checked(*args, **kwargs):
        try: return function(*args, **kwargs)
        except (KeyError, TypeError, AttributeError, UnicodeError, ValueError, RecursionError) as exc:
            raise SwarmError("LOOP_EXECUTOR_INPUT", "malformed executor input") from exc
    return checked


def _raw(value):
    try:
        return canonical(value).encode("utf-8")
    except (UnicodeError, TypeError, ValueError, RecursionError) as exc:
        raise SwarmError("LOOP_EXECUTOR_DOCUMENT", "executor evidence must be finite UTF-8 JSON") from exc


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "LOOP_EXECUTOR_DUPLICATE_KEY")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError("finite JSON required")))
    except (UnicodeError, ValueError) as exc:
        raise SwarmError("LOOP_EXECUTOR_DOCUMENT", "executor evidence is not strict JSON") from exc


def _base(value):
    text(value, 4096, "LOOP_EXECUTOR_ROOT")
    path = Path(value)
    require(path.is_absolute() and ".." not in path.parts and str(path) == value, "LOOP_EXECUTOR_ROOT")
    return path


def _relative(value):
    text(value, 1024, "LOOP_EXECUTOR_PATH")
    path = PurePosixPath(value)
    require(not path.is_absolute() and path.parts and value == path.as_posix()
            and all(part not in {".", ".."} for part in path.parts)
            and "\\" not in value and ":" not in value, "LOOP_EXECUTOR_PATH")
    return path.parts


def _source_set(payload):
    require(isinstance(payload, dict) and type(payload.get("version")) is int and payload["version"] == 2
            and isinstance(payload.get("objective"), dict), "LOOP_EXECUTOR_INPUT")
    require(len(_raw(payload)) <= MAX_INPUT_BYTES, "TASK_INPUT_LIMIT")
    require(isinstance(payload.get("task_id"), str) and re.fullmatch(
        r"task-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", payload["task_id"]), "TASK_ID_INVALID")
    integer(payload.get("revision"), "Task revision", maximum=2**53-1)
    rows = payload.get("sources")
    require(isinstance(rows, list) and 1 <= len(rows) <= 10, "TASK_SOURCES_INVALID")
    seen = set()
    for row in rows:
        shape(row, {"key", "revision", "text", "sha256"}, "TASK_SOURCE_INVALID")
        digest_ref(row["key"])
        integer(row["revision"], "Source revision", minimum=0, maximum=2**53-1)
        text(row["text"], 12000, "TASK_SOURCE_INVALID")
        require((row["key"], row["revision"]) not in seen, "TASK_SOURCE_DUPLICATE")
        seen.add((row["key"], row["revision"]))
        require(hashlib.sha256(row["text"].encode()).hexdigest() == row["sha256"], "TASK_SOURCE_DIGEST_MISMATCH")
    sources = _Sources(payload)
    sources.spans(payload["objective"].get("constraints"))
    return sources


def _policy_shape(policy):
    shape(policy, _POLICY, "LOOP_EXECUTOR_POLICY")
    require(policy["kind"] == "task_loop_executor" and type(policy["version"]) is int and policy["version"] == 1
            and type(policy["prompt_contract_version"]) is int and policy["prompt_contract_version"] == 1,
            "LOOP_EXECUTOR_VERSION")
    require(policy["mode"] == MODE and policy["visibility"] == "fixture_declared_material_observation", "LOOP_EXECUTOR_MODE_UNSUPPORTED")
    ref(policy["task_id"]); integer(policy["revision"], "Task revision", maximum=2**53-1)
    for field in ("parent_input_digest", "initial_specification_digest"): digest_ref(policy[field])
    shape(policy["policy_source"], SPAN_KEYS, "LOOP_EXECUTOR_POLICY_SOURCE")
    digest_ref(policy["policy_source"]["source_key"])
    integer(policy["policy_source"]["source_revision"], "policy Source revision", minimum=0, maximum=2**53-1)
    integer(policy["policy_source"]["start"], "policy offset", minimum=0, maximum=12000)
    integer(policy["policy_source"]["end"], "policy end", maximum=12000)
    require(policy["policy_source"]["start"] < policy["policy_source"]["end"], "LOOP_EXECUTOR_POLICY_SOURCE")
    base, paths, identities = _base(policy["owner_base"]), set(), set()
    require(isinstance(policy["materials"], list) and len(policy["materials"]) <= 2, "LOOP_EXECUTOR_MATERIAL_LIMIT")
    for index, item in enumerate([policy["executable"], *policy["materials"]]):
        shape(item, ({"path", "relative_path", "bytes", "sha256"} if not index else _MATERIAL | {"relative_path"}), "LOOP_EXECUTOR_FILE")
        relative = _relative(item["relative_path"])
        require(item["path"] == str(base.joinpath(*relative)) and item["path"] not in paths, "LOOP_EXECUTOR_PATH")
        paths.add(item["path"]); digest_ref(item["sha256"])
        integer(item["bytes"], "fixture file bytes", maximum=48000 if index else MAX_INPUT_BYTES)
        if not index: require(relative[-1].endswith(".py"), "LOOP_EXECUTOR_EXECUTABLE_UNSUPPORTED")
        else:
            digest_ref(item["source_key"])
            integer(item["source_revision"], "material Source revision", minimum=0, maximum=2**53-1)
            identity = (item["source_key"], item["source_revision"])
            require(identity not in identities and item["capability"] == "fixture_local_read_observation", "LOOP_EXECUTOR_MATERIAL")
            identities.add(identity)
    return base


@_pure_input
def derive_executor_policy(payload, initial_specification, policy_span, *, owner_base):
    """Derive a Source candidate, without checking an owner or reading a file."""
    from .closed_loop_contract import validate_plan
    sources, base = _source_set(payload), _base(owner_base)
    spec = validate_plan(initial_specification, payload)
    require(policy_span in payload["objective"]["constraints"], "LOOP_EXECUTOR_POLICY_SOURCE")
    raw = sources.span(policy_span).encode("utf-8")
    require(len(raw) <= MAX_POLICY_BYTES, "LOOP_EXECUTOR_POLICY_LIMIT")
    declaration = _json(raw)
    shape(declaration, _DECLARATION, "LOOP_EXECUTOR_POLICY")
    require(declaration["kind"] == "task_loop_executor" and type(declaration["version"]) is int
            and declaration["version"] == 1 and type(declaration["prompt_contract_version"]) is int
            and declaration["prompt_contract_version"] == 1, "LOOP_EXECUTOR_VERSION")
    require(declaration["mode"] == MODE, "LOOP_EXECUTOR_MODE_UNSUPPORTED")
    require(declaration["visibility"] == "fixture_declared_material_observation", "LOOP_EXECUTOR_CAPABILITY_UNSUPPORTED")
    executable = declaration["executable"]
    shape(executable, {"path", "sha256", "bytes"}, "LOOP_EXECUTOR_EXECUTABLE")
    parts = _relative(executable["path"])
    require(parts[-1].endswith(".py"), "LOOP_EXECUTOR_EXECUTABLE_UNSUPPORTED")
    digest_ref(executable["sha256"])
    integer(executable["bytes"], "fixture executable bytes", maximum=MAX_INPUT_BYTES)
    materials, identities, paths = [], set(), {executable["path"]}
    require(isinstance(declaration["materials"], list) and len(declaration["materials"]) <= 2, "LOOP_EXECUTOR_MATERIAL_LIMIT")
    for material in declaration["materials"]:
        shape(material, _MATERIAL, "LOOP_EXECUTOR_MATERIAL")
        parts = _relative(material["path"])
        identity = (material["source_key"], material["source_revision"])
        require(identity not in identities and material["path"] not in paths, "LOOP_EXECUTOR_MATERIAL_DUPLICATE")
        digest_ref(material["source_key"])
        integer(material["source_revision"], "material Source revision", minimum=0, maximum=2**53-1)
        require(sources.latest.get(identity[0]) == identity[1] and identity in sources.texts, "OBJECTIVE_SOURCE_STALE")
        raw_source = sources.texts[identity].encode("utf-8")
        integer(material["bytes"], "material bytes", maximum=48000)
        require(material["bytes"] == len(raw_source) and material["sha256"] == hashlib.sha256(raw_source).hexdigest(),
                "LOOP_EXECUTOR_MATERIAL_SOURCE")
        require(material["capability"] == "fixture_local_read_observation", "LOOP_EXECUTOR_CAPABILITY_UNSUPPORTED")
        materials.append({**material, "relative_path": material["path"], "path": str(base.joinpath(*parts))})
        identities.add(identity); paths.add(material["path"])
    return {**declaration, "task_id": payload["task_id"], "revision": payload["revision"],
        "parent_input_digest": digest(payload), "initial_specification_digest": digest(spec),
        "policy_source": copy.deepcopy(policy_span), "owner_base": str(base),
        "executable": {**executable, "relative_path": executable["path"],
                       "path": str(base.joinpath(*_relative(executable["path"])))}, "materials": materials}


def check_current_executor_policy(policy, payload, initial_specification, *, owner_path, owner_document):
    """Extra bounded mapping/byte checks; a caller-supplied document is no grant."""
    from .owner_file import _reject_symlink_components, _safe_resolve
    from .task_runner import read_bytes
    _policy_shape(policy)
    base = Path(owner_path).absolute().parent
    expected = derive_executor_policy(payload, initial_specification, policy["policy_source"], owner_base=str(base))
    require(_raw(policy) == _raw(expected), "LOOP_EXECUTOR_POLICY_CHANGED")
    require(isinstance(owner_document, dict) and len(_raw(owner_document)) <= 1024*1024, "LOOP_EXECUTOR_OWNER_MAPPING")
    binding = owner_document.get("binding", {})
    require(isinstance(binding, dict) and binding.get("task_id") == payload["task_id"]
            and type(binding.get("revision")) is int and binding["revision"] == payload["revision"]
            and binding.get("context_digest") == digest(payload), "LOOP_EXECUTOR_OWNER_MAPPING")
    checks = owner_document.get("source_checks")
    require(isinstance(checks, list), "LOOP_EXECUTOR_OWNER_MAPPING")
    for item in [policy["executable"], *policy["materials"]]:
        path = Path(item["path"])
        matched = []
        for check in checks:
            require(isinstance(check, dict), "LOOP_EXECUTOR_OWNER_MAPPING")
            candidate = _safe_resolve(check.get("path"), base=base, name="source path")
            if candidate == path: matched.append(check.get("sha256"))
        require(matched and all(sha == item["sha256"] for sha in matched), "LOOP_EXECUTOR_OWNER_MAPPING")
        _reject_symlink_components(path, stop=base, field="fixture source")
        raw = read_bytes(path, item["bytes"])
        require(len(raw) == item["bytes"] and hashlib.sha256(raw).hexdigest() == item["sha256"], "LOOP_EXECUTOR_FILE_CHANGED")
        _reject_symlink_components(path, stop=base, field="fixture source")


def executor_version(runtime_plan, initial_template):
    """Pure DB-template pair parser. The caller authenticates the DB snapshot."""
    from .closed_loop_contract import evidence_version
    require(isinstance(initial_template, dict) and isinstance(runtime_plan, dict), "LOOP_EXECUTOR_POLICY")
    critics = [j for j in runtime_plan.get("jobs", []) if isinstance(j, dict) and j.get("job_id") == "r0-critic"]
    require(len(critics) == 1 and critics[0].get("kind") == "review"
            and critics[0].get("payload_digest") == digest(initial_template), "LOOP_EXECUTOR_POLICY")
    fields = EXECUTOR_TEMPLATE_FIELDS.intersection(initial_template)
    if not fields:
        evidence_version(runtime_plan, initial_template)
        return None
    require(fields in (EXECUTOR_FIELDS, EXECUTOR_TEMPLATE_FIELDS) and type(initial_template["executor_contract_version"]) is int
            and initial_template["executor_contract_version"] == 1, "LOOP_EXECUTOR_VERSION")
    digest_ref(initial_template["executor_policy_sha256"])
    # Check the unchanged underlying policy against a derived copy only. The
    # original template digest was authenticated above; no DB value is edited.
    base = {k:v for k,v in initial_template.items() if k not in EXECUTOR_TEMPLATE_FIELDS}
    derived = copy.deepcopy(runtime_plan)
    next(j for j in derived["jobs"] if j["job_id"] == "r0-critic")["payload_digest"] = digest(base)
    require(evidence_version(derived, base) == 2, "LOOP_EXECUTOR_VERSION")
    return 1


def _core(delivered):
    require(isinstance(delivered, dict), "LOOP_EXECUTOR_INPUT")
    core = delivered.get("core", delivered)
    require(isinstance(core, dict) and core.get("role") in {"work", "critic", "prerequisite_review"}
            and isinstance(core.get("view"), dict), "LOOP_EXECUTOR_ROLE_UNSUPPORTED")
    return core


@_pure_input
def loop_request(policy, delivered, dispatch_identity):
    """Exact bounded input; materials lane does not remove mandatory policy text."""
    base = _policy_shape(policy)
    shape(dispatch_identity, {"run_id", "job_id", "actor_ref", "attempt", "epoch"}, "LOOP_EXECUTOR_DISPATCH")
    for field in ("run_id", "job_id", "actor_ref"): ref(dispatch_identity[field])
    for field in ("attempt", "epoch"): integer(dispatch_identity[field], field, maximum=2**53-1)
    core = _core(delivered)
    view = core["view"]
    require(dispatch_identity["run_id"] == "task-run-" + digest([policy["task_id"], policy["revision"]])[:32]
            and core.get("job_id") == view.get("job_id") == dispatch_identity["job_id"]
            and view.get("task_id") == policy["task_id"] and type(view.get("revision")) is int
            and view["revision"] == policy["revision"] and view.get("parent_input_digest") == policy["parent_input_digest"]
            and view.get("plan_digest") == policy["initial_specification_digest"], "LOOP_EXECUTOR_DISPATCH")
    require(view.get("view_digest") == digest({k:v for k,v in view.items() if k != "view_digest"}), "CLOSED_LOOP_VIEW_MISMATCH")
    from .closed_loop_context import _VIEW_KEYS, _RECORD_KEYS, _mandatory, _identity
    shape(view, _VIEW_KEYS, "CLOSED_LOOP_VIEW_INVALID")
    require(len(_raw(view)) <= MAX_INPUT_BYTES, "CLOSED_LOOP_CONTEXT_LIMIT")
    records = view.get("spans")
    require(isinstance(records, list) and len(records) <= 122, "CLOSED_LOOP_SELECTION_LIMIT")
    identities = set()
    for record in records:
        shape(record, _RECORD_KEYS, "CLOSED_LOOP_VIEW_INVALID")
        digest_ref(record["source_key"])
        integer(record["source_revision"], "view Source revision", minimum=0, maximum=2**53-1)
        integer(record["start"], "view start", minimum=0, maximum=12000)
        integer(record["end"], "view end", maximum=12000)
        text(record["text"], 12000, "CLOSED_LOOP_VIEW_INVALID")
        require(record["end"]-record["start"] == len(record["text"])
                and record["sha256"] == hashlib.sha256(record["text"].encode()).hexdigest()
                and _identity(record) not in identities, "CLOSED_LOOP_VIEW_INVALID")
        identities.add(_identity(record))
    require({_identity(span) for span,_ in _mandatory({"version": 2, "objective": view["objective"]})} <= identities,
            "CLOSED_LOOP_OBJECTIVE_REQUIRED")
    materials = []
    require(isinstance(policy["materials"], list) and len(policy["materials"]) <= 2, "LOOP_EXECUTOR_MATERIAL_LIMIT")
    for material in policy["materials"]:
        require(Path(material["path"]) == base.joinpath(*_relative(material["relative_path"])), "LOOP_EXECUTOR_PATH")
        for record in records:
            require(isinstance(record, dict), "CLOSED_LOOP_VIEW_INVALID")
            text(record.get("text"), 12000, "CLOSED_LOOP_VIEW_INVALID")
            raw = record["text"].encode("utf-8")
            if (record.get("source_key"), record.get("source_revision")) == (material["source_key"], material["source_revision"]):
                if (type(record.get("start")) is int and record["start"] == 0 and type(record.get("end")) is int
                    and record["end"] == len(record["text"]) and len(raw) == material["bytes"]
                    and record.get("sha256") == material["sha256"] == hashlib.sha256(raw).hexdigest()):
                    materials.append(copy.deepcopy(material)); break
    result = {"kind": "task_loop_executor_request", "version": 1, "executor_policy_sha256": digest(policy),
              "role": core["role"], "dispatch": dispatch_identity, "input": delivered, "materials": materials}
    raw = _raw(result)
    require(len(raw) <= MAX_INPUT_BYTES, "LOOP_EXECUTOR_INPUT_LIMIT")
    return raw


@_pure_input
def loop_schema(delivered):
    """Dynamic shape only; existing report/critic validators retain semantics."""
    from .task_schemas import obj, report_schema
    core = _core(delivered)
    if core["role"] == "work": return report_schema(core["job_id"])
    pre = core["role"] == "prerequisite_review"
    criteria = core.get("gate") if pre else list(core.get("criteria", {}))
    reports = {delivered["report"]["job_id"]: delivered["report"]} if pre else delivered.get("reports")
    require(isinstance(criteria, list) and criteria and len(criteria) <= 64
            and all(isinstance(c, str) for c in criteria) and isinstance(reports, dict)
            and 1 <= len(reports) <= 6, "LOOP_EXECUTOR_SCHEMA")
    require(len(set(criteria)) == len(criteria), "LOOP_EXECUTOR_SCHEMA")
    evidence = obj({"job_id": {"type": "string", "enum": sorted(reports)},
                    "claim_index": {"type": "integer", "minimum": 0, "maximum": 29}})
    row = {"criterion_id": {"type": "string", "enum": sorted(criteria)},
           "status": {"type": "string", "enum": ["passed", "failed", "unknown"] if pre else ["passed", "failed", "blocked", "not_run"]},
           "evidence": {"type": "array", "items": evidence, "maxItems": 30}}
    if not pre:
        row.update(gap_reason={"type": ["string", "null"], "maxLength": 1000}, source_spans={"type": "array", "maxItems": 32,
            "items": obj({"source_key": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                          "source_revision": {"type": "integer", "minimum": 0},
                          "start": {"type": "integer", "minimum": 0}, "end": {"type": "integer", "minimum": 1}})})
    validations = {"type": "array", "items": obj(row), "minItems": len(criteria), "maxItems": len(criteria)}
    if pre:
        return obj({"kind": {"type": "string", "const": "prerequisite_review"}, "version": {"type": "integer", "const": 1},
            "descriptor_sha256": {"type": "string", "const": delivered["descriptor_sha256"]},
            "report_sha256": {"type": "string", "const": delivered["report_sha256"]}, "validations": validations})
    require(delivered.get("report_digests") == {job:digest(report) for job,report in reports.items()}, "LOOP_EXECUTOR_SCHEMA")
    return obj({"parent_input_digest": {"type": "string", "const": core["view"]["parent_input_digest"]},
        "plan_digest": {"type": "string", "const": core["view"]["plan_digest"]},
        "round": {"type": "integer", "const": core["round"]},
        "report_digests": obj({job:{"type": "string", "const": digest(report)} for job,report in reports.items()}),
        "validations": validations})


def verify_fixture_runtime(value, attempt_directory, *, expected_input, expected_schema,
                           expected_executable, expected_identity, current_guard, freeze=False,
                           maximum_bytes=MAX_PROOF_BYTES):
    """Technical pipe/process/protocol proof; never native profile or consumption."""
    from .codex import (_paths, _event_identity, _runtime_receipt, _redact, _result_from_message,
                        _validate_schema, _build_command, MODEL, EFFORT, SANDBOX)
    from .task_runner import read_bytes, safe_directory, _verify_recorded_input, _validate_expected_input
    require(type(freeze) is bool, "LOOP_EXECUTOR_PROOF_OPTIONS")
    integer(maximum_bytes, "proof bytes", maximum=MAX_PROOF_BYTES)
    _validate_expected_input(expected_input)
    require(callable(current_guard), "LOOP_EXECUTOR_CURRENT_GUARD")
    original_packet = _raw(value)
    require(len(original_packet) <= MAX_PROOF_BYTES, "LOOP_EXECUTOR_PROOF_LIMIT")
    expected_schema, expected_identity = copy.deepcopy(expected_schema), copy.deepcopy(expected_identity)
    current_guard()
    require(isinstance(value, dict) and (set(value) == _RUNTIME or set(value) == _RUNTIME | _RUNTIME_HASHES), "LOOP_EXECUTOR_RUNTIME")
    require(freeze or set(value) == _RUNTIME | _RUNTIME_HASHES, "LOOP_EXECUTOR_RUNTIME_HASH_REQUIRED")
    base = safe_directory(attempt_directory)
    supplied = value["paths"]
    require(isinstance(supplied, dict) and isinstance(supplied.get("attempt_dir"), str), "RUN_RUNTIME_PATH_CHANGED")
    attempt = Path(supplied["attempt_dir"])
    require(attempt.parent == base and attempt.name.startswith("attempt-"), "RUN_RUNTIME_PATH_CHANGED")
    paths = _paths(safe_directory(attempt), record_input=True)
    require(supplied == {key:str(path) for key,path in paths.items()}, "RUN_RUNTIME_PATH_CHANGED")
    files, total = {}, 0
    def read(path, maximum=MAX_PROOF_BYTES):
        nonlocal total
        raw = read_bytes(path, min(maximum, maximum_bytes-total) if path not in files else min(maximum, len(files[path])))
        if path in files: require(raw == files[path], "RUN_RUNTIME_ARTIFACT_CHANGED")
        else: files[path] = raw; total += len(raw)
        return raw
    receipt_raw = read(paths["receipt"])
    receipt = _json(receipt_raw)
    receipt_sha = hashlib.sha256(receipt_raw).hexdigest()
    require(receipt == value["receipt"] and ("runtime_receipt_sha256" not in value or value["runtime_receipt_sha256"] == receipt_sha),
            "RUN_RUNTIME_RECEIPT_CHANGED")
    require(type(receipt.get("exit_code")) is int and receipt["exit_code"] == 0
            and receipt.get("completed") is True and receipt.get("completed_output_matches") is True
            and receipt.get("permission_probe") is None and receipt.get("permission_profile_sha256") is None
            and receipt.get("peer_tools") == [] and receipt.get("peer_write_authorized") is False, "LOOP_EXECUTOR_RUNTIME_SCOPE")
    require(isinstance(receipt.get("artifact_digests"), dict) and set(receipt["artifact_digests"]) == _DIGESTS, "RUN_RUNTIME_RECEIPT_INVALID")
    for key in sorted(_DIGESTS):
        require(hashlib.sha256(read(paths[key], MAX_INPUT_BYTES if key == "input" else MAX_PROOF_BYTES)).hexdigest()
                == receipt["artifact_digests"][key], "RUN_RUNTIME_ARTIFACT_CHANGED")
    _verify_recorded_input(receipt, paths, expected_input)
    require(_json(files[paths["schema"]]) == expected_schema and _json(files[paths["result"]]) == value["result"], "LOOP_EXECUTOR_RESULT")
    try: _validate_schema(value["result"], expected_schema)
    except ValueError as exc: raise SwarmError("LOOP_EXECUTOR_SCHEMA", "result shape mismatch") from exc
    shape(expected_identity, {"kind", "pid", "created_at"}, "LOOP_EXECUTOR_PROCESS")
    require(expected_identity["kind"] == "process", "LOOP_EXECUTOR_PROCESS")
    integer(expected_identity["pid"], "process pid", maximum=2**53-1)
    stamp = expected_identity["created_at"]
    require(type(stamp) in (int,float) and math.isfinite(stamp) and stamp > 0, "LOOP_EXECUTOR_PROCESS")
    process = _json(files[paths["process"]])
    require(type(process.get("pid")) is int and type(receipt.get("pid")) is int
            and process["pid"] == receipt["pid"] == expected_identity["pid"], "RUN_RUNTIME_IDENTITY_CHANGED")
    for item in (process, receipt):
        actual = item.get("created_at")
        require(type(actual) in (int,float) and math.isfinite(actual) and abs(actual-stamp) <= .001, "RUN_RUNTIME_IDENTITY_CHANGED")
    events = [_json(line) for line in files[paths["events"]].splitlines() if line.strip()]
    require(all(isinstance(event, dict) and isinstance(event.get("type"), str) and event["type"]
                for event in events), "LOOP_EXECUTOR_STDOUT_COMPLETION")
    require(all(event["type"] not in {"event_msg", "event.message"} or
                (isinstance(event.get("payload"), dict) and isinstance(event["payload"].get("type"), str))
                for event in events), "LOOP_EXECUTOR_STDOUT_COMPLETION")
    # A saved success receipt cannot replace the child's actual completion
    # event or hide a conflicting failure in the same bounded stdout stream.
    failed = {"error", "turn.error", "turn.failed", "task_failed", "turn_failed", "turn_error"}
    require(sum(event["type"] == "turn.completed" for event in events) == 1
            and not any(event["type"] in failed or
                (event["type"] in {"event_msg", "event.message"}
                 and isinstance(event.get("payload"), dict) and event["payload"].get("type") in failed)
                for event in events), "LOOP_EXECUTOR_STDOUT_COMPLETION")
    for event in events:
        for source in (event, event.get("payload")):
            if isinstance(source, dict):
                require(all(field not in source or (isinstance(source[field], str) and source[field])
                            for field in ("thread_id", "session_id", "turn_id")), "RUN_RUNTIME_IDENTITY_CHANGED")
                require("thread_id" not in source or "session_id" not in source
                        or source["thread_id"] == source["session_id"], "RUN_RUNTIME_IDENTITY_CHANGED")
    thread, turn = _event_identity(events)
    require(thread == receipt.get("thread_id") and turn == receipt.get("turn_id"), "RUN_RUNTIME_IDENTITY_CHANGED")
    executable = Path(expected_executable)
    require(executable.is_absolute() and executable.suffix == ".py", "LOOP_EXECUTOR_EXECUTABLE_UNSUPPORTED")
    command = _json(files[paths["command"]])
    require(command == {"argv": _build_command([sys.executable, "-u", str(executable)],
        schema_path=paths["schema"], last_message_path=paths["last_message"]), "shell": False, "cwd": str(attempt)}, "RUN_RUNTIME_PATH_CHANGED")
    require(process.get("cwd") == receipt.get("runtime_cwd") == str(attempt), "RUN_RUNTIME_PATH_CHANGED")
    rollout = Path(receipt.get("runtime_receipt_path", ""))
    sessions = safe_directory(base / "sessions")
    require(rollout.is_absolute() and rollout.parent == sessions, "RUN_RUNTIME_PATH_CHANGED")
    raw = read(rollout)
    rollout_sha = hashlib.sha256(raw).hexdigest()
    require("runtime_rollout_sha256" not in value or value["runtime_rollout_sha256"] == rollout_sha, "RUN_RUNTIME_ROLLOUT_CHANGED")
    try:
        started_at = datetime.fromisoformat(receipt["started_at"].replace("Z", "+00:00"))
        require(started_at.tzinfo is not None, "LOOP_EXECUTOR_RUNTIME")
        runtime = _runtime_receipt(thread, turn, sessions, attempt, started_at.timestamp(), exact_record=(rollout, raw))
    except (ValueError, KeyError, TypeError) as exc:
        raise SwarmError("RUN_RUNTIME_BINDING_CHANGED", "runtime binding is malformed") from exc
    require(runtime is not None and runtime["runtime_receipt_path"] == str(rollout) and not runtime["turn_failed"]
            and runtime["model"] == MODEL and runtime["effort"] == EFFORT and runtime["sandbox"] == SANDBOX
            and runtime["approval_policy"] == "never"
            and _redact(_result_from_message(runtime["completed_output"])) == value["result"], "RUN_RUNTIME_BINDING_CHANGED")
    require(runtime.get("permission_profile") is None and runtime.get("active_permission_profile") is None,
            "LOOP_EXECUTOR_RUNTIME_SCOPE")
    require(all(receipt.get(key) == expected for keys,expected in [
        (("model_requested", "model_observed", "model"), MODEL),
        (("effort_requested", "effort_observed", "effort"), EFFORT),
        (("sandbox_requested", "sandbox_observed", "sandbox"), SANDBOX)] for key in keys)
        and receipt.get("approval_policy") == "never", "RUN_RUNTIME_BINDING_CHANGED")
    read(paths["diagnostics"])
    current_guard()
    # Guard callbacks, schema/rollout parsing and late source checks cannot
    # change the raw input/proof and then have freeze bless new bytes.
    for path in list(files): read(path, MAX_INPUT_BYTES if path == paths["input"] else MAX_PROOF_BYTES)
    _verify_recorded_input(receipt, paths, expected_input)
    require(_raw(value) == original_packet, "LOOP_EXECUTOR_PACKET_CHANGED")
    if freeze: value.update(runtime_receipt_sha256=receipt_sha, runtime_rollout_sha256=rollout_sha)
    return total


def verify_loop_response(value, *, policy, delivered, dispatch_identity, expected_attempt,
                         expected_schema, current_guard, attempt_directory, freeze=False,
                         maximum_bytes=MAX_PROOF_BYTES):
    """Bind a technical response to caller-authenticated dispatch/attempt values."""
    shape(value, {"result", "receipt"}, "LOOP_BACKEND_INVALID")
    receipt = value["receipt"]
    shape(receipt, _RECEIPT, "LOOP_RECEIPT_INVALID")
    prompt = loop_request(policy, delivered, dispatch_identity)
    require(receipt["actor_ref"] == dispatch_identity["actor_ref"] == expected_attempt.get("worker_ref")
            and receipt["input_digest"] == digest(delivered) and receipt["synthetic"] is True
            and type(receipt["executor_contract_version"]) is int and receipt["executor_contract_version"] == 1
            and receipt["executor_policy_sha256"] == digest(policy) and type(receipt["prompt_contract_version"]) is int
            and receipt["prompt_contract_version"] == 1 and receipt["prompt_sha256"] == hashlib.sha256(prompt).hexdigest(), "LOOP_INPUT_RECEIPT_MISMATCH")
    for field in ("run_id", "job_id", "attempt", "epoch"):
        require(type(expected_attempt.get(field)) is type(dispatch_identity[field])
                and expected_attempt[field] == dispatch_identity[field], "LOOP_EXECUTOR_DISPATCH")
    runtime = receipt["runtime"]
    require(isinstance(runtime, dict) and isinstance(runtime.get("receipt"), dict)
            and value["result"] == runtime.get("result")
            and receipt["invocation_ref"] == runtime["receipt"].get("thread_id"), "LOOP_EXECUTOR_RUNTIME")
    require(_raw(expected_schema) == _raw(loop_schema(delivered)), "LOOP_EXECUTOR_SCHEMA")
    original = copy.deepcopy(value)
    inputs = _raw([policy, delivered, dispatch_identity, expected_attempt, expected_schema])
    total = verify_fixture_runtime(runtime, attempt_directory, expected_input=prompt, expected_schema=expected_schema,
        expected_executable=policy["executable"]["path"], expected_identity=expected_attempt.get("identity"),
        current_guard=current_guard, freeze=freeze, maximum_bytes=maximum_bytes)
    if freeze:
        original["receipt"]["runtime"].update({key: runtime[key] for key in _RUNTIME_HASHES})
    require(_raw(value) == _raw(original)
            and inputs == _raw([policy, delivered, dispatch_identity, expected_attempt, expected_schema]), "LOOP_EXECUTOR_PACKET_CHANGED")
    return total
