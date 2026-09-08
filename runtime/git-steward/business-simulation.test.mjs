import { test } from 'node:test';
import assert from 'node:assert/strict';
import { GitSteward, Refusal } from './coordinator.mjs';
import { runRehearsal } from './business-rehearsal.mjs';

const BASE = 'a'.repeat(40), HEAD = 'b'.repeat(40), DIFF = 'd'.repeat(64);
const PLANNER = 'ref/principal/planner';
const ATTESTER = 'ref/principal/attester';
const policy = { repository_ref: 'ref/repository/wearable', coordinator_ref: PLANNER,
  attester_ref: ATTESTER, required_checks: [{ name: 'regression', issuer_ref: 'ref/issuer/test' }],
  max_concurrent: 8, max_cells: 64, max_commands: 1024, max_attempts: 3, max_lease_ms: 1000, max_run_ms: 5000 };
class Store {
  state = null;
  transaction(callback) {
    const r = callback(structuredClone(this.state)); this.state = structuredClone(r.state); return structuredClone(r.result);
  }
}
function spec(id, changes = {}) {
  return { id, work_ref: `ref/work/${id}`, work_revision: 1, grant_ref: 'ref/grant/development',
    context_digest: 'e'.repeat(64), producer_ref: `ref/producer/${id}`, reviewer_ref: `ref/reviewer/${id}`,
    target_ref: 'refs/heads/main', base_sha: BASE, write_paths: [`src/${id}/`], read_paths: [], conflict_keys: [], depends_on: [], ...changes };
}
function harness() {
  const store = new Store(); const core = new GitSteward(store, policy); let seq = 0;
  const send = (type, id, fields = {}, at = 10, actor = PLANNER, request = undefined) => core.execute(actor,
    { request_id: request ?? `r-${++seq}`, type, cell_id: id, ...fields }, at);
  const add = (id, changes = {}, at = 10) => send('add', id, { spec: spec(id, changes) }, at);
  const claim = (id, at = 20, request = undefined) => send('claim', id, { base_sha: BASE, lease_ms: 100 }, at, `ref/producer/${id}`, request);
  const submit = (id, epoch = 1, at = 30) => send('submit', id, { epoch, base_sha: BASE, head_sha: HEAD,
    tree_sha: 'c'.repeat(40), diff_sha256: DIFF, changed_paths: [`src/${id}/change.mjs`], receipt_ref: 'ref/receipt/local' }, at, `ref/producer/${id}`);
  return { store, core, send, add, claim, submit };
}
const refuses = (fn, code) => assert.throws(fn, e => e instanceof Refusal && e.code === code);

test('a replay observation makes later backwards time invalid', () => {
  const h = harness(); h.add('mobile'); h.claim('mobile', 20, 'claim-once');
  const expired = h.claim('mobile', 200, 'claim-once'); assert.equal(expired.lease_usable, false);
  refuses(() => h.send('renew', 'mobile', { epoch: 1, lease_ms: 100 }, 30, 'ref/producer/mobile'), 'JOURNAL_INVALID');
  assert.equal(h.store.state.last_now, 200);
});

test('a correction stops the old Work even when the new paths differ', () => {
  const h = harness(); h.add('mobile', { work_ref: 'ref/work/reconnect' }); h.claim('mobile');
  h.add('audio', { work_ref: 'ref/work/reconnect', work_revision: 2, context_digest: 'f'.repeat(64) }, 25);
  refuses(() => h.submit('mobile'), 'LEASE_NOT_ACTIVE');
  refuses(() => h.claim('audio', 30), 'SCOPE_BUSY');
  h.send('stopped', 'mobile', { epoch: 1, receipt_ref: 'ref/receipt/stopped', disposition: 'cancelled' }, 31, ATTESTER);
  const next = h.claim('audio', 32); assert.equal(next.work_revision, 2);
  assert.equal(next.context_digest, 'f'.repeat(64));
  assert.equal(next.task_completed, false);
});

test('out-of-order Work revision cannot become the new current assignment', () => {
  const h = harness(); h.add('audio', { work_ref: 'ref/work/reconnect', work_revision: 2 });
  refuses(() => h.add('mobile', { work_ref: 'ref/work/reconnect', work_revision: 1 }, 11), 'WORK_REVISION_STALE');
});

test('a stopped superseded Work cannot be requeued', () => {
  const h = harness(); h.add('mobile', { work_ref: 'ref/work/reconnect' }); h.claim('mobile');
  h.add('audio', { work_ref: 'ref/work/reconnect', work_revision: 2 }, 25);
  refuses(() => h.send('stopped', 'mobile', { epoch: 1, receipt_ref: 'ref/receipt/stopped', disposition: 'queued' }, 26, ATTESTER), 'WORK_REVISION_STALE');
});

test('file-to-directory change reserves a structural conflict', () => {
  for (const [left, right] of [['src', 'src/file.mjs'], ['src/file.mjs', 'src'], ['src/', 'src']]) {
    const h = harness(); h.add('mobile', { write_paths: [left] }); h.add('audio', { write_paths: [right] });
    h.claim('mobile'); refuses(() => h.claim('audio'), 'SCOPE_BUSY');
  }
});

test('portable reservations serialize case aliases without prefix false positives', () => {
  const h = harness(); h.add('mobile', { write_paths: ['src/Audio/'] }); h.add('audio', { write_paths: ['SRC/audio/out.mjs'] });
  h.claim('mobile'); refuses(() => h.claim('audio'), 'SCOPE_BUSY');
  const other = harness(); other.add('mobile', { write_paths: ['src/a'] }); other.add('audio', { write_paths: ['src/ab'] }); other.claim('mobile'); other.claim('audio');
});

test('correction cannot wait for a dependency that it just superseded', () => {
  const h = harness(); h.add('mobile', { work_ref: 'ref/work/reconnect' });
  refuses(() => h.add('audio', { work_ref: 'ref/work/reconnect', work_revision: 2, depends_on: ['mobile'] }, 11), 'DEPENDENCY_SUPERSEDED');
  assert.equal(h.store.state.cells.mobile.state, 'queued');
  assert.equal(h.store.state.cells.audio, undefined);
});

test('consecutive corrections preserve each old stop barrier and original context binding', () => {
  const h = harness(); h.add('mobile', { work_ref: 'ref/work/reconnect' }); h.claim('mobile');
  h.add('audio', { work_ref: 'ref/work/reconnect', work_revision: 2, context_digest: 'f'.repeat(64) }, 25);
  h.add('final', { work_ref: 'ref/work/reconnect', work_revision: 3, context_digest: '0'.repeat(64) }, 26);
  refuses(() => h.claim('final', 27), 'SCOPE_BUSY');
  assert.equal(h.store.state.cells.audio.state, 'cancelled');
  assert.equal(h.store.state.cells.mobile.spec.context_digest, 'e'.repeat(64));
  assert.ok(h.store.state.events.some(e => e.type === 'superseded' && e.cell_id === 'mobile'));
  h.send('stopped', 'mobile', { epoch: 1, receipt_ref: 'ref/receipt/stopped', disposition: 'cancelled' }, 28, ATTESTER);
  assert.equal(h.claim('final', 29).work_revision, 3);
});

test('refused late operations also persist the clock high-water mark', () => {
  const h = harness(); h.add('mobile'); h.claim('mobile');
  refuses(() => h.submit('mobile', 1, 200), 'LEASE_NOT_ACTIVE');
  refuses(() => h.send('renew', 'mobile', { epoch: 1, lease_ms: 100 }, 30, 'ref/producer/mobile'), 'JOURNAL_INVALID');
  assert.equal(h.store.state.last_now, 200);
  assert.equal(h.store.state.cells.mobile.state, 'running'); // expired projection, no rejected business mutation
});

test('legacy journals are preserved and refused instead of silently reinterpreted', () => {
  const h = harness(); h.add('mobile'); h.claim('mobile'); h.store.state.version = 1;
  const before = structuredClone(h.store.state);
  refuses(() => h.submit('mobile'), 'JOURNAL_VERSION_UNSUPPORTED');
  assert.deepEqual(h.store.state, before);
});

test('correction invalidates transitive consumers of a previously integrated dependency', () => {
  const h = harness(); h.add('mobile'); h.claim('mobile'); h.submit('mobile');
  h.send('verify', 'mobile', { base_sha: BASE, head_sha: HEAD, diff_sha256: DIFF, receipt_ref: 'ref/receipt/review',
    checks: [{ name: 'regression', issuer_ref: 'ref/issuer/test', head_sha: HEAD, conclusion: 'success', receipt_ref: 'ref/receipt/check' }] }, 31, 'ref/reviewer/mobile');
  h.send('integrated', 'mobile', { base_sha: BASE, head_sha: HEAD, merge_sha: 'f'.repeat(40), receipt_ref: 'ref/receipt/merge' }, 32, ATTESTER);
  h.add('audio', { depends_on: ['mobile'] }, 33); h.claim('audio', 34);
  h.add('docs', { depends_on: ['audio'] }, 35);
  h.add('fixed', { work_ref: 'ref/work/mobile', work_revision: 2 }, 36);
  assert.equal(h.store.state.cells.mobile.state, 'integrated'); // historical integration is not erased
  assert.equal(h.store.state.cells.audio.state, 'stopping');
  assert.equal(h.store.state.cells.docs.state, 'cancelled');
  refuses(() => h.submit('audio', 2, 37), 'LEASE_NOT_ACTIVE');
  refuses(() => h.claim('docs', 38), 'DEPENDENCY_SUPERSEDED');
});

test('the executable rehearsal covers a continuous local flow and refuses production claims', async () => {
  const report = await runRehearsal();
  assert.equal(report.status, 'pass', JSON.stringify(report.cases.filter(c => c.status !== 'pass')));
  for (const family of ['correction', 'coordination', 'event-ordering', 'time-and-retry', 'evidence',
    'recovery', 'authority-ceiling', 'capacity', 'integration', 'continuous-local-flow']) {
    assert.ok(report.cases.some(c => c.family === family && c.status === 'pass'), family);
  }
  const flow = report.cases.find(c => c.family === 'continuous-local-flow');
  assert.deepEqual(flow.handoff.constraints, ['スマホ単体', 'BLE変更は対象外']);
  assert.equal(flow.handoff.revision, 2); assert.equal(flow.handoff.task_completed, false);
  for (const value of Object.values(report.claims)) assert.equal(value, false);
  assert.equal(report.coverage.device_audio_distribution, 'not_executed');
});
