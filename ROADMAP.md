# Roadmap to Public Beta

## Published now

- [x] Public repository and project direction
- [x] Explicit incomplete-preview status
- [x] Privacy and publication boundary
- [x] Minimal Company manifest / Block / MOC schemas
- [x] Dependency-free validator and negative tests
- [x] Source-to-Promotion-Candidate governance starter and walkthrough
- [x] Machine-verified flow inputs, Block sequence, dataflow, and MOC binding
- [x] Nine governed record contracts with exact Block-output coverage
- [x] Capability Grant, Change Execution, and human Promotion Decision seams
- [x] Navigation-only Company, Public Release Review, and Incident / Recovery MOCs
- [x] Machine-verified secondary MOC ordered-subsequence contract
- [x] Dependency-free starter initializer with ID/MOC rebinding and overwrite refusal
- [x] Machine-readable customization checklist with review/evidence separation
- [x] Candidate-bound review bundle with exact SHA-256 and byte-size bindings
- [x] Saved-bundle verifier with metadata, digest, and byte-drift detection
- [x] Candidate-bound review workflow with separate Human Decision and Promotion
- [x] Dynamic saved-bundle to Review Request contract with Pack-specific counts
- [x] Dynamic Review Response contract bound to the saved request
- [x] Dynamic Decision Handoff contract bound to the saved review chain
- [x] Public Template Guide, Starter Walkthrough, Status, and Roadmap current-state sync
- [x] Company Pack Catalog, Guided Next Steps, and Schema / Validator / Test Matrix entry navigation
- [x] Fourteen-entrypoint Company Pack CLI Reference with fixed cross-shell help boundaries
- [x] Standard-library-only one-command review-chain smoke with temporary cleanup and closed report
- [x] Clone-to-result five-minute tour with cross-shell commands, report interpretation, and bounded next choices
- [x] Company OS reader/story map from Vision through current reality to safe first use (in docs/OVERVIEW.md since 2026-09-14)
- [x] Cloudflare edge candidate merged via #18, with exact Wrangler supply-chain binding and a manual-only preview upload guard bound to the current `main` tip
- [x] Official Cloudflare OS source pin (merged via #18) and content-free Gatekeeper-to-Kotodama adapter contract
- [x] Content-free official Cloudflare OS local runtime receipt with exact integrity, 1060 passing tests, loopback readback, and cleanup evidence
- [x] Repository governance baseline (MIT root license, reproducible hash-locked CI, tracked-secret hygiene, session / conversation ledger contract) merged via #73 and #18 on 2026-09-12
- [x] Task-bound Company Pack execution and the persistent local review gateway merged via #75 and #76 on 2026-09-12
- [x] Discord runtime candidate `runtime/discord-template` (local ASR, continuous Live conversation, bounded Task worker, selectable voice-channel modes) merged via #79, #80, and #81 on 2026-09-13; real-microphone acceptance remains open
- [x] [Owner-confirmed Company AGI direction](docs/OWNER-INTENT-COMPANY-AGI.md) with README/STATUS/ROADMAP projections
- [x] Tag `v0.1.0-preview` and a tag-triggered release workflow that drafts a pre-release with the smoke report, source archive, and provenance attestation (#97)
- [x] Discord runtime review hardening merged via #99 on 2026-09-23: bounded analysis concurrency and limits, Linux Docker-isolated verification for write Tasks, restart states that never re-run work automatically, and fixes for #91, #92, and #93
- [x] [Luna Task swarm](docs/LUNA-TASK-SWARM.md) merged via #100 on 2026-09-23: owner-bound plans, budgets, acknowledged peer messages, and an independent verifier, exercised offline on Linux and Windows; live Codex/Luna acceptance remains open
- [x] Discord agent channels and an immediate start notice merged via #101 on 2026-09-23

## Current Cloudflare candidate

The merged Cloudflare candidate separates Cloudflare edge from the official
Cloudflare OS project. The edge side remains a content-free Worker candidate;
no preview version has been uploaded. The Cloudflare OS side pins the exact
official starter, the core gitlink used by that starter, and the separately
observed current core head. Because the gitlink and current head differ, an
independent drift review is required before re-pinning.

The local adapter covers observation, protected observation, submitted,
simulated, rejected, and applied Gatekeeper events. It emits Kotodama candidate
records only and cannot authorize execution, Promotion, or Current Truth.

The bounded local runtime evaluation is now complete: exact lock/toolchain
integrity is recorded, 1060 tests pass with 7 explicit skips, all 26 workspace
package projects have build coverage, three stable headers-only HTTP 200
readbacks were observed in `LOOPBACK_ONLY` mode, and cleanup left no evaluation
process or listener. This is local evidence only; provider deployment remains
`not_deployed`.

The next dependency-ordered gates are independent review of the 99-file drift,
remediation or explicit re-pin of the high `nanoid` advisory, default-deny
observability retention/readback, package-manager attestation verification,
paid-plan budget and entitlement, and provider readback/rollback/deletion.
Private Context, backup/restore, production behavior, Discord publication,
Promotion, Current Truth, and Final Human GO remain open.
`NO_GO_UNPUBLISHED` remains unchanged.

## Owner-confirmed Company AGI direction

The [Owner-confirmed direction](docs/OWNER-INTENT-COMPANY-AGI.md) is the canonical product-direction source for Company AGI, bounded autonomy,
Voice Requirements Agent, per-Invocation authority, and one Kotodama product /
Company SSOT. Correction themes: BecomeOne is the migration donor/control plane;
OKF v0.2 is central for governed curated knowledge, not sole Company truth; and
Voice raw/derived evidence plus adaptive GrillU remain explicit. Luna-first
routing, a provider-neutral archive interface with a private ZFS v1 target, and a synthetic ZFS test dataset with authenticated restore and 8/8 file-hash restore readback are distinct.
Production dataset/key custody/retention/deletion/replication binding remain pending. Reversible review/revert delegation
and the bounded Goal Completion Loop remain product requirements. This
documentation milestone does not implement the runtime: Voice-to-Requirement,
Agent Swarm, Context/encoder, provider, storage, and Promotion remain separate
work. The runtime remains unimplemented and Public Beta remains
`NO_GO_UNPUBLISHED`. The public bytes are a redacted owner-directed direction
candidate, not signed or independently verifiable governance approval,
rightsholder proof, canonical adoption, launch decision, or Final Human GO, and
no receipt is fabricated. The root license is MIT (merged via #18 on 2026-09-12); Issue #25 remains open
for the accountable rightsholder, contributor, provenance, and NOTICE record.

## Documentation revision history

The R91 to R179 documentation revision narrative that previously lived here is
preserved in [docs/HISTORY.md](docs/HISTORY.md). It is historical and does not
describe the current state of `main`. Open work is tracked on GitHub
[milestones](https://github.com/Kotodama-Project/Kotodama-project/milestones).

## Candidate contracts on `main`

- [x] [Read-only Source binding candidate](docs/SOURCE-BINDING-VERIFIER-CANDIDATE.md) with strict bounded parsing, stable terminal reread, non-reflective refusal, and non-emitted R30 projection digest. This line describes repository contents, not publication, protected verification, or Public Beta GO.
- [x] [Protected Source binding receipt candidate](docs/PROTECTED-SOURCE-BINDING-RECEIPT-CANDIDATE.md) schema with private snapshot, clock, locator, evidence, replay, retention/deletion, and detached-attestation roles. This is an unpopulated schema contract, not protected execution or a verified receipt.
- [x] [Protected execution request / handoff candidate](docs/PROTECTED-EXECUTION-REQUEST-HANDOFF-CANDIDATE.md) with opaque runner/input refs, bounded evaluation window, fixed stop/rollback shape, expected receipt, and independent-verification handoff. This is schema-only; no execution is requested or accepted.

## Runtime profiles still requiring live evidence

- [x] Executable Compose data-plane candidate manifest (not a live receipt)
- [ ] Protected, authenticated, fresh digest-pinned image staging and clean-install/migration receipt (`PB-G6`)
- [ ] Exact Proxmox guest/service candidate and segmented deployment receipt (`PB-G6`)
- [ ] Candidate-bound restart, rollback, and isolated restore receipts (`PB-G6`)
- [ ] External checkpoint-head canonical authority, old-key revocation, adopted segmentation policy, and scope-matched tested restore execution/continuity (`PB-G7`)
- [ ] PostgreSQL Company DB and Evidence Store setup/restore E2E (`PB-G6`)

## Required before opening access

Gate IDs are defined in [docs/OVERVIEW.md](docs/OVERVIEW.md#public-beta-完成としてまだ証明されていないもの).

- [ ] Fresh candidate-bound Voice cutover, rollback, and exact post-deployment byte/revision readback proving deployed/candidate parity (`PB-G4`)
- [ ] Real 15-minute rotation, transcription post, and deletion evidence (`PB-G2`, `PB-G3`)
- [ ] Always-on listener continuity and forced-disconnect/rejoin E2E (`PB-G1`)
- [ ] Speaker attribution and Voice-to-Verified-Handoff E2E (`PB-G5`)
- [ ] Separate-person verification and three-persona E2E (`PB-G5`, `PB-G7`)
- [ ] Protected reconciliation and independent verification receipts (`PB-G7`)
- [ ] Public Discord invite and publicly reachable Voice Bot readback (`PB-G8`)
- [ ] Candidate-bound Final Human GO (`PB-G9`)
- [ ] Voice / Discord mode acceptance in one real conversation (`PB-G10`): a social-only session ends without a new Task, source-cited catch-up works, bounded work runs on existing permission, corrections flow back to Knowledge / Task / agent context, and native UI, free text, and voice corrections share one history ([Product direction](docs/PRODUCT-DIRECTION.md))

この一覧は進捗を透明にするためのものです。チェック項目は、対応する検証 receipt が揃うまで完了扱いにしません。
