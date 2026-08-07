const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
  "x-content-type-options": "nosniff",
};

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: JSON_HEADERS,
  });
}

export default {
  async fetch(request, env) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return json({ ok: false, error: "method_not_allowed" }, 405);
    }

    const { pathname } = new URL(request.url);
    const body = pathname === "/healthz"
      ? { ok: true, surface: "cloudflare-edge-candidate" }
      : pathname === "/version"
        ? {
            ok: true,
            stage: env.DEPLOYMENT_STAGE,
            public_beta: env.PUBLIC_BETA_STATUS,
          }
        : null;

    if (body === null) {
      return json({ ok: false, error: "not_found" }, 404);
    }

    if (request.method === "HEAD") {
      return new Response(null, { status: 200, headers: JSON_HEADERS });
    }
    return json(body);
  },
};
