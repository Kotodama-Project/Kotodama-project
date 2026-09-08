from __future__ import annotations

from .foundation import *  # noqa: F401,F403
from .reserved import *  # noqa: F401,F403
from .load import *  # noqa: F401,F403

def _require_valid_bundle(bundle: Bundle) -> None:
    if any(issue.level == "error" for issue in bundle.issues):
        raise KnowledgeBaseError("invalid knowledge bundle; run validate before retrieval")


def _eligible_context(concept: Concept) -> bool:
    return (
        concept.extension.get("agent_use", {}).get("discoverable", False)
        and concept.extension.get("knowledge_state") in {"candidate", "confirmed"}
        and concept.metadata.get("status") != "deprecated"
        and not concept.is_stale
    )


def _search_haystacks(concept: Concept) -> dict[str, str]:
    metadata = concept.metadata
    extension = concept.extension
    tags = " ".join(str(tag) for tag in metadata.get("tags", []))
    refs = " ".join(
        str(ref)
        for key in ("goal_refs", "kgi_refs", "initiative_refs")
        for ref in extension.get(key, [])
    )
    return {
        "id": _normalized_text(concept.concept_id),
        "title": _normalized_text(str(metadata.get("title", ""))),
        "description": _normalized_text(str(metadata.get("description", ""))),
        "tags": _normalized_text(tags),
        "refs": _normalized_text(refs),
        "body": _normalized_text(_without_code_fences(concept.document.body)),
    }


def query_bundle(
    bundle: Bundle,
    query: str,
    *,
    limit: int = 10,
    type_filter: str | None = None,
    tag_filter: str | None = None,
    include_stale: bool = False,
) -> tuple[SearchResult, ...]:
    _require_valid_bundle(bundle)
    normalized_query = _normalized_text(query.strip())
    if not normalized_query:
        raise KnowledgeBaseError("query must not be empty")
    tokens = [token for token in re.findall(r"[\w-]+", normalized_query) if token]
    results: list[SearchResult] = []
    for concept in bundle.concepts:
        extension = concept.extension
        agent_use = extension.get("agent_use", {})
        if not agent_use.get("discoverable", False):
            continue
        if extension.get("knowledge_state") in {"revoked", "deprecated"} or concept.metadata.get("status") == "deprecated":
            continue
        if concept.is_stale and not include_stale:
            continue
        if type_filter and _normalized_text(str(concept.metadata.get("type", ""))) != _normalized_text(type_filter):
            continue
        tags = [str(tag) for tag in concept.metadata.get("tags", [])]
        if tag_filter and _normalized_text(tag_filter) not in {_normalized_text(tag) for tag in tags}:
            continue

        haystacks = _search_haystacks(concept)
        score = 0.0
        reasons: list[str] = []
        field_weights = {
            "id": 5.0,
            "title": 8.0,
            "description": 5.0,
            "tags": 4.0,
            "refs": 5.0,
            "body": 1.0,
        }
        for field, weight in field_weights.items():
            text = haystacks[field]
            if normalized_query in text:
                score += weight * 2
                reasons.append(f"query-in-{field}")
            for token in tokens:
                if token in text:
                    score += weight
                    reasons.append(f"token-in-{field}")
        # Trust and priority may rank real matches, never manufacture a match.
        if not reasons:
            continue
        if concept.trust_tier == "human-reviewed":
            score += 2.0
        elif concept.trust_tier == "machine-confirmed":
            score += 1.0
        score += max(0, 100 - int(extension.get("context_priority", 100))) / 100.0
        if score > 0:
            results.append(SearchResult(concept, score, tuple(sorted(set(reasons)))))

    results.sort(
        key=lambda result: (
            -result.score,
            int(result.concept.extension.get("context_priority", 1000)),
            result.concept.concept_id,
        )
    )
    return tuple(results[:limit])


def _mandatory_governance_ids(bundle: Bundle) -> set[str]:
    return {
        concept.concept_id
        for concept in bundle.concepts
        if "governance" in set(concept.metadata.get("tags", []))
        and int(concept.extension.get("context_priority", 1000)) <= 10
    }


def select_context(
    bundle: Bundle,
    *,
    goals: Sequence[str],
    kgis: Sequence[str],
    initiatives: Sequence[str],
    tags: Sequence[str],
    max_concepts: int | None,
) -> ContextSelection:
    _require_valid_bundle(bundle)
    filters = {
        "goals": tuple(sorted(set(goals))),
        "kgis": tuple(sorted(set(kgis))),
        "initiatives": tuple(sorted(set(initiatives))),
        "tags": tuple(sorted(set(tags))),
    }
    if not any(filters.values()):
        raise KnowledgeBaseError("context requires at least one --goal, --kgi, --initiative, or --tag")

    limit = max_concepts if max_concepts is not None else int(bundle.profile["quality"]["max_context_concepts"])
    configured_max = int(bundle.profile["quality"]["max_context_concepts"])
    if limit < 1 or limit > configured_max:
        raise KnowledgeBaseError(f"--max-concepts must be between 1 and {configured_max}")

    requested_goals = set(goals)
    requested_kgis = set(kgis)
    requested_initiatives = set(initiatives)
    requested_tags = {_normalized_text(tag) for tag in tags}
    matches: dict[str, Concept] = {}
    unresolved: set[str] = set()
    required: set[str] = set()
    seen_filters: dict[str, set[str]] = {key: set() for key in filters}

    for concept in bundle.concepts:
        extension = concept.extension
        concept_tags = {_normalized_text(str(tag)) for tag in concept.metadata.get("tags", [])}
        seen_filters["goals"].update(requested_goals & set(extension.get("goal_refs", [])))
        seen_filters["kgis"].update(requested_kgis & set(extension.get("kgi_refs", [])))
        seen_filters["initiatives"].update(requested_initiatives & set(extension.get("initiative_refs", [])))
        seen_filters["tags"].update(requested_tags & concept_tags)
        direct = bool(
            requested_goals & set(extension.get("goal_refs", []))
            or requested_kgis & set(extension.get("kgi_refs", []))
            or requested_initiatives & set(extension.get("initiative_refs", []))
            or requested_tags & concept_tags
        )
        if not direct:
            continue
        critical = bool(set(concept.metadata.get("tags", [])) & set(bundle.profile["quality"].get("critical_tags", [])))
        if critical:
            required.add(concept.concept_id)
        if not _eligible_context(concept):
            unresolved.add(concept.concept_id)
            continue
        matches[concept.concept_id] = concept

    for key, requested in filters.items():
        for value in requested:
            normalized = _normalized_text(value) if key == "tags" else value
            if normalized not in seen_filters[key]:
                unresolved.add(f"filter:{key}:{value}")

    by_id = bundle.by_id
    mandatory = _mandatory_governance_ids(bundle)
    required.update(mandatory)
    for concept_id in mandatory:
        concept = by_id[concept_id]
        if _eligible_context(concept):
            matches.setdefault(concept_id, concept)
        else:
            unresolved.add(concept_id)

    # Include directly linked concepts one hop away when they are safe and fit the
    # same public projection. This supports progressive disclosure without a full
    # graph dump.
    linked_ids = {
        linked_id
        for concept in matches.values()
        for linked_id in concept.resolved_concept_links
    }
    for linked_id in sorted(linked_ids):
        concept = by_id.get(linked_id)
        if not concept:
            continue
        if _eligible_context(concept):
            matches.setdefault(linked_id, concept)
        else:
            unresolved.add(linked_id)

    ordered = sorted(
        matches.values(),
        key=lambda concept: (
            concept.concept_id not in required,
            not bool(
                requested_initiatives & set(concept.extension.get("initiative_refs", []))
                or requested_kgis & set(concept.extension.get("kgi_refs", []))
                or requested_tags & {_normalized_text(str(tag)) for tag in concept.metadata.get("tags", [])}
            ),
            int(concept.extension.get("context_priority", 1000)),
            concept.is_stale,
            concept.concept_id,
        ),
    )
    selected = tuple(ordered[:limit])
    omitted = tuple(concept.concept_id for concept in ordered[limit:])
    unresolved.update(required - {concept.concept_id for concept in selected})
    return ContextSelection(
        selected=selected,
        omitted_ids=omitted,
        unresolved_ids=tuple(sorted(unresolved)),
        filters=filters,
    )



__all__ = [name for name in globals() if not name.startswith("__")]
