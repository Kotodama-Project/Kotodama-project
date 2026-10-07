"""Bind the existing v2 context to current revisions before a local consumer.

The caller supplies existing scope/access checks and the consumer. No provider
adapter, grant, Company truth, or independent identity proof is created here.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import inspect
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from knowledge_context import make_context, context_json

from .foundation import KnowledgeBaseError, _read_json, _read_bytes, _bounded_tree, _assert_current, _resolve_source_resource
from .load import load_bundle
from .retrieve import select_context
from .audit import context_as_dict
from .lineage_contract import SCHEMA_PATH, digest

REQUEST_REFS = ('request_ref', 'actor_ref', 'recipient_ref', 'purpose_ref', 'task_ref', 'session_ref',
                'intent_revision_ref', 'policy_revision_ref', 'grant_ref')


def _clone(value, maximum):
    try:
        _bounded_tree(value)
        pending, characters = [value], 0
        while pending:
            item = pending.pop()
            if isinstance(item, dict):
                pending.extend(item.keys()); pending.extend(item.values())
            elif isinstance(item, list): pending.extend(item)
            elif isinstance(item, str): characters += len(item)
            if characters > maximum: raise ValueError()
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(raw.encode('utf-8')) > maximum:
            raise ValueError()
        return json.loads(raw)
    except (ValueError, TypeError, RecursionError) as exc:
        raise KnowledgeBaseError('LINEAGE_CONTEXT_INPUT_INVALID') from exc


def _request(value):
    result = _clone(value, 32 * 1024)
    definitions = _read_json(SCHEMA_PATH)['$defs']
    properties = {key: {'$ref': '#/$defs/ref'} for key in REQUEST_REFS}
    properties.update(expires_at={'$ref': '#/$defs/timestamp'},
                      max_bytes={'type': 'integer', 'minimum': 1, 'maximum': 1024 * 1024},
                      max_concepts={'type': 'integer', 'minimum': 1, 'maximum': 32})
    properties['filters'] = {'type': 'object', 'additionalProperties': False,
        'required': ['goals', 'kgis', 'initiatives', 'tags'],
        'properties': {key: {'type': 'array', 'maxItems': 256, 'uniqueItems': True,
                            'items': {'type': 'string', 'minLength': 1, 'maxLength': 256}}
                       for key in ('goals', 'kgis', 'initiatives', 'tags')}}
    schema = {'type': 'object', 'additionalProperties': False, 'required': list(properties),
              'properties': properties, '$defs': definitions}
    if not Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(result):
        raise KnowledgeBaseError('LINEAGE_CONTEXT_REQUEST_INVALID')
    for field in ('max_bytes', 'max_concepts'): result[field] = int(result[field])
    return result


def _time(value):
    if isinstance(value, str):
        try: value = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError as exc: raise KnowledgeBaseError('LINEAGE_CONTEXT_CLOCK_INVALID') from exc
    if not isinstance(value, dt.datetime) or value.tzinfo is None:
        raise KnowledgeBaseError('LINEAGE_CONTEXT_CLOCK_INVALID')
    return value.astimezone(dt.timezone.utc)


def _artifacts():
    root = Path(__file__).resolve().parents[2]
    paths = [f'tools/kotodama_kb/{name}.py' for name in
             ('lineage_context', 'lineage_contract', 'revision_owner', 'audit', 'retrieve', 'load', 'foundation', 'reserved', 'strategy')]
    paths += ['tools/knowledge_context.py', 'schemas/knowledge-lineage.schema.json',
              'schemas/knowledge-context-bundle.schema.json', 'schemas/kotodama-okf-concept.schema.json',
              'schemas/kotodama-okf-profile.schema.json']
    return {path: hashlib.sha256(_read_bytes(root / path)).hexdigest() for path in paths}


def _public_span(source, path):
    span = source.get('span')
    if span is None:
        return
    raw = _read_bytes(path)
    if hashlib.sha256(raw).hexdigest() != source['content_sha256']:
        raise KnowledgeBaseError('LINEAGE_CONTEXT_SOURCE_CHANGED')
    try:
        if span['kind'] == 'lines':
            if span['end'] > len(raw.decode('utf-8').splitlines()):
                raise ValueError()
        elif span['kind'] == 'json_pointer':
            def pairs(items):
                value = {}
                for key, child in items:
                    if key in value: raise ValueError()
                    value[key] = child
                return value
            value = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            _bounded_tree(value)
            for part in span['pointer'].split('/')[1:]:
                part = part.replace('~1', '/').replace('~0', '~')
                if isinstance(value, list):
                    if not part.isdecimal() or str(int(part)) != part: raise ValueError()
                    value = value[int(part)]
                elif isinstance(value, dict): value = value[part]
                else: raise ValueError()
        else:
            raise KnowledgeBaseError('LINEAGE_CONTEXT_EVENT_SPAN_OWNER_REQUIRED')
    except (ValueError, KeyError, IndexError, UnicodeError, RecursionError) as exc:
        raise KnowledgeBaseError('LINEAGE_CONTEXT_SOURCE_SPAN_UNRESOLVED') from exc


class LineageContextGate:
    def __init__(self, owner, *, authorize_context, verify_opaque=None, verify_event_span=None, clock=None):
        if not callable(authorize_context) or any(callback is not None and not callable(callback) for callback in (verify_opaque, verify_event_span)):
            raise KnowledgeBaseError('LINEAGE_CONTEXT_GUARD_REQUIRED')
        self.owner, self.authorize_context, self.verify_opaque = owner, authorize_context, verify_opaque
        self.verify_event_span = verify_event_span
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))

    @staticmethod
    def _require_true(callback, argument, code):
        try:
            # The callback cannot mutate the admitted request or bound objects.
            approved = callback(json.loads(json.dumps(argument)))
        except Exception as exc:
            raise KnowledgeBaseError(code) from exc
        if approved is not True:
            if inspect.iscoroutine(approved): approved.close()
            raise KnowledgeBaseError(code)

    def _candidate(self, db, request, *, as_of, stage):
        now = _time(self.clock())
        if now >= _time(request['expires_at']):
            raise KnowledgeBaseError('LINEAGE_CONTEXT_REQUEST_EXPIRED')
        bundle = load_bundle(self.owner.root, as_of=_time(as_of))
        selection = select_context(bundle, **request['filters'], max_concepts=request['max_concepts'])
        if selection.unresolved_ids:
            raise KnowledgeBaseError('LINEAGE_CONTEXT_NEEDS_RESOLUTION')
        candidates = {concept.concept_id: concept for concept in selection.selected}
        requested = set(request['filters']['goals'] + request['filters']['kgis'] + request['filters']['initiatives'])
        critical_tags = set(bundle.profile['quality']['critical_tags'])
        required = {concept.concept_id for concept in selection.selected if critical_tags & set(concept.metadata.get('tags', []))}
        required.update(concept.concept_id for concept in bundle.concepts if concept.extension.get('strategy', {}).get('id') in requested)
        # Expand required Concept dependencies before rendering, within the
        # existing profile limit. Optional links do not become forced context.
        def expand(starts):
            found, frontier = {}, set(starts)
            for _ in range(32):
                following = set()
                if len(set(found) | frontier) > request['max_concepts']:
                    raise KnowledgeBaseError('LINEAGE_CONTEXT_REQUIRED_BUDGET')
                for logical in sorted(frontier):
                    pointer = db.execute('SELECT revision_ref FROM pointers WHERE logical_id=?', (logical,)).fetchone()
                    if pointer is None:
                        raise KnowledgeBaseError('LINEAGE_CONTEXT_POINTER_MISSING')
                    found[logical] = self.owner._eligible(db, pointer[0])
                    record = self.owner._record(db, pointer[0], 'concept')
                    for relation in record['relations']:
                        if relation['target_kind'] != 'concept' or not relation['required']:
                            continue
                        target = bundle.by_id.get(relation['target_id'])
                        source_concept = bundle.by_id.get(logical)
                        if target is not None and source_concept is not None and target.concept_id not in source_concept.resolved_concept_links:
                            raise KnowledgeBaseError('LINEAGE_CONTEXT_PORTABLE_LINK_REQUIRED')
                        following.add(relation['target_id'])
                frontier = following - set(found)
                if not frontier:
                    return found
            raise KnowledgeBaseError('LINEAGE_CONTEXT_DEPENDENCY_LIMIT')

        rows = expand(required)
        omitted = set(selection.omitted_ids)
        for logical in candidates:
            if logical in rows:
                continue
            try:
                trial = expand({logical})
            except KnowledgeBaseError as exc:
                # An optional closure may not fit. Never turn an owner access,
                # revision, dependency or integrity failure into an omission.
                if str(exc) not in {'LINEAGE_CONTEXT_POINTER_MISSING', 'LINEAGE_CONTEXT_REQUIRED_BUDGET'}:
                    raise
                omitted.add(logical)
                continue
            if len(set(rows) | set(trial)) > request['max_concepts']:
                omitted.add(logical)
                continue
            rows.update(trial)
        if not rows:
            raise KnowledgeBaseError('LINEAGE_CONTEXT_NEEDS_RESOLUTION')
        selected, sources = {}, {}
        for logical in sorted(rows):
            concept = bundle.by_id.get(logical)
            if concept is None or concept.metadata['status'] == 'deprecated' or concept.extension['knowledge_state'] not in {'candidate', 'confirmed'} or not concept.extension['agent_use']['discoverable']:
                raise KnowledgeBaseError('LINEAGE_CONTEXT_CONCEPT_WITHHELD')
            if not concept.stale_after or now >= _time(concept.stale_after):
                raise KnowledgeBaseError('LINEAGE_CONTEXT_CONCEPT_EXPIRED')
            current = rows[logical]
            if current['content_sha256'] != concept.content_sha256:
                raise KnowledgeBaseError('LINEAGE_CONTEXT_CONCEPT_CHANGED')
            if request['policy_revision_ref'] not in current['policy_revision_refs'] or request['intent_revision_ref'] not in current['intent_revision_refs']:
                raise KnowledgeBaseError('LINEAGE_CONTEXT_SCOPE_REVISION_MISMATCH')
            declared = {source['id']: source for source in concept.metadata['sources']}
            aliases = current.get('source_aliases', {})
            if set(aliases) != set(declared):
                raise KnowledgeBaseError('LINEAGE_CONTEXT_SOURCE_COVERAGE_UNRESOLVED')
            for alias, revision_ref in sorted(aliases.items()):
                source = self.owner._record(db, revision_ref, 'source')
                if source['locator_visibility'] == 'public':
                    path = _resolve_source_resource(source_path=concept.document.path, resource=declared[alias]['resource'],
                        repository_root=bundle.root, bundle_root=bundle.bundle_root)
                    if path is None or path != bundle.root / source['locator'] or dict(bundle.input_bindings).get(source['locator']) != source['content_sha256']:
                        raise KnowledgeBaseError('LINEAGE_CONTEXT_SOURCE_BINDING_MISMATCH')
                    if source.get('span', {}).get('kind') != 'events':
                        _public_span(source, path)
                else:
                    if self.verify_opaque is None:
                        raise KnowledgeBaseError('LINEAGE_CONTEXT_OPAQUE_UNVERIFIED')
                    self._require_true(self.verify_opaque,
                        {'request': request, 'concept_id': logical, 'source_alias': alias, 'source_binding': source,
                         'declared_resource': declared[alias]['resource'], 'stage': stage},
                        'LINEAGE_CONTEXT_OPAQUE_UNVERIFIED')
                if source.get('span', {}).get('kind') == 'events':
                    if self.verify_event_span is None:
                        raise KnowledgeBaseError('LINEAGE_CONTEXT_EVENT_SPAN_OWNER_REQUIRED')
                    self._require_true(self.verify_event_span,
                        {'request': request, 'source_binding': source, 'declared_resource': declared[alias]['resource'], 'stage': stage},
                        'LINEAGE_CONTEXT_EVENT_SPAN_UNVERIFIED')
                sources[revision_ref] = source
            selected[logical] = concept
        # Use the established v2 producer, then redact opaque source locations
        # through the same producer so its canonical digest is recomputed.
        import dataclasses
        selection = dataclasses.replace(selection, selected=tuple(selected[key] for key in sorted(selected)),
            omitted_ids=tuple(sorted(omitted - set(selected))))
        context = context_as_dict(selection, bundle=bundle)
        for item in context['concepts']:
            item['source_resources'] = sorted({sources[ref]['locator'] for ref in rows[item['id']]['source_aliases'].values()})
        context = make_context(bundle_id=context['bundle_id'], source_digest=context['source_digest'], as_of=context['as_of'],
            filters=context['filters'], concepts=context['concepts'], omitted_ids=context['omitted_ids'], unresolved_ids=context['unresolved_ids'])
        rendered = context_json(context).encode('utf-8')
        if len(rendered) > request['max_bytes']:
            raise KnowledgeBaseError('LINEAGE_CONTEXT_BYTE_BUDGET')
        bindings = {'request': request, 'concept_revisions': rows, 'source_bindings': sources,
                    'rendered_sha256': hashlib.sha256(rendered).hexdigest(), 'stage': stage}
        self._require_true(self.authorize_context, bindings, 'LINEAGE_CONTEXT_ACCESS_DENIED')
        _assert_current(bundle)
        final_time = _time(self.clock())
        if final_time >= _time(request['expires_at']) or any(final_time >= _time(concept.stale_after) for concept in selected.values()):
            raise KnowledgeBaseError('LINEAGE_CONTEXT_EXPIRED_BEFORE_USE')
        manifest = {'kind': 'kotodama.lineage-context-binding', 'schema_revision': 'v1',
            'request_sha256': digest(request), 'as_of': context['as_of'],
            'valid_until': min([_time(request['expires_at']), *(_time(c.stale_after) for c in selected.values())]).isoformat().replace('+00:00', 'Z'),
            'owner_generation': db.execute('SELECT generation FROM state WHERE id=1').fetchone()[0],
            'source_digest': bundle.source_digest, 'concept_revisions': {key: row['revision_ref'] for key, row in rows.items()},
            'source_set_digests': {key: row['source_set_sha256'] for key, row in rows.items()},
            'source_revision_refs': sorted(sources), 'rendered_sha256': bindings['rendered_sha256'],
            'context_sha256': context['context_sha256'], 'bytes': len(rendered), 'authority': 'projection_only',
            'artifact_sha256': _artifacts(),
            'source_identity_authenticated': False, 'provider_delivery_verified': False, 'human_go': False}
        projection_key = digest({'request': request, 'rendered_sha256': manifest['rendered_sha256']})
        manifest['projection_record'] = {
            'projection_ref': 'ref/context/' + '-'.join(projection_key[i:i + 8] for i in range(0, 64, 8)),
            'kind': 'context_pack', 'content_sha256': manifest['rendered_sha256'],
            'concept_revision_refs': sorted(row['revision_ref'] for row in rows.values()),
            'source_revision_refs': sorted(sources), 'goal_refs': request['filters']['goals'],
            'kgi_refs': request['filters']['kgis'], 'initiative_refs': request['filters']['initiatives']}
        return rendered, manifest

    def prepare(self, value):
        request = _request(value)
        as_of = _time(self.clock()).isoformat().replace('+00:00', 'Z')
        with self.owner._transaction('prepare_context', request['filters']['goals'], None, digest(request)) as db:
            _, manifest = self._candidate(db, request, as_of=as_of, stage='prepare')
            return manifest

    def consume(self, value, manifest, consumer):
        request = _request(value)
        manifest = _clone(manifest, 64 * 1024)
        if not callable(consumer) or any(check(callback) for callback in (consumer, getattr(consumer, '__call__', None))
                for check in (inspect.iscoroutinefunction, inspect.isasyncgenfunction, inspect.isgeneratorfunction)) or not isinstance(manifest, dict) or type(manifest.get('owner_generation')) is not int:
            raise KnowledgeBaseError('LINEAGE_CONTEXT_MANIFEST_INVALID')
        with self.owner._transaction('consume_context', request['filters']['goals'], manifest['owner_generation'], digest(request)) as db:
            rendered, current = self._candidate(db, request, as_of=manifest.get('as_of'), stage='consume')
            if digest(current) != digest(manifest):
                raise KnowledgeBaseError('LINEAGE_CONTEXT_MANIFEST_CHANGED')
            if _time(self.clock()) >= _time(current['valid_until']):
                raise KnowledgeBaseError('LINEAGE_CONTEXT_EXPIRED_BEFORE_USE')
            # This synchronous consumer owns actual transport/deduplication and
            # its receipts. A failure may be ambiguous; never retry it here.
            try:
                result = consumer(rendered)
                if inspect.isawaitable(result) or inspect.isasyncgen(result) or inspect.isgenerator(result):
                    if inspect.iscoroutine(result) or inspect.isgenerator(result): result.close()
                    raise KnowledgeBaseError('LINEAGE_CONTEXT_CONSUMER_NOT_SYNCHRONOUS')
            except Exception as exc:
                raise KnowledgeBaseError('LINEAGE_CONTEXT_CONSUMER_OUTCOME_UNCONFIRMED') from exc
            return {'status': 'LOCAL_CONSUMER_RETURNED', 'rendered_sha256': current['rendered_sha256'],
                    'provider_delivery_verified': False, 'human_go': False}
