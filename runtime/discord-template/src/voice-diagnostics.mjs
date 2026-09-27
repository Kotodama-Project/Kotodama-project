import {DatabaseSync} from 'node:sqlite';
import {lstatSync} from 'node:fs';

const TYPES = Object.freeze([
  'voice.local_turn', 'voice.local_asr_timing', 'voice.local_capture_dropped',
  'voice.session_ended', 'voice.provider_command_rejected', 'voice.reply_skipped',
  'task.created',
]);
const FLAGS = Object.freeze(['wakeDetected', 'eligible', 'liveActive', 'conversationActive']);
const TIMINGS = Object.freeze(['audioMs', 'queueMs', 'elapsedMs']);
const MAX_EVENTS = 10000;
const MAX_BODY_BYTES = 8192;
const MAX_DATABASE_BYTES = 256 * 1024 * 1024;
const MAX_WINDOW_MS = 24 * 60 * 60 * 1000;
const MAX_TIMING_MS = 60 * 60 * 1000;

export class VoiceDiagnosticsError extends Error {
  constructor(code) { super(code); this.name = 'VoiceDiagnosticsError'; this.code = code; }
}
function requireValue(condition, code) {
  if (!condition) throw new VoiceDiagnosticsError(code);
}
function timestamp(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(value)) return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) && new Date(ms).toISOString() === value ? ms : null;
}
function distribution(values, invalid) {
  values.sort((a, b) => a - b);
  const percentile = p => values.length ? values[Math.ceil(values.length * p) - 1] : null;
  return {samples: values.length, invalid, min: values[0] ?? null,
    p50: percentile(0.5), p95: percentile(0.95), max: values.at(-1) ?? null};
}

/** Operator-only local diagnostic. Never instantiate Store: its constructor writes. */
export function collectVoiceDiagnostics({database, since, until, revision} = {}) {
  const start = timestamp(since), end = timestamp(until);
  requireValue(start !== null && end !== null && end > start && end - start <= MAX_WINDOW_MS,
    'DIAGNOSTIC_WINDOW_INVALID');
  requireValue(typeof revision === 'string' && /^[a-f0-9]{40}$/.test(revision),
    'DIAGNOSTIC_REVISION_INVALID');
  requireValue(typeof database === 'string' && database.length > 0 && !database.includes('\0'),
    'DIAGNOSTIC_DATABASE_INVALID');
  let db, transactionOpen = false;
  try {
    const stat = lstatSync(database);
    requireValue(stat.isFile() && !stat.isSymbolicLink() && stat.size <= MAX_DATABASE_BYTES,
      'DIAGNOSTIC_DATABASE_INVALID');
    db = new DatabaseSync(database, {readOnly: true, allowExtension: false, timeout: 1000});
    db.exec('PRAGMA query_only=ON; PRAGMA trusted_schema=OFF; BEGIN;');
    transactionOpen = true;
    requireValue(db.prepare("SELECT type FROM sqlite_schema WHERE name='events'").get()?.type === 'table',
      'DIAGNOSTIC_SCHEMA_INVALID');
    const columns = db.prepare('PRAGMA table_info(events)').all();
    requireValue(['seq', 'type', 'at', 'body'].every(name => columns.some(c => c.name === name)) &&
      columns.some(c => c.name === 'seq' && c.pk === 1 && c.type === 'INTEGER'),
    'DIAGNOSTIC_SCHEMA_INVALID');

    const counts = Object.fromEntries(TYPES.map(type => [type, 0]));
    const flags = Object.fromEntries(FLAGS.map(key => [key, {true: 0, false: 0, unknown: 0}]));
    const values = Object.fromEntries(TIMINGS.map(key => [key, []]));
    const invalidTimings = Object.fromEntries(TIMINGS.map(key => [key, 0]));
    let events = 0, invalidBodies = 0;
    // Only two event bodies are needed. Do not read consent, source or Task content.
    // CASE bounds bytes before returning a body to JavaScript; iteration bounds memory.
    const query = db.prepare(`SELECT type, at,
      CASE WHEN type IN ('voice.local_turn','voice.local_asr_timing')
        AND typeof(body)='text' AND length(CAST(body AS BLOB)) <= ${MAX_BODY_BYTES}
        THEN body ELSE NULL END AS selected_body
      FROM events WHERE at >= ? AND at < ? AND type IN (${TYPES.map(() => '?').join(',')})
      ORDER BY seq LIMIT ?`);
    for (const row of query.iterate(since, until, ...TYPES, MAX_EVENTS + 1)) {
      requireValue(++events <= MAX_EVENTS, 'DIAGNOSTIC_EVENT_LIMIT');
      requireValue(timestamp(row.at) !== null, 'DIAGNOSTIC_EVENT_INVALID');
      counts[row.type]++;
      if (row.type !== 'voice.local_turn' && row.type !== 'voice.local_asr_timing') continue;
      let body = null;
      try { body = JSON.parse(row.selected_body); } catch { /* Do not reflect parser errors. */ }
      if (!body || typeof body !== 'object' || Array.isArray(body)) {
        body = {}; invalidBodies++;
      }
      if (row.type === 'voice.local_turn') {
        for (const key of FLAGS) {
          const value = Object.hasOwn(body, key) ? body[key] : undefined;
          flags[key][value === true ? 'true' : value === false ? 'false' : 'unknown']++;
        }
      } else {
        for (const key of TIMINGS) {
          const value = Object.hasOwn(body, key) ? body[key] : undefined;
          if (typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= MAX_TIMING_MS) {
            values[key].push(value);
          } else invalidTimings[key]++;
        }
      }
    }
    const incomplete = invalidBodies > 0 || Object.values(flags).some(x => x.unknown > 0) ||
      Object.values(invalidTimings).some(n => n > 0);
    return {
      schema: 'kotodama.voice-diagnostics.v1',
      status: events === 0 ? 'NO_MATCHING_EVENTS' : incomplete ? 'INCOMPLETE_FIELDS' : 'OBSERVED',
      evidence: 'LOCAL_EVENT_OBSERVATIONS_ONLY',
      scope: 'INSTALLATION_TIME_WINDOW_NOT_SESSION_SCOPED',
      public_beta: 'NO_GO_UNPUBLISHED',
      declared_revision: revision, revision_verified: false,
      window: {since, until, end_exclusive: true},
      selected_events: events, event_counts: counts, local_turn_flags: flags,
      local_asr_ms: Object.fromEntries(TIMINGS.map(key => [key, distribution(values[key], invalidTimings[key])])),
      invalid_bodies: invalidBodies,
      unmeasured: {audible_replies: null, interruption_stop_ms: null,
        output_queue_ms: null, participants: null, mode_acceptance: null},
      claims: {live_acceptance: false, provider_connected: false,
        promotion: false, current_truth: false, final_human_go: false},
    };
  } catch (error) {
    if (error instanceof VoiceDiagnosticsError) throw error;
    throw new VoiceDiagnosticsError('DIAGNOSTIC_READ_FAILED');
  } finally {
    if (db) {
      try { if (transactionOpen) db.exec('ROLLBACK'); }
      catch { throw new VoiceDiagnosticsError('DIAGNOSTIC_CLOSE_FAILED'); }
      finally {
        try { db.close(); }
        catch { throw new VoiceDiagnosticsError('DIAGNOSTIC_CLOSE_FAILED'); }
      }
    }
  }
}
