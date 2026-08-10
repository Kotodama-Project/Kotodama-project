import assert from "node:assert/strict";
import test from "node:test";

import worker from "../../runtime/cloudflare-edge/src/index.js";

const ENV = {
  DEPLOYMENT_STAGE: "preview-candidate",
  PUBLIC_BETA_STATUS: "NO_GO_UNPUBLISHED",
};

async function body(response) {
  return JSON.parse(await response.text());
}

test("the content-free preview exposes only health and version", async () => {
  const health = await worker.fetch(
    new Request("https://preview.example.test/healthz"),
    ENV,
  );
  assert.equal(health.status, 200);
  assert.deepEqual(await body(health), {
    ok: true,
    surface: "cloudflare-edge-candidate",
    public_beta: "NO_GO_UNPUBLISHED",
  });

  const version = await worker.fetch(
    new Request("https://preview.example.test/version"),
    ENV,
  );
  assert.equal(version.status, 200);
  assert.deepEqual(await body(version), {
    ok: true,
    stage: "preview-candidate",
    public_beta: "NO_GO_UNPUBLISHED",
  });

  const head = await worker.fetch(
    new Request("https://preview.example.test/healthz", { method: "HEAD" }),
    ENV,
  );
  assert.equal(head.status, 200);
  assert.equal(await head.text(), "");
});

test("Voice, Context Gateway, and unknown paths remain unavailable", async () => {
  for (const path of [
    "/voice/review",
    "/voice/review/doc-safe-1",
    "/context",
    "/search",
  ]) {
    const response = await worker.fetch(
      new Request(`https://preview.example.test${path}`),
      ENV,
    );
    assert.equal(response.status, 404, path);
    const value = await body(response);
    assert.equal(value.error, "not_found", path);
    assert.equal(value.public_beta, "NO_GO_UNPUBLISHED", path);
  }
});

test("request bodies and mutation methods fail before route handling", async () => {
  for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
    const response = await worker.fetch(
      new Request("https://preview.example.test/healthz", {
        method,
        body: method === "DELETE" ? undefined : "synthetic-body",
      }),
      ENV,
    );
    assert.equal(response.status, 405, method);
    assert.equal((await body(response)).error, "method_not_allowed", method);
  }
});

test("missing or widened runtime claims fail closed", async () => {
  for (const candidate of [
    {},
    { ...ENV, DEPLOYMENT_STAGE: "production" },
    { ...ENV, PUBLIC_BETA_STATUS: "PUBLIC_BETA" },
  ]) {
    const response = await worker.fetch(
      new Request("https://preview.example.test/version"),
      candidate,
    );
    assert.equal(response.status, 503);
    const value = await body(response);
    assert.equal(value.error, "runtime_configuration_denied");
    assert.equal(value.public_beta, "NO_GO_UNPUBLISHED");
  }
});

test("all responses retain content-free browser safety headers", async () => {
  const response = await worker.fetch(
    new Request("https://preview.example.test/not-found"),
    ENV,
  );
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.equal(response.headers.get("content-type"), "application/json; charset=utf-8");
  assert.equal(response.headers.get("referrer-policy"), "no-referrer");
  assert.equal(response.headers.get("x-content-type-options"), "nosniff");
  assert.match(response.headers.get("content-security-policy"), /default-src 'none'/);
});
