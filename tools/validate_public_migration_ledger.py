"""Read-only verifier for the public Kotodama migration ledger.

The ledger is an append-only JSONL file of public-safe aggregate records.  This
verifier checks structure, ordering, hash-chain integrity, classification
vocabulary separation, and gate consistency.  It never resolves an opaque
reference, reads a private receipt, contacts a provider, copies material,
executes a migration, writes a receipt, grants authority, or promotes Current
Truth.

A successful result means only that the recorded dispositions are internally
coherent and machine-checkable.  It is not evidence that any migration ran, that
private continuity holds, or that anything may be published.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # pragma: no cover - dependency-free installs fail closed
    Draft202012Validator = None  # type: ignore[assignment,misc]
    FormatChecker = None  # type: ignore[assignment,misc]


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "public-migration-ledger.schema.json"
MAX_INPUT_BYTES = 8_388_608
GENESIS_HASH = "0" * 64

TERMINAL_CLASSIFICATIONS = [
    "PUBLIC_EXTRACT",
    "PRIVATE_RETAIN",
    "REGENERATE",
    "DROP",
]

TRANSFER_MODES = ["REAUTHOR", "GENERATE", "NO_COPY"]

GATE_NAMES = [
    "license_provenance",
    "secret_scan",
    "history_scan",
    "dependency_baseline",
    "independent_review",
]

CLAIM_FIELDS = [
    "migration_executed",
    "private_continuity_verified",
    "public_extract_published",
    "dependency_cutover_verified",
    "rollback_rehearsed",
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
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_lines(raw: bytes) -> list[dict[str, Any]]:
    text = raw.decode("utf-8")
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            raise ValueError("blank line")
        record = json.loads(line, object_pairs_hook=reject_duplicate_keys)
        if not isinstance(record, dict):
            raise ValueError("record is not an object")
        records.append(record)
    if not records:
        raise ValueError("empty ledger")
    return records


def _ordering_reasons(records: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    seen_ids: set[str] = set()
    seen_subjects: set[tuple[str, int]] = set()
    previous_sequence = 0
    previous_recorded_at = ""
    for record in records:
        sequence = record["sequence"]
        if sequence != previous_sequence + 1:
            reasons.append("SEQUENCE_NOT_CONTIGUOUS")
        previous_sequence = sequence

        record_id = record["record_id"]
        if record_id in seen_ids:
            reasons.append("DUPLICATE_RECORD_ID")
        seen_ids.add(record_id)

        subject_key = (record["subject_ref"], sequence)
        if subject_key in seen_subjects:
            reasons.append("DUPLICATE_SUBJECT_SEQUENCE")
        seen_subjects.add(subject_key)

        recorded_at = record["recorded_at"]
        if recorded_at < previous_recorded_at:
            reasons.append("RECORDED_AT_NOT_MONOTONIC")
        previous_recorded_at = recorded_at
    return reasons


def _chain_reasons(records: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    expected_prev = GENESIS_HASH
    for record in records:
        if record["prev_hash"] != expected_prev:
            reasons.append("HASH_CHAIN_BROKEN")
        recomputed = canonical_content_hash(record)
        if record["content_hash"] != recomputed:
            reasons.append("CONTENT_DIGEST_DRIFT")
            expected_prev = record["content_hash"]
        else:
            expected_prev = recomputed
    return reasons


def _vocabulary_reasons(record: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    terminal = record["terminal_classification"]
    transfer = record["transfer_mode"]
    status = record["status"]

    # A transfer mechanism must never be recorded as a terminal classification,
    # and the reverse must not happen either. The schema enumerates each field
    # separately; this check states the separation explicitly so a future schema
    # relaxation cannot silently reintroduce the conflation.
    if terminal is not None and terminal not in TERMINAL_CLASSIFICATIONS:
        reasons.append("TERMINAL_CLASSIFICATION_UNKNOWN")
    if terminal in TRANSFER_MODES:
        reasons.append("TRANSFER_MODE_USED_AS_CLASSIFICATION")
    if transfer in TERMINAL_CLASSIFICATIONS:
        reasons.append("CLASSIFICATION_USED_AS_TRANSFER_MODE")

    if status == "BLOCKED" and terminal is not None:
        reasons.append("BLOCKED_RECORD_CARRIES_CLASSIFICATION")
    if status in {"PROPOSED", "ACCEPTED"} and terminal is None:
        reasons.append("UNBLOCKED_RECORD_MISSING_CLASSIFICATION")
    if terminal == "DROP" and transfer != "NO_COPY":
        reasons.append("DROP_REQUIRES_NO_COPY")
    if terminal == "REGENERATE" and transfer != "GENERATE":
        reasons.append("REGENERATE_REQUIRES_GENERATE")
    if record["supersession_reason"] is not None and status != "REJECTED":
        reasons.append("SUPERSESSION_WITHOUT_REJECTION")
    return reasons


def _gate_reasons(record: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    gates = record["gates"]
    results = [gates[name] for name in GATE_NAMES]
    status = record["status"]

    if status == "ACCEPTED" and any(result != "PASS" for result in results):
        reasons.append("GATE_BYPASS")
    if status == "BLOCKED" and all(result == "PASS" for result in results):
        reasons.append("BLOCKED_WITHOUT_BLOCKING_GATE")
    if any(result == "FAIL" for result in results) and status in {"PROPOSED", "ACCEPTED"}:
        reasons.append("FAILED_GATE_NOT_REJECTED_OR_BLOCKED")
    return reasons


def _claim_reasons(record: dict[str, Any]) -> list[str]:
    claims = record["claims"]
    if any(claims[field] is not False for field in CLAIM_FIELDS):
        return ["CLAIM_ASSERTED"]
    return []


def _semantic_reasons(records: list[dict[str, Any]]) -> list[str]:
    reasons = _ordering_reasons(records) + _chain_reasons(records)
    for record in records:
        reasons.extend(_vocabulary_reasons(record))
        reasons.extend(_gate_reasons(record))
        reasons.extend(_claim_reasons(record))
    return reasons


def _counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts = {name: 0 for name in TERMINAL_CLASSIFICATIONS}
    counts["UNCLASSIFIED_BLOCKED"] = 0
    for record in records:
        terminal = record["terminal_classification"]
        if terminal is None:
            counts["UNCLASSIFIED_BLOCKED"] += 1
        elif terminal in counts:
            counts[terminal] += 1
    return counts


def _payload(
    result: str,
    reason_codes: list[str],
    record_count: int,
    counts: dict[str, int],
) -> dict[str, Any]:
    return {
        "contract": "kotodama.public-migration-ledger/v1",
        "result": result,
        "reason_codes": reason_codes,
        "record_count": record_count,
        "terminal_classification_counts": counts,
        "zero_unclassified": counts.get("UNCLASSIFIED_BLOCKED", 0) == 0,
        "claims": {field: False for field in CLAIM_FIELDS},
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def reject(reason_codes: list[str], record_count: int = 0) -> int:
    unique = list(dict.fromkeys(reason_codes)) or ["INPUT_INVALID"]
    print(
        json.dumps(
            _payload("REFUSED", unique, record_count, {}),
            indent=2,
            sort_keys=True,
        )
    )
    return 2


def success(records: list[dict[str, Any]]) -> int:
    print(
        json.dumps(
            _payload(
                "LEDGER_CONSISTENT_UNVERIFIED",
                [],
                len(records),
                _counts(records),
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {Path(argv[0]).name} LEDGER_JSONL", file=sys.stderr)
        return 2

    ledger_path = Path(argv[1])
    try:
        raw = ledger_path.read_bytes()
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
        return reject(["SCHEMA_INVALID"], len(records))

    reasons = _semantic_reasons(records)
    return reject(reasons, len(records)) if reasons else success(records)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
