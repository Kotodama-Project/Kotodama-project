import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdtempSync, readFileSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { startLocalModelProxy } from "../../runtime/local-model-proxy/server.mjs";

test("model proxy pins model and routes, streams results, enforces budget and preserves metadata only", async () => {
  const dir = mkdtempSync(join(tmpdir(), "ktdm-model-proxy-"));
  let calls = 0;
  const upstream = createServer(async (req, res) => {
    let raw = ""; for await (const b of req) raw += b;
    const body = JSON.parse(raw); calls++;
    assert.equal(req.url, "/v1/chat/completions"); assert.equal(body.model, "test-local");
    res.writeHead(200, { "content-type": "text/event-stream" });
    res.end('data: {"choices":[{"delta":{"content":"fixture reply"}}]}\n\ndata: [DONE]\n\n');
  });
  await new Promise(accept => upstream.listen(0, "127.0.0.1", accept));
  const config = { upstream: `http://127.0.0.1:${upstream.address().port}/v1`, model: "test-local", port: 0,
    expiresAt: new Date(Date.now()+60000).toISOString(), maxRequests: 1, stateRoot: dir };
  const proxy = await startLocalModelProxy(config);
  const post = value => fetch(proxy.origin+"/v1/chat/completions", { method: "POST", headers: { "content-type":"application/json" }, body: JSON.stringify(value) });
  try {
    assert.equal((await fetch(proxy.origin+"/admin")).status, 404);
    assert.equal((await post({ model:"other", messages:[{role:"user",content:"x"}] })).status, 400);
    assert.equal((await post({ model:"test-local", messages:[{role:"user",content:"x"}], max_tokens:99999 })).status, 400);
    assert.equal((await post({ model:"test-local", messages:[{role:"user",content:"x"}], n:10 })).status, 400);
    assert.equal((await post({ model:"test-local", messages:[{role:"user",content:"x"}], max_tokens:10,max_completion_tokens:10000 })).status, 400);
    assert.equal((await post({ model:"test-local", messages:[{role:"user",content:"x"}], upstream:"http://other.invalid" })).status, 400);
    assert.equal((await post({ model:"test-local", messages:[{role:"user",content:"x"}], store:true })).status, 400);
    await assert.rejects(startLocalModelProxy(config));
    assert.equal(calls, 0);
    const response = await post({model:"test-local",messages:[{role:"user",content:"private-input-marker"}],max_tokens:128,stream:true,store:false});
    assert.equal(response.status, 200); assert.match(await response.text(), /fixture reply/);
    assert.equal((await post({model:"test-local",messages:[{role:"user",content:"again"}]})).status,429);
    assert.equal(calls,1);
    const saved=readFileSync(join(dir,"model-proxy-receipt.json"),"utf8");
    assert.ok(!saved.includes("private-input-marker") && !saved.includes("fixture reply"));
    await proxy.close();
    const resumed=await startLocalModelProxy(config);
    try { assert.equal((await fetch(resumed.origin+"/healthz").then(r=>r.json())).invocations,1); }
    finally { await resumed.close(); }
  } finally { await proxy.close(); await new Promise(accept=>upstream.close(accept)); rmSync(dir,{recursive:true,force:true}); }
});

test("model proxy refuses public upstreams and DNS names before creating a listener", async () => {
  const dir = mkdtempSync(join(tmpdir(), "ktdm-model-private-"));
  const config = { model: "test-local", port: 0, expiresAt: new Date(Date.now()+60000).toISOString(), maxRequests: 1, stateRoot: dir };
  try {
    for (const upstream of ["https://public.invalid/v1", "https://8.8.8.8/v1", "http://169.254.169.254/v1", "http://100.1.1.1/v1", "http://172.32.0.1/v1", "http://[2001:4860:4860::8888]/v1"]) {
      let proxy;
      try { await assert.rejects(async () => { proxy = await startLocalModelProxy({ ...config, upstream }); }, /upstream/); }
      finally { await proxy?.close(); }
      assert.equal(existsSync(join(dir, "model-proxy-receipt.json")), false);
    }
  } finally { rmSync(dir, { recursive:true, force:true }); }
});

test("the exported proxy enforces expiry during an active request and releases its writer", async () => {
  const dir = mkdtempSync(join(tmpdir(), "ktdm-model-expiry-"));
  let reached; const started = new Promise(resolve => { reached = resolve; });
  const upstream = createServer((req, res) => { req.resume(); reached(); });
  await new Promise(resolve => upstream.listen(0, "127.0.0.1", resolve));
  const config = { upstream:`http://127.0.0.1:${upstream.address().port}/v1`, model:"test-local", port:0,
    expiresAt:new Date(Date.now()+500).toISOString(), maxRequests:1, stateRoot:dir };
  const proxy = await startLocalModelProxy(config);
  const pending = fetch(proxy.origin+"/v1/chat/completions", { method:"POST", headers:{"content-type":"application/json"}, body:JSON.stringify({model:"test-local",messages:[{role:"user",content:"fixture"}]}) }).then(r=>r.text()).catch(()=>"closed");
  try {
    await started;
    await new Promise(resolve => setTimeout(resolve, 800));
    assert.equal(existsSync(join(dir,"proxy-writer.lock")), false, "API expiry must close the listener and release the lock without a CLI supervisor");
    await assert.rejects(fetch(proxy.origin+"/healthz"));
    const receipt=JSON.parse(readFileSync(join(dir,"model-proxy-receipt.json"),"utf8"));
    assert.equal(receipt.active,false); assert.equal(receipt.failed,1); assert.equal(receipt.completed,0);
    assert.equal(receipt.requests[0].state,"failed");
  } finally {
    await proxy.close(); await pending;
    await new Promise(resolve => { upstream.close(resolve); upstream.closeAllConnections(); });
    rmSync(dir,{recursive:true,force:true});
  }
});
