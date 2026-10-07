"""Public synthetic metadata: no credentials, provider records, or grants."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from kotodama_kb.foundation import KnowledgeBaseError
from kotodama_kb.lineage_contract import admit_snapshot, digest, source_set_digest, validate_public_bytes


def fixture():
    source = {
        'source_id': 'ref/source/alpha', 'revision_ref': 'ref/source-revision/alpha-one',
        'revision_kind': 'content_digest', 'revision_value': hashlib.sha256(b'original source\n').hexdigest(),
        'content_sha256': hashlib.sha256(b'original source\n').hexdigest(),
        'observed_at': '2026-10-01T00:00:00Z', 'observer_ref': 'ref/invocation/observation',
        'authority_scope_ref': 'ref/scope/synthetic', 'custodian_ref': 'ref/actor/source-owner',
        'access_policy_ref': 'ref/policy/public-fixture', 'access_state': 'allowed',
        'retention_ref': 'ref/retention/fixture', 'legal_hold_ref': None, 'invalidation_key': 'ref/invalidation/alpha',
        'locator_visibility': 'public', 'locator': 'docs/synthetic-source.md',
        'span': {'kind': 'lines', 'start': 1, 'end': 1}}
    concept = {'concept_id': 'synthetic/example', 'revision_ref': 'ref/concept-revision/example-one',
        'parent_revision_ref': None, 'content_sha256': hashlib.sha256(b'synthetic concept\n').hexdigest(),
        'source_set_sha256': source_set_digest([source]), 'source_revision_refs': [source['revision_ref']],
        'generator_invocation_ref': 'ref/invocation/authoring', 'policy_revision_refs': ['ref/policy-revision/one'],
        'intent_revision_refs': ['ref/intent-revision/one'], 'status': 'candidate'}
    relation = {'from_revision_ref': concept['revision_ref'], 'predicate': 'derived_from',
        'target_kind': 'source', 'target_id': source['source_id'], 'target_revision_ref': source['revision_ref'],
        'required': True, 'validity': 'current', 'resolution': 'resolved', 'evidence_ref': 'ref/evidence/source-check'}
    projection = {'projection_ref': 'ref/projection/context-one', 'kind': 'context_pack',
        'content_sha256': 'a' * 64, 'concept_revision_refs': [concept['revision_ref']],
        'source_revision_refs': [source['revision_ref']], 'goal_refs': ['OUT-INTENT'],
        'kgi_refs': ['KGI-INTENT'], 'initiative_refs': []}
    return {'kind': 'kotodama.knowledge-lineage', 'schema_revision': 'v1', 'authority': 'projection_only',
        'contains_content': False, 'sources': [source], 'concepts': [concept], 'relations': [relation], 'projections': [projection]}


def rebind(snapshot):
    sources = {row['revision_ref']: row for row in snapshot['sources']}
    for concept in snapshot['concepts']:
        concept['source_set_sha256'] = source_set_digest(sources[ref] for ref in concept['source_revision_refs'])


class KnowledgeLineageContractTests(unittest.TestCase):
    def assertRefused(self, snapshot, code=None):
        with self.assertRaises(KnowledgeBaseError) as caught:
            admit_snapshot(snapshot)
        if code:
            self.assertEqual(code, str(caught.exception))
        self.assertNotIn('private-test-value', str(caught.exception))

    def test_closed_synthetic_contract_clones_callers_and_has_deterministic_digest(self):
        original = fixture()
        admitted = admit_snapshot(original)
        self.assertEqual(digest(original), digest(admitted))
        self.assertEqual(admitted, admit_snapshot(admitted))
        original['sources'][0]['access_state'] = 'revoked'
        self.assertEqual('allowed', admitted['sources'][0]['access_state'])
        for mutate in (lambda v: v.update(contains_content=True), lambda v: v.update(authority='current_truth'),
                       lambda v: v['sources'][0].update(body='private-test-value')):
            value = fixture(); mutate(value); self.assertRefused(value)

    def test_duplicate_and_conflicting_source_revisions_are_refused(self):
        for collection in ('sources', 'concepts', 'projections'):
            value = fixture(); value[collection].append(copy.deepcopy(value[collection][0])); self.assertRefused(value)
        value = fixture(); alternate = copy.deepcopy(value['sources'][0])
        alternate.update(revision_ref='ref/source-revision/alpha-alternate', content_sha256='b' * 64)
        value['sources'].append(alternate); self.assertRefused(value, 'LINEAGE_SOURCE_CONFLICT')

    def test_exact_source_and_metadata_changes_require_a_new_source_set_digest(self):
        for field, changed in (('content_sha256', 'b' * 64), ('access_state', 'revoked'),
                               ('observed_at', '2026-10-02T00:00:00Z'), ('retention_ref', 'ref/retention/changed')):
            value = fixture(); old = digest(value); value['sources'][0][field] = changed
            if field == 'content_sha256': value['sources'][0]['revision_value'] = changed
            self.assertRefused(value, 'LINEAGE_SOURCE_SET_DIGEST')
            rebind(value); self.assertNotEqual(old, digest(admit_snapshot(value)))

    def test_private_absolute_url_or_unapproved_opaque_locator_is_rejected(self):
        for locator in ('C:/private-test-value/notes.txt', '/private-test-value', '../private-test-value',
                        'docs/../../private-test-value', 'docs//private-test-value', 'https://private.invalid/notes',
                        r'\\private-test-value\notes', 'docs/%2e%2e/notes.md'):
            value = fixture(); value['sources'][0]['locator'] = locator; rebind(value); self.assertRefused(value)
        value = fixture(); value['sources'][0].update(locator_visibility='opaque', locator='ref/locator/alpha')
        rebind(value); self.assertEqual('opaque', admit_snapshot(value)['sources'][0]['locator_visibility'])
        for locator in ('ref/locator/user@example.invalid', 'ref/locator/https://private.invalid', 'private-test-value'):
            value['sources'][0]['locator'] = locator; rebind(value); self.assertRefused(value)

    def test_exact_revision_kinds_spans_parent_identity_and_cycles(self):
        for field, change in (('revision_value', 'c' * 64), ('span', {'kind': 'lines', 'start': 4, 'end': 2})):
            value = fixture(); value['sources'][0][field] = change; rebind(value); self.assertRefused(value)
        for kind, revision in (('git_commit', 'z' * 40), ('event_sequence', '01')):
            value = fixture(); value['sources'][0].update(revision_kind=kind, revision_value=revision)
            rebind(value); self.assertRefused(value)
        value = fixture(); first = value['concepts'][0]; second = copy.deepcopy(first)
        second.update(revision_ref='ref/concept-revision/example-two', parent_revision_ref=first['revision_ref'])
        first['parent_revision_ref'] = second['revision_ref']; value['concepts'].append(second)
        self.assertRefused(value, 'LINEAGE_PARENT_CYCLE')
        second['concept_id'] = 'synthetic/different'; self.assertRefused(value, 'LINEAGE_PARENT_MISMATCH')

    def test_unresolved_relation_is_explicit_and_resolved_identity_cannot_lie(self):
        value = fixture(); edge = value['relations'][0]; edge['target_revision_ref'] = 'ref/source-revision/missing'
        self.assertRefused(value, 'LINEAGE_FALSE_RESOLUTION')
        edge['resolution'] = 'unresolved'; admit_snapshot(value)
        edge['target_revision_ref'] = value['sources'][0]['revision_ref']; edge['target_id'] = 'ref/source/other'
        self.assertRefused(value, 'LINEAGE_RELATION_TARGET_MISMATCH')
        value = fixture(); value['relations'][0]['target_id'] = 'OUT-INTENT'
        self.assertRefused(value, 'LINEAGE_RELATION_TARGET_TYPE')

    def test_unknown_projection_or_concept_source_is_never_resolved(self):
        value = fixture(); value['concepts'][0]['source_revision_refs'] = ['ref/source-revision/missing']
        self.assertRefused(value, 'LINEAGE_SOURCE_MISSING')
        value = fixture(); value['projections'][0]['concept_revision_refs'] = ['ref/concept-revision/missing']
        self.assertRefused(value, 'LINEAGE_PROJECTION_TARGET_MISSING')

    def test_optional_footnote_aliases_bind_exactly_the_declared_source_set(self):
        value = fixture(); value['concepts'][0]['source_aliases'] = {'primary': value['sources'][0]['revision_ref']}
        admitted = admit_snapshot(value)
        self.assertEqual(value['concepts'][0]['source_aliases'], admitted['concepts'][0]['source_aliases'])
        value['concepts'][0]['source_aliases']['primary'] = 'ref/source-revision/different'
        self.assertRefused(value, 'LINEAGE_SOURCE_ALIAS_BINDING')

    def test_real_bytes_readback_catches_same_path_change_without_resolving_opaque(self):
        value = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'docs/synthetic-source.md'; source.parent.mkdir(); source.write_bytes(b'original source\n')
            concept = root / 'knowledge/synthetic/example.md'; concept.parent.mkdir(parents=True); concept.write_bytes(b'synthetic concept\n')
            receipt = validate_public_bytes(value, repository_root=root)
            self.assertTrue(receipt['local_bytes_match']); self.assertFalse(receipt['access_authenticated'])
            source.write_bytes(b'corrected source\n')
            self.assertEqual([value['sources'][0]['revision_ref']], validate_public_bytes(value, repository_root=root)['mismatched_revision_refs'])
            value['sources'][0].update(locator_visibility='opaque', locator='ref/locator/alpha'); rebind(value)
            receipt = validate_public_bytes(value, repository_root=root)
            self.assertTrue(receipt['local_bytes_match'])
            self.assertEqual([value['sources'][0]['revision_ref']], receipt['opaque_unverified_revision_refs'])
            self.assertFalse(receipt['source_authenticated']); self.assertFalse(receipt['current_pointer_verified'])

    def test_real_bytes_readback_rejects_missing_and_hardlinked_files(self):
        value = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(KnowledgeBaseError): validate_public_bytes(value, repository_root=root)
            source = root / 'docs/synthetic-source.md'; source.parent.mkdir(); source.write_bytes(b'original source\n')
            os.link(source, root / 'alias.md')
            with self.assertRaises(KnowledgeBaseError): validate_public_bytes(value, repository_root=root)

    def test_cli_checks_real_fixture_and_refuses_duplicate_json_without_echo_or_writes(self):
        cli = ROOT / 'tools/knowledge_lineage.py'
        example = ROOT / 'examples/knowledge-lineage'
        before = {p.relative_to(example): p.read_bytes() for p in example.rglob('*') if p.is_file()}
        result = subprocess.run([sys.executable, str(cli), 'readback', '--snapshot', str(example / 'snapshot.json'),
                                 '--root', str(example)], capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual('LOCAL_METADATA_PASS', json.loads(result.stdout)['status'])
        self.assertEqual(before, {p.relative_to(example): p.read_bytes() for p in example.rglob('*') if p.is_file()})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.json'; path.write_text('{"x":"private-test-value","x":1}', encoding='utf-8')
            result = subprocess.run([sys.executable, str(cli), 'validate', '--snapshot', str(path)],
                                     capture_output=True, text=True, encoding='utf-8', timeout=20)
            self.assertEqual(1, result.returncode); self.assertEqual('REFUSED', json.loads(result.stdout)['status'])
            self.assertNotIn('private-test-value', result.stdout + result.stderr)

    def test_set_order_is_not_a_new_revision_but_changed_expectations_are(self):
        value = fixture(); value['concepts'][0]['policy_revision_refs'].append('ref/policy-revision/two')
        other = copy.deepcopy(value); other['concepts'][0]['policy_revision_refs'].reverse()
        self.assertEqual(digest(admit_snapshot(value)), digest(admit_snapshot(other)))
        other['concepts'][0]['policy_revision_refs'].append('ref/policy-revision/three')
        self.assertNotEqual(digest(value), digest(admit_snapshot(other)))

    def test_non_json_values_and_size_limits_fail_without_echo(self):
        for value in ({'x': float('nan')}, {'x': b'private-test-value'}, {'x': 'x' * (1024 * 1024 + 1)}):
            self.assertRefused(value)


if __name__ == '__main__':
    unittest.main()
