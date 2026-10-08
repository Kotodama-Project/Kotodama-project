"""Read-only shape and revision checks; never upload or authenticate a preview."""
import argparse
import json
import os
from pathlib import Path
import re
import stat

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {"no_jwt":401, "wrong_host":403, "unknown_path":404, "health":200, "version":200}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_FIELD")
        result[key] = value
    return result


def validate(receipt, expected_candidate):
    require(isinstance(expected_candidate, str) and re.fullmatch("[0-9a-f]{40}", expected_candidate), "EXPECTED_COMMIT_REQUIRED")
    schema = json.loads((ROOT / "schemas/cloudflare-preview-receipt.schema.json").read_text(encoding="utf-8"))
    require(next(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(receipt), None) is None, "PREVIEW_RECEIPT_SHAPE_REFUSED")
    require(all(receipt[field] == expected_candidate for field in ("candidate_sha", "dispatch_sha", "approved_sha", "readback_sha")), "CANDIDATE_REVISION_DRIFT")
    uploaded = receipt["upload_state"] == "REPORTED_UPLOADED"
    require(not uploaded or (receipt["version_locator"] is not None and receipt["approval_receipt_sha256"] is not None), "UPLOAD_BINDING_REQUIRED")
    failures = []
    for name, probe in receipt["probes"].items():
        require((probe["http_status"] is None) == (probe["headers_sha256"] is None), "PROBE_EVIDENCE_MISMATCH")
        require(uploaded or probe["http_status"] is None, "UNUPLOADED_PROBE_REFUSED")
        if probe["http_status"] != EXPECTED[name]:
            failures.append(name)
    return {"status": "PREVIEW_RECEIPT_VALID", "reported_checks_match": uploaded and not failures,
            "unmatched_probes": sorted(failures), "candidate_binding_checked": True,
            "provider_reverified": False, "human_approval_verified": False, "production_deployed": False,
            "public_beta": "NO_GO_UNPUBLISHED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--expected-candidate", required=True)
    args = parser.parse_args()
    try:
        descriptor = os.open(args.input, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
        with os.fdopen(descriptor, "rb") as stream:
            require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), "REGULAR_INPUT_REQUIRED")
            raw = stream.read(65537)
        require(len(raw) <= 65536, "INPUT_LIMIT")
        result = validate(json.loads(raw, object_pairs_hook=unique), args.expected_candidate)
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        print('{"status":"PREVIEW_RECEIPT_REFUSED","provider_reverified":false}')
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
