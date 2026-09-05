import assert from "node:assert/strict";
import { test } from "node:test";
import { existsSync, linkSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createHash, randomBytes } from "node:crypto";
import { startReviewGateway, startReviewGatewayFromCli } from "../../runtime/local-review-gateway/server.mjs";
import { syntheticSeed, syntheticCatalog } from "../../runtime/local-review-gateway/synthetic-fixture.mjs";

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
    gateway = await startReviewGateway({ ...config, seeds: syntheticCatalog() });
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
    gateway = await startReviewGateway({ ...config, seeds: syntheticCatalog() });
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
    await assert.rejects(startReviewGateway({ ...config, seeds: syntheticCatalog() }), /store_locked/);
  } finally {
    if (gateway) await gateway.close();
    rmSync(stateRoot, { recursive: true, force: true });
  }
});

test("startup refuses public bind, untrusted auth, private seeds and a non-directory store", async () => {
  const stateRoot = mkdtempSync(join(tmpdir(), "kotodama-local-review-"));
  try {
    const config = options(stateRoot);
    await assert.rejects(startReviewGateway({ ...config, host: "0.0.0.0", seeds: syntheticCatalog() }), /configuration_denied/);
    await assert.rejects(startReviewGateway({ ...config, clientSecret: "", seeds: syntheticCatalog() }), /configuration_denied/);
    const seed = syntheticSeed();
    seed.projection.source_body = "private";
    await assert.rejects(startReviewGateway({ ...config, seeds: syntheticCatalog([seed]) }), /seed_denied/);
    await assert.rejects(startReviewGateway({ ...config, stateRoot: join(stateRoot, "missing"), seeds: syntheticCatalog() }));
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
    await assert.rejects(startReviewGateway({ ...config, stateRoot: linkedDirectory, seeds: syntheticCatalog() }), /store_path_denied/);
    const source = join(external, "control.json");
    writeFileSync(source, "{}", "utf8");
    linkSync(source, join(stateRoot, "voice-reviews.json"));
    await assert.rejects(startReviewGateway({ ...config, seeds: syntheticCatalog() }), /store_denied/);
    assert.equal(readFileSync(source, "utf8"), "{}");
    rmSync(join(stateRoot, "voice-reviews.json"));
    const gateway = await startReviewGateway({ ...config, seeds: syntheticCatalog() });
    await gateway.close();
    writeFileSync(join(stateRoot, "voice-reviews.json"), "{malformed", "utf8");
    await assert.rejects(startReviewGateway({ ...config, seeds: syntheticCatalog() }));
    assert.equal(readFileSync(join(stateRoot, "voice-reviews.json"), "utf8"), "{malformed");
  } finally {
    rmSync(stateRoot, { recursive: true, force: true });
    rmSync(external, { recursive: true, force: true });
  }
});

test("exact local candidate file import -> HTTP review -> restart preserves the manually supplied candidate", async () => {
  const directory = mkdtempSync(join(tmpdir(), "kotodama-review-import-"));
  const stateRoot = join(directory, "state");
  mkdirSync(stateRoot);
  const config = options(stateRoot);
  const candidate = syntheticSeed();
  candidate.projection.handoff_id = "manual-candidate-1";
  candidate.projection.overview = "手動で用意した sanitized candidate。";
  const importFile = join(directory, "candidate.json");
  const bytes = Buffer.from(JSON.stringify(syntheticCatalog([candidate])), "utf8");
  writeFileSync(importFile, bytes);
  const expectedSha256 = createHash("sha256").update(bytes).digest("hex");
  let gateway;
  try {
    gateway = await startReviewGatewayFromCli(["--state-root", stateRoot, "--import-file", importFile, "--expected-sha256", expectedSha256], {
      CONTEXT_GATEWAY_CLIENT_ID: config.clientId, CONTEXT_GATEWAY_CLIENT_SECRET: config.clientSecret, LOCAL_REVIEW_PORT: "0",
    });
    const url = `${gateway.origin}/v1/voice/handoffs?q=manual-candidate-1`;
    const initial = await (await fetch(url, { headers: headers(config) })).json();
    assert.equal(initial.overview, "手動で用意した sanitized candidate。");
    assert.equal((await fetch(url, { headers: headers(config, { subject: "other", email: "other@example.test" }) })).status, 404);
    const reviewed = await fetch(`${gateway.origin}/v1/voice/handoffs/${initial.handoff_id}/review`, {
      method: "POST", headers: headers(config), body: JSON.stringify({ action: "accept", expected_revision: initial.revision }),
    });
    assert.equal(reviewed.status, 200);
    await gateway.close();
    gateway = await startReviewGateway(config);
    const saved = await (await fetch(`${gateway.origin}/v1/voice/handoffs`, { headers: headers(config) })).json();
    assert.equal(saved.handoff_id, "manual-candidate-1");
    assert.equal(saved.revision, 2);
    assert.equal(saved.human_review.state, "accepted");
    assert.equal(saved.promotion, false);
    assert.equal(saved.current_truth_mutation, false);
    assert.deepEqual(readFileSync(importFile), bytes);
    await gateway.close();
    const before = readFileSync(join(stateRoot, "voice-reviews.json"));
    await assert.rejects(startReviewGateway({ ...config, importFile, expectedSha256 }), /import_existing_state_denied/);
    assert.deepEqual(readFileSync(join(stateRoot, "voice-reviews.json")), before);
  } finally {
    if (gateway) await gateway.close();
    rmSync(directory, { recursive: true, force: true });
  }
});

test("candidate import refuses digest drift, private keys, missing actor, non-pending state, oversized input and aliases", async () => {
  const directory = mkdtempSync(join(tmpdir(), "kotodama-review-import-"));
  const stateRoot = join(directory, "state");
  mkdirSync(stateRoot);
  const config = options(stateRoot);
  const importFile = join(directory, "candidate.json");
  const valid = [syntheticSeed()];
  const encode = (value) => Buffer.from(JSON.stringify(syntheticCatalog(value)), "utf8");
  const digest = (bytes) => createHash("sha256").update(bytes).digest("hex");
  const privateCandidate = syntheticSeed();
  privateCandidate.projection.private_transcript = "private-body-must-not-enter-store";
  const missingActor = syntheticSeed();
  missingActor.actor = { subject: null, email: null };
  const revision = syntheticSeed();
  revision.projection.revision = 2;
  const accepted = syntheticSeed();
  accepted.projection.human_review.state = "accepted";
  try {
    for (const [bytes, expectedSha256] of [
      [encode(valid), "0".repeat(64)],
      [encode([privateCandidate]), null],
      [encode([missingActor]), null],
      [encode([revision]), null],
      [encode([accepted]), null],
      [encode(Array.from({ length: 65 }, () => syntheticSeed())), null],
      [Buffer.alloc(4_194_305, 0x20), null],
      [Buffer.from([0x7b, 0xc3, 0x28, 0x7d]), null],
    ]) {
      writeFileSync(importFile, bytes);
      await assert.rejects(startReviewGateway({ ...config, importFile, expectedSha256: expectedSha256 ?? digest(bytes) }));
      assert.equal(existsSync(join(stateRoot, "voice-reviews.json")), false);
      assert.equal(existsSync(join(stateRoot, ".voice-review-writer.lock")), false);
      assert.deepEqual(readFileSync(importFile), bytes);
    }
    writeFileSync(importFile, encode(valid));
    const expectedSha256 = digest(encode(valid));
    const hardlink = join(directory, "hardlink.json");
    linkSync(importFile, hardlink);
    await assert.rejects(startReviewGateway({ ...config, importFile: hardlink, expectedSha256 }), /import_file_denied/);
    rmSync(hardlink);
    const linked = join(directory, "linked");
    symlinkSync(directory, linked, process.platform === "win32" ? "junction" : "dir");
    await assert.rejects(startReviewGateway({ ...config, importFile: join(linked, "candidate.json"), expectedSha256 }), /store_path_denied/);
    const env = { CONTEXT_GATEWAY_CLIENT_ID: config.clientId, CONTEXT_GATEWAY_CLIENT_SECRET: config.clientSecret, LOCAL_REVIEW_PORT: "0" };
    for (const args of [
      ["--state-root", stateRoot, "--seed-synthetic", "--import-file", importFile, "--expected-sha256", expectedSha256],
      ["--state-root", stateRoot, "--import-file", importFile],
      ["--state-root", stateRoot, "--expected-sha256", expectedSha256],
      ["--state-root", stateRoot, "--import-file", importFile, "--import-file", importFile],
    ]) await assert.rejects(async () => startReviewGatewayFromCli(args, env));
    assert.equal(existsSync(join(stateRoot, "voice-reviews.json")), false);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
