# Cloudflare Edge Profile Candidate

This directory is a secret-free deployment candidate for the Cloudflare-facing
edge of Kotodama. It is not the Kotodama data plane and it does not replace the
Proxmox segmented profile.

## Boundary

- Cloudflare: public edge routing, a minimal health/status response, later
  Access/Tunnel policy enforcement, and deployment metadata.
- Proxmox: search runtime, Context Gateway, databases, Evidence Store, n8n,
  OpenClaw, and private administration.
- Tailscale or an equivalent private path: operator access while the
  Cloudflare Access/Tunnel candidate is not independently verified.

The Worker exposes only `/healthz` and `/version`. It has no origin binding,
storage binding, AI binding, route, custom domain, or secret. Every other path
fails closed with `404`.

## Candidate checks

```powershell
python tools\validate_cloudflare_edge_candidate.py
python -m unittest tests.test_cloudflare_edge_candidate -v
```

```bash
python3 tools/validate_cloudflare_edge_candidate.py
python3 -m unittest tests.test_cloudflare_edge_candidate -v
```

The GitHub workflow first checks a lowercase 40-hex commit and requires it to
equal the current remote tip of the allowed `codex/cloudflare-os-foundation`
branch; a historical ancestor is refused. Validator code is checked out from
trusted `main`. Candidate Python or tests are not executed in that unprivileged
validation job. After Environment approval, the upload job repeats the exact
remote-tip check before Wrangler runs, closing branch-advance drift during the
approval wait. It can upload a preview version only after a manual dispatch
from `main` and approval by the `cloudflare-preview` GitHub Environment. It
does not deploy a production route.

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
configuration, preview deployment, production deployment, origin reachability,
provider E2E, rollback, Promotion, Current Truth, or Public Beta GO.
