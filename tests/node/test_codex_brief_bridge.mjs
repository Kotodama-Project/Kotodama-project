import assert from "node:assert/strict";
import { test } from "node:test";
import { randomBytes, randomUUID } from "node:crypto";
import { mkdtempSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { request as httpRequest } from "node:http";
import { startBriefBridge, projectionDigest, grantDigest } from "../../runtime/codex-task-bridge/server.mjs";
import { parseCodexEvents, codexArguments, validateBrief } from "../../runtime/codex-task-bridge/codex-runner.mjs";
import { syntheticSeed, syntheticCatalog } from "../../runtime/local-review-gateway/synthetic-fixture.mjs";
import { validateAdmission, validateSource, validateQueued, validateResult, validateRevoked } from "../../runtime/cloudflare-os-kotodama/gatekeeper-kotodama-brief/src/protocol.mjs";

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
    const body = { request_id, source_revision: 1, binding_sha256: grantDigest(config.grant) };
    assert.equal((await call(bridge, config, "/v1/briefs", { body })).status, 202);
    assert.equal((await call(bridge, config, "/v1/briefs", { body: { source_revision: 1, request_id, binding_sha256: grantDigest(config.grant) } })).status, 202);
    assert.equal((await call(bridge, config, "/v1/briefs", { body: { request_id: randomUUID(), source_revision: 1, binding_sha256: grantDigest(config.grant) } })).status, 409);
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
    await call(bridge, config, "/v1/briefs", { body: { request_id, source_revision: 1, binding_sha256: grantDigest(config.grant) } });
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
      assert.equal((await call(bridge, config, "/v1/briefs", { body: { request_id: randomUUID(), source_revision: 1, binding_sha256: grantDigest(config.grant) } })).status, 404, mode);
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
    assert.equal((await call(bridge, config, "/v1/briefs", { body: { request_id, source_revision: 1, binding_sha256: grantDigest(config.grant) } })).status, 202);
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

test("an old queued binding cannot invoke a replacement grant with the same source revision", async () => {
  const { root, config } = fixture(); let bridge; let calls = 0;
  const invoke = async () => { calls += 1; return { brief }; };
  try {
    bridge = await startBriefBridge(config, { invoke });
    const source = await (await call(bridge, config, "/v1/handoff")).json();
    await bridge.close();
    const successor = { ...config, seeds: undefined, grant: { ...config.grant, work_order_ref: "work-order:replacement" } };
    bridge = await startBriefBridge(successor, { invoke });
    assert.equal((await call(bridge, successor, "/v1/briefs", { body: {
      request_id: randomUUID(), source_revision: source.revision, binding_sha256: source.binding_sha256 } })).status, 409);
    assert.equal((await call(bridge, successor, "/v1/briefs", { body: { request_id: randomUUID(), source_revision: 1 } })).status, 400);
    assert.equal(calls, 0);
  } finally { if (bridge) await bridge.close(); rmSync(root, { recursive: true, force: true }); }
});

test("shutdown is bounded and quarantines the writer when a runner ignores cancellation", async () => {
  const { root, config } = fixture(); let finish;
  const bridge = await startBriefBridge(config, { shutdownTimeoutMs: 25, invoke: () => new Promise((resolve) => { finish = resolve; }) });
  try {
    await call(bridge, config, "/v1/briefs", { body: { request_id: randomUUID(), source_revision: 1, binding_sha256: grantDigest(config.grant) } });
    const started = Date.now();
    await assert.rejects(bridge.close(), /shutdown_termination_uncertain/);
    assert.ok(Date.now() - started < 1500);
    const before = readFileSync(join(config.stateRoot, "invocations.json"), "utf8");
    assert.equal(JSON.parse(before).jobs[0].state, "interrupted");
    await assert.rejects(startBriefBridge({ ...config, seeds: undefined }), /EEXIST/);
    finish({ brief }); await new Promise(setImmediate);
    assert.equal(readFileSync(join(config.stateRoot, "invocations.json"), "utf8"), before);
  } finally { finish?.({ brief }); rmSync(root, { recursive: true, force: true }); }
});

test("OS wire validation refuses successful HTTP bodies with wrong identity, authority, state or shape", () => {
  const requestId = randomUUID();
  const samples = [
    [validateAdmission, { allowed: true, binding_sha256: "a".repeat(64) }],
    [validateSource, { handoff_id: "example", revision: 1, overview: "依頼", binding_sha256: "a".repeat(64) }],
    [(v) => validateQueued(v, requestId), { request_id: requestId, state: "running", task_state_changed: false }],
    [(v) => validateResult(v, requestId), { request_id: requestId, state: "ready", brief, task_state_changed: false, publication: false }],
    [validateRevoked, { revoked: true }],
  ];
  for (const [validate, value] of samples) {
    assert.deepEqual(validate(value), value);
    for (const invalid of [null, [], {}, { ...value, extra: true }]) assert.throws(() => validate(invalid));
  }
  const ready = samples[3][1];
  for (const patch of [{ request_id: randomUUID() }, { state: "completed" }, { task_state_changed: true }, { publication: true },
    { state: "running" }, { brief: { ...brief, constraints: [] } }]) assert.throws(() => validateResult({ ...ready, ...patch }, requestId));
  assert.throws(() => validateSource({ ...samples[1][1], revision: 0 }));
  assert.throws(() => validateAdmission({ ...samples[0][1], allowed: false }));
});

test("the actual Gadget preserves delayed approval, rejection and restart without duplicate dispatch", async () => {
  const path = new URL("../../runtime/cloudflare-os-kotodama/blueprints/kotodama-requirements/files/server.js", import.meta.url);
  const sourceCode = readFileSync(path, "utf8").replace('import { DurableObject } from "cloudflare:workers";',
    'class DurableObject { constructor(ctx, env) { this.ctx = ctx; this.env = env; } }');
  const { Gadget } = await import(`data:text/javascript;base64,${Buffer.from(sourceCode).toString("base64")}`);
  for (const outcome of ["ready", "rejected"]) {
    const storage = new Map(); let calls = 0; let requestId; let state = "awaiting_approval";
    const source = { handoff_id: "example", revision: 1, overview: "依頼", binding_sha256: "a".repeat(64) };
    const api = { getSource: async () => source,
      requestBrief: async (id, revision, binding) => { calls += 1; requestId = id;
        assert.equal(revision, 1); assert.equal(binding, source.binding_sha256); return { actionId: 1 }; },
      getResult: async (id) => { assert.equal(id, requestId); return { state, brief: state === "ready" ? brief : null }; } };
    const context = { storage: { kv: { get: (key) => storage.get(key), put: (key, value) => storage.set(key, value) } } };
    const gadget = new Gadget(context, { KOTODAMA_BRIEF: api });
    assert.equal((await gadget.requestBrief()).state, "awaiting_approval");
    const restarted = new Gadget(context, { KOTODAMA_BRIEF: api });
    assert.equal((await restarted.getState()).state, "awaiting_approval");
    await restarted.requestBrief(); assert.equal(calls, 1);
    state = outcome;
    const result = await restarted.getState();
    assert.equal(result.state, outcome); assert.deepEqual(result.result, outcome === "ready" ? brief : null);
    api.getSource = async () => { throw new Error("revoked"); };
    await assert.rejects(restarted.getState(), /revoked/);
  }
});
