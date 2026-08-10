# Cloudflare Edge Profile Candidate

This directory is a secret-free deployment candidate for the Cloudflare-facing
edge of Kotodama. It is not the Kotodama data plane and it does not replace the
Proxmox segmented profile.

## Boundary

- Cloudflare: a content-free health/status preview and deployment metadata.
- Proxmox: Voice, search runtime, Context Gateway, databases, Evidence Store,
  n8n, OpenClaw, and private administration.
- Tailscale or an equivalent private path: operator access while the
  Cloudflare Access/Tunnel candidate is not independently verified.

The Worker exposes only `GET|HEAD /healthz` and `GET|HEAD /version`. It has no
origin fetch, request-body handling, storage, AI, Voice, ASR, Context Gateway,
route, custom domain, or secret binding. Every other path, including
`/voice/review`, fails closed with `404`; mutation methods fail with `405`.

This intentionally preserves the ordering in [CFOS-07](https://github.com/dj-thank/Kotodama-project/issues/9):
request-body processing, residency, subrequests, logs, retention, and rollback
need a candidate-bound Human Decision before Voice or other private/personal
content can transit Cloudflare. The protected deployment identity and receipt
chain in [CFOS-02A](https://github.com/dj-thank/Kotodama-project/issues/10) also
remains a prerequisite. Neither gate is implemented by this profile.

## Runtime bindings

Only two non-secret values are accepted from `wrangler.jsonc`:

- `DEPLOYMENT_STAGE`: `production-disabled` or `preview-candidate`;
- `PUBLIC_BETA_STATUS`: exactly `NO_GO_UNPUBLISHED`.

Missing or widened values return `503`, while the response itself continues to
report `NO_GO_UNPUBLISHED`. No Access token, Context Gateway credential, private
identifier, or content body is required or accepted by this Worker.

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

The Node test filename is retained as a regression boundary: it now proves the
former Voice route stays unavailable until its separate decisions and evidence
gates are complete.

The fixed-point findings, primary sources, and remaining external gates are
recorded in the
[Cloudflare PR #1 review](../../docs/CLOUDFLARE-PR1-FIXED-POINT-REVIEW.md).

The manual workflow checks a lowercase 40-hex commit and requires it to equal
the current remote tip of the allowed `codex/cloudflare-os-foundation` branch;
a historical ancestor is refused. Validator code is checked out from the exact
`github.sha` dispatch revision on `main`, rather than re-resolving a mutable
default-branch name. Candidate Python and tests are not executed in the
unprivileged validation job.

The trusted validator binds the exact deployable Worker, Wrangler config,
supply-chain metadata, and workflow bytes. It also requires a closed profile
layout, rejects candidate-controlled `.wrangler/deploy/config.json` redirects,
package-manager/build control files, unknown config keys, provider/data
bindings, routes, assets, custom builds, observability, and logs.

After Environment approval, the upload job repeats the exact remote-tip check.
Its fixed command uses the explicit `wrangler.jsonc`, `--no-bundle`, `--strict`,
the explicit npm package manager, and disables Wrangler's experimental
provisioning and auto-creation defaults.
It can upload only a preview version after a manual dispatch from `main` and
approval by the `cloudflare-preview` GitHub Environment. It does not deploy a
production route.

Before any run, configure that Environment with required reviewers, prevent
self-review where available, restrict deployment branches to `main`, and add
`CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` as Environment secrets.
Those protections and secrets are not configured or verified by this public
candidate. Values must never be committed.

Wrangler is fixed to `4.120.0`. Its npm integrity and SLSA subject are bound in
[`wrangler-integrity.json`](wrangler-integrity.json). The workflow does not yet
independently verify the downloaded archive against that record, so the supply
attestation/adoption gate remains open. Observability and logs stay disabled.

Before running the workflow, bind an exact commit to a Work Order and verify:

1. the protected deployment identity, required reviewer, self-review denial,
   deployment-branch restriction, trusted clock, nonce, and receipt sink;
2. the API token is limited to the intended Cloudflare account and Worker;
3. the account remains within the approved plan and cost ceiling;
4. the preview URL is protected by Cloudflare Access before private data is
   introduced;
5. logs contain no request body, authorization header, personal identifier, or
   private source content;
6. the exact rollback target and sanitized provider readback are bound;
7. Public Beta remains `NO_GO_UNPUBLISHED`.

## Non-claims

The files here do not prove Cloudflare account ownership, Environment policy,
token scope, Access/Tunnel/DNS configuration, preview deployment, production
deployment, provider E2E, rollback, Promotion, Current Truth, Final Human GO,
or Public Beta GO.
