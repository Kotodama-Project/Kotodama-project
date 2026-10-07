"""Actual v2 context producer with synthetic local source and owner callbacks."""
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from kotodama_kb.foundation import KnowledgeBaseError
from kotodama_kb.load import load_bundle
from kotodama_kb.lineage_context import LineageContextGate
from kotodama_kb.revision_owner import LocalRevisionOwner
from tests.test_knowledge_lineage import fixture, rebind

NOW = dt.datetime(2026, 10, 7, tzinfo=dt.timezone.utc)


class KnowledgeLineageContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.now = NOW; self.allowed = True; self.calls = []
        for directory in ('knowledge/synthetic', 'schemas', 'docs'): (self.root / directory).mkdir(parents=True)
        for name in ('kotodama-okf-profile.schema.json', 'kotodama-okf-concept.schema.json'):
            shutil.copyfile(ROOT / 'schemas' / name, self.root / 'schemas' / name)
        shutil.copyfile(ROOT / 'knowledge/profile.yaml', self.root / 'knowledge/profile.yaml')
        (self.root / 'docs/synthetic-source.md').write_bytes(b'original source\n')
        self.meta = {'type': 'Information', 'title': '合成の依頼', 'description': '出典付き候補の合成例',
            'tags': ['synthetic', 'current-state'], 'status': 'draft', 'stale_after': '2026-12-07T00:00:00Z',
            'generated': {'by': 'process:synthetic', 'at': '2026-10-01T00:00:00Z'},
            'sources': [{'id': 'manual', 'resource': '../../docs/synthetic-source.md', 'title': '合成出典', 'author': 'team:synthetic'}],
            'kotodama': {'profile': '0.1', 'id': 'synthetic/example', 'classification': 'public_candidate',
                'authority': 'projection_only', 'knowledge_state': 'candidate', 'owner_role': 'AI-ANALYST',
                'reviewer_role': 'AI-AUDITOR', 'context_priority': 20, 'goal_refs': [], 'kgi_refs': [], 'initiative_refs': [],
                'agent_use': {'discoverable': True, 'answer_mode': 'source_required', 'decision_authority': False, 'runtime_authority': False}}}
        self.write_concept(self.meta)
        (self.root / 'knowledge/index.md').write_text('---\nokf_version: "0.2"\n---\n\n* [合成](synthetic/example.md)\n', encoding='utf-8')
        bundle = load_bundle(self.root, as_of=NOW)
        self.assertFalse([item for item in bundle.issues if item.level == 'error'])
        snapshot = fixture()
        snapshot['concepts'][0]['content_sha256'] = bundle.by_id['synthetic/example'].content_sha256
        snapshot['concepts'][0]['source_aliases'] = {'manual': snapshot['sources'][0]['revision_ref']}
        self.snapshot = copy.deepcopy(snapshot)
        self.owner = LocalRevisionOwner(self.root / 'work/owner.sqlite', repository_root=self.root, authorize=lambda request: True)
        self.owner.register(snapshot, expected_generation=0)
        self.owner.publish(snapshot['concepts'][0]['revision_ref'], expected_parent_ref=None, expected_generation=1)
        self.current_ref = snapshot['concepts'][0]['revision_ref']
        self.request = {key: 'ref/' + value for key, value in {
            'request_ref': 'request/one', 'actor_ref': 'actor/reader', 'recipient_ref': 'actor/consumer',
            'purpose_ref': 'purpose/context', 'task_ref': 'task/one', 'session_ref': 'session/one',
            'intent_revision_ref': 'intent-revision/one', 'policy_revision_ref': 'policy-revision/one', 'grant_ref': 'grant/synthetic'}.items()}
        self.request.update(expires_at='2026-10-07T01:00:00Z', max_bytes=32768, max_concepts=2,
                            filters={'goals': [], 'kgis': [], 'initiatives': [], 'tags': ['synthetic']})
        self.gate = LineageContextGate(self.owner, authorize_context=self.authorize, clock=lambda: self.now)

    def write_concept(self, metadata):
        path = self.root / 'knowledge' / (metadata['kotodama']['id'] + '.md')
        path.write_text('---\n' + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False) + '---\n\nEvidence only.[^manual]\n\n[^manual]: Synthetic source.\n', encoding='utf-8')

    def authorize(self, value):
        self.calls.append(value)
        return self.allowed and value['request']['actor_ref'] == 'ref/actor/reader'

    def revise(self, *, source_changes=None):
        self.write_concept(self.meta)
        value = fixture(); generation = self.owner.generation()
        source = value['sources'][0]
        source.update(revision_ref=f'ref/source-revision/revision-{generation}', **(source_changes or {}))
        source['revision_value'] = source['content_sha256']
        concept = value['concepts'][0]
        concept.update(revision_ref=f'ref/concept-revision/revision-{generation}', parent_revision_ref=self.current_ref,
            parent_resolution='external_unresolved',
            source_revision_refs=[source['revision_ref']], source_aliases={'manual': source['revision_ref']},
            content_sha256=load_bundle(self.root, as_of=NOW).by_id['synthetic/example'].content_sha256)
        value['relations'][0].update(from_revision_ref=concept['revision_ref'], target_revision_ref=source['revision_ref'])
        value['projections'][0].update(concept_revision_refs=[concept['revision_ref']], source_revision_refs=[source['revision_ref']])
        rebind(value); self.owner.register(value, expected_generation=generation)
        self.owner.publish(concept['revision_ref'], expected_parent_ref=self.current_ref, expected_generation=generation + 1)
        self.current_ref = concept['revision_ref']

    def test_changed_manifest_request_and_actor_are_not_treated_as_a_valid_binding(self):
        manifest = self.gate.prepare(self.request)
        for field, changed in (('bytes', 1), ('rendered_sha256', 'b' * 64), ('owner_generation', 0),
                               ('source_set_digests', {}), ('request_sha256', 'b' * 64), ('as_of', 'private-test-value')):
            bad = {**manifest, field: changed}; delivered = []
            with self.assertRaises(KnowledgeBaseError) as caught: self.gate.consume(self.request, bad, delivered.append)
            self.assertNotIn('private-test-value', str(caught.exception)); self.assertEqual([], delivered)
        request = {**self.request, 'actor_ref': 'ref/actor/other'}
        with self.assertRaises(KnowledgeBaseError): self.gate.consume(request, manifest, lambda body: self.fail('unexpected consumer'))
        for bad in ({**self.request, 'max_concepts': True}, {**self.request, 'body': 'private-test-value'}):
            with self.assertRaises(KnowledgeBaseError): self.gate.prepare(bad)

    def test_expiry_during_access_callback_refuses_the_consumer(self):
        manifest = self.gate.prepare(self.request); delivered = []
        def expire(value):
            self.now += dt.timedelta(hours=2)
            return True
        self.gate.authorize_context = expire
        with self.assertRaisesRegex(KnowledgeBaseError, 'EXPIRED_BEFORE_USE'):
            self.gate.consume(self.request, manifest, delivered.append)
        self.assertEqual([], delivered)

    def test_async_and_ambiguous_consumer_outcomes_are_not_success_or_retried(self):
        manifest = self.gate.prepare(self.request); calls = []
        async def asynchronous(body): calls.append(body)
        with self.assertRaises(KnowledgeBaseError): self.gate.consume(self.request, manifest, asynchronous)
        with self.assertRaises(KnowledgeBaseError): self.gate.consume(self.request, manifest, lambda body: asynchronous(body))
        self.assertEqual([], calls)
        def ambiguous(body):
            calls.append(body)
            raise RuntimeError('synthetic response lost')
        with self.assertRaisesRegex(KnowledgeBaseError, 'OUTCOME_UNCONFIRMED'):
            self.gate.consume(self.request, manifest, ambiguous)
        self.assertEqual(1, len(calls))

    def test_real_copied_code_byte_change_invalidates_the_prepared_binding(self):
        import kotodama_kb.lineage_context as module
        original = module._read_bytes
        target = Path(module.__file__)
        copied = self.root / 'work/copied-gate.py'; shutil.copyfile(target, copied)
        def read(path): return original(copied if path == target else path)
        with mock.patch.object(module, '_read_bytes', side_effect=read):
            manifest = self.gate.prepare(self.request)
            copied.write_bytes(copied.read_bytes() + b'\n# synthetic byte mutation\n')
            with self.assertRaisesRegex(KnowledgeBaseError, 'MANIFEST_CHANGED'):
                self.gate.consume(self.request, manifest, lambda body: self.fail('unexpected consumer'))

    def test_opaque_source_requires_owner_mapping_and_is_redacted_from_context(self):
        resource = 'https://provider.invalid/private-synthetic-object'
        self.meta['sources'][0]['resource'] = resource
        self.revise(source_changes={'locator_visibility': 'opaque', 'locator': 'ref/locator/alpha'})
        with self.assertRaisesRegex(KnowledgeBaseError, 'OPAQUE_UNVERIFIED'): self.gate.prepare(self.request)
        observed = []
        def verify(value):
            observed.append(value)
            return value['declared_resource'] == resource and value['source_binding']['locator'] == 'ref/locator/alpha'
        self.gate.verify_opaque = verify
        manifest = self.gate.prepare(self.request); delivered = []
        self.gate.consume(self.request, manifest, delivered.append)
        self.assertEqual(['prepare', 'consume'], [value['stage'] for value in observed])
        self.assertNotIn('provider.invalid', delivered[0].decode('utf-8') + json.dumps(manifest))
        self.assertEqual(['ref/locator/alpha'], json.loads(delivered[0])['concepts'][0]['source_resources'])
        self.gate.verify_opaque = lambda value: False
        with self.assertRaises(KnowledgeBaseError): self.gate.consume(self.request, manifest, lambda body: self.fail('unexpected consumer'))

    def test_missing_public_claim_span_and_context_byte_budget_fail_before_use(self):
        self.revise(source_changes={'span': {'kind': 'lines', 'start': 1, 'end': 2}})
        with self.assertRaisesRegex(KnowledgeBaseError, 'SOURCE_SPAN_UNRESOLVED'): self.gate.prepare(self.request)
        self.revise(source_changes={'span': {'kind': 'lines', 'start': 1, 'end': 1}})
        with self.assertRaisesRegex(KnowledgeBaseError, 'BYTE_BUDGET'): self.gate.prepare({**self.request, 'max_bytes': 1})

    def dependency_snapshot(self):
        for logical, tags, priority in (('synthetic/policy', ['background'], 100), ('synthetic/optional', ['synthetic'], 30)):
            metadata = copy.deepcopy(self.meta); metadata['kotodama']['id'] = logical
            metadata['kotodama']['context_priority'] = priority; metadata['tags'] = tags; self.write_concept(metadata)
            with (self.root / 'knowledge/index.md').open('a', encoding='utf-8') as stream:
                stream.write(f'* [{logical}]({logical}.md)\n')
        with (self.root / 'knowledge/synthetic/example.md').open('a', encoding='utf-8') as stream:
            stream.write('\n[Required policy](policy.md)\n')
        bundle = load_bundle(self.root, as_of=NOW); value = fixture(); original = value['concepts'][0]
        value['concepts'] = []; value['relations'] = []; value['projections'] = []
        for logical, suffix in (('synthetic/example', 'two'), ('synthetic/policy', 'policy'), ('synthetic/optional', 'optional')):
            concept = copy.deepcopy(original)
            concept.update(concept_id=logical, revision_ref='ref/concept-revision/' + suffix,
                parent_revision_ref=self.current_ref if suffix == 'two' else None,
                content_sha256=bundle.by_id[logical].content_sha256,
                source_aliases={'manual': value['sources'][0]['revision_ref']})
            if suffix == 'two': concept['parent_resolution'] = 'external_unresolved'
            value['concepts'].append(concept)
        value['relations'].append({'from_revision_ref': 'ref/concept-revision/two', 'predicate': 'requires_context',
            'target_kind': 'concept', 'target_id': 'synthetic/policy', 'target_revision_ref': 'ref/concept-revision/policy',
            'required': True, 'validity': 'current', 'resolution': 'resolved', 'evidence_ref': 'ref/evidence/policy-context'})
        self.owner.register(value, expected_generation=2)
        self.owner.publish('ref/concept-revision/policy', expected_parent_ref=None, expected_generation=3)
        self.owner.publish('ref/concept-revision/optional', expected_parent_ref=None, expected_generation=4)
        self.owner.publish('ref/concept-revision/two', expected_parent_ref=self.current_ref, expected_generation=5)
        self.current_ref = 'ref/concept-revision/two'

    def test_mandatory_typed_ancestor_displaces_optional_context_within_budget(self):
        self.dependency_snapshot()
        manifest = self.gate.prepare(self.request); delivered = []
        self.gate.consume(self.request, manifest, delivered.append)
        context = json.loads(delivered[0])
        self.assertEqual(['synthetic/example', 'synthetic/policy'], [item['id'] for item in context['concepts']])
        self.assertIn('synthetic/optional', context['omitted_ids'])
        with self.assertRaisesRegex(KnowledgeBaseError, 'REQUIRED_BUDGET'):
            self.gate.prepare({**self.request, 'max_concepts': 1})

    def test_typed_dependencies_require_portable_links_and_current_target_revisions(self):
        self.dependency_snapshot()
        self.write_concept(self.meta)  # Deliberately removes the portable policy link.
        with self.assertRaisesRegex(KnowledgeBaseError, 'PORTABLE_LINK_REQUIRED'): self.gate.prepare(self.request)
        with (self.root / 'knowledge/synthetic/example.md').open('a', encoding='utf-8') as stream:
            stream.write('\n[Required policy](policy.md)\n')
        value = fixture(); source = value['sources'][0]; policy = value['concepts'][0]
        policy.update(concept_id='synthetic/policy', revision_ref='ref/concept-revision/policy-new',
            parent_revision_ref='ref/concept-revision/policy', parent_resolution='external_unresolved', source_aliases={'manual': source['revision_ref']},
            content_sha256=load_bundle(self.root, as_of=NOW).by_id['synthetic/policy'].content_sha256)
        value['relations'] = []; value['projections'] = []
        self.owner.register(value, expected_generation=6)
        self.owner.publish(policy['revision_ref'], expected_parent_ref=policy['parent_revision_ref'], expected_generation=7)
        with self.assertRaisesRegex(KnowledgeBaseError, 'DEPENDENCY_NOT_CURRENT'): self.gate.prepare(self.request)

    def test_strict_json_pointer_checks_positions_without_claiming_semantic_support(self):
        raw = b'{"items":[{"k/v":"synthetic"}]}\n'
        (self.root / 'docs/synthetic-source.md').write_bytes(raw)
        content = hashlib.sha256(raw).hexdigest()
        self.revise(source_changes={'content_sha256': content, 'span': {'kind': 'json_pointer', 'pointer': '/items/0/k~1v'}})
        manifest = self.gate.prepare(self.request); delivered = []; self.gate.consume(self.request, manifest, delivered.append)
        self.assertFalse(json.loads(delivered[0])['claims']['semantic_entailment_verified'])
        self.revise(source_changes={'content_sha256': content, 'span': {'kind': 'json_pointer', 'pointer': '/items/01/k~1v'}})
        with self.assertRaisesRegex(KnowledgeBaseError, 'SOURCE_SPAN_UNRESOLVED'): self.gate.prepare(self.request)

    def test_event_range_requires_an_existing_event_owner_and_rechecks_at_use(self):
        self.revise(source_changes={'span': {'kind': 'events', 'from_event_ref': 'ref/event/one', 'to_event_ref': 'ref/event/two'}})
        with self.assertRaisesRegex(KnowledgeBaseError, 'EVENT_SPAN_OWNER_REQUIRED'): self.gate.prepare(self.request)
        self.gate.verify_event_span = lambda value: value['source_binding']['span']['from_event_ref'] == 'ref/event/one'
        manifest = self.gate.prepare(self.request)
        self.gate.verify_event_span = lambda value: False
        with self.assertRaisesRegex(KnowledgeBaseError, 'EVENT_SPAN_UNVERIFIED'):
            self.gate.consume(self.request, manifest, lambda body: self.fail('unexpected consumer'))

    def test_real_selector_and_v2_producer_reach_only_the_bound_consumer(self):
        manifest = self.gate.prepare(self.request)
        delivered = []
        receipt = self.gate.consume(self.request, manifest, delivered.append)
        self.assertEqual(1, len(delivered)); self.assertEqual('LOCAL_CONSUMER_RETURNED', receipt['status'])
        self.assertEqual(manifest['rendered_sha256'], hashlib.sha256(delivered[0]).hexdigest())
        context = json.loads(delivered[0])
        schema = json.loads((ROOT / 'schemas/knowledge-context-bundle.schema.json').read_text(encoding='utf-8'))
        self.assertEqual([], list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(context)))
        self.assertEqual(16, len(context)); self.assertFalse(context['claims']['execution_authorized'])
        self.assertEqual(['prepare', 'consume'], [call['stage'] for call in self.calls])
        self.assertEqual(manifest, self.gate.prepare(self.request))

    def test_actual_rendered_context_record_is_reachable_from_source_impact_index(self):
        from kotodama_kb.lineage_contract import admit_snapshot
        from kotodama_kb.lineage_impact import project_lineage, compare_lineage
        manifest = self.gate.prepare(self.request)
        snapshot = copy.deepcopy(self.snapshot); snapshot['projections'] = [manifest['projection_record']]
        snapshot = admit_snapshot(snapshot)
        projection = project_lineage(snapshot)
        ref = manifest['projection_record']['projection_ref']
        self.assertIn(ref, projection['indexes']['source_revision_to_projections']['ref/source-revision/alpha-one'])
        invalidated = compare_lineage(snapshot, snapshot, invalidation_keys=['ref/invalidation/alpha'])
        self.assertIn(ref, invalidated['quarantine_revision_refs'])

    def test_real_catalog_and_graph_outputs_are_bound_and_reverse_indexed(self):
        from kotodama_kb.lineage_projection import bind_generated_projections
        from kotodama_kb.lineage_impact import project_lineage
        from kotodama_kb.project import generated_outputs
        bundle = load_bundle(self.root, as_of=NOW)
        before = {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        result = bind_generated_projections(bundle, {**self.snapshot, 'projections': []})
        records = result['snapshot']['projections']
        self.assertEqual({'catalog', 'graph'}, {row['kind'] for row in records})
        self.assertEqual({hashlib.sha256(value).hexdigest() for value in generated_outputs(bundle).values()}, {row['content_sha256'] for row in records})
        index = project_lineage(result['snapshot'])
        self.assertEqual(sorted(row['projection_ref'] for row in records), index['indexes']['source_revision_to_projections']['ref/source-revision/alpha-one'])
        self.assertEqual(before, {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()})
        self.assertFalse(result['current_pointer_verified'])
        self.assertEqual(result, bind_generated_projections(bundle, result['snapshot']))
        missing = {**self.snapshot, 'concepts': [], 'relations': [], 'projections': []}
        with self.assertRaisesRegex(KnowledgeBaseError, 'COVERAGE_REQUIRED'): bind_generated_projections(bundle, missing)

    def test_revocation_after_assembly_blocks_consumer_without_a_regeneration(self):
        manifest = self.gate.prepare(self.request); delivered = []
        self.owner.revoke('ref/invalidation/alpha', evidence_ref='ref/evidence/withdrawn', expected_generation=2)
        with self.assertRaises(KnowledgeBaseError): self.gate.consume(self.request, manifest, delivered.append)
        self.assertEqual([], delivered)

    def test_source_change_request_expiry_and_owner_denial_never_reach_consumer(self):
        manifest = self.gate.prepare(self.request); delivered = []
        self.allowed = False
        with self.assertRaises(KnowledgeBaseError): self.gate.consume(self.request, manifest, delivered.append)
        self.allowed = True; self.now += dt.timedelta(hours=1)
        with self.assertRaises(KnowledgeBaseError): self.gate.consume(self.request, manifest, delivered.append)
        self.now = NOW; (self.root / 'docs/synthetic-source.md').write_bytes(b'changed source\n')
        with self.assertRaises(KnowledgeBaseError): self.gate.consume(self.request, manifest, delivered.append)
        self.assertEqual([], delivered)

    def test_unbound_optional_concept_is_omitted_without_losing_required_context(self):
        optional = copy.deepcopy(self.meta); optional['tags'] = ['synthetic']; optional['kotodama']['id'] = 'synthetic/optional'
        optional['kotodama']['context_priority'] = 100; self.write_concept(optional)
        with (self.root / 'knowledge/index.md').open('a', encoding='utf-8') as stream: stream.write('* [任意](synthetic/optional.md)\n')
        manifest = self.gate.prepare(self.request); delivered = []
        self.gate.consume(self.request, manifest, delivered.append)
        context = json.loads(delivered[0])
        self.assertEqual(['synthetic/example'], [item['id'] for item in context['concepts']])
        self.assertIn('synthetic/optional', context['omitted_ids'])


if __name__ == '__main__': unittest.main()
