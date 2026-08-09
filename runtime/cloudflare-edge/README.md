# Cloudflare Edge Profile Candidate

This directory is a secret-free deployment candidate for the Cloudflare-facing
edge of Kotodama. It is not the Kotodama data plane and it does not replace the
Proxmox segmented profile.

## Boundary

- Cloudflare: public edge routing, Access JWT verification, a bounded Voice
  review projection, and deployment metadata.
- Proxmox: search runtime, Context Gateway, databases, Evidence Store, n8n,
  OpenClaw, and private administration.
- Tailscale or an equivalent private path: operator access while the
  Cloudflare Access/Tunnel candidate is not independently verified.

The Worker exposes `/healthz`, `/version`, `GET /voice/review`, and
`POST /voice/review/{safe-document-id}`. Every route requires both the exact
bound preview hostname and a valid RS256 Cloudflare Access JWT with an exact
issuer and audience. Missing, malformed, forged, expired, not-yet-valid, or
wrong-audience JWTs fail closed. A different host, including a base
`workers.dev` or version-origin hostname, is denied before any upstream fetch.

The Voice route can call only the configured HTTPS Context Gateway origin:

- `GET /voice/review?q=...` maps to `GET /v1/voice/handoffs?q=...`;
- `POST /voice/review/{id}` maps to
  `POST /v1/voice/handoffs/{id}/review`;
- review actions are limited to `accept`, `edit`, and `reject`;
- the Gateway response is reconstructed through an allowlist;
- raw audio, transcript, credential, source body, and private corpus keys are
  rejected, not silently forwarded;
- evidence is digest-URN only and authority remains `candidate_only`.

The Worker has no search, storage, AI, Voice, ASR, database, or canonical-state
binding. Context Gateway remains mandatory; direct search access is absent.
Every other path fails closed.

## Runtime bindings

The preview requires the following values to be supplied through the protected
deployment environment. Values must not be committed or printed:

- `ACCESS_ISSUER`: exact HTTPS Cloudflare Access issuer origin;
- `ACCESS_AUD`: exact Access application audience;
- `PREVIEW_HOST`: exact Access-protected aliased preview hostname, without a
  scheme or path;
- `CONTEXT_GATEWAY_ORIGIN`: exact HTTPS Context Gateway origin;
- `CONTEXT_GATEWAY_CLIENT_ID`: Access service-token client identifier;
- `CONTEXT_GATEWAY_CLIENT_SECRET`: Access service-token secret.

If any value is absent or malformed, all routes return `503`; a host mismatch
returns `403`, and an invalid Access assertion returns `401`. Uploading code
does not by itself configure Access, Tunnel, the Context Gateway, or these
runtime values.

## Candidate checks

```powershell
python tools\validate_cloudflare_edge_candidate.py
python -m unittest tests.test_cloudflare_edge_candidate -v
C:\path\to\node.exe --test tests\node\test_cloudflare_voice_review.mjs
```

```bash
python3 tools/validate_cloudflare_edge_candidate.py
python3 -m unittest tests.test_cloudflare_edge_candidate -v
node --test tests/node/test_cloudflare_voice_review.mjs
```

The GitHub workflow first checks a lowercase 40-hex commit and requires it to
equal the current remote tip of the allowed `codex/cloudflare-os-foundation`
branch; a historical ancestor is refused. Validator code is checked out from
the exact `github.sha` dispatch revision on `main`, rather than re-resolving a
mutable default-branch name during the run. Candidate Python or tests are not
executed in that unprivileged validation job. After Environment approval, the
upload job repeats the exact remote-tip check before Wrangler runs, closing
branch-advance drift during the approval wait. It can upload a preview version
with the deterministic `voice-review` preview alias only after a manual
dispatch from `main` and approval by the
`cloudflare-preview` GitHub Environment. It does not deploy a production route.

The trusted validator checks the default configuration and every named
environment for forbidden provider/data bindings. The default and preview
environments disable the base `workers.dev` route; only preview URLs are
explicitly enabled for the preview environment. A preview-only R2, KV, AI,
service, route, or similar binding is refused, and an environment-specific
observability/logging override must remain disabled until provider retention
has separate evidence. It also requires the Access verification, exact two
bounded fetch sites (Access JWKS and Context Gateway), Voice projection denial,
and no direct search/provider endpoint markers.

Before any run, configure that Environment with required reviewers, prevent
self-review where available, restrict deployment branches to `main`, and add
`CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` as Environment secrets.
Those protections and secrets are not configured or verified by this public
candidate. Values must never be committed.

Wrangler is fixed to `4.120.0`. Its npm integrity and SLSA subject are bound in
[`wrangler-integrity.json`](wrangler-integrity.json). Observability and logs are
disabled by default until provider retention and content-free readback have a
separate receipt.

Before running the workflow, bind an exact commit to a Work Order and verify:

1. the API token is limited to the intended Cloudflare account and Worker;
2. the account remains within the approved plan and cost ceiling;
3. the preview URL is protected by Cloudflare Access before private data is
   introduced;
4. logs contain no request body, authorization header, personal identifier, or
   private source content;
5. rollback is the previous known-good Worker version;
6. Public Beta remains `NO_GO_UNPUBLISHED`.

## Non-claims

The files here do not prove Cloudflare account ownership, Access/Tunnel/DNS
configuration, runtime secret binding, preview deployment, production
deployment, Context Gateway origin reachability, real Voice data, provider E2E,
rollback, Promotion, Current Truth, or Public Beta GO.
