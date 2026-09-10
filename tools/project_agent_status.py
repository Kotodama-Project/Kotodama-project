"""Offline, read-only diagnostic projection; never an authority or live adapter.

Consumes the existing agent registry and OpenMaus integration contract. Optional
observations are caller-supplied reports, not authenticated runtime evidence.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = "governance/agent-registry.json"
CONTRACT = "governance/openmaus-integration.json"
SKILL = "skills/kotodama-agent-status/SKILL.md"
BUNDLE = ("tools/project_agent_status.py", CONTRACT, SKILL)
MAX_BYTES = 1_048_576
MAX_ITEMS = 1000
MAX_NODES = 50_000
NEXT_STEPS = {
    "runtime_unbound": "Inspect the existing implementation binding; do not activate a runtime from this report.",
    "registry_not_active": "Review the registry activation gates with the existing owner; do not change authority here.",
    "observation_missing": "Obtain a snapshot only through an already-authorized observer; absence is not offline.",
    "adapter_report_not_authenticated": "Check provenance and source access with the trusted observer; freshness is not authenticity.",
    "observation_future": "Reconcile the observer timestamp and evaluation clock before using this observation.",
    "observation_stale": "Request a current authorized snapshot; do not reuse this expired state for decisions.",
    "cancellation_not_observed": "Reconcile the exact Work/run stop observation; a cancelled label is not stop confirmation.",
    "producer_verification_not_accepted": "Route the exact result to the independent verifier; do not accept producer self-verification.",
    "stop_confirmation_missing": "Reconcile the existing stop request and exact Work/run; do not blindly retry or restart.",
}
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/@#-]{0,255}\Z")
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)\Z")
OBS_FIELDS = {
    "kotodama_agent_id", "observation_ref", "adapter_id", "observed_at",
    "connection_state", "current_work_ref", "run_ref", "work_state",
    "stop_requested_at", "stop_observed_at",
}


class InputError(ValueError):
    """An input cannot safely be projected; messages never echo input contents."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise InputError(message)


def timestamp(value: Any) -> datetime:
    require(isinstance(value, str) and TIMESTAMP.fullmatch(value) is not None,
            "timestamp must be offset-aware RFC3339")
    require(not value.endswith("-00:00"), "unknown timestamp offset is not supported")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise InputError("invalid timestamp") from exc


def token(value: Any) -> bool:
    return isinstance(value, str) and TOKEN.fullmatch(value) is not None


def file_identity(info: os.stat_result) -> tuple[int, ...]:
    # Do not include atime: reading a file may legitimately update it.
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def regular_bytes(path: Path) -> bytes:
    """Bound a stable regular-file read; reject observed replacement or mutation.

    This is not an atomic filesystem snapshot or an authorization boundary against
    a hostile process swapping ancestors. Use trusted, access-controlled inputs.
    """
    absolute = path.absolute()
    for entry in (absolute, *absolute.parents):
        info = entry.lstat()
        require(not stat.S_ISLNK(info.st_mode)
                and not (getattr(info, "st_file_attributes", 0)
                         & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)),
                "linked input is not supported")
    before = absolute.lstat()
    require(stat.S_ISREG(before.st_mode), "input must be a regular file")
    require(before.st_size <= MAX_BYTES, "input exceeds size limit")
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    # Binary mode matters when reading Windows files through an OS descriptor.
    flags |= getattr(os, "O_BINARY", 0)
    fd = os.open(absolute, flags)
    try:
        opened = os.fstat(fd)
        require(file_identity(opened) == file_identity(before), "input changed during read")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(MAX_BYTES + 1)
        require(len(data) <= MAX_BYTES, "input exceeds size limit")
        require(len(data) == opened.st_size
                and file_identity(os.fstat(fd)) == file_identity(opened)
                and file_identity(absolute.lstat()) == file_identity(opened),
                "input changed during read")
        return data
    finally:
        os.close(fd)


def bounded(value: Any, depth: int = 0) -> None:
    """Bound aggregate work as well as depth/width, including the pure API.

    A repeated-reference DAG or cycle supplied directly must not cause unbounded
    traversal. Only JSON values and Unicode scalar strings are accepted.
    """
    stack = [(value, depth)]
    nodes = 0
    text_bytes = 0
    while stack:
        item, level = stack.pop()
        nodes += 1
        require(nodes <= MAX_NODES, "JSON node count exceeds limit")
        require(level <= 24, "JSON nesting exceeds limit")
        if isinstance(item, str):
            require(len(item) <= MAX_BYTES, "JSON text exceeds limit")
            try:
                text_bytes += len(item.encode("utf-8"))
            except UnicodeError as exc:
                raise InputError("invalid Unicode scalar string") from exc
            require(text_bytes <= MAX_BYTES, "JSON text exceeds limit")
        elif isinstance(item, dict):
            require(len(item) <= MAX_ITEMS, "JSON object exceeds limit")
            require(all(isinstance(key, str) for key in item), "JSON keys must be strings")
            stack.extend((key, level + 1) for key in item)
            stack.extend((child, level + 1) for child in item.values())
        elif isinstance(item, list):
            require(len(item) <= MAX_ITEMS, "JSON array exceeds limit")
            stack.extend((child, level + 1) for child in item)
        elif isinstance(item, float):
            require(math.isfinite(item), "non-finite JSON value")
        else:
            require(item is None or type(item) in (int, bool), "non-JSON value")


def parse_json(data: bytes) -> dict[str, Any]:
    require(len(data) <= MAX_BYTES, "input exceeds size limit")
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def constant(_: str) -> None:
        raise InputError("non-finite JSON value")

    try:
        value = json.loads(data.decode("utf-8"),
                           object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, RecursionError) as exc:
        raise InputError("invalid JSON input") from exc
    require(isinstance(value, dict), "JSON root must be an object")
    bounded(value)
    return value


def load_json(path: Path) -> dict[str, Any]:
    return parse_json(regular_bytes(path))


def bundle_sha256(root: Path, contract_data: bytes | None = None) -> str:
    """Content identity, NOT authenticity, authorization, or an approval."""
    digest = hashlib.sha256(b"kotodama-agent-status-bundle-v1\0")
    for name in sorted(BUNDLE):
        path = name.encode("utf-8")
        data = contract_data if name == CONTRACT and contract_data is not None else regular_bytes(root / name)
        digest.update(len(path).to_bytes(8, "big") + path)
        digest.update(len(data).to_bytes(8, "big") + data)
    return digest.hexdigest()


def project(registry: dict[str, Any], contract: dict[str, Any],
            observations: dict[str, Any], *, as_of: str,
            max_age_seconds: int = 120) -> dict[str, Any]:
    """Pure snapshot projection. Caller must authorize source access separately.

    Checks consumed fields, not full registry/contract conformance (the existing
    validators remain responsible for that). Never mutates any supplied object.
    """
    now = timestamp(as_of)
    require(type(max_age_seconds) is int and 1 <= max_age_seconds <= 86400,
            "max age must be an integer between 1 and 86400 seconds")
    for document in (registry, contract, observations):
        require(isinstance(document, dict), "input must be an object")
        bounded(document)
        require(type(document.get("version")) is int and document["version"] == 1,
                "unsupported document version")
    require(registry.get("status") in ("candidate_only", "promoted"), "invalid registry status")
    require(contract.get("status") == "candidate_only", "unsupported integration contract status")
    view = contract.get("common_agent_view")
    work = contract.get("work_contract")
    adapters = contract.get("adapters")
    require(isinstance(view, dict) and isinstance(work, dict) and isinstance(adapters, dict),
            "missing integration contract sections")
    require(view.get("execution_completion_is_not_verification") is True
            and work.get("stop_request_requires_stop_observation") is True,
            "integration safety boundary changed")
    for values in (view.get("connection_states"), work.get("result_states")):
        require(isinstance(values, list) and bool(values) and all(token(v) for v in values),
                "invalid state vocabulary")
        require(len(values) == len(set(values)), "duplicate state vocabulary")
    require("unknown" in view["connection_states"]
            and {"execution_settled", "verification_pending", "verified_candidate", "cancelled"}
            <= set(work["result_states"]), "required states missing")
    require(isinstance(view.get("required_fields"), list)
            and all(token(v) for v in view["required_fields"]), "invalid common view fields")
    require(len(view["required_fields"]) == len(set(view["required_fields"])),
            "duplicate common view fields")
    agents = registry.get("agents")
    require(isinstance(agents, list) and bool(agents), "registry agents must be a nonempty array")
    by_id: dict[str, dict[str, Any]] = {}
    for agent in agents:
        require(isinstance(agent, dict) and token(agent.get("id")), "invalid registry agent")
        require(agent["id"] not in by_id, "duplicate registry agent identity")
        require(all(isinstance(agent.get(k), str) and bool(agent[k]) for k in ("name", "purpose")),
                "missing registry display fields")
        require(agent.get("activation_state") in ("planned", "candidate", "active", "disabled", "retired")
                and agent.get("authority") in ("read_only", "proposal_only", "bounded_execute"),
                "invalid registry activation or authority")
        impl = agent.get("implementation")
        require(isinstance(impl, dict) and impl.get("kind") in
                ("unbound", "script", "service", "workflow", "external_adapter"),
                "invalid implementation binding")
        require(impl.get("path") is None or isinstance(impl["path"], str), "invalid implementation path")
        by_id[agent["id"]] = agent
    require(set(observations) == {"version", "observations"}, "unknown observation envelope field")
    entries = observations["observations"]
    require(isinstance(entries, list), "observations must be an array")
    seen_refs: set[str] = set()
    seen_runs: set[tuple[str, str]] = set()
    by_agent: dict[str, dict[str, Any]] = {}
    for obs in entries:
        require(isinstance(obs, dict) and set(obs) == OBS_FIELDS, "invalid observation fields")
        require(all(token(obs[k]) for k in ("kotodama_agent_id", "observation_ref", "adapter_id")),
                "invalid observation identity")
        agent_id = obs["kotodama_agent_id"]
        require(agent_id in by_id, "observation refers to unregistered agent")
        require(agent_id not in by_agent, "multiple observations for one agent; reconcile upstream")
        require(obs["observation_ref"] not in seen_refs, "duplicate observation reference")
        require(obs["adapter_id"] in adapters, "unknown adapter")
        require(obs["connection_state"] in view["connection_states"], "unknown connection state")
        require(obs["work_state"] is None or obs["work_state"] in work["result_states"],
                "unknown work state")
        has_work = obs["work_state"] is not None
        require(all(token(obs[k]) if has_work else obs[k] is None
                    for k in ("current_work_ref", "run_ref")), "work and run binding required together")
        if has_work:
            run = (obs["current_work_ref"], obs["run_ref"])
            require(run not in seen_runs, "one run is attributed to multiple agents")
            seen_runs.add(run)
        observed = timestamp(obs["observed_at"])
        request, stopped = obs["stop_requested_at"], obs["stop_observed_at"]
        require(stopped is None or request is not None, "stop observation has no request binding")
        if request is not None:
            require(has_work and timestamp(request) <= observed, "invalid stop request binding or time")
        if stopped is not None:
            require(timestamp(request) <= timestamp(stopped) <= observed, "invalid stop observation time")
            require(obs["connection_state"] in ("idle", "offline", "interrupted")
                    and obs["work_state"] == "cancelled", "stop observation conflicts with running state")
        seen_refs.add(obs["observation_ref"])
        by_agent[agent_id] = obs
    rows = []
    for agent_id, agent in sorted(by_id.items()):
        row: dict[str, Any] = {
            "kotodama_agent_id": agent_id, "display_name": agent["name"],
            "purpose": agent["purpose"], "authority": agent["authority"],
            "activation_state": agent["activation_state"], "group_ids": [], "project_ids": [],
            "runtime_kind": agent["implementation"]["kind"], "runtime_location_ref": None,
            "connection_state": "unknown", "current_work_ref": None, "parent_work_ref": None,
            "last_observed_at": None, "artifact_refs": [], "verification_state": "not_evaluated",
            "cost_observation_ref": None, "execution_state": "unknown", "run_ref": None,
            "stop_state": "unknown", "observation_freshness": "missing",
            "source_observation_ref": None, "reported_connection_state": None,
            "reported_work_state": None, "adapter_id": None, "controls": [], "diagnostics": [],
        }
        require(set(view["required_fields"]) <= set(row), "common view contract changed; projector upgrade required")
        codes = row["diagnostics"]
        bound = (agent["implementation"]["kind"] != "unbound"
                 and bool(agent["implementation"].get("path")))
        if not bound:
            codes.append("runtime_unbound")
        if agent["activation_state"] != "active" or registry["status"] != "promoted":
            codes.append("registry_not_active")
        obs = by_agent.get(agent_id)
        if obs is None:
            codes.append("observation_missing")
        else:
            codes.append("adapter_report_not_authenticated")
            age = (now - timestamp(obs["observed_at"])).total_seconds()
            fresh = 0 <= age < max_age_seconds
            row.update(last_observed_at=obs["observed_at"], source_observation_ref=obs["observation_ref"],
                       reported_connection_state=obs["connection_state"], reported_work_state=obs["work_state"],
                       adapter_id=obs["adapter_id"],
                       observation_freshness="future" if age < 0 else "fresh" if fresh else "stale")
            if not fresh:
                codes.append("observation_future" if age < 0 else "observation_stale")
            if fresh and bound and "registry_not_active" not in codes:
                row.update(connection_state=obs["connection_state"], current_work_ref=obs["current_work_ref"],
                           run_ref=obs["run_ref"], execution_state=obs["work_state"] or "unknown",
                           stop_state="not_requested")
                if obs["work_state"] in ("verified_candidate", "verification_pending"):
                    row["execution_state"] = "execution_settled"
                if obs["stop_requested_at"] is not None:
                    row["stop_state"] = "observed" if obs["stop_observed_at"] else "requested"
                if obs["work_state"] == "cancelled" and obs["stop_observed_at"] is None:
                    row["execution_state"] = "unknown"
                    codes.append("cancellation_not_observed")
            if obs["work_state"] == "verified_candidate":
                codes.append("producer_verification_not_accepted")
            if obs["stop_requested_at"] is not None and obs["stop_observed_at"] is None:
                codes.append("stop_confirmation_missing")
        row["next_steps"] = [{"code": code, "action": NEXT_STEPS[code]} for code in codes]
        rows.append(row)
    return {
        "schema_revision": "agent-status-v2", "projection_kind": "offline_diagnostic_only",
        "as_of": now.isoformat(), "max_age_seconds": max_age_seconds,
        "access_evaluation": "not_evaluated_do_not_serve", "runtime_evidence_verified": False,
        "mutations_enabled": False, "independent_verification_performed": False,
        "agents": rows,
        "summary": {"registered_agents": len(rows), "supplied_observations": len(entries),
                    "agents_with_diagnostics": sum(bool(r["diagnostics"]) for r in rows),
                    "observation_freshness": {
                        state: sum(r["observation_freshness"] == state for r in rows)
                        for state in ("missing", "stale", "future", "fresh")}},
    }


def markdown(report: dict[str, Any]) -> str:
    # JSON string escaping keeps controls/newlines inert; HTML and pipes are escaped.
    def cell(value: Any) -> str:
        import html
        return html.escape(json.dumps(value, ensure_ascii=False)).replace("|", "&#124;")
    lines = ["# Agent status — offline diagnostic projection", "",
             "Not live evidence, authorization, or independent verification. No mutation controls.", "",
             "| Agent | Registry | Connection | Execution | Freshness | Diagnostics | Next step |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in report["agents"]:
        lines.append("| " + " | ".join(cell(row[k]) for k in
                     ("kotodama_agent_id", "activation_state", "connection_state", "execution_state",
                      "observation_freshness", "diagnostics", "next_steps")) + " |")
    return "\n".join(lines) + "\n"


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, "invalid arguments; use --help\n")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = SafeArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--as-of", help="RFC3339 instant; pin for reproducible output")
    parser.add_argument("--max-age-seconds", type=int, default=120)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--bundle-sha256", action="store_true")
    parser.add_argument("--expected-bundle-sha256")
    args = parser.parse_args(argv)
    try:
        # Code and skill are always identified from this implementation, never a substituted --root.
        contract_data = regular_bytes(args.root / CONTRACT)
        digest = bundle_sha256(ROOT, contract_data)
        if args.expected_bundle_sha256 is not None:
            require(args.expected_bundle_sha256 == digest, "skill/implementation bundle mismatch")
        if args.bundle_sha256:
            print(digest)
            return 0
        registry_data = regular_bytes(args.root / REGISTRY)
        observation_data = regular_bytes(args.observations) if args.observations else None
        report = project(parse_json(registry_data), parse_json(contract_data),
                         parse_json(observation_data) if observation_data is not None else {"version": 1, "observations": []},
                         as_of=args.as_of or datetime.now(timezone.utc).isoformat(),
                         max_age_seconds=args.max_age_seconds)
        report["bundle_sha256"] = digest
        report["input_sha256"] = {
            "registry": hashlib.sha256(registry_data).hexdigest(),
            "contract": hashlib.sha256(contract_data).hexdigest(),
            "observations": hashlib.sha256(observation_data).hexdigest() if observation_data is not None else None,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.format == "json" else markdown(report), end="\n" if args.format == "json" else "")
        # Exit 0 means projection succeeded, not healthy/deployed/authorized.
        return 0
    except (InputError, OSError, ValueError, TypeError, RecursionError) as exc:
        message = str(exc) if isinstance(exc, InputError) else "input unavailable or invalid"
        print(json.dumps({"error": message, "mutations_enabled": False}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
