"""Public synthetic corpus admission before comparing retrieval algorithms."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from kotodama_kb.foundation import KnowledgeBaseError
from kotodama_kb.retrieval_corpus import load_corpus, admit_corpus, corpus_digest


class FrozenContextCorpusTests(unittest.TestCase):
    def setUp(self):
        self.corpus = load_corpus(ROOT / 'examples/retrieval-evaluation/corpus.json')

    def test_fixture_has_required_coverage_and_no_adoption_claim(self):
        self.assertEqual(24, len(self.corpus['cases']))
        self.assertEqual(16, len({case['category'] for case in self.corpus['cases']}))
        self.assertEqual(17, len(self.corpus['documents'])); self.assertEqual(3, len(self.corpus['sources']))
        self.assertFalse(self.corpus['external_calls_authorized'])
        self.assertEqual('not_adopted', self.corpus['adoption_status'])

    def test_required_forbidden_and_unknown_goldens_are_revision_bound(self):
        for field in ('required_revision_refs', 'forbidden_revision_refs', 'required_source_refs', 'unknown_refs'):
            value = copy.deepcopy(self.corpus)
            value['cases'][0]['expected'][field].append('ref/synthetic/changed')
            self.assertNotEqual(self.corpus['corpus_sha256'], corpus_digest(value))
            with self.assertRaisesRegex(KnowledgeBaseError, 'REVISION_CHANGED'): admit_corpus(value)

    def test_bytes_and_source_binding_must_agree_even_after_refreezing(self):
        for mutate in (lambda value: value['documents'][0].update(content_sha256='b'*64),
                       lambda value: value['sources'][0].update(text='different synthetic bytes')):
            value = copy.deepcopy(self.corpus); mutate(value); value['corpus_sha256'] = corpus_digest(value)
            with self.assertRaises(KnowledgeBaseError): admit_corpus(value)

    def test_duplicate_ids_scope_claims_and_missing_categories_are_refused(self):
        for mutate in (lambda value: value.update(synthetic=False),
                       lambda value: value.update(external_calls_authorized=True),
                       lambda value: value['cases'][0].update(case_id=value['cases'][1]['case_id']),
                       lambda value: value['cases'][0].update(extra='unrecognized'),
                       lambda value: value.update(cases=[case for case in value['cases'] if case['category'] != value['cases'][-1]['category']])):
            value = copy.deepcopy(self.corpus); mutate(value); value['corpus_sha256'] = corpus_digest(value)
            with self.assertRaises(KnowledgeBaseError): admit_corpus(value)

    def test_current_revision_maps_cannot_relabel_another_logical_record(self):
        value = copy.deepcopy(self.corpus)
        value['cases'][0]['current_revisions']['synthetic/wrong'] = value['documents'][0]['revision_ref']
        value['corpus_sha256'] = corpus_digest(value)
        with self.assertRaisesRegex(KnowledgeBaseError, 'CURRENT_CONCEPT_MISMATCH'): admit_corpus(value)
        value = copy.deepcopy(self.corpus)
        value['cases'][0]['current_source_revisions']['ref/source/wrong'] = value['sources'][0]['binding']['revision_ref']
        value['corpus_sha256'] = corpus_digest(value)
        with self.assertRaisesRegex(KnowledgeBaseError, 'CURRENT_SOURCE_MISMATCH'): admit_corpus(value)

    def test_admission_clones_the_fixture_and_limits_structure(self):
        admitted = admit_corpus(self.corpus); admitted['cases'][0]['request']['query'] = 'mutated'
        self.assertNotEqual(admitted['cases'][0]['request']['query'], self.corpus['cases'][0]['request']['query'])
        cyclic = {}; cyclic['child'] = cyclic
        with self.assertRaises(KnowledgeBaseError): admit_corpus(cyclic)


if __name__ == '__main__': unittest.main()
