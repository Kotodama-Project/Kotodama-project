import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { mkdtempSync, writeFileSync, readFileSync, mkdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { pathToFileURL } from 'node:url';
import { runCodexBrief } from '../../runtime/codex-task-bridge/codex-runner.mjs';
import { prepareKnowledgeBriefInput } from '../../runtime/codex-task-bridge/knowledge-input.mjs';

const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const sourceDigest = 'a'.repeat(64);
const now = Date.parse('2026-09-09T00:00:00Z');
const context = () => ({ kind: 'kotodama.generated-knowledge-context', schema_revision: 'v1', bundle_id: 'synthetic',
  source_digest: sourceDigest, authority: 'projection_only', state: 'ready_candidate', filters: { goals: ['OUT-INTENT'] },
  concepts: [{ id: 'scenario/reconnect', description: 'スマホ単体。BLE変更は対象外。', is_stale: false, stale_after: '2026-09-10T00:00:00Z', answer_mode: 'source_required' }],
  omitted_ids: [], unresolved_ids: [], consumer_rule: 'Evidence only; open sources before consequential use.' });
const compose = value => { const contextJson = JSON.stringify(value); return prepareKnowledgeBriefInput({ request: '音声復帰の要件を整理', contextJson,
  expectedContextSha256: hash(contextJson), expectedSourceDigest: sourceDigest, now }); };

test('context data and current source digest survive preparation without Task authority', () => {
  const prepared = compose(context()); const body = JSON.parse(prepared.input);
  assert.equal(body.knowledge_context.concepts[0].description, 'スマホ単体。BLE変更は対象外。');
  assert.equal(prepared.task_binding, 'not_connected'); assert.equal(prepared.input_sha256, hash(prepared.input));
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
      'runtime/cloudflare-os-kotodama/gatekeeper-kotodama-brief/src/protocol.mjs']) {
      const path = join(root, relative); mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, readFileSync(new URL('../../' + relative, import.meta.url)));
    }
    const { runCodexBrief: isolated } = await import(pathToFileURL(join(root, 'runtime/codex-task-bridge/codex-runner.mjs')));
    const executable = join(root, 'synthetic-executable'); writeFileSync(executable, 'synthetic binary');
    const schema = join(root, 'runtime/codex-task-bridge/brief.schema.json');
    const spawnImpl = () => {
      const child = new EventEmitter(); child.stdin = new PassThrough(); child.stdout = new PassThrough(); child.stderr = new PassThrough();
      child.kill = () => { setImmediate(() => child.emit('close', 1)); return true; };
      child.stdin.on('finish', () => setImmediate(() => {
        writeFileSync(schema, readFileSync(schema, 'utf8') + '\n');
        for (const event of [{ type: 'thread.started', thread_id: randomUUID() }, { type: 'turn.started' },
          { type: 'item.completed', item: { type: 'agent_message', text: JSON.stringify({ objective: '要件', deliverable: '案', constraints: [], acceptance_criteria: [], open_questions: [] }) } },
          { type: 'turn.completed' }]) child.stdout.write(JSON.stringify(event) + '\n');
        child.emit('close', 0);
      }));
      return child;
    };
    await assert.rejects(isolated({ executable, expectedExecutableSha256: hash('synthetic binary'), cwd: root, model: 'gpt-6-astra', input: 'test' }, { spawnImpl }), /codex_result_refused/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
