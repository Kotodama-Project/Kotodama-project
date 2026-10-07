"""Local reference owner for revision pointers, separate from prose/Company truth.

The caller supplies the existing authorization boundary. SQLite here is a local
reference implementation, not selection of a production database or policy.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import stat

from jsonschema import Draft202012Validator
from .foundation import KnowledgeBaseError, _read_json
from .lineage_contract import SCHEMA_PATH, admit_snapshot, canonical, digest

MAX_RECORDS = 4096


class LocalRevisionOwner:
    def __init__(self, database: Path, *, repository_root: Path, authorize):
        if not callable(authorize):
            raise KnowledgeBaseError('LINEAGE_OWNER_AUTHORIZER_REQUIRED')
        original_root = Path(repository_root).absolute()
        database = Path(database).absolute()
        self._reject_ancestor_links(original_root)
        self._reject_ancestor_links(database)
        root = original_root.resolve()
        resolved = database.resolve()
        if not resolved.is_relative_to(root) or resolved.is_relative_to(root / 'knowledge'):
            raise KnowledgeBaseError('LINEAGE_OWNER_PATH')
        self.root, self.original_root, self.database, self.authorize = root, original_root, database, authorize
        self._safe_path()
        database.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction('initialize', (), None) as db:
            application = db.execute('PRAGMA application_id').fetchone()[0]
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if application != 0x4B544C4E and tables:
                raise KnowledgeBaseError('LINEAGE_OWNER_UNRECOGNIZED_STORE')
            if application == 0x4B544C4E and db.execute('PRAGMA user_version').fetchone()[0] != 1:
                raise KnowledgeBaseError('LINEAGE_OWNER_STORE_VERSION')
            db.execute('PRAGMA application_id=1263815758')
            db.execute('PRAGMA user_version=1')
            db.execute('CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1),generation INTEGER NOT NULL)')
            db.execute('INSERT OR IGNORE INTO state VALUES(1,0)')
            db.execute('CREATE TABLE IF NOT EXISTS records(ref TEXT PRIMARY KEY,kind TEXT NOT NULL,logical_id TEXT NOT NULL,body TEXT NOT NULL,sha256 TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS pointers(logical_id TEXT PRIMARY KEY,revision_ref TEXT NOT NULL REFERENCES records(ref))')
            db.execute('CREATE TABLE IF NOT EXISTS invalidations(key TEXT PRIMARY KEY,evidence_ref TEXT NOT NULL,generation INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS events(generation INTEGER PRIMARY KEY,action TEXT NOT NULL,receipt TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS source_keys(source_id TEXT PRIMARY KEY,invalidation_key TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS source_versions(source_id TEXT NOT NULL,kind TEXT NOT NULL,value TEXT NOT NULL,sha256 TEXT NOT NULL,PRIMARY KEY(source_id,kind,value))')

    def _safe_path(self):
        self._reject_ancestor_links(self.original_root)
        self._reject_ancestor_links(self.database)
        resolved = self.database.resolve()
        if not resolved.is_relative_to(self.root) or resolved.is_relative_to(self.root / 'knowledge'):
            raise KnowledgeBaseError('LINEAGE_OWNER_UNSAFE_PATH')
        if self.database.exists():
            info = self.database.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise KnowledgeBaseError('LINEAGE_OWNER_UNSAFE_PATH')
        for suffix in ('-journal', '-wal', '-shm'):
            sidecar = self.database.with_name(self.database.name + suffix)
            if sidecar.is_symlink() or sidecar.exists() and (not sidecar.is_file() or sidecar.stat().st_nlink != 1):
                raise KnowledgeBaseError('LINEAGE_OWNER_UNSAFE_PATH')

    @staticmethod
    def _reject_ancestor_links(candidate):
        # Inspect the original path before resolve: a linked repository root
        # would otherwise disappear from a canonical-root-relative traversal.
        for path in (candidate, *candidate.parents):
            if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
                raise KnowledgeBaseError('LINEAGE_OWNER_UNSAFE_PATH')

    @contextmanager
    def _transaction(self, action, refs, expected_generation, request_digest=None):
        self._safe_path()
        db = None
        try:
            db = sqlite3.connect(self.database, timeout=2.0, isolation_level=None)
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='state'").fetchone()
            generation = db.execute('SELECT generation FROM state WHERE id=1').fetchone()[0] if exists else 0
            if expected_generation is not None and (type(expected_generation) is not int or generation != expected_generation):
                raise KnowledgeBaseError('LINEAGE_OWNER_GENERATION_CONFLICT')
            try:
                allowed = self.authorize({'action': action, 'revision_refs': sorted(refs), 'generation': generation,
                                          'request_sha256': request_digest})
            except Exception as exc:
                raise KnowledgeBaseError('LINEAGE_OWNER_AUTHORIZATION_UNAVAILABLE') from exc
            if allowed is not True:
                raise KnowledgeBaseError('LINEAGE_OWNER_FORBIDDEN')
            yield db
            self._safe_path()
            db.execute('COMMIT')
        except sqlite3.DatabaseError as exc:
            raise KnowledgeBaseError('LINEAGE_OWNER_STORE_UNAVAILABLE') from exc
        finally:
            if db is not None:
                db.close()  # Rolls back any transaction not committed above.

    @staticmethod
    def _receipt(db, action, refs, *, changed):
        generation = db.execute('SELECT generation FROM state WHERE id=1').fetchone()[0]
        if changed:
            generation += 1
            db.execute('UPDATE state SET generation=? WHERE id=1', (generation,))
        receipt = {'kind': 'kotodama.local-revision-receipt', 'action': action, 'generation': generation,
                   'revision_refs': sorted(refs), 'changed': changed, 'authority': 'local_revision_pointer_only',
                   'company_truth_adopted': False, 'runtime_authority': False, 'human_go': False}
        receipt['receipt_sha256'] = digest(receipt)
        if changed:
            db.execute('INSERT INTO events VALUES(?,?,?)', (generation, action, json.dumps(receipt, sort_keys=True)))
        return receipt

    def generation(self):
        with self._transaction('read_generation', (), None) as db:
            return db.execute('SELECT generation FROM state WHERE id=1').fetchone()[0]

    @staticmethod
    def _record(db, ref, kind=None):
        row = db.execute('SELECT kind,body,sha256 FROM records WHERE ref=?', (ref,)).fetchone()
        if row is None or kind is not None and row[0] != kind:
            raise KnowledgeBaseError('LINEAGE_OWNER_RECORD_MISSING')
        record = json.loads(row[1])
        if digest(record) != row[2]:
            raise KnowledgeBaseError('LINEAGE_OWNER_RECORD_CORRUPT')
        return record

    def register(self, value, *, expected_generation):
        self._expected_generation(expected_generation)
        snapshot = admit_snapshot(value)
        records = [(source['revision_ref'], 'source', source['source_id'], source) for source in snapshot['sources']]
        for concept in snapshot['concepts']:
            record = {'concept': concept, 'relations': [r for r in snapshot['relations'] if r['from_revision_ref'] == concept['revision_ref']]}
            records.append((concept['revision_ref'], 'concept', concept['concept_id'], record))
        with self._transaction('register', [r[0] for r in records], expected_generation, digest(snapshot)) as db:
            changed = False
            for source in snapshot['sources']:
                key = db.execute('SELECT invalidation_key FROM source_keys WHERE source_id=?', (source['source_id'],)).fetchone()
                if key is not None and key != (source['invalidation_key'],):
                    raise KnowledgeBaseError('LINEAGE_OWNER_INVALIDATION_KEY_CHANGED')
                db.execute('INSERT OR IGNORE INTO source_keys VALUES(?,?)', (source['source_id'], source['invalidation_key']))
                version = (source['source_id'], source['revision_kind'], source['revision_value'])
                previous = db.execute('SELECT sha256 FROM source_versions WHERE source_id=? AND kind=? AND value=?', version).fetchone()
                if previous is not None and previous != (source['content_sha256'],):
                    raise KnowledgeBaseError('LINEAGE_OWNER_SOURCE_CONFLICT')
                db.execute('INSERT OR IGNORE INTO source_versions VALUES(?,?,?,?)', (*version, source['content_sha256']))
            for ref, kind, logical, body in records:
                fingerprint = digest(body)
                old = db.execute('SELECT kind,logical_id,sha256 FROM records WHERE ref=?', (ref,)).fetchone()
                if old:
                    if old != (kind, logical, fingerprint):
                        raise KnowledgeBaseError('LINEAGE_OWNER_IMMUTABLE_CONFLICT')
                    self._record(db, ref, kind)
                    continue
                if db.execute('SELECT COUNT(*) FROM records').fetchone()[0] >= MAX_RECORDS:
                    raise KnowledgeBaseError('LINEAGE_OWNER_CAPACITY')
                db.execute('INSERT INTO records VALUES(?,?,?,?,?)', (ref, kind, logical, json.dumps(canonical(body), sort_keys=True), fingerprint))
                changed = True
            for concept in snapshot['concepts']:
                parent_ref = concept['parent_revision_ref']
                if parent_ref is not None:
                    parent = self._record(db, parent_ref, 'concept')['concept']
                    if parent['concept_id'] != concept['concept_id']:
                        raise KnowledgeBaseError('LINEAGE_OWNER_PARENT_MISMATCH')
            for source in snapshot['sources']:
                if source['access_state'] != 'allowed':
                    inserted = db.execute('INSERT OR IGNORE INTO invalidations VALUES(?,?,?)',
                                          (source['invalidation_key'], source['access_policy_ref'], expected_generation + 1)).rowcount
                    changed |= bool(inserted)
            return self._receipt(db, 'register', [r[0] for r in records], changed=changed)

    def _eligible(self, db, revision_ref, active=None):
        active = set() if active is None else active
        if revision_ref in active or len(active) >= 32:
            raise KnowledgeBaseError('LINEAGE_OWNER_DEPENDENCY_CYCLE_OR_LIMIT')
        active.add(revision_ref)
        record = self._record(db, revision_ref, 'concept'); concept = record['concept']
        if concept['parent_revision_ref'] is not None:
            parent = self._record(db, concept['parent_revision_ref'], 'concept')['concept']
            if parent['concept_id'] != concept['concept_id']:
                raise KnowledgeBaseError('LINEAGE_OWNER_PARENT_MISMATCH')
        if concept['status'] != 'candidate':
            raise KnowledgeBaseError('LINEAGE_OWNER_REVISION_WITHHELD')
        for source_ref in concept['source_revision_refs']:
            source = self._record(db, source_ref, 'source')
            if source['access_state'] != 'allowed' or db.execute('SELECT 1 FROM invalidations WHERE key=?', (source['invalidation_key'],)).fetchone():
                raise KnowledgeBaseError('LINEAGE_OWNER_ACCESS_WITHHELD')
        for relation in record['relations']:
            if not relation['required']:
                continue
            if relation['resolution'] != 'resolved' or relation['validity'] != 'current':
                raise KnowledgeBaseError('LINEAGE_OWNER_REQUIRED_UNRESOLVED')
            if relation['target_kind'] == 'source':
                if relation['target_revision_ref'] not in concept['source_revision_refs']:
                    raise KnowledgeBaseError('LINEAGE_OWNER_REQUIRED_UNRESOLVED')
            elif relation['target_kind'] == 'concept' and relation['predicate'] not in {'supersedes', 'invalidates', 'conflicts_with'}:
                target = self._eligible(db, relation['target_revision_ref'], active)
                row = db.execute('SELECT revision_ref FROM pointers WHERE logical_id=?', (target['concept_id'],)).fetchone()
                if row != (target['revision_ref'],):
                    raise KnowledgeBaseError('LINEAGE_OWNER_DEPENDENCY_NOT_CURRENT')
            else:
                raise KnowledgeBaseError('LINEAGE_OWNER_REQUIRED_UNRESOLVED')
        active.remove(revision_ref)
        return concept

    def publish(self, revision_ref, *, expected_parent_ref, expected_generation):
        self._expected_generation(expected_generation)
        with self._transaction('publish', (revision_ref,), expected_generation) as db:
            concept = self._eligible(db, revision_ref)
            current = db.execute('SELECT revision_ref FROM pointers WHERE logical_id=?', (concept['concept_id'],)).fetchone()
            current = current[0] if current else None
            if concept['parent_revision_ref'] != expected_parent_ref or current != expected_parent_ref:
                raise KnowledgeBaseError('LINEAGE_OWNER_PARENT_CONFLICT')
            db.execute('INSERT INTO pointers VALUES(?,?) ON CONFLICT(logical_id) DO UPDATE SET revision_ref=excluded.revision_ref',
                       (concept['concept_id'], revision_ref))
            return self._receipt(db, 'publish', (revision_ref,), changed=True)

    def revoke(self, invalidation_key, *, evidence_ref, expected_generation):
        self._expected_generation(expected_generation)
        # Reuse the closed ref rules without accepting arbitrary log/body data.
        schema = _read_json(SCHEMA_PATH)
        validator = Draft202012Validator({'$ref': '#/$defs/ref', '$defs': schema['$defs']})
        if any(not validator.is_valid(value) for value in (invalidation_key, evidence_ref)):
            raise KnowledgeBaseError('LINEAGE_OWNER_REFERENCE_INVALID')
        with self._transaction('revoke', (invalidation_key, evidence_ref), expected_generation) as db:
            known = [json.loads(row[0]) for row in db.execute("SELECT body FROM records WHERE kind='source'")]
            if not any(row['invalidation_key'] == invalidation_key for row in known):
                raise KnowledgeBaseError('LINEAGE_OWNER_INVALIDATION_UNKNOWN')
            changed = db.execute('INSERT OR IGNORE INTO invalidations VALUES(?,?,?)',
                                 (invalidation_key, evidence_ref, expected_generation + 1)).rowcount == 1
            return self._receipt(db, 'revoke', (invalidation_key, evidence_ref), changed=changed)

    def current(self, logical_id):
        with self._transaction('read_current', (logical_id,), None) as db:
            row = db.execute('SELECT revision_ref FROM pointers WHERE logical_id=?', (logical_id,)).fetchone()
            if row is None:
                raise KnowledgeBaseError('LINEAGE_OWNER_POINTER_MISSING')
            concept = self._eligible(db, row[0])
            return {'concept': concept, 'generation': db.execute('SELECT generation FROM state WHERE id=1').fetchone()[0],
                    'direct_parent_checked_in_local_owner': True,
                    'authority': 'local_revision_pointer_only', 'source_access_authenticated': False, 'serving_authorized': False}

    @staticmethod
    def _expected_generation(value):
        if type(value) is not int or value < 0:
            raise KnowledgeBaseError('LINEAGE_OWNER_GENERATION_REQUIRED')
