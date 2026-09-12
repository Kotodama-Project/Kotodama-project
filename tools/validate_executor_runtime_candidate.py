#!/usr/bin/env python3
"""Validate a Kotodama executor runtime candidate against the public schema."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "executor-runtime-candidate.schema.json"


class StrictJsonError(ValueError):
    pass


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise StrictJsonError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise StrictJsonError(f"non-finite JSON number is not allowed: {value}")


def load_strict_json(path: Path) -> object:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_pairs,
        parse_constant=_reject_constant,
    )


def validate(candidate_path: Path) -> list[str]:
    try:
        schema = load_strict_json(SCHEMA_PATH)
        candidate = load_strict_json(candidate_path)
    except (OSError, json.JSONDecodeError, StrictJsonError) as exc:
        return [str(exc)]

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(candidate), key=lambda error: list(error.absolute_path))
    messages: list[str] = []
    for error in errors:
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        messages.append(f"{location}: {error.message}")
    return messages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path, help="executor runtime candidate JSON")
    args = parser.parse_args()

    candidate_path = args.candidate
    if not candidate_path.is_absolute():
        candidate_path = Path.cwd() / candidate_path

    errors = validate(candidate_path)
    if errors:
        print("FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
