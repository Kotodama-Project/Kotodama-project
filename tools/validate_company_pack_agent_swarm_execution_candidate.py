"""Read-only preflight for the public Kotodama agent-swarm candidate.

This validator checks a bounded, opaque swarm *plan*.  It does not resolve a
task, inspect a private workspace, spawn an agent, call Codex, send a message,
invoke a provider/device/public route, write a receipt, grant authority, or
promote Current Truth.  A successful result means only that the candidate's
structure and internal comparisons are coherent enough for a later, separately
authorized implementation review.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # pragma: no cover - dependency-free installs fail closed
    Draft202012Validator = None  # type: ignore[assignment,misc]
    FormatChecker = None  # type: ignore[assignment,misc]


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "company-pack-agent-swarm-execution-candidate.schema.json"
MAX_INPUT_BYTES = 1_048_576
MAX_WINDOW_SECONDS = 86_400
OPAQUE_REF = re.compile(r"^ref/[a-z0-9][a-z0-9/_-]{1,510}$")
SHA1 = re.compile(r"^[0-9a-f]{40}$")

STOP_CONDITIONS = [
    "parent_edge_mismatch",
    "assignment_identity_mismatch",
    "workspace_or_revision_drift",
    "handoff_binding_mismatch",
    "lease_expired_or_epoch_drift",
    "child_timeout_or_cancel",
    "output_binding_missing",
    "external_effect_detected",
]

REVIEW_TRIGGERS = [
    "root_orchestrator_identity_change",
    "budget_or_wave_change",
    "assignment_role_objective_or_ownership_change",
    "parent_edge_or_handoff_change",
    "workspace_or_revision_change",
    "lease_ttl_epoch_or_dedup_change",
    "stop_condition_or_expected_output_change",
    "verifier_reserve_or_acceptance_change",
    "schema_change",
    "request_expiry",
]

CLAIM_FIELDS = [
    "plan_verified",
    "budget_verified",
    "orchestrator_identity_verified",
    "parent_edges_verified",
    "assignment_identity_verified",
    "workspace_binding_verified",
    "revision_current_verified",
    "handoff_verified",
    "lease_fencing_verified",
    "replay_prevented",
    "all_assignments_completed",
    "swarm_runtime_verified",
    "dispatch_executed",
    "external_effect_authorized",
    "external_effect_executed",
    "human_decision_verified",
    "promotion_verified",
    "current_truth_changed",
    "final_human_go",
    "public_beta_go",
]


class DuplicateKeyError(ValueError):
    pass


class InputTooLargeError(ValueError):
    pass


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError
        result[key] = value
    return result


def read_bounded(path: Path) -> bytes:
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise InputTooLargeError
    with path.open("rb") as stream:
        raw = stream.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise InputTooLargeError
    return raw


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _opaque_ref(value: Any) -> bool:
    return isinstance(value, str) and OPAQUE_REF.fullmatch(value) is not None


def _sha1(value: Any) -> bool:
    return isinstance(value, str) and SHA1.fullmatch(value) is not None


def _binding(value: Any) -> tuple[str, int] | None:
    if not isinstance(value, dict):
        return None
    sha256 = value.get("sha256")
    byte_count = value.get("bytes")
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        return None
    if not isinstance(byte_count, int) or isinstance(byte_count, bool):
        return None
    return sha256, byte_count


def _semantic_reasons(candidate: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    orchestrator = candidate["orchestrator"]
    budget = candidate["budget"]
    root_policy = candidate["root_policy"]
    assignments = candidate["assignments"]

    if candidate["swarm_id_ref"] == candidate["root_operation_ref"]:
        reasons.append("SWARM_OPERATION_ID_COLLISION")
    if candidate["root_task_ref"] != orchestrator["task_ref"]:
        reasons.append("ROOT_TASK_ORCHESTRATOR_MISMATCH")
    if candidate["root_operation_ref"] == orchestrator["task_ref"]:
        reasons.append("OPERATION_TASK_ID_COLLISION")

    recorded_at = parse_timestamp(candidate["recorded_at"])
    expires_at = parse_timestamp(candidate["expires_at"])
    if recorded_at is None or expires_at is None:
        reasons.append("TIMESTAMP_INVALID")
        return reasons
    window_seconds = (expires_at - recorded_at).total_seconds()
    if not recorded_at < expires_at:
        reasons.append("REQUEST_WINDOW_ORDER_INVALID")
    if window_seconds > MAX_WINDOW_SECONDS:
        reasons.append("REQUEST_WINDOW_UNBOUNDED")

    attempt_budget = budget["attempt_budget_N"]
    concurrency_cap = budget["concurrency_cap_C"]
    wave_width = budget["wave_width_W"]
    verifier_reserve = budget["verifier_reserve_V"]
    if wave_width > concurrency_cap:
        reasons.append("WAVE_WIDTH_EXCEEDS_CONCURRENCY")
    if wave_width > attempt_budget:
        reasons.append("WAVE_WIDTH_EXCEEDS_ATTEMPT_BUDGET")
    if verifier_reserve > attempt_budget:
        reasons.append("VERIFIER_RESERVE_EXCEEDS_ATTEMPT_BUDGET")
    if len(assignments) > attempt_budget:
        reasons.append("ASSIGNMENTS_EXCEED_ATTEMPT_BUDGET")

    attempt_refs = [assignment["attempt_ref"] for assignment in assignments]
    if len(attempt_refs) != len(set(attempt_refs)):
        reasons.append("DUPLICATE_ATTEMPT_REF")
    attempt_set = set(attempt_refs)
    root_assignments = [a for a in assignments if a["parent_attempt_ref"] is None]
    if len(root_assignments) != 1:
        reasons.append("ROOT_ASSIGNMENT_CARDINALITY_INVALID")

    verifier_count = sum(assignment["kind"] == "VERIFIER" for assignment in assignments)
    if verifier_count < verifier_reserve:
        reasons.append("VERIFIER_RESERVE_NOT_PLANNED")

    wave_counts = Counter(assignment["wave"] for assignment in assignments)
    if any(count > wave_width for count in wave_counts.values()):
        reasons.append("WAVE_WIDTH_EXCEEDED")

    workspace_ref = orchestrator["workspace_ref"]
    workspace_binding = _binding(orchestrator["workspace_binding"])
    revisions: set[str] = set()
    dedup_keys: set[str] = set()
    output_refs: set[str] = set()
    handoff_refs: set[str] = set()
    for assignment in assignments:
        attempt_ref = assignment["attempt_ref"]
        parent_ref = assignment["parent_attempt_ref"]
        if parent_ref == attempt_ref:
            reasons.append("PARENT_SELF_REFERENCE")
        if parent_ref is not None and parent_ref not in attempt_set:
            reasons.append("PARENT_ATTEMPT_UNKNOWN")
        if assignment["depth"] == 1 and parent_ref is not None:
            reasons.append("ROOT_DEPTH_PARENT_INVALID")
        if assignment["depth"] == 2 and parent_ref is None:
            reasons.append("CHILD_DEPTH_PARENT_MISSING")
        if assignment["depth"] > candidate["budget"]["max_workflow_depth"]:
            reasons.append("DEPTH_EXCEEDS_MAX_WORKFLOW_DEPTH")
        if assignment["depth"] == 2 and assignment["descendant_budget"] != 0:
            reasons.append("DESCENDANT_BUDGET_NOT_ZERO")
        if assignment["may_spawn_descendants"] is not False:
            reasons.append("DESCENDANT_SPAWN_NOT_DISABLED")

        if assignment["source_task_ref"] == assignment["target_task_ref"]:
            reasons.append("ASSIGNMENT_SOURCE_TARGET_COLLISION")
        if assignment["workspace_ref"] != workspace_ref:
            reasons.append("WORKSPACE_REF_MISMATCH")
        if _binding(assignment["workspace_binding"]) != workspace_binding:
            reasons.append("WORKSPACE_BINDING_MISMATCH")
        revisions.add(assignment["public_revision"])

        if assignment["handoff"]["source_attempt_ref"] != attempt_ref:
            reasons.append("HANDOFF_SOURCE_ATTEMPT_MISMATCH")
        if assignment["handoff"]["target_attempt_ref"] == attempt_ref:
            reasons.append("HANDOFF_SELF_REFERENCE")
        if assignment["handoff"]["target_attempt_ref"] not in attempt_set:
            reasons.append("HANDOFF_TARGET_UNKNOWN")
        if assignment["handoff"]["handoff_ref"] in handoff_refs:
            reasons.append("DUPLICATE_HANDOFF_REF")
        handoff_refs.add(assignment["handoff"]["handoff_ref"])

        if assignment["lease"]["ttl_seconds"] > window_seconds:
            reasons.append("LEASE_EXCEEDS_REQUEST_WINDOW")
        dedup_key = assignment["lease"]["dedup_key_ref"]
        if dedup_key in dedup_keys:
            reasons.append("DUPLICATE_DEDUP_KEY")
        dedup_keys.add(dedup_key)
        output_ref = assignment["expected_output"]["expected_output_ref"]
        if output_ref in output_refs:
            reasons.append("DUPLICATE_EXPECTED_OUTPUT_REF")
        output_refs.add(output_ref)
        if assignment["stop_conditions"] != STOP_CONDITIONS:
            reasons.append("STOP_CONDITION_SET_MISMATCH")

        for dependency in assignment["dependencies"]:
            if dependency not in attempt_set:
                reasons.append("DEPENDENCY_ATTEMPT_UNKNOWN")
        for child in assignment["planned_child_attempt_refs"]:
            if child not in attempt_set:
                reasons.append("PLANNED_CHILD_ATTEMPT_UNKNOWN")

    if len(revisions) > 1:
        reasons.append("PUBLIC_REVISION_DRIFT")

    for assignment in assignments:
        if assignment["attempt_ref"] in assignment["dependencies"]:
            reasons.append("DEPENDENCY_SELF_REFERENCE")

    dependency_graph = {
        assignment["attempt_ref"]: [
            dependency
            for dependency in assignment["dependencies"]
            if dependency in attempt_set and dependency != assignment["attempt_ref"]
        ]
        for assignment in assignments
    }

    dependency_state: dict[str, int] = {}

    def dependency_cycle(attempt_ref: str) -> bool:
        state = dependency_state.get(attempt_ref, 0)
        if state == 1:
            return True
        if state == 2:
            return False
        dependency_state[attempt_ref] = 1
        cycle = any(dependency_cycle(dependency) for dependency in dependency_graph[attempt_ref])
        dependency_state[attempt_ref] = 2
        return cycle

    for attempt_ref in dependency_graph:
        if dependency_cycle(attempt_ref):
            reasons.append("DEPENDENCY_CYCLE")

    # Parent/child edges are explicit: every non-root assignment must be listed
    # by its parent, and every child declaration must point back to its parent.
    by_ref = {assignment["attempt_ref"]: assignment for assignment in assignments}
    for assignment in assignments:
        parent_ref = assignment["parent_attempt_ref"]
        if parent_ref is not None:
            parent = by_ref.get(parent_ref)
            if parent is None or assignment["attempt_ref"] not in parent["planned_child_attempt_refs"]:
                reasons.append("PARENT_CHILD_EDGE_UNVERIFIED")
            elif parent["depth"] >= assignment["depth"]:
                reasons.append("PARENT_DEPTH_ORDER_INVALID")
        for child_ref in assignment["planned_child_attempt_refs"]:
            child = by_ref.get(child_ref)
            if child is not None and child["parent_attempt_ref"] != assignment["attempt_ref"]:
                reasons.append("CHILD_PARENT_EDGE_MISMATCH")
    if root_assignments:
        root_assignment = root_assignments[0]
        if root_assignment["source_task_ref"] != candidate["root_task_ref"]:
            reasons.append("ROOT_ASSIGNMENT_TASK_MISMATCH")

    if root_policy["expected_effects"] != ["INTERNAL_CANDIDATE_RECORD_ONLY"]:
        reasons.append("ROOT_EFFECT_POLICY_INVALID")
    if any(candidate["claims"].get(field) is not False for field in CLAIM_FIELDS):
        reasons.append("CLAIM_NOT_FALSE")
    return reasons


CLAIMS_FALSE = {name: False for name in CLAIM_FIELDS}


def _payload(
    *, result: str, reason_codes: list[str], matched: bool, schema_matched: bool
) -> dict[str, Any]:
    return {
        "kind": "company_pack_agent_swarm_execution_candidate_preflight",
        "version": "1.0",
        "status": "CANDIDATE_ONLY",
        "result": result,
        "reason_codes": reason_codes,
        "checks": {
            "schema": "MATCH" if schema_matched else "REFUSED",
            "budget_and_wave": "MATCH_UNVERIFIED" if matched else "REFUSED",
            "assignment_identity": "MATCH_UNVERIFIED" if matched else "REFUSED",
            "parent_edges": "MATCH_UNVERIFIED" if matched else "REFUSED",
            "workspace_and_revision": "MATCH_UNVERIFIED" if matched else "REFUSED",
            "handoff_and_lease": "MATCH_UNVERIFIED" if matched else "REFUSED",
            "no_external_effects": "MATCH" if matched else "REFUSED",
            "runtime_and_authority": "NOT_VERIFIED" if matched else "REFUSED",
        },
        "claims": CLAIMS_FALSE,
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def reject(reason_codes: list[str], *, schema_matched: bool = False) -> int:
    unique = list(dict.fromkeys(reason_codes)) or ["INPUT_INVALID"]
    print(
        json.dumps(
            _payload(
                result="REFUSED",
                reason_codes=unique,
                matched=False,
                schema_matched=schema_matched,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 2


def success() -> int:
    print(
        json.dumps(
            _payload(
                result="PRECONDITIONS_MATCH_UNVERIFIED",
                reason_codes=[],
                matched=True,
                schema_matched=True,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {Path(argv[0]).name} CANDIDATE_JSON", file=sys.stderr)
        return 2

    candidate_path = Path(argv[1])
    try:
        raw = read_bounded(candidate_path)
        candidate = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        if not isinstance(candidate, dict) or not isinstance(schema, dict):
            raise ValueError
    except InputTooLargeError:
        return reject(["INPUT_TOO_LARGE"])
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError, DuplicateKeyError, ValueError):
        return reject(["INPUT_INVALID"])

    if Draft202012Validator is None or FormatChecker is None:
        return reject(["VALIDATOR_UNAVAILABLE"])
    try:
        schema_errors = list(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(candidate)
        )
    except (TypeError, ValueError):
        return reject(["VALIDATOR_UNAVAILABLE"])
    if schema_errors:
        return reject(["SCHEMA_INVALID"])
    if candidate["swarm_state"] == "REFUSED_UNVERIFIED":
        return reject(["CANDIDATE_MARKED_REFUSED"], schema_matched=True)
    reasons = _semantic_reasons(candidate)
    return reject(reasons, schema_matched=True) if reasons else success()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
