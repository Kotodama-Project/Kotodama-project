#!/usr/bin/env python3
"""Read-only structural audit of the public knowledge and agent responsibility indexes.

The audit intentionally has no mutation path. It verifies control-plane structure,
repository inventory coverage, freshness signals, cross-registry links, and the
boundary that agent automation cannot manufacture authority or live-state claims.
"""

from __future__ import annotations

import argparse
import fnmatch
import html
import json
import os
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from integration_contract_inputs import load_contract, local_schema_references_only
from knowledge_work_validator import read_bound
from knowledge_base import load_bundle, KnowledgeBaseError
from kotodama_kb.foundation import _assert_current

SEVERITY = {"info": 0, "warning": 1, "error": 2, "critical": 3}
REGISTRIES = {
    "knowledge": "governance/knowledge-registry.json",
    "agents": "governance/agent-registry.json",
    "audit": "governance/audit-policy.json",
}


def load_json(root: Path, relative: str) -> dict[str, Any]:
    value = load_contract(root, relative)
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def parse_day(value: str) -> date:
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def add(findings: list[dict[str, Any]], severity: str, code: str, message: str,
        *, source: str | None = None, evidence: Any = None) -> None:
    item: dict[str, Any] = {"severity": severity, "code": code, "message": message}
    if source is not None:
        item["source"] = source
    if evidence is not None:
        item["evidence"] = evidence
    findings.append(item)


def duplicates(values: list[str]) -> list[str]:
    return sorted(k for k, count in Counter(values).items() if count > 1)


def path_matches(path: str, patterns: list[str]) -> bool:
    normalized = path.replace(os.sep, "/")
    return any(fnmatch.fnmatchcase(normalized, pattern) for pattern in patterns)


def inventory(root: Path, include: list[str], exclude: list[str]) -> list[str]:
    """Bound enumeration, prune excluded directories, and never follow links."""
    result: list[str] = []
    visited = 0
    stack = [root]
    while stack:
        directory = stack.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                visited += 1
                if visited > 20000:
                    raise ValueError("inventory entry budget exceeded")
                rel = Path(entry.path).relative_to(root).as_posix()
                if rel == ".git" or path_matches(rel, exclude):
                    continue
                metadata = entry.stat(follow_symlinks=False)
                linked = entry.is_symlink() or bool(getattr(metadata, "st_file_attributes", 0) & 0x400)
                if not linked and entry.is_dir(follow_symlinks=False):
                    if not path_matches(rel + "/", exclude):
                        stack.append(Path(entry.path))
                elif path_matches(rel, include):
                    result.append(rel)
    return sorted(result)


def freshness_day(root: Path, family: dict[str, Any]) -> date | None:
    cfg = family.get("freshness", {})
    mode = cfg.get("mode")
    if mode == "manual":
        return None
    if mode == "json_field":
        value = load_json(root, family["canonical_path"]).get(cfg.get("field", ""))
        if isinstance(value, str):
            return parse_day(value)
        raise ValueError(f"freshness field missing in {family['canonical_path']}")
    if mode == "date_line":
        prefix = cfg.get("prefix")
        if not isinstance(prefix, str):
            raise ValueError("date_line freshness requires prefix")
        for line in read_bound(root, family["canonical_path"], 256 * 1024).decode("utf-8").splitlines():
            if line.startswith(prefix):
                return parse_day(line[len(prefix):].strip())
        raise ValueError(f"freshness prefix {prefix!r} missing in {family['canonical_path']}")
    raise ValueError(f"unknown freshness mode: {mode}")


def check_knowledge(root: Path, knowledge: dict[str, Any], findings: list[dict[str, Any]],
                    as_of: date) -> tuple[set[str], dict[str, Any]]:
    families = knowledge.get("fact_families", [])
    ids = [x.get("id", "") for x in families if isinstance(x, dict)]
    for duplicate in duplicates(ids):
        add(findings, "error", "duplicate-fact-family", f"duplicate fact family id: {duplicate}", source=REGISTRIES["knowledge"])

    canonical_paths = [x.get("canonical_path", "") for x in families if isinstance(x, dict)]
    for duplicate in duplicates(canonical_paths):
        add(findings, "error", "competing-canonical-owner", f"multiple fact families claim the same canonical path: {duplicate}", source=REGISTRIES["knowledge"])

    stale_count = 0
    for family in families:
        if not isinstance(family, dict):
            continue
        canonical_path = family.get("canonical_path")
        try:
            read_bound(root, canonical_path, 256 * 1024)
        except (ValueError, OSError, TypeError):
            add(findings, "error", "missing-canonical-source", f"{family.get('id')} canonical source is unavailable or unsafe", source=REGISTRIES["knowledge"])
            continue
        cfg = family.get("freshness", {})
        max_age = cfg.get("max_age_days")
        if cfg.get("mode") != "manual":
            try:
                observed = freshness_day(root, family)
                if observed is not None:
                    age = (as_of - observed).days
                    if age < 0:
                        raise ValueError("future freshness evidence")
                    if isinstance(max_age, int) and age > max_age:
                        stale_count += 1
                        add(findings, cfg.get("severity", "warning"), "stale-canonical-source", f"{family.get('id')} is {age} days old; SLA is {max_age} days", source=canonical_path, evidence={"observed_date": observed.isoformat(), "as_of": as_of.isoformat()})
            except Exception as exc:
                add(findings, "error", "freshness-check-failed", f"{family.get('id')}: invalid freshness evidence", source=canonical_path)

    scope = knowledge.get("inventory_scope", {})
    files = inventory(root, scope.get("include", ["*"]), scope.get("exclude", []))
    patterns: list[str] = []
    for family in families:
        if isinstance(family, dict):
            patterns.extend(family.get("classification_patterns", []))
    classified = [p for p in files if path_matches(p, patterns)]
    uncovered = sorted(set(files) - set(classified))
    coverage = 1.0 if not files else len(classified) / len(files)
    minimum = max(0.98, float(scope.get("minimum_classification_coverage", 1.0)))
    if coverage < minimum:
        add(findings, "error", "inventory-coverage", f"repository classification coverage {coverage:.1%} is below {minimum:.1%}", source=REGISTRIES["knowledge"], evidence={"uncovered_sample": uncovered[:25], "uncovered_count": len(uncovered)})
    metrics = {
        "repository_file_count": len(files),
        "classified_file_count": len(classified),
        "classification_coverage": round(coverage, 6),
        "uncovered_count": len(uncovered),
        "uncovered_sample": uncovered[:25],
        "fact_family_count": len(ids),
        "stale_fact_family_count": stale_count,
    }
    return set(ids), metrics


def check_agents(root: Path, agents: dict[str, Any], fact_ids: set[str],
                 concept_ids: set[str], findings: list[dict[str, Any]]) -> dict[str, Any]:
    entries = agents.get("agents", [])
    agent_ids = [x.get("id", "") for x in entries if isinstance(x, dict)]
    for duplicate in duplicates(agent_ids):
        add(findings, "error", "duplicate-agent-id", f"duplicate agent id: {duplicate}", source=REGISTRIES["agents"])

    active = 0
    for agent in entries:
        if not isinstance(agent, dict):
            continue
        aid = agent.get("id")
        for ref in agent.get("reads_fact_families", []):
            if ref not in fact_ids:
                add(findings, "error", "unknown-fact-family", f"{aid} reads unknown fact family {ref}", source=REGISTRIES["agents"])
        for ref in agent.get("knowledge_refs", []):
            if ref not in concept_ids:
                add(findings, "error", "unknown-concept-reference", f"{aid} references unknown Concept {ref}", source=REGISTRIES["agents"])

        state = agent.get("activation_state")
        authority = agent.get("authority")
        if state != "active" and authority == "bounded_execute":
            add(findings, "error", "preactive-execute-authority", f"{aid} is {state} but requests bounded_execute authority", source=REGISTRIES["agents"])
        if state == "active" or agent.get("runtime_evidence") is not None:
            add(findings, "critical", "index-cannot-activate", f"{aid}: a responsibility index cannot assert runtime activation", source=REGISTRIES["agents"])
        eval_gate = agent.get("eval_gate", {})
        if not eval_gate.get("required_before_activation") or eval_gate.get("critical_failures_allowed") != 0:
            add(findings, "critical", "agent-eval-gate", f"{aid} does not preserve a closed critical eval gate", source=REGISTRIES["agents"])
    return {"registered_agent_count": len(agent_ids), "active_agent_count": active}


def check_audit_policy(policy: dict[str, Any], findings: list[dict[str, Any]]) -> None:
    boundaries = policy.get("autonomy_boundaries", {})
    required_forbidden = {
        "human_approval", "capability_grant", "promotion", "current_truth_change",
        "runtime_deployment", "final_human_go", "public_beta_go",
    }
    forbidden = set(boundaries.get("automatic_outputs_forbidden", []))
    if forbidden.intersection(boundaries.get("automatic_outputs_allowed", [])):
        add(findings, "critical", "autonomy-policy-conflict", "automatic outputs cannot be both allowed and forbidden", source=REGISTRIES["audit"])
    for cadence in policy.get("cadence", []):
        if forbidden.intersection(cadence.get("outputs", [])):
            add(findings, "critical", "forbidden-cadence-output", "cadence declares a globally forbidden output", source=REGISTRIES["audit"])
    missing = sorted(required_forbidden - forbidden)
    if missing:
        add(findings, "critical", "autonomy-boundary-gap", f"automatic forbidden outputs are missing: {', '.join(missing)}", source=REGISTRIES["audit"])
    if boundaries.get("agentic_maintenance_default") != "proposal_only":
        add(findings, "critical", "unsafe-agentic-default", "agentic maintenance default must remain proposal_only in this phase", source=REGISTRIES["audit"])


def build_report(root: Path, as_of: date) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    registries: dict[str, dict[str, Any]] = {}
    for name, rel in REGISTRIES.items():
        if not (root / rel).exists():
            add(findings, "critical", "missing-registry", f"missing registry: {rel}", source=rel)
            registries[name] = {}
            continue
        try:
            value = load_json(root, rel)
            schema = load_json(root, "schemas/" + Path(rel).stem + ".schema.json")
            if not local_schema_references_only(schema):
                raise ValueError("external schema reference")
            Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
            registries[name] = value
        except Exception as exc:
            add(findings, "critical", "invalid-registry-json", f"registry does not satisfy its bounded schema: {rel}", source=rel)
            registries[name] = {}

    concept_ids: set[str] = set()
    bundle = None
    try:
        bundle = load_bundle(root, as_of=datetime.combine(as_of, datetime.min.time(), tzinfo=timezone.utc))
        if any(issue.level == "error" for issue in bundle.issues):
            raise ValueError("invalid knowledge profile")
        concept_ids = {concept.concept_id for concept in bundle.concepts}
    except (ValueError, OSError, KnowledgeBaseError):
        add(findings, "error", "knowledge-profile-unavailable", "canonical knowledge profile is invalid or unavailable", source="knowledge/profile.yaml")
    fact_ids, knowledge_metrics = check_knowledge(root, registries["knowledge"], findings, as_of)
    agent_metrics = check_agents(root, registries["agents"], fact_ids, concept_ids, findings)
    check_audit_policy(registries["audit"], findings)

    if bundle is not None:
        try:
            _assert_current(bundle)
        except (ValueError, OSError, KnowledgeBaseError):
            add(findings, "error", "knowledge-input-changed", "canonical knowledge changed during the audit", source="knowledge/profile.yaml")

    findings.sort(key=lambda x: (-SEVERITY[x["severity"]], x["code"], x["message"]))
    counts = {level: sum(1 for x in findings if x["severity"] == level) for level in SEVERITY}
    return {
        "schema_version": 1,
        "audit_kind": "candidate_only_read_only_control_plane",
        "as_of": as_of.isoformat(),
        "scope": "explicit_repository_root",
        "status": "PASS" if counts["critical"] == 0 and counts["error"] == 0 else "REFUSED",
        "summary": {**counts, **knowledge_metrics, **agent_metrics},
        "claims": {
            "human_approval_created": False,
            "capability_grant_created": False,
            "runtime_activated": False,
            "promotion_created": False,
            "current_truth_changed": False,
            "final_human_go_created": False,
            "public_beta_go_created": False,
        },
        "findings": findings,
    }


def escaped(value: str) -> str:
    value = html.escape(value, quote=True).replace("\n", " ").replace("\r", " ")
    for character in "\\`*_{}[]()#+-.!|":
        value = value.replace(character, "\\" + character)
    return value


def to_markdown(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        "# Kotodama Control Plane Audit",
        "",
        f"- Status: **{report['status']}**",
        f"- As of: `{report['as_of']}`",
        f"- Critical / Error / Warning / Info: **{s['critical']} / {s['error']} / {s['warning']} / {s['info']}**",
        f"- Repository classification: **{s['classification_coverage']:.1%}** ({s['classified_file_count']}/{s['repository_file_count']})",
        f"- Fact families: **{s['fact_family_count']}**",
        f"- Registered / active agents: **{s['registered_agent_count']} / {s['active_agent_count']}**",
        "",
        "## Findings",
        "",
    ]
    if not report["findings"]:
        lines.append("- None.")
    else:
        for finding in report["findings"]:
            source = f" — {escaped(finding['source'])}" if finding.get("source") else ""
            lines.append(f"- **{finding['severity'].upper()} `{finding['code']}`**: {escaped(finding['message'])}{source}")
    lines += [
        "",
        "## Authority boundary",
        "",
        "This audit is read-only. PASS does not create Human approval, Capability Grant, runtime activation, Promotion, Current Truth, Final Human GO, or Public Beta GO.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--as-of", default=date.today().isoformat(), help="YYYY-MM-DD; deterministic audits may pin this")
    parser.add_argument("--fail-on", choices=("warning", "error", "critical", "never"), default="error")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        as_of = parse_day(args.as_of)
        report = build_report(root, as_of)
    except Exception as exc:
        print(json.dumps({"status": "REFUSED", "error": "invalid_or_unavailable_audit_input"}))
        return 2

    if args.format == "markdown":
        print(to_markdown(report))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.fail_on == "never":
        return 0
    threshold = SEVERITY[args.fail_on]
    return 1 if any(SEVERITY[f["severity"]] >= threshold for f in report["findings"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
