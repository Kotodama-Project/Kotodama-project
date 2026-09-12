#!/usr/bin/env python3
"""Turn control-plane audit findings into bounded proposal-only maintenance work.

This planner is deliberately non-mutating. It can prioritize and assign candidate
work to governed agent roles, but it cannot create authority, execute changes, or
promote Current Truth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from audit_control_plane import build_report, parse_day

ROLE_RULES = (
    (("stale-", "inventory-", "missing-canonical", "competing-canonical", "duplicate-fact", "freshness-"), "knowledge-curator"),
    (("unknown-kgi", "unknown-kf", "unknown-phase", "invalid-baseline", "missing-baseline", "no-current-phase", "duplicate-id"), "okf-steward"),
    (("duplicate-agent", "preactive-execute", "active-agent", "unknown-fact-family"), "agent-auditor"),
    (("autonomy-", "unsafe-agentic", "promotion-", "critical-contradiction"), "evidence-auditor"),
)

ROLE_LINKS = {
    "knowledge-curator": {"kgis": ["KGI-03", "KGI-05", "KGI-06"], "key_factors": ["KF-01", "KF-05", "KF-07"]},
    "okf-steward": {"kgis": ["KGI-01", "KGI-06"], "key_factors": ["KF-02", "KF-07"]},
    "agent-auditor": {"kgis": ["KGI-04", "KGI-06"], "key_factors": ["KF-03", "KF-06", "KF-07"]},
    "evidence-auditor": {"kgis": ["KGI-02", "KGI-04", "KGI-06"], "key_factors": ["KF-04", "KF-06"]},
}

SEVERITY_PRIORITY = {"critical": 0, "error": 1, "warning": 2, "info": 3}


def assign_role(code: str) -> str:
    for prefixes, role in ROLE_RULES:
        if code.startswith(prefixes):
            return role
    return "okf-steward"


def candidate_id(finding: dict[str, Any]) -> str:
    material = "|".join(str(finding.get(key, "")) for key in ("severity", "code", "source", "message"))
    return "cw-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def next_action(finding: dict[str, Any], role: str) -> str:
    code = finding.get("code", "")
    source = finding.get("source", "unknown source")
    if code == "stale-canonical-source":
        return f"Review fresh evidence for {source}; prepare a candidate update or explicitly re-verify the existing canonical state."
    if code == "inventory-coverage":
        return "Classify uncovered repository files into an existing fact family or propose a new fact family with one canonical owner."
    if code in {"missing-canonical-source", "competing-canonical-owner"}:
        return "Restore or resolve canonical ownership without deleting source evidence; require authorized resolution for competing truth."
    if role == "agent-auditor":
        return "Compare the agent contract against registry, eval, authority, runtime-evidence, and rollback gates; prepare a bounded agent change proposal."
    if role == "evidence-auditor":
        return "Bind the claim to evidence and recommend a Promotion stop until the governance boundary is restored."
    if role == "okf-steward":
        return "Reconcile the finding against Goal/KGI/Phase links and prepare the smallest bounded OKF or work-planning change."
    return "Prepare a bounded candidate change with source provenance and verification criteria."


def verification_for(finding: dict[str, Any], role: str) -> list[str]:
    common = [
        "Re-run tools/audit_control_plane.py with the same or newer evidence snapshot.",
        "No new critical/error finding is introduced.",
        "Human approval, Capability Grant, Promotion, Current Truth, runtime activation, Final Human GO, and Public Beta GO remain unchanged unless separately authorized.",
    ]
    if role == "knowledge-curator":
        common.insert(0, "Canonical owner, provenance, freshness, and contradiction state are explicit.")
    elif role == "agent-auditor":
        common.insert(0, "Agent eval, least-privilege authority, rollback, and retirement path remain explicit.")
    elif role == "okf-steward":
        common.insert(0, "KGI/Key Factor/Phase links are valid and metric claims are evidence-backed.")
    elif role == "evidence-auditor":
        common.insert(0, "Claim-to-evidence binding is exact enough to justify any proposed status change.")
    return common


def plan(root: Path, as_of: date, include_info: bool = False) -> dict[str, Any]:
    report = build_report(root, as_of)
    work: list[dict[str, Any]] = []
    for finding in report["findings"]:
        if finding["severity"] == "info" and not include_info:
            continue
        role = assign_role(finding["code"])
        links = ROLE_LINKS[role]
        work.append(
            {
                "candidate_work_id": candidate_id(finding),
                "state": "candidate_only",
                "priority": finding["severity"],
                "assigned_agent_role": role,
                "source_finding": {
                    "code": finding["code"],
                    "severity": finding["severity"],
                    "source": finding.get("source"),
                    "message": finding["message"],
                    "evidence": finding.get("evidence"),
                },
                "kgi_links": links["kgis"],
                "key_factor_links": links["key_factors"],
                "next_action": next_action(finding, role),
                "verification": verification_for(finding, role),
                "authority": "proposal_only",
            }
        )
    work.sort(key=lambda item: (SEVERITY_PRIORITY[item["priority"]], item["candidate_work_id"]))
    return {
        "schema_version": 1,
        "kind": "candidate_only_maintenance_plan",
        "as_of": as_of.isoformat(),
        "source_audit_status": report["status"],
        "source_audit_summary": report["summary"],
        "candidate_work_count": len(work),
        "candidate_work": work,
        "claims": {
            "issue_created": False,
            "work_order_promoted": False,
            "agent_activated": False,
            "capability_grant_created": False,
            "current_truth_changed": False,
            "runtime_deployed": False,
            "public_beta_go_created": False,
        },
    }


def markdown(value: dict[str, Any]) -> str:
    lines = [
        "# Kotodama Candidate Maintenance Plan",
        "",
        f"- As of: `{value['as_of']}`",
        f"- Source audit: **{value['source_audit_status']}**",
        f"- Candidate work: **{value['candidate_work_count']}**",
        "",
    ]
    if not value["candidate_work"]:
        lines.append("No candidate maintenance work.")
    for item in value["candidate_work"]:
        lines += [
            f"## {item['candidate_work_id']} — {item['assigned_agent_role']}",
            "",
            f"- Priority: **{item['priority']}**",
            f"- Finding: `{item['source_finding']['code']}` — {item['source_finding']['message']}",
            f"- KGI: {', '.join(item['kgi_links'])}",
            f"- Key Factors: {', '.join(item['key_factor_links'])}",
            f"- Next action: {item['next_action']}",
            "- Verification:",
        ]
        lines.extend(f"  - {criterion}" for criterion in item["verification"])
        lines.append("")
    lines += [
        "This is proposal-only. It does not create an Issue, execute a Work Order, grant capability, activate an agent, promote Current Truth, deploy runtime, or create Public Beta GO.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--include-info", action="store_true")
    args = parser.parse_args()
    value = plan(args.root.resolve(), parse_day(args.as_of), args.include_info)
    print(markdown(value) if args.format == "markdown" else json.dumps(value, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
