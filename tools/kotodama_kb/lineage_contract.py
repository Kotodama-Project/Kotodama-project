"""Closed, revision-bound metadata admission. This module grants no access."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from collections.abc import Mapping

from jsonschema import Draft202012Validator, FormatChecker

from .foundation import KnowledgeBaseError, _bounded_tree, _read_json

SCHEMA_PATH = Path(__file__).resolve().parents[2] / 'schemas/knowledge-lineage.schema.json'
MAX_SNAPSHOT_BYTES = 1024 * 1024


def canonical(value):
    """Every array in this contract is a set, including revision references."""
    if isinstance(value, Mapping):
        return {key: canonical(child) for key, child in sorted(value.items())}
    if isinstance(value, list):
        return sorted((canonical(child) for child in value), key=lambda x: json.dumps(x, sort_keys=True))
    return value


def digest(value) -> str:
    data = json.dumps(canonical(value), ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def source_set_digest(sources) -> str:
    """Bind both exact bytes and observation/access/custodian metadata."""
    return digest(list(sources))


def _index(rows, key):
    result = {}
    for row in rows:
        if row[key] in result:
            raise KnowledgeBaseError('LINEAGE_DUPLICATE_ID')
        result[row[key]] = row
    return result


def admit_snapshot(value: dict) -> dict:
    """Clone and validate a bounded snapshot; never echo rejected input."""
    try:
        _bounded_tree(value)
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(raw.encode('utf-8')) > MAX_SNAPSHOT_BYTES:
            raise KnowledgeBaseError('LINEAGE_BYTE_BUDGET')
        snapshot = json.loads(raw)
    except (TypeError, ValueError, RecursionError) as exc:
        raise KnowledgeBaseError('LINEAGE_INPUT_INVALID') from exc
    schema = _read_json(SCHEMA_PATH)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    if next(validator.iter_errors(snapshot), None) is not None:
        raise KnowledgeBaseError('LINEAGE_SCHEMA')
    sources = _index(snapshot['sources'], 'revision_ref')
    concepts = _index(snapshot['concepts'], 'revision_ref')
    projections = _index(snapshot['projections'], 'projection_ref')
    if (set(sources) & set(concepts) or set(sources) & set(projections)
            or set(concepts) & set(projections)):
        raise KnowledgeBaseError('LINEAGE_ID_COLLISION')

    versions = {}
    for source in sources.values():
        identity = (source['source_id'], source['revision_kind'], source['revision_value'])
        previous = versions.setdefault(identity, source['content_sha256'])
        if previous != source['content_sha256']:
            raise KnowledgeBaseError('LINEAGE_SOURCE_CONFLICT')
        kind, revision = source['revision_kind'], source['revision_value']
        if kind == 'content_digest' and revision != source['content_sha256']:
            raise KnowledgeBaseError('LINEAGE_REVISION_DIGEST')
        if kind == 'git_commit' and (len(revision) not in (40, 64) or any(c not in '0123456789abcdef' for c in revision)):
            raise KnowledgeBaseError('LINEAGE_GIT_REVISION')
        if kind == 'event_sequence' and (not revision.isdecimal() or revision != str(int(revision))):
            raise KnowledgeBaseError('LINEAGE_EVENT_SEQUENCE')
        span = source.get('span', {})
        if span.get('kind') == 'lines' and span['end'] < span['start']:
            raise KnowledgeBaseError('LINEAGE_SPAN_ORDER')

    for concept in concepts.values():
        if any(ref not in sources for ref in concept['source_revision_refs']):
            raise KnowledgeBaseError('LINEAGE_SOURCE_MISSING')
        if 'source_aliases' in concept and set(concept['source_aliases'].values()) != set(concept['source_revision_refs']):
            raise KnowledgeBaseError('LINEAGE_SOURCE_ALIAS_BINDING')
        expected = source_set_digest(sources[ref] for ref in concept['source_revision_refs'])
        if concept['source_set_sha256'] != expected:
            raise KnowledgeBaseError('LINEAGE_SOURCE_SET_DIGEST')
        parent = concept['parent_revision_ref']
        if parent == concept['revision_ref'] or (parent in concepts and concepts[parent]['concept_id'] != concept['concept_id']):
            raise KnowledgeBaseError('LINEAGE_PARENT_MISMATCH')
    for concept in concepts.values():
        visited, current = set(), concept
        while current:
            ref = current['revision_ref']
            if ref in visited:
                raise KnowledgeBaseError('LINEAGE_PARENT_CYCLE')
            visited.add(ref)
            current = concepts.get(current['parent_revision_ref'])

    for relation in snapshot['relations']:
        if relation['from_revision_ref'] not in concepts:
            raise KnowledgeBaseError('LINEAGE_RELATION_ORIGIN')
        target_kind, target_id = relation['target_kind'], relation['target_id']
        id_type = 'concept_id' if target_kind == 'concept' else 'semantic_id' if target_kind in {'goal', 'kgi', 'initiative'} else 'ref'
        if not Draft202012Validator({'$ref': '#/$defs/' + id_type, '$defs': schema['$defs']}).is_valid(target_id):
            raise KnowledgeBaseError('LINEAGE_RELATION_TARGET_TYPE')
        if target_kind in {'source', 'concept'}:
            target = (sources if target_kind == 'source' else concepts).get(relation['target_revision_ref'])
            id_field = 'source_id' if target_kind == 'source' else 'concept_id'
            if target and target[id_field] != target_id:
                raise KnowledgeBaseError('LINEAGE_RELATION_TARGET_MISMATCH')
            # Missing targets can be represented explicitly, never as resolved.
            if not target and relation['resolution'] == 'resolved':
                raise KnowledgeBaseError('LINEAGE_FALSE_RESOLUTION')
    for projection in projections.values():
        if (any(ref not in concepts for ref in projection['concept_revision_refs'])
                or any(ref not in sources for ref in projection['source_revision_refs'])):
            raise KnowledgeBaseError('LINEAGE_PROJECTION_TARGET_MISSING')
    return canonical(snapshot)


def read_snapshot(path: Path) -> dict:
    return admit_snapshot(_read_json(path))


def validate_public_bytes(snapshot: dict, *, repository_root: Path) -> dict:
    """Check public local files only. Opaque input is always unresolved here.

    This is a readback, not locator authorization, a receipt authenticator, or a
    current-pointer store. The caller must separately bind the admitted files.
    """
    from .foundation import _capture_inputs
    snapshot = admit_snapshot(snapshot)
    root = repository_root.resolve()
    paths = [root / source['locator'] for source in snapshot['sources'] if source['locator_visibility'] == 'public']
    paths += [root / 'knowledge' / (concept['concept_id'] + '.md') for concept in snapshot['concepts']]
    bindings = dict(_capture_inputs(root, paths))
    mismatches, opaque = [], []
    for source in snapshot['sources']:
        if source['locator_visibility'] == 'opaque':
            opaque.append(source['revision_ref'])
        elif bindings[source['locator']] != source['content_sha256']:
            mismatches.append(source['revision_ref'])
    for concept in snapshot['concepts']:
        if bindings['knowledge/' + concept['concept_id'] + '.md'] != concept['content_sha256']:
            mismatches.append(concept['revision_ref'])
    return {'authority': 'projection_only', 'snapshot_sha256': digest(snapshot),
            'local_bytes_match': not mismatches, 'mismatched_revision_refs': sorted(mismatches),
            'opaque_unverified_revision_refs': sorted(opaque), 'input_bindings': sorted(bindings.items()),
            'access_authenticated': False, 'source_authenticated': False, 'current_pointer_verified': False}
