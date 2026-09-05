import { createServer } from "node:http";
import { createHash, randomBytes, randomUUID, timingSafeEqual } from "node:crypto";
import { lstatSync, mkdirSync, openSync, closeSync, fsyncSync, readFileSync, writeFileSync, renameSync, rmdirSync, unlinkSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { startReviewGateway, strictJson } from "../local-review-gateway/server.mjs";
import { runCodexBrief, validateBrief } from "./codex-runner.mjs";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const principal = /^urn:kotodama:principal:[0-9a-f-]{36}$/;
const hex = /^[0-9a-f]{64}$/;
const hash = (value) => createHash("sha256").update(value).digest("hex");
const closed = (value, keys) => value && typeof value === "object" && !Array.isArray(value)
  && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
const GRANT_KEYS = ["work_order_ref", "requester_ref", "worker_ref", "handoff_id", "source_revision", "source_sha256", "policy_revision", "expires_at", "max_invocations", "operation"];
export const grantDigest = (grant) => hash(JSON.stringify(GRANT_KEYS.map((key) => [key, grant[key]])));
export function projectionDigest(value) {
  const ordered = (item) => Array.isArray(item) ? item.map(ordered)
    : item && typeof item === "object" ? Object.fromEntries(Object.keys(item).sort().map((key) => [key, ordered(item[key])])) : item;
  return hash(JSON.stringify(ordered(value)));
}

function prepareInput(p) {
  const input = JSON.stringify({ overview: p.overview, speaker_highlights: p.speaker_highlights.map((v) => v.summary),
    decision_candidates: p.decisions.map((v) => v.summary), todos: p.todos.map((v) => v.summary),
    open_questions: p.open_questions.map((v) => v.summary) });
  if (Buffer.byteLength(input) > 16384 || new Set(p.open_questions.map((v) => v.summary)).size > 32) throw new Error("source_exceeds_brief_scope");
  return input;
}

function checkedDirectory(value) {
  const root = resolve(value);
  for (let p = root; ; p = dirname(p)) {
    const info = lstatSync(p);
    if (!info.isDirectory() || info.isSymbolicLink()) throw new Error("state_path_denied");
    if (dirname(p) === p) break;
  }
  return root;
}

function saveJobs(root, jobs) {
  const body = Buffer.from(JSON.stringify({ schema: "kotodama/brief-invocations/v1", jobs }));
  if (body.length > 2_097_152) throw new Error("job_store_limit");
  const temporary = join(root, `.${randomUUID()}.tmp`);
  const fd = openSync(temporary, "wx", 0o600);
  try { writeFileSync(fd, body); fsyncSync(fd); } finally { closeSync(fd); }
  try { renameSync(temporary, join(root, "invocations.json")); }
  catch (error) { unlinkSync(temporary); throw error; }
}

function loadJobs(root) {
  try {
    const path = join(root, "invocations.json");
    const info = lstatSync(path);
    if (!info.isFile() || info.isSymbolicLink() || info.nlink !== 1 || info.size > 2_097_152) throw new Error("job_store_denied");
    const store = strictJson(readFileSync(path));
    if (!closed(store, ["schema", "jobs"]) || store.schema !== "kotodama/brief-invocations/v1"
      || !Array.isArray(store.jobs) || store.jobs.length > 32) throw new Error("job_store_denied");
    const ids = new Set();
    for (const job of store.jobs) {
      if (!closed(job, ["request_id", "fingerprint", "requester_ref", "handoff_id", "source_revision", "policy_revision", "binding_sha256", "state", "result"])
        || !uuid.test(job.request_id) || ids.has(job.request_id) || !hex.test(job.fingerprint)
        || !principal.test(job.requester_ref) || typeof job.handoff_id !== "string" || !/^[a-z0-9][a-z0-9-]{0,127}$/.test(job.handoff_id)
        || !Number.isSafeInteger(job.source_revision) || job.source_revision < 1
        || !Number.isSafeInteger(job.policy_revision) || job.policy_revision < 1 || !hex.test(job.binding_sha256)
        || !["running", "ready", "failed", "interrupted"].includes(job.state)) throw new Error("job_store_denied");
      ids.add(job.request_id);
      if (job.state === "ready") validateBrief(job.result?.brief);
      else if (job.result !== null) throw new Error("job_store_denied");
    }
    return store.jobs;
  } catch (error) { if (error.code === "ENOENT") return []; throw error; }
}

function reply(response, status, body) {
  response.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", "x-content-type-options": "nosniff" });
  response.end(JSON.stringify(body));
}

async function requestBody(request) {
  if (request.headers["content-type"] !== "application/json") throw new Error("body_denied");
  const chunks = []; let size = 0;
  for await (const bytes of request.iterator({ destroyOnReturn: false })) {
    size += bytes.length; if (size > 2048) { request.resume(); throw new Error("body_denied"); }
    chunks.push(bytes);
  }
  const value = strictJson(Buffer.concat(chunks));
  if (!closed(value, ["request_id", "source_revision", "binding_sha256"]) || !uuid.test(value.request_id) || !hex.test(value.binding_sha256)
    || !Number.isSafeInteger(value.source_revision) || value.source_revision < 1) throw new Error("body_denied");
  return value;
}

export async function startBriefBridge({ stateRoot, reviewStateRoot, seeds, serviceSecret, expectedHost, grant, runner, port = 0 }, { invoke = runCodexBrief, shutdownTimeoutMs = 5000 } = {}) {
  if (typeof serviceSecret !== "string" || !/^[0-9a-f]{64}$/.test(serviceSecret)
    || typeof expectedHost !== "string" || !expectedHost || /[\s/]/.test(expectedHost)
    || !closed(grant, GRANT_KEYS) || grant.operation !== "DRAFT_REQUIREMENTS"
    || typeof grant.work_order_ref !== "string" || !/^work-order:[a-z0-9][a-z0-9-]{0,127}$/.test(grant.work_order_ref)
    || typeof grant.handoff_id !== "string" || !/^[a-z0-9][a-z0-9-]{0,127}$/.test(grant.handoff_id)
    || typeof grant.requester_ref !== "string" || typeof grant.worker_ref !== "string"
    || !principal.test(grant.requester_ref) || !principal.test(grant.worker_ref) || grant.requester_ref === grant.worker_ref
    || !Number.isSafeInteger(grant.max_invocations) || grant.max_invocations < 1 || grant.max_invocations > 3
    || !Number.isSafeInteger(grant.source_revision) || grant.source_revision < 1
    || !Number.isSafeInteger(grant.policy_revision) || grant.policy_revision < 1
    || typeof grant.source_sha256 !== "string" || !hex.test(grant.source_sha256) || typeof grant.expires_at !== "string"
    || !Number.isFinite(Date.parse(grant.expires_at)) || new Date(grant.expires_at).toISOString() !== grant.expires_at
    || !Number.isInteger(port) || port < 0 || port > 65535) throw new Error("bridge_configuration_denied");
  const boundGrant = structuredClone(grant);
  const grantBinding = JSON.stringify(GRANT_KEYS.map((key) => [key, boundGrant[key]]));
  const bindingSha256 = grantDigest(boundGrant);
  const fingerprintFor = (requester, body) => hash(JSON.stringify([requester, body.request_id, body.source_revision, body.binding_sha256, grantBinding]));
  const root = checkedDirectory(stateRoot);
  const lock = join(root, ".brief-writer.lock");
  mkdirSync(lock, { mode: 0o700 });
  let gateway;
  let jobs;
  try {
    gateway = await startReviewGateway({ stateRoot: reviewStateRoot, seeds, clientId: "in-process-brief-adapter", clientSecret: randomBytes(32).toString("hex") });
    jobs = loadJobs(root).map((job) => job.state === "running" ? { ...job, state: "interrupted" } : job);
    saveJobs(root, jobs);
  } catch (error) { if (gateway) await gateway.close(); rmdirSync(lock); throw error; }
  let active;
  let closing = false;
  let sealedAfterShutdown = false;
  const revokeMarker = join(root, ".grant-revoked");
  let grantRevoked = false;
  try { const info = lstatSync(revokeMarker); if (!info.isDirectory() || info.isSymbolicLink()) throw new Error("revocation_marker_denied"); grantRevoked = true; }
  catch (error) { if (error.code !== "ENOENT") { await gateway.close(); rmdirSync(lock); throw error; } }
  const secretHash = Buffer.from(hash(serviceSecret), "hex");
  function admitted(requesterRef) {
    if (closing || grantRevoked || requesterRef !== boundGrant.requester_ref || Date.now() >= Date.parse(boundGrant.expires_at)) throw new Error("access_denied");
    const user = gateway.inspectHandoff(requesterRef, boundGrant.handoff_id);
    const worker = gateway.inspectHandoff(boundGrant.worker_ref, boundGrant.handoff_id);
    if (user.principal_kind !== "human" || worker.principal_kind !== "agent"
      || user.projection.revision !== boundGrant.source_revision || user.policy_revision !== boundGrant.policy_revision
      || worker.policy_revision !== user.policy_revision || projectionDigest(user.projection) !== boundGrant.source_sha256) throw new Error("source_or_grant_drift");
    prepareInput(user.projection); // Refuse oversized scope before consuming an invocation.
    return user;
  }
  async function perform(job) {
    const controller = new AbortController();
    active = { request_id: job.request_id, controller, promise: null };
    let result = null;
    let state = "failed";
    try {
      const source = admitted(job.requester_ref);
      const p = source.projection;
      const input = prepareInput(p);
      result = await invoke({ ...runner, input, signal: controller.signal });
      admitted(job.requester_ref);
      validateBrief(result.brief);
      // Source questions are unresolved evidence. A model cannot silently remove them.
      result = { ...result, brief: { ...result.brief,
        open_questions: [...new Set([...p.open_questions.map((v) => v.summary), ...result.brief.open_questions])] } };
      validateBrief(result.brief);
      state = "ready";
    } catch { result = null; }
    finally {
      if (sealedAfterShutdown) { active = null; return; }
      const next = jobs.map((item) => item.request_id === job.request_id ? { ...item, result, state } : item);
      try { saveJobs(root, next); jobs = next; }
      catch { closing = true; }
      active = null;
    }
  }
  const server = createServer({ maxHeaderSize: 8192, requestTimeout: 5000, headersTimeout: 5000 }, async (request, response) => {
    try {
      if (closing || request.headers.host !== expectedHost || request.headers.origin) return reply(response, 403, { error: "request_denied" });
      const token = request.headers.authorization;
      if (typeof token !== "string" || token.length > 1000 || !token.startsWith("Bearer ")
        || !timingSafeEqual(Buffer.from(hash(token.slice(7)), "hex"), secretHash)) return reply(response, 401, { error: "authentication_required" });
      const requester = request.headers["x-kotodama-principal"];
      if (request.method === "POST" && request.url === "/v1/revoke") {
        if (requester !== boundGrant.requester_ref) return reply(response, 404, { error: "information_unavailable" });
        request.resume();
        if (!grantRevoked) { mkdirSync(revokeMarker, { mode: 0o700 }); grantRevoked = true; }
        active?.controller.abort();
        return reply(response, 200, { revoked: true });
      }
      let source;
      try { source = admitted(requester); } catch { return reply(response, 404, { error: "information_unavailable" }); }
      if (request.method === "GET" && request.url === "/v1/admission") return reply(response, 200, { allowed: true, binding_sha256: bindingSha256 });
      if (request.method === "GET" && request.url === "/v1/handoff") return reply(response, 200, { handoff_id: boundGrant.handoff_id, revision: source.projection.revision, overview: source.projection.overview, binding_sha256: bindingSha256 });
      if (request.method === "POST" && request.url === "/v1/briefs") {
        let body; try { body = await requestBody(request); admitted(requester); } catch { return reply(response, 400, { error: "request_denied" }); }
        if (body.source_revision !== boundGrant.source_revision || body.binding_sha256 !== bindingSha256) return reply(response, 409, { error: "revision_conflict" });
        const fingerprint = fingerprintFor(requester, body);
        let job = jobs.find((item) => item.request_id === body.request_id);
        if (job && job.fingerprint !== fingerprint) return reply(response, 409, { error: "request_conflict" });
        if (!job) {
          if (active || jobs.length >= boundGrant.max_invocations) return reply(response, 409, { error: "invocation_budget_or_busy" });
          job = { request_id: body.request_id, fingerprint, requester_ref: requester, handoff_id: boundGrant.handoff_id,
            source_revision: body.source_revision, policy_revision: boundGrant.policy_revision, binding_sha256: bindingSha256, state: "running", result: null };
          const next = [...jobs, job]; saveJobs(root, next); jobs = next;
          const promise = perform(job); if (active) active.promise = promise;
          promise.catch(() => {});
        }
        return reply(response, 202, { request_id: job.request_id, state: job.state, task_state_changed: false });
      }
      const match = request.url.match(/^\/v1\/briefs\/([0-9a-f-]{36})$/);
      if (request.method === "GET" && match && uuid.test(match[1])) {
        const job = jobs.find((item) => item.request_id === match[1] && item.requester_ref === requester);
        if (!job || job.handoff_id !== boundGrant.handoff_id || job.fingerprint !== fingerprintFor(requester, job)
          || job.source_revision !== source.projection.revision || job.policy_revision !== source.policy_revision) return reply(response, 404, { error: "information_unavailable" });
        return reply(response, 200, { request_id: job.request_id, state: job.state,
          brief: job.state === "ready" ? job.result.brief : null, task_state_changed: false, publication: false });
      }
      return reply(response, 404, { error: "route_unavailable" });
    } catch { reply(response, 503, { error: "bridge_unavailable" }); }
  });
  server.maxConnections = 8;
  server.setTimeout(5000, (socket) => socket.destroy());
  try { await new Promise((accept, reject) => { server.once("error", reject); server.listen(port, "127.0.0.1", accept); }); }
  catch (error) { await gateway.close(); rmdirSync(lock); throw error; }
  let closePromise;
  return { origin: `http://127.0.0.1:${server.address().port}`,
    updateAccessPolicy: gateway.updateAccessPolicy,
    close() {
      if (!closePromise) {
        closing = true; const pending = active?.promise; active?.controller.abort();
        closePromise = (async () => {
          await new Promise((accept) => { server.close(accept); server.closeAllConnections(); });
          let timer;
          const finished = !pending || await Promise.race([pending.then(() => true, () => true),
            new Promise((accept) => { timer = setTimeout(() => accept(false), shutdownTimeoutMs); })]);
          clearTimeout(timer);
          if (!finished) {
            sealedAfterShutdown = true;
            jobs = jobs.map((job) => job.state === "running" ? { ...job, state: "interrupted", result: null } : job);
            saveJobs(root, jobs);
            await gateway.close();
            // Retain the bridge writer lock: a runner that ignored cancellation may still be active.
            throw new Error("shutdown_termination_uncertain");
          }
          await gateway.close(); rmdirSync(lock);
        })();
      }
      return closePromise;
    },
  };
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    if (process.argv.length !== 3) throw new Error("usage");
    const configPath = resolve(process.argv[2]);
    const info = lstatSync(configPath);
    if (!info.isFile() || info.isSymbolicLink() || info.nlink !== 1 || info.size > 65536) throw new Error("config_denied");
    const config = strictJson(readFileSync(configPath));
    config.serviceSecret = process.env.KOTODAMA_BRIDGE_SECRET;
    const bridge = await startBriefBridge(config);
    process.stdout.write("Private Codex brief bridge ready.\n");
    for (const signal of ["SIGINT", "SIGTERM"]) process.once(signal, () => bridge.close().catch(() => { process.exitCode = 1; }));
  } catch { process.stderr.write("Brief bridge start refused. Check the private operator configuration.\n"); process.exitCode = 1; }
}
