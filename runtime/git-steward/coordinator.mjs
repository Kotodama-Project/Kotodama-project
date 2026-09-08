/** Internal Git work-cell coordinator. No HTTP, credentials, model calls or Git writes.
 * Call only behind a protected adapter which resolves identity and live Work/Grant
 * revisions. A lease is NOT a capability grant; receipts are trusted adapter input.
 */
export class Refusal extends Error {
  constructor(code) { super(code); this.name = 'Refusal'; this.code = code; }
}
const requireThat = (ok, code = 'INPUT_INVALID') => { if (!ok) throw new Refusal(code); };
const plain = v => v !== null && typeof v === 'object' && Object.getPrototypeOf(v) === Object.prototype;
const integer = (v, min, max) => Number.isSafeInteger(v) && v >= min && v <= max;
const ref = v => typeof v === 'string' && /^ref\/[a-zA-Z0-9][a-zA-Z0-9_./-]{0,190}$/.test(v) && !v.includes('..');
const id = v => typeof v === 'string' && /^[a-z0-9][a-z0-9-]{0,63}$/.test(v);
const sha = v => typeof v === 'string' && /^[0-9a-f]{40}$/.test(v);
const digest = v => typeof v === 'string' && /^[0-9a-f]{64}$/.test(v);
function keys(value, names) {
  requireThat(plain(value));
  requireThat(Object.keys(value).length === names.length && names.every(n => Object.hasOwn(value, n)));
}
function strings(value, check, limit = 64, min = 0) {
  requireThat(Array.isArray(value) && value.length >= min && value.length <= limit);
  requireThat(value.every(check) && new Set(value).size === value.length);
}
export function validPath(path, directory = true) {
  if (typeof path !== 'string' || !path || path.length > 512 || /[\x00-\x20\x7f\\:*?\[\]{}]/.test(path)) return false;
  const p = directory && path.endsWith('/') ? path.slice(0, -1) : path;
  return p.split('/').every(s => s && s !== '.' && s !== '..' && s.toLowerCase() !== '.git');
}
const covers = (scope, path) => scope === path || (scope.endsWith('/') && path.startsWith(scope));
// Reservations are deliberately conservative across case-insensitive hosts.
// A file and a directory at the same path cannot coexist in a Git tree. Keep
// write admission (covers) exact: reserving a file does not grant its children.
const reservationPath = p => p.replace(/\/$/, '').toLowerCase();
const overlaps = (a, b) => {
  const x = reservationPath(a), y = reservationPath(b);
  return x === y || x.startsWith(y + '/') || y.startsWith(x + '/');
};
function conflicts(a, b) {
  return a.work_ref === b.work_ref || a.conflict_keys.some(k => b.conflict_keys.includes(k)) ||
    a.write_paths.some(p => [...b.write_paths, ...b.read_paths].some(q => overlaps(p, q))) ||
    a.read_paths.some(p => b.write_paths.some(q => overlaps(p, q)));
}
function canonical(value, depth = 0) {
  requireThat(depth <= 12);
  if (value === null || typeof value === 'boolean' || typeof value === 'string') return JSON.stringify(value);
  if (typeof value === 'number') { requireThat(Number.isFinite(value)); return JSON.stringify(value); }
  if (Array.isArray(value)) { requireThat(value.length <= 1024); return '[' + value.map(v => canonical(v, depth + 1)).join(',') + ']'; }
  requireThat(plain(value) && Object.keys(value).length <= 64);
  return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + canonical(value[k], depth + 1)).join(',') + '}';
}
const held = cell => !['queued', 'cancelled', 'integrated'].includes(cell.state);
const effective = (cell, now) => cell.state === 'running' && now >= cell.until ? 'reconciling' : cell.state;
function validateSpec(s) {
  keys(s, ['id', 'work_ref', 'work_revision', 'grant_ref', 'context_digest', 'producer_ref', 'reviewer_ref',
    'target_ref', 'base_sha', 'write_paths', 'read_paths', 'conflict_keys', 'depends_on']);
  requireThat(id(s.id) && ref(s.work_ref) && ref(s.grant_ref) && digest(s.context_digest));
  requireThat(integer(s.work_revision, 1, Number.MAX_SAFE_INTEGER) && sha(s.base_sha));
  requireThat(ref(s.producer_ref) && ref(s.reviewer_ref) && s.producer_ref !== s.reviewer_ref, 'REVIEWER_NOT_INDEPENDENT');
  requireThat(typeof s.target_ref === 'string' && /^refs\/heads\/[a-zA-Z0-9][a-zA-Z0-9_./-]{0,190}$/.test(s.target_ref));
  requireThat(s.target_ref.split('/').every(x => x && !x.startsWith('.') && !x.endsWith('.') && !x.endsWith('.lock')) && !s.target_ref.includes('..'));
  strings(s.write_paths, p => validPath(p), 64, 1);
  strings(s.read_paths, p => validPath(p)); strings(s.conflict_keys, ref); strings(s.depends_on, id);
  requireThat(!s.depends_on.includes(s.id), 'DEPENDENCY_INVALID');
}
const commandFields = {
  add: ['spec'], claim: ['base_sha', 'lease_ms'], renew: ['epoch', 'lease_ms'],
  unknown: ['epoch'], stop: [], stopped: ['epoch', 'receipt_ref', 'disposition'],
  submit: ['epoch', 'base_sha', 'head_sha', 'tree_sha', 'diff_sha256', 'changed_paths', 'receipt_ref'],
  verify: ['base_sha', 'head_sha', 'diff_sha256', 'checks', 'receipt_ref'],
  assess: ['base_sha', 'head_sha'], integrated: ['base_sha', 'head_sha', 'merge_sha', 'receipt_ref']
};

/** The store transaction must synchronously commit state + result deduplication
 * atomically or roll back on throw. Never perform network I/O in this callback.
 */
export class GitSteward {
  constructor(store, policy) {
    keys(policy, ['repository_ref', 'coordinator_ref', 'attester_ref', 'required_checks',
      'max_concurrent', 'max_cells', 'max_commands', 'max_attempts', 'max_lease_ms', 'max_run_ms']);
    requireThat(ref(policy.repository_ref) && ref(policy.coordinator_ref) && ref(policy.attester_ref));
    requireThat(Array.isArray(policy.required_checks) && policy.required_checks.length > 0 && policy.required_checks.length <= 32);
    policy.required_checks.forEach(c => { keys(c, ['name', 'issuer_ref']); requireThat(id(c.name) && ref(c.issuer_ref)); });
    strings(policy.required_checks.map(c => c.name), id, 32, 1);
    for (const k of ['max_concurrent', 'max_cells', 'max_commands', 'max_attempts']) requireThat(integer(policy[k], 1, k === 'max_commands' ? 8192 : 256));
    requireThat(policy.max_concurrent <= policy.max_cells);
    requireThat(integer(policy.max_lease_ms, 1, 300000) && integer(policy.max_run_ms, policy.max_lease_ms, 86400000));
    this.store = store; this.policy = structuredClone(policy);
  }
  execute(actor, command, now) {
    requireThat(ref(actor) && integer(now, 0, 8640000000000000));
    requireThat(plain(command) && Object.hasOwn(commandFields, command.type));
    keys(command, ['request_id', 'type', 'cell_id', ...commandFields[command.type]]);
    requireThat(id(command.request_id) && id(command.cell_id));
    const fingerprint = canonical({ actor, command });
    requireThat(new TextEncoder().encode(fingerprint).byteLength <= 65536, 'INPUT_TOO_LARGE');
    const transaction = this.store.transaction(stored => {
      const state = stored === null ? { version: 2, policy: this.policy, last_now: 0, epoch: 0, cells: {}, commands: {}, events: [] } : stored;
      requireThat(state.version === 2, 'JOURNAL_VERSION_UNSUPPORTED');
      requireThat(canonical(state.policy) === canonical(this.policy), 'JOURNAL_BINDING_MISMATCH');
      requireThat(integer(state.last_now, 0, now) && plain(state.cells) && plain(state.commands) && Array.isArray(state.events), 'JOURNAL_INVALID');
      const observationOnly = structuredClone(state);
      observationOnly.last_now = now;
      // A business refusal rolls back cell changes and deduplication, while the
      // trusted clock observation must survive. Otherwise expiry can be undone
      // by a backwards timestamp after a refused submit, not just after replay.
      try {
      const previous = Object.hasOwn(state.commands, command.request_id) ? state.commands[command.request_id] : null;
      if (previous) {
        requireThat(previous === fingerprint, 'IDEMPOTENCY_CONFLICT');
        // Replays also observe time. Persist that high-water mark atomically so
        // a restart/backwards clock cannot resurrect an already expired lease.
        state.last_now = now;
        return { state, result: { projection: this.project(state, command.cell_id, now, true) } };
      }
      requireThat(Object.keys(state.commands).length < this.policy.max_commands, 'JOURNAL_FULL');
      const c = command;
      let cell = Object.hasOwn(state.cells, c.cell_id) ? state.cells[c.cell_id] : undefined;
      const planner = () => requireThat(actor === this.policy.coordinator_ref, 'ACTOR_FORBIDDEN');
      const attester = () => requireThat(actor === this.policy.attester_ref, 'ACTOR_FORBIDDEN');
      const currentLease = () => {
        requireThat(actor === cell.spec.producer_ref, 'ACTOR_FORBIDDEN');
        requireThat(integer(c.epoch, 1, Number.MAX_SAFE_INTEGER) && c.epoch === cell.epoch, 'STALE_FENCE');
        requireThat(cell.state === 'running' && now < cell.until, 'LEASE_NOT_ACTIVE');
      };
      if (c.type === 'add') {
        planner(); validateSpec(c.spec);
        requireThat(c.cell_id === c.spec.id && !cell, 'CELL_EXISTS');
        requireThat(Object.keys(state.cells).length < this.policy.max_cells, 'CELL_BUDGET');
        requireThat(c.spec.producer_ref !== this.policy.attester_ref, 'ATTESTER_NOT_INDEPENDENT');
        requireThat(!Object.values(state.cells).some(x => x.spec.work_ref === c.spec.work_ref && x.spec.work_revision === c.spec.work_revision), 'WORK_ALREADY_BOUND');
        const prior = Object.values(state.cells).filter(x => x.spec.work_ref === c.spec.work_ref);
        requireThat(prior.every(x => x.spec.work_revision < c.spec.work_revision), 'WORK_REVISION_STALE');
        requireThat(c.spec.depends_on.every(d => Object.hasOwn(state.cells, d)), 'DEPENDENCY_INVALID');
        requireThat(c.spec.depends_on.every(d => !state.cells[d].superseded_by && !state.cells[d].invalidated_by &&
          state.cells[d].state !== 'cancelled' && state.cells[d].spec.work_ref !== c.spec.work_ref), 'DEPENDENCY_SUPERSEDED');
        // The protected Work owner admits only an authoritative current revision.
        // A correction invalidates earlier work atomically, but never pretends
        // that an old executor stopped. Keep its reservation until attested stop.
        for (const older of prior) {
          older.superseded_by = c.cell_id;
          if (!['integrated', 'cancelled'].includes(older.state)) older.state = older.state === 'queued' ? 'cancelled' : 'stopping';
          state.events.push({ sequence: state.events.length + 1, request_id: c.request_id, actor_ref: actor,
            type: 'superseded', cell_id: older.spec.id, at: now, epoch: older.epoch, state: older.state,
            superseded_by: c.cell_id, receipt_ref: null, output: older.output ? structuredClone(older.output) : null });
        }
        // A recorded integration stays historical evidence. Its consumers must
        // nevertheless rebind after an upstream correction, even across several
        // dependency levels. This is a bounded DAG traversal, not Work creation.
        const invalidated = new Set(prior.map(x => x.spec.id));
        let changed = true;
        while (changed) {
          changed = false;
          for (const consumer of Object.values(state.cells)) {
            if (invalidated.has(consumer.spec.id) || !consumer.spec.depends_on.some(d => invalidated.has(d))) continue;
            invalidated.add(consumer.spec.id); changed = true;
            consumer.invalidated_by = c.cell_id;
            if (!['integrated', 'cancelled'].includes(consumer.state)) consumer.state = consumer.state === 'queued' ? 'cancelled' : 'stopping';
            state.events.push({ sequence: state.events.length + 1, request_id: c.request_id, actor_ref: actor,
              type: 'dependency_invalidated', cell_id: consumer.spec.id, at: now, epoch: consumer.epoch,
              state: consumer.state, invalidated_by: c.cell_id, receipt_ref: null,
              output: consumer.output ? structuredClone(consumer.output) : null });
          }
        }
        requireThat(c.spec.depends_on.every(d => !invalidated.has(d)), 'DEPENDENCY_SUPERSEDED');
        cell = { spec: structuredClone(c.spec), state: 'queued', epoch: 0, attempts: 0, until: 0, started: 0, output: null, verification: null };
        state.cells[c.cell_id] = cell;
      } else {
        requireThat(cell !== undefined, 'CELL_UNKNOWN');
        switch (c.type) {
          case 'claim': {
            requireThat(actor === cell.spec.producer_ref, 'ACTOR_FORBIDDEN');
            requireThat(!cell.superseded_by, 'WORK_REVISION_STALE');
            requireThat(!cell.invalidated_by, 'DEPENDENCY_SUPERSEDED');
            requireThat(cell.state === 'queued', 'CELL_NOT_QUEUED');
            requireThat(sha(c.base_sha) && c.base_sha === cell.spec.base_sha, 'BASE_MOVED');
            requireThat(cell.spec.depends_on.every(d => !state.cells[d].superseded_by && !state.cells[d].invalidated_by), 'DEPENDENCY_SUPERSEDED');
            requireThat(cell.spec.depends_on.every(d => state.cells[d].state === 'integrated'), 'DEPENDENCY_NOT_INTEGRATED');
            requireThat(cell.attempts < this.policy.max_attempts, 'ATTEMPT_BUDGET');
            requireThat(integer(c.lease_ms, 1, this.policy.max_lease_ms));
            const active = Object.values(state.cells).filter(held);
            requireThat(active.length < this.policy.max_concurrent, 'CONCURRENCY_BUDGET');
            requireThat(!active.some(x => conflicts(cell.spec, x.spec)), 'SCOPE_BUSY');
            requireThat(Number.isSafeInteger(state.epoch + 1), 'EPOCH_EXHAUSTED');
            cell.epoch = ++state.epoch; cell.attempts++; cell.started = now; cell.until = now + c.lease_ms; cell.state = 'running';
            break;
          }
          case 'renew':
            currentLease(); requireThat(integer(c.lease_ms, 1, this.policy.max_lease_ms));
            requireThat(now + c.lease_ms <= cell.started + this.policy.max_run_ms, 'RUNTIME_BUDGET');
            requireThat(now + c.lease_ms >= cell.until, 'LEASE_SHORTENING');
            cell.until = now + c.lease_ms; break;
          case 'unknown':
            currentLease(); cell.state = 'reconciling'; break;
          case 'stop':
            planner(); requireThat(!['cancelled', 'integrated'].includes(cell.state), 'CELL_TERMINAL');
            cell.state = cell.state === 'queued' ? 'cancelled' : 'stopping'; break;
          case 'stopped':
            attester(); requireThat(['stopping', 'reconciling'].includes(effective(cell, now)), 'STOP_NOT_PENDING');
            requireThat(integer(c.epoch, 1, Number.MAX_SAFE_INTEGER) && c.epoch === cell.epoch, 'STALE_FENCE');
            requireThat(ref(c.receipt_ref) && ['cancelled', 'queued'].includes(c.disposition));
            requireThat(!cell.superseded_by || c.disposition === 'cancelled', 'WORK_REVISION_STALE');
            requireThat(!cell.invalidated_by || c.disposition === 'cancelled', 'DEPENDENCY_SUPERSEDED');
            // The adapter must prove the previous executor is stopped/fenced and
            // preserve its output before asking to release these scopes.
            cell.state = c.disposition; cell.output = null; cell.verification = null; break;
          case 'submit':
            currentLease(); requireThat(sha(c.base_sha) && c.base_sha === cell.spec.base_sha, 'BASE_MOVED');
            requireThat(sha(c.head_sha) && c.head_sha !== c.base_sha && sha(c.tree_sha) && digest(c.diff_sha256) && ref(c.receipt_ref));
            strings(c.changed_paths, p => validPath(p, false), 512, 1);
            requireThat(c.changed_paths.every(p => cell.spec.write_paths.some(s => covers(s, p))), 'PATH_OUT_OF_SCOPE');
            cell.output = { base_sha: c.base_sha, head_sha: c.head_sha, tree_sha: c.tree_sha, diff_sha256: c.diff_sha256,
              changed_paths: [...c.changed_paths], receipt_ref: c.receipt_ref };
            cell.state = 'candidate'; break;
          case 'verify': {
            requireThat(actor === cell.spec.reviewer_ref && actor !== cell.spec.producer_ref, 'REVIEWER_NOT_INDEPENDENT');
            requireThat(cell.state === 'candidate', 'NOT_CANDIDATE');
            this.bindOutput(cell, c); requireThat(ref(c.receipt_ref));
            requireThat(Array.isArray(c.checks) && c.checks.length === this.policy.required_checks.length, 'CHECKS_INCOMPLETE');
            const seen = new Set();
            c.checks.forEach(check => {
              keys(check, ['name', 'issuer_ref', 'head_sha', 'conclusion', 'receipt_ref']);
              const required = this.policy.required_checks.find(x => x.name === check.name);
              requireThat(required && !seen.has(check.name) && check.issuer_ref === required.issuer_ref &&
                check.head_sha === cell.output.head_sha && check.conclusion === 'success' && ref(check.receipt_ref), 'CHECKS_NOT_TRUSTED');
              seen.add(check.name);
            });
            cell.verification = { reviewer_ref: actor, receipt_ref: c.receipt_ref, checks: structuredClone(c.checks) };
            cell.state = 'verified_candidate'; break;
          }
          case 'assess':
            attester(); requireThat(cell.state === 'verified_candidate', 'NOT_VERIFIED'); this.bindOutput(cell, c); break;
          case 'integrated':
            attester(); requireThat(cell.state === 'verified_candidate', 'NOT_VERIFIED'); this.bindOutput(cell, c);
            requireThat(sha(c.merge_sha) && c.merge_sha !== c.base_sha && ref(c.receipt_ref));
            cell.integration = { merge_sha: c.merge_sha, receipt_ref: c.receipt_ref };
            cell.state = 'integrated'; break;
        }
      }
      state.last_now = now;
      state.commands[c.request_id] = fingerprint;
      // Internal operational journal only; not the canonical Task/event ledger.
      state.events.push({ sequence: state.events.length + 1, request_id: c.request_id, actor_ref: actor,
        type: c.type, cell_id: c.cell_id, at: now, epoch: cell.epoch, state: cell.state,
        receipt_ref: c.receipt_ref ?? null, output: cell.output ? structuredClone(cell.output) : null });
      requireThat(new TextEncoder().encode(JSON.stringify(state)).byteLength <= 4 * 1024 * 1024, 'JOURNAL_FULL');
      return { state, result: { projection: this.project(state, c.cell_id, now, false) } };
      } catch (error) {
        if (!(error instanceof Refusal)) throw error;
        return { state: observationOnly, result: { refusal: error.code } };
      }
    });
    if (Object.hasOwn(transaction, 'refusal')) throw new Refusal(transaction.refusal);
    return transaction.projection;
  }
  bindOutput(cell, c) {
    requireThat(sha(c.base_sha) && c.base_sha === cell.output.base_sha, 'BASE_MOVED');
    requireThat(sha(c.head_sha) && c.head_sha === cell.output.head_sha, 'HEAD_MOVED');
    if (Object.hasOwn(c, 'diff_sha256')) requireThat(c.diff_sha256 === cell.output.diff_sha256, 'DIFF_MOVED');
  }
  project(state, cellId, now, replayed) {
    const cell = state.cells[cellId];
    requireThat(cell !== undefined, 'JOURNAL_INVALID');
    return { repository_ref: this.policy.repository_ref, cell_id: cellId, work_ref: cell.spec.work_ref,
      work_revision: cell.spec.work_revision, context_digest: cell.spec.context_digest,
      superseded_by: cell.superseded_by ?? null,
      invalidated_by: cell.invalidated_by ?? null,
      state: effective(cell, now), epoch: cell.epoch, attempts: cell.attempts, expires_at: cell.until,
      lease_usable: cell.state === 'running' && now < cell.until,
      branch: cell.epoch ? `work/${cellId}-e${cell.epoch}` : null,
      workspace_ref: cell.epoch ? `ref/workspace/${cellId}/e${cell.epoch}` : null,
      candidate: cell.output ? structuredClone(cell.output) : null,
      replayed, merge_authorized: false, task_completed: false, runtime_deployed: false };
  }
}
