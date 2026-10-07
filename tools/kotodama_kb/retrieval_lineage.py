"""Map public synthetic evaluation inputs to the existing lineage projection."""
from .lineage_contract import admit_snapshot, source_set_digest
from .lineage_impact import project_lineage
from .foundation import KnowledgeBaseError


def fixture_lineage(corpus, case):
    sources = {row['binding']['revision_ref']: row['binding'] for row in corpus['sources']}
    documents = {row['revision_ref']: row for row in corpus['documents']}
    included = {ref: row for ref, row in documents.items() if row['source_revision_refs'] and all(s in sources for s in row['source_revision_refs'])}
    concepts, relations = [], []
    for ref, document in included.items():
        concepts.append({'concept_id': document['id'], 'revision_ref': ref, 'parent_revision_ref': None,
            'content_sha256': document['content_sha256'],
            'source_set_sha256': source_set_digest(sources[s] for s in document['source_revision_refs']),
            'source_revision_refs': document['source_revision_refs'], 'generator_invocation_ref': 'ref/invocation/synthetic-evaluation',
            'policy_revision_refs': [case['request']['policy_ref']], 'intent_revision_refs': [case['request']['intent_ref']],
            'status': document['status'] if document['status'] in {'superseded', 'revoked', 'conflicted'} else 'candidate'})
        for target, required in [(target, required) for field, required in (('required_dependencies', True), ('optional_dependencies', False)) for target in document[field]]:
            relations.append({'from_revision_ref': ref, 'predicate': 'requires_context', 'target_kind': 'concept',
                'target_id': documents[target]['id'] if target in documents else 'synthetic/unresolved',
                'target_revision_ref': target, 'required': required, 'validity': 'current',
                'resolution': 'resolved' if target in included else 'unresolved', 'evidence_ref': 'ref/evidence/synthetic-dependency'})
    snapshot = admit_snapshot({'kind': 'kotodama.knowledge-lineage', 'schema_revision': 'v1', 'authority': 'projection_only',
        'contains_content': False, 'sources': list(sources.values()), 'concepts': concepts, 'relations': relations, 'projections': []})
    return snapshot, project_lineage(snapshot)


def affected_revisions(corpus, case):
    if not case['changed_source_refs']:
        return []
    _, index = fixture_lineage(corpus, case)
    if not index['complete']:
        raise KnowledgeBaseError('EVALUATION_LINEAGE_INCOMPLETE')
    return sorted({ref for source in case['changed_source_refs']
                   for ref in index['indexes']['source_revision_to_concepts'].get(source, [])})
