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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from kotodama_kb.foundation import KnowledgeBaseError
from kotodama_kb.revision_owner import LocalRevisionOwner
from tests.test_knowledge_lineage import fixture, rebind

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


if __name__ == '__main__':
    unittest.main()
