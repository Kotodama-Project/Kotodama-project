"""Bind the existing catalog/graph bytes to a complete public-local snapshot."""
from __future__ import annotations

import hashlib

from .foundation import KnowledgeBaseError, _assert_current, _resolve_source_resource
from .lineage_contract import admit_snapshot, digest, validate_public_bytes
from .project import generated_outputs


def bind_generated_projections(bundle, value):
    snapshot = admit_snapshot(value)
    concepts = {row['concept_id']: row for row in snapshot['concepts']}
    if len(concepts) != len(snapshot['concepts']) or set(concepts) != set(bundle.by_id):
        raise KnowledgeBaseError('LINEAGE_PROJECTION_COVERAGE_REQUIRED')
    sources = {row['revision_ref']: row for row in snapshot['sources']}
    readback = validate_public_bytes(snapshot, repository_root=bundle.root)
    if not readback['local_bytes_match'] or readback['opaque_unverified_revision_refs']:
        raise KnowledgeBaseError('LINEAGE_PROJECTION_SOURCE_UNVERIFIED')
    for logical, row in concepts.items():
        concept = bundle.by_id[logical]
        aliases = row.get('source_aliases', {})
        declared = {source['id']: source for source in concept.metadata['sources']}
        if set(aliases) != set(declared):
            raise KnowledgeBaseError('LINEAGE_PROJECTION_SOURCE_COVERAGE_REQUIRED')
        for alias, ref in aliases.items():
            source = sources[ref]
            path = _resolve_source_resource(source_path=concept.document.path, resource=declared[alias]['resource'],
                repository_root=bundle.root, bundle_root=bundle.bundle_root)
            if path != bundle.root / source['locator']:
                raise KnowledgeBaseError('LINEAGE_PROJECTION_SOURCE_BINDING_MISMATCH')
    records = []
    paths = {bundle.root / path: kind for kind, path in bundle.profile['generated_outputs'].items()}
    for path, content in generated_outputs(bundle).items():
        kind = paths[path]
        fingerprint = hashlib.sha256(content).hexdigest()
        safe = '-'.join(fingerprint[i:i + 8] for i in range(0, 64, 8))
        records.append({'projection_ref': f'ref/projection/{kind}/{safe}', 'kind': kind,
            'content_sha256': fingerprint, 'concept_revision_refs': sorted(row['revision_ref'] for row in concepts.values()),
            'source_revision_refs': sorted(sources),
            **{field: sorted({ref for concept in bundle.concepts for ref in concept.extension.get(field, [])})
               for field in ('goal_refs', 'kgi_refs', 'initiative_refs')}})
    existing = {row['projection_ref']: row for row in snapshot['projections']}
    for row in records:
        old = existing.get(row['projection_ref'])
        if old is not None and digest(old) != digest(row):
            raise KnowledgeBaseError('LINEAGE_PROJECTION_RECORD_CONFLICT')
        existing[row['projection_ref']] = row
    output = admit_snapshot({**snapshot, 'projections': list(existing.values())})
    _assert_current(bundle)
    return {'snapshot': output, 'snapshot_sha256': digest(output), 'authority': 'projection_only',
            'current_pointer_verified': False, 'source_access_authenticated': False}
