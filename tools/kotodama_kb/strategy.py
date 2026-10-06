"""Typed strategy references over OKF Concepts; definitions remain in the bundle."""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from .foundation import Concept, Issue, KnowledgeBaseError

KINDS = {
    "Goal": "goal", "Outcome": "outcome", "Metric": "metric",
    "Key Factor": "factor", "KPI": "kpi", "Initiative": "initiative",
    "Experiment": "experiment", "Decision": "decision", "Risk": "risk",
    "Measurement Policy": "measurement_policy", "Attested Computation": "computation",
    "Evidence": "evidence",
}
REFERENCE_KINDS = {
    "goal_refs": {"goal", "outcome"}, "kgi_refs": {"metric"},
    "factor_refs": {"factor"}, "initiative_refs": {"initiative"},
}
RELATIONS = {
    "measured_by": ({"goal", "outcome"}, {"metric"}),
    "computed_by": ({"metric", "kpi"}, {"computation"}),
    "enabled_by": ({"metric"}, {"factor"}),
    "observed_by": ({"factor"}, {"kpi"}),
    "advanced_by": ({"factor"}, {"initiative"}),
    "tested_by": ({"initiative"}, {"experiment"}),
    "produces": ({"initiative", "experiment"}, {"outcome", "evidence"}),
    "governed_by": (set(KINDS.values()), {"measurement_policy"}),
    **{verb: ({"decision"}, set(KINDS.values())) for verb in ("adopts", "revises", "pauses", "rejects")},
    "mitigates": ({"risk"}, {"goal", "outcome", "metric", "factor", "initiative"}),
}
ID = re.compile(r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\Z")
MEASUREMENT_FIELDS = ("baseline", "target", "deadline", "measurement_window", "exclusion_policy")


def strategy_template(concept_type: str, identifier: str) -> dict:
    """The producer extension for an unadopted definition, not a runtime grant."""
    if concept_type not in KINDS or not isinstance(identifier, str) or not ID.fullmatch(identifier):
        raise KnowledgeBaseError("STRATEGY_TEMPLATE_INVALID")
    value = {"id": identifier, "adoption_status": "candidate", "relationships": []}
    if concept_type in {"Metric", "KPI", "Measurement Policy"}:
        value.update({field: "unknown" if field == "baseline" else "not_adopted" for field in MEASUREMENT_FIELDS})
    if concept_type in {"Metric", "KPI"}:
        value["measurement_role"] = "supporting_kpi" if concept_type == "KPI" else "control_slo"
    if concept_type == "Initiative":
        value["hypothesis"] = {"intervention": "TODO", "expected_effect": "TODO", "falsifier": "TODO"}
    return value


def strategy_reference_issues(record: Mapping, index: Mapping, *, path: str) -> list[Issue]:
    """Also accepts a Task owner's reference projection without copying its state."""
    issues = []
    for field, kinds in REFERENCE_KINDS.items():
        values = record.get(field, [])
        if not isinstance(values, list) or len(values) > 256 or any(not isinstance(v, str) or not ID.fullmatch(v) for v in values):
            issues.append(Issue("error", "STRATEGY_REF_INVALID", path, f"invalid {field}"))
            continue
        for value in values:
            if value not in index:
                issues.append(Issue("error", "STRATEGY_REF_UNRESOLVED", path, f"unresolved {field}: {value}"))
            elif index[value]["kind"] not in kinds:
                issues.append(Issue("error", "STRATEGY_REF_TYPE", path, f"wrong target type for {field}: {value}"))
            elif field == "kgi_refs" and index[value].get("measurement_role") != "product_outcome":
                issues.append(Issue("error", "STRATEGY_REF_TYPE", path, "a control measure cannot replace the product outcome KGI"))
    return issues


def strategy_model(concepts: Iterable[Concept]) -> tuple[dict, list[Issue]]:
    """Validate all reference projections and produce a deterministic typed graph.

    load_bundle uses this after schema admission. An empty definition set does
    not validate unresolved references, including a Task reference projection.
    """
    concepts = tuple(concepts)
    if len(concepts) > 256:
        raise KnowledgeBaseError("STRATEGY_CONCEPT_LIMIT")
    index, definitions, issues, edges = {}, {}, [], set()
    def issue(concept, code, message):
        issues.append(Issue("error", code, "knowledge/" + concept.document.relative_path, message))
    for concept in concepts:
        value = concept.extension.get("strategy")
        if value is None:
            continue
        if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not ID.fullmatch(value["id"]):
            issue(concept, "STRATEGY_DEFINITION_INVALID", "strategy requires a stable identifier")
            continue
        identifier, kind = value["id"], KINDS.get(concept.metadata.get("type"))
        if kind is None or value.get("adoption_status") != "candidate":
            issue(concept, "STRATEGY_DEFINITION_INVALID", "unsupported type or adoption claim")
            continue
        if identifier in index:
            issue(concept, "STRATEGY_DUPLICATE_ID", "strategy identifier has multiple definitions")
            continue
        index[identifier] = {"concept_id": concept.concept_id, "kind": kind}
        if kind in {"metric", "kpi"}:
            index[identifier]["measurement_role"] = value.get("measurement_role")
        definitions[identifier] = concept
        if kind in {"metric", "kpi", "measurement_policy"}:
            for field in MEASUREMENT_FIELDS:
                expected = "unknown" if field == "baseline" else "not_adopted"
                if value.get(field) != expected:
                    issue(concept, "STRATEGY_MEASUREMENT_NOT_ADOPTED", "candidate measurements cannot adopt a value or policy")
        if kind in {"metric", "kpi"}:
            allowed = {"product_outcome", "control_slo"} if kind == "metric" else {"supporting_kpi"}
            if value.get("measurement_role") not in allowed:
                issue(concept, "STRATEGY_MEASUREMENT_ROLE", "product outcomes and control measures require distinct roles")
        if kind == "initiative":
            hypothesis = value.get("hypothesis")
            if not isinstance(hypothesis, dict) or set(hypothesis) != {"intervention", "expected_effect", "falsifier"} or any(not isinstance(v, str) or not v.strip() or v.strip().upper() in {"TODO", "UNKNOWN"} for v in hypothesis.values()):
                issue(concept, "STRATEGY_HYPOTHESIS_REQUIRED", "initiative requires an intervention, expected effect and falsifier")
    for concept in concepts:
        issues.extend(strategy_reference_issues(concept.extension, index, path="knowledge/" + concept.document.relative_path))
    for identifier, concept in sorted(definitions.items()):
        relationships = concept.extension["strategy"].get("relationships")
        if not isinstance(relationships, list) or len(relationships) > 32:
            issue(concept, "STRATEGY_RELATION_INVALID", "relationships must be a bounded list")
            continue
        for relation in relationships:
            if not isinstance(relation, dict) or set(relation) != {"type", "target"} or not isinstance(relation.get("type"), str) or not isinstance(relation.get("target"), str):
                issue(concept, "STRATEGY_RELATION_INVALID", "relationship must name a type and target")
                continue
            verb, target = relation["type"], relation["target"]
            if verb not in RELATIONS or target not in index:
                issue(concept, "STRATEGY_RELATION_UNRESOLVED", "relationship type or target is unresolved")
                continue
            origins, destinations = RELATIONS[verb]
            if index[identifier]["kind"] not in origins or index[target]["kind"] not in destinations:
                issue(concept, "STRATEGY_RELATION_TYPE", "relationship joins incompatible definition types")
                continue
            if index[target]["concept_id"] not in concept.resolved_concept_links:
                issue(concept, "STRATEGY_PORTABLE_LINK_REQUIRED", "typed relationship also requires a Markdown Concept link")
            edge = (identifier, verb, target)
            if edge in edges:
                issue(concept, "STRATEGY_DUPLICATE_RELATION", "relationship is repeated")
            edges.add(edge)
    adjacency = {key: [] for key in index}
    for origin, _, target in sorted(edges):
        adjacency[origin].append(target)
    visited, active, cyclic = set(), set(), set()
    def visit(identifier):
        if identifier in active:
            cyclic.add(identifier)
            return
        if identifier in visited:
            return
        active.add(identifier)
        for target in adjacency[identifier]:
            visit(target)
        active.remove(identifier)
        visited.add(identifier)
    for identifier in sorted(index):
        visit(identifier)
    for identifier in sorted(cyclic):
        issue(definitions[identifier], "STRATEGY_DEPENDENCY_CYCLE", "circular strategy relationships require review")
    # Invalid graphs do not offer apparently usable definitions to consumers.
    projection = {"authority": "projection_only", "adoption_status": "candidate", "valid": not issues,
                  "definitions": {key: index[key] for key in sorted(index)} if not issues else {},
                  "relationships": [{"from": a, "type": b, "to": c} for a, b, c in sorted(edges)] if not issues else []}
    return projection, sorted(set(issues))
