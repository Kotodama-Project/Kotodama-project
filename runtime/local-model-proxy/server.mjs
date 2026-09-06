import { createServer, request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync, renameSync, existsSync, lstatSync, mkdirSync, rmdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { isIP } from "node:net";
import { strictJson } from "../local-review-gateway/server.mjs";

const MAX_BODY = 262144;
const MAX_OUTPUT = 8 * 1024 * 1024;
const hash = data => createHash("sha256").update(data).digest("hex");
const privateAddress = hostname => {
  const host = hostname.replace(/^\[|\]$/g, "");
  if (isIP(host) === 4) {
    const [a, b] = host.split(".").map(Number);
    return a === 127 || a === 10 || (a === 172 && b >= 16 && b <= 31)
      || (a === 192 && b === 168) || (a === 100 && b >= 64 && b <= 127);
  }
  return isIP(host) === 6 && (host === "::1" || /^f[cd]/i.test(host));
};
const json = (res, status, value) => {
  res.writeHead(status, { "content-type": "application/json", "cache-control": "no-store" });
  res.end(JSON.stringify(value));
};

/** A private loopback bridge for one operator-selected model. No model/admin discovery routes. */
export async function startLocalModelProxy(config) {
  const allowedKeys = ["upstream", "model", "port", "expiresAt", "maxRequests", "stateRoot"];
  if (!config || Object.keys(config).some(key => !allowedKeys.includes(key))
    || typeof config.model !== "string" || !/^[a-zA-Z0-9_.:/-]{1,128}$/.test(config.model)
    || !Number.isInteger(config.port) || config.port < 0 || config.port > 65535
    || !Number.isInteger(config.maxRequests) || config.maxRequests < 1 || config.maxRequests > 40
    || typeof config.expiresAt !== "string" || !Number.isFinite(Date.parse(config.expiresAt))
    || Date.parse(config.expiresAt) <= Date.now()
    || Date.parse(config.expiresAt) - Date.now() > 7200000) throw new Error("invalid_model_proxy_config");
  const upstream = new URL(config.upstream);
  // Pin localhost without consulting DNS. All other upstreams must be private IP
  // literals; mutable DNS names and link-local metadata services are not accepted.
  if (upstream.hostname === "localhost") upstream.hostname = "127.0.0.1";
  if (!["http:", "https:"].includes(upstream.protocol) || upstream.username || upstream.password
    || !privateAddress(upstream.hostname) || upstream.search || upstream.hash
    || !["/v1", "/v1/"].includes(upstream.pathname)) throw new Error("invalid_upstream");
  const stateRoot = resolve(config.stateRoot);
  if (!lstatSync(stateRoot).isDirectory() || lstatSync(stateRoot).isSymbolicLink()) throw new Error("invalid_state_root");
  const binding = hash(JSON.stringify([config.upstream, config.model, config.expiresAt, config.maxRequests]));
  const statePath = join(stateRoot, "model-proxy-receipt.json");
  let receipt = { binding, invocations: 0, completed: 0, failed: 0, active: false, requests: [] };
  if (existsSync(statePath)) {
    const info = lstatSync(statePath);
    if (!info.isFile() || info.isSymbolicLink() || info.size > 65536) throw new Error("invalid_receipt_file");
    receipt = strictJson(readFileSync(statePath));
    if (receipt.binding !== binding || !Number.isInteger(receipt.invocations) || receipt.invocations < 0
      || receipt.invocations > config.maxRequests || receipt.active || !Array.isArray(receipt.requests)
      || receipt.requests.length !== receipt.invocations) throw new Error("receipt_requires_reconciliation");
  }
  const save = () => {
    const temporary = statePath + ".tmp";
    writeFileSync(temporary, JSON.stringify(receipt, null, 2) + "\n", { mode: 0o600 });
    renameSync(temporary, statePath);
  };
  let closing = false;
  let activeUpstream;
  const server = createServer(async (req, res) => {
    if (closing || Date.now() >= Date.parse(config.expiresAt)) { req.resume(); return json(res, 503, { error: "model_bridge_offline" }); }
    if (req.method === "GET" && req.url === "/healthz") return json(res, 200, { state: receipt.active ? "busy" : "idle", invocations: receipt.invocations, expiresAt: config.expiresAt });
    if (req.method === "GET" && req.url === "/v1/models") return json(res, 200, { object: "list", data: [{ id: config.model, object: "model", owned_by: "operator-configured" }] });
    if (req.method !== "POST" || req.url !== "/v1/chat/completions") { req.resume(); return json(res, 404, { error: "route_unavailable" }); }
    if (receipt.active || receipt.invocations >= config.maxRequests) { req.resume(); return json(res, 429, { error: "model_busy_or_budget_reached" }); }
    if (!req.headers["content-type"]?.startsWith("application/json") || req.headers["content-encoding"]
      || Number(req.headers["content-length"] ?? 0) > MAX_BODY) { req.resume(); return json(res, 400, { error: "request_refused" }); }
    try {
      let size = 0; const chunks = [];
      for await (const chunk of req.iterator({ destroyOnReturn: false })) {
        size += chunk.length;
        if (size > MAX_BODY) { req.resume(); return json(res, 413, { error: "request_too_large" }); }
        chunks.push(chunk);
      }
      const bytes = Buffer.concat(chunks);
      const body = strictJson(bytes);
      const requestKeys = ["model", "messages", "stream", "stream_options", "max_tokens", "max_completion_tokens", "temperature", "top_p",
        "frequency_penalty", "presence_penalty", "seed", "tools", "tool_choice", "parallel_tool_calls", "reasoning_effort", "n", "store"];
      const outputCap = body.max_tokens ?? body.max_completion_tokens ?? 4096;
      if (Object.keys(body).some(key => !requestKeys.includes(key)) || (body.n !== undefined && body.n !== 1)
        || (body.store !== undefined && body.store !== false)
        || (body.max_tokens !== undefined && body.max_completion_tokens !== undefined)
        || body.model !== config.model || !Array.isArray(body.messages) || !body.messages.length
        || body.messages.length > 256 || !Number.isInteger(outputCap) || outputCap < 1 || outputCap > 4096
        || (body.stream !== undefined && typeof body.stream !== "boolean")) return json(res, 400, { error: "model_or_scope_refused" });
      // The body read is asynchronous: a second caller may have reserved the only slot meanwhile.
      if (receipt.active || receipt.invocations >= config.maxRequests || closing || Date.now() >= Date.parse(config.expiresAt)) return json(res, 429, { error: "model_busy_or_budget_reached" });
      if (body.max_tokens === undefined && body.max_completion_tokens === undefined) body.max_tokens = 4096;
      const forwarded = Buffer.from(JSON.stringify(body));
      const item = { inputSha256: hash(bytes), inputBytes: bytes.length, startedAt: new Date().toISOString(), state: "running", outputBytes: 0 };
      receipt.invocations++; receipt.active = true; receipt.requests.push(item); save();
      const client = upstream.protocol === "https:" ? httpsRequest : httpRequest;
      const url = new URL("chat/completions", upstream.href.replace(/\/?$/, "/"));
      activeUpstream = client(url, { method: "POST", headers: { "content-type": "application/json", "content-length": forwarded.length }, timeout: 180000 }, reply => {
        if (item.state !== "running") { reply.destroy(); return; }
        if (reply.statusCode !== 200) {
          reply.resume(); current.destroy(new Error("upstream_refused")); return;
        }
        const contentType = reply.headers["content-type"] ?? "";
        if (!(contentType.startsWith("application/json") || contentType.startsWith("text/event-stream"))) {
          reply.resume(); current.destroy(new Error("upstream_protocol_refused")); return;
        }
        res.writeHead(200, { "content-type": contentType, "cache-control": "no-store" });
        reply.on("data", chunk => {
          if (item.state !== "running") { reply.destroy(); return; }
          item.outputBytes += chunk.length;
          if (item.outputBytes > MAX_OUTPUT) { current.destroy(new Error("upstream_output_limit")); return; }
          if (!res.write(chunk)) reply.pause();
        });
        res.on("drain", () => reply.resume());
        reply.on("end", () => {
          if (item.state !== "running") return;
          item.state = "completed"; receipt.completed++; receipt.active = false; activeUpstream = undefined; save(); res.end();
        });
        reply.on("error", () => current.destroy(new Error("upstream_stream_failed")));
      });
      const current = activeUpstream;
      current.on("timeout", () => current.destroy(new Error("upstream_timeout")));
      current.on("error", () => {
        if (item.state !== "running") return;
        item.state = "failed"; receipt.failed++; receipt.active = false; activeUpstream = undefined; save();
        if (!res.headersSent) json(res, 502, { error: "local_model_unavailable" }); else res.destroy();
      });
      res.on("close", () => { if (!res.writableEnded && item.state === "running") current.destroy(new Error("caller_closed")); });
      current.end(forwarded);
    } catch {
      if (!res.headersSent) json(res, 400, { error: "request_refused" }); else res.destroy();
    }
  });
  server.maxConnections = 8;
  server.requestTimeout = 200000;
  server.headersTimeout = 10000;
  const lock = join(stateRoot, "proxy-writer.lock");
  mkdirSync(lock, { mode: 0o700 });
  try { await new Promise((accept, reject) => { server.once("error", reject); server.listen(config.port, "127.0.0.1", accept); }); }
  catch (error) { rmdirSync(lock); throw error; }
  save();
  let closePromise;
  let expiryTimer;
  let finishClosed;
  const closed = new Promise(accept => { finishClosed = accept; });
  const close = () => closePromise ??= (async () => {
    closing = true; clearTimeout(expiryTimer);
    let failure;
    try {
      // Persist cancellation before destroying sockets; later transport callbacks
      // must not turn an expired invocation into a successful completion.
      if (receipt.active) {
        const item = receipt.requests.at(-1);
        if (item?.state !== "running") throw new Error("model_request_termination_uncertain");
        item.state = "failed"; receipt.failed++; receipt.active = false; save();
      }
    } catch (error) { failure = error; }
    activeUpstream?.destroy(new Error("operator_stop")); activeUpstream = undefined;
    await new Promise(accept => { server.close(accept); server.closeAllConnections(); });
    if (!failure) {
      try { rmdirSync(lock); } catch (error) { failure = error; }
    }
    finishClosed({ error: Boolean(failure) });
    if (failure) throw failure;
  })();
  // The exported API owns its expiry, including active requests and writer lock.
  expiryTimer = setTimeout(() => { void close().catch(() => {}); }, Math.max(1, Date.parse(config.expiresAt) - Date.now()));
  return { origin: `http://127.0.0.1:${server.address().port}`, close, closed };
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const config = strictJson(readFileSync(process.argv[2]));
    const proxy = await startLocalModelProxy(config);
    const finish = () => { void proxy.close().catch(() => { process.exitCode = 1; }); };
    proxy.closed.then(result => { if (result.error) process.exitCode = 1; process.stdin.pause(); });
    process.stdout.write("Local model bridge ready.\n");
    for (const signal of ["SIGINT", "SIGTERM"]) process.once(signal, finish);
    process.stdin.on("data", bytes => { if (bytes.toString().trim() === "stop") finish(); });
  } catch { process.stderr.write("Local model bridge start refused.\n"); process.exitCode = 1; }
}
