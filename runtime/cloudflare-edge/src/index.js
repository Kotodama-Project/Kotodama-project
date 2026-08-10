const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
  "content-security-policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
  "referrer-policy": "no-referrer",
  "x-content-type-options": "nosniff",
};

const ALLOWED_STAGES = new Set(["production-disabled", "preview-candidate"]);
const PUBLIC_BETA = "NO_GO_UNPUBLISHED";

function json(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

function deny(code, status) {
  return json({
    ok: false,
    error: code,
    content: "omitted",
    promotion: false,
    current_truth_mutation: false,
    public_beta: PUBLIC_BETA,
  }, status);
}

function runtimeStage(env) {
  if (
    !env
    || !ALLOWED_STAGES.has(env.DEPLOYMENT_STAGE)
    || env.PUBLIC_BETA_STATUS !== PUBLIC_BETA
  ) return null;
  return env.DEPLOYMENT_STAGE;
}

async function evaluate(request, env) {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return deny("method_not_allowed", 405);
  }

  const stage = runtimeStage(env);
  if (!stage) return deny("runtime_configuration_denied", 503);

  const { pathname } = new URL(request.url);
  const body = pathname === "/healthz"
    ? {
        ok: true,
        surface: "cloudflare-edge-candidate",
        public_beta: PUBLIC_BETA,
      }
    : pathname === "/version"
      ? { ok: true, stage, public_beta: PUBLIC_BETA }
      : null;

  if (body === null) return deny("not_found", 404);
  return request.method === "HEAD"
    ? new Response(null, { status: 200, headers: JSON_HEADERS })
    : json(body);
}

export default { fetch: (request, env) => evaluate(request, env) };
