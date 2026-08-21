# Cloudflare edge and official Cloudflare OS

Kotodama adopts two related but distinct Cloudflare planes.

| Plane | Adopted role | Current public evidence | Not proven |
|---|---|---|---|
| Cloudflare edge | Bounded public ingress and application delivery through Workers and Access | content-free `/healthz` and `/version` candidate, exact Wrangler binding, manual preview-upload workflow candidate | upload, route, origin, production traffic, provider log retention, independent review, Public Beta |
| Official Cloudflare OS | AI workspace, sandboxed Gadget application, Blueprint, and capability-based Gatekeeper foundation | exact official starter/core source pin, metadata-only Gatekeeper projections, a content-free local runtime receipt with 1060 passing tests, and a workspace-only security-overlay preflight with an observed generated-lock byte binding | frozen install and zero-high remediation proof, independent drift review, provider entitlement, Dynamic Worker provider execution, private Context, backup/restore, production |
| Proxmox | Protected local compute, storage, search and service runtime | lifecycle/profile documentation and historical local evidence outside this public candidate | current live topology and deployment parity in this repository |
| BecomeOne / Human Intent | Decision, Work Order, Promotion and Current Truth authority | public Company governance contracts | canonical adoption or live authority execution |
| Context Gateway | Default-deny Authorized Corpus query authority | architecture and adapter contract | real provider-to-local search E2E |

## Selected upstream baseline

The machine-readable pin is
[`runtime/cloudflare-os/upstream-pin.json`](../runtime/cloudflare-os/upstream-pin.json).
It selects the official starter at one exact commit and its own exact core
gitlink. A newer core head was observed separately; it is drift to review, not
an ambient upgrade. Both upstream repositories were observed with Apache-2.0
licensing, but this source-only pass does not prove the eventual installed
dependency tree or its integrity.

The official starter requires Workers, KV, R2, Browser Rendering and Dynamic
Worker Loaders. Dynamic Workers require Workers Paid. Therefore the existing
content-free edge preview and an official Cloudflare OS provider evaluation are
separate cost and authority gates. Adoption does not silently authorize paid
plan activation, provider deployment or private-data transit.

## Gatekeeper mapping

The local adapter accepts a closed, content-free metadata envelope:

```text
Gatekeeper observation  -> Source Evidence Candidate
submitted/simulated     -> Change Candidate
rejected action         -> Decision Evidence Candidate
applied action          -> Verification Receipt Candidate
```

An applied event must bind the exact candidate, Work Order, Capability Grant,
Human Decision and external action receipt. Even then, the adapter keeps
execution authorization, Promotion and Current Truth mutation false. Protected
Context metadata additionally requires admission and corpus digests. Private
result bodies are rejected. The projection preserves the closed `data_class`
enum so independent projection validation can reject public metadata carrying
protected Context bindings and protected metadata missing those bindings.

The adapter is stateless. Request digests make event binding visible, but a
durable replay cache, trusted clock, production Gatekeeper parity and independent
observer are later gates.

## First runtime evaluation result

The first local evaluation is complete and recorded in
[Official Cloudflare OS local runtime evaluation](CLOUDFLARE-OS-LOCAL-RUNTIME-EVALUATION.md).
It used frozen lockfiles, ignored lifecycle scripts, scrubbed credentials, read
no response bodies, bound runtime to `LOOPBACK_ONLY`, and cleaned up all observed
evaluation processes and listeners. The accepted matrix passed 1060 tests with
7 explicit skips and covered all 26 workspace package projects.

The following gates remain before provider evaluation:

1. independently review the starter-to-core drift and license/dependency policy;
2. remediate or explicitly re-pin the open high `nanoid` advisory;
3. make telemetry and error-report retention default-deny and prove readback;
4. independently verify the exact package-manager archive attestation signature;
5. set an exact paid-plan budget, quota, billing owner and automatic stop;
6. keep data public/synthetic/content-free and produce provider readback,
   rollback, and deletion evidence under a separate Work Order.

## High-advisory remediation preflight

[`runtime/cloudflare-os/security-overlay.json`](../runtime/cloudflare-os/security-overlay.json)
binds the vulnerable production graph to the pinned core Git tree and two exact
Git blobs. It applies two parent-scoped root overrides: `nanoid` 3.3.18 for
`GHSA-2v37-7h3g-55p8`, and `@puppeteer/browsers` 3.0.4 under
`@cloudflare/puppeteer` for `GHSA-jmr9-qjv8-65gv`. The latter advisory has no
patched direct `extract-zip` release, so the candidate does not invent the
non-existent 2.0.2 suggested by one audit view; browsers 3.0.4 replaces the
archive path with integrity-bound `modern-tar` 0.7.7. Exact `pnpm@11.9.0`
generated a 268,881-byte, 8,040-line LF lock with five nanoid target markers,
the bound browser/archive markers, and no vulnerable nanoid or extract-zip
markers. The transformer itself still writes workspace bytes only and never
synthesizes a lockfile. Byte equivalence alone does not prove package-manager
provenance. The contract refuses CRLF, already-applied overlays, marker or
integrity drift, global overrides, ambient latest, manual-lock acceptance, or
any provider/Public GO overclaim.

Validate the public contract:

```powershell
python -m unittest tests.test_cloudflare_os_security_overlay -v
python tools/validate_cloudflare_os_security_candidate.py
```

The first command covers the workspace-only transform, observed-lock byte
verification, rejection of the old four-marker manual prediction, and other
negative cases. The second validates the public spec only. A local reviewer may
additionally pass a trusted official core checkout with `--core-repo`; the
validator reads the pinned objects with Git and never reads authoritative bytes
from the dirty worktree. To reverify materialization instead of only validating
the recorded receipt, pass both `--generated-workspace` and `--generated-lock`;
omitting either fails closed, while omitting both reports the materialization as
recorded but not reverified by that run.

This is `LOCAL_MATERIALIZATION_VERIFIED_NOT_DEPLOYED`. The exact pnpm archive
matched its recorded SHA-1/SHA-512 values and reported 11.9.0; regeneration,
scripts-disabled frozen install, zero-High production audit, all 26 workspace
builds, and 279 focused Workshop backend tests passed (4 provider-dependent
integration tests skipped). No upstream source, provider deployment, or
production dependency has been changed. Independent review and provider
deployment/remediation remain closed gates.

Local Wrangler/workerd is not supported Proxmox production-hosting evidence.
No provider deployment, private Context transfer, production Promotion or Public
Beta GO is included in this revision. `NO_GO_UNPUBLISHED` remains.
