from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path("governance/openmaus-integration.json")
SCHEMA_PATH = Path("schemas/openmaus-integration.schema.json")

EXPECTED_GROUPS = {
    "intake-orchestration",
    "knowledge-research",
    "build-execution",
    "verification-audit",
    "operations-improvement",
}
EXPECTED_ZONES = {"management", "worker", "verification"}
EXPECTED_ROLLOUT = {"P0", "P1", "P2", "P3"}
REQUIRED_MCP_GAPS = {
    "approve_requests",
    "remember_permission_grants",
    "delete_data",
    "import_teams",
    "change_credentials",
    "computer_or_vm_lifecycle",
}
REQUIRED_UPSTREAM_SURFACES = {
    "README.md",
    "docs/mcp-server.md",
    "docs/byo-vps.md",
    "docs/deploy-vps.md",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(root: Path) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    config_path = root / CONFIG_PATH
    schema_path = root / SCHEMA_PATH

    try:
        config = load_json(config_path)
        schema = load_json(schema_path)
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "status": "FAIL",
            "findings": [{"code": "input-invalid", "message": str(exc)}],
            "claims": {},
        }

    try:
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        schema_errors = sorted(validator.iter_errors(config), key=lambda error: list(error.path))
    except Exception as exc:  # fail closed if validator setup itself is unavailable/broken
        return {
            "status": "FAIL",
            "findings": [{"code": "validator-unavailable", "message": str(exc)}],
            "claims": config.get("claims", {}),
        }

    for error in schema_errors:
        location = "/".join(str(part) for part in error.absolute_path) or "<root>"
        findings.append({"code": "schema-invalid", "message": f"{location}: {error.message}"})

    groups = [item["id"] for item in config.get("agent_groups", []) if isinstance(item, dict) and "id" in item]
    if set(groups) != EXPECTED_GROUPS or len(groups) != len(EXPECTED_GROUPS):
        findings.append({"code": "agent-group-drift", "message": "agent groups must contain each cross-functional group exactly once"})

    zones = [item["id"] for item in config.get("execution_zones", []) if isinstance(item, dict) and "id" in item]
    if set(zones) != EXPECTED_ZONES or len(zones) != len(EXPECTED_ZONES):
        findings.append({"code": "execution-zone-drift", "message": "management, worker, and verification zones must each exist exactly once"})

    rollout = [item["id"] for item in config.get("rollout", []) if isinstance(item, dict) and "id" in item]
    if set(rollout) != EXPECTED_ROLLOUT or len(rollout) != len(EXPECTED_ROLLOUT):
        findings.append({"code": "rollout-drift", "message": "P0 through P3 must each exist exactly once"})

    management = config.get("management_model", {})
    if management.get("no_parallel_authority") is not True:
        findings.append({"code": "parallel-authority", "message": "the unified surface must not create a second canonical authority"})

    for relative in management.get("canonical_owners", {}).values():
        if not isinstance(relative, str) or not (root / relative).is_file():
            findings.append({"code": "canonical-owner-missing", "message": f"canonical owner does not resolve: {relative!r}"})

    upstream = config.get("upstream", {})
    surfaces = set(upstream.get("verified_surfaces", []))
    if not REQUIRED_UPSTREAM_SURFACES.issubset(surfaces):
        findings.append({"code": "upstream-evidence-incomplete", "message": "pinned upstream review must cover README, MCP, BYO-VPS, and VPS deployment docs"})

    mcp = config.get("adapters", {}).get("openmaus_mcp", {})
    if not REQUIRED_MCP_GAPS.issubset(set(mcp.get("not_exposed_by_upstream_v1_mcp", []))):
        findings.append({"code": "mcp-boundary-drift", "message": "known upstream v1 MCP omissions must remain explicit"})

    proxmox = config.get("adapters", {}).get("proxmox", {})
    if proxmox.get("direct_agent_access_to_proxmox_management") is not False:
        findings.append({"code": "proxmox-direct-agent-access", "message": "agents must not receive direct Proxmox management access"})
    if proxmox.get("management_adapter_required") is not True:
        findings.append({"code": "proxmox-adapter-bypass", "message": "Proxmox mutations must pass through the bounded management adapter"})

    zone_by_id = {item.get("id"): item for item in config.get("execution_zones", []) if isinstance(item, dict)}
    management_zone = zone_by_id.get("management", {})
    worker_zone = zone_by_id.get("worker", {})
    verification_zone = zone_by_id.get("verification", {})
    if management_zone.get("work_agent_execution_allowed") is not False:
        findings.append({"code": "management-zone-execution", "message": "work agents must not execute in the canonical management zone"})
    if worker_zone.get("may_hold_canonical_authority_records") is not False:
        findings.append({"code": "worker-zone-authority", "message": "worker zone must not own canonical authority records"})
    if verification_zone.get("work_agent_execution_allowed") is not False:
        findings.append({"code": "verification-zone-execution", "message": "producer work agents must not execute in the independent verification zone"})

    work_contract = config.get("work_contract", {})
    result_states = set(work_contract.get("result_states", []))
    if "execution_settled" not in result_states or "verification_pending" not in result_states:
        findings.append({"code": "execution-verification-collapse", "message": "execution settlement and verification must remain separately representable"})

    claims = config.get("claims", {})
    asserted_claims = sorted(key for key, value in claims.items() if value is not False)
    if asserted_claims:
        findings.append({"code": "authority-claim", "message": "candidate contract asserted claims: " + ", ".join(asserted_claims)})

    return {
        "status": "PASS" if not findings else "FAIL",
        "summary": {
            "finding_count": len(findings),
            "agent_group_count": len(groups),
            "execution_zone_count": len(zones),
            "rollout_phase_count": len(rollout),
            "canonical_owner_count": len(management.get("canonical_owners", {})),
        },
        "findings": findings,
        "claims": claims,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# OpenMaus integration validation", "", f"Status: **{report['status']}**"]
    summary = report.get("summary")
    if summary:
        lines.extend(["", "## Summary"])
        lines.extend(f"- {key}: {value}" for key, value in summary.items())
    findings = report.get("findings", [])
    lines.extend(["", "## Findings"])
    if not findings:
        lines.append("- none")
    else:
        lines.extend(f"- `{item['code']}`: {item['message']}" for item in findings)
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the candidate OpenMaus unified agent control-plane contract.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    args = parser.parse_args()

    report = validate(args.root.resolve())
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(report), end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
