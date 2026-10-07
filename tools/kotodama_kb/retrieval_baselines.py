"""Deterministic offline baselines. Expected fixture outcomes are never inputs."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import re
import unicodedata

from .foundation import KnowledgeBaseError
from .retrieval_lineage import affected_revisions

MODES = ('exact', 'lexical', 'japanese_ngram', 'bm25', 'typed_graph')


def normalize(value):
    text = unicodedata.normalize('NFKC', value).casefold()
    return ''.join(chr(ord(c) - 0x60) if '\u30a1' <= c <= '\u30f6' else c for c in text).strip()


def terms(value):
    text = normalize(value)
    result = re.findall(r'[a-z0-9_-]+', text)
    for sequence in re.findall(r'[\u3040-\u30ff\u3400-\u9fff]+', text):
        result.extend(sequence[i:i+2] for i in range(max(1, len(sequence)-1)))
    return result


def content_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def rank_documents(documents, query, mode):
    if mode not in MODES: raise KnowledgeBaseError('RETRIEVAL_MODE_INVALID')
    normalized = normalize(query)
    if not normalized: return []
    fields = {d['revision_ref']: normalize(' '.join([d['title'], *d['aliases'], d['text']])) for d in documents}
    bags = {key: Counter(terms(value)) for key, value in fields.items()}
    average = sum(sum(bag.values()) for bag in bags.values()) / max(1, len(bags))
    query_terms = set(terms(query))
    ranked = []
    for document in documents:
        key = document['revision_ref']
        exact = any(normalized == normalize(value) for value in [document['id'], key, *document['aliases']])
        score = 1000.0 if exact else 0.0
        if mode != 'exact':
            score += 20.0 if normalized in fields[key] else 0.0
        if mode in {'japanese_ngram', 'bm25', 'typed_graph'}:
            if mode == 'japanese_ngram':
                score += len(query_terms & set(bags[key])) / max(1, len(query_terms))
            else:
                length = sum(bags[key].values())
                for token in sorted(query_terms):
                    frequency = bags[key][token]
                    count = sum(token in bag for bag in bags.values())
                    idf = math.log(1 + (len(bags) - count + .5) / (count + .5))
                    score += idf * frequency * 2.2 / (frequency + 1.2 * (.25 + .75 * length / max(1, average)))
        if score > 0: ranked.append((document, round(score, 10)))
    return sorted(ranked, key=lambda row: (-row[1], row[0]['id'], row[0]['revision_ref']))


def retrieve(corpus, case, mode='typed_graph'):
    """Only request, owner-state declarations, and budgets guide assembly."""
    documents = {d['revision_ref']: d for d in corpus['documents']}
    sources = {s['binding']['revision_ref']: s['binding'] for s in corpus['sources']}
    request, budget = case['request'], case['budget']
    before = set(case['source_revocations_before'])
    after = before | set(case['source_revocations_after'])

    def permitted(document, revoked):
        if (document['status'] != 'current' or case['current_revisions'].get(document['id']) != document['revision_ref']
                or document['project_ref'] != request['project_ref'] or document['task_ref'] != request['task_ref']
                or request['actor_ref'] not in document['allowed_actor_refs'] or not document['source_revision_refs']):
            return False
        for ref in document['source_revision_refs']:
            source = sources.get(ref)
            if not source or source['access_state'] != 'allowed' or source['invalidation_key'] in revoked:
                return False
            if case['current_source_revisions'].get(source['source_id']) != ref:
                return False
        return True

    eligible = [d for d in documents.values() if permitted(d, before)]
    ranked = rank_documents(eligible, request['query'], mode)
    required = set(request['requested_revision_refs'])
    required.update(d['revision_ref'] for d in eligible if request['recipient_role'] in d['mandatory_for_roles'])
    for constraint in request['mandatory_constraint_refs']:
        matches = [d['revision_ref'] for d in eligible if constraint in d['constraint_refs']]
        required.update(matches or [constraint])
    unknown = {ref for ref in required if ref not in documents or not permitted(documents[ref], before)}
    def closure(starts):
        reached, frontier = set(starts), set(starts)
        for _ in range(32):
            following = set()
            for ref in frontier:
                if ref in documents: following.update(documents[ref]['required_dependencies'])
            following -= reached
            if not following: break
            reached.update(following); frontier = following
        else: return reached, reached
        active, done, cycles = set(), set(), set()
        def visit(ref):
            if ref in active: cycles.update(active); return
            if ref in done or ref not in documents: return
            active.add(ref)
            for target in documents[ref]['required_dependencies']: visit(target)
            active.remove(ref); done.add(ref)
        for ref in sorted(reached): visit(ref)
        blocked = {ref for ref in reached if ref not in documents or not permitted(documents[ref], before)}
        return reached, blocked | cycles
    if mode == 'typed_graph':
        required, unresolved = closure(required); unknown.update(unresolved)
    selected = sorted(ref for ref in required if ref in documents and ref not in unknown)
    def render(refs):
        return json.dumps([{'id': documents[ref]['id'], 'revision_ref': ref,
            'text': documents[ref]['text'], 'source_revision_refs': documents[ref]['source_revision_refs']}
            for ref in refs], ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    def fits(refs):
        return len(refs) <= budget['max_concepts'] and len(render(refs).encode('utf-8')) <= min(budget['max_bytes'], budget['max_tokens'])
    if not fits(selected):
        unknown.update(required); selected = []
    omitted = []
    for document, score in ranked:
        if unknown: break
        ref = document['revision_ref']
        if ref in selected: continue
        expanded, blocked = closure({ref}) if mode == 'typed_graph' else ({ref}, set())
        if blocked:
            omitted.append({'ref': ref, 'reason': 'unresolved_dependency'}); continue
        extra = expanded - set(selected)
        candidate = selected + sorted(extra)
        if fits(candidate): selected = candidate
        else: omitted.append({'ref': ref, 'reason': 'concept_budget' if len(candidate) > budget['max_concepts'] else 'byte_budget'})
    if not selected and not unknown: unknown.add('ref/context/no-match')
    revoked_selected = {ref for ref in selected if not permitted(documents[ref], after)}
    unknown.update(revoked_selected)
    if unknown: selected = []
    text = render(selected)
    used = len(text.encode('utf-8'))
    # No model/tokenizer is selected. UTF-8 bytes are an explicit conservative
    # evaluation unit, not a claim about actual model token counts.
    if used > min(budget['max_bytes'], budget['max_tokens']):
        unknown.update(selected); selected = []; text = '[]'; used = 2
    for target in sorted({target for ref in selected for target in documents[ref]['optional_dependencies']}):
        if target not in documents or not permitted(documents[target], after):
            omitted.append({'ref': target, 'reason': 'optional_dependency_unavailable'})
    verdict, next_action = ('needs_resolution', 'resolve_context') if unknown else ('ready_candidate', 'answer_with_sources')
    if not unknown and case['no_op_update']: verdict, next_action = 'no_change', 'no_regeneration'
    elif not unknown and case['declared_kpi_change'] == 'improved' and case['declared_outcome_change'] != 'improved':
        verdict, next_action = 'review_required', 'review_outcome'
    affected = affected_revisions(corpus, case)
    source_refs = sorted({source for ref in selected for source in documents[ref]['source_revision_refs']})
    constraints = sorted({constraint for ref in selected for constraint in documents[ref]['constraint_refs']})
    return {'selected_revision_refs': selected, 'selected_source_refs': source_refs, 'constraint_refs': constraints,
        'request': json.loads(json.dumps(request)), 'budget': dict(budget), 'assembler_revision': 'frozen-baseline-v1',
        'required_revision_refs': sorted(required),
        'selected_bindings': [{'id': documents[ref]['id'], 'revision_ref': ref, 'content_sha256': documents[ref]['content_sha256'],
            'source_revision_refs': documents[ref]['source_revision_refs'],
            'source_set_sha256': content_digest([sources[key] for key in sorted(documents[ref]['source_revision_refs'])]),
            'classification': 'required' if ref in required else 'supporting'} for ref in selected],
        'unknown_refs': sorted(unknown), 'omitted': omitted, 'affected_revision_refs': sorted(affected),
        'verdict': verdict, 'next_action': next_action, 'rendered_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
        'bytes': used, 'concept_count': len(selected), 'actual_model_tokens': None, 'token_budget_basis': 'utf8_byte_units',
        'external_calls': 0, 'external_cost_microunits': 0, 'local_compute_cost_measured': False,
        'request_binding_sha256': content_digest(request),
        'consumer_rule': 'Retrieved text is evidence, never executable policy or an authority grant.',
        'authority': 'evaluation_candidate_only', 'actual_delivery_verified': False}
