import assert from "node:assert/strict";
import { test } from "node:test";
import { request } from "node:http";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createHash, randomBytes } from "node:crypto";
import { startReviewGateway } from "../../runtime/local-review-gateway/server.mjs";
import { syntheticSeed, syntheticCatalog, syntheticTenantDigest } from "../../runtime/local-review-gateway/synthetic-fixture.mjs";

function auth(config, seed) {
  return { "cf-access-client-id": config.clientId, "cf-access-client-secret": config.clientSecret,
    "x-kotodama-access-subject": seed.actor.subject, "x-kotodama-access-email": seed.actor.email,
    "x-kotodama-tenant-digest": syntheticTenantDigest, "x-kotodama-purpose": "voice_review",
    "content-type": "application/json" };
}

test("HTTP read and review reject mismatched or missing tenant/purpose despite valid actor and service auth", async () => {
  const stateRoot = mkdtempSync(join(tmpdir(), "kotodama-context-scope-"));
  const config = { stateRoot, clientId: "test-client", clientSecret: randomBytes(32).toString("hex") };
  const seed = syntheticSeed();
  let gateway;
  try {
    gateway = await startReviewGateway({ ...config, seeds: syntheticCatalog([seed]) });
    const original = readFileSync(join(stateRoot, "voice-reviews.json"));
    for (const patch of [{ "x-kotodama-tenant-digest": "b".repeat(64) },
      { "x-kotodama-tenant-digest": "" }, { "x-kotodama-purpose": "export" }, { "x-kotodama-purpose": "" }]) {
      const headers = { ...auth(config, seed), ...patch };
      const read = await fetch(`${gateway.origin}/v1/voice/handoffs`, { headers });
      assert.equal(read.status, 404);
      assert.equal(read.headers.get("x-kotodama-context-outcome"), "refused");
      assert.equal(read.headers.get("x-kotodama-context-policy"), null);
      assert.equal((await read.text()).includes(seed.projection.overview), false);
      const review = await fetch(`${gateway.origin}/v1/voice/handoffs/${seed.projection.handoff_id}/review`, {
        method: "POST", headers, body: JSON.stringify({ action: "accept", expected_revision: 1 }),
      });
      assert.equal(review.status, 404);
    }
    assert.deepEqual(readFileSync(join(stateRoot, "voice-reviews.json")), original);
    const accepted = await fetch(`${gateway.origin}/v1/voice/handoffs`, { headers: auth(config, seed) });
    assert.equal(accepted.status, 200);
    assert.equal(accepted.headers.get("x-kotodama-context-policy"), createHash("sha256").update(JSON.stringify(seed.access_policy)).digest("hex"));
    assert.equal(accepted.headers.get("x-kotodama-context-provenance"), createHash("sha256").update(JSON.stringify(seed.projection.evidence_pointers)).digest("hex"));
    assert.equal(accepted.headers.get("x-kotodama-context-backend"), "local-review-gateway/v3");
    assert.ok(["under_100ms", "under_1s", "at_least_1s"].includes(accepted.headers.get("x-kotodama-context-latency")));
  } finally { if (gateway) await gateway.close(); rmSync(stateRoot, { recursive: true, force: true }); }
});

test("expired/revoked consent is refused and revocation persists after restart", async () => {
  for (const mode of ["expired", "revoked"]) {
    const stateRoot = mkdtempSync(join(tmpdir(), "kotodama-context-consent-"));
    const config = { stateRoot, clientId: "test-client", clientSecret: randomBytes(32).toString("hex") };
    const seed = syntheticSeed();
    let gateway;
    try {
      gateway = await startReviewGateway({ ...config, seeds: syntheticCatalog([seed]) });
      const policy = structuredClone(seed.access_policy); policy.revision = 2;
      if (mode === "expired") policy.context_scope.consent.expires_at = "2020-01-01T00:00:00.000Z";
      else policy.context_scope.consent.state = "revoked";
      gateway.updateAccessPolicy({ handoffId: seed.projection.handoff_id, expectedPolicyRevision: 1, policy });
      assert.throws(() => gateway.inspectHandoff(seed.principal_ref, seed.projection.handoff_id), /handoff_not_found/);
      await gateway.close(); gateway = await startReviewGateway(config);
      assert.equal((await fetch(`${gateway.origin}/v1/voice/handoffs`, { headers: auth(config, seed) })).status, 404);
    } finally { if (gateway) await gateway.close(); rmSync(stateRoot, { recursive: true, force: true }); }
  }
});

test("consent changed while a review body is pending wins before commit", async () => {
  const stateRoot = mkdtempSync(join(tmpdir(), "kotodama-consent-race-"));
  const config = { stateRoot, clientId: "test-client", clientSecret: randomBytes(32).toString("hex") };
  const seed = syntheticSeed();
  let gateway;
  try {
    gateway = await startReviewGateway({ ...config, seeds: syntheticCatalog([seed]) });
    const body = JSON.stringify({ action: "accept", expected_revision: 1 });
    const pending = request(`${gateway.origin}/v1/voice/handoffs/${seed.projection.handoff_id}/review`, {
      method: "POST", headers: { ...auth(config, seed), "content-length": Buffer.byteLength(body) },
    });
    const response = new Promise((resolve, reject) => {
      pending.on("error", reject); pending.on("response", res => { res.resume(); res.on("end", () => resolve(res.statusCode)); });
    });
    pending.write(body.slice(0, -1));
    await new Promise(resolve => setTimeout(resolve, 20));
    const policy = structuredClone(seed.access_policy); policy.revision = 2; policy.context_scope.consent.state = "revoked";
    gateway.updateAccessPolicy({ handoffId: seed.projection.handoff_id, expectedPolicyRevision: 1, policy });
    pending.end(body.slice(-1));
    assert.equal(await response, 404);
    assert.equal(JSON.parse(readFileSync(join(stateRoot, "voice-reviews.json"))).catalog.records[0].projection.revision, 1);
  } finally { if (gateway) await gateway.close(); rmSync(stateRoot, { recursive: true, force: true }); }
});

test("unbound provenance and old v2 state are refused without rewriting saved bytes", async () => {
  const stateRoot = mkdtempSync(join(tmpdir(), "kotodama-context-source-"));
  const config = { stateRoot, clientId: "test-client", clientSecret: randomBytes(32).toString("hex") };
  const seed = syntheticSeed();
  try {
    seed.access_policy.context_scope.consent.source_refs = [`urn:kotodama:evidence:sha256:${"b".repeat(64)}`];
    await assert.rejects(startReviewGateway({ ...config, seeds: syntheticCatalog([seed]) }), /seed_denied/);
    const old = Buffer.from(JSON.stringify({ schema: "kotodama/local-voice-review-candidates/v2", catalog: {} }));
    writeFileSync(join(stateRoot, "voice-reviews.json"), old);
    await assert.rejects(startReviewGateway(config), /store_denied/);
    assert.deepEqual(readFileSync(join(stateRoot, "voice-reviews.json")), old);
  } finally { rmSync(stateRoot, { recursive: true, force: true }); }
});
