import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { request } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomBytes, randomUUID } from "node:crypto";
import { startReviewGateway, readAccessMetadata } from "../../runtime/local-review-gateway/server.mjs";
import { syntheticSeed, syntheticCatalog } from "../../runtime/local-review-gateway/synthetic-fixture.mjs";

const reader = { subject: "reader-synthetic", email: "reader@example.test" };
const readerRef = `urn:kotodama:principal:${randomUUID()}`;
function headers(config, actor) {
  return { "cf-access-client-id": config.clientId, "cf-access-client-secret": config.clientSecret,
    "x-kotodama-access-subject": actor.subject, "x-kotodama-access-email": actor.email,
    "content-type": "application/json" };
}

test("shared read is distinct from review; revocation persists and policy never leaves the backend", async () => {
  const root = mkdtempSync(join(tmpdir(), "kotodama-information-policy-"));
  const config = { stateRoot: root, clientId: "test-client", clientSecret: randomBytes(32).toString("hex") };
  const seed = syntheticSeed();
  const catalog = syntheticCatalog([seed]);
  catalog.principals.push({ principal_ref: readerRef, kind: "human", actor: reader });
  catalog.records[0].access_policy.readers.push(readerRef);
  let gateway;
  try {
    gateway = await startReviewGateway({ ...config, seeds: catalog });
    const get = (actor) => fetch(`${gateway.origin}/v1/voice/handoffs?q=${seed.projection.handoff_id}`, { headers: headers(config, actor) });
    const visible = await get(reader);
    assert.equal(visible.status, 200);
    const text = await visible.text();
    assert.equal(text.includes("access_policy"), false);
    assert.equal(text.includes(readerRef), false);
    assert.equal(text.includes(seed.access_policy.policy_id), false);
    assert.equal((await fetch(`${gateway.origin}/v1/voice/handoffs/${seed.projection.handoff_id}/review`, {
      method: "POST", headers: headers(config, reader), body: JSON.stringify({ action: "accept", expected_revision: 1 }),
    })).status, 404);
    const next = { ...seed.access_policy, revision: 2, readers: [seed.principal_ref] };
    const observed = gateway.updateAccessPolicy({ handoffId: seed.projection.handoff_id, expectedPolicyRevision: 1, policy: next });
    assert.equal(observed.policy_revision, 2);
    assert.equal((await get(reader)).status, 404);
    assert.equal((await get(seed.actor)).status, 200);
    assert.throws(() => gateway.updateAccessPolicy({ handoffId: seed.projection.handoff_id, expectedPolicyRevision: 1, policy: next }), /policy_revision_conflict/);
    await gateway.close();
    gateway = await startReviewGateway(config);
    assert.equal((await get(reader)).status, 404);
    const store = JSON.parse(readFileSync(join(root, "voice-reviews.json"), "utf8"));
    assert.equal(store.catalog.records[0].policy_history.length, 1);
    assert.equal(store.catalog.records[0].policy_history[0].readers.includes(readerRef), true);
    assert.equal(JSON.stringify(store).includes(reader.email), false);
    const metadata = readAccessMetadata(root);
    assert.equal(metadata.information[0].access_policy.owner_ref, seed.principal_ref);
    assert.equal(metadata.information[0].access_policy.revision, 2);
    for (const privateValue of ["actor_sha256", reader.email, seed.projection.overview]) assert.equal(JSON.stringify(metadata).includes(privateValue), false);
  } finally { if (gateway) await gateway.close(); rmSync(root, { recursive: true, force: true }); }
});

test("unclassified, secret, expired and unknown identities cannot retrieve content, including owners", async () => {
  for (const mode of ["unclassified", "secret", "expired", "owner-without-read", "unknown"]) {
    const root = mkdtempSync(join(tmpdir(), "kotodama-policy-denial-"));
    const seed = syntheticSeed();
    if (["unclassified", "secret"].includes(mode)) seed.access_policy.classification = mode;
    if (mode === "expired") seed.access_policy.expires_at = "2020-01-01T00:00:00.000Z";
    if (mode === "owner-without-read") { seed.access_policy.readers = []; seed.access_policy.reviewers = []; }
    const config = { stateRoot: root, clientId: "test-client", clientSecret: randomBytes(32).toString("hex") };
    let gateway;
    try {
      gateway = await startReviewGateway({ ...config, seeds: syntheticCatalog([seed]) });
      const response = await fetch(`${gateway.origin}/v1/voice/handoffs`, { headers: headers(config, mode === "unknown" ? reader : seed.actor) });
      assert.equal(response.status, 404, mode);
      assert.equal((await response.text()).includes(seed.projection.overview), false);
    } finally { if (gateway) await gateway.close(); rmSync(root, { recursive: true, force: true }); }
  }
});

test("policy changes cannot be smuggled through review; even public candidates require an explicit reader", async () => {
  const root = mkdtempSync(join(tmpdir(), "kotodama-policy-public-"));
  const seed = syntheticSeed();
  seed.access_policy.classification = "public_candidate";
  const config = { stateRoot: root, clientId: "test-client", clientSecret: randomBytes(32).toString("hex") };
  let gateway;
  try {
    gateway = await startReviewGateway({ ...config, seeds: syntheticCatalog([seed]) });
    const url = `${gateway.origin}/v1/voice/handoffs`;
    assert.equal((await fetch(url)).status, 401);
    assert.equal((await fetch(url, { headers: { ...headers(config, reader), "x-kotodama-principal-ref": seed.principal_ref } })).status, 404);
    const before = readFileSync(join(root, "voice-reviews.json"));
    for (const added of [{ access_policy: seed.access_policy }, { classification: "public_candidate" }, { readers: [readerRef] }]) {
      assert.equal((await fetch(`${url}/${seed.projection.handoff_id}/review`, {
        method: "POST", headers: headers(config, seed.actor), body: JSON.stringify({ action: "accept", expected_revision: 1, ...added }),
      })).status, 400);
    }
    assert.equal((await fetch(`${url}/${seed.projection.handoff_id}/policy`, { method: "POST", headers: headers(config, seed.actor), body: "{}" })).status, 404);
    assert.deepEqual(readFileSync(join(root, "voice-reviews.json")), before);
    const accepted = await fetch(`${url}/${seed.projection.handoff_id}/review`, {
      method: "POST", headers: headers(config, seed.actor), body: JSON.stringify({ action: "accept", expected_revision: 1 }),
    });
    assert.equal(accepted.status, 200);
    assert.equal((await accepted.json()).promotion, false);
    assert.deepEqual(JSON.parse(readFileSync(join(root, "voice-reviews.json"))).catalog.records[0].access_policy, seed.access_policy);
  } finally { if (gateway) await gateway.close(); rmSync(root, { recursive: true, force: true }); }
});

test("revocation wins over a review body already in flight", async () => {
  const root = mkdtempSync(join(tmpdir(), "kotodama-policy-race-"));
  const seed = syntheticSeed();
  const config = { stateRoot: root, clientId: "test-client", clientSecret: randomBytes(32).toString("hex") };
  let gateway;
  let req;
  try {
    gateway = await startReviewGateway({ ...config, seeds: syntheticCatalog([seed]) });
    const response = new Promise((accept, reject) => {
      req = request(`${gateway.origin}/v1/voice/handoffs/${seed.projection.handoff_id}/review`, {
        method: "POST", headers: headers(config, seed.actor),
      }, (res) => { res.resume(); res.once("end", () => accept(res.statusCode)); });
      req.once("error", reject);
    });
    req.write('{"action":"accept",');
    // A separate roundtrip lets the original body remain pending while the operator revokes access.
    assert.equal((await fetch(`${gateway.origin}/v1/voice/handoffs`, { headers: headers(config, seed.actor) })).status, 200);
    gateway.updateAccessPolicy({ handoffId: seed.projection.handoff_id, expectedPolicyRevision: 1,
      policy: { ...seed.access_policy, revision: 2, state: "revoked" } });
    req.end('"expected_revision":1}');
    assert.equal(await response, 404);
    assert.equal(JSON.parse(readFileSync(join(root, "voice-reviews.json"))).catalog.records[0].projection.revision, 1);
  } finally { req?.destroy(); if (gateway) await gateway.close(); rmSync(root, { recursive: true, force: true }); }
});

test("ambiguous principals, missing classification and dangling grants fail closed without rewriting legacy bytes", async () => {
  const root = mkdtempSync(join(tmpdir(), "kotodama-policy-invalid-"));
  const config = { stateRoot: root, clientId: "test-client", clientSecret: randomBytes(32).toString("hex") };
  try {
    const bad = [
      (input) => { delete input.records[0].access_policy; },
      (input) => { input.records[0].access_policy.readers.push(readerRef); },
      (input) => { input.records[0].access_policy.reviewers.push(readerRef); },
      (input) => { input.records[0].access_policy.classification = "public"; },
      (input) => { input.records[0].access_policy.revision = true; },
      (input) => { input.records[0].access_policy.expires_at = "2026-02-30T00:00:00.000Z"; },
      (input) => { input.principals.push({ ...input.principals[0], principal_ref: readerRef }); },
      (input) => { input.principals.push({ ...input.principals[0], actor: reader }); },
      (input) => { input.records.push(structuredClone(input.records[0])); },
    ];
    for (const mutate of bad) {
      const seeds = syntheticCatalog(); mutate(seeds);
      await assert.rejects(startReviewGateway({ ...config, seeds }));
    }
    const old = Buffer.from(JSON.stringify({ schema: "kotodama/local-voice-review-candidates/v1", records: [{ actor_sha256: "a".repeat(64), projection: syntheticSeed().projection }] }));
    writeFileSync(join(root, "voice-reviews.json"), old);
    await assert.rejects(startReviewGateway({ ...config, seeds: syntheticCatalog() }), /store_denied/);
    assert.deepEqual(readFileSync(join(root, "voice-reviews.json")), old);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("trusted policy updates validate identity/history and are disabled after releasing the writer", async () => {
  const root = mkdtempSync(join(tmpdir(), "kotodama-policy-control-"));
  const seed = syntheticSeed();
  const config = { stateRoot: root, clientId: "test-client", clientSecret: randomBytes(32).toString("hex") };
  let gateway;
  try {
    gateway = await startReviewGateway({ ...config, seeds: syntheticCatalog([seed]) });
    const before = readFileSync(join(root, "voice-reviews.json"));
    for (const patch of [{ policy_id: `urn:kotodama:access-policy:${randomUUID()}` }, { revision: 1 }, { readers: [readerRef] }, { owner_ref: readerRef }]) {
      assert.throws(() => gateway.updateAccessPolicy({ handoffId: seed.projection.handoff_id, expectedPolicyRevision: 1,
        policy: { ...seed.access_policy, revision: 2, ...patch } }));
    }
    assert.deepEqual(readFileSync(join(root, "voice-reviews.json")), before);
    await gateway.close();
    assert.throws(() => gateway.updateAccessPolicy({ handoffId: seed.projection.handoff_id, expectedPolicyRevision: 1,
      policy: { ...seed.access_policy, revision: 2 } }), /gateway_closed/);
  } finally { if (gateway) await gateway.close(); rmSync(root, { recursive: true, force: true }); }
});
