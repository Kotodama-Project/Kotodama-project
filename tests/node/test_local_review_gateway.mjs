import assert from "node:assert/strict";
import { test } from "node:test";
import { linkSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomBytes } from "node:crypto";
import { startReviewGateway } from "../../runtime/local-review-gateway/server.mjs";
import { syntheticSeed } from "../../runtime/local-review-gateway/synthetic-fixture.mjs";

function options(stateRoot) {
  return { stateRoot, clientId: "synthetic-client-id", clientSecret: randomBytes(32).toString("hex") };
}

function headers(config, actor = syntheticSeed().actor) {
  return {
    "cf-access-client-id": config.clientId,
    "cf-access-client-secret": config.clientSecret,
    "x-kotodama-access-subject": actor.subject,
    "x-kotodama-access-email": actor.email,
    "content-type": "application/json",
  };
}

test("local HTTP review survives restart; another actor and stale writers cannot change it", async () => {
  const stateRoot = mkdtempSync(join(tmpdir(), "kotodama-local-review-"));
  const config = options(stateRoot);
  let gateway;
  try {
    gateway = await startReviewGateway({ ...config, seeds: [syntheticSeed()] });
    const url = `${gateway.origin}/v1/voice/handoffs`;
    const initial = await (await fetch(url, { headers: headers(config) })).json();
    assert.equal(initial.revision, 1);
    const path = `/v1/voice/handoffs/${initial.handoff_id}/review`;
    const review = { action: "edit", expected_revision: initial.revision, edited_overview: "訂正した合成概要。" };
    const wrongActor = await fetch(gateway.origin + path, {
      method: "POST", headers: headers(config, { subject: "other-reviewer", email: "other@example.test" }),
      body: JSON.stringify(review),
    });
    assert.equal(wrongActor.status, 404);
    const attempts = await Promise.all([0, 1].map(() => fetch(gateway.origin + path, {
      method: "POST", headers: headers(config), body: JSON.stringify(review),
    })));
    assert.deepEqual(attempts.map((result) => result.status).sort(), [200, 409]);
    await gateway.close();
    gateway = await startReviewGateway(config);
    const persisted = await (await fetch(`${gateway.origin}/v1/voice/handoffs?q=${initial.handoff_id}`, {
      headers: headers(config),
    })).json();
    assert.equal(persisted.overview, "訂正した合成概要。");
    assert.equal(persisted.revision, 2);
    assert.equal(persisted.human_review.state, "edited");
    assert.equal(persisted.promotion, false);
    assert.equal(persisted.current_truth_mutation, false);
    assert.equal(persisted.public_beta, "NO_GO_UNPUBLISHED");
    assert.equal((await fetch(gateway.origin + path, { method: "POST", headers: headers(config), body: JSON.stringify(review) })).status, 409);
    assert.equal(readFileSync(join(stateRoot, "voice-reviews.json"), "utf8").includes(config.clientSecret), false);
  } finally {
    if (gateway) await gateway.close();
    rmSync(stateRoot, { recursive: true, force: true });
  }
});

test("backend authentication, private keys, malformed UTF-8, duplicate keys and size fail closed", async () => {
  const stateRoot = mkdtempSync(join(tmpdir(), "kotodama-local-review-"));
  const config = options(stateRoot);
  let gateway;
  try {
    gateway = await startReviewGateway({ ...config, seeds: [syntheticSeed()] });
    const url = `${gateway.origin}/v1/voice/handoffs`;
    assert.equal((await fetch(url, { headers: { "x-kotodama-access-subject": syntheticSeed().actor.subject } })).status, 401);
    assert.equal((await fetch(url, { headers: { ...headers(config), "cf-access-client-secret": "wrong" } })).status, 401);
    assert.equal((await fetch(url, { headers: { ...headers(config), origin: "https://untrusted.example.test" } })).status, 403);
    const before = readFileSync(join(stateRoot, "voice-reviews.json"));
    const reviewUrl = `${url}/${syntheticSeed().projection.handoff_id}/review`;
    for (const body of [
      '{',
      '{"action":"accept","expected_revision":1,"private_transcript":"forbidden"}',
      '{"action":"accept","action":"reject","expected_revision":1}',
      '{"action":"accept","expected_revision":1,"expected_revision":2}',
      '{"action":"accept"}',
      '{"action":"approve","expected_revision":1}',
      Buffer.from([0x7b, 0xc3, 0x28, 0x7d]),
      "x".repeat(16_385),
    ]) {
      assert.equal((await fetch(reviewUrl, { method: "POST", headers: headers(config), body })).status, 400);
    }
    assert.equal((await fetch(`${url}?q=${"x".repeat(257)}`, { headers: headers(config) })).status, 400);
    assert.deepEqual(readFileSync(join(stateRoot, "voice-reviews.json")), before);
    await assert.rejects(startReviewGateway({ ...config, seeds: [syntheticSeed()] }), /store_locked/);
  } finally {
    if (gateway) await gateway.close();
    rmSync(stateRoot, { recursive: true, force: true });
  }
});

test("startup refuses public bind, untrusted auth, private seeds and a non-directory store", async () => {
  const stateRoot = mkdtempSync(join(tmpdir(), "kotodama-local-review-"));
  try {
    const config = options(stateRoot);
    await assert.rejects(startReviewGateway({ ...config, host: "0.0.0.0", seeds: [syntheticSeed()] }), /configuration_denied/);
    await assert.rejects(startReviewGateway({ ...config, clientSecret: "", seeds: [syntheticSeed()] }), /configuration_denied/);
    const seed = syntheticSeed();
    seed.projection.source_body = "private";
    await assert.rejects(startReviewGateway({ ...config, seeds: [seed] }), /seed_denied/);
    await assert.rejects(startReviewGateway({ ...config, stateRoot: join(stateRoot, "missing"), seeds: [syntheticSeed()] }));
  } finally {
    rmSync(stateRoot, { recursive: true, force: true });
  }
});

test("store paths cannot follow directory links or hardlinks; corrupt saved input is preserved and refused", async () => {
  const stateRoot = mkdtempSync(join(tmpdir(), "kotodama-local-review-"));
  const external = mkdtempSync(join(tmpdir(), "kotodama-review-path-control-"));
  const config = options(stateRoot);
  try {
    const linkedDirectory = join(stateRoot, "linked-store");
    symlinkSync(external, linkedDirectory, process.platform === "win32" ? "junction" : "dir");
    await assert.rejects(startReviewGateway({ ...config, stateRoot: linkedDirectory, seeds: [syntheticSeed()] }), /store_path_denied/);
    const source = join(external, "control.json");
    writeFileSync(source, "{}", "utf8");
    linkSync(source, join(stateRoot, "voice-reviews.json"));
    await assert.rejects(startReviewGateway({ ...config, seeds: [syntheticSeed()] }), /store_denied/);
    assert.equal(readFileSync(source, "utf8"), "{}");
    rmSync(join(stateRoot, "voice-reviews.json"));
    const gateway = await startReviewGateway({ ...config, seeds: [syntheticSeed()] });
    await gateway.close();
    writeFileSync(join(stateRoot, "voice-reviews.json"), "{malformed", "utf8");
    await assert.rejects(startReviewGateway({ ...config, seeds: [syntheticSeed()] }));
    assert.equal(readFileSync(join(stateRoot, "voice-reviews.json"), "utf8"), "{malformed");
  } finally {
    rmSync(stateRoot, { recursive: true, force: true });
    rmSync(external, { recursive: true, force: true });
  }
});
