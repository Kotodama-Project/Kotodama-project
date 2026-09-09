from __future__ import annotations

from .foundation import *  # noqa: F401,F403


def okf_conformance_issues(bundle: Bundle) -> tuple[Issue, ...]:
    """Return only failures from the normative OKF v0.2 conformance rules.

    OKF v0.2 requires parseable frontmatter with a non-empty ``type`` on each
    non-reserved Markdown file, and valid reserved-file structure when those
    files are present. Missing optional metadata, missing indexes, unknown
    fields/types, and broken links are deliberately not conformance failures.
    """

    issues = [
        issue
        for issue in bundle.issues
        if issue.code == "FRONTMATTER"
        or issue.code in OKF_RESERVED_CONFORMANCE_CODES
    ]
    for concept in bundle.concepts:
        value = concept.metadata.get("type")
        if not isinstance(value, str) or not value.strip():
            issues.append(
                Issue(
                    "error",
                    "OKF_TYPE",
                    concept.document.path.relative_to(bundle.root).as_posix(),
                    "OKF v0.2 requires a non-empty type field",
                )
            )
    return tuple(sorted(set(issues)))


def validation_verdicts(bundle: Bundle) -> dict[str, Any]:
    okf_errors = [issue for issue in okf_conformance_issues(bundle) if issue.level == "error"]
    profile_errors = [issue for issue in bundle.issues if issue.level == "error"]
    return {
        "OKF_CONFORMANT": {
            "verdict": "PASS" if not okf_errors else "FAIL",
            "error_count": len(okf_errors),
            "issues": [issue.as_dict() for issue in okf_errors],
        },
        "KOTODAMA_PROFILE_PASS": {
            "verdict": "PASS" if not profile_errors else "FAIL",
            "error_count": len(profile_errors),
            "issues": [issue.as_dict() for issue in profile_errors],
        },
        "DECISION_READY": {
            "verdict": "NOT_EVALUATED",
            "reason": "Run the readiness command with an explicit actor and purpose.",
        },
    }


def decision_readiness_report(
    bundle: Bundle,
    *,
    actor: str,
    purpose: str,
    concept_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Audit content readiness without granting access or decision authority."""

    actor = actor.strip()
    purpose = purpose.strip()
    if not actor:
        raise KnowledgeBaseError("decision readiness requires a non-empty actor")
    if not purpose:
        raise KnowledgeBaseError("decision readiness requires a non-empty purpose")

    by_id = bundle.by_id
    requested_ids = tuple(sorted(set(concept_ids)))
    missing_ids = tuple(concept_id for concept_id in requested_ids if concept_id not in by_id)
    selected = (
        tuple(by_id[concept_id] for concept_id in requested_ids if concept_id in by_id)
        if requested_ids
        else bundle.concepts
    )

    rows: list[dict[str, Any]] = []
    ready_count = 0
    for concept in selected:
        blockers: list[str] = []
        metadata = concept.metadata
        extension = concept.extension
        if metadata.get("status") != "stable":
            blockers.append("DOCUMENT_NOT_STABLE")
        if extension.get("knowledge_state") != "confirmed":
            blockers.append("KNOWLEDGE_NOT_CONFIRMED")
        if not _verification_entries(metadata):
            blockers.append("NO_INDEPENDENT_VERIFICATION")
        if concept.is_stale:
            blockers.append("STALE")
        if not concept.source_resources:
            blockers.append("NO_SOURCE")
        if not extension.get("agent_use", {}).get("discoverable", False):
            blockers.append("NOT_DISCOVERABLE")
        if blockers:
            content_verdict = "NOT_READY"
        else:
            content_verdict = "CONTENT_READY"
            ready_count += 1
        rows.append(
            {
                "id": concept.concept_id,
                "content_verdict": content_verdict,
                "blockers": blockers,
            }
        )

    denominator = len(selected)
    content_ready_ratio = round(ready_count / denominator, 4) if denominator else None
    global_blockers = []
    if missing_ids:
        global_blockers.append("UNKNOWN_CONCEPT_ID")
    # This public bundle has no authoritative actor/purpose access resolver or
    # decision grant. Naming them makes the audit scoped, but cannot manufacture
    # either authority.
    global_blockers.extend(
        [
            "ACTOR_PURPOSE_ACCESS_NOT_RESOLVED",
            "DECISION_AUTHORITY_NOT_GRANTED",
        ]
    )
    if ready_count != denominator:
        global_blockers.append("CONTENT_NOT_READY")

    return {
        "kind": "kotodama.okf-decision-readiness-audit",
        "schema_revision": "v1",
        "bundle_id": bundle.profile["bundle_id"],
        "source_digest": bundle.source_digest,
        "actor": actor,
        "purpose": purpose,
        "authority": "projection_only",
        "DECISION_READY": "NEEDS_RESOLUTION",
        "content_ready_count": ready_count,
        "concept_count": denominator,
        "content_ready_ratio": content_ready_ratio,
        "global_blockers": global_blockers,
        "missing_concept_ids": list(missing_ids),
        "concepts": rows,
        "consumer_rule": "Resolve access and decision authority in their canonical systems; this audit cannot grant either.",
    }


def readiness_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Kotodama decision-readiness audit",
        "",
        f"- Verdict: **{report['DECISION_READY']}**",
        f"- Actor: `{report['actor']}`",
        f"- Purpose: `{report['purpose']}`",
        f"- Source digest: `{report['source_digest']}`",
        "- Authority: **projection only**",
        f"- Content ready: `{report['content_ready_count']}/{report['concept_count']}` (`{report['content_ready_ratio']}`)",
        "",
        "## Global blockers",
        "",
    ]
    lines.extend(f"- `{blocker}`" for blocker in report["global_blockers"])
    if report["missing_concept_ids"]:
        lines.extend(["", "## Missing concepts", ""])
        lines.extend(f"- `{concept_id}`" for concept_id in report["missing_concept_ids"])
    lines.extend(["", "## Concepts", ""])
    for concept in report["concepts"]:
        blockers = ", ".join(concept["blockers"]) or "none"
        lines.append(
            f"- `{concept['id']}` — **{concept['content_verdict']}**; blockers: `{blockers}`"
        )
    lines.extend(["", str(report["consumer_rule"]), ""])
    return "\n".join(lines)


__all__ = [name for name in globals() if not name.startswith("__")]
