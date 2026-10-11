"""Finite, source-declared work inside one existing Task; no execution authority.

Hierarchy nodes have already passed the producer's current-file/span checks.
An all_of edge is decomposition, never a runnable work dependency or a new owner.
"""
from __future__ import annotations

import hashlib

from runtime.task_swarm.task_contract import require, shape
from runtime.task_swarm.task_planning import _Sources


def _identity(span):
    return tuple(span[key] for key in ("source_key", "source_revision", "start", "end"))


def _unique(spans, sources):
    result, seen = [], set()
    for span in spans:
        sources.span(span)
        key = _identity(span)
        if key not in seen:
            result.append(span)
            seen.add(key)
    return result


def resolve_frontier(nodes, root_id):
    """Check the whole rooted DAG before deduplicating its atomic leaf work."""
    require(isinstance(root_id, str) and root_id in nodes
            and nodes[root_id]["kind"] == "requirement", "TASK_FRONTIER_ROOT_INVALID")
    active, visited, children, postorder = set(), set(), {}, []

    def visit(identifier):
        require(identifier not in active, "TASK_FRONTIER_CYCLE")
        if identifier in visited:
            return
        node = nodes[identifier]
        value = node["frontier"]
        shape(value, {"kind", "children", "requires"}, "TASK_FRONTIER_INVALID")
        require(value["kind"] in ("atomic", "all_of"), "TASK_FRONTIER_INVALID")
        require(isinstance(value["requires"], list) and not value["requires"],
                "TASK_FRONTIER_DEPENDENCY_UNSUPPORTED")
        targets = value["children"]
        require(isinstance(targets, list) and len(targets) <= 8
                and all(isinstance(key, str) and key in nodes
                        and nodes[key]["kind"] == "requirement" for key in targets),
                "TASK_FRONTIER_CHILD_INVALID")
        require(len(set(targets)) == len(targets), "TASK_FRONTIER_CHILD_DUPLICATE")
        require(bool(targets) == (value["kind"] == "all_of"), "TASK_FRONTIER_INVALID")
        children[identifier] = sorted(targets)
        active.add(identifier)
        for target in children[identifier]:
            visit(target)
        active.remove(identifier)
        visited.add(identifier)
        postorder.append(identifier)

    visit(root_id)
    # Every parent precedes its children in this order. A shared node's longest
    # path still includes parents visited after its first DFS discovery.
    depths = {root_id: 0}
    for identifier in reversed(postorder):
        require(depths[identifier] <= 2, "TASK_FRONTIER_DEPTH_LIMIT")
        for target in children[identifier]:
            depths[target] = max(depths.get(target, 0), depths[identifier] + 1)
    leaves = {}
    for identifier in postorder:
        leaves[identifier] = (set().union(*(leaves[key] for key in children[identifier]))
                              if children[identifier] else {identifier})
    require(1 <= len(leaves[root_id]) <= 3, "TASK_FRONTIER_WORK_LIMIT")
    required = set(visited)
    for identifier in visited:
        ancestors = set()
        parent = nodes[identifier]["parent"]
        while parent is not None:
            require(parent in nodes and parent not in ancestors, "TASK_CONTEXT_PARENT_CYCLE")
            ancestors.add(parent)
            required.add(parent)
            parent = nodes[parent]["parent"]
    require(required == set(nodes), "TASK_CONTEXT_UNUSED_HIERARCHY")
    return {"root": root_id, "requirements": [root_id, *sorted(visited - {root_id})],
            "leaves": sorted(leaves[root_id]), "ancestors": sorted(required - visited),
            "descendants": {key: sorted(leaves[key]) for key in sorted(leaves)},
            "edges": [[key, child] for key in sorted(children) for child in children[key]],
            "depth": max(depths.values())}


def frontier_work(seed, nodes, root_id, constraints, catalog_spans):
    """Derive work, global conditions and criterion origins without mutating input."""
    graph, sources = resolve_frontier(nodes, root_id), _Sources(seed)
    require(isinstance(constraints, list), "OBJECTIVE_SPANS_INVALID")
    global_constraints = list(constraints)
    acceptance, origins, indices = [], [], {}
    for identifier in [*graph["ancestors"], *graph["requirements"]]:
        global_constraints.extend(nodes[identifier]["constraints"])
    for identifier in graph["requirements"]:
        for span in nodes[identifier]["acceptance"]:
            key = _identity(span)
            if key not in indices:
                indices[key] = len(acceptance)
                acceptance.append(span)
                origins.append(set())
            origins[indices[key]].add(identifier)
    assigned = {}
    for index, origin in enumerate(origins, 1):
        assigned[f"A{index}"] = sorted(set().union(
            *(set(graph["descendants"][key]) for key in origin)))
    jobs, job_ids = [], set()
    for leaf in graph["leaves"]:
        node = nodes[leaf]
        identifier = "leaf-" + hashlib.sha256(leaf.encode("utf-8")).hexdigest()[:32]
        require(identifier not in job_ids, "TASK_FRONTIER_JOB_COLLISION")
        job_ids.add(identifier)
        context = list(catalog_spans)
        for parent in graph["requirements"]:
            if leaf in graph["descendants"][parent] and (parent != leaf or parent == root_id):
                source = nodes[parent]["source"]
                context.append({"source_key": source["key"], "source_revision": source["revision"],
                                "start": 0, "end": len(source["text"])})
        jobs.append({"job_id": identifier, "purpose": sources.span(node["need"]),
                     "selected_spans": _unique([*context, node["need"], *node["acceptance"],
                                                *node["constraints"]], sources)})
    diagnostic = {"version": 1, "root_requirement_id": root_id, "edges": graph["edges"],
                  "max_depth": graph["depth"],
                  "leaf_jobs": [{"requirement_id": leaf, "job_id": job["job_id"]}
                                for leaf, job in zip(graph["leaves"], jobs)],
                  "criteria": [{"criterion_id": f"A{index+1}", "source": span,
                                "origin_requirement_ids": sorted(origins[index]),
                                "leaf_requirement_ids": assigned[f"A{index+1}"]}
                               for index, span in enumerate(acceptance)],
                  "guarantee": "source_declared_distribution_not_semantic_completion"}
    return {"constraints": _unique(global_constraints, sources), "acceptance": acceptance,
            "jobs": jobs, "assignments": assigned, "leaves": graph["leaves"],
            "diagnostic": diagnostic}
