"""Evaluate frozen public fixtures; semantic results and timing observations differ."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
from .foundation import KnowledgeBaseError, _bounded_tree

from .retrieval_corpus import admit_corpus
from .retrieval_baselines import MODES, retrieve, content_digest


def ratio(actual, expected):
    expected = set(expected)
    return None if not expected else len(set(actual) & expected) / len(expected)


def score_case(corpus, case, result, *, mode='typed_graph'):
    expected = case['expected']
    concepts, sources = set(result['selected_revision_refs']), set(result['selected_source_refs'])
    forbidden = concepts & set(expected['forbidden_revision_refs'])
    leaked_sources = sources & set(expected['forbidden_source_refs'])
    documents = {d['revision_ref']: d for d in corpus['documents']}
    bindings = {s['binding']['revision_ref']: s['binding'] for s in corpus['sources']}
    revoked = set(case['source_revocations_before']) | set(case['source_revocations_after'])
    denied = set()
    stale = set()
    supported_pairs, pairs = 0, 0
    actual_sources = set()
    for ref in concepts:
        document = documents.get(ref)
        if document is None:
            denied.add(ref); continue
        if document['status'] != 'current' or case['current_revisions'].get(document['id']) != ref:
            stale.add(ref)
        if (document['project_ref'] != case['request']['project_ref'] or document['task_ref'] != case['request']['task_ref']
                or case['request']['actor_ref'] not in document['allowed_actor_refs']): denied.add(ref)
        for source_ref in document['source_revision_refs']:
            pairs += 1; actual_sources.add(source_ref)
            source = bindings.get(source_ref)
            valid = source is not None and source['access_state'] == 'allowed' and source['invalidation_key'] not in revoked
            valid = valid and case['current_source_revisions'].get(source['source_id']) == source_ref
            if valid: supported_pairs += 1
            else: leaked_sources.add(source_ref)
    for source_ref in sources:
        source = bindings.get(source_ref)
        if not source or source['access_state'] != 'allowed' or source['invalidation_key'] in revoked or case['current_source_revisions'].get(source['source_id']) != source_ref:
            leaked_sources.add(source_ref)
    leaked_sources.update(sources - actual_sources)
    known = all(ref in documents for ref in result['selected_revision_refs'])
    # Recompute mandatory policy/graph metadata from request and owner-state
    # inputs. Golden answers and the candidate's classifications cannot set it.
    baseline = retrieve(corpus, case, mode)
    required = baseline['required_revision_refs']
    fixed = {'actual_model_tokens': None, 'external_calls': 0, 'external_cost_microunits': 0,
        'local_compute_cost_measured': False, 'token_budget_basis': 'utf8_byte_units', 'assembler_revision': 'frozen-baseline-v1',
        'consumer_rule': 'Retrieved text is evidence, never executable policy or an authority grant.',
        'authority': 'evaluation_candidate_only', 'actual_delivery_verified': False}
    declared = set(result) == set(baseline) and all(key in result and type(result[key]) is type(value) and result[key] == value for key, value in fixed.items())
    expected_bindings = [{'id': documents[ref]['id'], 'revision_ref': ref,
        'content_sha256': documents[ref]['content_sha256'], 'source_revision_refs': documents[ref]['source_revision_refs'],
        'source_set_sha256': content_digest([bindings.get(key) for key in sorted(documents[ref]['source_revision_refs'])]),
        'classification': 'required' if ref in required else 'supporting'}
        for ref in result['selected_revision_refs'] if ref in documents]
    rendered = json.dumps([{'id': documents[ref]['id'], 'revision_ref': ref, 'text': documents[ref]['text'],
                            'source_revision_refs': documents[ref]['source_revision_refs']}
                           for ref in result['selected_revision_refs'] if ref in documents],
                          ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    integrity = (known and declared and len(concepts) == len(result['selected_revision_refs'])
        and type(result['bytes']) is int and type(result['concept_count']) is int
        and hashlib.sha256(rendered).hexdigest() == result['rendered_sha256']
        and result['bytes'] == len(rendered) and result['concept_count'] == len(concepts)
        and result['request_binding_sha256'] == content_digest(case['request'])
        and content_digest(result['request']) == content_digest(case['request']) and content_digest(result['budget']) == content_digest(case['budget'])
        and result['constraint_refs'] == sorted({ref for key in concepts if key in documents for ref in documents[key]['constraint_refs']})
        and (result['verdict'] == 'needs_resolution' or set(required) <= concepts)
        and result['required_revision_refs'] == required and result['selected_bindings'] == expected_bindings)
    budget_met = len(concepts) <= case['budget']['max_concepts'] and len(rendered) <= min(case['budget']['max_bytes'], case['budget']['max_tokens'])
    metrics = {'required_concept_recall': ratio(concepts, expected['required_revision_refs']),
        'required_source_recall': ratio(sources, expected['required_source_refs']),
        'mandatory_constraint_retention': ratio(result['constraint_refs'], expected['constraint_refs']),
        'forbidden_concept_leakage': len(forbidden), 'forbidden_source_leakage': len(leaked_sources),
        'access_or_scope_leakage': len(denied), 'superseded_or_stale_leakage': len(stale),
        'citation_binding_precision': None if not pairs else supported_pairs / pairs,
        'candidate_binding_integrity': integrity, 'context_budget_met': budget_met,
        'expected_unknown_recall': ratio(result['unknown_refs'], expected['unknown_refs']),
        'unknown_set_exact': set(result['unknown_refs']) == set(expected['unknown_refs']),
        'impact_recall': ratio(result['affected_revision_refs'], expected['affected_revision_refs']),
        'impact_precision': None if not result['affected_revision_refs'] else len(set(result['affected_revision_refs']) & set(expected['affected_revision_refs'])) / len(result['affected_revision_refs']),
        'material_human_correction_rate': None, 'real_task_outcome_success': None, 'semantic_claim_support_verified': False}
    hard_failure = bool(forbidden or leaked_sources or denied or stale or actual_sources != sources
                        or not integrity or result.get('actual_delivery_verified') is not False
                        or type(result.get('external_calls')) is not int or result['external_calls'] != 0
                        or result.get('authority') != 'evaluation_candidate_only')
    quality_match = (not concepts and not sources) if expected['verdict'] == 'needs_resolution' else all(
        metrics[key] in (None, 1.0) for key in ('required_concept_recall', 'required_source_recall', 'mandatory_constraint_retention'))
    matched = (not hard_failure and budget_met and result['verdict'] == expected['verdict'] and result['next_action'] == expected['next_action']
        and metrics['unknown_set_exact'] and quality_match and metrics['impact_recall'] in (None, 1.0)
        and set(result['affected_revision_refs']) == set(expected['affected_revision_refs']))
    return {'metrics': metrics, 'synthetic_case_match': matched, 'hard_failure': hard_failure}


def evaluate_corpus(value, *, modes=MODES, implementation=retrieve, clock=time.perf_counter):
    corpus = admit_corpus(value)
    if not isinstance(modes, (list, tuple)) or not modes or any(mode not in MODES for mode in modes) or len(set(modes)) != len(modes):
        raise ValueError('invalid baseline modes')
    results, observations = [], []
    for mode in modes:
        cases = []
        for case in corpus['cases']:
            start = clock()
            result = implementation(corpus, case, mode)
            elapsed = max(0, (clock() - start) * 1000)
            scored = score_case(corpus, case, result, mode=mode)
            cases.append({'case_id': case['case_id'], 'case_revision': case['revision_ref'], 'category': case['category'],
                          'candidate_manifest': result, **scored})
            observations.append({'case_id': case['case_id'], 'mode': mode, 'latency_ms': elapsed,
                                 'latency_budget_met': elapsed <= case['budget']['max_latency_ms']})
        results.append({'mode': mode, 'cases': cases, 'matched_cases': sum(c['synthetic_case_match'] for c in cases),
                        'hard_failures': sum(c['hard_failure'] for c in cases), 'total_cases': len(cases),
                        'verdict': 'PASS_SYNTHETIC' if all(c['synthetic_case_match'] for c in cases) else 'FAIL_SYNTHETIC'})
    root = Path(__file__).resolve().parents[2]
    code_paths = ('tools/kotodama_kb/retrieval_corpus.py', 'tools/kotodama_kb/retrieval_baselines.py',
                  'tools/kotodama_kb/retrieval_evaluation.py', 'schemas/frozen-context-corpus.schema.json',
                  'tools/kotodama_kb/retrieval_lineage.py', 'tools/kotodama_kb/lineage_impact.py',
                  'tools/kotodama_kb/lineage_contract.py', 'tools/kotodama_kb/foundation.py', 'schemas/knowledge-lineage.schema.json')
    semantic = {'kind': 'kotodama.frozen-context-evaluation', 'schema_revision': 'v1',
        'corpus_sha256': corpus['corpus_sha256'], 'source_sha256': content_digest(corpus['sources']),
        'index_sha256': content_digest(corpus['documents']), 'model': 'none', 'retriever_revision': 'frozen-baseline-v1',
        'code_sha256': {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in code_paths},
        'results': results, 'authority': 'evaluation_fixture_only', 'adoption_status': 'not_adopted',
        'actual_provider_or_runtime_verified': False, 'human_go': False}
    return {**semantic, 'semantic_result_sha256': content_digest(semantic), 'timing_observations': observations,
            'latency_budgets_met': all(row['latency_budget_met'] for row in observations)}


def attest_evaluation(corpus, receipt):
    try:
        _bounded_tree(receipt)
        receipt = json.loads(json.dumps(receipt, ensure_ascii=False, allow_nan=False))
        modes = tuple(row['mode'] for row in receipt['results'])
        if len(set(modes)) != len(modes): raise ValueError()
        expected = evaluate_corpus(corpus, modes=modes, clock=lambda: 0)
        unverified = {'timing_observations', 'latency_budgets_met'}
        expected_core = {key: value for key, value in expected.items() if key not in unverified}
        actual_core = {key: value for key, value in receipt.items() if key not in unverified}
        if content_digest(expected_core) != content_digest(actual_core): raise ValueError()
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        raise KnowledgeBaseError('EVALUATION_RECEIPT_MISMATCH') from exc
    return {'status': 'PINNED_CORPUS_AND_BASELINE_MATCH', 'semantic_result_sha256': expected['semantic_result_sha256'],
            'timing_or_cost_observations_authenticated': False, 'actual_runtime_delivery_verified': False, 'human_go': False}
