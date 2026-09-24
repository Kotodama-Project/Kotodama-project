#!/usr/bin/env python3
"""Validate a Kotodama executor runtime candidate against the public schema.

Needs jsonschema from the hash-locked ``requirements-ci.txt``. Every value is
also scanned with the repository's tracked-secret detectors, so a credential
cannot hide in an otherwise schema-valid string field.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_tracked_secret_hygiene import scan_text  # noqa: E402  (stdlib-only sibling tool)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "executor-runtime-candidate.schema.json"
MISSING_JSONSCHEMA = (
    "jsonschema is required: python -m pip install --require-hashes -r requirements-ci.txt"
)


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


def _read_utf8(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StrictJsonError(f"{path.name} is not valid UTF-8 (byte {exc.start})") from None


def _parse_strict_json(text: str) -> object:
    return json.loads(
        text,
        object_pairs_hook=_reject_duplicate_pairs,
        parse_constant=_reject_constant,
    )


def load_strict_json(path: Path) -> object:
    return _parse_strict_json(_read_utf8(path))


def validate(candidate_path: Path) -> list[str]:
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return [MISSING_JSONSCHEMA]
    try:
        schema = load_strict_json(SCHEMA_PATH)
        raw_candidate = _read_utf8(candidate_path)
        candidate = _parse_strict_json(raw_candidate)
    except (OSError, json.JSONDecodeError, StrictJsonError) as exc:
        return [str(exc)]

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(candidate), key=lambda error: list(error.absolute_path))
    messages: list[str] = []
    for error in errors:
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        messages.append(f"{location}: {error.message}")
    # Report only the detector and line; never echo the value.
    for _path, line, detector in scan_text(candidate_path, raw_candidate):
        messages.append(f"line {line}: secret-like value ({detector})")
    return messages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path, help="executor runtime candidate JSON")
    args = parser.parse_args()

    candidate_path = args.candidate
    if not candidate_path.is_absolute():
        candidate_path = Path.cwd() / candidate_path

    errors = validate(candidate_path)
    if errors == [MISSING_JSONSCHEMA]:
        print(f"ERROR: {MISSING_JSONSCHEMA}", file=sys.stderr)
        return 2
    if errors:
        print("FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
