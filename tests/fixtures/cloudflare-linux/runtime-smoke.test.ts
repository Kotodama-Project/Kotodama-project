// Copied into the fixed public core's integration-test directory by our runner.
// The real backend and built frontend run locally; no account or provider call.
import { expect, it } from "vitest";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { startHarness } from "../src/harness.js";
import { NetworkInterceptor } from "../src/network-interceptor.js";

it("serves three loopback HEAD responses and closes the owned listener", async () => {
  const outbound = new NetworkInterceptor();
  outbound.install();
  let harness;
  let closed = false;
  try {
    harness = await startHarness({
      gatekeepers: [],
      patchWorkshop(config) {
        config.assets = {
          directory: resolve(fileURLToPath(new URL("../../workshop-frontend/dist", import.meta.url))),
          not_found_handling: "single-page-application",
          run_worker_first: ["/api", "/api/*"],
        };
      },
    });
    expect(["127.0.0.1", "[::1]", "localhost"]).toContain(harness.url.hostname);
    const statuses = [];
    for (let count = 0; count < 3; count++) {
      const response = await fetch(harness.url, { method: "HEAD", redirect: "error", signal: AbortSignal.timeout(5000) });
      statuses.push(response.status);
      expect(response.status).toBe(200);
      expect(response.headers.get("content-type")).toMatch(/^text\/html/);
      expect(await response.text()).toBe("");
      await new Promise(resolve => setTimeout(resolve, 250));
    }
    await harness.server.close();
    closed = true;
    await expect(fetch(harness.url, { method: "HEAD", signal: AbortSignal.timeout(3000) })).rejects.toThrow();
    expect(outbound.getUnmockedCalls()).toEqual([]);
    console.log(JSON.stringify({ kind: "kotodama/cloudflare-runtime-smoke/v1", statuses,
      response_body_bytes: 0, selected_listener_closed: true, worker_outbound_requests: 0,
      scope: "real-backend-and-built-frontend-no-gatekeepers-or-worker-loader", public_beta: "NO_GO_UNPUBLISHED" }));
  } finally {
    if (!closed) await harness?.server.close();
    outbound.uninstall();
  }
});
