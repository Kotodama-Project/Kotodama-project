"""Admit a frozen, public-synthetic corpus without consulting expected scores."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from .foundation import KnowledgeBaseError, _read_json, _bounded_tree
from .lineage_contract import admit_snapshot

ROOT = Path(__file__).resolve().parents[2]


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
    documents = {item['revision_ref']: item for item in value['documents']}
    sources = {item['revision_ref']: item for item in bindings}
    for case in value['cases']:
        for logical, revision in case['current_revisions'].items():
            if revision in documents and documents[revision]['id'] != logical:
                raise KnowledgeBaseError('CORPUS_CURRENT_CONCEPT_MISMATCH')
        for logical, revision in case['current_source_revisions'].items():
            if revision in sources and sources[revision]['source_id'] != logical:
                raise KnowledgeBaseError('CORPUS_CURRENT_SOURCE_MISMATCH')
    required = set(schema['$defs']['case']['properties']['category']['enum'])
    if {case['category'] for case in value['cases']} != required:
        raise KnowledgeBaseError('CORPUS_CATEGORY_COVERAGE')
    return value


def load_corpus(path):
    return admit_corpus(_read_json(Path(path)))
