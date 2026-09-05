import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomBytes } from "node:crypto";

import worker, { __testing } from "../../runtime/cloudflare-edge/src/index.js";
import { startReviewGateway } from "../../runtime/local-review-gateway/server.mjs";
import { syntheticSeed, syntheticCatalog } from "../../runtime/local-review-gateway/synthetic-fixture.mjs";


const ISSUER = "https://team.cloudflareaccess.com";
const AUDIENCE = "audience-test";
const GATEWAY = "https://gateway.example.test";

async function signingFixture(kid = "kid-test") {
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
  jwk.kid = kid;
  jwk.alg = "RS256";
  jwk.use = "sig";

  async function token(overrides = {}) {
    const now = Math.floor(Date.now() / 1000);
    const header = { alg: "RS256", kid, typ: "JWT" };
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

  async function signedTokenFromBytes(headerBytes, payloadBytes) {
    const encoded = `${base64url(headerBytes)}.${base64url(payloadBytes)}`;
    const signature = await crypto.subtle.sign(
      "RSASSA-PKCS1-v1_5",
      keyPair.privateKey,
      new TextEncoder().encode(encoded),
    );
    return `${encoded}.${base64url(new Uint8Array(signature))}`;
  }

  return { jwk, token, signedTokenFromBytes };
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
    handoff_id: "doc-safe-1",
    revision: 1,
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

function streamingResponse(chunks, { contentLength, trapArrayBuffer = false } = {}) {
  let index = 0;
  let pulls = 0;
  let cancelled = false;
  const body = new ReadableStream(
    {
      pull(controller) {
        pulls += 1;
        if (index === chunks.length) {
          controller.close();
          return;
        }
        controller.enqueue(chunks[index]);
        index += 1;
      },
      cancel() {
        cancelled = true;
      },
    },
    { highWaterMark: 0 },
  );
  const headers = new Headers({ "content-type": "application/json" });
  if (contentLength !== undefined) headers.set("content-length", contentLength);
  return {
    response: {
      ok: true,
      headers,
      body,
      arrayBuffer() {
        if (trapArrayBuffer) throw new Error("arrayBuffer must not be called");
        return new ArrayBuffer(0);
      },
    },
    get pulls() {
      return pulls;
    },
    get cancelled() {
      return cancelled;
    },
  };
}

const MALFORMED_UTF8_CASES = [
  { name: "bad continuation", bytes: Uint8Array.from([0xc3, 0x28]) },
  { name: "truncated sequence", bytes: Uint8Array.from([0xe2, 0x82]) },
];

function malformedJsonBytes(value, key, replacement) {
  const json = JSON.stringify(value);
  const marker = `"${key}":"`;
  const markerStart = json.indexOf(marker);
  assert.notEqual(markerStart, -1, `missing JSON marker for ${key}`);
  const valueStart = markerStart + marker.length;
  const prefix = new TextEncoder().encode(json.slice(0, valueStart));
  const suffix = new TextEncoder().encode(json.slice(valueStart + 1));
  return Uint8Array.from([...prefix, ...replacement, ...suffix]);
}

function installFetch(fixture, { onJwks, onGateway } = {}) {
  const calls = { jwks: 0, gateway: 0 };
  __testing.setFetch(async (request) => {
    const value = request instanceof Request ? request : new Request(request);
    if (value.url === `${ISSUER}/cdn-cgi/access/certs`) {
      calls.jwks += 1;
      return onJwks ? onJwks(value) : Response.json({ keys: [fixture.jwk] });
    }
    calls.gateway += 1;
    return onGateway ? onGateway(value) : Response.json(projection());
  });
  return calls;
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
    assert.equal(value.headers.get("x-kotodama-access-subject"), "reviewer-synthetic");
    assert.equal(value.headers.get("x-kotodama-access-email"), "reviewer@example.test");
    return Response.json(projection());
  });

  const response = await worker.fetch(
    withJwt("https://preview.example.test/voice/review?q=synthetic", jwt, {
      headers: {
        "x-kotodama-access-subject": "spoofed-subject",
        "x-kotodama-access-email": "spoofed@example.test",
      },
    }),
    env(),
  );
  const body = await response.json();
  assert.equal(response.status, 200);
  assert.equal(calls.length, 2);
  assert.equal(body.authority, "candidate_only");
  assert.equal(body.handoff_id, "doc-safe-1");
  assert.equal(body.revision, 1);
  assert.equal(body.context_gateway_bypass, false);
  assert.equal(body.raw_audio_transferred, false);
  assert.equal(body.private_transcript_transferred, false);
  assert.equal(JSON.stringify(body).includes("synthetic-client-secret"), false);
});

test("malformed UTF-8 in Access JWT and JWKS JSON is denied", async () => {
  const malformed = MALFORMED_UTF8_CASES[0];
  for (const field of ["header", "payload"]) {
    __testing.reset();
    const fixture = await signingFixture();
    const now = Math.floor(Date.now() / 1000);
    const header = { alg: "RS256", kid: "kid-test", typ: "a" };
    const payload = {
      iss: ISSUER, aud: AUDIENCE, sub: "reviewer-synthetic", email: "reviewer@example.test",
      iat: now - 1, nbf: now - 1, exp: now + 300, note: "a",
    };
    const headerBytes = field === "header"
      ? malformedJsonBytes(header, "typ", malformed.bytes)
      : new TextEncoder().encode(JSON.stringify(header));
    const payloadBytes = field === "payload"
      ? malformedJsonBytes(payload, "note", malformed.bytes)
      : new TextEncoder().encode(JSON.stringify(payload));
    const jwt = await fixture.signedTokenFromBytes(headerBytes, payloadBytes);
    const calls = installFetch(fixture);
    const response = await worker.fetch(
      withJwt("https://preview.example.test/healthz", jwt),
      env(),
    );
    const label = `${field}/${malformed.name}`;
    assert.equal(response.status, 401, label);
    assert.equal(calls.jwks, 0, label);
  }

  __testing.reset();
  const fixture = await signingFixture();
  const body = malformedJsonBytes({ keys: [fixture.jwk], marker: "a" }, "marker", malformed.bytes);
  const stream = streamingResponse([body], { contentLength: String(body.byteLength) });
  const calls = installFetch(fixture, { onJwks: () => stream.response });
  const response = await worker.fetch(
    withJwt("https://preview.example.test/healthz", await fixture.token()),
    env(),
  );
  assert.equal(response.status, 401, malformed.name);
  assert.equal(calls.gateway, 0, malformed.name);
});

test("malformed UTF-8 in review JSON is denied before gateway forwarding", async () => {
  for (const malformed of MALFORMED_UTF8_CASES) {
    __testing.reset();
    const fixture = await signingFixture();
    const body = malformedJsonBytes(
      { action: "edit", expected_revision: 1, edited_overview: "Synthetic overview." },
      "edited_overview",
      malformed.bytes,
    );
    const calls = installFetch(fixture);
    const response = await worker.fetch(
      withJwt("https://preview.example.test/voice/review/doc-safe-1", await fixture.token(), {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "content-length": String(body.byteLength),
        },
        body,
      }),
      env(),
    );
    assert.equal(response.status, 400, malformed.name);
    assert.equal((await response.json()).error, "review_body_denied", malformed.name);
    assert.equal(calls.gateway, 0, malformed.name);
  }
});

test("malformed UTF-8 in Context Gateway JSON is denied as a body failure", async () => {
  for (const malformed of MALFORMED_UTF8_CASES) {
    __testing.reset();
    const fixture = await signingFixture();
    const body = malformedJsonBytes(projection(), "overview", malformed.bytes);
    const stream = streamingResponse([body], { contentLength: String(body.byteLength) });
    const calls = installFetch(fixture, { onGateway: () => stream.response });
    const response = await worker.fetch(
      withJwt("https://preview.example.test/voice/review", await fixture.token()),
      env(),
    );
    assert.equal(response.status, 502, malformed.name);
    assert.equal((await response.json()).error, "context_gateway_body_denied", malformed.name);
    assert.equal(calls.gateway, 1, malformed.name);
  }
});

test("valid and absent optional speaker references survive projection allowlisting", async () => {
  __testing.reset();
  const { jwk, token } = await signingFixture();
  const expected = projection({
    speaker_highlights: [
      { summary: "A highlight with a valid speaker reference.", speaker_ref: "speaker-highlight-1" },
      { summary: "A highlight without a speaker reference." },
    ],
    todos: [
      { summary: "A todo with a valid owner reference.", owner: "speaker-owner-1", due: "2026-08-10" },
      { summary: "A todo without an owner reference.", due: "2026-08-11" },
    ],
  });
  __testing.setFetch(async (request) => {
    const value = request instanceof Request ? request : new Request(request);
    if (value.url === `${ISSUER}/cdn-cgi/access/certs`) return Response.json({ keys: [jwk] });
    return Response.json(expected);
  });

  const response = await worker.fetch(
    withJwt("https://preview.example.test/voice/review", await token()),
    env(),
  );
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), expected);
});

test("explicit speaker_ref and owner values must match safe reference syntax", async () => {
  const fields = [
    ["speaker_highlights", "speaker_ref"],
    ["decisions", "speaker_ref"],
    ["todos", "owner"],
    ["open_questions", "owner"],
  ];
  const invalidValues = ["", " ", "\t", "speaker-", "speaker-A", "speaker-a/b", null, 42, {}];

  for (const [section, field] of fields) {
    for (const invalid of invalidValues) {
      __testing.reset();
      const { jwk, token } = await signingFixture();
      let gatewayCalls = 0;
      __testing.setFetch(async (request) => {
        const value = request instanceof Request ? request : new Request(request);
        if (value.url === `${ISSUER}/cdn-cgi/access/certs`) return Response.json({ keys: [jwk] });
        gatewayCalls += 1;
        return Response.json(projection({
          [section]: [{ summary: "Invalid optional reference.", [field]: invalid }],
        }));
      });

      const response = await worker.fetch(
        withJwt("https://preview.example.test/voice/review", await token()),
        env(),
      );
      assert.equal(response.status, 502, `${section}.${field}=${JSON.stringify(invalid)}`);
      assert.equal(
        (await response.json()).error,
        "context_gateway_projection_denied",
        `${section}.${field}=${JSON.stringify(invalid)}`,
      );
      assert.equal(gatewayCalls, 1, `${section}.${field}=${JSON.stringify(invalid)}`);
    }
  }
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

test("J1-RED/J1-01: oversized Access JWKS streams are refused without arrayBuffer", async () => {
  __testing.reset();
  const { token } = await signingFixture();
  const stream = streamingResponse(
    [new Uint8Array(262_144), new Uint8Array(1)],
    { trapArrayBuffer: true },
  );
  let gatewayCalls = 0;
  __testing.setFetch(async (request) => {
    const value = request instanceof Request ? request : new Request(request);
    if (value.url === `${ISSUER}/cdn-cgi/access/certs`) return stream.response;
    gatewayCalls += 1;
    return Response.json({ keys: [] });
  });

  const response = await worker.fetch(
    withJwt("https://preview.example.test/healthz", await token()),
    env(),
  );
  assert.equal(response.status, 401);
  assert.equal(stream.pulls, 2);
  assert.equal(stream.cancelled, true);
  assert.equal(gatewayCalls, 0);
});

test("J1-02: Access JWKS stream read errors fail closed", async () => {
  __testing.reset();
  const { token } = await signingFixture();
  let pulls = 0;
  const body = new ReadableStream(
    {
      pull(controller) {
        pulls += 1;
        controller.error(new Error("synthetic JWKS read failure"));
      },
    },
    { highWaterMark: 0 },
  );
  const responseWithError = {
    ok: true,
    headers: new Headers({ "content-type": "application/json" }),
    body,
    arrayBuffer() {
      throw new Error("JWKS arrayBuffer must not be called");
    },
  };
  __testing.setFetch(async (request) => {
    const value = request instanceof Request ? request : new Request(request);
    if (value.url === `${ISSUER}/cdn-cgi/access/certs`) return responseWithError;
    return Response.json({ keys: [] });
  });

  const response = await worker.fetch(
    withJwt("https://preview.example.test/healthz", await token()),
    env(),
  );
  assert.equal(response.status, 401);
  assert.equal(pulls, 1);
});

test("J1-03: an underreported Access JWKS length still enforces the byte bound", async () => {
  __testing.reset();
  const { token } = await signingFixture();
  const stream = streamingResponse(
    [new Uint8Array(262_144), new Uint8Array(1)],
    { contentLength: "1", trapArrayBuffer: true },
  );
  __testing.setFetch(async (request) => {
    const value = request instanceof Request ? request : new Request(request);
    if (value.url === `${ISSUER}/cdn-cgi/access/certs`) return stream.response;
    return Response.json({ keys: [] });
  });

  const response = await worker.fetch(
    withJwt("https://preview.example.test/healthz", await token()),
    env(),
  );
  assert.equal(response.status, 401);
  assert.equal(stream.pulls, 2);
  assert.equal(stream.cancelled, true);
});

test("a cached JWKS refreshes once when Cloudflare rotates to a new kid", async () => {
  __testing.reset();
  const original = await signingFixture("kid-original");
  const rotated = await signingFixture("kid-rotated");
  let jwksCalls = 0;
  __testing.setFetch(async (request) => {
    const value = request instanceof Request ? request : new Request(request);
    assert.equal(value.url, `${ISSUER}/cdn-cgi/access/certs`);
    jwksCalls += 1;
    return Response.json({ keys: [jwksCalls === 1 ? original.jwk : rotated.jwk] });
  });

  const beforeRotation = await worker.fetch(
    withJwt("https://preview.example.test/healthz", await original.token()),
    env(),
  );
  assert.equal(beforeRotation.status, 200);
  const afterRotation = await worker.fetch(
    withJwt("https://preview.example.test/healthz", await rotated.token()),
    env(),
  );
  assert.equal(afterRotation.status, 200);
  assert.equal(jwksCalls, 2);
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
    return Response.json(projection({ revision: 2, human_review: {
      required: true,
      state: "accepted",
      actions: ["accept", "edit", "reject"],
    } }));
  });

  const response = await worker.fetch(
    withJwt("https://preview.example.test/voice/review/doc-safe-1", jwt, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ action: "accept", expected_revision: 1 }),
    }),
    env(),
  );
  assert.equal(response.status, 200);
  assert.equal(observed.url, `${GATEWAY}/v1/voice/handoffs/doc-safe-1/review`);
  assert.equal(observed.method, "POST");
  assert.deepEqual(await observed.clone().json(), { action: "accept", expected_revision: 1 });
});

test("GW-RED/GW-STREAM: oversized gateway responses use a bounded reader, not arrayBuffer", async () => {
  __testing.reset();
  const { jwk, token } = await signingFixture();
  const stream = streamingResponse(
    [new Uint8Array(1_048_576), new Uint8Array(1)],
    { trapArrayBuffer: true },
  );
  let gatewayCalls = 0;
  __testing.setFetch(async (request) => {
    const value = request instanceof Request ? request : new Request(request);
    if (value.url === `${ISSUER}/cdn-cgi/access/certs`) return Response.json({ keys: [jwk] });
    gatewayCalls += 1;
    return stream.response;
  });

  const response = await worker.fetch(
    withJwt("https://preview.example.test/voice/review", await token()),
    env(),
  );
  assert.equal(response.status, 502);
  assert.equal((await response.json()).error, "context_gateway_body_denied");
  assert.equal(stream.pulls, 2);
  assert.equal(stream.cancelled, true);
  assert.equal(gatewayCalls, 1);
});

test("GW-LENGTH: invalid or known-oversize gateway content lengths cancel before pulling", async () => {
  for (const contentLength of ["invalid", "9007199254740992", "1048577"]) {
    __testing.reset();
    const { jwk, token } = await signingFixture();
    const stream = streamingResponse([new Uint8Array(1)], { contentLength });
    __testing.setFetch(async (request) => {
      const value = request instanceof Request ? request : new Request(request);
      if (value.url === `${ISSUER}/cdn-cgi/access/certs`) return Response.json({ keys: [jwk] });
      return stream.response;
    });

    const response = await worker.fetch(
      withJwt("https://preview.example.test/voice/review", await token()),
      env(),
    );
    assert.equal(response.status, 502, contentLength);
    assert.equal((await response.json()).error, "context_gateway_body_denied", contentLength);
    assert.equal(stream.pulls, 0, contentLength);
    assert.equal(stream.cancelled, true, contentLength);
  }
});

test("GW-UNDERREPORT: a gateway body larger than its declared length is cancelled", async () => {
  __testing.reset();
  const { jwk, token } = await signingFixture();
  const stream = streamingResponse(
    [new Uint8Array(1_048_576), new Uint8Array(1)],
    { contentLength: "1", trapArrayBuffer: true },
  );
  __testing.setFetch(async (request) => {
    const value = request instanceof Request ? request : new Request(request);
    if (value.url === `${ISSUER}/cdn-cgi/access/certs`) return Response.json({ keys: [jwk] });
    return stream.response;
  });

  const response = await worker.fetch(
    withJwt("https://preview.example.test/voice/review", await token()),
    env(),
  );
  assert.equal(response.status, 502);
  assert.equal((await response.json()).error, "context_gateway_body_denied");
  assert.equal(stream.pulls, 2);
  assert.equal(stream.cancelled, true);
});

test("GW-REGRESSION: valid Unicode JSON keeps successful bounded readback semantics", async () => {
  __testing.reset();
  const { jwk, token } = await signingFixture();
  const expected = projection({ overview: "日本語の概要 🌸" });
  const encoded = new TextEncoder().encode(JSON.stringify(expected));
  const emojiStart = encoded.indexOf(0xf0);
  assert.notEqual(emojiStart, -1);
  const withBom = Uint8Array.from([0xef, 0xbb, 0xbf, ...encoded]);
  const splitAt = emojiStart + 4;
  const stream = streamingResponse(
    [withBom.slice(0, splitAt), withBom.slice(splitAt)],
    { contentLength: String(withBom.byteLength), trapArrayBuffer: true },
  );
  __testing.setFetch(async (request) => {
    const value = request instanceof Request ? request : new Request(request);
    if (value.url === `${ISSUER}/cdn-cgi/access/certs`) return Response.json({ keys: [jwk] });
    return stream.response;
  });

  const response = await worker.fetch(
    withJwt("https://preview.example.test/voice/review", await token()),
    env(),
  );
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), expected);
  assert.equal(stream.cancelled, false);
});

test("oversized review streams are cancelled as soon as the byte limit is crossed", async () => {
  for (const declaredLength of [null, "1"]) {
    __testing.reset();
    const { jwk, token } = await signingFixture();
    let gatewayCalls = 0;
    __testing.setFetch(async (request) => {
      const value = request instanceof Request ? request : new Request(request);
      if (value.url === `${ISSUER}/cdn-cgi/access/certs`) return Response.json({ keys: [jwk] });
      gatewayCalls += 1;
      return Response.json(projection());
    });

    const chunks = [new Uint8Array(8_192), new Uint8Array(8_193), new Uint8Array(1_024)];
    let pulls = 0;
    let cancelled = false;
    const body = new ReadableStream(
      {
        pull(controller) {
          if (pulls === chunks.length) {
            controller.close();
            return;
          }
          controller.enqueue(chunks[pulls]);
          pulls += 1;
        },
        cancel() {
          cancelled = true;
        },
      },
      { highWaterMark: 0 },
    );
    const headers = { "content-type": "application/json" };
    if (declaredLength !== null) headers["content-length"] = declaredLength;

    const response = await worker.fetch(
      withJwt("https://preview.example.test/voice/review/doc-safe-1", await token(), {
        method: "POST",
        headers,
        body,
        duplex: "half",
      }),
      env(),
    );
    assert.equal(response.status, 400, String(declaredLength));
    assert.equal(cancelled, true, String(declaredLength));
    assert.equal(pulls, 2, String(declaredLength));
    assert.equal(gatewayCalls, 0, String(declaredLength));
  }
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

test("review requires a positive safe expected revision and denies private fields before forwarding", async () => {
  __testing.reset();
  const fixture = await signingFixture();
  const jwt = await fixture.token();
  const calls = installFetch(fixture);
  for (const body of [
    { action: "accept" },
    ...[null, 0, -1, 1.5, "1", Number.MAX_SAFE_INTEGER].map((expected_revision) => ({ action: "accept", expected_revision })),
    { action: "accept", expected_revision: 1, source_body: "private" },
  ]) {
    const response = await worker.fetch(withJwt("https://preview.example.test/voice/review/doc-safe-1", jwt, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
    }), env());
    assert.equal(response.status, 400);
  }
  assert.equal(calls.gateway, 0);
});

test("projection identity and review readback cannot silently drift", async () => {
  const fixture = await signingFixture();
  const jwt = await fixture.token();
  for (const extra of [{ handoff_id: "../unsafe" }, { handoff_id: null }, { revision: 0 }, { revision: "1" }]) {
    __testing.reset();
    installFetch(fixture, { onGateway: () => Response.json(projection(extra)) });
    assert.equal((await worker.fetch(withJwt("https://preview.example.test/voice/review", jwt), env())).status, 502);
  }
  for (const extra of [{ handoff_id: "different-id" }, { revision: 1 }, { human_review: projection().human_review }]) {
    __testing.reset();
    const accepted = { revision: 2, human_review: { ...projection().human_review, state: "accepted" } };
    installFetch(fixture, { onGateway: () => Response.json(projection({ ...accepted, ...extra })) });
    const response = await worker.fetch(withJwt("https://preview.example.test/voice/review/doc-safe-1", jwt, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action: "accept", expected_revision: 1 }),
    }), env());
    assert.equal(response.status, 502);
  }
});

test("duplicate review keys cannot be normalized before reaching the Gateway", async () => {
  __testing.reset();
  const fixture = await signingFixture();
  const calls = installFetch(fixture);
  for (const body of [
    '{"action":"accept","action":"reject","expected_revision":1}',
    '{"action":"accept","expected_revision":1,"expected_revision":2}',
    '{"action":"accept","expected_revision":1,"expected_\\u0072evision":2}',
  ]) {
    const response = await worker.fetch(withJwt("https://preview.example.test/voice/review/doc-safe-1", await fixture.token(), {
      method: "POST", headers: { "content-type": "application/json" }, body,
    }), env());
    assert.equal(response.status, 400);
  }
  assert.equal(calls.gateway, 0);
});

test("Worker GET -> review -> restart -> GET uses the actual persistent local HTTP Gateway", async () => {
  const stateRoot = mkdtempSync(join(tmpdir(), "kotodama-edge-roundtrip-"));
  const config = env();
  config.CONTEXT_GATEWAY_CLIENT_SECRET = randomBytes(32).toString("hex");
  const gatewayConfig = { stateRoot, clientId: config.CONTEXT_GATEWAY_CLIENT_ID, clientSecret: config.CONTEXT_GATEWAY_CLIENT_SECRET };
  const fixture = await signingFixture();
  const jwt = await fixture.token();
  let gateway;
  try {
    gateway = await startReviewGateway({ ...gatewayConfig, seeds: syntheticCatalog() });
    __testing.reset();
    __testing.setFetch(async (request) => {
      const url = new URL(request.url);
      if (url.href === `${ISSUER}/cdn-cgi/access/certs`) return Response.json({ keys: [fixture.jwk] });
      assert.equal(url.origin, GATEWAY);
      // Transport substitution only: the production Worker remains HTTPS-only.
      return fetch(new Request(`${gateway.origin}${url.pathname}${url.search}`, request));
    });
    const get = () => worker.fetch(withJwt("https://preview.example.test/voice/review", jwt), config);
    const initial = await (await get()).json();
    assert.equal(initial.handoff_id, "handoff-synthetic-1");
    assert.equal(initial.revision, 1);
    const review = (token, body) => worker.fetch(withJwt(`https://preview.example.test/voice/review/${initial.handoff_id}`, token, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
    }), config);
    const body = { action: "edit", expected_revision: initial.revision, edited_overview: "Worker から訂正した合成概要。" };
    assert.equal((await review(await fixture.token({ sub: "other-reviewer" }), body)).status, 404);
    const accepted = await review(jwt, body);
    assert.equal(accepted.status, 200);
    assert.equal((await accepted.json()).revision, 2);
    assert.equal((await review(jwt, body)).status, 409);
    assert.equal((await review(jwt, { ...body, expected_revision: 2, private_transcript: "forbidden" })).status, 400);
    await gateway.close();
    gateway = await startReviewGateway(gatewayConfig);
    const persisted = await (await get()).json();
    assert.equal(persisted.overview, body.edited_overview);
    assert.equal(persisted.human_review.state, "edited");
    assert.equal(persisted.revision, 2);
    assert.equal(persisted.promotion, false);
    assert.equal(persisted.current_truth_mutation, false);
    assert.equal(persisted.public_beta, "NO_GO_UNPUBLISHED");
  } finally {
    __testing.reset();
    if (gateway) await gateway.close();
    rmSync(stateRoot, { recursive: true, force: true });
  }
});
