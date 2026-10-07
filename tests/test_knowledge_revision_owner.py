"""Synthetic local pointer ownership; no production policy or source authority."""
import copy
from contextlib import closing
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from kotodama_kb.foundation import KnowledgeBaseError
from kotodama_kb.revision_owner import LocalRevisionOwner
from tests.test_knowledge_lineage import fixture, rebind
from tests.test_knowledge_lineage_impact import edge

FIRST = 'ref/concept-revision/example-one'
SECOND = 'ref/concept-revision/example-two'
KEY = 'ref/invalidation/alpha'


def revision(ref, parent):
    value = fixture(); value['concepts'][0].update(revision_ref=ref, parent_revision_ref=parent)
    if parent is not None: value['concepts'][0]['parent_resolution'] = 'external_unresolved'
    value['relations'][0]['from_revision_ref'] = ref
    value['projections'][0]['concept_revision_refs'] = [ref]
    return value


class KnowledgeRevisionOwnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.authorizations = []; self.allow = True
        self.owner = LocalRevisionOwner(self.root / 'work/lineage.sqlite', repository_root=self.root, authorize=self.authorize)

    def authorize(self, request):
        self.authorizations.append(request)
        return self.allow

    def register_first(self):
        self.owner.register(fixture(), expected_generation=0)
        self.owner.publish(FIRST, expected_parent_ref=None, expected_generation=1)

    def test_register_publish_reopen_and_noop_preserve_local_scope(self):
        first = self.owner.register(fixture(), expected_generation=0)
        self.assertEqual(1, first['generation'])
        self.assertFalse(self.owner.register(fixture(), expected_generation=1)['changed'])
        receipt = self.owner.publish(FIRST, expected_parent_ref=None, expected_generation=1)
        self.assertFalse(receipt['company_truth_adopted']); self.assertFalse(receipt['runtime_authority'])
        reopened = LocalRevisionOwner(self.owner.database, repository_root=self.root, authorize=self.authorize)
        self.assertEqual(FIRST, reopened.current('synthetic/example')['concept']['revision_ref'])
        self.assertFalse(reopened.current('synthetic/example')['serving_authorized'])
        self.assertIsNotNone(next(r['request_sha256'] for r in self.authorizations if r['action'] == 'register'))

    def test_late_candidate_cannot_replace_a_newer_pointer_even_with_fresh_generation(self):
        self.register_first()
        self.owner.register(revision(SECOND, FIRST), expected_generation=2)
        self.owner.publish(SECOND, expected_parent_ref=FIRST, expected_generation=3)
        late = 'ref/concept-revision/late'
        self.owner.register(revision(late, FIRST), expected_generation=4)
        with self.assertRaisesRegex(KnowledgeBaseError, 'PARENT_CONFLICT'):
            self.owner.publish(late, expected_parent_ref=FIRST, expected_generation=5)
        self.assertEqual(SECOND, self.owner.current('synthetic/example')['concept']['revision_ref'])
        with self.assertRaises(KnowledgeBaseError): self.owner.publish(FIRST, expected_parent_ref=None, expected_generation=5)

    def test_generation_cas_has_one_winner_across_independent_connections(self):
        self.owner.register(fixture(), expected_generation=0)
        other = LocalRevisionOwner(self.owner.database, repository_root=self.root, authorize=self.authorize)
        def publish(owner):
            try: return owner.publish(FIRST, expected_parent_ref=None, expected_generation=1)['generation']
            except KnowledgeBaseError as exc: return str(exc)
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(publish, [self.owner, other]))
        self.assertEqual(1, results.count(2)); self.assertEqual(1, results.count('LINEAGE_OWNER_GENERATION_CONFLICT'))

    def test_mutation_requires_generation_and_literal_authorization(self):
        for bad in (None, True, -1):
            with self.assertRaises(KnowledgeBaseError): self.owner.register(fixture(), expected_generation=bad)
        self.allow = 1
        with self.assertRaisesRegex(KnowledgeBaseError, 'FORBIDDEN'): self.owner.register(fixture(), expected_generation=0)
        self.allow = True; self.assertEqual(0, self.owner.generation())

    def test_immutable_ref_conflict_rolls_back_the_whole_registration(self):
        self.register_first(); value = fixture()
        value['concepts'][0]['content_sha256'] = 'b' * 64
        with self.assertRaisesRegex(KnowledgeBaseError, 'IMMUTABLE_CONFLICT'): self.owner.register(value, expected_generation=2)
        self.assertEqual(2, self.owner.generation())
        self.assertEqual(fixture()['concepts'][0]['content_sha256'], self.owner.current('synthetic/example')['concept']['content_sha256'])

    def test_revocation_is_sticky_and_cannot_be_bypassed_by_a_new_invalidation_key(self):
        self.register_first()
        self.owner.revoke(KEY, evidence_ref='ref/evidence/revoked', expected_generation=2)
        with self.assertRaisesRegex(KnowledgeBaseError, 'ACCESS_WITHHELD'): self.owner.current('synthetic/example')
        with self.assertRaises(KnowledgeBaseError): self.owner.publish(FIRST, expected_parent_ref=None, expected_generation=3)
        changed = revision(SECOND, FIRST)
        changed['sources'][0].update(revision_ref='ref/source-revision/new-key', invalidation_key='ref/invalidation/bypass')
        changed['concepts'][0]['source_revision_refs'] = ['ref/source-revision/new-key']
        changed['relations'][0]['target_revision_ref'] = 'ref/source-revision/new-key'
        changed['projections'][0]['source_revision_refs'] = ['ref/source-revision/new-key']; rebind(changed)
        with self.assertRaisesRegex(KnowledgeBaseError, 'INVALIDATION_KEY_CHANGED'): self.owner.register(changed, expected_generation=3)
        self.assertEqual(3, self.owner.generation())

    def test_source_conflict_is_detected_across_separate_snapshots(self):
        first = fixture(); first['sources'][0].update(revision_kind='etag', revision_value='version-one'); rebind(first)
        self.owner.register(first, expected_generation=0)
        changed = copy.deepcopy(first); changed['sources'][0].update(revision_ref='ref/source-revision/alternative', content_sha256='c' * 64)
        changed['concepts'] = []; changed['relations'] = []; changed['projections'] = []
        with self.assertRaisesRegex(KnowledgeBaseError, 'SOURCE_CONFLICT'): self.owner.register(changed, expected_generation=1)
        self.assertEqual(1, self.owner.generation())

    def test_owner_store_cannot_be_placed_in_prose_or_outside_repository(self):
        for path in (self.root / 'knowledge/owner.sqlite', self.root.parent / 'outside.sqlite', self.root / 'work/../../outside.sqlite'):
            with self.assertRaisesRegex(KnowledgeBaseError, 'OWNER_PATH'):
                LocalRevisionOwner(path, repository_root=self.root, authorize=self.authorize)

    def test_unrelated_database_and_private_evidence_refs_are_not_adopted(self):
        unrelated = self.root / 'work/unrelated.sqlite'
        with closing(sqlite3.connect(unrelated)) as db, db: db.execute('CREATE TABLE existing(value TEXT)')
        with self.assertRaisesRegex(KnowledgeBaseError, 'UNRECOGNIZED_STORE'):
            LocalRevisionOwner(unrelated, repository_root=self.root, authorize=self.authorize)
        self.register_first()
        with self.assertRaisesRegex(KnowledgeBaseError, 'REFERENCE_INVALID'):
            self.owner.revoke(KEY, evidence_ref='ref/sk-private-test-value', expected_generation=2)

    def test_repository_root_alias_cannot_bypass_ancestor_link_refusal(self):
        target = self.root / 'real-repository'; target.mkdir()
        alias = self.root / 'alias-repository'
        if os.name == 'nt':
            created = subprocess.run(['cmd', '/d', '/c', 'mklink', '/J', str(alias), str(target)], capture_output=True, timeout=10)
            self.assertEqual(0, created.returncode, 'synthetic directory junction creation failed')
        else:
            alias.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(KnowledgeBaseError, 'UNSAFE_PATH'):
            LocalRevisionOwner(alias / 'work/owner.sqlite', repository_root=alias, authorize=self.authorize)
        self.assertFalse((target / 'work/owner.sqlite').exists())

    def test_external_parent_is_resolved_in_owner_and_cannot_cross_logical_ids(self):
        self.register_first()
        missing = revision(SECOND, 'ref/concept-revision/missing')
        with self.assertRaisesRegex(KnowledgeBaseError, 'RECORD_MISSING'):
            self.owner.register(missing, expected_generation=2)
        self.assertEqual(2, self.owner.generation())
        wrong = revision(SECOND, FIRST); wrong['concepts'][0]['concept_id'] = 'synthetic/other'
        with self.assertRaisesRegex(KnowledgeBaseError, 'PARENT_MISMATCH'):
            self.owner.register(wrong, expected_generation=2)
        self.assertEqual(2, self.owner.generation())

    def test_denied_initialization_creates_no_directory_or_database(self):
        for mode in ('deny', 'raise'):
            target = self.root / mode / 'nested/owner.sqlite'
            def authorize(_request):
                if mode == 'raise': raise RuntimeError('synthetic unavailable')
                return False
            with self.assertRaises(KnowledgeBaseError):
                LocalRevisionOwner(target, repository_root=self.root, authorize=authorize)
            self.assertFalse((self.root / mode).exists())

    def test_foreign_application_without_tables_is_preserved(self):
        target = self.root / 'foreign.sqlite'
        with closing(sqlite3.connect(target)) as db, db:
            db.execute('PRAGMA application_id=1234')
            db.execute('CREATE VIEW foreign_view AS SELECT 1')
        original = target.read_bytes()
        with self.assertRaisesRegex(KnowledgeBaseError, 'UNRECOGNIZED_STORE'):
            LocalRevisionOwner(target, repository_root=self.root, authorize=self.authorize)
        self.assertEqual(original, target.read_bytes())

    def test_revocation_noop_cannot_claim_different_evidence(self):
        self.register_first()
        first = self.owner.revoke(KEY, evidence_ref='ref/evidence/first', expected_generation=2)
        same = self.owner.revoke(KEY, evidence_ref='ref/evidence/first', expected_generation=3)
        self.assertFalse(same['changed']); self.assertEqual(first['revision_refs'], same['revision_refs'])
        with self.assertRaisesRegex(KnowledgeBaseError, 'REVOCATION_EVIDENCE_CONFLICT'):
            self.owner.revoke(KEY, evidence_ref='ref/evidence/second', expected_generation=3)
        self.assertEqual(3, self.owner.generation())

    def test_optional_current_conflict_is_withheld_on_publish_and_current(self):
        value = fixture()
        other = copy.deepcopy(value['concepts'][0]); other.update(concept_id='synthetic/other', revision_ref=SECOND)
        value['concepts'].append(other)
        value['relations'].append(edge(FIRST, SECOND, 'synthetic/other', required=False, predicate='conflicts_with'))
        self.owner.register(value, expected_generation=0)
        with self.assertRaisesRegex(KnowledgeBaseError, 'REVISION_WITHHELD'):
            self.owner.publish(FIRST, expected_parent_ref=None, expected_generation=1)
        # Simulate a pointer admitted by an older owner; readback must still refuse.
        with closing(sqlite3.connect(self.owner.database)) as db, db:
            db.execute('INSERT INTO pointers VALUES(?,?)', ('synthetic/example', FIRST))
        with self.assertRaisesRegex(KnowledgeBaseError, 'REVISION_WITHHELD'):
            self.owner.current('synthetic/example')

    def test_incoming_state_relation_withholds_the_target_and_its_source_consumers(self):
        for predicate in ('conflicts_with', 'supersedes', 'invalidates'):
            with self.subTest(predicate=predicate):
                owner = LocalRevisionOwner(self.root / (predicate + '.sqlite'), repository_root=self.root, authorize=self.authorize)
                value = fixture(); other = copy.deepcopy(value['concepts'][0])
                other.update(concept_id='synthetic/other', revision_ref=SECOND); value['concepts'].append(other)
                value['relations'].append(edge(FIRST, SECOND, 'synthetic/other', required=False, predicate=predicate))
                owner.register(value, expected_generation=0)
                with self.assertRaisesRegex(KnowledgeBaseError, 'REVISION_WITHHELD'):
                    owner.publish(SECOND, expected_parent_ref=None, expected_generation=1)
                with closing(sqlite3.connect(owner.database)) as db, db:
                    db.execute('INSERT INTO pointers VALUES(?,?)', ('synthetic/other', SECOND))
                with self.assertRaisesRegex(KnowledgeBaseError, 'REVISION_WITHHELD'):
                    owner.current('synthetic/other')
        source_case = fixture(); relation = source_case['relations'][0]
        relation.update(predicate='invalidates', required=False)
        self.owner.register(source_case, expected_generation=0)
        with self.assertRaisesRegex(KnowledgeBaseError, 'ACCESS_WITHHELD'):
            self.owner.publish(FIRST, expected_parent_ref=None, expected_generation=1)

    def test_shared_dependency_dag_is_checked_once_per_revision(self):
        value = fixture(); base = copy.deepcopy(value['concepts'][0]); value['concepts'] = []; value['relations'] = []; value['projections'] = []
        layers = [[(f'synthetic/layer-{layer}-{side}', f'ref/concept-revision/layer-{layer}-{side}') for side in range(2)] for layer in range(16)]
        for layer, nodes in enumerate(layers):
            for logical, ref in nodes:
                concept = copy.deepcopy(base); concept.update(concept_id=logical, revision_ref=ref)
                value['concepts'].append(concept)
                if layer + 1 < len(layers):
                    value['relations'].extend(edge(ref, target, target_id) for target_id, target in layers[layer + 1])
        self.owner.register(value, expected_generation=0)
        # Valid dependency pointers are fixture state, not timed setup work.
        with closing(sqlite3.connect(self.owner.database)) as db, db:
            db.executemany('INSERT INTO pointers VALUES(?,?)', [node for layer in layers[1:] for node in layer])
        original = self.owner._record; calls = 0
        def bounded_record(*args):
            nonlocal calls
            calls += 1
            self.assertLessEqual(calls, 100, 'dependency traversal revisits shared records exponentially')
            return original(*args)
        with patch.object(self.owner, '_record', side_effect=bounded_record):
            self.owner.publish(layers[0][0][1], expected_parent_ref=None, expected_generation=1)
        self.assertLessEqual(calls, 64)

    def test_cached_subtree_cannot_hide_longer_paths_or_dependency_cycles(self):
        value = fixture(); base = copy.deepcopy(value['concepts'][0]); value['relations'] = []; value['projections'] = []
        tail = [(f'synthetic/a-tail-{i}', f'ref/concept-revision/a-tail-{i}') for i in range(3)]
        long = [(f'synthetic/z-chain-{i}', f'ref/concept-revision/z-chain-{i}') for i in range(29)]
        for logical, ref in tail + long:
            concept = copy.deepcopy(base); concept.update(concept_id=logical, revision_ref=ref); value['concepts'].append(concept)
        for route in ([(base['concept_id'], FIRST)] + tail, [(base['concept_id'], FIRST)] + long + tail[:1]):
            value['relations'].extend(edge(origin[1], target[1], target[0]) for origin, target in zip(route, route[1:]))
        self.owner.register(value, expected_generation=0)
        with closing(sqlite3.connect(self.owner.database)) as db, db:
            db.executemany('INSERT INTO pointers VALUES(?,?)', tail + long)
        with self.assertRaisesRegex(KnowledgeBaseError, 'DEPENDENCY_CYCLE_OR_LIMIT'):
            self.owner.publish(FIRST, expected_parent_ref=None, expected_generation=1)
        self.assertEqual(1, self.owner.generation())
        cyclic = revision(SECOND, FIRST)
        cyclic['relations'].append(edge(SECOND, SECOND, 'synthetic/example'))
        self.owner.register(cyclic, expected_generation=1)
        with self.assertRaisesRegex(KnowledgeBaseError, 'DEPENDENCY_CYCLE_OR_LIMIT'):
            self.owner.publish(SECOND, expected_parent_ref=FIRST, expected_generation=2)


if __name__ == '__main__':
    unittest.main()
