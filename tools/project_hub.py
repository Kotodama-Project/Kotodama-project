"""Read-only Project brief projection over operator-selected existing Task owners.

No persistence, admission, grant, dispatch, or Task-state mutation. Local inputs
are trusted operator selections, not authentication or an external MCP surface.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import time
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / "tools", ROOT / "runtime"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from project_agent_status import InputError, bounded, load_json
from task_swarm.owner_file import OwnerFile
from task_swarm.protocol import SwarmError, digest, digest_ref, finite, integer, ref
from task_swarm.task_contract import shape, text, validate_input

TASK_ID = re.compile(r"task-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
BRIEF_FIELDS = {"outcome", "in_scope", "out_of_scope", "constraints", "acceptance", "unknowns"}
PROJECT_FIELDS = {"version", "project_id", "revision", "owner_ref", "name", "original_ref", "brief", "task_refs"}
Resolver = Callable[[str], tuple[dict, dict]]


def require(condition: bool, code: str) -> None:
    if not condition:
        raise SwarmError(code, "Project input refused")


def validate_project(value: dict) -> dict:
    """Validate a candidate/read snapshot, never establish its authority."""
    bounded(value)
    shape(value, PROJECT_FIELDS, "PROJECT_INVALID")
    require(type(value["version"]) is int and value["version"] == 1, "PROJECT_VERSION_INVALID")
    for key in ("project_id", "owner_ref", "original_ref"):
        ref(value[key], key)
    integer(value["revision"], "Project revision", maximum=2**53 - 1)
    text(value["name"], 200, "PROJECT_NAME_INVALID")
    brief = value["brief"]
    shape(brief, BRIEF_FIELDS, "PROJECT_BRIEF_INVALID")
    text(brief["outcome"], 4000, "PROJECT_OUTCOME_INVALID")
    for key in BRIEF_FIELDS - {"outcome"}:
        require(isinstance(brief[key], list) and len(brief[key]) <= 20, "PROJECT_BRIEF_INVALID")
        for item in brief[key]:
            text(item, 1000, "PROJECT_BRIEF_INVALID")
        require(len(set(brief[key])) == len(brief[key]), "PROJECT_BRIEF_DUPLICATE")
    require(isinstance(value["task_refs"], list) and len(value["task_refs"]) <= 50, "PROJECT_TASK_LIMIT")
    seen = set()
    for task in value["task_refs"]:
        shape(task, {"task_id", "owner_ref", "revision", "context_digest"}, "PROJECT_TASK_INVALID")
        require(isinstance(task["task_id"], str) and TASK_ID.fullmatch(task["task_id"]) is not None,
                "PROJECT_TASK_INVALID")
        require(task["task_id"] not in seen, "PROJECT_TASK_DUPLICATE")
        seen.add(task["task_id"])
        ref(task["owner_ref"], "Task owner")
        integer(task["revision"], "Task revision", maximum=2**53 - 1)
        digest_ref(task["context_digest"])
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def project_view(project: dict, resolve: Resolver, *, now: float) -> dict:
    """Resolve each Task afresh; omit its contents on any failed binding check.

    Re-reading detects changes within each observation, not an atomic snapshot
    across all owners. Execution must revalidate at its own boundary.
    """
    project = validate_project(project)
    finite(now, "observation clock")
    tasks = []
    for selected in project["task_refs"]:
        row = {**selected, "resolution": "unresolved"}
        try:
            binding, payload = resolve(selected["task_id"])
            bounded(binding)
            bounded(payload)
            payload = validate_input(payload, binding, now=now)
            require(binding["owner_ref"] == selected["owner_ref"], "PROJECT_OWNER_MISMATCH")
            require(payload["task_id"] == selected["task_id"], "WRONG_TASK")
            require(payload["revision"] == selected["revision"], "PROJECT_TASK_STALE")
            require(digest(payload) == selected["context_digest"], "PROJECT_CONTEXT_MISMATCH")
            observed = digest([binding, payload])
            latest_binding, latest_payload = resolve(selected["task_id"])
            bounded(latest_binding)
            bounded(latest_payload)
            validate_input(latest_payload, latest_binding, now=now)
            require(digest([latest_binding, latest_payload]) == observed, "PROJECT_TASK_CHANGED")
            row.update(resolution="resolved", request=payload["request"],
                       acceptance=payload["acceptance"],
                       source_refs=[{k: source[k] for k in ("key", "revision", "sha256")}
                                    for source in payload["sources"]],
                       objective=payload.get("objective"),
                       binding_status=binding["status"],
                       completion="not_observed", artifacts="not_observed")
        except SwarmError as exc:
            row["reason_code"] = exc.code
        except (OSError, InputError):
            row["reason_code"] = "PROJECT_INPUT_UNAVAILABLE"
        tasks.append(row)
    return {"kind": "kotodama.project-view", "version": 1, "authority": "read_only_projection",
            "observed_at": now, "project": project, "project_digest": digest(project),
            "tasks": tasks, "unresolved_count": sum(t["resolution"] != "resolved" for t in tasks),
            "completion": "not_observed", "execution_authorized": False}


def inspect_change(project: dict, proposal: dict) -> dict:
    """Check a brief-edit candidate against exact caller-selected base bytes.

    Does not save a new revision or approve a weaker requirement. The owner must
    reread, authorize and append its correction event before any adoption.
    """
    project = validate_project(project)
    bounded(proposal)
    shape(proposal, {"version", "project_id", "expected_revision", "base_digest",
                     "reason", "source_ref", "brief"}, "PROJECT_CHANGE_INVALID")
    require(type(proposal["version"]) is int and proposal["version"] == 1, "PROJECT_CHANGE_INVALID")
    integer(proposal["expected_revision"], "expected revision", maximum=2**53 - 1)
    require(proposal["project_id"] == project["project_id"], "PROJECT_ID_MISMATCH")
    require(proposal["expected_revision"] == project["revision"], "PROJECT_REVISION_STALE")
    require(proposal["base_digest"] == digest(project), "PROJECT_BASE_MISMATCH")
    text(proposal["reason"], 1000, "PROJECT_CHANGE_REASON_INVALID")
    ref(proposal["source_ref"], "change source")
    candidate = validate_project({**project, "brief": proposal["brief"]})
    changed = sorted(k for k in BRIEF_FIELDS if candidate["brief"][k] != project["brief"][k])
    require(bool(changed), "PROJECT_CHANGE_EMPTY")
    removed = {k: [item for item in project["brief"][k] if item not in candidate["brief"][k]]
               for k in ("constraints", "acceptance")}
    return {"kind": "kotodama.project-change-candidate", "version": 1,
            "authority": "candidate_only", "project_id": project["project_id"],
            "expected_revision": project["revision"], "base_digest": digest(project),
            "proposal_digest": digest(proposal), "proposal": proposal,
            "changed_fields": changed, "removed_requirements": removed,
            "impact_task_refs": project["task_refs"], "applied": False,
            "next_action": "owner_revalidate_authorize_and_record_correction"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("view", "inspect-change"))
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--task", nargs=3, action="append", default=[],
                        metavar=("TASK_ID", "OWNER_JSON", "INPUT_JSON"))
    parser.add_argument("--proposal", type=Path)
    args = parser.parse_args(argv)
    try:
        project = load_json(args.project)
        if args.operation == "inspect-change":
            require(args.proposal is not None and not args.task, "PROJECT_ARGUMENTS_INVALID")
            result = inspect_change(project, load_json(args.proposal))
        else:
            require(args.proposal is None, "PROJECT_ARGUMENTS_INVALID")
            selections = {}
            for task_id, owner_path, input_path in args.task:
                require(task_id not in selections, "PROJECT_TASK_DUPLICATE")
                selections[task_id] = (OwnerFile(owner_path), Path(input_path))
            selected_ids = {t["task_id"] for t in validate_project(project)["task_refs"]}
            require(set(selections).issubset(selected_ids), "PROJECT_TASK_UNEXPECTED")

            def resolve(task_id: str) -> tuple[dict, dict]:
                require(task_id in selections, "PROJECT_OWNER_UNSELECTED")
                owner, input_path = selections[task_id]
                try:
                    binding = owner.read_task(task_id)
                except (TypeError, ValueError, RecursionError) as exc:
                    # The existing owner reader assumes some nested JSON types.
                    # Contain malformed selections at this adapter boundary so
                    # one unavailable owner cannot suppress other observations.
                    raise SwarmError("PROJECT_OWNER_INVALID", "owner input refused") from exc
                return binding, load_json(input_path)

            result = project_view(project, resolve, now=time.time())
        # Detect observed edits of either caller-selected input during the read.
        require(digest(load_json(args.project)) == digest(project), "PROJECT_CHANGED_DURING_READ")
        if args.proposal is not None:
            require(digest(load_json(args.proposal)) == result["proposal_digest"], "PROJECT_CHANGED_DURING_READ")
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (SwarmError, InputError, OSError) as exc:
        print(json.dumps({"status": "REFUSED", "reason_code": exc.code if isinstance(exc, SwarmError)
                          else "PROJECT_INPUT_UNAVAILABLE"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
