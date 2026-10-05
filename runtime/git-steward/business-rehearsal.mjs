/** Synthetic business rehearsal, NOT a service, company ledger or executor API.
 * Exercises the existing kernel against actual temporary Git + SQLite + Node
 * processes. No network, credentials, provider writes, or production data.
 */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { execFileSync, spawn, spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, relative, isAbsolute } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DatabaseSync } from 'node:sqlite';
import { GitSteward, Refusal } from './coordinator.mjs';
import { CloudflareSqliteStore } from './sqlite-store.mjs';
import { observeDiff } from './git-observer.mjs';

export const BASE = 'a'.repeat(40), HEAD = 'b'.repeat(40), TREE = 'c'.repeat(40), DIFF = 'd'.repeat(64);
export const PLAN = 'ref/principal/planner', ATTEST = 'ref/principal/attester';
export const makePolicy = (changes = {}) => ({ repository_ref: 'ref/repository/wearable-example',
  coordinator_ref: PLAN, attester_ref: ATTEST,
  required_checks: [{ name: 'regression', issuer_ref: 'ref/issuer/test' }],
  max_concurrent: 8, max_cells: 64, max_commands: 1024, max_attempts: 3,
  max_lease_ms: 1000, max_run_ms: 5000, ...changes });
export const makeSpec = (id, changes = {}) => ({ id, work_ref: `ref/work/${id}`, work_revision: 1,
  grant_ref: 'ref/grant/development', context_digest: 'e'.repeat(64), producer_ref: `ref/producer/${id}`,
  reviewer_ref: `ref/reviewer/${id}`, target_ref: 'refs/heads/main', base_sha: BASE,
  write_paths: [`src/${id}/`], read_paths: [], conflict_keys: [], depends_on: [], ...changes });
export class MemoryStore {
  state = null;
  transaction(callback) {
    const r = callback(structuredClone(this.state)); this.state = structuredClone(r.state); return structuredClone(r.result);
  }
}
export function sqliteStorage(db) {
  return { sql: { exec(query, ...bindings) {
    if (query.startsWith('SELECT')) return { toArray: () => db.prepare(query).all(...bindings) };
    db.prepare(query).run(...bindings); return { toArray: () => [] };
  } }, transactionSync(callback) {
    db.exec('BEGIN IMMEDIATE');
    try { const result = callback(); db.exec('COMMIT'); return result; }
    catch (e) { db.exec('ROLLBACK'); throw e; }
  } };
}
export function harness(store = new MemoryStore(), policy = makePolicy(), trace = []) {
  const core = new GitSteward(store, policy); let seq = 0; const prefix = `session-${trace.length}`;
  const send = (type, id, fields = {}, now = 10, actor = PLAN, request = undefined) => {
    try {
      const result = core.execute(actor, { request_id: request ?? `${prefix}-r-${++seq}`, type, cell_id: id, ...fields }, now);
      trace.push({ type, cell: id, now, result }); return result;
    } catch (e) {
      trace.push({ type, cell: id, now, refusal: e.code ?? e.name }); throw e;
    }
  };
  return { core, store, trace, send,
    add: (id, changes = {}, now = 10) => send('add', id, { spec: makeSpec(id, changes) }, now),
    claim: (id, now = 20, request = undefined, base = BASE) => send('claim', id, { base_sha: base, lease_ms: 100 }, now, `ref/producer/${id}`, request),
    submit: (id, epoch = 1, now = 30, changes = {}) => send('submit', id, { epoch, base_sha: BASE, head_sha: HEAD,
      tree_sha: TREE, diff_sha256: DIFF, changed_paths: [`src/${id}/change.mjs`], receipt_ref: 'ref/receipt/output', ...changes }, now, `ref/producer/${id}`),
    verify: (id, now = 40, changes = {}) => send('verify', id, { base_sha: BASE, head_sha: HEAD, diff_sha256: DIFF,
      receipt_ref: 'ref/receipt/review', checks: [{ name: 'regression', issuer_ref: 'ref/issuer/test', head_sha: HEAD,
        conclusion: 'success', receipt_ref: 'ref/receipt/check' }], ...changes }, now, `ref/reviewer/${id}`)
  };
}
export const refuses = (fn, code) => assert.throws(fn, e => e instanceof Refusal && e.code === code);

function assertCeiling(projection) {
  for (const name of ['merge_authorized', 'task_completed', 'runtime_deployed']) assert.equal(projection[name], false, name);
}

function cleanupOwned(path, parent) {
  const rel = relative(resolve(parent), resolve(path));
  assert.ok(rel && !rel.startsWith('..') && !isAbsolute(rel), 'temporary directory ownership');
  rmSync(path, { recursive: true, force: true });
}

async function withDeadline(promise, ms) {
  let timer;
  try { return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('CONTROLLED_PROCESS_TIMEOUT')), ms); })]); }
  finally { clearTimeout(timer); }
}

async function continuousLocalFlow(mode) {
  const parent = tmpdir(), dir = mkdtempSync(join(parent, 'business-rehearsal-'));
  const trace = []; let db, oldProcess, oldExit; let oldExited = false;
  const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.toUpperCase().startsWith('GIT_')));
  Object.assign(env, { GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: process.platform === 'win32' ? 'NUL' : '/dev/null',
    GIT_TERMINAL_PROMPT: '0', GIT_NO_REPLACE_OBJECTS: '1', GIT_CONFIG_COUNT: '1', GIT_CONFIG_KEY_0: 'core.autocrlf', GIT_CONFIG_VALUE_0: 'false',
    GIT_AUTHOR_DATE: '2026-01-01T00:00:00Z', GIT_COMMITTER_DATE: '2026-01-01T00:00:00Z' });
  const git = (cwd, ...args) => execFileSync('git', ['-C', cwd, ...args], { env, timeout: 10000,
    encoding: 'utf8', maxBuffer: 4 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] }).trim();
  const digest = bytes => createHash('sha256').update(bytes).digest('hex');
  try {
    const repo = join(dir, 'repo'); mkdirSync(repo); git(repo, 'init', '-b', 'main');
    git(repo, 'config', 'user.name', 'Synthetic Rehearsal'); git(repo, 'config', 'user.email', 'rehearsal@example.invalid');
    mkdirSync(join(repo, 'src'));
    writeFileSync(join(repo, 'src/reconnect.mjs'), 'export const usable = (connected, audioReady) => connected;\n');
    git(repo, 'add', '.'); git(repo, 'commit', '-m', 'synthetic baseline'); const base = git(repo, 'rev-parse', 'HEAD');
    const contextPath = join(dir, 'context.json');
    const firstContext = { work_ref: 'ref/work/reconnect', revision: 1, goal: '移動後に音声会話を再開できる',
      constraints: ['スマホとペンダントを調査'], next: '接続と音声の復帰を調べる' };
    writeFileSync(contextPath, JSON.stringify(firstContext), 'utf8');
    const original = makeSpec('original', { work_ref: firstContext.work_ref, base_sha: base,
      context_digest: digest(readFileSync(contextPath)), write_paths: ['src/'] });
    db = new DatabaseSync(join(dir, 'journal.db')); let h = harness(new CloudflareSqliteStore(sqliteStorage(db)), makePolicy(), trace);
    h.send('add', 'original', { spec: original }, 10, PLAN, 'add-original');
    const firstAssignment = h.claim('original', 20, 'claim-original', base);
    const oldTree = join(dir, 'old'); git(repo, 'worktree', 'add', '-b', firstAssignment.branch, oldTree, base);
    assert.equal(git(oldTree, 'symbolic-ref', 'HEAD'), `refs/heads/${firstAssignment.branch}`);
    // This controlled process is an executor fixture, not an LLM or device.
    const controlledCode = `process.on('message', message => {
      if (message === 'late-result') require('node:fs').writeFileSync(process.argv[1], '// stale proposal\\n');
      if (message === 'late-result' || message === 'cooperative-stop') process.exit(0);
    }); process.send('ready');`;
    oldProcess = spawn(process.execPath, ['-e', controlledCode, join(oldTree, 'src/reconnect.mjs')],
      { env, stdio: ['ignore', 'ignore', 'ignore', 'ipc'], windowsHide: true });
    oldExit = new Promise((resolveExit, reject) => {
      oldProcess.once('error', error => { oldExited = true; reject(error); });
      oldProcess.once('exit', (status, signal) => { oldExited = true; resolveExit({ status, signal }); });
    });
    await withDeadline(Promise.race([new Promise(resolveReady => oldProcess.once('message', resolveReady)),
      oldExit.then(() => { throw new Error('WORKER_EXITED_BEFORE_READY'); })]), 5000);
    assert.equal(oldExited, false);
    const corrected = { ...firstContext, revision: 2, constraints: ['スマホ単体', 'BLE変更は対象外'],
      next: '同じ候補版で接続と音声の両方を確認する' };
    writeFileSync(contextPath, JSON.stringify(corrected), 'utf8');
    const revised = makeSpec('corrected', { work_ref: corrected.work_ref, work_revision: 2,
      context_digest: digest(readFileSync(contextPath)), base_sha: base, write_paths: ['src/'] });
    h.send('add', 'corrected', { spec: revised }, 25, PLAN, 'add-corrected');
    refuses(() => h.submit('original', 1, 26), 'LEASE_NOT_ACTIVE');
    refuses(() => h.claim('corrected', 27, 'claim-too-early', base), 'SCOPE_BUSY');
    oldProcess.send(mode); const oldWorker = await withDeadline(oldExit, 5000);
    assert.equal(oldWorker.status, 0); assert.equal(oldWorker.signal, null);
    if (mode === 'late-result') assert.equal(readFileSync(join(oldTree, 'src/reconnect.mjs'), 'utf8'), '// stale proposal\n');
    else assert.ok(readFileSync(join(oldTree, 'src/reconnect.mjs'), 'utf8').includes('=> connected;'));
    refuses(() => h.submit('original', 1, 28), 'LEASE_NOT_ACTIVE');
    // Real process exit after correction is observed; authenticity is fixture-only.
    h.send('stopped', 'original', { epoch: 1, receipt_ref: 'ref/receipt/process-exit', disposition: 'cancelled' }, 28, ATTEST);
    db.close(); db = null; db = new DatabaseSync(join(dir, 'journal.db'));
    h = harness(new CloudflareSqliteStore(sqliteStorage(db)), makePolicy(), trace);
    const resumed = h.send('add', 'corrected', { spec: revised }, 29, PLAN, 'add-corrected');
    const recovered = JSON.parse(readFileSync(contextPath, 'utf8'));
    assert.equal(resumed.context_digest, digest(readFileSync(contextPath)));
    assert.equal(recovered.goal, firstContext.goal); assert.deepEqual(recovered.constraints, corrected.constraints);
    const assignment = h.claim('corrected', 30, 'claim-corrected', base); assertCeiling(assignment);
    const newTree = join(dir, 'new'); git(repo, 'worktree', 'add', '-b', assignment.branch, newTree, base);
    assert.equal(git(newTree, 'symbolic-ref', 'HEAD'), `refs/heads/${assignment.branch}`);
    const workerCode = `const fs = require('node:fs'); const c = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));
      require('node:assert/strict').deepEqual(c.constraints, ['スマホ単体', 'BLE変更は対象外']);
      fs.writeFileSync(process.argv[2], 'export const usable = (connected, audioReady) => connected && audioReady;\\n');`;
    const worker = spawnSync(process.execPath, ['-e', workerCode, contextPath, join(newTree, 'src/reconnect.mjs')],
      { env, timeout: 5000, encoding: 'utf8' }); assert.equal(worker.status, 0, worker.stderr);
    git(newTree, 'add', 'src/reconnect.mjs'); git(newTree, 'commit', '-m', 'synthetic connection and audio requirement');
    const head = git(newTree, 'rev-parse', 'HEAD'); const observed = observeDiff(newTree, base, head);
    h.submit('corrected', assignment.epoch, 40, observed);
    const reviewFile = join(dir, 'review.mjs');
    writeFileSync(reviewFile, `import assert from 'node:assert/strict';\nimport {pathToFileURL} from 'node:url';\nconst {usable} = await import(pathToFileURL(process.argv[2]));\nassert.equal(usable(true, false), false);\nassert.equal(usable(false, true), false);\nassert.equal(usable(true, true), true);\n`, 'utf8');
    const review = spawnSync(process.execPath, [reviewFile, join(newTree, 'src/reconnect.mjs')], { env, timeout: 5000, encoding: 'utf8' });
    assert.equal(review.status, 0, review.stderr);
    h.verify('corrected', 50, { base_sha: base, head_sha: head, diff_sha256: observed.diff_sha256,
      checks: [{ name: 'regression', issuer_ref: 'ref/issuer/test', head_sha: head, conclusion: 'success', receipt_ref: 'ref/receipt/process-review' }] });
    const assessed = h.send('assess', 'corrected', { base_sha: git(repo, 'rev-parse', 'HEAD'), head_sha: head }, 60, ATTEST);
    assertCeiling(assessed);
    git(repo, 'merge', '--ff-only', head);
    const integrated = h.send('integrated', 'corrected', { base_sha: base, head_sha: head,
      merge_sha: git(repo, 'rev-parse', 'HEAD'), receipt_ref: 'ref/receipt/local-git-integration' }, 70, ATTEST);
    assert.equal(integrated.state, 'integrated'); assertCeiling(integrated);
    db.close(); db = null; db = new DatabaseSync(join(dir, 'journal.db'));
    h = harness(new CloudflareSqliteStore(sqliteStorage(db)), makePolicy(), trace);
    const nextDay = h.send('add', 'corrected', { spec: revised }, 2000, PLAN, 'add-corrected');
    assert.equal(nextDay.state, 'integrated'); assert.equal(nextDay.context_digest, digest(readFileSync(contextPath))); assertCeiling(nextDay);
    return { id: `continuous-${mode}-correct-restart-execute-review-integrate`, status: 'pass',
      boundary: 'real_local_git_sqlite_processes_synthetic_work_context_receipts', trace,
      handoff: { ...recovered, context_digest: nextDay.context_digest, candidate_head: head,
        current_state: nextDay.state, task_completed: false, next: '実機・配布版での音声確認は未実施' },
      measured_processes: { old_worker_running_at_correction: true, old_worker_exit: oldWorker.status,
        old_worker_mode: mode, corrected_worker_exit: worker.status, review_exit: review.status },
      manual_steps_in_fixture: 0, manual_steps_in_production: null,
      limits: ['no semantic conversation extraction', 'context supplied by synthetic Work owner',
        'no real identity or grant validation', 'no deployed executor', 'no device or distribution acceptance'] };
  } catch (error) { error.rehearsalTrace = trace; throw error; }
  finally {
    // Only this exact child handle can be stopped. Do not remove a workspace
    // while a process we started could still write to it.
    if (oldProcess && !oldExited) { oldProcess.kill(); await withDeadline(oldExit, 5000); }
    if (db) db.close(); cleanupOwned(dir, parent);
  }
}

export async function runRehearsal() {
  const cases = [];
  function record(id, family, run) {
    const trace = [];
    try { run(trace); cases.push({ id, family, status: 'pass', boundary: 'existing_kernel_synthetic_inputs', trace }); }
    catch (e) { cases.push({ id, family, status: 'fail', error: e.code ?? e.message, trace }); }
  }
  for (const phase of ['queued', 'running', 'candidate', 'verified_candidate']) {
    for (const duplicateCount of [0, 1, 3]) {
      record(`correction-${phase}-replay-${duplicateCount}`, 'correction', trace => {
        const h = harness(undefined, undefined, trace); const original = makeSpec('old', { work_ref: 'ref/work/reconnect' });
        h.send('add', 'old', { spec: original }, 10, PLAN, 'old-add');
        if (phase !== 'queued') h.claim('old');
        if (['candidate', 'verified_candidate'].includes(phase)) h.submit('old');
        if (phase === 'verified_candidate') h.verify('old');
        const corrected = makeSpec('new', { work_ref: 'ref/work/reconnect', work_revision: 2, context_digest: 'f'.repeat(64) });
        h.send('add', 'new', { spec: corrected }, 50, PLAN, 'correction');
        for (let i = 0; i < duplicateCount; i++) h.send('add', 'new', { spec: corrected }, 51 + i, PLAN, 'correction');
        const old = h.send('add', 'old', { spec: original }, 60, PLAN, 'old-add'); assert.equal(old.superseded_by, 'new');
        assert.equal(old.lease_usable, false); assertCeiling(old);
        if (phase !== 'queued') {
          refuses(() => h.claim('new', 61), 'SCOPE_BUSY');
          h.send('stopped', 'old', { epoch: 1, receipt_ref: 'ref/receipt/stopped', disposition: 'cancelled' }, 62, ATTEST);
        }
        const next = h.claim('new', 63); assert.equal(next.work_revision, 2); assert.equal(next.context_digest, 'f'.repeat(64));
      });
    }
  }
  for (const participants of [2, 4, 8]) for (const relation of ['independent', 'same-file', 'read-write', 'semantic', 'case-alias', 'file-directory']) {
    record(`participants-${participants}-${relation}`, 'coordination', trace => {
      const h = harness(undefined, undefined, trace);
      for (let i = 0; i < participants; i++) {
        const change = relation === 'same-file' ? { write_paths: ['src/shared.mjs'] } :
          relation === 'read-write' ? (i === 0 ? { write_paths: ['contract/api.json'] } : { read_paths: ['contract/'] }) :
          relation === 'semantic' ? { conflict_keys: ['ref/contract/audio'] } :
          relation === 'case-alias' ? { write_paths: [i === 0 ? 'src/Audio/' : 'SRC/audio/file'] } :
          relation === 'file-directory' ? { write_paths: [i === 0 ? 'src' : 'src/file'] } : {};
        h.add(`p${i}`, change);
      }
      h.claim('p0');
      for (let i = 1; i < participants; i++) {
        if (relation === 'independent') assertCeiling(h.claim(`p${i}`));
        else refuses(() => h.claim(`p${i}`), 'SCOPE_BUSY');
      }
    });
  }
  const permutations = values => values.length === 0 ? [[]] : values.flatMap((v, i) =>
    permutations(values.filter((_, j) => j !== i)).map(tail => [v, ...tail]));
  for (const order of permutations(['correct', 'submit', 'ack', 'claim-new'])) {
    record(`ordering-${order.join('-')}`, 'event-ordering', trace => {
      const h = harness(undefined, undefined, trace); h.add('old', { work_ref: 'ref/work/reconnect' }); h.claim('old');
      let corrected = false, acknowledged = false, now = 30;
      for (const op of order) {
        if (op === 'correct') { h.add('new', { work_ref: 'ref/work/reconnect', work_revision: 2 }, now); corrected = true; }
        if (op === 'submit') {
          if (corrected) refuses(() => h.submit('old', 1, now), 'LEASE_NOT_ACTIVE'); else h.submit('old', 1, now);
        }
        if (op === 'ack') {
          const acknowledge = () => h.send('stopped', 'old', { epoch: 1, receipt_ref: 'ref/receipt/stopped', disposition: 'cancelled' }, now, ATTEST);
          if (!corrected) refuses(acknowledge, 'STOP_NOT_PENDING'); else { acknowledge(); acknowledged = true; }
        }
        if (op === 'claim-new') {
          if (!corrected) refuses(() => h.claim('new', now), 'CELL_UNKNOWN');
          else if (!acknowledged) refuses(() => h.claim('new', now), 'SCOPE_BUSY');
          else assert.equal(h.claim('new', now).work_revision, 2);
        }
        if (corrected) assert.notEqual(h.store.state.cells.old.state, 'running');
        now++;
      }
    });
  }
  for (const at of [119, 120, 121, 10000]) {
    record(`replay-time-${at}`, 'time-and-retry', trace => {
      const h = harness(undefined, undefined, trace); h.add('mobile'); h.claim('mobile', 20, 'once');
      const observed = h.claim('mobile', at, 'once'); assert.equal(observed.lease_usable, at < 120);
      refuses(() => h.send('renew', 'mobile', { epoch: 1, lease_ms: 100 }, 30, 'ref/producer/mobile'), 'JOURNAL_INVALID');
    });
  }
  for (const [condition, changes, reason] of [
    ['failure', { conclusion: 'failure' }, 'CHECKS_NOT_TRUSTED'],
    ['skipped', { conclusion: 'skipped' }, 'CHECKS_NOT_TRUSTED'],
    ['wrong-head', { head_sha: BASE }, 'CHECKS_NOT_TRUSTED'],
    ['wrong-issuer', { issuer_ref: 'ref/issuer/other' }, 'CHECKS_NOT_TRUSTED'],
    ['missing', null, 'CHECKS_INCOMPLETE']]) {
    record(`review-${condition}`, 'evidence', trace => {
      const h = harness(undefined, undefined, trace); h.add('mobile'); h.claim('mobile'); h.submit('mobile');
      const checks = changes ? [{ name: 'regression', issuer_ref: 'ref/issuer/test', head_sha: HEAD,
        conclusion: 'success', receipt_ref: 'ref/receipt/check', ...changes }] : [];
      refuses(() => h.verify('mobile', 40, { checks }), reason);
    });
  }
  record('ambiguous-delivery-stop-old-fence', 'recovery', trace => {
    const h = harness(undefined, undefined, trace); h.add('mobile'); h.claim('mobile');
    h.send('unknown', 'mobile', { epoch: 1 }, 30, 'ref/producer/mobile'); refuses(() => h.claim('mobile', 31), 'CELL_NOT_QUEUED');
    h.send('stopped', 'mobile', { epoch: 1, receipt_ref: 'ref/receipt/reconciled', disposition: 'queued' }, 32, ATTEST);
    const next = h.claim('mobile', 33); assert.equal(next.epoch, 2);
    refuses(() => h.submit('mobile', 1, 34), 'STALE_FENCE'); h.submit('mobile', 2, 35);
  });
  record('development-is-not-company-authority', 'authority-ceiling', trace => {
    const h = harness(undefined, undefined, trace); h.add('mobile');
    for (const type of ['purchase', 'refund', 'send-customer-message', 'deploy', 'merge']) {
      refuses(() => h.send(type, 'mobile', {}, 20), 'INPUT_INVALID');
    }
    refuses(() => h.send('stop', 'mobile', {}, 20, 'ref/producer/mobile'), 'ACTOR_FORBIDDEN');
  });
  record('budget-does-not-evict-active-work', 'capacity', trace => {
    const h = harness(undefined, makePolicy({ max_concurrent: 1 }), trace); h.add('mobile'); h.add('support'); h.claim('mobile');
    refuses(() => h.claim('support'), 'CONCURRENCY_BUDGET');
  });
  record('base-moved-requires-new-work-revision', 'integration', trace => {
    const h = harness(undefined, undefined, trace); h.add('mobile'); h.claim('mobile'); h.submit('mobile'); h.verify('mobile');
    refuses(() => h.send('assess', 'mobile', { base_sha: HEAD, head_sha: HEAD }, 50, ATTEST), 'BASE_MOVED');
  });
  for (const mode of ['late-result', 'cooperative-stop']) {
    try { cases.push({ ...await continuousLocalFlow(mode), family: 'continuous-local-flow' }); }
    catch (e) { cases.push({ id: `continuous-${mode}-correct-restart-execute-review-integrate`, family: 'continuous-local-flow',
      status: 'fail', error: e.code ?? e.message, trace: e.rehearsalTrace ?? [] }); }
  }
  return { kind: 'synthetic_business_rehearsal', version: 1, status: cases.every(c => c.status === 'pass') ? 'pass' : 'fail',
    cases, counts: { scenarios: cases.length, passed: cases.filter(c => c.status === 'pass').length,
      families: [...new Set(cases.map(c => c.family))] },
    coverage: { local_kernel: 'executed', local_git_sqlite_child_processes: 'executed_in_continuous_case_if_pass',
      semantic_conversation_extraction: 'not_executed', live_work_grant_acl: 'not_executed',
      hosted_os: 'not_executed', github_delivery: 'not_executed', device_audio_distribution: 'not_executed',
      customer_satisfaction_and_financial_viability: 'not_executed' },
    claims: { production_ready: false, company_operating: false, task_completed: false, human_go: false,
      github_latency_measured: false, new_task_authority: false } };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.length !== 2) { process.stderr.write('Usage: node runtime/git-steward/business-rehearsal.mjs\n'); process.exitCode = 2; }
  else { const report = await runRehearsal(); process.stdout.write(JSON.stringify(report, null, 2) + '\n'); if (report.status !== 'pass') process.exitCode = 1; }
}
