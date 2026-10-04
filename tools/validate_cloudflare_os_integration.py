"""Read-only design-contract checks; no Cloudflare, OS, or worker API calls."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from integration_contract_inputs import (MAX_BYTES, QuietParser, load_contract,
                                         local_schema_references_only)
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
CONFIG = "governance/cloudflare-os-integration.json"
SCHEMA = "schemas/cloudflare-os-integration.schema.json"
OPENMAUS = "governance/openmaus-integration.json"
SERVICE_STAGES = {
    "workers": "core", "durable_objects": "core",
    "dynamic_workers_and_facets": "core", "access": "hybrid_phase",
    "tunnel": "hybrid_phase", "r2": "artifact_phase",
    "workflows": "deferred", "queues": "deferred", "d1": "deferred",
    "ai_gateway": "deferred",
}
REPORT_CLAIMS = {"runtime_verified": False, "deployment_authorized": False}
EXPECTED_CLAIMS = {"cloudflare_os_integrated", "all_agents_integrated",
                   "cloudflare_resources_deployed", "proxmox_connected",
                   "team_acl_verified", "runtime_tests_passed", "human_go"}


def _get(value: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _report(codes: list[str]) -> dict[str, Any]:
    return {"status": "FAIL" if codes else "PASS", "scope": "design_contract_only",
            "findings": [{"code": code} for code in sorted(set(codes))],
            "claims": dict(REPORT_CLAIMS), "public_beta": "NO_GO_UNPUBLISHED"}


def validate(root: Path) -> dict[str, Any]:
    try:
        config, schema, base = (load_contract(root, path) for path in (CONFIG, SCHEMA, OPENMAUS))
    except (OSError, ValueError, RecursionError):
        return _report(["INPUT_INVALID"])
    if not local_schema_references_only(schema):
        return _report(["EXTERNAL_SCHEMA_REF_FORBIDDEN"])
    try:
        Draft202012Validator.check_schema(schema)
        if not Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(config):
            return _report(["SCHEMA_INVALID"])
    except Exception:
        return _report(["VALIDATOR_UNAVAILABLE"])
    codes: list[str] = []
    claims = _get(config, "claims")
    if (not isinstance(claims, dict) or set(claims) != EXPECTED_CLAIMS
            or any(value is not False for value in claims.values())):
        codes.append("AUTHORITY_CLAIM")
    try:
        services = config["cloudflare_services"]
        observed = {entry["id"]: entry["stage"] for entry in services}
        if len(services) != len(observed) or observed != SERVICE_STAGES:
            codes.append("SERVICE_STAGE_DRIFT")
        if any(entry.get("enabled") is not False for entry in services):
            codes.append("SERVICE_ENABLED")
        if (_get(base, "management_model", "primary_human_surface") != config["composition"]["surface_ref"]
                or _get(base, "management_model", "no_parallel_authority") is not True
                or _get(base, "management_model", "principle") != "one_management_plane_multiple_execution_boundaries"):
            codes.append("PARALLEL_MANAGEMENT_PLANE")
        if (_get(base, "work_contract", "shared_work_identity_required") is not True
                or _get(base, "work_contract", "idempotency_required_for_dispatch") is not True
                or _get(base, "work_contract", "stop_request_requires_stop_observation") is not True):
            codes.append("SHARED_WORK_CONTRACT_DRIFT")
        if _get(base, "adapters", "proxmox", "direct_agent_access_to_proxmox_management") is not False:
            codes.append("PROXMOX_BOUNDARY_DRIFT")
    except (AttributeError, KeyError, TypeError, ValueError):
        return _report(["CONTRACT_SHAPE_INVALID"])
    return _report(codes)


def main() -> int:
    parser = QuietParser(prog="validate_cloudflare_os_integration.py", description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    report = validate(args.root)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
