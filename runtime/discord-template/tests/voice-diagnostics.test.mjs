import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {mkdtempSync, readFileSync, rmSync, existsSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {collectVoiceDiagnostics, VoiceDiagnosticsError} from '../src/voice-diagnostics.mjs';

const since = '2026-01-01T00:00:00.000Z', until = '2026-01-01T00:30:00.000Z';
const revision = 'a'.repeat(40);
const cli = fileURLToPath(new URL('../bin/voice-diagnostics.mjs', import.meta.url));
const secret = 'SYNTHETIC_PRIVATE_CONTENT_DO_NOT_EXPORT';
const turn = {wakeDetected: false, eligible: true, liveActive: true, conversationActive: true};
function fixture(t, rows = []) {
  const dir = mkdtempSync(path.join(tmpdir(), 'kotodama-diagnostic-'));
  t.after(() => rmSync(dir, {recursive: true, force: true}));
  const database = path.join(dir, 'events.sqlite');
  const db = new DatabaseSync(database);
  db.exec('CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, type TEXT NOT NULL, at TEXT NOT NULL, body TEXT NOT NULL)');
  const insert = db.prepare('INSERT INTO events(type, at, body) VALUES(?,?,?)');
  for (const row of rows) insert.run(row.type, row.at ?? since,
    typeof row.body === 'string' ? row.body : JSON.stringify(row.body ?? {}));
  db.close();
  return {database, dir, since, until, revision};
}
function run(args) {
  return spawnSync(process.execPath, [cli, ...args], {encoding: 'utf8', timeout: 10000});
}
function args(f) {return ['--db', f.database, '--since', since, '--until', until, '--revision', revision];}
function refused(fn, code) {
  assert.throws(fn, error => error instanceof VoiceDiagnosticsError && error.code === code);
}

test('counts observations and ASR timing without claiming audible replies or acceptance', t => {
  const f = fixture(t, [
    {type: 'voice.local_turn', body: {...turn, wakeDetected: true}},
    {type: 'voice.local_turn', body: turn},
    {type: 'voice.local_asr_timing', body: {audioMs: 1000, queueMs: 0, elapsedMs: 100}},
    {type: 'voice.local_asr_timing', body: {audioMs: 2000, queueMs: 10, elapsedMs: 300}},
    {type: 'voice.local_capture_dropped', body: {reason: secret}},
    {type: 'voice.session_ended'}, {type: 'voice.provider_command_rejected'},
    {type: 'voice.reply_skipped'}, {type: 'task.created', body: {source_key: secret}},
  ]);
  const report = collectVoiceDiagnostics(f);
  assert.equal(report.status, 'OBSERVED');
  assert.equal(report.selected_events, 9);
  assert.equal(report.event_counts['task.created'], 1);
  assert.deepEqual(report.local_turn_flags.wakeDetected, {true: 1, false: 1, unknown: 0});
  assert.deepEqual(report.local_asr_ms.elapsedMs,
    {samples: 2, invalid: 0, min: 100, p50: 100, p95: 300, max: 300});
  assert.equal(report.revision_verified, false);
  assert.equal(report.scope, 'INSTALLATION_TIME_WINDOW_NOT_SESSION_SCOPED');
  assert.equal(report.public_beta, 'NO_GO_UNPUBLISHED');
  assert(Object.values(report.claims).every(v => v === false));
  assert(Object.values(report.unmeasured).every(v => v === null));
  assert(!JSON.stringify(report).includes(secret));
});

test('uses a half-open interval and does not treat no data as success', t => {
  const f = fixture(t, [
    {type: 'voice.local_turn', at: '2025-12-31T23:59:59.999Z', body: turn},
    {type: 'voice.local_turn', at: since, body: turn},
    {type: 'voice.local_turn', at: until, body: turn},
  ]);
  assert.equal(collectVoiceDiagnostics(f).selected_events, 1);
  const empty = collectVoiceDiagnostics({...f, since: '2026-01-02T00:00:00.000Z', until: '2026-01-02T01:00:00.000Z'});
  assert.equal(empty.status, 'NO_MATCHING_EVENTS');
  assert.equal(empty.local_asr_ms.elapsedMs.p95, null);
  assert.equal(empty.unmeasured.audible_replies, null);
});

test('never exports unselected events, identifiers, arbitrary properties or source tables', t => {
  const f = fixture(t, [
    {type: 'voice.consent', body: {actor: secret}},
    {type: secret, body: secret},
    {type: 'source.created', body: {text: secret}},
    {type: 'voice.usage_snapshot', body: {total: 100, actor: secret}},
    {type: 'voice.usage_snapshot', body: {total: 200, actor: secret}},
    {type: 'voice.local_turn', body: {...turn, text: secret, liveSession: secret,
      voiceSession: secret, actor: secret, error: {message: secret}, [secret]: secret}},
    {type: 'voice.local_asr_timing', body: {audioMs: 1, queueMs: 2, elapsedMs: 3, path: secret}},
    {type: 'voice.reply_skipped', body: secret},
  ]);
  const db = new DatabaseSync(f.database);
  db.exec('CREATE TABLE sources(secret TEXT)');
  db.prepare('INSERT INTO sources VALUES(?)').run(secret);
  db.close();
  const result = run(args(f));
  assert.equal(result.status, 0, result.stderr);
  assert(!result.stdout.includes(secret));
  assert(!result.stderr.includes(secret));
  assert(!result.stdout.includes(f.database));
  assert.equal(JSON.parse(result.stdout).selected_events, 3);
  assert.equal(JSON.parse(result.stdout).event_counts['voice.usage_snapshot'], undefined);
});

test('malformed, oversized or non-object bodies are incomplete, not fabricated zero measurements', t => {
  const f = fixture(t, [
    {type: 'voice.local_turn', body: '{' + secret},
    {type: 'voice.local_turn', body: JSON.stringify({text: secret.repeat(1000)})},
    {type: 'voice.local_turn', body: '[]'},
    {type: 'voice.local_asr_timing', body: 'null'},
    {type: 'voice.local_asr_timing', body: {audioMs: '123', queueMs: -1, elapsedMs: 3600001}},
    {type: 'voice.local_asr_timing', body: '{"audioMs":1e309,"queueMs":null,"elapsedMs":true}'},
  ]);
  const report = collectVoiceDiagnostics(f);
  assert.equal(report.status, 'INCOMPLETE_FIELDS');
  assert.equal(report.invalid_bodies, 4);
  assert.equal(report.local_turn_flags.liveActive.unknown, 3);
  for (const metric of Object.values(report.local_asr_ms)) {
    assert.equal(metric.samples, 0); assert.equal(metric.invalid, 3); assert.equal(metric.p50, null);
  }
  assert(!JSON.stringify(report).includes(secret));
});

test('does not coerce flags or inherit prototype fields', t => {
  const f = fixture(t, [{type: 'voice.local_turn',
    body: '{"__proto__":{"wakeDetected":true},"eligible":"true","liveActive":1,"conversationActive":null}'}]);
  for (const stats of Object.values(collectVoiceDiagnostics(f).local_turn_flags)) {
    assert.deepEqual(stats, {true: 0, false: 0, unknown: 1});
  }
});

test('rejects invalid windows and revisions without reflecting inputs', async t => {
  const f = fixture(t);
  for (const patch of [
    {since: secret}, {since: '2026-02-30T00:00:00.000Z'}, {since: until}, {until: since},
    {until: '2026-01-02T00:00:00.001Z'}, {since: '2026-01-01T00:00:00Z'},
  ]) await t.test(JSON.stringify(Object.keys(patch)), () => {
    refused(() => collectVoiceDiagnostics({...f, ...patch}), 'DIAGNOSTIC_WINDOW_INVALID');
  });
  for (const value of [undefined, secret, 'A'.repeat(40), 'a'.repeat(39)]) {
    refused(() => collectVoiceDiagnostics({...f, revision: value}), 'DIAGNOSTIC_REVISION_INVALID');
  }
});

test('does not create a missing database, accepts no directory, hides corrupt-file errors', t => {
  const f = fixture(t);
  const missing = path.join(f.dir, secret);
  refused(() => collectVoiceDiagnostics({...f, database: missing}), 'DIAGNOSTIC_READ_FAILED');
  assert.equal(existsSync(missing), false);
  refused(() => collectVoiceDiagnostics({...f, database: f.dir}), 'DIAGNOSTIC_DATABASE_INVALID');
  const corrupt = path.join(f.dir, 'corrupt.sqlite');
  writeFileSync(corrupt, secret);
  const result = run(args({...f, database: corrupt}));
  assert.equal(result.status, 1);
  assert(!result.stdout.includes(secret)); assert(!result.stderr.includes(secret));
});

test('refuses missing schema and views rather than reading arbitrary source tables', t => {
  const f = fixture(t);
  const db = new DatabaseSync(f.database);
  db.exec('DROP TABLE events; CREATE TABLE private_data(seq INTEGER, type TEXT, at TEXT, body TEXT); CREATE VIEW events AS SELECT * FROM private_data;');
  db.close();
  refused(() => collectVoiceDiagnostics(f), 'DIAGNOSTIC_SCHEMA_INVALID');
});

test('refuses more than 10000 selected events instead of emitting a truncated success', t => {
  const f = fixture(t);
  const db = new DatabaseSync(f.database);
  db.exec('BEGIN');
  const insert = db.prepare('INSERT INTO events(type,at,body) VALUES(?,?,?)');
  for (let i = 0; i < 10001; i++) insert.run('voice.session_ended', since, '{}');
  db.exec('COMMIT'); db.close();
  refused(() => collectVoiceDiagnostics(f), 'DIAGNOSTIC_EVENT_LIMIT');
});

test('preserves all bytes of a closed synthetic database and closes its connection', t => {
  const f = fixture(t, [{type: 'voice.local_turn', body: turn}]);
  const before = readFileSync(f.database);
  collectVoiceDiagnostics(f);
  assert.deepEqual(readFileSync(f.database), before);
  // Windows also needs the reader closed before removal.
  rmSync(f.database);
  assert.equal(existsSync(f.database), false);
});

test('reads committed WAL rows without changing runtime tables', t => {
  const f = fixture(t);
  const writer = new DatabaseSync(f.database);
  try {
    writer.exec('PRAGMA journal_mode=WAL');
    writer.prepare('INSERT INTO events(type,at,body) VALUES(?,?,?)').run('voice.local_turn', since, JSON.stringify(turn));
    const before = writer.prepare('SELECT * FROM events').all();
    assert.equal(collectVoiceDiagnostics(f).selected_events, 1);
    assert.deepEqual(writer.prepare('SELECT * FROM events').all(), before);
  } finally { writer.close(); }
});

test('CLI refuses extra, duplicate and private arguments without echoing them', t => {
  const f = fixture(t);
  for (const extra of [['--' + secret], [secret], ['--db', secret], ['--help', secret]]) {
    const result = run([...args(f), ...extra]);
    assert.equal(result.status, 1);
    assert.equal(JSON.parse(result.stdout).status, 'REFUSED');
    assert(!result.stdout.includes(secret)); assert(!result.stderr.includes(secret));
    assert(!result.stdout.includes(f.database));
  }
  const help = run(['--help']);
  assert.equal(help.status, 0); assert.match(help.stdout, /never real-voice acceptance/);
});
