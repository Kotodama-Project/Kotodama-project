import assert from "node:assert/strict";
import { test } from "node:test";

import worker, { __testing } from "../../runtime/cloudflare-edge/src/index.js";


const ISSUER = "https://team.cloudflareaccess.com";
const AUDIENCE = "audience-test";
const GATEWAY = "https://gateway.example.test";

async function signingFixture() {
  const keyPair = await crypto.subtle.generateKey(
    {
      name: "RSASSA-PKCS1-v1_5",
      modulusLength: 2048,
      publicExponent: new Uint8Array([1, 0, 1]),
      hash: "SHA-256",
    },
    true,
    ["sign", "verify"],
  );
  const jwk = await crypto.subtle.exportKey("jwk", keyPair.publicKey);
  jwk.kid = "kid-test";
  jwk.alg = "RS256";
  jwk.use = "sig";

  async function token(overrides = {}) {
    const now = Math.floor(Date.now() / 1000);
    const header = { alg: "RS256", kid: "kid-test", typ: "JWT" };
    const payload = {
      iss: ISSUER,
      aud: AUDIENCE,
      sub: "reviewer-synthetic",
      email: "reviewer@example.test",
      iat: now - 1,
      nbf: now - 1,
      exp: now + 300,
      ...overrides,
    };
    const encoded = `${base64url(JSON.stringify(header))}.${base64url(JSON.stringify(payload))}`;
    const signature = await crypto.subtle.sign(
      "RSASSA-PKCS1-v1_5",
      keyPair.privateKey,
      new TextEncoder().encode(encoded),
    );
    return `${encoded}.${base64url(new Uint8Array(signature))}`;
  }
  return { jwk, token };
}

function base64url(value) {
  const bytes = typeof value === "string" ? new TextEncoder().encode(value) : value;
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

function projection(extra = {}) {
  return {
    schema: "kotodama.cloudflare_os.authorized_voice_projection",
    schema_version: "1.0.0",
    route: "cloudflare_os->context_gateway",
    data_class: "authorized_voice_handoff_projection",
    authority: "candidate_only",
    overview: "Synthetic overview.",
    speaker_highlights: [{ summary: "A highlight.", speaker_ref: "speaker-a" }],
    decisions: [{ summary: "Keep preview private." }],
    todos: [{ summary: "Run checks.", owner: "speaker-a", due: "2026-08-10" }],
    open_questions: [{ summary: "Who gives Final GO?" }],
    evidence_pointers: [`urn:kotodama:evidence:sha256:${"a".repeat(64)}`],
    human_review: {
      required: true,
      state: "pending",
      actions: ["accept", "edit", "reject"],
    },
    raw_audio_transferred: false,
    private_transcript_transferred: false,
    context_gateway_bypass: false,
    promotion: false,
    current_truth_mutation: false,
    public_beta: "NO_GO_UNPUBLISHED",
    ...extra,
  };
}

function env() {
  return {
    DEPLOYMENT_STAGE: "preview-candidate",
    PUBLIC_BETA_STATUS: "NO_GO_UNPUBLISHED",
    ACCESS_ISSUER: ISSUER,
    ACCESS_AUD: AUDIENCE,
    PREVIEW_HOST: "preview.example.test",
    CONTEXT_GATEWAY_ORIGIN: GATEWAY,
    CONTEXT_GATEWAY_CLIENT_ID: "synthetic-client-id",
    CONTEXT_GATEWAY_CLIENT_SECRET: "synthetic-client-secret",
  };
}

function withJwt(url, jwt, init = {}) {
  return new Request(url, {
    ...init,
    headers: {
      ...(init.headers ?? {}),
      "cf-access-jwt-assertion": jwt,
    },
  });
}

test("Access-verified review readback can only come through Context Gateway", async () => {
  __testing.reset();
  const { jwk, token } = await signingFixture();
  const jwt = await token();
  const calls = [];
  __testing.setFetch(async (request) => {
    const value = request instanceof Request ? request : new Request(request);
    calls.push(value);
    if (value.url === `${ISSUER}/cdn-cgi/access/certs`) {
      return Response.json({ keys: [jwk] });
    }
    assert.equal(value.url, `${GATEWAY}/v1/voice/handoffs?q=synthetic`);
    assert.equal(value.headers.get("cf-access-client-id"), "synthetic-client-id");
    assert.equal(value.headers.get("cf-access-client-secret"), "synthetic-client-secret");
    return Response.json(projection());
  });

  const response = await worker.fetch(
    withJwt("https://preview.example.test/voice/review?q=synthetic", jwt),
    env(),
  );
  const body = await response.json();
  assert.equal(response.status, 200);
  assert.equal(calls.length, 2);
  assert.equal(body.authority, "candidate_only");
  assert.equal(body.context_gateway_bypass, false);
  assert.equal(body.raw_audio_transferred, false);
  assert.equal(body.private_transcript_transferred, false);
  assert.equal(JSON.stringify(body).includes("synthetic-client-secret"), false);
});

test("missing, forged, and expired Access JWTs deny direct origin access", async () => {
  __testing.reset();
  const { jwk, token } = await signingFixture();
  let gatewayCalls = 0;
  __testing.setFetch(async (request) => {
    const value = request instanceof Request ? request : new Request(request);
    if (value.url === `${ISSUER}/cdn-cgi/access/certs`) return Response.json({ keys: [jwk] });
    gatewayCalls += 1;
    return Response.json(projection());
  });

  const missing = await worker.fetch(new Request("https://preview.example.test/voice/review"), env());
  assert.equal(missing.status, 401);
  const forged = await worker.fetch(
    withJwt("https://preview.example.test/voice/review", "a.b.c"),
    env(),
  );
  assert.equal(forged.status, 401);
  const expired = await worker.fetch(
    withJwt("https://preview.example.test/voice/review", await token({ exp: 1 })),
    env(),
  );
  assert.equal(expired.status, 401);
  const direct = await worker.fetch(
    withJwt("https://worker-version.workers.dev/voice/review", await token()),
    env(),
  );
  assert.equal(direct.status, 403);
  assert.equal(gatewayCalls, 0);
});

test("health and version surfaces require Access and exact preview host", async () => {
  __testing.reset();
  const { jwk, token } = await signingFixture();
  __testing.setFetch(async (request) => {
    const value = request instanceof Request ? request : new Request(request);
    assert.equal(value.url, `${ISSUER}/cdn-cgi/access/certs`);
    return Response.json({ keys: [jwk] });
  });

  const unauthenticated = await worker.fetch(
    new Request("https://preview.example.test/healthz"),
    env(),
  );
  assert.equal(unauthenticated.status, 401);
  const direct = await worker.fetch(
    withJwt("https://worker-version.workers.dev/version", await token()),
    env(),
  );
  assert.equal(direct.status, 403);
  const authorized = await worker.fetch(
    withJwt("https://preview.example.test/healthz", await token()),
    env(),
  );
  assert.equal(authorized.status, 200);
});

test("review actions are bounded and forwarded only to the Context Gateway", async () => {
  __testing.reset();
  const { jwk, token } = await signingFixture();
  const jwt = await token();
  let observed;
  __testing.setFetch(async (request) => {
    const value = request instanceof Request ? request : new Request(request);
    if (value.url === `${ISSUER}/cdn-cgi/access/certs`) return Response.json({ keys: [jwk] });
    observed = value;
    return Response.json(projection({ human_review: {
      required: true,
      state: "accepted",
      actions: ["accept", "edit", "reject"],
    } }));
  });

  const response = await worker.fetch(
    withJwt("https://preview.example.test/voice/review/doc-safe-1", jwt, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ action: "accept" }),
    }),
    env(),
  );
  assert.equal(response.status, 200);
  assert.equal(observed.url, `${GATEWAY}/v1/voice/handoffs/doc-safe-1/review`);
  assert.equal(observed.method, "POST");
  assert.deepEqual(await observed.clone().json(), { action: "accept" });
});

test("raw Voice, transcript, credential, and corpus fields fail closed", async () => {
  for (const forbidden of ["raw_audio", "private_transcript", "credential", "private_corpus"]) {
    __testing.reset();
    const { jwk, token } = await signingFixture();
    __testing.setFetch(async (request) => {
      const value = request instanceof Request ? request : new Request(request);
      if (value.url === `${ISSUER}/cdn-cgi/access/certs`) return Response.json({ keys: [jwk] });
      return Response.json(projection({ [forbidden]: "must-not-cross" }));
    });
    const response = await worker.fetch(
      withJwt("https://preview.example.test/voice/review", await token()),
      env(),
    );
    assert.equal(response.status, 502, forbidden);
    assert.equal(JSON.stringify(await response.json()).includes("must-not-cross"), false);
  }
});

test("excessively deep or wide gateway JSON fails closed without recursion", async () => {
  const deeplyNested = {};
  let cursor = deeplyNested;
  for (let depth = 0; depth < 64; depth += 1) {
    cursor.next = {};
    cursor = cursor.next;
  }

  for (const invalid of [
    { nested: deeplyNested },
    { nested: Array.from({ length: 10_001 }, () => null) },
  ]) {
    __testing.reset();
    const { jwk, token } = await signingFixture();
    __testing.setFetch(async (request) => {
      const value = request instanceof Request ? request : new Request(request);
      if (value.url === `${ISSUER}/cdn-cgi/access/certs`) return Response.json({ keys: [jwk] });
      return Response.json(projection(invalid));
    });

    const response = await worker.fetch(
      withJwt("https://preview.example.test/voice/review", await token()),
      env(),
    );
    assert.equal(response.status, 502);
    assert.equal((await response.json()).error, "context_gateway_projection_denied");
  }
});

test("schema drift and empty required sections fail closed", async () => {
  for (const invalid of [
    { schema_version: "2.0.0" },
    { route: "cloudflare_os->search" },
    { decisions: [] },
    { todos: [] },
    { open_questions: [] },
    { speaker_highlights: [] },
  ]) {
    __testing.reset();
    const { jwk, token } = await signingFixture();
    __testing.setFetch(async (request) => {
      const value = request instanceof Request ? request : new Request(request);
      if (value.url === `${ISSUER}/cdn-cgi/access/certs`) return Response.json({ keys: [jwk] });
      return Response.json(projection(invalid));
    });
    const response = await worker.fetch(
      withJwt("https://preview.example.test/voice/review", await token()),
      env(),
    );
    assert.equal(response.status, 502, JSON.stringify(invalid));
  }
});

test("unsafe gateway origin and invalid review input are denied before fetch", async () => {
  __testing.reset();
  const { token } = await signingFixture();
  let calls = 0;
  __testing.setFetch(async () => {
    calls += 1;
    throw new Error("must not fetch");
  });
  const unsafe = env();
  unsafe.CONTEXT_GATEWAY_ORIGIN = "http://search.example.test";
  const response = await worker.fetch(
    withJwt("https://preview.example.test/voice/review", await token()),
    unsafe,
  );
  assert.equal(response.status, 503);
  assert.equal(calls, 0);
});
