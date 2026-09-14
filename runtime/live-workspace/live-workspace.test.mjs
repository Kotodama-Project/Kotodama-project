import test from 'node:test';
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { EventEmitter } from 'node:events';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';
import { ChannelWorkspaceHub, ChannelRoom, scopeIdentity, sessionStart, mediaSession, digest } from './core.mjs';
import { DiscordVoiceSlots } from './discord-slots.mjs';
import { openAILiveConnector, createWebRTCSession } from './openai.mjs';

// All actors, authority, consent, Work records and Live media are SYNTHETIC.
const scope = { provider: 'discord', tenant: 'fixture-tenant', channel: 'fixture-channel' };
const source = () => ({ sourceFinal: true, addressed: true, principal: 'fixture-human',
  sourceRef: 'fixture-source', sourceDigest: 'a'.repeat(64), revision: '1',
  objective: 'Improve the synthetic example.', acceptance: ['The example passes its test.'] });
const started = (id = 'fixture-live') => ({ type: 'session.started',
  session: { id, model: 'gpt-live-1', status: 'active' } });
const transcript = (id, delta, start = 0, end = 10) => ({ type: 'session.input_transcript.delta',
  event_id: id, delta, start_ms: start, end_ms: end });
const delegated = (id = 'fixture-delegation', event = 'fixture-event', offset = 100) => ({
  type: 'session.delegation.created', event_id: event, offset_ms: offset,
  delegation: { id, target: 'client', type: 'delegation' } });
function deferred() { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; }
function fixture(options = {}) {
  let clock = Date.now(); let created = 0; let dispatchCount = 0; let transportCount = 0;
  const admissions = new Map(); const results = new Map(); const frames = []; const notices = []; const transports = [];
  const owner = {
    async authorize(input) { return options.authorize ? options.authorize(input) : true; },
    async ensureWorkspace({ scope }) {
      created++;
      return { roomKey: scope.key, kind: options.kind ?? 'paired_host',
        ref: `fixture-workspace-${scope.key}`, expiresAt: clock + 60000 };
    },
    async reconcileWorkspace() { return options.reconciled ?? true; },
    async admit(request) {
      if (options.admit) return options.admit(request);
      const previous = admissions.get(request.requestKey);
      if (previous) { assert.equal(previous.inputDigest, request.inputDigest); return previous; }
      const admission = { requestKey: request.requestKey, roomKey: request.scope.key, principal: request.principal,
        sourceDigest: request.source.sourceDigest, inputDigest: request.inputDigest,
        workspaceRef: request.workspace.ref, executorKind: request.workspace.kind,
        operation: 'development_to_pr', expiresAt: request.workspace.expiresAt,
        workRef: `fixture-work-${request.requestKey}`, revision: '1', grantRef: 'fixture-grant',
        contextDigest: 'b'.repeat(64) };
      admissions.set(request.requestKey, admission); return admission;
    },
    async dispatch(input) {
      if (results.has(input.admission.requestKey)) return results.get(input.admission.requestKey);
      dispatchCount++;
      const result = options.dispatch ? await options.dispatch(input) : { state: 'needs_review',
        workRef: input.admission.workRef, revision: input.admission.revision,
        requestKey: input.admission.requestKey };
      results.set(input.admission.requestKey, result); return result;
    },
  };
  const intentOwner = { async resolve(input) { return options.resolve ? options.resolve(input) : source(); } };
  const connect = async () => {
    transportCount++;
    const transport = { sent: [], closed: false,
      onEvent(fn) { this.receive = fn; }, onClose(fn) { this.end = fn; },
      start(event) { this.sent.push(event); queueMicrotask(() => this.receive(started(`fixture-live-${transportCount}`))); },
      send(event) { this.sent.push(event); }, close() { this.closed = true; } };
    transports.push(transport); return transport;
  };
  const config = { owner, intentOwner, connect, now: () => clock,
    onAudio: (key, bytes) => frames.push([key, bytes]), onNotice: item => notices.push(item), maxRooms: options.maxRooms ?? 8 };
  return { owner, intentOwner, config, transports, frames, notices, admissions, results,
    hub: new ChannelWorkspaceHub(config), advance: ms => { clock += ms; },
    counts: () => ({ created, dispatchCount, transportCount }) };
}
async function roomFixture(t, options) {
  const f = fixture(options); const room = await f.hub.join(scope, 'fixture-human');
  t.after(() => room.close()); return { ...f, room };
}

for (const field of ['provider', 'tenant', 'channel', 'meeting']) test(`scope isolation: ${field}`, () => {
  const a = scopeIdentity(scope); const b = scopeIdentity({ ...scope,
    [field]: field === 'provider' ? 'slack' : 'different-fixture' });
  assert.notEqual(a.key, b.key);
});
test('scope canonicalization ignores caller-supplied key and avoids separator collisions', () => {
  assert.equal(scopeIdentity({ ...scope, key: 'attacker' }).key, scopeIdentity(scope).key);
  assert.notEqual(scopeIdentity({ ...scope, tenant: 'a:b', channel: 'c' }).key,
    scopeIdentity({ ...scope, tenant: 'a', channel: 'b:c' }).key);
});
test('invalid provider, identity and audio rate are rejected', () => {
  for (const value of ['', null, 4, 'a\nb']) assert.throws(() => scopeIdentity({ ...scope, channel: value }));
  assert.throws(() => scopeIdentity({ ...scope, provider: 'invented' }));
  assert.throws(() => sessionStart(48000));
});
test('Live startup is not the legacy Realtime protocol', () => {
  const start = sessionStart(); assert.equal(start.type, 'session.start');
  assert.equal(start.session.model, 'gpt-live-1'); assert.equal(start.session.store, false);
  assert.deepEqual(start.session.audio.format, { type: 'audio/pcm', rate: 24000 });
  assert.deepEqual(start.session.delegation, { type: 'client' });
  assert.equal(mediaSession().audio, undefined);
  assert.deepEqual(mediaSession().client.data_channel.allowed_client_events, []);
});
test('concurrent joins create one workspace and one Live transport', async t => {
  const f = fixture();
  const [a, b] = await Promise.all([f.hub.join(scope, 'fixture-human'), f.hub.join(scope, 'fixture-peer')]);
  t.after(() => a.close()); assert.equal(a, b);
  assert.deepEqual(f.counts(), { created: 1, dispatchCount: 0, transportCount: 1 });
});
test('different channels receive independent workspace and Live state', async t => {
  const f = fixture(); const a = await f.hub.join(scope, 'fixture-human');
  const b = await f.hub.join({ ...scope, channel: 'other' }, 'fixture-human');
  t.after(() => { a.close(); b.close(); }); a.handle(transcript('fragment', 'private to channel a'));
  assert.notEqual(a.key, b.key); assert.notEqual(a.sessionId, b.sessionId);
  assert.equal(f.transports[1].sent.length, 1); assert.equal(f.counts().created, 2);
});
test('admission denies an unconsented listener before resources are created', async () => {
  const f = fixture({ authorize: () => false });
  await assert.rejects(f.hub.join(scope, 'fixture-human'), /access_denied/);
  assert.equal(f.counts().created, 0);
});
test('workspace owner may select paired host, container or VM', async t => {
  for (const kind of ['paired_host', 'container', 'vm']) {
    const f = await roomFixture(t, { kind }); const result = await f.room.handle(delegated());
    assert.equal(result.state, 'needs_review');
    assert.equal([...f.admissions.values()][0].executorKind, kind);
  }
});
test('unknown workspace kind and unbounded expiry do not start Live', async () => {
  const f = fixture({ kind: 'host_root' });
  await assert.rejects(f.hub.join(scope, 'fixture-human'), /invalid_workspace/);
  assert.equal(f.counts().transportCount, 0);
  const g = fixture(); g.owner.ensureWorkspace = async ({ scope }) => ({ roomKey: scope.key,
    kind: 'vm', ref: 'fixture', expiresAt: Date.now() + 86400000 });
  await assert.rejects(g.hub.join(scope, 'fixture-human'), /invalid_workspace_expiry/);
});
test('room quota is enforced before creating another provider session', async t => {
  const f = await roomFixture(t, { maxRooms: 1 });
  await assert.rejects(f.hub.join({ ...scope, channel: 'other' }, 'fixture-human'), /room_quota/);
  assert.equal(f.counts().created, 1);
});
test('PCM requires individually authorized participant and valid PCM16 frames', async t => {
  const f = await roomFixture(t); await f.room.appendPCM('fixture-human', Buffer.alloc(960));
  assert.equal(f.transports[0].sent.at(-1).type, 'session.input_audio.append');
  assert.equal(Buffer.from(f.transports[0].sent.at(-1).audio, 'base64').length, 960);
  await assert.rejects(f.room.appendPCM('stranger', Buffer.alloc(960)), /not_a_participant/);
  for (const bytes of [Buffer.alloc(0), Buffer.alloc(3), Buffer.alloc(48002), 'audio'])
    await assert.rejects(f.room.appendPCM('fixture-human', bytes), /invalid_pcm/);
});
test('audio output is silent until addressed; primary output needs no event_id', async t => {
  const f = await roomFixture(t); const event = { type: 'session.output_audio.delta', delta: Buffer.alloc(960).toString('base64') };
  await f.room.handle(event); assert.equal(f.frames.length, 0);
  await f.room.allowReply('fixture-human'); await f.room.handle(event); assert.equal(f.frames.length, 1);
  f.advance(10001); await f.room.handle(event); assert.equal(f.frames.length, 1);
});
test('speech permission is rechecked before rendering and held audio is discarded', async t => {
  let allow = true; const f = await roomFixture(t, { authorize: input => input.operation !== 'speak' || allow });
  await f.room.allowReply('fixture-human'); allow = false;
  await f.room.handle({ type: 'session.output_audio.delta', delta: Buffer.alloc(960).toString('base64') });
  assert.equal(f.frames.length, 0); assert.equal(f.notices.at(-1).code, 'playback_withheld');
});
test('participant departure during authorization blocks audio and work', async t => {
  const gate = deferred(); let hold = false;
  const f = await roomFixture(t, { authorize: async () => { if (hold) await gate.promise; return true; } });
  await f.room.addParticipant('fixture-peer'); hold = true;
  const append = f.room.appendPCM('fixture-human', Buffer.alloc(960));
  f.room.removeParticipant('fixture-human'); gate.resolve();
  await assert.rejects(append, /access_denied/); assert.equal(f.transports[0].sent.length, 1);
});
test('malformed provider audio closes rather than sending corrupt frames', async t => {
  const f = await roomFixture(t); f.room.handle({ type: 'session.output_audio.delta', delta: 'not base64!' });
  assert.equal(f.room.state, 'closed'); assert.equal(f.frames.length, 0);
});
test('transcript deltas preserve order and are not execution triggers', async t => {
  let captured;
  const f = await roomFixture(t, { resolve: input => { captured = input; return null; } });
  f.room.handle(transcript('first', 'first', 0, 20)); f.room.handle(transcript('second', 'second', 10, 30));
  f.room.handle(transcript('later', 'not yet', 30, 200));
  assert.equal(f.counts().dispatchCount, 0);
  const result = await f.room.handle(delegated());
  assert.deepEqual(captured.observed.map(x => x.text), ['first', 'second']);
  assert.equal(captured.transcriptComplete, false); assert.equal(result.state, 'needs_intent_resolution');
});
test('duplicate transcript event does not duplicate text; changed replay fails closed', async t => {
  let observed; const f = await roomFixture(t, { resolve: input => { observed = input.observed; return null; } });
  const event = transcript('same', 'only once'); f.room.handle(event); f.room.handle(event);
  await f.room.handle(delegated()); assert.equal(observed.length, 1);
  f.room.handle({ ...event, delta: 'changed' }); assert.equal(f.room.state, 'closed');
});
test('huge transcript is refused, not silently truncated into a request', async t => {
  const f = await roomFixture(t); f.room.handle(transcript('big', 'x'.repeat(65537)));
  assert.equal(f.room.state, 'closed'); assert.equal(f.counts().dispatchCount, 0);
});
for (const [name, mutate] of [
  ['unfinalized source', x => { x.sourceFinal = false; }],
  ['not addressed', x => { x.addressed = false; }],
  ['missing acceptance', x => { x.acceptance = []; }],
  ['unknown speaker', x => { x.principal = 'stranger'; }],
  ['unbound source', x => { x.sourceDigest = 'not-a-digest'; }],
]) test(`development refused: ${name}`, async t => {
  const f = await roomFixture(t, { resolve: () => { const intent = source(); mutate(intent); return intent; } });
  assert.equal((await f.room.handle(delegated())).state, 'blocked'); assert.equal(f.counts().dispatchCount, 0);
});
test('delegation metadata is not interpreted as a task or a grant', async t => {
  const f = await roomFixture(t, { resolve: () => null });
  const event = delegated(); event.delegation.task = 'run an unapproved command'; event.delegation.grant = 'admin';
  assert.equal((await f.room.handle(event)).state, 'needs_intent_resolution'); assert.equal(f.counts().dispatchCount, 0);
});
test('successful candidate is not independent verification; status is silent by default', async t => {
  const f = await roomFixture(t); const result = await f.room.handle(delegated());
  assert.equal(result.state, 'needs_review'); assert.equal(result.verified, false);
  assert.equal(f.transports[0].sent.at(-1).type, 'session.thinking.append');
  assert.equal(f.transports[0].sent.at(-1).delegation_id, 'fixture-delegation');
});
test('retries reuse canonical source idempotency across new Live sessions', async t => {
  const f = await roomFixture(t); await f.room.handle(delegated());
  await f.room.handle(delegated('another-id', 'another-event'));
  f.room.close(); const room = await f.hub.reopen(scope, 'fixture-human'); t.after(() => room.close());
  await room.handle(delegated()); assert.equal(f.counts().dispatchCount, 1);
});
test('same source revision with changed objective conflicts rather than silently rerunning', async t => {
  let objective = 'Original'; const f = await roomFixture(t, { resolve: () => ({ ...source(), objective }) });
  await f.room.handle(delegated()); objective = 'Changed';
  const result = await f.room.handle(delegated('changed', 'changed-event'));
  assert.equal(result.state, 'blocked'); assert.equal(f.counts().dispatchCount, 1);
});
test('cross-room or altered-input admission is rejected before dispatch', async t => {
  const f = await roomFixture(t, { admit: async request => ({ requestKey: request.requestKey,
    roomKey: 'other', principal: request.principal, inputDigest: request.inputDigest }) });
  const result = await f.room.handle(delegated()); assert.equal(result.code, 'admission_binding_mismatch');
  assert.equal(f.counts().dispatchCount, 0);
});
test('development can continue asynchronously while new media is processed', async t => {
  const gate = deferred(); const f = await roomFixture(t, { dispatch: async ({ admission }) => {
    await gate.promise; return { ...admission, state: 'needs_review' }; } });
  const work = f.room.handle(delegated()); await delay(0);
  await f.room.appendPCM('fixture-human', Buffer.alloc(960));
  assert.equal(f.transports[0].sent.at(-1).type, 'session.input_audio.append');
  gate.resolve(); assert.equal((await work).state, 'needs_review');
});
test('revoked result access withholds delivery and raw backend errors', async t => {
  const f = await roomFixture(t, { authorize: input => input.operation !== 'read_result' });
  const result = await f.room.handle(delegated()); assert.equal(result.code, 'access_denied');
  assert.equal(f.transports[0].sent.length, 1);
  const g = await roomFixture(t, { dispatch: () => { throw new Error('PRIVATE PROVIDER DETAIL'); } });
  assert.equal((await g.room.handle(delegated())).code, 'work_handoff_failed');
  assert.doesNotMatch(JSON.stringify(g.notices), /PRIVATE/);
});
test('closing aborts active work and prevents late completion audio', async t => {
  const gate = deferred(); let signal;
  const f = await roomFixture(t, { dispatch: async input => { signal = input.signal;
    await gate.promise; return { ...input.admission, state: 'needs_review' }; } });
  const work = f.room.handle(delegated()); await delay(0); f.room.close();
  assert.equal(signal.aborted, true); gate.resolve(); assert.equal((await work).state, 'blocked');
  assert.equal(f.transports[0].sent.length, 1);
});
test('room expiry denies media even if timer callback has not run', async t => {
  const f = await roomFixture(t); f.advance(60000);
  await assert.rejects(f.room.appendPCM('fixture-human', Buffer.alloc(960)), /room_unavailable/);
});
test('closed event overrides the provider snapshot still saying active', async t => {
  const f = await roomFixture(t); f.room.handle({ type: 'session.closed', session: { status: 'active' } });
  assert.equal(f.room.state, 'closed');
});
test('reopen requires owner reconciliation; last departure closes audio, not a VM', async t => {
  const f = await roomFixture(t, { reconciled: false }); f.room.removeParticipant('fixture-human');
  assert.equal(f.room.state, 'closed');
  await assert.rejects(f.hub.reopen(scope, 'fixture-human'), /reconciliation_required/);
  assert.equal(f.counts().created, 1);
});
test('startup timeout rejects waiters and closes the inert transport', async () => {
  const f = fixture(); const identity = scopeIdentity(scope); const transport = { close() {} };
  const room = new ChannelRoom({ scope: identity, owner: f.owner, intentOwner: f.intentOwner,
    transport, workspace: { expiresAt: Date.now() + 1000 }, principal: 'fixture-human', startupTimeoutMs: 5 });
  await delay(10); await assert.rejects(room.ready, /startup_timeout/); assert.equal(room.state, 'closed');
});
test('unexpected session model is refused before media begins', async () => {
  const f = fixture(); const room = new ChannelRoom({ scope: scopeIdentity(scope), owner: f.owner,
    intentOwner: f.intentOwner, transport: { close() {} }, workspace: { expiresAt: Date.now() + 1000 },
    principal: 'fixture-human' });
  room.handle({ ...started(), session: { id: 'fixture', model: 'other' } });
  await assert.rejects(room.ready, /unexpected_model/);
});

test('official SDK adapter installs handlers before sending and redacts errors', async () => {
  let sdk; let clientOptions; let socketOptions; let received;
  class OpenAI { constructor(options) { clientOptions = options; } }
  class LiveWS extends EventEmitter {
    constructor(client, options) { super(); sdk = this; socketOptions = options; this.socket = { platformSocket: { bufferedAmount: 0 } }; }
    send(event) { this.sent = event; } close() { this.closed = true; }
  }
  const connect = openAILiveConnector({ OpenAI, LiveWS, apiKey: randomUUID() });
  const transport = await connect(); assert.equal(sdk, undefined);
  transport.onEvent(event => { received = event; }); transport.onClose(() => {}); transport.start(sessionStart());
  assert.equal(sdk.sent.type, 'session.start'); assert.equal(socketOptions.reconnect, null);
  assert.equal(clientOptions.baseURL, 'https://api.openai.com/v1'); assert.equal(clientOptions.maxRetries, 0);
  sdk.emit('error', new Error('PRIVATE')); assert.deepEqual(received, { type: 'error' });
  transport.send({ type: 'session.input_audio.append', audio: 'AAA=' });
  sdk.socket.platformSocket.bufferedAmount = 65536;
  assert.throws(() => transport.send({ type: 'session.input_audio.append', audio: 'AAA=' }), /transport_backpressure/);
  transport.close(); assert.equal(sdk.closed, true);
});
test('WebRTC signaling uses JSON live.create and never leaks server credentials', async () => {
  let body; const client = { live: { create: async input => { body = input;
    return { session: { id: 'fixture-live' }, transport: { type: 'webrtc', sdp: 'v=0\r\nanswer' } }; } } };
  const response = await createWebRTCSession({ client, offer: 'v=0\r\noffer' });
  assert.deepEqual(response, { sessionId: 'fixture-live', answer: 'v=0\r\nanswer' });
  assert.equal(body.transport.type, 'webrtc'); assert.equal(body.session.model, 'gpt-live-1');
  assert.equal(body.session.store, false); assert.equal(body.session.audio, undefined);
  await assert.rejects(createWebRTCSession({ client, offer: 'x' }), /invalid_sdp/);
});
test('WebRTC errors and malformed response are non-reflective refusals', async () => {
  await assert.rejects(createWebRTCSession({ offer: 'v=0', client: { live: { create: async () => {
    throw new Error('PRIVATE'); } } } }), /^LiveWorkspaceError: live_signaling_failed$/);
  await assert.rejects(createWebRTCSession({ offer: 'v=0', client: { live: { create: async () => ({}) } } }), /invalid_live_response/);
});

test('real file and Node syntax-check handoff, durable owner replay after Hub restart (synthetic authority)', async t => {
  const root = await mkdtemp(join(tmpdir(), 'kotodama-live-test-')); t.after(() => rm(root, { recursive: true, force: true }));
  const f = fixture(); let writes = 0;
  // Tiny local test owner only. NOT the production Work authority or a coding model.
  f.owner.dispatch = async ({ admission }) => {
    const receiptPath = join(root, `${admission.requestKey}.json`);
    try { return JSON.parse(await readFile(receiptPath, 'utf8')); } catch (e) { if (e.code !== 'ENOENT') throw e; }
    await writeFile(join(root, 'candidate.mjs'), 'export const add = (a, b) => a + b;\n'); writes++;
    execFileSync(process.execPath, ['--check', join(root, 'candidate.mjs')], { stdio: 'pipe' });
    const result = { state: 'needs_review', workRef: admission.workRef, revision: admission.revision,
      requestKey: admission.requestKey };
    await writeFile(receiptPath, JSON.stringify(result)); return result;
  };
  const a = await f.hub.join(scope, 'fixture-human'); await a.handle(delegated()); a.close();
  const restarted = new ChannelWorkspaceHub(f.config); const b = await restarted.join(scope, 'fixture-human');
  t.after(() => b.close()); const result = await b.handle(delegated());
  assert.equal(result.state, 'needs_review'); assert.equal(result.verified, false); assert.equal(writes, 1);
  assert.equal(await readFile(join(root, 'candidate.mjs'), 'utf8'), 'export const add = (a, b) => a + b;\n');
});


test('Discord slots never move the same bot from an occupied guild channel', () => {
  const slots = new DiscordVoiceSlots(['fixture-bot']); const first = slots.reserve(scope);
  assert.equal(slots.reserve(scope), first);
  assert.throws(() => slots.reserve({ ...scope, channel: 'other' }), /capacity_exhausted/);
  assert.equal(slots.reserve({ ...scope, tenant: 'another-guild' }).botRef, first.botRef);
});
test('different bots can occupy different VCs in the same guild', () => {
  const slots = new DiscordVoiceSlots(['fixture-bot-a', 'fixture-bot-b']);
  assert.notEqual(slots.reserve(scope).botRef, slots.reserve({ ...scope, channel: 'other' }).botRef);
});
test('uncertain disconnect does not release Discord capacity or accept a forged lease', async () => {
  const slots = new DiscordVoiceSlots(['fixture-bot']); const lease = slots.reserve(scope);
  await assert.rejects(slots.release({ ...lease }, async () => true), /invalid_discord_lease/);
  assert.equal(await slots.release(lease, async () => false), false);
  assert.throws(() => slots.reserve(scope), /reconciling/);
  assert.throws(() => slots.reserve({ ...scope, channel: 'other' }), /capacity_exhausted/);
  assert.equal(await slots.release(lease, async () => true), true);
  const fresh = slots.reserve(scope); assert.notEqual(fresh.id, lease.id);
  await assert.rejects(slots.release(lease, async () => true), /invalid_discord_lease/);
});
test('concurrent release retains the reservation until a disconnect is observed', async () => {
  const slots = new DiscordVoiceSlots(['fixture-bot']); const lease = slots.reserve(scope); const gate = deferred();
  const releasing = slots.release(lease, () => gate.promise);
  await assert.rejects(slots.release(lease, async () => true), /invalid_discord_lease/);
  assert.throws(() => slots.reserve(scope), /reconciling/);
  gate.resolve(true); assert.equal(await releasing, true);
});
test('multiline development constraints are preserved, not truncated', async t => {
  const f = await roomFixture(t, { resolve: () => ({ ...source(), objective: 'First line.\nSecond line.' }) });
  assert.equal((await f.room.handle(delegated())).state, 'needs_review');
});
test('admission cannot widen operation or outlive the selected workspace', async t => {
  for (const patch of [{ operation: 'merge' }, { expiresAt: Date.now() + 3600000 }]) {
    const f = await roomFixture(t); const original = f.owner.admit;
    f.owner.admit = async request => ({ ...await original(request), ...patch });
    assert.equal((await f.room.handle(delegated())).code, 'admission_binding_mismatch');
    assert.equal(f.counts().dispatchCount, 0);
  }
});


test('delegation concurrency is bounded while the owner is slow', async t => {
  const gate = deferred(); const f = await roomFixture(t, { resolve: async () => { await gate.promise; return null; } });
  const jobs = [];
  for (let i = 0; i < 4; i++) jobs.push(f.room.handle(delegated(`d-${i}`, `e-${i}`)));
  f.room.handle(delegated('overflow', 'overflow-event')); assert.equal(f.room.state, 'closed');
  gate.resolve(); await Promise.all(jobs); assert.equal(f.counts().dispatchCount, 0);
});
test('grant deadline reaches the executor cancellation signal', async t => {
  let signal;
  const f = await roomFixture(t, { dispatch: async input => {
    signal = input.signal;
    await new Promise(resolve => signal.addEventListener('abort', resolve, { once: true }));
    return { ...input.admission, state: 'cancelled' };
  } });
  const original = f.owner.admit;
  f.owner.admit = async request => ({ ...await original(request), expiresAt: Date.now() + 50 });
  const work = f.room.handle(delegated()); await delay(80); assert.equal(signal.aborted, true);
  f.advance(20); await work;
});


test('a clock-aligned mix requires consent and current access for every included track', async t => {
  const f = await roomFixture(t); await f.room.addParticipant('fixture-peer');
  await f.room.appendMix(['fixture-human', 'fixture-peer'], Buffer.alloc(960));
  assert.equal(f.transports[0].sent.length, 2);
  await assert.rejects(f.room.appendMix(['fixture-human', 'stranger'], Buffer.alloc(960)), /not_a_participant/);
  await assert.rejects(f.room.appendMix(['fixture-human', 'fixture-human'], Buffer.alloc(960)), /invalid_track_principals/);
  assert.equal(f.transports[0].sent.length, 2);
});
