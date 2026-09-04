import { createServer } from "node:http";
import { createHash, randomUUID, timingSafeEqual } from "node:crypto";
import {
  closeSync, fsyncSync, lstatSync, mkdirSync, openSync, readFileSync, renameSync,
  rmdirSync, unlinkSync, writeFileSync,
} from "node:fs";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { isDeepStrictEqual } from "node:util";
import { sanitizeProjection, validateReview } from "../cloudflare-edge/src/index.js";
import { syntheticSeed } from "./synthetic-fixture.mjs";

const MAX_STORE_BYTES = 4_194_304;
const MAX_RECORDS = 64;
const MAX_REVIEW_BYTES = 16_384;
const STORE_SCHEMA = "kotodama/local-voice-review-candidates/v1";
const ACTOR_DIGEST = /^[0-9a-f]{64}$/;
const decoder = new TextDecoder("utf-8", { fatal: true });
const hash = (value) => createHash("sha256").update(value).digest();
const closed = (value, keys) => value && typeof value === "object" && !Array.isArray(value)
  && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));

// JSON.parse validates grammar; this bounded lexical pass also rejects duplicate keys.
function strictJson(bytes) {
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

function validateRecords(records) {
  if (!Array.isArray(records) || !records.length || records.length > MAX_RECORDS) throw new Error("store_denied");
  const identities = new Set();
  for (const record of records) {
    if (!closed(record, ["actor_sha256", "projection"]) || !ACTOR_DIGEST.test(record.actor_sha256)
      || !isDeepStrictEqual(sanitizeProjection(record.projection), record.projection)) throw new Error("store_denied");
    const key = `${record.actor_sha256}/${record.projection.handoff_id}`;
    if (identities.has(key)) throw new Error("store_denied");
    identities.add(key);
  }
  return records;
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
  if (!closed(value, ["schema", "records"]) || value.schema !== STORE_SCHEMA) throw new Error("store_denied");
  return validateRecords(value.records);
}

function persist(root, records) {
  const bytes = Buffer.from(JSON.stringify({ schema: STORE_SCHEMA, records: validateRecords(records) }), "utf8");
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
export async function startReviewGateway({ stateRoot, clientId, clientSecret, seeds, host = "127.0.0.1", port = 0 } = {}) {
  if (host !== "127.0.0.1" || !Number.isInteger(port) || port < 0 || port > 65535
    || typeof clientId !== "string" || !/^[\x21-\x7e]{1,4096}$/.test(clientId)
    || typeof clientSecret !== "string" || !/^[\x21-\x7e]{32,4096}$/.test(clientSecret)) throw new Error("configuration_denied");
  const root = checkedRoot(stateRoot);
  const lock = join(root, ".voice-review-writer.lock");
  try { mkdirSync(lock, { mode: 0o700 }); }
  catch { throw new Error("store_locked"); }
  let records;
  try {
    try { records = readStore(join(root, "voice-reviews.json")); }
    catch (error) {
      if (error.code !== "ENOENT") throw error;
      if (!Array.isArray(seeds)) throw new Error("seed_required");
      if (!seeds.length || seeds.length > MAX_RECORDS) throw new Error("seed_denied");
      try {
        records = seeds.map((seed) => {
          if (!closed(seed, ["actor", "projection"]) || seed.projection?.revision !== 1
            || seed.projection?.human_review?.state !== "pending") throw new Error("seed_denied");
          return { actor_sha256: actorDigest(seed.actor), projection: seed.projection };
        });
        validateRecords(records);
      } catch { throw new Error("seed_denied"); }
      persist(root, records);
    }
    // Detach operator input; callers cannot mutate an admitted in-memory projection.
    records = structuredClone(records);
  } catch (error) { rmdirSync(lock); throw error; }

  const credentials = [hash(clientId), hash(clientSecret)];
  const server = createServer({ maxHeaderSize: 16_384, requestTimeout: 5_000, headersTimeout: 5_000 }, async (request, response) => {
    try {
      if (request.headers.host !== `127.0.0.1:${server.address().port}` || request.headers.origin) return refuse(response, 403, "origin_denied");
      const provided = [request.headers["cf-access-client-id"], request.headers["cf-access-client-secret"]];
      if (provided.some((value, i) => typeof value !== "string" || value.length > 4096
        || !timingSafeEqual(hash(value), credentials[i]))) return refuse(response, 401, "backend_auth_denied");
      let actor;
      try { actor = actorDigest({ subject: request.headers["x-kotodama-access-subject"] ?? null, email: request.headers["x-kotodama-access-email"] ?? null }); }
      catch { return refuse(response, 403, "actor_denied"); }
      if (!request.url.startsWith("/") || request.url.length > 2048) return refuse(response, 400, "path_denied");
      const url = new URL(request.url, "http://127.0.0.1");
      if (request.method === "GET" && url.pathname === "/v1/voice/handoffs") {
        const query = url.searchParams.get("q");
        if ([...url.searchParams.keys()].some((key) => key !== "q") || url.searchParams.getAll("q").length > 1
          || (query !== null && Buffer.byteLength(query, "utf8") > 256)) return refuse(response, 400, "query_denied");
        const record = records.find((item) => item.actor_sha256 === actor && (query === null || query === item.projection.handoff_id));
        return record ? reply(response, 200, record.projection) : refuse(response, 404, "handoff_not_found");
      }
      const match = url.pathname.match(/^\/v1\/voice\/handoffs\/([a-z0-9][a-z0-9-]{0,127})\/review$/);
      if (request.method !== "POST" || !match || url.search) return refuse(response, 404, "path_denied");
      const body = await reviewBody(request);
      if (!body) return refuse(response, 400, "review_body_denied");
      const index = records.findIndex((item) => item.actor_sha256 === actor && item.projection.handoff_id === match[1]);
      if (index < 0) return refuse(response, 404, "handoff_not_found");
      const current = records[index].projection;
      if (body.expected_revision !== current.revision) return refuse(response, 409, "revision_conflict");
      const next = structuredClone(records);
      next[index].projection = { ...current, revision: current.revision + 1,
        overview: body.action === "edit" ? body.edited_overview : current.overview,
        human_review: { ...current.human_review, state: { accept: "accepted", edit: "edited", reject: "rejected" }[body.action] } };
      // No await between CAS, durable replacement and publication of the new state.
      persist(root, next);
      records = next;
      reply(response, 200, records[index].projection);
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
    close() {
      closePromise ??= new Promise((accept, reject) => server.close((error) => {
        try { rmdirSync(lock); } catch (cleanupError) { reject(cleanupError); return; }
        if (error) reject(error); else accept();
      }));
      return closePromise;
    },
  };
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const args = process.argv.slice(2);
    if (args.length < 2 || args[0] !== "--state-root" || args.length > 3
      || (args.length === 3 && args[2] !== "--seed-synthetic")) throw new Error("usage");
    const gateway = await startReviewGateway({ stateRoot: args[1],
      clientId: process.env.CONTEXT_GATEWAY_CLIENT_ID,
      clientSecret: process.env.CONTEXT_GATEWAY_CLIENT_SECRET,
      port: Number(process.env.LOCAL_REVIEW_PORT ?? "8789"),
      seeds: args[2] === "--seed-synthetic" ? [syntheticSeed()] : undefined });
    process.stdout.write(`Local candidate review Gateway listening on ${gateway.origin}\n`);
    for (const signal of ["SIGINT", "SIGTERM"]) process.once(signal, () => { gateway.close().catch(() => { process.exitCode = 1; }); });
  } catch {
    process.stderr.write("Gateway start refused. Check the runbook, explicit auth, dedicated state directory and writer lock.\n");
    process.exitCode = 1;
  }
}
