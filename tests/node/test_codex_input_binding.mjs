import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { EventEmitter } from 'node:events';
import { spawn } from 'node:child_process';
import { PassThrough } from 'node:stream';
import { mkdtempSync, writeFileSync, readFileSync, mkdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { pathToFileURL } from 'node:url';
import { runCodexBrief, validateBrief } from '../../runtime/codex-task-bridge/codex-runner.mjs';
import { prepareKnowledgeBriefInput } from '../../runtime/codex-task-bridge/knowledge-input.mjs';

const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const sourceDigest = 'a'.repeat(64);
const now = Date.parse('2026-09-09T00:00:00Z');
const ordered = value => Array.isArray(value) ? value.map(ordered) : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, ordered(value[key])])) : value;
const seal = value => ({ ...value, context_sha256: hash(JSON.stringify(ordered({ ...value, context_sha256: null }))) });
const falseClaims = {human_approval_verified:false,reviewer_identity_verified:false,semantic_entailment_verified:false,execution_authorized:false,promotion_created:false,current_truth_changed:false};
const context = () => seal({ kind: 'kotodama.generated-knowledge-context', schema_revision: 'v2', bundle_id: 'synthetic',
  source_digest: sourceDigest, as_of: new Date(now).toISOString(), authority: 'projection_only', state: 'ready_candidate', filters: { goals: ['OUT-INTENT'], kgis: [], initiatives: [], tags: [] },
  concepts: [{ id: 'scenario/reconnect', path: 'knowledge/scenario/reconnect.md', title: '合成の要件', description: 'スマホ単体。BLE変更は対象外。',
    status: 'draft', knowledge_state: 'candidate', trust_tier: 'unverified', owner_role: 'AI-LIBRARIAN', reviewer_role: 'AI-AUDITOR',
    goal_refs: ['OUT-INTENT'], kgi_refs: [], initiative_refs: [], source_resources: ['docs/fixture.md'],
    is_stale: false, stale_after: '2026-09-10T00:00:00Z', answer_mode: 'source_required' }],
  omitted_ids: [], unresolved_ids: [], consumer_rule: 'Evidence only; open sources before consequential use.', errors: [], work: null, claims: {...falseClaims}, context_sha256: null });
const compose = (value, options = {}) => { const contextJson = JSON.stringify(seal(value)); return prepareKnowledgeBriefInput({ request: '音声復帰の要件を整理', contextJson,
  expectedContextSha256: hash(contextJson), expectedSourceDigest: sourceDigest, now, ...options }); };

test('context data and current source digest survive preparation without Task authority', () => {
  const prepared = compose(context()); const body = JSON.parse(prepared.input);
  assert.equal(body.knowledge_context.concepts[0].description, 'スマホ単体。BLE変更は対象外。');
  assert.equal(prepared.task_binding, 'not_connected'); assert.equal(prepared.input_sha256, hash(prepared.input));
});

const workContext = () => seal({ ...context(), concepts: [], filters: {goals:[],kgis:[],initiatives:[],tags:[]},
  work: {package_sha256:'b'.repeat(64),subject_sha256:'c'.repeat(64),sensitivity_ceiling:'public',work_ref:'ref/work/synthetic',objective:'合成の成果を確認する',
    selected_claims:[{id:'claim',kind:'observation',statement:'合成の観測',source_refs:['source'],material:true,sensitivity:'public'}],
    sources:[{id:'source',sha256:'d'.repeat(64),kind:'synthetic_fixture',sensitivity:'public',expires_at:null}],
    assumptions:[],questions:[],contradictions:[],
    acceptance_criteria:[{id:'criterion',description:'要件が一致する',reported_state:'met',deliverable_refs:['result']}],
    deliverable_bindings:[{id:'result',sha256:'e'.repeat(64),criterion_refs:['criterion']}]}});

test('one v2 envelope carries work criteria and digest bindings without introducing authority', () => {
  const prepared = compose(workContext()); const result = JSON.parse(prepared.input).knowledge_context;
  assert.equal(result.kind,context().kind); assert.equal(result.schema_revision,'v2');
  assert.deepEqual(Object.keys(result).sort(),Object.keys(context()).sort());
  assert.equal(result.work.acceptance_criteria[0].description,'要件が一致する');
  assert.equal(result.work.deliverable_bindings[0].sha256,'e'.repeat(64));
  assert(Object.values(result.claims).every(value=>value===false));
});

test('legacy envelopes and false authority cannot bypass explicit v2 acceptance', () => {
  const old = context(); old.schema_revision='v1'; assert.throws(()=>compose(old),/knowledge_context_not_ready/);
  const other = workContext(); other.kind='knowledge_context_bundle'; assert.throws(()=>compose(other),/knowledge_context_not_ready/);
  const elevated = workContext(); elevated.claims.execution_authorized=true; assert.throws(()=>compose(elevated),/knowledge_context_not_ready/);
  const raw = JSON.stringify({...context(),context_sha256:'0'.repeat(64)});
  assert.throws(()=>prepareKnowledgeBriefInput({request:'x',contextJson:raw,expectedContextSha256:hash(raw),expectedSourceDigest:sourceDigest,now}),/knowledge_context_digest_mismatch/);
});

test('work constraints and mapping errors refuse even when their hashes are consistent', () => {
  for (const change of [
    c=>c.work.selected_claims[0].source_refs=['unknown'],
    c=>c.work.selected_claims[0].material=false,
    c=>c.work.sources[0].kind='local_snapshot',
    c=>c.work.sources[0].expires_at='2026-09-08T00:00:00Z',
    c=>c.work.acceptance_criteria[0].reported_state='pending',
    c=>c.work.deliverable_bindings[0].criterion_refs=['unknown'],
    c=>c.work.assumptions.push({id:'assumption',statement:'仮定',claim_refs:['omitted']}),
    c=>c.omitted_ids.push('claim'),
    c=>c.work.questions.push({id:'question',statement:'未決',blocking:true,state:'open'}),
    c=>c.work.contradictions.push({id:'conflict',claim_refs:['claim'],severity:1,state:'open'}),
    c=>c.work.sources.push({...c.work.sources[0]}),
    c=>c.work.deliverable_bindings[0].sha256=['e'.repeat(64)]
  ]) { const value=workContext(); change(value); assert.throws(()=>compose(value),/knowledge_work_not_ready/); }
});

test('a caller must explicitly allow a higher sensitivity ceiling', () => {
  const value=workContext(); value.work.sensitivity_ceiling='restricted'; value.work.sources[0].sensitivity='restricted'; value.work.selected_claims[0].sensitivity='restricted';
  assert.throws(()=>compose(value),/knowledge_work_not_ready/);
  assert.equal(compose(value,{sensitivityCeiling:'restricted'}).authority,'projection_only');
  value.work.sensitivity_ceiling='public'; assert.throws(()=>compose(value,{sensitivityCeiling:'restricted'}),/knowledge_work_not_ready/);
});

test('changed, unresolved, stale and oversized knowledge refuses preparation', () => {
  const raw = JSON.stringify(context());
  assert.throws(() => prepareKnowledgeBriefInput({ request: 'x', contextJson: raw + ' ', expectedContextSha256: hash(raw), expectedSourceDigest: sourceDigest, now }), /context_drift/);
  for (const change of [c => c.unresolved_ids.push('missing'), c => c.state = 'needs_resolution',
    c => c.concepts[0].is_stale = true, c => c.concepts[0].stale_after = '2026-09-08T00:00:00Z',
    c => c.source_digest = 'b'.repeat(64), c => c.authority = 'approved', c => c.concepts[0].description = 'x'.repeat(20000)]) {
    const c = context(); change(c); assert.throws(() => compose(c), /knowledge_/);
  }
});

test('runner binds the exact UTF-8 stdin before spawn and to a started session even on failure', async () => {
  const root = mkdtempSync(join(tmpdir(), 'input-binding-')); const executable = join(root, 'synthetic-executable');
  writeFileSync(executable, 'synthetic binary'); const thread_id = randomUUID();
  let captured = Buffer.alloc(0), prepared, started, spawnCount = 0;
  const options = { executable, expectedExecutableSha256: hash('synthetic binary'), cwd: root, model: 'gpt-6-astra', input: compose(context()).input,
    onInputPrepared(value) { prepared = value; assert.equal(spawnCount, 0); },
    onSessionStarted(value) { started = value; assert.equal(value.stdin_sha256, hash(captured)); } };
  const spawnImpl = () => {
    spawnCount++; const child = new EventEmitter();
    child.stdin = new PassThrough(); child.stdout = new PassThrough(); child.stderr = new PassThrough();
    child.stdin.on('data', bytes => { captured = Buffer.concat([captured, bytes]); });
    let killed = false; child.kill = () => { if (!killed) { killed = true; setImmediate(() => child.emit('close', 1)); } return true; };
    child.stdin.on('finish', () => setImmediate(() => {
      child.stdout.write(JSON.stringify({ type: 'thread.started', thread_id }) + '\n');
      child.stdout.write(JSON.stringify({ type: 'turn.failed' }) + '\n');
    }));
    return child;
  };
  try {
    await assert.rejects(runCodexBrief(options, { spawnImpl }), /provider_failed/);
    assert.ok(prepared); assert.equal(prepared.stdin_sha256, hash(captured));
    assert.notEqual(prepared.stdin_sha256, hash(options.input));
    assert.equal(started.thread_id, thread_id); assert.equal(started.input_sha256, hash(options.input));
    assert.equal(JSON.parse(captured.toString('utf8').split('\n').slice(1).join('\n')).request, options.input);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('a failed or async input observer prevents any model process', async () => {
  const root = mkdtempSync(join(tmpdir(), 'input-observer-')); const executable = join(root, 'synthetic-executable');
  writeFileSync(executable, 'synthetic binary'); let calls = 0;
  try {
    for (const onInputPrepared of [() => { throw new Error('private error'); }, async () => {}]) {
      await assert.rejects(runCodexBrief({ executable, expectedExecutableSha256: hash('synthetic binary'), cwd: root, model: 'gpt-6-astra', input: 'test', onInputPrepared },
        { spawnImpl: () => { calls++; throw new Error('must not spawn'); } }), /input_observer/);
    }
    assert.equal(calls, 0);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('cancellation during input persistence prevents spawning', async () => {
  const root = mkdtempSync(join(tmpdir(), 'input-abort-')); const executable = join(root, 'synthetic-executable');
  writeFileSync(executable, 'synthetic binary'); const controller = new AbortController(); let calls = 0;
  try {
    await assert.rejects(runCodexBrief({ executable, expectedExecutableSha256: hash('synthetic binary'), cwd: root,
      model: 'gpt-6-astra', input: 'test', signal: controller.signal, onInputPrepared: () => controller.abort() },
      { spawnImpl: () => { calls++; throw new Error('must not spawn'); } }), /codex_aborted/);
    assert.equal(calls, 0);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('schema drift after preparation refuses a successful-looking result', async () => {
  const root = mkdtempSync(join(tmpdir(), 'schema-binding-'));
  try {
    for (const relative of ['runtime/codex-task-bridge/codex-runner.mjs', 'runtime/codex-task-bridge/brief.schema.json',
      'runtime/cloudflare-os-kotodama/gatekeeper-kotodama-brief/src/protocol.mjs',
      'runtime/local-review-gateway/server.mjs', 'runtime/local-review-gateway/access-policy.mjs',
      'runtime/local-review-gateway/context-receipt.mjs',
      'runtime/local-review-gateway/synthetic-fixture.mjs', 'runtime/cloudflare-edge/src/index.js']) {
      const path = join(root, relative); mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, readFileSync(new URL('../../' + relative, import.meta.url)));
    }
    writeFileSync(join(root, 'package.json'), JSON.stringify({type: 'module'}));
    const { runCodexBrief: isolated } = await import(pathToFileURL(join(root, 'runtime/codex-task-bridge/codex-runner.mjs')));
    const executable = join(root, 'synthetic-executable'); writeFileSync(executable, 'synthetic binary');
    const schema = join(root, 'runtime/codex-task-bridge/brief.schema.json');
    const validReply = validateBrief({ objective: '要件', deliverable: '案', constraints: ['変更しない'], acceptance_criteria: ['同じ版を確認する'], open_questions: [] });
    const spawnImpl = () => {
      const child = new EventEmitter(); child.stdin = new PassThrough(); child.stdout = new PassThrough(); child.stderr = new PassThrough();
      child.kill = () => { setImmediate(() => child.emit('close', 1)); return true; };
      child.stdin.on('finish', () => setImmediate(() => {
        writeFileSync(schema, readFileSync(schema, 'utf8') + '\n');
        for (const event of [{ type: 'thread.started', thread_id: randomUUID() }, { type: 'turn.started' },
          { type: 'item.completed', item: { type: 'agent_message', text: JSON.stringify(validReply) } },
          { type: 'turn.completed' }]) child.stdout.write(JSON.stringify(event) + '\n');
        child.emit('close', 0);
      }));
      return child;
    };
    await assert.rejects(isolated({ executable, expectedExecutableSha256: hash('synthetic binary'), cwd: root, model: 'gpt-6-astra', input: 'test' }, { spawnImpl }), /codex_result_refused/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('current context shape and declared lifecycle must be valid before preparation', () => {
  for (const change of [
    c => delete c.as_of, c => c.as_of = '2027-02-30T00:00:00Z',
    c => c.as_of = '2026-09-10T00:00:00Z', c => c.filters = { goals: ['OUT-INTENT'] },
    c => c.filters.goals = [], c => c.concepts[0].knowledge_state = 'revoked',
    c => c.concepts[0].status = 'deprecated', c => c.concepts[0].source_resources = [],
    c => c.concepts[0].title = [], c => c.concepts[0].description = '\ud800',
    c => c.concepts[0].stale_after = '2027-02-30T00:00:00Z',
    c => c.concepts[0].runtime_authority = true, c => c.omitted_ids.push('scenario/reconnect'),
  ]) {
    const c = context(); change(c); assert.throws(() => compose(c), /knowledge_/);
  }
});

test('a real owned child receives exactly the prepared UTF-8 stdin binding', async () => {
  const root = mkdtempSync(join(tmpdir(), 'real-input-binding-'));
  const childPath = join(root, 'synthetic-child.mjs');
  writeFileSync(childPath, `
    import {createHash,randomUUID} from 'node:crypto';
    const chunks=[];for await(const chunk of process.stdin)chunks.push(chunk);
    const raw=Buffer.concat(chunks),text=raw.toString('utf8');
    const body=JSON.parse(JSON.parse(text.slice(text.indexOf('\\n')+1)).request);
    const brief={objective:body.request,deliverable:'合成の要件候補',
      constraints:[body.knowledge_context.concepts[0].description,createHash('sha256').update(raw).digest('hex')],
      acceptance_criteria:['同じ入力のdigestを返す'],open_questions:[]};
    for(const event of [{type:'thread.started',thread_id:randomUUID()},{type:'turn.started'},
      {type:'item.completed',item:{type:'agent_message',text:JSON.stringify(brief)}},{type:'turn.completed'}])
      process.stdout.write(JSON.stringify(event)+'\\n');
  `);
  try {
    let prepared, started;
    const result = await runCodexBrief({ executable: process.execPath,
      expectedExecutableSha256: hash(readFileSync(process.execPath)), cwd: root,
      model: 'synthetic-model', input: compose(context()).input,
      onInputPrepared(value) { prepared = value; }, onSessionStarted(value) { started = value; } },
      { spawnImpl(executable, _codexArgs, options) { return spawn(executable, [childPath], options); } });
    assert.equal(result.stdin_sha256, prepared.stdin_sha256);
    assert.equal(started.stdin_sha256, prepared.stdin_sha256);
    assert.equal(result.brief.constraints[1], prepared.stdin_sha256);
    assert.equal(result.brief.constraints[0], context().concepts[0].description);
    assert.equal(result.tool_events, 0);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
