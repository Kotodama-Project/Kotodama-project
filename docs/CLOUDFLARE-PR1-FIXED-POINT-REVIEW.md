# Cloudflare PR #1 Fixed-Point Review

Review date: 2026-08-10

## Review target and claim boundary

This review fixes its public comparison point before discussing a successor:

- repository: `dj-thank/Kotodama-project`;
- pull request: [#1](https://github.com/dj-thank/Kotodama-project/pull/1);
- base and merge base: `be71f424689648b3ab1b1db15adbaddea374586b`;
- reviewed PR head: `e1e39bee29cde36a88e8b31136c603534ebf5b6f`;
- reviewed PR tree: `d93c2cfb07a0bb4f912585a83f82d64536815b9a`.

The public PR remained a draft with no submitted review when this review was
performed. Its body and [CFOS-11](https://github.com/dj-thank/Kotodama-project/issues/11)
still named the older `23d0721...` candidate, so they were not exact-head
evidence for the reviewed object.

The result below is a local code-review fix candidate. It is not an independent
Human approval, a provider deployment, a public-PR update, a merge decision, or
Public Beta GO.

## Primary sources and acceptance contract

- [CFOS-03](https://github.com/dj-thank/Kotodama-project/issues/4) limits the
  first manual preview to the content-free `/healthz` and `/version` surface.
- [CFOS-07](https://github.com/dj-thank/Kotodama-project/issues/9) requires a
  candidate-bound Human Decision before private or personal request bodies can
  transit Cloudflare.
- [CFOS-02A](https://github.com/dj-thank/Kotodama-project/issues/10) requires a
  protected deployment identity, runner, and receipt chain before preview
  upload; the issue does not itself authorize a workflow run.
- Cloudflare documents that a Wrangler
  [`[build].command`](https://developers.cloudflare.com/workers/wrangler/custom-builds/)
  runs during `wrangler versions upload`, and that
  [`.wrangler/deploy/config.json`](https://developers.cloudflare.com/workers/wrangler/configuration/)
  can select a different deploy configuration.
- The official
  [`wrangler versions upload` command reference](https://developers.cloudflare.com/workers/wrangler/commands/workers/)
  documents `--no-bundle`, `--strict`, and the experimental provisioning and
  automatic resource-creation controls used by the successor command.
- The pinned
  [`wrangler-action`](https://github.com/cloudflare/wrangler-action/tree/9acf94ace14e7dc412b076f2c5c20b8ce93c79cd)
  runs commands from `workingDirectory`, can infer a package manager from local
  lockfiles, and installs the requested Wrangler version with that manager.

## Standards review

### S1 — P1 — trusted-validator escape paths

The reviewed head accepted marker-preserving edits instead of binding exact
deployable bytes. It also did not close candidate-controlled Wrangler config
redirects, custom build commands, extra package-manager control files, or the
full provider-binding surface. A candidate could therefore pass the trusted
validation job while causing the later secret-bearing upload job to interpret
different deploy instructions.

Local successor disposition: fixed. The validator now performs bounded strict
UTF-8 reads, rejects symlinks and an open-ended deploy layout, binds canonical
SHA-256 digests for all deploy inputs, rejects alternate Wrangler/build/package
control files, and validates an exact closed configuration. The upload command
also names `wrangler.jsonc`, fixes the package manager to npm, disables bundling
and automatic provisioning, and uses strict mode.

### S2 — P1 — stale fixed-point evidence

The public PR body and CFOS-11 issue name an older candidate even though the PR
head has advanced. Checks attached to the current head do not repair prose that
claims another exact object. Review, approval, and any future deployment receipt
must bind the same successor commit and tree.

Disposition: unresolved externally. This local branch does not edit the public
PR or issue.

## Specification review

### P1 — P1 — premature Voice and Context Gateway surface

The reviewed head added `/voice/review`, request-body parsing, Cloudflare Access
service-token handling, and Context Gateway subrequests. That exceeded the
health/version-only acceptance contract in CFOS-03 and preceded the Human
Decision required by CFOS-07.

Local successor disposition: fixed. The Worker now supports only `GET|HEAD`
for `/healthz` and `/version`; other paths fail with `404`, mutation methods
fail with `405`, and widened or missing public status bindings fail with `503`.
There is no body handling, origin fetch, Voice route, secret binding, or Context
Gateway call.

### P2 — P1 — provider execution gate remains open

CFOS-02A is still an external prerequisite. A locally hardened workflow cannot
prove Environment review policy, token scope, runner identity, trusted clock,
nonce/receipt persistence, provider readback, or rollback.

Disposition: intentionally unresolved. No workflow dispatch, secret access,
preview upload, provider mutation, or production route change was performed.

## Local verification

The following checks were run against the local successor working tree:

- 19 focused Python tests for the trusted validator and CI contract: PASS;
- direct trusted-validator execution: PASS;
- 5 Node Worker contract tests with exact Node `v24.14.0`: PASS; the official
  Windows x64 archive SHA-256
  `313fa40c0d7b18575821de8cb17483031fe07d95de5994f6f435f3b345f85c66`
  matched Node's published `SHASUMS256.txt` before execution;
- complete Python suite, 584 tests: PASS with one Windows symlink-privilege
  skip;
- exact Wrangler `4.120.0` npm tarball: recorded SHA-512 integrity and SHA-1
  shasum both matched; static CLI inspection confirmed the config, no-bundle,
  strict, provisioning, and auto-create options used by the workflow;
- Python compilation and `git diff --check`: PASS.

The exact local Node result matches the hosted runtime pin but does not replace
an exact-head hosted check. The first full-suite run exposed a stale closed
`.gitattributes` expectation; the allowed set was updated without weakening the
exact-set check, and the complete suite then passed. The final handoff must bind
these results to the exact successor commit and tree before this local candidate
is proposed for the public PR.

## Remaining gates

1. Bind the review request, checks, and PR prose to the exact successor commit
   and tree.
2. Obtain a genuinely independent Human review; this Codex review does not
   satisfy that gate.
3. Run exact-head hosted checks, including the repository's pinned Node 24 and
   Python 3.12 lanes.
4. Complete CFOS-02A before any provider upload and CFOS-07 before restoring any
   body-bearing Voice or Context Gateway path.
5. Preserve `NO_GO_UNPUBLISHED` until provider, public-route, rollback, privacy,
   and Human GO evidence all exist for the same fixed point.
