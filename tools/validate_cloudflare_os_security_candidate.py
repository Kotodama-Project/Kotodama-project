#!/usr/bin/env python3
"""Validate the fail-closed Cloudflare OS security-overlay candidate."""

from __future__ import annotations

import argparse
import json
import pathlib

from cloudflare_os_security_overlay import (
    SecurityOverlayViolation,
    evaluate_git_source,
    load_spec,
    validate_spec,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-repo", type=pathlib.Path)
    args = parser.parse_args()
    try:
        spec = load_spec()
        validate_spec(spec)
        evaluation = evaluate_git_source(args.core_repo, spec) if args.core_repo else None
    except SecurityOverlayViolation as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 1
    result = {
        "status": "PASS",
        "spec_status": spec["status"],
        "evaluation": evaluation,
        "materialized": False,
        "remediation_proven": False,
        "effects": spec["effects"],
        "public_beta": spec["public_beta"],
    }
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
