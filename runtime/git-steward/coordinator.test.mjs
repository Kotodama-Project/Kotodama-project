import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { DatabaseSync } from 'node:sqlite';
import { Worker } from 'node:worker_threads';
import { GitSteward, Refusal } from './coordinator.mjs';
import { CloudflareSqliteStore } from './sqlite-store.mjs';
import { observeDiff } from './git-observer.mjs';

const BASE = 'a'.repeat(40), HEAD = 'b'.repeat(40), TREE = 'c'.repeat(40), DIFF = 'd'.repeat(64);
const PLAN = 'ref/principal/planner', ATTEST = 'ref/principal/attester';
const policy = overrides => ({ repository_ref: 'ref/repository/demo', coordinator_ref: PLAN, attester_ref: ATTEST,
  required_checks: [{ name: 'trusted-validation', issuer_ref: 'ref/issuer/ci' }], max_concurrent: 4,
  max_cells: 32, max_commands: 256, max_attempts: 3, max_lease_ms: 1000, max_run_ms: 3000, ...overrides });
const spec = (id = 'alpha', changes = {}) => ({ id, work_ref: `ref/work/${id}`, work_revision: 1,
  grant_ref: `ref/grant/${id}`, context_digest: 'e'.repeat(64), producer_ref: `ref/producer/${id}`,
  reviewer_ref: `ref/reviewer/${id}`, target_ref: 'refs/heads/main', base_sha: BASE,
  write_paths: [`src/${id}/`], read_paths: [], conflict_keys: [], depends_on: [], ...changes });
class MemoryStore {
  state = null;
  transaction(callback) {
    const result = callback(structuredClone(this.state));
    this.state = structuredClone(result.state); return structuredClone(result.result);
  }
}
// Real SQLite adapter for testing the documented CF synchronous storage shape.
// This is NOT a workerd/Cloudflare runtime test.
function sqliteStorage(db) {
  return {
    sql: { exec(query, ...bindings) {
      if (query.startsWith('SELECT')) return { toArray: () => db.prepare(query).all(...bindings) };
      db.prepare(query).run(...bindings); return { toArray: () => [] };
    } },
    transactionSync(callback) {
      db.exec('BEGIN IMMEDIATE');
      try { const result = callback(); db.exec('COMMIT'); return result; }
      catch (e) { db.exec('ROLLBACK'); throw e; }
    }
  };
}
let session = 0;
function setup(store = new MemoryStore(), p = policy()) {
  const agent = new GitSteward(store, p); const prefix = `s-${++session}`; let seq = 0; let now = 10;
  const send = (type, cell, fields = {}, actor = PLAN, request = undefined, at = undefined) => agent.execute(actor,
    { request_id: request ?? `${prefix}-r-${++seq}`, type, cell_id: cell, ...fields }, at ?? now++);
  const add = (id = 'alpha', changes = {}) => send('add', id, { spec: spec(id, changes) });
  const claim = (id = 'alpha', fields = {}, request) => send('claim', id, { base_sha: BASE, lease_ms: 500, ...fields }, `ref/producer/${id}`, request);
  const submit = (id = 'alpha', epoch = 1, fields = {}) => send('submit', id, { epoch, base_sha: BASE, head_sha: HEAD,
    tree_sha: TREE, diff_sha256: DIFF, changed_paths: [`src/${id}/a.js`], receipt_ref: 'ref/receipt/output', ...fields }, `ref/producer/${id}`);
  const verification = () => ({ base_sha: BASE, head_sha: HEAD, diff_sha256: DIFF, receipt_ref: 'ref/receipt/review',
    checks: [{ name: 'trusted-validation', issuer_ref: 'ref/issuer/ci', head_sha: HEAD, conclusion: 'success', receipt_ref: 'ref/receipt/check' }] });
  const verify = (id = 'alpha', fields = {}, actor) => send('verify', id, { ...verification(), ...fields }, actor ?? `ref/reviewer/${id}`);
  const integrated = (id = 'alpha', fields = {}) => send('integrated', id, { base_sha: BASE, head_sha: HEAD, merge_sha: 'f'.repeat(40), receipt_ref: 'ref/receipt/integration', ...fields }, ATTEST);
  return { agent, store, send, add, claim, submit, verify, integrated, verification, at(value) { now = value; } };
}
const rejects = (fn, code) => assert.throws(fn, e => e instanceof Refusal && e.code === code);

test('independent paths get separate immutable branch/workspace identities', () => {
  const h = setup(); h.add(); h.add('beta'); const a = h.claim(), b = h.claim('beta');
  assert.notEqual(a.epoch, b.epoch); assert.notEqual(a.branch, b.branch); assert.notEqual(a.workspace_ref, b.workspace_ref);
  assert.equal(a.merge_authorized, false); assert.equal(a.task_completed, false);
});
test('overlapping directory/file writers are excluded', () => {
  const h = setup(); h.add('alpha', { write_paths: ['src/'] }); h.add('beta'); h.claim(); rejects(() => h.claim('beta'), 'SCOPE_BUSY');
});
test('path components do not produce false prefix conflicts', () => {
  const h = setup(); h.add('alpha', { write_paths: ['src/a/'] }); h.add('beta', { write_paths: ['src/ab/'] }); h.claim(); h.claim('beta');
});
test('read/write overlap is excluded in either claim order', () => {
  for (const first of ['alpha', 'beta']) {
    const h = setup(); h.add('alpha', { read_paths: ['contract/'] }); h.add('beta', { write_paths: ['contract/api.json'] }); h.claim(first);
    rejects(() => h.claim(first === 'alpha' ? 'beta' : 'alpha'), 'SCOPE_BUSY');
  }
});
test('read-only shared dependency allows parallel work', () => {
  const h = setup(); h.add('alpha', { read_paths: ['contract/'] }); h.add('beta', { read_paths: ['contract/'] }); h.claim(); h.claim('beta');
});
test('semantic conflict key serializes nonoverlapping paths', () => {
  const h = setup(); h.add('alpha', { conflict_keys: ['ref/contract/public-api'] }); h.add('beta', { conflict_keys: ['ref/contract/public-api'] });
  h.claim(); rejects(() => h.claim('beta'), 'SCOPE_BUSY');
});
test('dependency must be integrated, not merely submitted or verified', () => {
  const h = setup(); h.add(); h.add('beta', { depends_on: ['alpha'] }); rejects(() => h.claim('beta'), 'DEPENDENCY_NOT_INTEGRATED');
  h.claim(); h.submit(); h.verify(); rejects(() => h.claim('beta'), 'DEPENDENCY_NOT_INTEGRATED'); h.integrated(); h.claim('beta');
});
test('unknown, self and forward dependency edges fail closed', () => {
  for (const depends_on of [['missing'], ['alpha']]) { const h = setup(); rejects(() => h.add('alpha', { depends_on }), 'DEPENDENCY_INVALID'); }
});
test('same Work revision cannot be silently duplicated under a different cell', () => {
  const h = setup(); h.add(); rejects(() => h.add('beta', { work_ref: 'ref/work/alpha' }), 'WORK_ALREADY_BOUND');
});
test('producer and verifier/attester cannot be the same principal', () => {
  const h = setup(); rejects(() => h.add('alpha', { reviewer_ref: 'ref/producer/alpha' }), 'REVIEWER_NOT_INDEPENDENT');
  rejects(() => h.add('alpha', { producer_ref: ATTEST }), 'ATTESTER_NOT_INDEPENDENT');
});
test('retry of same command returns current projection without another attempt', () => {
  const h = setup(); h.add(); h.claim('alpha', {}, 'same');
  const replay = h.claim('alpha', {}, 'same'); assert.equal(replay.replayed, true); assert.equal(replay.attempts, 1);
  rejects(() => h.claim('alpha', { lease_ms: 499 }, 'same'), 'IDEMPOTENCY_CONFLICT');
});
test('replaying a claim after expiry cannot resurrect lease or release scope', () => {
  const h = setup(); h.add('alpha', { write_paths: ['src/'] }); h.add('beta'); h.claim('alpha', {}, 'same'); h.at(1000);
  const replay = h.claim('alpha', {}, 'same'); assert.equal(replay.lease_usable, false); assert.equal(replay.state, 'reconciling');
  rejects(() => h.claim('beta'), 'SCOPE_BUSY'); rejects(() => h.submit(), 'LEASE_NOT_ACTIVE');
});
test('expiry + trusted stop acknowledgement allows new epoch, never old epoch', () => {
  const h = setup(); h.add(); h.claim(); h.at(1000);
  h.send('stopped', 'alpha', { epoch: 1, receipt_ref: 'ref/receipt/stopped', disposition: 'queued' }, ATTEST);
  const next = h.claim(); assert.equal(next.attempts, 2); assert.equal(next.epoch, 2);
  rejects(() => h.submit(), 'STALE_FENCE'); h.submit('alpha', 2);
});
test('unknown delivery blocks another dispatch until reconciled', () => {
  const h = setup(); h.add(); h.claim(); h.send('unknown', 'alpha', { epoch: 1 }, 'ref/producer/alpha');
  rejects(() => h.claim(), 'CELL_NOT_QUEUED'); rejects(() => h.submit(), 'LEASE_NOT_ACTIVE');
});
test('stop request is not confirmed cancellation and holds overlaps', () => {
  const h = setup(); h.add('alpha', { write_paths: ['src/'] }); h.add('beta'); h.claim(); h.send('stop', 'alpha');
  rejects(() => h.claim('beta'), 'SCOPE_BUSY');
  rejects(() => h.send('stopped', 'alpha', { epoch: 1, receipt_ref: 'ref/receipt/stop', disposition: 'cancelled' }, 'ref/producer/alpha'), 'ACTOR_FORBIDDEN');
  h.send('stopped', 'alpha', { epoch: 1, receipt_ref: 'ref/receipt/stop', disposition: 'cancelled' }, ATTEST); h.claim('beta');
});
test('stale stop receipt cannot release a newer executor', () => {
  const h = setup(); h.add(); h.claim(); h.send('stop', 'alpha');
  rejects(() => h.send('stopped', 'alpha', { epoch: 2, receipt_ref: 'ref/receipt/stop', disposition: 'queued' }, ATTEST), 'STALE_FENCE');
});
test('renewal cannot exceed total run time budget', () => {
  const h = setup(); h.add(); h.claim();
  for (const now of [400, 1200, 2000]) { h.at(now); h.send('renew', 'alpha', { epoch: 1, lease_ms: 1000 }, 'ref/producer/alpha'); }
  h.at(2800); rejects(() => h.send('renew', 'alpha', { epoch: 1, lease_ms: 1000 }, 'ref/producer/alpha'), 'RUNTIME_BUDGET');
});
test('bounded concurrent cells and attempts', () => {
  const h = setup(undefined, policy({ max_concurrent: 1, max_attempts: 1 })); h.add(); h.add('beta'); h.claim();
  rejects(() => h.claim('beta'), 'CONCURRENCY_BUDGET'); h.send('stop', 'alpha');
  h.send('stopped', 'alpha', { epoch: 1, receipt_ref: 'ref/receipt/stop', disposition: 'queued' }, ATTEST);
  rejects(() => h.claim(), 'ATTEMPT_BUDGET');
});
test('base movement refuses claim and integration assessment', () => {
  const h = setup(); h.add(); rejects(() => h.claim('alpha', { base_sha: HEAD }), 'BASE_MOVED'); h.claim(); h.submit(); h.verify();
  rejects(() => h.send('assess', 'alpha', { base_sha: HEAD, head_sha: HEAD }, ATTEST), 'BASE_MOVED');
  rejects(() => h.send('assess', 'alpha', { base_sha: BASE, head_sha: TREE }, ATTEST), 'HEAD_MOVED');
  const result = h.send('assess', 'alpha', { base_sha: BASE, head_sha: HEAD }, ATTEST); assert.equal(result.merge_authorized, false);
});
test('out-of-scope renamed/deleted paths cannot be hidden by the submitter', () => {
  const h = setup(); h.add(); h.claim(); rejects(() => h.submit('alpha', 1, { changed_paths: ['outside/a.js', 'src/alpha/a.js'] }), 'PATH_OUT_OF_SCOPE');
});
test('unsafe paths, wildcard and empty write set are rejected', () => {
  for (const write_paths of [['../secret'], ['/root'], ['src//a'], ['src\\a'], ['.git/config'], ['a/.GIT/x'], ['src/**'], []]) {
    const h = setup(); rejects(() => h.add('alpha', { write_paths }), 'INPUT_INVALID');
  }
});
test('missing, failed, skipped, stale and wrong-issuer checks do not pass', () => {
  const cases = [[], [{ name: 'trusted-validation', issuer_ref: 'ref/issuer/ci', head_sha: HEAD, conclusion: 'failure', receipt_ref: 'ref/receipt/check' }]];
  for (const variant of [{ conclusion: 'skipped' }, { head_sha: BASE }, { issuer_ref: 'ref/issuer/untrusted' }]) {
    cases.push([{ name: 'trusted-validation', issuer_ref: 'ref/issuer/ci', head_sha: HEAD, conclusion: 'success', receipt_ref: 'ref/receipt/check', ...variant }]);
  }
  for (const checks of cases) { const h = setup(); h.add(); h.claim(); h.submit(); rejects(() => h.verify('alpha', { checks }), checks.length ? 'CHECKS_NOT_TRUSTED' : 'CHECKS_INCOMPLETE'); }
});
test('self-certification and stale diff review are refused', () => {
  const h = setup(); h.add(); h.claim(); h.submit();
  rejects(() => h.verify('alpha', {}, 'ref/producer/alpha'), 'REVIEWER_NOT_INDEPENDENT');
  rejects(() => h.verify('alpha', { diff_sha256: '0'.repeat(64) }), 'DIFF_MOVED');
});
test('integrated observation requires verifier and separate attester', () => {
  const h = setup(); h.add(); h.claim(); h.submit(); rejects(() => h.integrated(), 'NOT_VERIFIED'); h.verify();
  const result = h.integrated(); assert.equal(result.state, 'integrated'); assert.equal(result.task_completed, false);
  rejects(() => h.claim(), 'CELL_NOT_QUEUED');
});
test('malformed commands, spoofed actors and unknown fields are refused', () => {
  const h = setup(); rejects(() => h.send('add', 'alpha', { spec: spec() }, 'ref/producer/alpha'), 'ACTOR_FORBIDDEN');
  h.add(); rejects(() => h.claim('alpha', { force: true }), 'INPUT_INVALID');
  rejects(() => h.agent.execute(PLAN, { request_id: 'x', cell_id: 'alpha', type: 'merge' }, 100), 'INPUT_INVALID');
  rejects(() => h.send('claim', 'alpha', { base_sha: BASE, lease_ms: true }, 'ref/producer/alpha'), 'INPUT_INVALID');
});
test('bounded journal refuses rather than pruning idempotency history', () => {
  const h = setup(undefined, policy({ max_commands: 1 })); h.add(); rejects(() => h.claim(), 'JOURNAL_FULL');
});
test('oversized and excessively nested input fail before mutation', () => {
  const h = setup(); rejects(() => h.add('alpha', { target_ref: 'x'.repeat(70000) }), 'INPUT_TOO_LARGE');
  let context_digest = {}; for (let i = 0; i < 20; i++) context_digest = { value: context_digest };
  rejects(() => h.add('alpha', { context_digest }), 'INPUT_INVALID'); assert.equal(h.store.state, null);
});
test('policy/scope drift and backwards clock refuse reopening a journal', () => {
  const h = setup(); h.add(); const changed = setup(h.store, policy({ repository_ref: 'ref/repository/other' }));
  rejects(() => changed.claim(), 'JOURNAL_BINDING_MISMATCH');
  rejects(() => h.send('claim', 'alpha', { base_sha: BASE, lease_ms: 500 }, 'ref/producer/alpha', 'earlier', 0), 'JOURNAL_INVALID');
});
test('ordinary object property names cannot alias another record', () => {
  const h = setup(); h.add('constructor'); h.claim('constructor', {}, 'constructor');
  rejects(() => h.send('stop', 'tostring'), 'CELL_UNKNOWN');
});
test('real SQLite restart retains claims, replay, fences and receipts', () => {
  const dir = mkdtempSync(join(tmpdir(), 'steward-sql-')); const path = join(dir, 'journal.db');
  try {
    let db = new DatabaseSync(path); let h = setup(new CloudflareSqliteStore(sqliteStorage(db)));
    h.add(); const before = h.claim('alpha', {}, 'claim-once'); db.close();
    db = new DatabaseSync(path); h = setup(new CloudflareSqliteStore(sqliteStorage(db))); h.at(100);
    const after = h.claim('alpha', {}, 'claim-once'); assert.equal(after.epoch, before.epoch); assert.equal(after.replayed, true);
    h.submit(); h.verify(); db.close();
    db = new DatabaseSync(path); h = setup(new CloudflareSqliteStore(sqliteStorage(db))); h.at(200); h.integrated(); db.close();
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
test('two SQLite connections see one repository-wide claim owner', () => {
  const dir = mkdtempSync(join(tmpdir(), 'steward-race-'));
  try {
    const a = new DatabaseSync(join(dir, 'journal.db')), b = new DatabaseSync(join(dir, 'journal.db'));
    const ha = setup(new CloudflareSqliteStore(sqliteStorage(a))), hb = setup(new CloudflareSqliteStore(sqliteStorage(b)));
    ha.add('alpha', { write_paths: ['src/'] }); ha.add('beta'); ha.claim(); hb.at(100);
    rejects(() => hb.claim('beta', {}, 'other-client'), 'SCOPE_BUSY'); a.close(); b.close();
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
test('SQLite rolls back rejected business changes but persists trusted observation time', () => {
  const db = new DatabaseSync(':memory:'); const h = setup(new CloudflareSqliteStore(sqliteStorage(db)));
  h.add(); const before = db.prepare('SELECT payload FROM git_steward_state').get().payload;
  rejects(() => h.claim('alpha', { base_sha: HEAD }, 'retry-after-repair'), 'BASE_MOVED');
  const after = JSON.parse(db.prepare('SELECT payload FROM git_steward_state').get().payload);
  const expected = JSON.parse(before); expected.last_now = after.last_now;
  assert.deepEqual(after, expected); assert.equal(after.last_now, 11);
  h.claim('alpha', {}, 'retry-after-repair'); db.close();
});
test('corrupt journal never silently resets coordination history', () => {
  const db = new DatabaseSync(':memory:'); const store = new CloudflareSqliteStore(sqliteStorage(db));
  db.prepare('INSERT INTO git_steward_state VALUES (1, ?)').run('{bad');
  assert.throws(() => setup(store).add(), SyntaxError);
  assert.equal(db.prepare('SELECT payload FROM git_steward_state').get().payload, '{bad'); db.close();
});
function gitFixture(callback) {
  const dir = mkdtempSync(join(tmpdir(), 'steward-git-')); const repo = join(dir, 'repo'); mkdirSync(repo);
  const env = { ...process.env, GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: '/dev/null' };
  const git = (cwd, ...args) => execFileSync('git', ['-C', cwd, ...args], { env, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
  try {
    git(repo, 'init', '-b', 'main'); git(repo, 'config', 'user.name', 'Synthetic Test'); git(repo, 'config', 'user.email', 'synthetic@example.invalid');
    mkdirSync(join(repo, 'src')); writeFileSync(join(repo, 'src', 'before.txt'), 'one\n'); git(repo, 'add', '.'); git(repo, 'commit', '-m', 'fixture');
    callback({ dir, repo, git, base: git(repo, 'rev-parse', 'HEAD') });
  } finally { rmSync(dir, { recursive: true, force: true }); }
}
test('real git worktrees isolate edits and observer binds both rename endpoints', () => gitFixture(({ dir, repo, git, base }) => {
  const a = join(dir, 'alpha'), b = join(dir, 'beta'); git(repo, 'worktree', 'add', '-b', 'work/alpha-e1', a, base); git(repo, 'worktree', 'add', '-b', 'work/beta-e2', b, base);
  git(a, 'mv', 'src/before.txt', 'src/after.txt'); git(a, 'commit', '-am', 'rename'); const head = git(a, 'rev-parse', 'HEAD');
  assert.equal(git(b, 'rev-parse', 'HEAD'), base); const result = observeDiff(a, base, head);
  assert.deepEqual(result.changed_paths, ['src/after.txt', 'src/before.txt']); assert.match(result.diff_sha256, /^[0-9a-f]{64}$/);
  assert.deepEqual(observeDiff(a, base, head), result); assert.equal(result.tree_sha, git(a, 'rev-parse', 'HEAD^{tree}'));
}));
test('real git observer refuses refs, noncommits, unrelated ancestry and empty diffs', () => gitFixture(({ repo, git, base }) => {
  rejects(() => observeDiff(repo, 'main', base), 'REVISION_INVALID');
  rejects(() => observeDiff(repo, base, git(repo, 'rev-parse', 'HEAD^{tree}')), 'NOT_COMMIT');
  rejects(() => observeDiff(repo, base, base), 'PATH_INVALID');
  git(repo, 'checkout', '--orphan', 'unrelated'); git(repo, 'commit', '-m', 'orphan');
  rejects(() => observeDiff(repo, base, git(repo, 'rev-parse', 'HEAD')), 'GIT_OBSERVATION_FAILED');
}));
test('real git rename across path scope is rejected by coordination core', () => gitFixture(({ repo, git, base }) => {
  git(repo, 'mv', 'src/before.txt', 'outside.txt'); git(repo, 'commit', '-am', 'rename outside'); const observed = observeDiff(repo, base, git(repo, 'rev-parse', 'HEAD'));
  const h = setup(); h.add('alpha', { base_sha: base, write_paths: ['src/'] }); h.claim('alpha', { base_sha: base });
  rejects(() => h.submit('alpha', 1, observed), 'PATH_OUT_OF_SCOPE');
}));

test('simultaneous worker threads acquire exactly one overlapping cell', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'steward-concurrent-'));
  const path = join(dir, 'journal.db');
  try {
    const db = new DatabaseSync(path); const h = setup(new CloudflareSqliteStore(sqliteStorage(db)));
    h.add('alpha', { write_paths: ['src/'] }); h.add('beta'); db.close();
    const barrier = new SharedArrayBuffer(4);
    const code = `
      const { parentPort, workerData } = require('node:worker_threads');
      (async () => {
        const { DatabaseSync } = await import('node:sqlite');
        const { GitSteward } = await import(workerData.core);
        const { CloudflareSqliteStore } = await import(workerData.store);
        const db = new DatabaseSync(workerData.path); db.exec('PRAGMA busy_timeout = 5000');
        const sqliteStorage = ${sqliteStorage.toString()};
        const agent = new GitSteward(new CloudflareSqliteStore(sqliteStorage(db)), workerData.policy);
        const flag = new Int32Array(workerData.barrier);
        Atomics.add(flag, 0, 1); Atomics.notify(flag, 0);
        while (Atomics.load(flag, 0) < 2) Atomics.wait(flag, 0, 1, 5000);
        let result;
        try { result = agent.execute('ref/producer/' + workerData.id, {
          request_id: 'race-' + workerData.id, type: 'claim', cell_id: workerData.id,
          base_sha: workerData.base, lease_ms: 500 }, 100).state; }
        catch (e) { result = e.code || e.message; }
        db.close(); parentPort.postMessage(result);
      })().catch(e => { throw e; });`;
    const run = id => new Promise((resolve, reject) => {
      const w = new Worker(code, { eval: true, workerData: { path, barrier, id, base: BASE, policy: policy(),
        core: new URL('./coordinator.mjs', import.meta.url).href, store: new URL('./sqlite-store.mjs', import.meta.url).href } });
      w.once('message', resolve); w.once('error', reject);
      w.once('exit', code => { if (code !== 0) reject(new Error(`Worker exit ${code}`)); });
    });
    assert.deepEqual((await Promise.all([run('alpha'), run('beta')])).sort(), ['SCOPE_BUSY', 'running']);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
