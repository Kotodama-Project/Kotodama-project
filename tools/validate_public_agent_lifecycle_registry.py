"""Read-only verifier for the public Kotodama agent lifecycle registry.

The registry is an append-only JSONL file of provider-neutral records: agent
specifications, instances, runs, worker leases, run events, and evidence
receipts.  This verifier checks structure, ordering, hash-chain integrity,
referential integrity, the fail-closed run outcome contract, fan-out and depth
budgets, lease and idempotency discipline, and restart continuity
*preconditions*.

It never spawns an agent, dispatches a run, contacts a provider, resolves an
opaque locator, reads a private receipt, writes a receipt, grants authority, or
promotes Current Truth.

Two results are deliberately impossible to obtain from this tool:

* a run is never reported as successful merely because it is marked
  ``degraded`` or because a payload was constructed; success is *derived* from
  ``state == "completed"`` together with a completion reason and at least one
  bound evidence receipt, and it is never read from a stored flag; and
* continuity is never reported as verified.  Matching every recorded
  precondition across a restart yields ``PRECONDITIONS_MATCH_UNVERIFIED``,
  because a public record cannot prove that a provider actually reused the same
  authorized instance.  Reconstructing a plan or re-dispatching a task is work
  resume, and is reported as ``WORK_RESUME_ONLY``.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # pragma: no cover - dependency-free installs fail closed
    Draft202012Validator = None  # type: ignore[assignment,misc]
    FormatChecker = None  # type: ignore[assignment,misc]


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "public-agent-lifecycle-registry.schema.json"
MAX_INPUT_BYTES = 8_388_608
GENESIS_HASH = "0" * 64

NON_TERMINAL_STATES = ["prepared", "dispatched", "running"]
TERMINAL_STATES = ["completed", "failed", "cancelled", "expired"]

ALLOWED_TRANSITIONS = {
    None: {"prepared"},
    "prepared": {"dispatched", "failed", "cancelled", "expired"},
    "dispatched": {"running", "failed", "cancelled", "expired"},
    "running": {"completed", "failed", "cancelled", "expired"},
}

FAILURE_REASONS = [
    "WORKER_ERROR",
    "EMPTY_RESULT",
    "TIMEOUT",
    "UNKNOWN_STATE",
    "MISSING_EVIDENCE",
    "CANCELLED_BY_PARENT",
    "LEASE_EXPIRED",
]

CONTINUITY_PRECONDITIONS = [
    "spec_ref",
    "spec_digest",
    "policy_version",
    "provider_locator_ref",
    "context_capsule_digest",
    "repository_ref",
    "revision",
]

CLAIM_FIELDS = [
    "agent_runtime_verified",
    "dispatch_executed",
    "provider_instance_reused",
    "continuity_verified",
    "evidence_independently_verified",
    "promotion_verified",
    "current_truth_changed",
    "final_human_go",
    "public_beta_go",
]


class DuplicateKeyError(ValueError):
    pass


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError
        result[key] = value
    return result


def canonical_content_hash(record: dict[str, Any]) -> str:
    """Hash the record with `content_hash` removed, canonically encoded."""
    payload = {key: value for key, value in record.items() if key != "content_hash"}
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def derived_success(run: dict[str, Any]) -> bool:
    """Success is derived, never stored.

    A run is successful only when it reached `completed`, recorded the
    completion reason, and bound at least one evidence receipt.  `degraded` is
    irrelevant here by design: it is a quality attribute, so a degraded run that
    genuinely completed with evidence is still successful, and a non-completed
    run can never be made successful by clearing it.
    """
    return (
        run["state"] == "completed"
        and run["termination_reason"] == "EVIDENCE_COMPLETE"
        and bool(run["evidence_receipt_refs"])
    )


def _parse_lines(raw: bytes) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in raw.decode("utf-8").splitlines():
        if not line.strip():
            raise ValueError("blank line")
        record = json.loads(line, object_pairs_hook=reject_duplicate_keys)
        if not isinstance(record, dict):
            raise ValueError("record is not an object")
        records.append(record)
    if not records:
        raise ValueError("empty registry")
    return records


def _envelope_reasons(records: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    seen_ids: set[str] = set()
    previous_sequence = 0
    previous_recorded_at = ""
    expected_prev = GENESIS_HASH
    for record in records:
        if record["sequence"] != previous_sequence + 1:
            reasons.append("SEQUENCE_NOT_CONTIGUOUS")
        previous_sequence = record["sequence"]

        if record["record_id"] in seen_ids:
            reasons.append("DUPLICATE_RECORD_ID")
        seen_ids.add(record["record_id"])

        if record["recorded_at"] < previous_recorded_at:
            reasons.append("RECORDED_AT_NOT_MONOTONIC")
        previous_recorded_at = record["recorded_at"]

        if record["prev_hash"] != expected_prev:
            reasons.append("HASH_CHAIN_BROKEN")
        recomputed = canonical_content_hash(record)
        if record["content_hash"] != recomputed:
            reasons.append("CONTENT_DIGEST_DRIFT")
            expected_prev = record["content_hash"]
        else:
            expected_prev = recomputed

        if any(record["claims"][field] is not False for field in CLAIM_FIELDS):
            reasons.append("CLAIM_ASSERTED")
    return reasons


def _index(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[record["kind"]].append(record)
    return grouped


def _reference_reasons(grouped: dict[str, list[dict[str, Any]]]) -> list[str]:
    reasons: list[str] = []
    specs = {r["spec_ref"]: r for r in grouped["agent_spec"]}
    instances = {r["instance_ref"]: r for r in grouped["agent_instance"]}
    runs = {r["run_ref"]: r for r in grouped["agent_run"]}
    receipts = {r["receipt_ref"]: r for r in grouped["evidence_receipt"]}

    if len(specs) != len(grouped["agent_spec"]):
        reasons.append("DUPLICATE_SPEC_REF")
    # A repeated `instance_ref` is intentional: it is the same logical instance
    # observed again after a restart. Continuity is assessed separately; only the
    # spec binding must stay identical across observations.
    if len(runs) != len(grouped["agent_run"]):
        reasons.append("DUPLICATE_RUN_REF")
    if len(receipts) != len(grouped["evidence_receipt"]):
        reasons.append("DUPLICATE_RECEIPT_REF")

    for instance in grouped["agent_instance"]:
        spec = specs.get(instance["spec_ref"])
        if spec is None:
            reasons.append("INSTANCE_SPEC_UNKNOWN")
            continue
        if (
            spec["spec_digest"] != instance["spec_digest"]
            or spec["policy_version"] != instance["policy_version"]
        ):
            reasons.append("INSTANCE_SPEC_BINDING_DRIFT")

    for run in grouped["agent_run"]:
        if run["instance_ref"] not in instances:
            reasons.append("RUN_INSTANCE_UNKNOWN")
        for receipt_ref in run["evidence_receipt_refs"]:
            receipt = receipts.get(receipt_ref)
            if receipt is None:
                reasons.append("RUN_EVIDENCE_UNKNOWN")
            elif receipt["run_ref"] != run["run_ref"]:
                reasons.append("RUN_EVIDENCE_BOUND_TO_ANOTHER_RUN")

    for lease in grouped["worker_lease"]:
        if lease["run_ref"] not in runs:
            reasons.append("LEASE_RUN_UNKNOWN")
        if lease["heartbeat_at"] > lease["expires_at"]:
            reasons.append("LEASE_HEARTBEAT_AFTER_EXPIRY")

    for event in grouped["run_event"]:
        if event["run_ref"] not in runs:
            reasons.append("EVENT_RUN_UNKNOWN")

    for receipt in grouped["evidence_receipt"]:
        if receipt["run_ref"] not in runs:
            reasons.append("RECEIPT_RUN_UNKNOWN")
    return reasons


def _outcome_reasons(grouped: dict[str, list[dict[str, Any]]]) -> list[str]:
    reasons: list[str] = []
    for run in grouped["agent_run"]:
        state = run["state"]
        reason = run["termination_reason"]
        if state in NON_TERMINAL_STATES:
            if reason is not None:
                reasons.append("NON_TERMINAL_RUN_CARRIES_TERMINATION_REASON")
            if run["evidence_receipt_refs"]:
                reasons.append("NON_TERMINAL_RUN_CARRIES_EVIDENCE")
        elif state == "completed":
            if reason != "EVIDENCE_COMPLETE":
                reasons.append("COMPLETED_RUN_WITHOUT_COMPLETION_REASON")
            if not run["evidence_receipt_refs"]:
                reasons.append("COMPLETED_RUN_WITHOUT_EVIDENCE")
        else:
            if reason is None:
                reasons.append("TERMINAL_RUN_WITHOUT_TERMINATION_REASON")
            elif reason == "EVIDENCE_COMPLETE":
                reasons.append("FAILED_RUN_CLAIMS_COMPLETION_REASON")
        if (run.get("parent_run_ref") is None) != (run.get("parent_edge_ref") is None):
            reasons.append("PARENT_EDGE_INCONSISTENT")
        if run.get("parent_run_ref") is None and run["depth"] != 0:
            reasons.append("ROOT_RUN_DEPTH_NOT_ZERO")
    return reasons


def _budget_reasons(grouped: dict[str, list[dict[str, Any]]]) -> list[str]:
    reasons: list[str] = []
    specs = {r["spec_ref"]: r for r in grouped["agent_spec"]}
    instances = {r["instance_ref"]: r for r in grouped["agent_instance"]}
    runs = {r["run_ref"]: r for r in grouped["agent_run"]}
    children: Counter[str] = Counter()

    for run in grouped["agent_run"]:
        instance = instances.get(run["instance_ref"])
        spec = specs.get(instance["spec_ref"]) if instance else None
        if spec is not None and run["depth"] > spec["max_depth"]:
            reasons.append("DEPTH_BUDGET_EXCEEDED")

        parent_ref = run.get("parent_run_ref")
        if parent_ref is None:
            continue
        parent = runs.get(parent_ref)
        if parent is None:
            reasons.append("PARENT_RUN_UNKNOWN")
            continue
        if run["depth"] != parent["depth"] + 1:
            reasons.append("DEPTH_NOT_PARENT_PLUS_ONE")
        children[parent_ref] += 1

    for parent_ref, count in children.items():
        parent = runs[parent_ref]
        instance = instances.get(parent["instance_ref"])
        spec = specs.get(instance["spec_ref"]) if instance else None
        if spec is not None and count > spec["max_fan_out"]:
            reasons.append("FAN_OUT_BUDGET_EXCEEDED")
    return reasons


def _idempotency_reasons(grouped: dict[str, list[dict[str, Any]]]) -> list[str]:
    reasons: list[str] = []
    attempts: dict[str, list[int]] = defaultdict(list)
    for run in grouped["agent_run"]:
        attempts[run["idempotency_key_ref"]].append(run["attempt"])
    for key, values in attempts.items():
        if len(set(values)) != len(values):
            reasons.append("DUPLICATE_ATTEMPT_FOR_IDEMPOTENCY_KEY")
        if sorted(values) != list(range(1, len(values) + 1)):
            reasons.append("ATTEMPTS_NOT_CONTIGUOUS_FROM_ONE")

    epochs: dict[str, list[int]] = defaultdict(list)
    for lease in grouped["worker_lease"]:
        epochs[lease["run_ref"]].append(lease["epoch"])
    for run_ref, values in epochs.items():
        if values != sorted(set(values)) or len(set(values)) != len(values):
            reasons.append("LEASE_EPOCH_NOT_STRICTLY_INCREASING")
    return reasons


def _event_reasons(grouped: dict[str, list[dict[str, Any]]]) -> list[str]:
    reasons: list[str] = []
    runs = {r["run_ref"]: r for r in grouped["agent_run"]}
    per_run: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in grouped["run_event"]:
        per_run[event["run_ref"]].append(event)

    for run_ref, events in per_run.items():
        ordered = sorted(events, key=lambda e: e["subject_sequence"])
        if [e["subject_sequence"] for e in ordered] != list(range(1, len(ordered) + 1)):
            reasons.append("SUBJECT_SEQUENCE_NOT_CONTIGUOUS")
        state: str | None = None
        for event in ordered:
            if event["from_state"] != state:
                reasons.append("EVENT_FROM_STATE_MISMATCH")
            if event["to_state"] not in ALLOWED_TRANSITIONS.get(state, set()):
                reasons.append("ILLEGAL_STATE_TRANSITION")
            state = event["to_state"]
        run = runs.get(run_ref)
        if run is not None and run["state"] != state:
            reasons.append("RUN_STATE_DOES_NOT_MATCH_EVENT_HISTORY")

    for run_ref, run in runs.items():
        if run_ref not in per_run:
            reasons.append("RUN_WITHOUT_EVENT_HISTORY")
    return reasons


def _continuity(grouped: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Assess restart continuity preconditions per logical instance.

    Two instance records that share an `instance_ref` describe the same logical
    agent instance observed across a restart.  Every recorded precondition must
    match for the successor to be a continuity *candidate*; the assessment never
    becomes verified here.
    """
    grouped_by_ref: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for instance in grouped["agent_instance"]:
        grouped_by_ref[instance["instance_ref"]].append(instance)

    assessments: list[dict[str, Any]] = []
    for instance_ref, observations in sorted(grouped_by_ref.items()):
        if len(observations) < 2:
            continue
        first = observations[0]
        mismatched = [
            field
            for field in CONTINUITY_PRECONDITIONS
            if any(other[field] != first[field] for other in observations[1:])
        ]
        assessments.append(
            {
                "instance_ref": instance_ref,
                "observations": len(observations),
                "assessment": "PRECONDITIONS_MATCH_UNVERIFIED"
                if not mismatched
                else "WORK_RESUME_ONLY",
                "mismatched_preconditions": sorted(mismatched),
            }
        )
    return assessments


def _semantic_reasons(records: list[dict[str, Any]]) -> list[str]:
    grouped = _index(records)
    return (
        _envelope_reasons(records)
        + _reference_reasons(grouped)
        + _outcome_reasons(grouped)
        + _budget_reasons(grouped)
        + _idempotency_reasons(grouped)
        + _event_reasons(grouped)
    )


def _payload(
    result: str,
    reason_codes: list[str],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    grouped = _index(records)
    runs = grouped["agent_run"]
    return {
        "contract": "kotodama.public-agent-lifecycle-registry/v1",
        "result": result,
        "reason_codes": reason_codes,
        "record_count": len(records),
        "record_kind_counts": dict(sorted(Counter(r["kind"] for r in records).items())),
        "run_state_counts": dict(sorted(Counter(r["state"] for r in runs).items())),
        "derived_success_count": sum(1 for r in runs if derived_success(r)),
        "degraded_run_count": sum(1 for r in runs if r["degraded"]),
        "continuity_assessments": _continuity(grouped),
        "claims": {field: False for field in CLAIM_FIELDS},
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def reject(reason_codes: list[str], records: list[dict[str, Any]] | None = None) -> int:
    unique = list(dict.fromkeys(reason_codes)) or ["INPUT_INVALID"]
    if records is None:
        payload = {
            "contract": "kotodama.public-agent-lifecycle-registry/v1",
            "result": "REFUSED",
            "reason_codes": unique,
            "record_count": 0,
            "record_kind_counts": {},
            "run_state_counts": {},
            "derived_success_count": 0,
            "degraded_run_count": 0,
            "continuity_assessments": [],
            "claims": {field: False for field in CLAIM_FIELDS},
            "public_beta": "NO_GO_UNPUBLISHED",
        }
    else:
        payload = _payload("REFUSED", unique, records)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 2


def success(records: list[dict[str, Any]]) -> int:
    print(
        json.dumps(
            _payload("REGISTRY_CONSISTENT_UNVERIFIED", [], records),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {Path(argv[0]).name} REGISTRY_JSONL", file=sys.stderr)
        return 2

    registry_path = Path(argv[1])
    try:
        raw = registry_path.read_bytes()
        if len(raw) > MAX_INPUT_BYTES:
            return reject(["INPUT_TOO_LARGE"])
        records = _parse_lines(raw)
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        if not isinstance(schema, dict):
            raise ValueError
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, DuplicateKeyError, ValueError):
        return reject(["INPUT_INVALID"])

    if Draft202012Validator is None or FormatChecker is None:
        return reject(["VALIDATOR_UNAVAILABLE"])
    try:
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        schema_errors = [error for record in records for error in validator.iter_errors(record)]
    except (TypeError, ValueError):
        return reject(["VALIDATOR_UNAVAILABLE"])
    if schema_errors:
        return reject(["SCHEMA_INVALID"])

    reasons = _semantic_reasons(records)
    return reject(reasons, records) if reasons else success(records)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
