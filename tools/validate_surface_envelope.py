"""Read-only synthetic envelope shape check; does not verify platform identity."""
import argparse
import json
import os
from pathlib import Path
import stat

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_FIELD")
        result[key] = value
    return result


def validate(value):
    schema = json.loads((ROOT / "schemas/surface-event-envelope.schema.json").read_text(encoding="utf-8"))
    if next(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value), None):
        raise ValueError("INVALID_ENVELOPE")
    if value["acl"]["tenant"] != value["tenant"] or value["actor"] not in value["acl"]["readers"]:
        raise ValueError("ACL_MISMATCH")
    return {"status": "SYNTHETIC_CONTRACT_VALID", "surface": value["surface"],
            "signature_verified": False, "membership_verified": False, "provider_verified": False,
            "task_created": False, "public_beta": "NO_GO_UNPUBLISHED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    try:
        descriptor = os.open(args.input, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("REGULAR_FILE_REQUIRED")
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError("BODY_LIMIT")
        result = validate(json.loads(raw, object_pairs_hook=unique))
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        print('{"status":"REFUSED","provider_verified":false}')
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
