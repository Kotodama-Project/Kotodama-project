from __future__ import annotations

from .foundation import *  # noqa: F401,F403

OKF_SPEC_URL = "https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/82a483de8a381f1ed25b9dfe1dc5622622afff55/okf/SPEC.md"


def optional_timestamp_guidance(bundle: Bundle) -> tuple[Issue, ...]:
    """Report §5 timestamp guidance without widening §11 conformance rules."""
    issues = []
    for concept in bundle.concepts:
        metadata = concept.metadata
        path = concept.document.path.relative_to(bundle.root).as_posix()

        def timestamp(mapping, key, field):
            if not isinstance(mapping, dict) or key not in mapping:
                return
            value = mapping[key]
            try:
                if not isinstance(value, str):
                    raise KnowledgeBaseError("timestamp type")
                _parse_datetime(value, field=field, path=path)
            except (KnowledgeBaseError, OverflowError):
                issues.append(Issue("warning", "OKF_TIMESTAMP_GUIDANCE", path,
                                    f"{field} should be an ISO 8601 datetime with an explicit UTC offset"))

        def window(mapping, prefix):
            if isinstance(mapping, dict):
                for key in ("from", "to"):
                    timestamp(mapping.get("usage_window"), key, prefix + "usage_window." + key)

        timestamp(metadata, "stale_after", "stale_after")
        timestamp(metadata.get("generated"), "at", "generated.at")
        verified = metadata.get("verified", [])
        if isinstance(verified, dict):
            verified = [verified]
        if isinstance(verified, list):
            for item in verified:
                timestamp(item, "at", "verified.at")
        window(metadata, "")
        sources = metadata.get("sources", [])
        if isinstance(sources, list):
            for item in sources:
                timestamp(item, "last_modified", "sources.last_modified")
                window(item, "sources.")
    return tuple(sorted(set(issues)))


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
    _assert_current(bundle)
    okf_errors = [issue for issue in okf_conformance_issues(bundle) if issue.level == "error"]
    profile_errors = [issue for issue in bundle.issues if issue.level == "error"]
    return {
        "specification": {"version": "0.2", "url": OKF_SPEC_URL},
        "OKF_CONFORMANT": {
            "verdict": "PASS" if not okf_errors else "FAIL",
            "error_count": len(okf_errors),
            "issues": [issue.as_dict() for issue in okf_errors],
            "guidance": [issue.as_dict() for issue in optional_timestamp_guidance(bundle)],
        },
        "KOTODAMA_PROFILE_PASS": {
            "verdict": "PASS" if not profile_errors else "FAIL",
            "error_count": len(profile_errors),
            "issues": [issue.as_dict() for issue in profile_errors],
        },
        "DECISION_READY": {
            "verdict": "NOT_EVALUATED",
            "reason": "Run readiness with an explicit actor, purpose, time, and Task reference.",
        },
    }


def decision_readiness_report(
    bundle: Bundle,
    *,
    actor: str,
    purpose: str,
    concept_ids: Sequence[str] = (),
    task: str | None = None,
    evaluated_at: dt.datetime | None = None,
    mandatory_concept_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Audit content readiness without granting access or decision authority."""

    def scope_text(value):
        if not isinstance(value, str) or not value.strip() or len(value) > 4096:
            raise KnowledgeBaseError("READINESS_SCOPE_INVALID")
        return value.strip()

    def scope_ids(value):
        if not isinstance(value, (list, tuple)) or len(value) > MAX_INPUT_FILES:
            raise KnowledgeBaseError("READINESS_CONCEPT_IDS_INVALID")
        # Concept IDs are exact paths. Whitespace normalization would name a
        # different concept while making a malformed requirement look included.
        if any(not isinstance(item, str) or not item or item != item.strip() or len(item) > 4096 for item in value):
            raise KnowledgeBaseError("READINESS_CONCEPT_IDS_INVALID")
        return tuple(value)

    actor, purpose = scope_text(actor), scope_text(purpose)
    task = scope_text(task) if task is not None else None
    concept_ids = scope_ids(concept_ids)
    if mandatory_concept_ids is not None:
        mandatory_concept_ids = scope_ids(mandatory_concept_ids)
    if evaluated_at is not None and not isinstance(evaluated_at, dt.datetime):
        raise KnowledgeBaseError("READINESS_INSTANT_INVALID")
    if evaluated_at is not None and (evaluated_at.tzinfo is None or evaluated_at != bundle.as_of):
        raise KnowledgeBaseError("READINESS_INSTANT_MISMATCH_RELOAD_REQUIRED")
    scope_bound = bool(task) and evaluated_at is not None
    _assert_current(bundle)
    invalid_bundle = any(issue.level == "error" for issue in bundle.issues)

    by_id = bundle.by_id
    requested_ids = tuple(sorted(set(concept_ids)))
    missing_ids = tuple(concept_id for concept_id in requested_ids if concept_id not in by_id)
    selected = (
        tuple(by_id[concept_id] for concept_id in requested_ids if concept_id in by_id)
        if requested_ids
        else bundle.concepts
    )
    selected_ids = {concept.concept_id for concept in selected}
    bound_paths = {name for name, digest in bundle.input_bindings}
    missing_mandatory = sorted(set(mandatory_concept_ids or ()) - selected_ids)
    context_check = ("NOT_EVALUATED" if mandatory_concept_ids is None
                     else "MISSING" if missing_mandatory else "INCLUDED")

    rows: list[dict[str, Any]] = []
    ready_count = 0
    for concept in selected:
        if invalid_bundle:
            rows.append({"id": concept.concept_id, "content_verdict": "NOT_READY", "blockers": ["INVALID_BUNDLE"],
                         "checks": {key: "NOT_EVALUATED" for key in (
                             "source_resolution", "source_revision_integrity", "verification", "freshness",
                             "conflict", "access", "attestation", "mandatory_context", "final_readiness")}})
            continue
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
        if not concept.stale_after:
            blockers.append("FRESHNESS_NOT_DECLARED")
        if not concept.source_resources:
            blockers.append("NO_SOURCE")
        def source_bound(resource):
            resolved = _resolve_source_resource(source_path=concept.document.path, resource=resource,
                                                repository_root=bundle.root, bundle_root=bundle.bundle_root)
            return resolved is not None and resolved.is_relative_to(bundle.root) and resolved.relative_to(bundle.root).as_posix() in bound_paths
        local_sources = bool(concept.source_resources) and all(map(source_bound, concept.source_resources))
        if concept.source_resources and not local_sources:
            blockers.append("SOURCE_NOT_RESOLVED_LOCALLY")
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
                "checks": {
                    "source_resolution": "RESOLVED_LOCAL" if local_sources else "UNRESOLVED",
                    "source_revision_integrity": "MATCHED_LOCAL_SNAPSHOT" if local_sources else "UNRESOLVED",
                    "verification": "DECLARED_NOT_AUTHENTICATED" if _verification_entries(metadata) else "NOT_RECORDED",
                    "freshness": "STALE" if concept.is_stale else "CURRENT" if concept.stale_after else "UNKNOWN",
                    "conflict": "CONFLICTED" if extension.get("knowledge_state") == "conflicted" else "NO_CONFLICT_DECLARED",
                    "access": "UNRESOLVED",
                    "attestation": "NOT_EVALUATED",
                    "mandatory_context": context_check,
                    "final_readiness": "NEEDS_RESOLUTION" if scope_bound else "NOT_EVALUATED",
                },
            }
        )

    denominator = len(selected)
    content_ready_ratio = round(ready_count / denominator, 4) if denominator else None
    global_blockers = []
    _assert_current(bundle)
    if invalid_bundle:
        global_blockers.append("INVALID_BUNDLE")
    if missing_ids:
        global_blockers.append("UNKNOWN_CONCEPT_ID")
    if not scope_bound:
        global_blockers.append("EXPLICIT_TIME_AND_TASK_REQUIRED")
    if mandatory_concept_ids is None:
        global_blockers.append("MANDATORY_CONTEXT_NOT_DECLARED")
    elif missing_mandatory:
        global_blockers.append("MANDATORY_CONTEXT_MISSING")
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
        "schema_revision": "v2",
        "bundle_id": bundle.profile["bundle_id"],
        "source_digest": bundle.source_digest,
        "as_of": bundle.as_of.isoformat().replace("+00:00", "Z"),
        "actor": actor,
        "purpose": purpose,
        "task_ref": task or None,
        "scope": "BOUND_REFERENCE_ONLY" if scope_bound else "NOT_EVALUATED",
        "authority": "projection_only",
        "DECISION_READY": "NEEDS_RESOLUTION" if scope_bound else "NOT_EVALUATED",
        "content_ready_count": ready_count,
        "concept_count": denominator,
        "content_ready_ratio": content_ready_ratio,
        "global_blockers": global_blockers,
        "missing_concept_ids": list(missing_ids),
        "missing_mandatory_concept_ids": missing_mandatory,
        "mandatory_context": context_check,
        "concepts": rows,
        "consumer_rule": "Task and required-context inputs are declared scope, not verified owner policy. Resolve access, attestation, and decision authority in their canonical systems; this audit cannot grant them.",
    }


def readiness_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Kotodama decision-readiness audit",
        "",
        f"- Verdict: **{report['DECISION_READY']}**",
        f"- Actor: `{report['actor']}`",
        f"- Purpose: `{report['purpose']}`",
        f"- Task reference: `{report['task_ref'] or 'not supplied'}`",
        f"- Mandatory context: `{report['mandatory_context']}`",
        f"- Source digest: `{report['source_digest']}`",
        f"- As of: `{report['as_of']}`",
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
    if report["missing_mandatory_concept_ids"]:
        lines.extend(["", "## Missing required concepts", ""])
        lines.extend(f"- `{concept_id}`" for concept_id in report["missing_mandatory_concept_ids"])
    lines.extend(["", "## Concepts", ""])
    for concept in report["concepts"]:
        blockers = ", ".join(concept["blockers"]) or "none"
        lines.append(
            f"- `{concept['id']}` — **{concept['content_verdict']}**; blockers: `{blockers}`"
        )
        lines.append("  - Checks: " + ", ".join(f"`{key}={value}`" for key, value in concept["checks"].items()))
    lines.extend(["", str(report["consumer_rule"]), ""])
    return "\n".join(lines)


__all__ = [name for name in globals() if not name.startswith("__")]
