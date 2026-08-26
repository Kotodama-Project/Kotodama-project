const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
  "content-security-policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
  "referrer-policy": "no-referrer",
  "x-content-type-options": "nosniff",
};
const ACCESS_HEADER = "cf-access-jwt-assertion";
const MAX_JWT_BYTES = 16_384;
const MAX_ACCESS_IDENTITY_BYTES = 1_024;
const MAX_QUERY_BYTES = 256;
const MAX_REVIEW_BODY_BYTES = 16_384;
const MAX_ACCESS_JWKS_BYTES = 262_144;
const MAX_GATEWAY_BODY_BYTES = 1_048_576;
const MAX_GATEWAY_JSON_DEPTH = 32;
const MAX_GATEWAY_JSON_NODES = 10_000;
const SAFE_DOCUMENT_ID = /^[a-z0-9][a-z0-9-]{0,127}$/;
const SAFE_SPEAKER_REF = /^speaker-[a-z0-9-]{1,32}$/;
const EVIDENCE_URN = /^urn:kotodama:evidence:sha256:[0-9a-f]{64}$/;
const REVIEW_ACTIONS = ["accept", "edit", "reject"];
const FORBIDDEN_GATEWAY_KEYS = new Set([
  "audio",
  "credential",
  "credentials",
  "private_corpus",
  "private_transcript",
  "raw_audio",
  "source_body",
  "transcript",
]);

let fetchImpl = (...args) => globalThis.fetch(...args);
let jwksCache = null;

function json(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

function deny(code, status) {
  return json({
    ok: false,
    error: code,
    content: "omitted",
    promotion: false,
    current_truth_mutation: false,
    public_beta: "NO_GO_UNPUBLISHED",
  }, status);
}

function utf8Bytes(value) {
  return new TextEncoder().encode(value).byteLength;
}

function normalizedHttpsOrigin(value) {
  if (typeof value !== "string" || value.length > 2048) return null;
  try {
    const url = new URL(value);
    if (
      url.protocol !== "https:"
      || url.username
      || url.password
      || url.search
      || url.hash
      || (url.pathname !== "/" && url.pathname !== "")
    ) return null;
    return url.origin;
  } catch {
    return null;
  }
}

function normalizedHostname(value) {
  if (typeof value !== "string" || value.length > 253) return null;
  const candidate = value.trim().toLowerCase();
  if (!candidate || candidate !== value || candidate.includes(":")) return null;
  try {
    const url = new URL(`https://${candidate}`);
    if (url.hostname !== candidate || url.port || url.pathname !== "/") return null;
    return candidate;
  } catch {
    return null;
  }
}

function runtimeConfig(env) {
  const issuer = normalizedHttpsOrigin(env?.ACCESS_ISSUER);
  const gateway = normalizedHttpsOrigin(env?.CONTEXT_GATEWAY_ORIGIN);
  const previewHost = normalizedHostname(env?.PREVIEW_HOST);
  const audience = typeof env?.ACCESS_AUD === "string" ? env.ACCESS_AUD.trim() : "";
  const clientId = typeof env?.CONTEXT_GATEWAY_CLIENT_ID === "string"
    ? env.CONTEXT_GATEWAY_CLIENT_ID.trim()
    : "";
  const clientSecret = typeof env?.CONTEXT_GATEWAY_CLIENT_SECRET === "string"
    ? env.CONTEXT_GATEWAY_CLIENT_SECRET.trim()
    : "";
  if (
    !issuer
    || !gateway
    || !previewHost
    || !audience
    || audience.length > 1024
    || !clientId
    || !clientSecret
    || clientId.length > 4096
    || clientSecret.length > 4096
  ) return null;
  return { issuer, gateway, previewHost, audience, clientId, clientSecret };
}

function decodeBase64url(value) {
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]+$/.test(value)) return null;
  try {
    const normalized = value.replaceAll("-", "+").replaceAll("_", "/")
      + "=".repeat((4 - (value.length % 4)) % 4);
    const binary = atob(normalized);
    return Uint8Array.from(binary, (character) => character.charCodeAt(0));
  } catch {
    return null;
  }
}

function parseJwt(token) {
  if (typeof token !== "string" || utf8Bytes(token) > MAX_JWT_BYTES) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  const headerBytes = decodeBase64url(parts[0]);
  const payloadBytes = decodeBase64url(parts[1]);
  const signature = decodeBase64url(parts[2]);
  if (!headerBytes || !payloadBytes || !signature) return null;
  try {
    const header = JSON.parse(new TextDecoder().decode(headerBytes));
    const payload = JSON.parse(new TextDecoder().decode(payloadBytes));
    if (!header || typeof header !== "object" || !payload || typeof payload !== "object") {
      return null;
    }
    return { header, payload, signature, signed: `${parts[0]}.${parts[1]}` };
  } catch {
    return null;
  }
}

function audienceMatches(value, expected) {
  return value === expected || (Array.isArray(value) && value.includes(expected));
}

function normalizedIdentityClaim(value) {
  if (value === undefined) return null;
  if (
    typeof value !== "string"
    || !value
    || value !== value.trim()
    || utf8Bytes(value) > MAX_ACCESS_IDENTITY_BYTES
    || !/^[\x21-\x7e]+$/.test(value)
  ) return null;
  return value;
}

async function refreshAccessJwks(config) {
  let response;
  try {
    response = await fetchImpl(new Request(`${config.issuer}/cdn-cgi/access/certs`, {
      method: "GET",
      redirect: "error",
      headers: { accept: "application/json" },
    }));
  } catch {
    return null;
  }
  if (!response.ok) return null;
  const bytes = await boundedBodyBytes(response, MAX_ACCESS_JWKS_BYTES);
  if (!bytes) return null;
  let value;
  try {
    value = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return null;
  }
  if (!Array.isArray(value?.keys) || value.keys.length > 32) return null;
  jwksCache = { issuer: config.issuer, keys: value.keys, expiresAt: Date.now() + 300_000 };
  return jwksCache.keys;
}

async function accessIdentity(request, config) {
  const parsed = parseJwt(request.headers.get(ACCESS_HEADER));
  if (!parsed || parsed.header.alg !== "RS256" || typeof parsed.header.kid !== "string") {
    return null;
  }
  const now = Math.floor(Date.now() / 1000);
  const subject = normalizedIdentityClaim(parsed.payload.sub);
  const email = normalizedIdentityClaim(parsed.payload.email);
  if (
    parsed.payload.iss !== config.issuer
    || !audienceMatches(parsed.payload.aud, config.audience)
    || !Number.isSafeInteger(parsed.payload.exp)
    || parsed.payload.exp <= now
    || (parsed.payload.nbf !== undefined
      && (!Number.isSafeInteger(parsed.payload.nbf) || parsed.payload.nbf > now))
    || (parsed.payload.sub !== undefined && !subject)
    || (parsed.payload.email !== undefined && !email)
    || (!subject && !email)
  ) return null;

  let keys = jwksCache
    && jwksCache.issuer === config.issuer
    && jwksCache.expiresAt > Date.now()
    ? jwksCache.keys
    : await refreshAccessJwks(config);
  if (!keys) return null;
  let jwk = keys.find((key) => key?.kid === parsed.header.kid && key?.kty === "RSA");
  if (!jwk) {
    keys = await refreshAccessJwks(config);
    if (!keys) return null;
    jwk = keys.find((key) => key?.kid === parsed.header.kid && key?.kty === "RSA");
  }
  if (!jwk) return null;
  try {
    const key = await crypto.subtle.importKey(
      "jwk",
      jwk,
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
      false,
      ["verify"],
    );
    const valid = await crypto.subtle.verify(
      "RSASSA-PKCS1-v1_5",
      key,
      parsed.signature,
      new TextEncoder().encode(parsed.signed),
    );
    if (!valid) return null;
  } catch {
    return null;
  }
  return {
    subject,
    email,
  };
}

function hasForbiddenGatewayKey(value) {
  const pending = [{ value, depth: 0 }];
  let visited = 0;
  while (pending.length) {
    const current = pending.pop();
    visited += 1;
    if (visited > MAX_GATEWAY_JSON_NODES || current.depth > MAX_GATEWAY_JSON_DEPTH) {
      return true;
    }
    if (!current.value || typeof current.value !== "object") continue;
    if (Array.isArray(current.value)) {
      for (const nested of current.value) {
        pending.push({ value: nested, depth: current.depth + 1 });
      }
      continue;
    }
    for (const [key, nested] of Object.entries(current.value)) {
      if (FORBIDDEN_GATEWAY_KEYS.has(key.toLowerCase())) return true;
      pending.push({ value: nested, depth: current.depth + 1 });
    }
  }
  return false;
}

function projectItems(value) {
  if (!Array.isArray(value) || !value.length || value.length > 100) return null;
  const result = [];
  for (const item of value) {
    if (!item || typeof item !== "object" || typeof item.summary !== "string") return null;
    if (!item.summary.trim() || utf8Bytes(item.summary) > 8_000) return null;
    const projected = { summary: item.summary };
    for (const key of ["speaker_ref", "owner", "due"]) {
      if (item[key] !== undefined) {
        if (typeof item[key] !== "string" || utf8Bytes(item[key]) > 256) return null;
        projected[key] = item[key];
      }
    }
    if (
      (projected.speaker_ref !== undefined && !SAFE_SPEAKER_REF.test(projected.speaker_ref))
      || (projected.owner !== undefined && !SAFE_SPEAKER_REF.test(projected.owner))
    ) return null;
    result.push(projected);
  }
  return result;
}

function sanitizeProjection(value) {
  if (!value || typeof value !== "object" || hasForbiddenGatewayKey(value)) return null;
  if (
    value.schema !== "kotodama.cloudflare_os.authorized_voice_projection"
    || value.schema_version !== "1.0.0"
    || value.route !== "cloudflare_os->context_gateway"
    || value.authority !== "candidate_only"
    || value.data_class !== "authorized_voice_handoff_projection"
    || value.raw_audio_transferred !== false
    || value.private_transcript_transferred !== false
    || value.context_gateway_bypass !== false
    || value.promotion !== false
    || value.current_truth_mutation !== false
    || value.public_beta !== "NO_GO_UNPUBLISHED"
    || typeof value.overview !== "string"
    || !value.overview.trim()
    || utf8Bytes(value.overview) > 16_000
  ) return null;
  const speakerHighlights = projectItems(value.speaker_highlights);
  const decisions = projectItems(value.decisions);
  const todos = projectItems(value.todos);
  const openQuestions = projectItems(value.open_questions);
  if (!speakerHighlights || !decisions || !todos || !openQuestions) return null;
  if (
    !Array.isArray(value.evidence_pointers)
    || !value.evidence_pointers.length
    || value.evidence_pointers.length > 512
    || value.evidence_pointers.some((item) => typeof item !== "string" || !EVIDENCE_URN.test(item))
  ) return null;
  const review = value.human_review;
  if (
    !review
    || typeof review !== "object"
    || review.required !== true
    || !["pending", "accepted", "edited", "rejected"].includes(review.state)
    || JSON.stringify(review.actions) !== JSON.stringify(REVIEW_ACTIONS)
  ) return null;
  return {
    schema: "kotodama.cloudflare_os.authorized_voice_projection",
    schema_version: "1.0.0",
    route: "cloudflare_os->context_gateway",
    data_class: "authorized_voice_handoff_projection",
    authority: "candidate_only",
    overview: value.overview,
    speaker_highlights: speakerHighlights,
    decisions,
    todos,
    open_questions: openQuestions,
    evidence_pointers: [...value.evidence_pointers],
    human_review: { required: true, state: review.state, actions: [...REVIEW_ACTIONS] },
    raw_audio_transferred: false,
    private_transcript_transferred: false,
    context_gateway_bypass: false,
    promotion: false,
    current_truth_mutation: false,
    public_beta: "NO_GO_UNPUBLISHED",
  };
}

async function boundedBodyBytes(request, limit) {
  if (!request.body) return new Uint8Array();
  let reader;
  try {
    reader = request.body.getReader();
  } catch {
    return null;
  }
  const chunks = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = value instanceof Uint8Array
        ? value
        : value instanceof ArrayBuffer
          ? new Uint8Array(value)
          : null;
      if (!chunk || total + chunk.byteLength > limit) {
        try {
          await reader.cancel("body_limit_exceeded");
        } catch {
          // The request is already denied; cancellation is best effort.
        }
        return null;
      }
      total += chunk.byteLength;
      chunks.push(chunk);
    }
  } catch {
    try {
      await reader.cancel("body_read_failed");
    } catch {
      // The request is already denied; cancellation is best effort.
    }
    return null;
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
}

async function cancelReadableBody(body, reason) {
  if (!body) return;
  let reader;
  try {
    reader = body.getReader();
    await reader.cancel(reason);
  } catch {
    // The response is already denied; cancellation is best effort.
  } finally {
    try {
      reader?.releaseLock();
    } catch {
      // The response is already denied; releasing is best effort.
    }
  }
}

async function boundedGatewayBody(response, limit) {
  const declared = response.headers.get("content-length");
  if (declared !== null) {
    const declaredBytes = Number(declared);
    if (
      !/^[0-9]+$/.test(declared)
      || !Number.isSafeInteger(declaredBytes)
      || declaredBytes > limit
    ) {
      await cancelReadableBody(response.body, "gateway_body_length_denied");
      return null;
    }
  }
  return boundedBodyBytes(response, limit);
}

async function boundedReviewBody(request) {
  const contentType = request.headers.get("content-type") ?? "";
  if (!/^application\/json(?:\s*;\s*charset=utf-8)?$/i.test(contentType.trim())) return null;
  const declared = request.headers.get("content-length");
  if (declared && (!/^[0-9]+$/.test(declared) || Number(declared) > MAX_REVIEW_BODY_BYTES)) {
    return null;
  }
  const bytes = await boundedBodyBytes(request, MAX_REVIEW_BODY_BYTES);
  if (!bytes) return null;
  let value;
  try {
    value = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return null;
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const keys = Object.keys(value);
  if (!REVIEW_ACTIONS.includes(value.action) || keys.some((key) => !["action", "edited_overview"].includes(key))) {
    return null;
  }
  if (value.action === "edit") {
    if (
      typeof value.edited_overview !== "string"
      || !value.edited_overview.trim()
      || utf8Bytes(value.edited_overview) > 8_000
    ) return null;
  } else if (value.edited_overview !== undefined) {
    return null;
  }
  return value;
}

async function gatewayReadback(request, config, pathname, identity) {
  let target;
  let init;
  if (request.method === "GET" && pathname === "/voice/review") {
    const query = new URL(request.url).searchParams.get("q");
    if (query !== null && utf8Bytes(query) > MAX_QUERY_BYTES) return deny("query_denied", 400);
    target = `${config.gateway}/v1/voice/handoffs${query === null ? "" : `?q=${encodeURIComponent(query)}`}`;
    init = { method: "GET" };
  } else if (request.method === "POST") {
    const match = pathname.match(/^\/voice\/review\/([a-z0-9][a-z0-9-]{0,127})$/);
    if (!match || !SAFE_DOCUMENT_ID.test(match[1])) return deny("path_denied", 404);
    const body = await boundedReviewBody(request);
    if (!body) return deny("review_body_denied", 400);
    target = `${config.gateway}/v1/voice/handoffs/${match[1]}/review`;
    init = {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "content-type": "application/json; charset=utf-8" },
    };
  } else {
    return deny("method_not_allowed", 405);
  }
  const headers = new Headers(init.headers ?? {});
  headers.set("accept", "application/json");
  headers.set("cf-access-client-id", config.clientId);
  headers.set("cf-access-client-secret", config.clientSecret);
  if (identity.subject) headers.set("x-kotodama-access-subject", identity.subject);
  if (identity.email) headers.set("x-kotodama-access-email", identity.email);
  let response;
  try {
    response = await fetchImpl(new Request(target, { ...init, headers, redirect: "error" }));
  } catch {
    return deny("context_gateway_unavailable", 502);
  }
  if (!response.ok) return deny("context_gateway_refused", 502);
  const bytes = await boundedGatewayBody(response, MAX_GATEWAY_BODY_BYTES);
  if (!bytes) return deny("context_gateway_body_denied", 502);
  let value;
  try {
    value = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return deny("context_gateway_body_denied", 502);
  }
  const projected = sanitizeProjection(value);
  return projected ? json(projected, 200) : deny("context_gateway_projection_denied", 502);
}

async function evaluate(request, env) {
  const url = new URL(request.url);
  const { pathname } = url;
  const config = runtimeConfig(env);
  if (!config) return deny("runtime_configuration_denied", 503);
  if (url.hostname.toLowerCase() !== config.previewHost) {
    return deny("direct_origin_denied", 403);
  }
  const identity = await accessIdentity(request, config);
  if (!identity) return deny("access_denied", 401);
  if (pathname === "/healthz" || pathname === "/version") {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return deny("method_not_allowed", 405);
    }
    const body = pathname === "/healthz"
      ? { ok: true, surface: "cloudflare-edge-candidate" }
      : { ok: true, stage: env.DEPLOYMENT_STAGE, public_beta: env.PUBLIC_BETA_STATUS };
    return request.method === "HEAD" ? new Response(null, { status: 200, headers: JSON_HEADERS }) : json(body);
  }
  if (!pathname.startsWith("/voice/review")) return deny("not_found", 404);
  return gatewayReadback(request, config, pathname, identity);
}

export default { fetch: (request, env) => evaluate(request, env) };

export const __testing = {
  reset() {
    jwksCache = null;
    fetchImpl = (...args) => globalThis.fetch(...args);
  },
  setFetch(value) {
    fetchImpl = value;
  },
};
