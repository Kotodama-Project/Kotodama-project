// Run inside the pinned core checkout: node --test test/native-approval.test.mjs.
// Tests the authored native class against queue/storage/fetch doubles, not a live OS.
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { createRequire } from "node:module";

const source = readFileSync(new URL("../src/kotodama.ts", import.meta.url), "utf8");
const { transformSync } = createRequire(import.meta.resolve("capnweb-validate"))("esbuild");
let compiled = transformSync(source, { loader: "ts", target: "es2022", format: "esm",
  tsconfigRaw: { compilerOptions: { experimentalDecorators: true } },
}).code;
compiled = compiled.replace(/import \{[^}]+\} from "cloudflare:workers";/, `
class DurableObject { constructor(ctx, env) { this.ctx = ctx; this.env = env; } }
class WorkerEntrypoint extends DurableObject {}
class RpcTarget {}
class RpcStub { constructor(target) { return target; } }
`);
compiled = compiled.replace(/import \{[^}]+\} from "capnweb-validate";/,
  "const validateRpc = () => (...args) => args.length === 1 ? args[0] : undefined; const skipRpcValidation = validateRpc;");
compiled = compiled.replace(/import CONFIGURATOR from "[^"]+";/, 'const CONFIGURATOR = "fixture";');
compiled = compiled.replace('"./protocol.mjs"', JSON.stringify(new URL("../src/protocol.mjs", import.meta.url).href));
compiled = compiled.replace('"./project-protocol.mjs"', JSON.stringify(new URL("../src/project-protocol.mjs", import.meta.url).href));
const { KotodamaGatekeeper } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

test("native class preserves delayed, rejected and uncertain queue delivery across restart", async () => {
  const previousFetch = globalThis.fetch;
  try {
    for (const scenario of ["delayed", "rejected", "accepted-response-lost", "not-accepted-response-lost"]) {
      const store = new Map(); let queuedId; let posts = 0;
      const requestId = randomUUID(); const binding = "a".repeat(64);
      const context = { props: { principalRef: `urn:kotodama:principal:${randomUUID()}` },
        storage: { kv: { get: (key) => store.get(key), put: (key, value) => store.set(key, value) } },
        exports: { AccountState: { getByName: () => ({ isRevoked: async () => false }) } } };
      const env = { KOTODAMA_BRIDGE_ORIGIN: "http://127.0.0.1:18790", KOTODAMA_BRIDGE_SECRET: "b".repeat(64) };
      globalThis.fetch = async (url, init) => {
        assert.equal(init.redirect, "manual", "Workers supports manual/follow; redirects must never be followed with the service credential");
        const path = new URL(url).pathname;
        if (path === "/v1/admission") return Response.json({ allowed: true, binding_sha256: binding });
        if (path === "/v1/handoff") return Response.json({ handoff_id: "fixture", revision: 1, overview: "検証", binding_sha256: binding });
        if (path === "/v1/briefs") {
          posts += 1; assert.equal(JSON.parse(init.body).binding_sha256, binding);
          return Response.json({ request_id: requestId, state: "running", task_state_changed: false });
        }
        return Response.json({ request_id: requestId, state: "running", brief: null, task_state_changed: false, publication: false });
      };
      const queue = { dup() { return this; }, [Symbol.dispose]() {}, authorizeObservation: async () => {},
        submitAction: async (id) => {
          if (scenario !== "not-accepted-response-lost") queuedId = id;
          if (scenario.endsWith("response-lost")) throw new Error("transport_lost");
        } };
      let gatekeeper = new KotodamaGatekeeper(context, env);
      const session = await gatekeeper.startSession(queue);
      const requested = session.requestBrief(requestId, 1, binding);
      if (scenario.endsWith("response-lost")) await assert.rejects(requested, /transport_lost/); else await requested;
      assert.equal(posts, 0, "queue acceptance must never execute the bridge");
      gatekeeper = new KotodamaGatekeeper(context, env);
      const resumed = await gatekeeper.startSession(queue);
      assert.equal((await resumed.getResult(requestId)).state, scenario.endsWith("response-lost") ? "approval_unknown" : "awaiting_approval");
      if (scenario === "rejected") {
        await gatekeeper.rejectAction(queuedId);
        assert.equal((await resumed.getResult(requestId)).state, "rejected");
        await assert.rejects(gatekeeper.applyAction(queuedId)); assert.equal(posts, 0);
      } else if (queuedId !== undefined) {
        await gatekeeper.applyAction(queuedId); await gatekeeper.applyAction(queuedId);
        assert.equal(posts, 1); assert.equal((await resumed.getResult(requestId)).state, "running");
      } else { assert.equal(posts, 0); }
    }
  } finally { globalThis.fetch = previousFetch; }
});

test("native Project inspection uses observation only, pins identity, and honors account revocation", async () => {
  const oldFetch = globalThis.fetch; let revoked = false, observations = 0, inspections = 0, wrongImpact = false;
  const store = new Map(); const binding = "b".repeat(64), projectBinding = "c".repeat(64);
  const brief = { outcome: "原資料は別に保持", in_scope: [], out_of_scope: [], constraints: ["公開しない"], acceptance: ["同じProjectを読む"], unknowns: [] };
  const taskRefs = [{ adapter: "discord_local_task_v1", task_id: "task-00000000-0000-4000-8000-000000000001", revision: 2 }];
  const project = { version: 2, project_id: "ref/project/fixture", revision: 1, owner_ref: "ref/owner/fixture", name: "合成Project", original_ref: "ref/source/original", brief, task_refs: taskRefs };
  const view = { kind: "kotodama.project-owner-view", version: 1, authority: "selected_local_project_owner", project, project_digest: "a".repeat(64), snapshot: "current", current_revision: 1,
    source_refs: [{ key: "f".repeat(64), revision: 1, current_revision: 1, freshness: "current" }], task_state_changed: false, execution_authorized: false };
  let readBinding = projectBinding;
  const context = { props: { principalRef: `urn:kotodama:principal:${randomUUID()}` },
    storage: { kv: { get: key => store.get(key), put: (key, value) => store.set(key, value) } },
    exports: { AccountState: { getByName: () => ({ isRevoked: async () => revoked }) } } };
  const gatekeeper = new KotodamaGatekeeper(context, { KOTODAMA_BRIDGE_ORIGIN: "http://127.0.0.1:18790", KOTODAMA_BRIDGE_SECRET: "a".repeat(64) });
  const queue = { dup() { return this; }, [Symbol.dispose]() {}, authorizeObservation: async () => { observations++; }, submitAction: () => assert.fail("no action queued") };
  try {
    globalThis.fetch = async (url, init) => {
      if (new URL(url).pathname === "/v1/admission") return Response.json({ allowed: true, binding_sha256: binding });
      if (new URL(url).pathname === "/v1/project") return Response.json({ state: "connected", binding_sha256: readBinding, can_inspect: true, view });
      inspections++; const input = JSON.parse(init.body);
      return Response.json({ binding_sha256: projectBinding, inspection: { kind: "kotodama.project-change-candidate", version: 1, authority: "candidate_only", project_id: project.project_id,
        expected_revision: 1, base_digest: view.project_digest, proposal_digest: "d".repeat(64), proposal: { version: 1, project_id: project.project_id, expected_revision: 1, base_digest: view.project_digest, reason: input.reason, source_ref: "ref/source/correction", brief: input.brief },
        changed_fields: ["constraints"], removed_requirements: { constraints: brief.constraints, acceptance: [] }, impact_task_refs: wrongImpact ? [] : taskRefs, applied: false,
        next_action: "owner_revalidate_authorize_and_record_correction", source_refs: [{ key: "f".repeat(64), revision: 1 }], task_state_changed: false, execution_authorized: false } });
    };
    const session = await gatekeeper.startSession(queue);
    assert.deepEqual((await session.getProject()).view, view);
    const input = { binding_sha256: projectBinding, expected_revision: 1, base_digest: view.project_digest, reason: "条件を検査", brief: { ...brief, constraints: [] } };
    assert.equal((await session.inspectProjectChange(input)).inspection.applied, false);
    assert.equal(observations, 2); assert.equal(inspections, 1);
    wrongImpact = true; await assert.rejects(session.inspectProjectChange(input)); assert.equal(inspections, 2); wrongImpact = false;
    await assert.rejects(session.inspectProjectChange({ ...input, expected_revision: 2 })); assert.equal(inspections, 2);
    readBinding = "e".repeat(64); await assert.rejects(session.getProject());
    readBinding = projectBinding; revoked = true; await assert.rejects(session.getProject());
    assert.equal(inspections, 2);
  } finally { globalThis.fetch = oldFetch; }
});
