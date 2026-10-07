"""Admit a frozen, public-synthetic corpus without consulting expected scores."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from .foundation import KnowledgeBaseError, _read_json, _bounded_tree
from .lineage_contract import admit_snapshot

ROOT = Path(__file__).resolve().parents[2]


def _case_preconditions(case, documents, sources):
    request, expected = case['request'], case['expected']
    requested = set(request['requested_revision_refs'])
    targets = [documents[ref] for ref in requested if ref in documents]
    required = set(requested)
    scoped = [doc for doc in documents.values() if doc['project_ref'] == request['project_ref'] and doc['task_ref'] == request['task_ref']]
    required.update(doc['revision_ref'] for doc in scoped if request['recipient_role'] in doc['mandatory_for_roles']
                    or set(doc['constraint_refs']) & set(request['mandatory_constraint_refs']))
    for _ in range(len(documents) + 1):
        following = {target for ref in required if ref in documents for target in documents[ref]['required_dependencies']} - required
        if not following: break
        required.update(following)
    before, after = set(case['source_revocations_before']), set(case['source_revocations_after'])
    keys = {source['invalidation_key'] for source in sources.values()}
    if (before | after) - keys or set(case['changed_source_refs']) - sources.keys():
        raise KnowledgeBaseError('CORPUS_CHANGE_REFERENCE_UNKNOWN')
    revoked = {ref for ref, source in sources.items() if source['invalidation_key'] in before | after}
    if not revoked <= set(expected['forbidden_source_refs']):
        raise KnowledgeBaseError('CORPUS_REVOKED_SOURCE_GOLDEN_REQUIRED')
    affected_required = {source for ref in required if ref in documents for source in documents[ref]['source_revision_refs']} & revoked
    forbidden = [documents[ref] for ref in expected['forbidden_revision_refs'] if ref in documents]
    expected_docs = [documents[ref] for ref in expected['required_revision_refs'] if ref in documents]
    missing_required = any(not doc['source_revision_refs'] or set(doc['source_revision_refs']) - sources.keys()
        or set(doc['required_dependencies']) - documents.keys() for doc in targets)
    missing_optional = any(set(doc['optional_dependencies']) - documents.keys() for doc in targets)
    unknown = expected['verdict'] == 'needs_resolution'
    checks = {
        'exact_lookup': bool(targets) and any(request['query'] in [doc['id'], doc['revision_ref'], *doc['aliases']] for doc in targets),
        'japanese_variation': bool(re.search(r'[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]', request['query'])) and bool(expected_docs),
        'false_neighbor': any((doc['project_ref'] != request['project_ref'] or doc['task_ref'] != request['task_ref'])
            and request['query'] in ' '.join([doc['title'], doc['text'], *doc['aliases']]) for doc in forbidden),
        'mandatory_ancestor': bool(required - requested) and any(doc['constraint_refs'] for doc in scoped if doc['revision_ref'] in required - requested),
        'stale_source': unknown and any(ref in sources and sources[ref]['source_id'] in case['current_source_revisions']
            and case['current_source_revisions'][sources[ref]['source_id']] != ref for doc in targets for ref in doc['source_revision_refs']),
        'superseded_intent': any(doc['kind'] == 'intent' and doc['status'] == 'current' for doc in targets)
            and any(doc['kind'] == 'intent' and doc['status'] == 'superseded' for doc in forbidden),
        'conflicting_correction': unknown and any(doc['status'] == 'conflicted' for doc in targets),
        'revoked_before': bool(before) and not after and bool(affected_required) and unknown,
        'revoked_after': bool(after) and not before and bool(affected_required) and unknown,
        'budget_exceeded': unknown and (len(required) > case['budget']['max_concepts'] or
            sum(len(documents[ref]['text'].encode('utf-8')) for ref in required if ref in documents) > min(case['budget']['max_bytes'], case['budget']['max_tokens'])),
        'inert_instructions': any(doc['inert_instruction_fragments'] for doc in targets),
        'missing_source': bool(requested - documents.keys()) or missing_required and unknown or missing_optional,
        'fresh_session': bool(case['changed_source_refs']) and bool(case.get('previous_session_ref')) and case['previous_session_ref'] != request['session_ref'],
        'proxy_improvement': case['declared_kpi_change'] == 'improved' and case['declared_outcome_change'] != 'improved'
            and expected['verdict'] == 'review_required' and expected['next_action'] == 'review_outcome',
        'rollback': unknown and any(doc['status'] == 'revoked' for doc in targets),
        'no_op': case['no_op_update'] and not case['changed_source_refs'] and not before and not after
            and not expected['affected_revision_refs'] and expected['verdict'] == 'no_change' and expected['next_action'] == 'no_regeneration',
    }
    if not checks[case['category']]:
        raise KnowledgeBaseError('CORPUS_CASE_PRECONDITION')


def corpus_digest(value):
    body = {key: item for key, item in value.items() if key != 'corpus_sha256'}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def admit_corpus(value):
    try:
        _bounded_tree(value)
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(raw.encode('utf-8')) > 1024 * 1024:
            raise ValueError()
        value = json.loads(raw)
    except (TypeError, ValueError, RecursionError) as exc:
        raise KnowledgeBaseError('CORPUS_INPUT_INVALID') from exc
    schema = _read_json(ROOT / 'schemas/frozen-context-corpus.schema.json')
    if not Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(value):
        raise KnowledgeBaseError('CORPUS_SCHEMA')
    if corpus_digest(value) != value['corpus_sha256']:
        raise KnowledgeBaseError('CORPUS_REVISION_CHANGED')
    for rows, key in ((value['documents'], 'revision_ref'), (value['cases'], 'case_id'), (value['cases'], 'revision_ref')):
        if len({row[key] for row in rows}) != len(rows):
            raise KnowledgeBaseError('CORPUS_DUPLICATE_ID')
    bindings = [item['binding'] for item in value['sources']]
    if len({item['revision_ref'] for item in bindings}) != len(bindings):
        raise KnowledgeBaseError('CORPUS_DUPLICATE_SOURCE')
    admit_snapshot({'kind': 'kotodama.knowledge-lineage', 'schema_revision': 'v1', 'authority': 'projection_only',
                    'contains_content': False, 'sources': bindings, 'concepts': [], 'relations': [], 'projections': []})
    for item in value['sources']:
        binding = item['binding']
        content = hashlib.sha256(item['text'].encode('utf-8')).hexdigest()
        if content != binding['content_sha256'] or binding['revision_kind'] == 'content_digest' and binding['revision_value'] != content:
            raise KnowledgeBaseError('CORPUS_SOURCE_BYTES')
    for item in value['documents']:
        if hashlib.sha256(item['text'].encode('utf-8')).hexdigest() != item['content_sha256']:
            raise KnowledgeBaseError('CORPUS_DOCUMENT_BYTES')
        if any(fragment not in item['text'] for fragment in item['inert_instruction_fragments']):
            raise KnowledgeBaseError('CORPUS_INSTRUCTION_FRAGMENT_MISSING')
    documents = {item['revision_ref']: item for item in value['documents']}
    sources = {item['revision_ref']: item for item in bindings}
    for case in value['cases']:
        for logical, revision in case['current_revisions'].items():
            if revision not in documents or documents[revision]['id'] != logical:
                raise KnowledgeBaseError('CORPUS_CURRENT_CONCEPT_MISMATCH')
        for logical, revision in case['current_source_revisions'].items():
            if revision not in sources or sources[revision]['source_id'] != logical:
                raise KnowledgeBaseError('CORPUS_CURRENT_SOURCE_MISMATCH')
        _case_preconditions(case, documents, sources)
    required = set(schema['$defs']['case']['properties']['category']['enum'])
    if {case['category'] for case in value['cases']} != required:
        raise KnowledgeBaseError('CORPUS_CATEGORY_COVERAGE')
    return value


def load_corpus(path):
    return admit_corpus(_read_json(Path(path)))
