"""Rebuildable reverse indexes and bounded impact; never a current-pointer owner."""
from __future__ import annotations

from collections import defaultdict

from .foundation import KnowledgeBaseError
from .lineage_contract import admit_snapshot, digest, unresolved_parent_refs

STATE_RELATIONS = {'supersedes', 'conflicts_with', 'invalidates'}
DEFAULT_BUDGET = {'max_depth': 32, 'max_nodes': 768, 'max_edges': 4096}


def _budget(overrides):
    if overrides is not None and not isinstance(overrides, dict):
        raise KnowledgeBaseError('LINEAGE_IMPACT_BUDGET_INVALID')
    budget = {**DEFAULT_BUDGET, **(overrides or {})}
    if set(budget) != set(DEFAULT_BUDGET) or any(type(value) is not int or not 1 <= value <= DEFAULT_BUDGET[key] for key, value in budget.items()):
        raise KnowledgeBaseError('LINEAGE_IMPACT_BUDGET_INVALID')
    return budget


def _graph(snapshot, budget):
    rows, kinds = {}, {}
    for collection, kind, key in (('sources', 'source', 'revision_ref'), ('concepts', 'concept', 'revision_ref'),
                                   ('projections', 'projection', 'projection_ref')):
        for row in snapshot[collection]:
            rows[row[key]], kinds[row[key]] = row, kind
    if len(rows) > budget['max_nodes']:
        raise KnowledgeBaseError('LINEAGE_IMPACT_NODE_BUDGET')
    mandatory, optional, unresolved, blocked, state_edges = set(), set(), [], set(), []

    def edge(origin, target, required):
        (mandatory if required else optional).add((origin, target))
        if len(mandatory) + len(optional) > budget['max_edges']:
            raise KnowledgeBaseError('LINEAGE_IMPACT_EDGE_BUDGET')

    for source in snapshot['sources']:
        if source['access_state'] != 'allowed':
            blocked.add(source['revision_ref'])
    for concept in snapshot['concepts']:
        if concept['status'] != 'candidate' or concept.get('parent_resolution') == 'external_unresolved':
            blocked.add(concept['revision_ref'])
        for target in concept['source_revision_refs']:
            edge(concept['revision_ref'], target, True)
    for projection in snapshot['projections']:
        for target in projection['concept_revision_refs'] + projection['source_revision_refs']:
            edge(projection['projection_ref'], target, True)
    for relation in snapshot['relations']:
        origin, target = relation['from_revision_ref'], relation['target_revision_ref']
        if (relation['resolution'] != 'resolved' or relation['validity'] != 'current'
                or relation['target_kind'] not in {'source', 'concept'} or target not in rows):
            unresolved.append(relation)
            if relation['required']:
                blocked.add(origin)
            continue
        if relation['predicate'] in STATE_RELATIONS:
            state_edges.append(relation)
            blocked.add(target)
            if relation['predicate'] == 'conflicts_with':
                blocked.add(origin)
        else:
            edge(origin, target, relation['required'])
    if len(mandatory) + len(optional) + len(unresolved) + len(state_edges) > budget['max_edges']:
        raise KnowledgeBaseError('LINEAGE_IMPACT_EDGE_BUDGET')
    return rows, kinds, mandatory, optional, unresolved, blocked, state_edges


def _reverse(edges):
    reverse = defaultdict(set)
    for dependent, dependency in edges:
        reverse[dependency].add(dependent)
    return reverse


def _closure(seeds, reverse, max_depth):
    reached, frontier = set(seeds), set(seeds)
    for _ in range(max_depth):
        following = {target for node in frontier for target in reverse[node]} - reached
        if not following:
            return reached, True
        reached.update(following)
        frontier = following
    return reached, not any(reverse[node] - reached for node in frontier)


def _cycles(nodes, edges):
    dependencies = defaultdict(set)
    for origin, target in edges:
        dependencies[origin].add(target)
    complete, active, path, found = set(), {}, [], set()

    def visit(node):
        if node in active:
            found.update(path[active[node]:])
            return
        if node in complete:
            return
        active[node] = len(path); path.append(node)
        for target in sorted(dependencies[node]):
            visit(target)
        path.pop(); del active[node]; complete.add(node)

    for node in sorted(nodes):
        visit(node)
    return found


def project_lineage(value, *, budget=None):
    """Compute indexes without trusting access declarations as authorization."""
    snapshot, budget = admit_snapshot(value), _budget(budget)
    rows, kinds, mandatory, optional, unresolved, blocked, state_edges = _graph(snapshot, budget)
    reverse = _reverse(mandatory)
    cycles = _cycles(rows, mandatory)
    quarantine, complete = _closure(blocked | cycles, reverse, budget['max_depth'])
    indexes = {name: {} for name in ('source_revision_to_concepts', 'concept_revision_to_projections',
                                    'source_revision_to_projections', 'invalidation_key_to_nodes', 'strategy_to_nodes')}
    for ref, kind in kinds.items():
        if kind not in {'source', 'concept'}:
            continue
        affected, traversed = _closure({ref}, reverse, budget['max_depth'])
        complete &= traversed
        if kind == 'source':
            indexes['source_revision_to_concepts'][ref] = sorted(n for n in affected if kinds[n] == 'concept')
        indexes[kind + '_revision_to_projections'][ref] = sorted(n for n in affected if kinds[n] == 'projection')
    for source in snapshot['sources']:
        reached, traversed = _closure({source['revision_ref']}, reverse, budget['max_depth'])
        key = source['invalidation_key']; complete &= traversed
        indexes['invalidation_key_to_nodes'].setdefault(key, set()).update(reached)
    for relation in snapshot['relations']:
        if relation['target_kind'] in {'goal', 'kgi', 'initiative'}:
            indexes['strategy_to_nodes'].setdefault(relation['target_id'], set()).add(relation['from_revision_ref'])
    for projection in snapshot['projections']:
        for field in ('goal_refs', 'kgi_refs', 'initiative_refs'):
            for identifier in projection[field]:
                indexes['strategy_to_nodes'].setdefault(identifier, set()).add(projection['projection_ref'])
    indexes = {name: {key: sorted(value) for key, value in sorted(index.items())} for name, index in indexes.items()}
    return {'kind': 'kotodama.lineage-index', 'authority': 'projection_only', 'snapshot_sha256': digest(snapshot),
            'complete': complete, 'budget': budget, 'node_count': len(rows),
            'edge_count': len(mandatory) + len(optional) + len(unresolved) + len(state_edges),
            'indexes': indexes, 'mandatory_edges': sorted(mandatory), 'optional_edges': sorted(optional),
            'state_relations': state_edges, 'unresolved_relations': unresolved, 'cycle_revision_refs': sorted(cycles),
            'unresolved_parent_revision_refs': unresolved_parent_refs(snapshot),
            'optional_cycle_revision_refs': sorted(_cycles(rows, mandatory | optional) - cycles),
            'quarantine_revision_refs': sorted(quarantine if complete else rows),
            'source_access_authenticated': False, 'serving_authorized': False}


def compare_lineage(previous, current, *, invalidation_keys=(), budget=None):
    """Union old/new dependencies so deletion cannot erase its impact trail."""
    before, after, budget = admit_snapshot(previous), admit_snapshot(current), _budget(budget)
    old = _graph(before, budget); new = _graph(after, budget)
    nodes = set(old[0]) | set(new[0]); mandatory = old[2] | new[2]; optional = old[3] | new[3]
    extra = {digest(edge) for graph in (old, new) for edge in graph[4] + graph[6]}
    if len(nodes) > budget['max_nodes'] or len(mandatory) + len(optional) + len(extra) > budget['max_edges']:
        raise KnowledgeBaseError('LINEAGE_IMPACT_UNION_BUDGET')

    def signatures(snapshot, rows):
        edges = defaultdict(list)
        for relation in snapshot['relations']:
            edges[relation['from_revision_ref']].append(relation)
        return {ref: digest({'record': row, 'relations': edges[ref]}) for ref, row in rows.items()}

    old_hashes, new_hashes = signatures(before, old[0]), signatures(after, new[0])
    changed = {ref for ref in nodes if old_hashes.get(ref) != new_hashes.get(ref)}
    if not isinstance(invalidation_keys, (list, tuple, set)) or len(invalidation_keys) > 256 or any(not isinstance(key, str) for key in invalidation_keys):
        raise KnowledgeBaseError('LINEAGE_INVALIDATION_KEY_INVALID')
    keys = set(invalidation_keys)
    known_keys = {source['invalidation_key'] for source in before['sources'] + after['sources']}
    if keys - known_keys:
        raise KnowledgeBaseError('LINEAGE_INVALIDATION_KEY_UNKNOWN')
    revoked = {source['revision_ref'] for source in before['sources'] + after['sources'] if source['invalidation_key'] in keys}
    affected, complete = _closure(changed | revoked, _reverse(mandatory), budget['max_depth'])
    # Optional links are reported; they do not silently become mandatory.
    optional_affected = {origin for origin, target in optional if target in affected} - affected
    quarantined, quarantine_complete = _closure(new[5] | revoked | _cycles(nodes, mandatory), _reverse(mandatory), budget['max_depth'])
    complete &= quarantine_complete
    result = {'kind': 'kotodama.lineage-impact', 'authority': 'projection_only',
              'before_sha256': digest(before), 'after_sha256': digest(after),
              'status': 'NO_CHANGE' if not changed and not revoked else 'CHANGED', 'complete': complete, 'budget': budget,
              'changed_revision_refs': sorted(changed), 'affected_revision_refs': sorted(affected),
              'optional_revision_refs': sorted(optional_affected), 'invalidation_keys': sorted(keys),
              'quarantine_revision_refs': sorted((affected | quarantined) if complete else nodes),
              'source_access_authenticated': False, 'serving_authorized': False}
    if not complete:
        result['status'] = 'BUDGET_EXCEEDED'
    return {**result, 'receipt_sha256': digest(result)}
