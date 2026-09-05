// Run inside the pinned core checkout: node --test test/native-approval.test.mjs.
// Tests the authored native class against queue/storage/fetch doubles, not a live OS.
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import ts from "typescript";

const source = readFileSync(new URL("../src/kotodama.ts", import.meta.url), "utf8");
let compiled = ts.transpileModule(source, { compilerOptions: {
  target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, experimentalDecorators: true,
} }).outputText;
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
