# Cloudflare edge and official Cloudflare OS

Kotodama adopts two related but distinct Cloudflare planes.

| Plane | Adopted role | Current public evidence | Not proven |
|---|---|---|---|
| Cloudflare edge | Bounded public ingress and application delivery through Workers and Access | content-free `/healthz` and `/version` candidate, exact Wrangler binding, manual preview-upload workflow candidate | upload, route, origin, production traffic, provider log retention, independent review, Public Beta |
| Official Cloudflare OS | AI workspace, sandboxed Gadget application, Blueprint, and capability-based Gatekeeper foundation | exact official starter/core source pin plus metadata-only Gatekeeper projection tests | dependency integrity, installed runtime, provider entitlement, Dynamic Worker execution, private Context, backup/restore, production |
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
result bodies are rejected.

The adapter is stateless. Request digests make event binding visible, but a
durable replay cache, trusted clock, production Gatekeeper parity and independent
observer are later gates.

## First runtime evaluation gate

Before any dependency install or provider evaluation:

1. independently review the starter-to-core drift and license/dependency policy;
2. resolve package ranges to an exact lock/integrity set and bind the toolchain;
3. set an exact paid-plan budget, quota, billing owner and automatic stop;
4. keep data public/synthetic/content-free and telemetry disabled or content-free;
5. prove local build and negative tests without treating local Wrangler/workerd
   as supported Proxmox production hosting;
6. produce a candidate-bound receipt and separate Human promotion decision.

No provider deployment, private Context transfer, production Promotion or
Public Beta GO is included in this revision. `NO_GO_UNPUBLISHED` remains.
