"""Validate an OpenMaus design contract without contacting an agent or provider."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from integration_contract_inputs import QuietParser, load_contract, local_schema_references_only
from knowledge_work_validator import read_bound

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path("governance/openmaus-integration.json")
SCHEMA_PATH = Path("schemas/openmaus-integration.schema.json")
EXPECTED_GROUPS = {"intake-orchestration", "knowledge-research", "build-execution",
                   "verification-audit", "operations-improvement"}
EXPECTED_ZONES = {"management", "worker", "verification"}
EXPECTED_ROLLOUT = {"P0", "P1", "P2", "P3"}
REQUIRED_VIEW_FIELDS = {"kotodama_agent_id", "display_name", "group_ids", "project_ids",
                        "purpose", "authority", "activation_state", "runtime_kind",
                        "runtime_location_ref", "connection_state", "current_work_ref",
                        "parent_work_ref", "last_observed_at", "artifact_refs",
                        "verification_state", "cost_observation_ref"}
CONNECTION_STATES = {"unknown", "offline", "idle", "running", "needs_user", "failed", "stalled", "interrupted"}
REQUIRED_MCP_GAPS = {"approve_requests", "remember_permission_grants", "delete_data",
                     "import_teams", "change_credentials", "computer_or_vm_lifecycle"}
SUPPORTED_MCP = {"inspect_bots_and_channels", "inspect_activity", "read_bounded_transcript_pages",
                 "create_and_edit_bots_channels_tasks", "send_work", "wait_for_conversation",
                 "interrupt_turn", "switch_idle_bot_model"}
REQUIRED_UPSTREAM_SURFACES = {"README.md", "docs/mcp-server.md", "docs/byo-vps.md", "docs/deploy-vps.md"}
OWNER_DOCUMENTS = {"goal_and_kgi": "docs/OWNER-INTENT-COMPANY-AGI.md",
                   "knowledge": "knowledge/index.md",
                   "agent_portfolio": "docs/PUBLIC-AGENT-LIFECYCLE-REGISTRY.md",
                   "audit_policy": "docs/IMPROVEMENT-LOOP.md"}
REPORT_CLAIMS = {key: False for key in ("openmaus_runtime_deployed", "all_agents_integrated",
                 "proxmox_adapter_deployed", "runtime_isolation_verified", "capability_grant_created",
                 "promotion_created", "current_truth_changed", "final_human_go", "public_beta_go")}


def report(codes: list[str], summary: dict[str, int] | None = None) -> dict[str, Any]:
    result = {"status": "FAIL" if codes else "PASS", "scope": "design_contract_only",
              "findings": [{"code": code, "message": code} for code in sorted(set(codes))],
              "claims": dict(REPORT_CLAIMS), "public_beta": "NO_GO_UNPUBLISHED"}
    if summary is not None:
        result["summary"] = {"finding_count": len(result["findings"]), **summary}
    return result


def validate(root: Path) -> dict[str, Any]:
    try:
        config = load_contract(root, CONFIG_PATH)
        schema = load_contract(root, SCHEMA_PATH)
    except (OSError, ValueError, RecursionError):
        return report(["input-invalid"])
    if not local_schema_references_only(schema):
        return report(["external-schema-ref-forbidden"])
    try:
        Draft202012Validator.check_schema(schema)
        if not Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(config):
            return report(["schema-invalid"])
    except Exception:
        return report(["validator-unavailable"])

    codes: list[str] = []
    # A candidate schema may not weaken the owned semantic contract.
    try:
        groups = [item["id"] for item in config["agent_groups"]]
        zones = [item["id"] for item in config["execution_zones"]]
        rollout = [item["id"] for item in config["rollout"]]
        for values, expected, code in ((groups, EXPECTED_GROUPS, "agent-group-drift"),
                                      (zones, EXPECTED_ZONES, "execution-zone-drift"),
                                      (rollout, EXPECTED_ROLLOUT, "rollout-drift")):
            if set(values) != expected or len(values) != len(expected):
                codes.append(code)
        management = config["management_model"]
        if management["no_parallel_authority"] is not True:
            codes.append("parallel-authority")
        owners = management["canonical_owners"]
        if owners != OWNER_DOCUMENTS:
            codes.append("canonical-owner-drift")
        for relative in OWNER_DOCUMENTS.values():
            try:
                read_bound(root, relative, 256 * 1024)
            except (OSError, ValueError):
                codes.append("canonical-owner-missing")
        if not REQUIRED_UPSTREAM_SURFACES <= set(config["upstream"]["verified_surfaces"]):
            codes.append("upstream-evidence-incomplete")
        view = config["common_agent_view"]
        if (set(view["required_fields"]) != REQUIRED_VIEW_FIELDS
                or len(view["required_fields"]) != len(REQUIRED_VIEW_FIELDS)
                or set(view["connection_states"]) != CONNECTION_STATES
                or len(view["connection_states"]) != len(CONNECTION_STATES)):
            codes.append("agent-view-drift")
        mcp = config["adapters"]["openmaus_mcp"]
        supported, gaps = set(mcp["supported_for_integration"]), set(mcp["not_exposed_by_upstream_v1_mcp"])
        if supported & gaps or supported != SUPPORTED_MCP or gaps != REQUIRED_MCP_GAPS:
            codes.append("mcp-boundary-drift")
        proxmox = config["adapters"]["proxmox"]
        if proxmox["direct_agent_access_to_proxmox_management"] is not False:
            codes.append("proxmox-direct-agent-access")
        if proxmox["management_adapter_required"] is not True:
            codes.append("proxmox-adapter-bypass")
        zone_by_id = {item["id"]: item for item in config["execution_zones"]}
        if zone_by_id["management"]["work_agent_execution_allowed"] is not False:
            codes.append("management-zone-execution")
        if zone_by_id["worker"]["may_hold_canonical_authority_records"] is not False:
            codes.append("worker-zone-authority")
        if zone_by_id["verification"]["work_agent_execution_allowed"] is not False:
            codes.append("verification-zone-execution")
        if not {"execution_settled", "verification_pending"} <= set(config["work_contract"]["result_states"]):
            codes.append("execution-verification-collapse")
        if config["claims"] != REPORT_CLAIMS or any(value is not False for value in config["claims"].values()):
            codes.append("authority-claim")
    except (AttributeError, KeyError, TypeError, ValueError):
        return report(["contract-shape-invalid"])
    return report(codes, {"agent_group_count": len(groups), "execution_zone_count": len(zones),
                         "rollout_phase_count": len(rollout), "canonical_owner_count": len(owners)})


def render_markdown(value: dict[str, Any]) -> str:
    lines = ["# OpenMaus integration validation", "", f"Status: **{value['status']}**",
             "", "Scope: design_contract_only", "Public Beta: NO_GO_UNPUBLISHED"]
    lines += [f"- `{item['code']}`" for item in value["findings"]] or ["- none"]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = QuietParser(prog="validate_openmaus_integration.py", description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    args = parser.parse_args()
    value = validate(args.root)
    output = json.dumps(value, ensure_ascii=False, indent=2) + "\n" if args.format == "json" else render_markdown(value)
    print(output, end="")
    return 0 if value["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
