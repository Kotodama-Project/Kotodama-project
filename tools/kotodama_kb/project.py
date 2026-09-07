from __future__ import annotations

from .foundation import *  # noqa: F401,F403
from .reserved import *  # noqa: F401,F403
from .load import *  # noqa: F401,F403

def _catalog(bundle: Bundle) -> dict[str, Any]:
    concepts = []
    for concept in bundle.concepts:
        metadata = concept.metadata
        extension = concept.extension
        concepts.append(
            {
                "id": concept.concept_id,
                "path": concept.document.path.relative_to(bundle.root).as_posix(),
                "type": metadata.get("type"),
                "title": metadata.get("title"),
                "description": metadata.get("description"),
                "tags": sorted(metadata.get("tags", [])),
                "status": metadata.get("status"),
                "stale_after": concept.stale_after,
                "trust_tier": concept.trust_tier,
                "knowledge_state": extension.get("knowledge_state"),
                "classification": extension.get("classification"),
                "authority": extension.get("authority"),
                "owner_role": extension.get("owner_role"),
                "reviewer_role": extension.get("reviewer_role"),
                "context_priority": extension.get("context_priority"),
                "goal_refs": sorted(extension.get("goal_refs", [])),
                "kgi_refs": sorted(extension.get("kgi_refs", [])),
                "initiative_refs": sorted(extension.get("initiative_refs", [])),
                "agent_use": extension.get("agent_use", {}),
                "source_resources": list(concept.source_resources),
                "concept_links": list(concept.resolved_concept_links),
                "content_sha256": concept.content_sha256,
            }
        )
    return {
        "kind": "kotodama.okf-catalog",
        "schema_revision": "v1",
        "okf_version": bundle.profile["okf_version"],
        "profile_version": bundle.profile["profile_version"],
        "bundle_id": bundle.profile["bundle_id"],
        "source_digest": bundle.source_digest,
        "authority": "projection_only",
        "concepts": concepts,
    }


def _graph(bundle: Bundle) -> dict[str, Any]:
    nodes: dict[tuple[str, str], dict[str, Any]] = {}
    edges: set[tuple[str, str, str, str, str]] = set()

    def add_node(node_id: str, node_kind: str, **details: Any) -> None:
        key = (node_kind, node_id)
        existing = nodes.get(key, {"id": node_id, "kind": node_kind})
        existing.update({key_: value for key_, value in details.items() if value is not None})
        nodes[key] = existing

    def add_edge(source: str, source_kind: str, target: str, target_kind: str, relation: str) -> None:
        edges.add((source_kind, source, relation, target_kind, target))

    for concept in bundle.concepts:
        add_node(
            concept.concept_id,
            "concept",
            path=concept.document.path.relative_to(bundle.root).as_posix(),
            type=concept.metadata.get("type"),
            title=concept.metadata.get("title"),
        )
        for linked_id in concept.resolved_concept_links:
            add_node(linked_id, "concept")
            add_edge(concept.concept_id, "concept", linked_id, "concept", "links_to")
        for resource in concept.source_resources:
            add_node(resource, "source")
            add_edge(concept.concept_id, "concept", resource, "source", "derived_from")
        for goal_ref in concept.extension.get("goal_refs", []):
            add_node(goal_ref, "goal")
            add_edge(concept.concept_id, "concept", goal_ref, "goal", "advances_goal")
        for kgi_ref in concept.extension.get("kgi_refs", []):
            add_node(kgi_ref, "kgi")
            add_edge(concept.concept_id, "concept", kgi_ref, "kgi", "supports_kgi")
        for initiative_ref in concept.extension.get("initiative_refs", []):
            add_node(initiative_ref, "initiative")
            add_edge(concept.concept_id, "concept", initiative_ref, "initiative", "implements_initiative")

    node_rows = sorted(nodes.values(), key=lambda row: (row["kind"], row["id"]))
    edge_rows = [
        {
            "from": source,
            "from_kind": source_kind,
            "relation": relation,
            "to": target,
            "to_kind": target_kind,
        }
        for source_kind, source, relation, target_kind, target in sorted(edges)
    ]
    return {
        "kind": "kotodama.okf-graph",
        "schema_revision": "v1",
        "bundle_id": bundle.profile["bundle_id"],
        "source_digest": bundle.source_digest,
        "authority": "projection_only",
        "nodes": node_rows,
        "edges": edge_rows,
    }


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=False) + "\n").encode("utf-8")


def generated_outputs(bundle: Bundle) -> dict[Path, bytes]:
    outputs = bundle.profile["generated_outputs"]
    return {
        bundle.root / outputs["catalog"]: _json_bytes(_catalog(bundle)),
        bundle.root / outputs["graph"]: _json_bytes(_graph(bundle)),
    }


def build(bundle: Bundle, *, check: bool) -> list[str]:
    changed: list[str] = []
    for path, expected in generated_outputs(bundle).items():
        current = path.read_bytes() if path.is_file() else None
        if current != expected:
            changed.append(path.relative_to(bundle.root).as_posix())
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(expected)
    return changed



__all__ = [name for name in globals() if not name.startswith("__")]
