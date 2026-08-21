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
    verify_observed_generated_lock,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-repo", type=pathlib.Path)
    parser.add_argument("--generated-workspace", type=pathlib.Path)
    parser.add_argument("--generated-lock", type=pathlib.Path)
    args = parser.parse_args()
    try:
        spec = load_spec()
        validate_spec(spec)
        evaluation = evaluate_git_source(args.core_repo, spec) if args.core_repo else None
        if (args.generated_workspace is None) != (args.generated_lock is None):
            raise SecurityOverlayViolation("generated workspace and lock must be supplied together")
        materialization = None
        if args.generated_workspace is not None and args.generated_lock is not None:
            try:
                workspace_bytes = args.generated_workspace.read_bytes()
                lock_bytes = args.generated_lock.read_bytes()
            except OSError as exc:
                raise SecurityOverlayViolation("cannot read generated materialization bytes") from exc
            materialization = verify_observed_generated_lock(workspace_bytes, lock_bytes, spec)
    except SecurityOverlayViolation as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 1
    result = {
        "status": "PASS",
        "spec_status": spec["status"],
        "evaluation": evaluation,
        "materialization_recorded": spec["gates"]["materialized"],
        "materialization_verification": materialization,
        "materialized": materialization is not None,
        "remediation_proven": False,
        "effects": spec["effects"],
        "public_beta": spec["public_beta"],
    }
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
