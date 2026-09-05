import { createServer } from "node:http";
import { createHash, randomUUID, timingSafeEqual } from "node:crypto";
import {
  closeSync, constants, fstatSync, fsyncSync, lstatSync, mkdirSync, openSync, readFileSync, readSync, renameSync,
  rmdirSync, unlinkSync, writeFileSync,
} from "node:fs";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { isDeepStrictEqual } from "node:util";
import { sanitizeProjection, validateReview } from "../cloudflare-edge/src/index.js";
import { syntheticCatalog } from "./synthetic-fixture.mjs";
import { canAccess, validateAccessPolicy, validatePrincipals } from "./access-policy.mjs";

const MAX_STORE_BYTES = 4_194_304;
const MAX_RECORDS = 64;
const MAX_REVIEW_BYTES = 16_384;
const STORE_SCHEMA = "kotodama/local-voice-review-candidates/v2";
const ACTOR_DIGEST = /^[0-9a-f]{64}$/;
const decoder = new TextDecoder("utf-8", { fatal: true });
const hash = (value) => createHash("sha256").update(value).digest();
const closed = (value, keys) => value && typeof value === "object" && !Array.isArray(value)
  && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));

// JSON.parse validates grammar; this bounded lexical pass also rejects duplicate keys.
export function strictJson(bytes) {
  const text = decoder.decode(bytes);
  const stack = [];
  for (let i = 0; i < text.length; i += 1) {
    if (text[i] === '"') {
      const start = i;
      for (i += 1; i < text.length; i += 1) {
        if (text[i] === "\\") i += 1;
        else if (text[i] === '"') break;
      }
      const token = JSON.parse(text.slice(start, i + 1));
      let next = i + 1;
      while (/\s/.test(text[next] ?? "") && next < text.length) next += 1;
      if (text[next] === ":") {
        const keys = stack.at(-1);
        if (!(keys instanceof Set) || keys.has(token)) throw new Error("invalid_json");
        keys.add(token);
      }
    } else if (text[i] === "{" || text[i] === "[") {
      stack.push(text[i] === "{" ? new Set() : null);
      if (stack.length > 32) throw new Error("invalid_json");
    } else if (text[i] === "}" || text[i] === "]") stack.pop();
  }
  return JSON.parse(text);
}

function actorDigest(actor) {
  if (!closed(actor, ["subject", "email"])) throw new Error("actor_denied");
  const values = [actor.subject, actor.email];
  if (values.every((value) => value === null)
    || values.some((value) => value !== null && (typeof value !== "string"
      || !/^[\x21-\x7e]{1,1024}$/.test(value)))) throw new Error("actor_denied");
  return hash(JSON.stringify(values)).toString("hex");
}

function validateCatalog(catalog) {
  if (!closed(catalog, ["principals", "records"])) throw new Error("store_denied");
  const principalRefs = validatePrincipals(catalog.principals);
  const { records } = catalog;
  if (!Array.isArray(records) || !records.length || records.length > MAX_RECORDS) throw new Error("store_denied");
  const identities = new Set();
  const policies = new Set();
  for (const record of records) {
    if (!closed(record, ["projection", "access_policy", "policy_history"])
      || !isDeepStrictEqual(sanitizeProjection(record.projection), record.projection)) throw new Error("store_denied");
    const policy = validateAccessPolicy(record.access_policy, principalRefs);
    if (policies.has(policy.policy_id) || !Array.isArray(record.policy_history)
      || record.policy_history.length !== policy.revision - 1) throw new Error("store_denied");
    for (const [index, previous] of record.policy_history.entries()) {
      validateAccessPolicy(previous, principalRefs);
      if (previous.revision !== index + 1 || previous.policy_id !== policy.policy_id) throw new Error("store_denied");
    }
    policies.add(policy.policy_id);
    const key = record.projection.handoff_id;
    if (identities.has(key)) throw new Error("store_denied");
    identities.add(key);
  }
  return catalog;
}

function recordsFromSeeds(seeds) {
  if (!closed(seeds, ["principals", "records"])) throw new Error("seed_required");
  try {
    if (!Array.isArray(seeds.principals) || !Array.isArray(seeds.records)) throw new Error("seed_denied");
    return validateCatalog({
      principals: seeds.principals.map((principal) => {
        if (!closed(principal, ["principal_ref", "kind", "actor"])) throw new Error("seed_denied");
        return { principal_ref: principal.principal_ref, kind: principal.kind, actor_sha256: actorDigest(principal.actor) };
      }),
      records: seeds.records.map((seed) => {
        if (!closed(seed, ["projection", "access_policy"]) || seed.projection?.revision !== 1
          || seed.projection?.human_review?.state !== "pending" || seed.access_policy?.revision !== 1) throw new Error("seed_denied");
        return { projection: seed.projection, access_policy: seed.access_policy, policy_history: [] };
      }),
    });
  } catch { throw new Error("seed_denied"); }
}

function checkedRoot(value) {
  if (typeof value !== "string" || !value) throw new Error("configuration_denied");
  const root = resolve(value);
  for (let path = root; ; path = dirname(path)) {
    const info = lstatSync(path);
    if (!info.isDirectory() || info.isSymbolicLink()) throw new Error("store_path_denied");
    if (dirname(path) === path) break;
  }
  return root;
}

function readStore(path) {
  const info = lstatSync(path);
  if (!info.isFile() || info.isSymbolicLink() || info.nlink !== 1 || info.size > MAX_STORE_BYTES) throw new Error("store_denied");
  const value = strictJson(readFileSync(path));
  if (!closed(value, ["schema", "catalog"]) || value.schema !== STORE_SCHEMA) throw new Error("store_denied");
  return validateCatalog(value.catalog);
}

/** Internal operator inspection: no projection body or authentication binding is returned. */
export function readAccessMetadata(stateRoot) {
  const catalog = readStore(join(checkedRoot(stateRoot), "voice-reviews.json"));
  return {
    schema: "kotodama/information-access-inventory/v1",
    principals: catalog.principals.map(({ principal_ref, kind }) => ({ principal_ref, kind })),
    information: catalog.records.map(({ projection, access_policy, policy_history }) => ({
      information_ref: projection.handoff_id, information_revision: projection.revision,
      access_policy, policy_history,
    })),
    internal_only: true, publication_authorized: false,
  };
}

function readImport(path, expectedSha256) {
  const absolute = resolve(path);
  checkedRoot(dirname(absolute));
  const before = lstatSync(absolute);
  if (!before.isFile() || before.isSymbolicLink() || before.nlink !== 1 || before.size > MAX_STORE_BYTES) throw new Error("import_file_denied");
  const file = openSync(absolute, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  try {
    const opened = fstatSync(file);
    if (!opened.isFile() || opened.nlink !== 1 || opened.dev !== before.dev || opened.ino !== before.ino
      || opened.size !== before.size) throw new Error("import_file_denied");
    const buffer = Buffer.alloc(MAX_STORE_BYTES + 1);
    let length = 0;
    while (length < buffer.length) {
      const count = readSync(file, buffer, length, buffer.length - length, null);
      if (!count) break;
      length += count;
    }
    if (length > MAX_STORE_BYTES || length !== opened.size) throw new Error("import_file_denied");
    const bytes = buffer.subarray(0, length);
    if (hash(bytes).toString("hex") !== expectedSha256) throw new Error("import_digest_mismatch");
    return recordsFromSeeds(strictJson(bytes));
  } finally { closeSync(file); }
}

function persist(root, catalog) {
  const bytes = Buffer.from(JSON.stringify({ schema: STORE_SCHEMA, catalog: validateCatalog(catalog) }), "utf8");
  if (bytes.length > MAX_STORE_BYTES) throw new Error("store_limit");
  const temporary = join(root, `.voice-reviews-${randomUUID()}.tmp`);
  const file = openSync(temporary, "wx", 0o600);
  try {
    try { writeFileSync(file, bytes); fsyncSync(file); }
    finally { closeSync(file); }
    renameSync(temporary, join(root, "voice-reviews.json"));
  } catch (error) { unlinkSync(temporary); throw error; }
}

function reply(response, status, body) {
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8", "cache-control": "no-store",
    "x-content-type-options": "nosniff", "content-security-policy": "default-src 'none'",
  });
  response.end(JSON.stringify(body));
}

function refuse(response, status, error) {
  reply(response, status, { ok: false, error, content: "omitted", promotion: false,
    current_truth_mutation: false, public_beta: "NO_GO_UNPUBLISHED" });
}

async function reviewBody(request) {
  if (!/^application\/json(?:\s*;\s*charset=utf-8)?$/i.test(request.headers["content-type"] ?? "")) return null;
  const declared = request.headers["content-length"];
  if (declared !== undefined && (!/^[0-9]+$/.test(declared) || Number(declared) > MAX_REVIEW_BYTES)) {
    request.resume();
    return null;
  }
  const chunks = [];
  let length = 0;
  for await (const chunk of request.iterator({ destroyOnReturn: false })) {
    length += chunk.length;
    if (length > MAX_REVIEW_BYTES) { request.resume(); return null; }
    chunks.push(chunk);
  }
  try { return validateReview(strictJson(Buffer.concat(chunks))); }
  catch { return null; }
}

/** Trusted backend only. Actor headers are accepted only after exact service authentication. */
export async function startReviewGateway({ stateRoot, clientId, clientSecret, seeds, importFile, expectedSha256, host = "127.0.0.1", port = 0 } = {}) {
  const importing = importFile !== undefined || expectedSha256 !== undefined;
  if (host !== "127.0.0.1" || !Number.isInteger(port) || port < 0 || port > 65535
    || typeof clientId !== "string" || !/^[\x21-\x7e]{1,4096}$/.test(clientId)
    || typeof clientSecret !== "string" || !/^[\x21-\x7e]{32,4096}$/.test(clientSecret)
    || (importing && (typeof importFile !== "string" || !importFile || typeof expectedSha256 !== "string"
      || !ACTOR_DIGEST.test(expectedSha256) || seeds !== undefined))) throw new Error("configuration_denied");
  const root = checkedRoot(stateRoot);
  const lock = join(root, ".voice-review-writer.lock");
  try { mkdirSync(lock, { mode: 0o700 }); }
  catch { throw new Error("store_locked"); }
  let catalog;
  try {
    try {
      catalog = readStore(join(root, "voice-reviews.json"));
      if (importing) throw new Error("import_existing_state_denied");
    }
    catch (error) {
      if (error.code !== "ENOENT") throw error;
      catalog = importing ? readImport(importFile, expectedSha256) : recordsFromSeeds(seeds);
      persist(root, catalog);
    }
    // Detach operator input; callers cannot mutate an admitted in-memory projection.
    catalog = structuredClone(catalog);
  } catch (error) { rmdirSync(lock); throw error; }

  const credentials = [hash(clientId), hash(clientSecret)];
  let closing = false;
  const server = createServer({ maxHeaderSize: 16_384, requestTimeout: 5_000, headersTimeout: 5_000 }, async (request, response) => {
    try {
      if (request.headers.host !== `127.0.0.1:${server.address().port}` || request.headers.origin) return refuse(response, 403, "origin_denied");
      const provided = [request.headers["cf-access-client-id"], request.headers["cf-access-client-secret"]];
      if (provided.some((value, i) => typeof value !== "string" || value.length > 4096
        || !timingSafeEqual(hash(value), credentials[i]))) return refuse(response, 401, "backend_auth_denied");
      let actor;
      try { actor = actorDigest({ subject: request.headers["x-kotodama-access-subject"] ?? null, email: request.headers["x-kotodama-access-email"] ?? null }); }
      catch { return refuse(response, 403, "actor_denied"); }
      const principalRef = catalog.principals.find((principal) => principal.actor_sha256 === actor)?.principal_ref;
      if (!request.url.startsWith("/") || request.url.length > 2048) return refuse(response, 400, "path_denied");
      const url = new URL(request.url, "http://127.0.0.1");
      if (request.method === "GET" && url.pathname === "/v1/voice/handoffs") {
        const query = url.searchParams.get("q");
        if ([...url.searchParams.keys()].some((key) => key !== "q") || url.searchParams.getAll("q").length > 1
          || (query !== null && Buffer.byteLength(query, "utf8") > 256)) return refuse(response, 400, "query_denied");
        const record = catalog.records.find((item) => canAccess(item.access_policy, principalRef, "read")
          && (query === null || query === item.projection.handoff_id));
        return record ? reply(response, 200, record.projection) : refuse(response, 404, "handoff_not_found");
      }
      const match = url.pathname.match(/^\/v1\/voice\/handoffs\/([a-z0-9][a-z0-9-]{0,127})\/review$/);
      if (request.method !== "POST" || !match || url.search) return refuse(response, 404, "path_denied");
      const body = await reviewBody(request);
      if (!body) return refuse(response, 400, "review_body_denied");
      // Re-evaluate after reading the asynchronous body: a concurrent local revocation wins.
      if (closing) return refuse(response, 503, "local_gateway_unavailable");
      const index = catalog.records.findIndex((item) => canAccess(item.access_policy, principalRef, "review")
        && item.projection.handoff_id === match[1]);
      if (index < 0) return refuse(response, 404, "handoff_not_found");
      const current = catalog.records[index].projection;
      if (body.expected_revision !== current.revision) return refuse(response, 409, "revision_conflict");
      const next = structuredClone(catalog);
      next.records[index].projection = { ...current, revision: current.revision + 1,
        overview: body.action === "edit" ? body.edited_overview : current.overview,
        human_review: { ...current.human_review, state: { accept: "accepted", edit: "edited", reject: "rejected" }[body.action] } };
      // No await between CAS, durable replacement and publication of the new state.
      persist(root, next);
      catalog = next;
      reply(response, 200, catalog.records[index].projection);
    } catch { refuse(response, 503, "local_gateway_unavailable"); }
  });
  server.maxConnections = 16;
  server.setTimeout(5_000, (socket) => socket.destroy());
  try {
    await new Promise((accept, reject) => { server.once("error", reject); server.listen(port, host, accept); });
  } catch (error) { rmdirSync(lock); throw error; }
  let closePromise;
  return {
    origin: `http://127.0.0.1:${server.address().port}`,
    // For a trusted in-process adapter that has authenticated a vendor principal.
    // The snapshot is atomic and detached; it is not a new public HTTP endpoint.
    inspectHandoff(principalRef, handoffId) {
      if (closing) throw new Error("gateway_closed");
      const principal = catalog.principals.find((item) => item.principal_ref === principalRef);
      const record = catalog.records.find((item) => item.projection.handoff_id === handoffId);
      if (!principal || !record || !canAccess(record.access_policy, principalRef, "read")) throw new Error("handoff_not_found");
      return structuredClone({ projection: record.projection, policy_revision: record.access_policy.revision, principal_kind: principal.kind });
    },
    // Trusted in-process operator surface only. Never forwarded as an HTTP/Worker action.
    updateAccessPolicy({ handoffId, expectedPolicyRevision, policy } = {}) {
      if (closing) throw new Error("gateway_closed");
      const index = catalog.records.findIndex((record) => record.projection.handoff_id === handoffId);
      if (index < 0) throw new Error("policy_target_denied");
      const current = catalog.records[index].access_policy;
      if (!Number.isSafeInteger(expectedPolicyRevision) || expectedPolicyRevision !== current.revision) throw new Error("policy_revision_conflict");
      validateAccessPolicy(policy, validatePrincipals(catalog.principals));
      if (policy.policy_id !== current.policy_id || policy.revision !== current.revision + 1) throw new Error("policy_revision_conflict");
      const next = structuredClone(catalog);
      next.records[index].policy_history.push(structuredClone(current));
      next.records[index].access_policy = structuredClone(policy);
      persist(root, next);
      catalog = next;
      return { handoff_id: handoffId, policy_revision: policy.revision, publication: false };
    },
    close() {
      closing = true;
      closePromise ??= new Promise((accept, reject) => server.close((error) => {
        try { rmdirSync(lock); } catch (cleanupError) { reject(cleanupError); return; }
        if (error) reject(error); else accept();
      }));
      return closePromise;
    },
  };
}

export function startReviewGatewayFromCli(args, env = process.env) {
  const values = new Map();
  for (let index = 0; index < args.length; index += 1) {
    const key = args[index];
    if (!["--state-root", "--seed-synthetic", "--import-file", "--expected-sha256"].includes(key)
      || values.has(key)) throw new Error("usage");
    const value = key === "--seed-synthetic" ? true : args[++index];
    if (value === undefined || value === "" || (typeof value === "string" && value.startsWith("--"))) throw new Error("usage");
    values.set(key, value);
  }
  if (!values.has("--state-root")) throw new Error("usage");
  return startReviewGateway({ stateRoot: values.get("--state-root"),
    clientId: env.CONTEXT_GATEWAY_CLIENT_ID, clientSecret: env.CONTEXT_GATEWAY_CLIENT_SECRET,
    port: Number(env.LOCAL_REVIEW_PORT ?? "8789"),
    seeds: values.has("--seed-synthetic") ? syntheticCatalog() : undefined,
    importFile: values.get("--import-file"), expectedSha256: values.get("--expected-sha256") });
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const args = process.argv.slice(2);
    if (args[0] === "--inspect-access") {
      if (args.length !== 3 || args[1] !== "--state-root" || !args[2]) throw new Error("usage");
      process.stdout.write(`${JSON.stringify(readAccessMetadata(args[2]), null, 2)}\n`);
    } else {
      const gateway = await startReviewGatewayFromCli(args);
      process.stdout.write(`Local candidate review Gateway listening on ${gateway.origin}\n`);
      for (const signal of ["SIGINT", "SIGTERM"]) process.once(signal, () => { gateway.close().catch(() => { process.exitCode = 1; }); });
    }
  } catch {
    process.stderr.write("Gateway start refused. Check the runbook, explicit auth, dedicated state directory and writer lock.\n");
    process.exitCode = 1;
  }
}
