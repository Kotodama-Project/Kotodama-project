import assert from "node:assert/strict";
import { test } from "node:test";
import { randomBytes, randomUUID } from "node:crypto";
import { mkdtempSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { request as httpRequest } from "node:http";
import { startBriefBridge, projectionDigest } from "../../runtime/codex-task-bridge/server.mjs";
import { parseCodexEvents, codexArguments, validateBrief } from "../../runtime/codex-task-bridge/codex-runner.mjs";
import { syntheticSeed, syntheticCatalog } from "../../runtime/local-review-gateway/synthetic-fixture.mjs";

const brief = { objective: "要件を整理する", deliverable: "要件案", constraints: ["公開しない"], acceptance_criteria: ["同じ画面で読み戻せる"], open_questions: [] };
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "kotodama-brief-"));
  const stateRoot = join(root, "jobs"); const reviewStateRoot = join(root, "review");
  mkdirSync(stateRoot); mkdirSync(reviewStateRoot);
  const seed = syntheticSeed(); const seeds = syntheticCatalog([seed]);
  const worker = `urn:kotodama:principal:${randomUUID()}`;
  seeds.principals.push({ principal_ref: worker, kind: "agent", actor: { subject: "worker-synthetic", email: null } });
  seed.access_policy.readers.push(worker);
  return { root, seed, config: { stateRoot, reviewStateRoot, seeds, expectedHost: "bridge.example.test", serviceSecret: randomBytes(32).toString("hex"),
    grant: { work_order_ref: "work-order:local-brief-test", requester_ref: seed.principal_ref, worker_ref: worker,
      handoff_id: seed.projection.handoff_id, source_revision: 1, source_sha256: projectionDigest(seed.projection),
      policy_revision: 1, expires_at: new Date(Date.now() + 60_000).toISOString(), max_invocations: 1, operation: "DRAFT_REQUIREMENTS" }, runner: {} } };
}
async function call(bridge, config, path, { body, who = config.grant.requester_ref, secret = config.serviceSecret, ...extra } = {}) {
  return new Promise((accept, reject) => {
    const req = httpRequest(bridge.origin + path, { method: body === undefined ? "GET" : "POST", headers: {
      host: config.expectedHost, authorization: `Bearer ${secret}`, "x-kotodama-principal": who,
      "content-type": "application/json", ...extra } }, (res) => {
      const chunks = []; res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => accept(new Response(Buffer.concat(chunks), { status: res.statusCode })));
    });
    req.on("error", reject); req.end(body === undefined ? undefined : JSON.stringify(body));
  });
}

test("actual HTTP admission, one invocation, deterministic replay, restart and grant-bound readback", async () => {
  const { root, config } = fixture(); let bridge; let finish; let calls = 0;
  const invoke = ({ signal }) => { calls += 1; return new Promise((resolve, reject) => {
    finish = resolve; signal.addEventListener("abort", () => reject(new Error("cancelled")), { once: true });
  }); };
  try {
    bridge = await startBriefBridge(config, { invoke });
    assert.equal((await call(bridge, config, "/v1/handoff", { secret: "wrong" })).status, 401);
    assert.equal((await call(bridge, config, "/v1/handoff", { who: `urn:kotodama:principal:${randomUUID()}` })).status, 404);
    assert.equal((await call(bridge, config, "/v1/handoff", { origin: "null" })).status, 403);
    const request_id = randomUUID();
    const body = { request_id, source_revision: 1 };
    assert.equal((await call(bridge, config, "/v1/briefs", { body })).status, 202);
    assert.equal((await call(bridge, config, "/v1/briefs", { body: { source_revision: 1, request_id } })).status, 202);
    assert.equal((await call(bridge, config, "/v1/briefs", { body: { request_id: randomUUID(), source_revision: 1 } })).status, 409);
    assert.equal(calls, 1);
    finish({ brief, tool_events: 0, model_requested: "synthetic" });
    await new Promise(setImmediate);
    let result = await (await call(bridge, config, `/v1/briefs/${request_id}`)).json();
    assert.equal(result.state, "ready"); assert.deepEqual(result.brief, brief); assert.equal(result.task_state_changed, false);
    await bridge.close(); bridge = await startBriefBridge({ ...config, seeds: undefined }, { invoke: () => { throw new Error("must not rerun"); } });
    result = await (await call(bridge, config, `/v1/briefs/${request_id}`)).json();
    assert.equal(result.state, "ready");
    await bridge.close(); bridge = await startBriefBridge({ ...config, seeds: undefined, grant: { ...config.grant, work_order_ref: "work-order:different" } }, { invoke });
    assert.equal((await call(bridge, config, `/v1/briefs/${request_id}`)).status, 404);
    assert.equal(calls, 1);
  } finally { if (bridge) await bridge.close(); rmSync(root, { recursive: true, force: true }); }
});

test("revocation during inference withholds output and creates no ready artifact", async () => {
  const { root, seed, config } = fixture(); let bridge; let finish;
  try {
    bridge = await startBriefBridge(config, { invoke: ({ signal }) => new Promise((resolve, reject) => {
      finish = resolve; signal.addEventListener("abort", () => reject(new Error("cancelled")), { once: true });
    }) });
    const request_id = randomUUID();
    await call(bridge, config, "/v1/briefs", { body: { request_id, source_revision: 1 } });
    bridge.updateAccessPolicy({ handoffId: seed.projection.handoff_id, expectedPolicyRevision: 1,
      policy: { ...seed.access_policy, revision: 2, state: "revoked" } });
    finish({ brief }); await new Promise(setImmediate);
    assert.equal((await call(bridge, config, `/v1/briefs/${request_id}`)).status, 404);
    const stored = JSON.parse(readFileSync(join(config.stateRoot, "invocations.json")));
    assert.equal(stored.jobs[0].state, "failed"); assert.equal(stored.jobs[0].result, null);
  } finally { if (bridge) await bridge.close(); rmSync(root, { recursive: true, force: true }); }
});

test("invalid scopes, stale source and private categories cannot invoke a model", async () => {
  for (const mode of ["expired", "source-drift", "policy-drift", "worker-no-read", "secret", "unclassified"]) {
    const { root, seed, config } = fixture(); let bridge; let calls = 0;
    if (mode === "expired") config.grant.expires_at = "2020-01-01T00:00:00.000Z";
    if (mode === "source-drift") config.grant.source_sha256 = "a".repeat(64);
    if (mode === "policy-drift") config.grant.policy_revision = 2;
    if (mode === "worker-no-read") seed.access_policy.readers = [seed.principal_ref];
    if (["secret", "unclassified"].includes(mode)) seed.access_policy.classification = mode;
    try {
      bridge = await startBriefBridge(config, { invoke: () => { calls += 1; return { brief }; } });
      assert.equal((await call(bridge, config, "/v1/briefs", { body: { request_id: randomUUID(), source_revision: 1 } })).status, 404, mode);
      assert.equal(calls, 0);
    } finally { if (bridge) await bridge.close(); rmSync(root, { recursive: true, force: true }); }
  }
});

test("a native account revocation cancels its invocation and remains closed after restart", async () => {
  const { root, config } = fixture(); let bridge; let aborted = false;
  try {
    bridge = await startBriefBridge(config, { invoke: ({ signal }) => new Promise((_, reject) => {
      signal.addEventListener("abort", () => { aborted = true; reject(new Error("cancelled")); }, { once: true });
    }) });
    assert.equal((await call(bridge, config, "/v1/admission")).status, 200);
    const request_id = randomUUID();
    assert.equal((await call(bridge, config, "/v1/briefs", { body: { request_id, source_revision: 1, prompt: "not allowed" } })).status, 400);
    assert.equal((await call(bridge, config, "/v1/briefs", { body: { request_id, source_revision: 1 } })).status, 202);
    assert.equal((await call(bridge, config, "/v1/revoke", { body: {}, who: `urn:kotodama:principal:${randomUUID()}` })).status, 404);
    assert.equal(aborted, false);
    assert.equal((await call(bridge, config, "/v1/revoke", { body: {} })).status, 200);
    assert.equal(aborted, true);
    assert.equal((await call(bridge, config, "/v1/admission")).status, 404);
    await bridge.close(); bridge = await startBriefBridge({ ...config, seeds: undefined }, { invoke: () => { throw new Error("must not run"); } });
    assert.equal((await call(bridge, config, "/v1/admission")).status, 404);
    assert.equal((await call(bridge, config, `/v1/briefs/${request_id}`)).status, 404);
  } finally { if (bridge) await bridge.close(); rmSync(root, { recursive: true, force: true }); }
});

test("Codex parsing separates the known CLI advisory from failures and refuses tools or malformed results", () => {
  const stream = (item = { type: "agent_message", text: JSON.stringify(brief) }) => [
    { type: "thread.started", thread_id: randomUUID() }, { type: "turn.started" },
    { type: "item.completed", item }, { type: "turn.completed", usage: { input_tokens: 1, output_tokens: 1 } },
  ];
  const serialize = (rows) => rows.map((row) => JSON.stringify(row)).join("\n");
  assert.deepEqual(parseCodexEvents(serialize(stream())).brief, brief);
  const warning = stream(); warning.splice(1, 0, { type: "item.completed", item: { type: "error", message: "Under-development features enabled: skip_host_skill_discovery. Known advisory." } });
  assert.equal(parseCodexEvents(serialize(warning)).warnings.length, 1);
  for (const item of [{ type: "command_execution" }, { type: "mcp_tool_call" }, { type: "error", message: "failed" }, { type: "agent_message", text: '{"ok":true}' }]) {
    assert.throws(() => parseCodexEvents(serialize(stream(item))));
  }
  assert.throws(() => parseCodexEvents(serialize(stream().slice(0, -1))));
  assert.throws(() => validateBrief({ ...brief, authority: true }));
  const args = codexArguments({ model: "gpt-6-astra" });
  for (const control of ["read-only", "--ignore-user-config", "--ephemeral", "--output-schema", "shell_tool", "plugins", "multi_agent", "hooks"]) assert.ok(args.includes(control));
  assert.equal(args.includes("--dangerously-bypass-approvals-and-sandbox"), false);
});
