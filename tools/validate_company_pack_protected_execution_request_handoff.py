"""Read-only preflight for a protected execution request/handoff candidate.

This tool validates the public schema and the cross-field time preconditions
that JSON Schema cannot express. It never resolves a locator, starts a runner,
opens a credential, writes a receipt, or emits input values.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "company-pack-protected-execution-request-handoff-candidate.schema.json"
MAX_INPUT_BYTES = 1_048_576


class DuplicateKeyError(ValueError):
    pass


def reject(reason_codes: list[str]) -> int:
    payload = {
        "kind": "company_pack_protected_execution_request_handoff_candidate_preflight",
        "version": "1.0",
        "status": "CANDIDATE_ONLY",
        "result": "REFUSED",
        "reason_codes": reason_codes,
        "claims": {
            "execution_verified": False,
            "private_inputs_resolved": False,
            "trusted_clock_verified": False,
            "receipt_emitted": False,
            "public_beta_go": False,
        },
        "public_beta": "NO_GO_UNPUBLISHED",
    }
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    return 2


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError
        result[key] = value
    return result


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def success() -> int:
    payload = {
        "kind": "company_pack_protected_execution_request_handoff_candidate_preflight",
        "version": "1.0",
        "status": "CANDIDATE_ONLY",
        "result": "PRECONDITIONS_MATCH_UNVERIFIED",
        "reason_codes": [],
        "checks": {
            "schema": "MATCH",
            "window_order": "MATCH_UNVERIFIED_CLOCK",
            "window_duration": "MATCH_BOUNDED",
            "parent_expiry": "MATCH",
        },
        "claims": {
            "execution_verified": False,
            "private_inputs_resolved": False,
            "trusted_clock_verified": False,
            "receipt_emitted": False,
            "public_beta_go": False,
        },
        "public_beta": "NO_GO_UNPUBLISHED",
    }
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {Path(argv[0]).name} CANDIDATE_JSON", file=sys.stderr)
        return 2

    candidate_path = Path(argv[1])
    try:
        raw = candidate_path.read_bytes()
        if len(raw) > MAX_INPUT_BYTES:
            return reject(["INPUT_TOO_LARGE"])
        candidate = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, DuplicateKeyError):
        return reject(["INPUT_INVALID"])

    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        if list(validator.iter_errors(candidate)):
            return reject(["SCHEMA_INVALID"])
    except (OSError, json.JSONDecodeError):
        return reject(["VALIDATOR_UNAVAILABLE"])

    if not isinstance(candidate, dict):
        return reject(["SCHEMA_INVALID"])
    window = candidate["evaluation_window"]
    recorded_at = parse_timestamp(candidate["recorded_at"])
    parent_expires_at = parse_timestamp(candidate["expires_at"])
    not_before = parse_timestamp(window["not_before"])
    window_expires_at = parse_timestamp(window["expires_at"])
    if None in (recorded_at, parent_expires_at, not_before, window_expires_at):
        return reject(["TIMESTAMP_INVALID"])

    reasons: list[str] = []
    if not (recorded_at <= not_before < window_expires_at):
        reasons.append("WINDOW_ORDER_INVALID")
    if window_expires_at > parent_expires_at:
        reasons.append("WINDOW_EXCEEDS_PARENT_EXPIRY")
    actual_duration = (window_expires_at - not_before).total_seconds()
    requested_duration = window["requested_duration_seconds"]
    if actual_duration <= 0 or actual_duration > 86_400:
        reasons.append("WINDOW_DURATION_UNBOUNDED")
    if not actual_duration.is_integer() or int(actual_duration) != requested_duration:
        reasons.append("WINDOW_DURATION_MISMATCH")
    return reject(reasons) if reasons else success()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
