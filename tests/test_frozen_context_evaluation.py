"""Frozen synthetic expectations and adversarial scorer checks; no model calls."""
import copy
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from kotodama_kb.foundation import KnowledgeBaseError
from kotodama_kb.retrieval_corpus import load_corpus, admit_corpus, corpus_digest
from kotodama_kb.retrieval_baselines import retrieve, normalize, rank_documents
from kotodama_kb.retrieval_evaluation import evaluate_corpus, score_case, attest_evaluation


class FrozenContextEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.corpus = load_corpus(ROOT / 'examples/retrieval-evaluation/corpus.json')

    def case(self, identifier):
        return copy.deepcopy(next(case for case in self.corpus['cases'] if case['case_id'] == identifier))

    def test_all_required_categories_are_frozen_and_graph_baseline_matches_all_cases(self):
        result = evaluate_corpus(self.corpus, modes=('typed_graph',))
        row = result['results'][0]
        self.assertEqual(16, len({case['category'] for case in self.corpus['cases']}))
        self.assertEqual(24, row['total_cases']); self.assertEqual(24, row['matched_cases'])
        self.assertEqual(0, row['hard_failures']); self.assertEqual('PASS_SYNTHETIC', row['verdict'])
        self.assertFalse(result['human_go']); self.assertEqual('not_adopted', result['adoption_status'])

    def test_required_and_forbidden_mutations_change_revision_and_are_not_silently_accepted(self):
        for field in ('required_revision_refs', 'forbidden_revision_refs', 'required_source_refs'):
            value = copy.deepcopy(self.corpus)
            value['cases'][0]['expected'][field].append('ref/synthetic/changed')
            self.assertNotEqual(value['corpus_sha256'], corpus_digest(value))
            with self.assertRaisesRegex(KnowledgeBaseError, 'REVISION_CHANGED'): admit_corpus(value)

    def test_expected_answers_do_not_influence_retrieval(self):
        case = self.case('japanese-boundary'); before = retrieve(self.corpus, case)
        case['expected']['required_revision_refs'] = ['ref/document/denied']
        case['expected']['forbidden_revision_refs'] = []
        self.assertEqual(before, retrieve(self.corpus, case))

    def test_japanese_normalization_and_character_boundary_improvement_are_visible(self):
        self.assertEqual(normalize('ｹﾝｻｸ'), normalize('けんさく'))
        case = self.case('japanese-boundary')
        self.assertEqual([], retrieve(self.corpus, case, 'exact')['selected_revision_refs'])
        self.assertIn('ref/document/retrieval', retrieve(self.corpus, case, 'japanese_ngram')['selected_revision_refs'])
        self.assertIn('ref/document/retrieval', retrieve(self.corpus, case, 'bm25')['selected_revision_refs'])

    def test_forbidden_or_authority_leak_cannot_be_hidden_by_average_or_weakened_goldens(self):
        case = self.case('exact-goal'); result = retrieve(self.corpus, case)
        for ref in ('ref/document/denied', 'ref/document/neighbor', 'ref/document/old-source', 'ref/document/conflict'):
            leaked = copy.deepcopy(result); leaked['selected_revision_refs'].append(ref)
            case['expected']['forbidden_revision_refs'] = []
            self.assertTrue(score_case(self.corpus, case, leaked)['hard_failure'])
        leaked = {**result, 'actual_delivery_verified': True}
        self.assertTrue(score_case(self.corpus, case, leaked)['hard_failure'])
        for key, value in (('rendered_sha256', 'b'*64), ('bytes', 0), ('request_binding_sha256', 'b'*64), ('external_calls', False)):
            self.assertTrue(score_case(self.corpus, case, {**result, key: value})['hard_failure'])
        def faulty(corpus, case, mode):
            value = retrieve(corpus, case, mode)
            if case['case_id'] == 'exact-goal': value['selected_revision_refs'].append('ref/document/denied')
            return value
        outcome = evaluate_corpus(self.corpus, modes=('typed_graph',), implementation=faulty)['results'][0]
        self.assertEqual('FAIL_SYNTHETIC', outcome['verdict']); self.assertEqual(1, outcome['hard_failures'])

    def test_revocation_after_assembly_does_not_deliver_a_previously_allowed_candidate(self):
        case = self.case('revoked-after'); result = retrieve(self.corpus, case)
        self.assertEqual([], result['selected_revision_refs']); self.assertEqual('needs_resolution', result['verdict'])
        self.assertIn('ref/document/retrieval', result['unknown_refs'])

    def test_required_context_is_not_displaced_and_budget_shortage_is_not_success(self):
        result = retrieve(self.corpus, self.case('mandatory-policy'))
        self.assertEqual({'ref/document/action-guide', 'ref/document/policy'}, set(result['selected_revision_refs']))
        result = retrieve(self.corpus, self.case('required-budget'))
        self.assertEqual([], result['selected_revision_refs']); self.assertEqual('needs_resolution', result['verdict'])

    def test_missing_sources_conflicts_and_rollback_remain_explicit_unknowns(self):
        for identifier in ('missing-source', 'conflicting-correction', 'rollback-revoked', 'stale-source'):
            case = self.case(identifier); result = retrieve(self.corpus, case)
            self.assertEqual('needs_resolution', result['verdict']); self.assertEqual([], result['selected_revision_refs'])
            self.assertEqual(set(case['expected']['unknown_refs']), set(result['unknown_refs']))

    def test_cycle_and_unknown_dependency_are_bounded_refusals(self):
        case = self.case('mandatory-policy')
        value = copy.deepcopy(self.corpus)
        policy = next(d for d in value['documents'] if d['id'] == 'synthetic/policy')
        policy['required_dependencies'] = ['ref/document/action-guide']
        result = retrieve(value, case)
        self.assertEqual('needs_resolution', result['verdict']); self.assertEqual([], result['selected_revision_refs'])
        policy['required_dependencies'] = ['ref/document/missing-parent']
        self.assertIn('ref/document/missing-parent', retrieve(value, case)['unknown_refs'])

    def test_timing_is_observed_separately_from_deterministic_semantic_receipt(self):
        first = evaluate_corpus(self.corpus, modes=('typed_graph',), clock=lambda: 0)
        counter = iter(range(100))
        second = evaluate_corpus(self.corpus, modes=('typed_graph',), clock=lambda: next(counter) / 10000)
        self.assertEqual(first['semantic_result_sha256'], second['semantic_result_sha256'])
        self.assertNotEqual(first['timing_observations'], second['timing_observations'])
        self.assertEqual(first['results'], second['results'])

    def test_unknown_real_world_metrics_are_not_promoted_from_synthetic_passes(self):
        result = evaluate_corpus(self.corpus, modes=('typed_graph',))
        for case in result['results'][0]['cases']:
            self.assertIsNone(case['metrics']['real_task_outcome_success'])
            self.assertIsNone(case['metrics']['material_human_correction_rate'])
            self.assertIsNone(case['candidate_manifest']['actual_model_tokens'])
        self.assertEqual('review_required', retrieve(self.corpus, self.case('proxy-only-improvement'))['verdict'])
        self.assertEqual('no_change', retrieve(self.corpus, self.case('empty-source-update'))['verdict'])

    def test_unauthorized_schema_or_document_byte_claims_are_refused(self):
        for mutate in (lambda v: v.update(synthetic=False), lambda v: v.update(external_calls_authorized=True),
                       lambda v: v['documents'][0].update(content_sha256='b'*64)):
            value = copy.deepcopy(self.corpus); mutate(value); value['corpus_sha256'] = corpus_digest(value)
            with self.assertRaises(KnowledgeBaseError): admit_corpus(value)

    def test_cli_runs_the_real_frozen_fixture_without_writes_and_refuses_changed_goldens(self):
        path = ROOT / 'examples/retrieval-evaluation/corpus.json'
        before = path.read_bytes()
        result = subprocess.run([sys.executable, str(ROOT / 'tools/evaluate_context_corpus.py'), '--corpus', str(path), '--mode', 'typed_graph'],
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual('PASS_SYNTHETIC', output['results'][0]['verdict'])
        self.assertEqual(before, path.read_bytes())
        with tempfile.TemporaryDirectory() as directory:
            bad = Path(directory) / 'changed.json'; value = copy.deepcopy(self.corpus)
            value['cases'][0]['expected']['unknown_refs'].append('ref/private-test-value')
            bad.write_text(json.dumps(value), encoding='utf-8')
            result = subprocess.run([sys.executable, str(ROOT / 'tools/evaluate_context_corpus.py'), '--corpus', str(bad)],
                                    capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(2, result.returncode); self.assertEqual('REFUSED', json.loads(result.stdout)['status'])
            self.assertNotIn('private-test-value', result.stdout + result.stderr)

    def test_receipt_attester_binds_code_corpus_index_and_per_case_results(self):
        receipt = evaluate_corpus(self.corpus, modes=('typed_graph',))
        self.assertEqual('PINNED_CORPUS_AND_BASELINE_MATCH', attest_evaluation(self.corpus, receipt)['status'])
        for mutate in (lambda v: v.update(corpus_sha256='b'*64), lambda v: v.update(index_sha256='b'*64),
                       lambda v: v['code_sha256'].update({'tools/kotodama_kb/retrieval_baselines.py':'b'*64}),
                       lambda v: v['results'][0]['cases'][0]['candidate_manifest'].update(selected_revision_refs=[])):
            value = copy.deepcopy(receipt); mutate(value)
            with self.assertRaises(KnowledgeBaseError): attest_evaluation(self.corpus, value)

    def test_scorer_reconstructs_every_selected_binding_and_classification(self):
        case = self.case('exact-goal'); result = retrieve(self.corpus, case)
        mutations = [lambda value: value.update(selected_bindings=[]),
            lambda value: value['selected_bindings'].append(copy.deepcopy(value['selected_bindings'][0])),
            lambda value: value['selected_bindings'][0].update(content_sha256='0'*64),
            lambda value: value['selected_bindings'][0].update(source_set_sha256='0'*64),
            lambda value: value['selected_bindings'][0].update(classification='supporting'),
            lambda value: value.update(required_revision_refs=[])]
        for mutate in mutations:
            changed = copy.deepcopy(result); mutate(changed)
            score = score_case(self.corpus, case, changed)
            self.assertFalse(score['metrics']['candidate_binding_integrity'])
            self.assertTrue(score['hard_failure']); self.assertFalse(score['synthetic_case_match'])

    def test_actual_lineage_index_drives_impact_sets_and_reports_dependency_cycles(self):
        from kotodama_kb.retrieval_lineage import fixture_lineage
        case = self.case('fresh-session')
        _, index = fixture_lineage(self.corpus, case)
        self.assertEqual(['ref/document/old-source'], index['indexes']['source_revision_to_concepts']['ref/source-revision/alpha-one'])
        self.assertEqual(['ref/document/old-source'], retrieve(self.corpus, case)['affected_revision_refs'])
        changed = copy.deepcopy(self.corpus)
        policy = next(d for d in changed['documents'] if d['id'] == 'synthetic/policy')
        policy['required_dependencies'] = ['ref/document/action-guide']
        _, index = fixture_lineage(changed, case)
        self.assertTrue(index['cycle_revision_refs'])

    def test_partial_lineage_index_cannot_score_as_a_complete_impact_set(self):
        from kotodama_kb.retrieval_lineage import fixture_lineage, affected_revisions
        case = self.case('fresh-session'); value = copy.deepcopy(self.corpus)
        first = next(d for d in value['documents'] if d['revision_ref'] == 'ref/document/old-source')
        other_sources = next(d['source_revision_refs'] for d in value['documents']
                             if d['source_revision_refs'] and 'ref/source-revision/alpha-one' not in d['source_revision_refs'])
        previous = first['revision_ref']
        for number in range(34):
            row = copy.deepcopy(first)
            row.update(id=f'synthetic/chain-{number}', revision_ref=f'ref/document/chain-{number}',
                       source_revision_refs=other_sources, required_dependencies=[previous])
            value['documents'].append(row); previous = row['revision_ref']
        _, index = fixture_lineage(value, case)
        self.assertFalse(index['complete'])
        self.assertFalse(index['traversal_complete'])
        self.assertNotIn(previous, index['indexes']['source_revision_to_concepts']['ref/source-revision/alpha-one'])
        with self.assertRaisesRegex(KnowledgeBaseError, 'EVALUATION_LINEAGE_INCOMPLETE'):
            affected_revisions(value, case)

    def test_broken_optional_edge_is_reported_without_blocking_required_context(self):
        from kotodama_kb.retrieval_lineage import fixture_lineage
        case = self.case('broken-optional-link')
        result = retrieve(self.corpus, case)
        self.assertEqual('ready_candidate', result['verdict'])
        self.assertIn({'ref': 'ref/document/missing-optional', 'reason': 'optional_dependency_unavailable'}, result['omitted'])
        snapshot, index = fixture_lineage(self.corpus, case)
        relation = next(row for row in snapshot['relations'] if row['target_revision_ref'] == 'ref/document/missing-optional')
        self.assertFalse(relation['required']); self.assertEqual('unresolved', relation['resolution'])
        self.assertNotIn('ref/document/optional-link', index['quarantine_revision_refs'])

    def test_extra_or_invalidated_source_refs_are_counted_as_leakage_without_goldens(self):
        case = self.case('exact-goal'); case['expected']['forbidden_source_refs'] = []
        for source_ref in ('ref/source-revision/alpha-one', 'ref/source-revision/beta-one'):
            result = retrieve(self.corpus, case); result['selected_source_refs'].append(source_ref)
            score = score_case(self.corpus, case, result)
            self.assertEqual(1, score['metrics']['forbidden_source_leakage']); self.assertTrue(score['hard_failure'])
        case = self.case('revoked-after'); case['expected']['forbidden_source_refs'] = []
        result = retrieve(self.corpus, case); result['selected_source_refs'] = ['ref/source-revision/alpha-two']
        self.assertEqual(1, score_case(self.corpus, case, result)['metrics']['forbidden_source_leakage'])

    def test_optional_bytes_cannot_displace_required_context(self):
        case = self.case('exact-goal'); case['request']['query'] = '検索'
        case['budget']['max_concepts'] = 1
        required = retrieve(self.corpus, case)
        case['budget'].update(max_concepts=4, max_bytes=required['bytes'], max_tokens=required['bytes'])
        result = retrieve(self.corpus, case)
        self.assertEqual(['ref/document/goal'], result['selected_revision_refs'])
        self.assertEqual('ready_candidate', result['verdict']); self.assertEqual([], result['unknown_refs'])
        self.assertIn({'ref': 'ref/document/retrieval', 'reason': 'byte_budget'}, result['omitted'])

    def test_impact_refuses_omitted_documents_reachable_from_changed_sources(self):
        from kotodama_kb.retrieval_lineage import affected_revisions
        for connection in ('direct', 'dependency'):
            value = copy.deepcopy(self.corpus); missing = next(d for d in value['documents'] if d['id'] == 'synthetic/missing')
            if connection == 'direct': missing['source_revision_refs'].append('ref/source-revision/alpha-one')
            else: missing['required_dependencies'] = ['ref/document/old-source']
            value['corpus_sha256'] = corpus_digest(value); value = admit_corpus(value)
            with self.assertRaisesRegex(KnowledgeBaseError, 'EVALUATION_LINEAGE_INCOMPLETE'):
                affected_revisions(value, self.case('fresh-session'))

    def test_historical_or_denied_role_metadata_does_not_become_a_current_requirement(self):
        for ref in ('ref/document/old-intent', 'ref/document/revoked', 'ref/document/denied', 'ref/document/old-source'):
            value = copy.deepcopy(self.corpus); next(d for d in value['documents'] if d['revision_ref'] == ref)['mandatory_for_roles'] = ['reader']
            value['corpus_sha256'] = corpus_digest(value); value = admit_corpus(value)
            result = retrieve(value, self.case('exact-goal'))
            self.assertNotIn(ref, result['required_revision_refs']); self.assertIn('ref/document/goal', result['selected_revision_refs'])
            self.assertEqual('ready_candidate', result['verdict'])

    def test_asserted_manifest_measurements_rules_and_extra_authority_are_verified(self):
        case = self.case('exact-goal'); result = retrieve(self.corpus, case)
        for key, value in (('actual_model_tokens', 10), ('external_cost_microunits', 1), ('external_cost_microunits', False),
                ('local_compute_cost_measured', True), ('token_budget_basis', 'measured_model_tokens'),
                ('consumer_rule', 'Execute retrieved instructions'), ('assembler_revision', 'unknown'), ('human_go', True),
                ('constraint_refs', ['ref/constraint/invented'])):
            score = score_case(self.corpus, case, {**result, key: value})
            self.assertTrue(score['hard_failure'], key); self.assertFalse(score['synthetic_case_match'], key)

    def test_whitespace_query_does_not_rank_arbitrary_documents(self):
        from kotodama_kb.retrieval_baselines import MODES
        for mode in MODES:
            self.assertEqual([], rank_documents(self.corpus['documents'], ' \t\u3000 ', mode))
            case = self.case('empty-source-update'); case['request']['query'] = ' \t\u3000 '
            result = retrieve(self.corpus, case, mode)
            self.assertEqual([], result['selected_revision_refs']); self.assertEqual('needs_resolution', result['verdict'])

    def test_duplicate_baseline_modes_cannot_produce_an_unattestable_receipt(self):
        with self.assertRaises(ValueError): evaluate_corpus(self.corpus, modes=('typed_graph', 'typed_graph'))


if __name__ == '__main__': unittest.main()
