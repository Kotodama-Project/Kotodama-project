"""Validate a content-free reported inventory, without contacting Cloudflare."""
import argparse
import json
import math
import os
from pathlib import Path
import stat

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]


def require(condition, code):
    if not condition:
        raise ValueError(code)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_FIELD")
        result[key] = value
    return result


def validate(receipt):
    schema = json.loads((ROOT / "schemas/cloudflare-provider-inventory-receipt.schema.json").read_text(encoding="utf-8"))
    require(next(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(receipt), None) is None, "INVENTORY_SHAPE_REFUSED")
    unresolved = []
    if receipt["identity_state"] == "REPORTED_MATCH":
        require(receipt["account_locator"] is not None and receipt["private_receipt_sha256"] is not None, "IDENTITY_EVIDENCE_REQUIRED")
    else:
        unresolved.append("identity")
    for name, row in receipt["services"].items():
        status = row["status"]
        if status == "OBSERVED":
            require(row["http_status"] == 200 and type(row["resource_count"]) is int and row["response_sha256"] is not None, "OBSERVATION_INCOMPLETE")
        else:
            require(row["resource_count"] is None, "UNKNOWN_IS_NOT_ZERO")
            if status == "DENIED":
                require(row["http_status"] in (401, 403), "DENIAL_STATUS_MISMATCH")
            elif status == "UNAVAILABLE":
                require(row["http_status"] in (404, 429, 500, 502, 503), "UNAVAILABLE_STATUS_MISMATCH")
            else:
                require(row["http_status"] is None and row["response_sha256"] is None, "UNKNOWN_STATUS_MISMATCH")
            unresolved.append(name)
    if receipt["zone_locator"] is None:
        require(receipt["services"]["dns"]["status"] != "OBSERVED", "ZONE_BINDING_REQUIRED")
        unresolved.append("zone")
    if receipt["plan"]["name"] == "UNKNOWN":
        require(receipt["plan"]["entitlement_sha256"] is None, "UNKNOWN_PLAN_EVIDENCE")
        unresolved.append("plan")
    else:
        require(receipt["plan"]["entitlement_sha256"] is not None and receipt["services"]["billing"]["status"] == "OBSERVED", "PLAN_EVIDENCE_REQUIRED")
    budget = receipt["budget"]
    require(budget["monthly_ceiling"] is None or math.isfinite(budget["monthly_ceiling"]), "FINITE_BUDGET_REQUIRED")
    if budget["state"] == "UNKNOWN":
        require(all(budget[key] is None for key in ("currency", "monthly_ceiling", "decision_sha256")), "UNKNOWN_BUDGET_FIELDS")
        unresolved.append("budget")
    else:
        require(all(budget[key] is not None for key in ("currency", "monthly_ceiling", "decision_sha256")), "BUDGET_DECISION_REQUIRED")
    unresolved.extend(receipt["unknown_bindings"])
    return {"status": "INVENTORY_RECORD_VALID", "reported_completeness": "PARTIAL" if unresolved else "COMPLETE_REPORTED",
            "unresolved": sorted(set(unresolved)), "authenticity_verified": False, "identity_verified": False,
            "observations_reverified": False, "budget_approved": False, "deployment_authorized": False,
            "public_beta": "NO_GO_UNPUBLISHED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    try:
        descriptor = os.open(args.input, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
        with os.fdopen(descriptor, "rb") as stream:
            require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), "REGULAR_FILE_REQUIRED")
            raw = stream.read(65537)
        require(len(raw) <= 65536, "INPUT_LIMIT")
        result = validate(json.loads(raw, object_pairs_hook=unique))
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        print('{"status":"INVENTORY_REFUSED","identity_verified":false}')
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
