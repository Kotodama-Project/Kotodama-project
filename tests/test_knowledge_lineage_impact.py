"""Fixed revision/metadata changes and bounded reverse dependency traversal."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from kotodama_kb.foundation import KnowledgeBaseError
from kotodama_kb.lineage_contract import digest
from kotodama_kb.lineage_impact import project_lineage, compare_lineage
from tests.test_knowledge_lineage import fixture, rebind

SOURCE = 'ref/source-revision/alpha-one'
FIRST = 'ref/concept-revision/example-one'
SECOND = 'ref/concept-revision/dependent-one'
OPTIONAL = 'ref/concept-revision/optional-one'
PACK = 'ref/projection/context-one'
KEY = 'ref/invalidation/alpha'


def edge(origin, target, logical, *, required=True, predicate='depends_on'):
    return {'from_revision_ref': origin, 'predicate': predicate, 'target_kind': 'concept',
            'target_id': logical, 'target_revision_ref': target, 'required': required,
            'validity': 'current', 'resolution': 'resolved', 'evidence_ref': 'ref/evidence/link-review'}


def chain():
    value = fixture()
    second_source = copy.deepcopy(value['sources'][0])
    second_source.update(source_id='ref/source/beta', revision_ref='ref/source-revision/beta-one',
                         invalidation_key='ref/invalidation/beta', locator='docs/beta.md')
    value['sources'].append(second_source)
    for ref, logical in ((SECOND, 'synthetic/dependent'), (OPTIONAL, 'synthetic/optional')):
        concept = copy.deepcopy(value['concepts'][0])
        concept.update(concept_id=logical, revision_ref=ref, source_revision_refs=[second_source['revision_ref']])
        value['concepts'].append(concept)
    value['relations'] += [edge(SECOND, FIRST, 'synthetic/example'), edge(OPTIONAL, FIRST, 'synthetic/example', required=False)]
    value['projections'][0].update(concept_revision_refs=[SECOND], source_revision_refs=[])
    rebind(value)
    return value


class KnowledgeLineageImpactTests(unittest.TestCase):
    def test_indexes_reach_context_and_metric_inputs_and_strategy_nodes(self):
        value = chain()
        metric = copy.deepcopy(value['projections'][0]); metric.update(projection_ref='ref/projection/metric-one', kind='metric_input')
        value['projections'].append(metric)
        projected = project_lineage(value)
        indexes = projected['indexes']
        self.assertEqual([SECOND, FIRST], indexes['source_revision_to_concepts'][SOURCE])
        self.assertEqual([PACK, metric['projection_ref']], indexes['source_revision_to_projections'][SOURCE])
        self.assertIn(PACK, indexes['concept_revision_to_projections'][FIRST])
        self.assertIn(SECOND, indexes['invalidation_key_to_nodes'][KEY])
        self.assertIn(PACK, indexes['strategy_to_nodes']['KGI-INTENT'])
        self.assertFalse(projected['serving_authorized']); self.assertTrue(projected['complete'])

    def test_exact_byte_change_propagates_only_mandatory_and_reports_optional(self):
        before = chain(); after = copy.deepcopy(before)
        after['sources'][0].update(content_sha256='b' * 64, revision_value='b' * 64); rebind(after)
        impact = compare_lineage(before, after)
        self.assertEqual([SECOND, FIRST, PACK, SOURCE], impact['affected_revision_refs'])
        self.assertEqual([OPTIONAL], impact['optional_revision_refs'])
        self.assertEqual('CHANGED', impact['status'])
        self.assertEqual(impact['affected_revision_refs'], impact['quarantine_revision_refs'])

    def test_same_bytes_with_changed_observation_or_access_is_not_noop(self):
        for field, change in (('observed_at', '2026-10-02T00:00:00Z'), ('access_state', 'revoked')):
            before = chain(); after = copy.deepcopy(before)
            after['sources'][0][field] = change; rebind(after)
            self.assertIn(PACK, compare_lineage(before, after)['quarantine_revision_refs'])

    def test_unchanged_input_is_noop_with_same_receipt_but_revoked_stays_quarantined(self):
        value = chain(); impact = compare_lineage(value, value)
        self.assertEqual('NO_CHANGE', impact['status']); self.assertEqual([], impact['affected_revision_refs'])
        reverse = copy.deepcopy(value)
        for collection in ('sources', 'concepts', 'relations', 'projections'): reverse[collection].reverse()
        self.assertEqual(impact, compare_lineage(reverse, value))
        value['sources'][0]['access_state'] = 'revoked'; rebind(value)
        impact = compare_lineage(value, value)
        self.assertEqual('NO_CHANGE', impact['status']); self.assertIn(PACK, impact['quarantine_revision_refs'])

    def test_revocation_key_fans_out_before_rebuild_and_old_dependencies_survive_removal(self):
        value = chain(); impact = compare_lineage(value, value, invalidation_keys=[KEY])
        self.assertIn(PACK, impact['quarantine_revision_refs']); self.assertIn(OPTIONAL, impact['optional_revision_refs'])
        empty = fixture()
        for collection in ('sources', 'concepts', 'relations', 'projections'): empty[collection] = []
        removed = compare_lineage(value, empty)
        self.assertIn(PACK, removed['affected_revision_refs'])
        with self.assertRaises(KnowledgeBaseError): compare_lineage(value, value, invalidation_keys=['ref/invalidation/missing'])

    def test_missing_required_and_optional_targets_are_separate(self):
        for required in (True, False):
            value = chain(); relation = edge(SECOND, 'ref/concept-revision/missing', 'synthetic/missing', required=required)
            relation['resolution'] = 'unresolved'; value['relations'].append(relation)
            result = project_lineage(value)
            self.assertEqual(required, PACK in result['quarantine_revision_refs'])
            self.assertEqual(1, len(result['unresolved_relations']))

    def test_superseded_old_link_and_conflicts_do_not_turn_into_active_context(self):
        for predicate in ('supersedes', 'invalidates', 'conflicts_with'):
            value = chain(); value['relations'].append(edge(OPTIONAL, FIRST, 'synthetic/example', predicate=predicate))
            result = project_lineage(value)
            self.assertIn(FIRST, result['quarantine_revision_refs']); self.assertIn(PACK, result['quarantine_revision_refs'])
            if predicate == 'conflicts_with': self.assertIn(OPTIONAL, result['quarantine_revision_refs'])
            self.assertEqual([], result['cycle_revision_refs'])

    def test_cycles_are_reported_and_stop_without_recursing_forever(self):
        value = chain(); value['relations'].append(edge(FIRST, SECOND, 'synthetic/dependent'))
        result = project_lineage(value)
        self.assertEqual([SECOND, FIRST], result['cycle_revision_refs'])
        self.assertIn(PACK, result['quarantine_revision_refs'])
        value['relations'][-1]['required'] = False
        result = project_lineage(value)
        self.assertEqual([], result['cycle_revision_refs'])
        self.assertEqual([SECOND, FIRST], result['optional_cycle_revision_refs'])

    def test_depth_exhaustion_quarantines_all_and_never_claims_complete_impact(self):
        value = chain(); result = project_lineage(value, budget={'max_depth': 1})
        self.assertFalse(result['complete']); self.assertIn(OPTIONAL, result['quarantine_revision_refs'])
        result = compare_lineage(value, value, invalidation_keys=[KEY], budget={'max_depth': 1})
        self.assertEqual('BUDGET_EXCEEDED', result['status']); self.assertIn(OPTIONAL, result['quarantine_revision_refs'])
        for budget in ({'max_nodes': 1}, {'max_edges': 1}, {'max_depth': True}, {'unknown': 1}, []):
            with self.assertRaises(KnowledgeBaseError): project_lineage(value, budget=budget)

    def test_metadata_only_relation_change_has_impact_and_receipt_is_bound(self):
        before = chain(); after = copy.deepcopy(before); after['relations'][-1]['required'] = True
        impact = compare_lineage(before, after)
        self.assertIn(OPTIONAL, impact['affected_revision_refs'])
        body = {key: value for key, value in impact.items() if key != 'receipt_sha256'}
        self.assertEqual(digest(body), impact['receipt_sha256'])
        body['status'] = 'NO_CHANGE'; self.assertNotEqual(digest(body), impact['receipt_sha256'])

    def test_external_refs_cannot_resolve_by_colliding_with_a_known_source_ref(self):
        value = chain(); relation = value['relations'][0]
        relation.update(predicate='governed_by', target_kind='policy', target_id='ref/policy/synthetic')
        result = project_lineage(value)
        self.assertIn(PACK, result['quarantine_revision_refs']); self.assertEqual(1, len(result['unresolved_relations']))

    def test_explicit_unresolved_parent_is_reported_and_quarantined_on_noop(self):
        value = chain()
        value['concepts'][0].update(parent_revision_ref='ref/concept-revision/missing-parent', parent_resolution='external_unresolved')
        result = project_lineage(value)
        self.assertEqual(['ref/concept-revision/missing-parent'], result['unresolved_parent_revision_refs'])
        self.assertIn(PACK, result['quarantine_revision_refs'])
        result = compare_lineage(value, value)
        self.assertEqual('NO_CHANGE', result['status']); self.assertIn(PACK, result['quarantine_revision_refs'])

    def test_cli_emits_bound_index_noop_and_invalidation_receipts(self):
        example = ROOT / 'examples/knowledge-lineage/snapshot.json'
        cli = ROOT / 'tools/knowledge_lineage.py'
        args = [sys.executable, str(cli)]
        for command in ('index', 'impact'):
            extra = [] if command == 'index' else ['--before', str(example)]
            result = subprocess.run(args + [command, '--snapshot', str(example)] + extra,
                                    capture_output=True, text=True, encoding='utf-8', timeout=20)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout); self.assertFalse(payload['projection']['serving_authorized'])
            if command == 'impact': self.assertEqual('NO_CHANGE', payload['projection']['status'])
        result = subprocess.run(args + ['impact', '--snapshot', str(example), '--before', str(example),
                                        '--invalidation-key', KEY], capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(1, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual('NEEDS_RESOLUTION', payload['status']); self.assertIn(PACK, payload['projection']['quarantine_revision_refs'])


if __name__ == '__main__':
    unittest.main()
