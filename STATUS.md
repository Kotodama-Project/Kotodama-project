# Project Status

Updated: 2026-09-26

現在の公開面の状態表です。過去の documentation revision（R91〜R179）の履歴は
[docs/HISTORY.md](docs/HISTORY.md) に移し、この文書は現在地だけを示します。
GitHub の [milestones](https://github.com/Kotodama-Project/Kotodama-project/milestones) が
次に何が来るかの索引です。

Repository entries describe the source in this revision. They do not refresh
or promote the separately scoped runtime/deployment evidence below.

| Surface | Status |
|---|---|
| Public repository | Published preview |
| Product direction and roadmap | Public |
| Company governance starter | Published and locally validated |
| [Task-bound Company Pack execution](docs/COMPANY-PACK-TASK-EXECUTION.md) | Included local CREATE_COMPANY_PACK adapter; existing-record binding and checked output receipt; no Task-state write or agent dispatch |
| [Persistent local review gateway](runtime/local-review-gateway/README.md) | Included local review/restart candidate; actor-scoped projections; live Access/Tunnel and automatic Voice-to-Task connection remain unverified |
| [Discord runtime candidate](docs/DISCORD-RUNTIME.md) | Included in `main` via #79, #80, and #81 as `runtime/discord-template` (Node 24 template with local ASR, continuous Live conversation, and a bounded Task worker); the voice-channel modes (楽しく過ごす / 一緒に考える / 必要なときだけ仕事) are selectable there; #99 added bounded analysis concurrency and limits, Linux Docker-isolated verification for write Tasks (`write_file` / `develop` need Linux and `worker.verify` / `worker.verification`), and restart states that keep queued Tasks paused and running Tasks uncertain; #101 added agent channels (`discord.agentChannelIds`) that start a clear, complete request immediately and send the requester a DM with its title and ID; real-microphone continuity, a two-person 30-minute session, and reproduction in a separate setup remain unaccepted; no public Bot |
| [Session / conversation event ledger](docs/SESSION-CONVERSATION-LEDGER.md) | Published schema and validator; no runtime ingestion or Task connection |
| Agent swarm and autonomous delegation after a human GO | [Luna Task swarm](docs/LUNA-TASK-SWARM.md) (#67 with the #85 repairs) is on `main` as a bounded local runtime: owner-bound plans, budgets, acknowledged peer messages, and an independent verifier, exercised by the offline fixture on Linux and Windows in the required check; live Codex/Luna acceptance is not established. Contract candidates #34, #35, and #36 are not on `main`; they are to be re-landed with a mapping to this runtime ([#30](https://github.com/Kotodama-Project/Kotodama-project/issues/30)). The repository's own [improvement loop](docs/IMPROVEMENT-LOOP.md) defines how agents select, verify, merge, and revert one change at a time |
| Knowledge base (OKF) control plane | Candidate PRs #48, #61, and #59 are not on `main`. On 2026-09-24 the owner chose the #48 line as the canonical OKF bundle; the #49 line is to be connected to it ([#30](https://github.com/Kotodama-Project/Kotodama-project/issues/30)) |
| Slack / Teams / Salesforce adapters | Requirement records only (#70, #77); unconnected |
| Compose / Proxmox lifecycle contract | Published and locally validated |
| [Cloudflare edge preview candidate](runtime/cloudflare-edge/README.md) | Merged source candidate via #18; content-free validation only, no version upload or deployment established |
| [Official Cloudflare OS bounded runtime candidate](docs/CLOUDFLARE-OS-ADOPTION.md) | Merged source candidate via #18; exact source pin, six synthetic metadata projections, and content-free runtime receipt; no provider execution established |
| Compose minimum data-plane skeleton | Published candidate; offline config only |
| Resolved Compose candidate | Published credential-free configuration candidate |
| Local image availability preflight | Published read-only tool; saved verification is historical binding only |
| Clean-install / migration evidence candidate | Published unattested saved-binding contract; no live receipt |
| Protected one-use attestation evaluation | Published local candidate; atomic only within one bound SQLite store |
| [Signed nonce-store checkpoint](docs/ATTESTATION-NONCE-STORE-CHECKPOINT.md) | Published protected-local tool; point-in-time and immediate-parent only |
| [Recursive nonce-store checkpoint chain](docs/ATTESTATION-NONCE-STORE-CHECKPOINT-CHAIN.md) | Published protected-local candidate; supplied path/store equivalence only |
| [Checkpoint-head anchor / restore-drill evidence](docs/ATTESTATION-NONCE-STORE-HEAD-ANCHOR-AND-RESTORE-DRILL.md) | Published protected-local contract; signed reported binding only |
| [Checkpoint segment transition / key rotation](docs/ATTESTATION-NONCE-STORE-CHECKPOINT-SEGMENT-TRANSITION.md) | Published protected-local contract; one presented boundary only |
| [Segment transition candidate builder](docs/ATTESTATION-NONCE-STORE-CHECKPOINT-SEGMENT-TRANSITION-CREATION.md) | Published protected-local CLI; deterministic new-file creation only, unsigned and unverified |
| [Source binding verification candidate](docs/SOURCE-BINDING-VERIFIER-CANDIDATE.md) | Included in this revision as a read-only local candidate; stable postcheck and R30 projection digest only |
| [Protected Source binding receipt candidate](docs/PROTECTED-SOURCE-BINDING-RECEIPT-CANDIDATE.md) | Included as an unpopulated schema-only private receipt contract; no protected runner or verified receipt |
| [Protected execution request / handoff candidate](docs/PROTECTED-EXECUTION-REQUEST-HANDOFF-CANDIDATE.md) | Included as an opaque schema-only request shape; no execution accepted, executed, or private handoff |
| [Agent orchestration route-binding candidate](docs/AGENT-ORCHESTRATION-ROUTE-BINDING-CANDIDATE.md) | Included as an opaque schema and read-only preflight; no Codex transport, subagent spawn, provider / device / public send, approval, Promotion, or Current Truth |
| [Agent Swarm × Kotodama adoption candidate](docs/AGENT-SWARM-KOTODAMA-ADOPTION-CANDIDATE.md) | Included as an opaque bounded root / worker / verifier plan, schema, validator, and tests, mapped to the Luna Task swarm runtime; no dispatch, provider / device / public send, Promotion, or Current Truth |
| [Public migration ledger](docs/PUBLIC-MIGRATION-LEDGER.md) | Included from #35 as a hash-chained record schema, read-only verifier, optional trusted-head anchor, tests, and a synthetic fixture, with a note on how it differs from the Luna Task swarm records; the ledger file itself is not yet populated, and migration execution, private continuity, publication, approval, Promotion, and Current Truth remain unverified |
| [Public Preview Self-check](docs/PUBLIC-PREVIEW-SELF-CHECK.md) | Included as a read-only aggregate of starter validator, Catalog, customization, and false-claim checks; JSON by default, `--format markdown` for the human-first fixed summary |
| [Company Pack Catalog](docs/COMPANY-PACK-CATALOG.md) | Published `read-only/candidate-only` catalog; no runtime or approval; `NO_GO_UNPUBLISHED` |
| [Company Pack Guided Next Steps](docs/COMPANY-PACK-NEXT-STEPS.md) | Published deterministic planner/runbook; candidate-only guidance only; `NO_GO_UNPUBLISHED` |
| [Schema / Validator / Test Matrix](docs/SCHEMA-VALIDATOR-MATRIX.md) | Published schema, validator, test, and runbook map; local/static evidence only |
| [Compose candidate runbooks](docs/RESOLVED-COMPOSE-CANDIDATE.md) | Published read-only candidate guidance with PowerShell/POSIX parity; no live image or runtime receipt |
| [Image availability preflight](docs/IMAGE-AVAILABILITY-PREFLIGHT.md) | Published read-only historical-binding guidance with PowerShell/POSIX parity; current-host availability remains unverified |
| [Company Pack review bundle](docs/REVIEW-BUNDLE.md) | Published candidate-only exact-byte binding and drift verifier; no approval or Promotion |
| [Company Pack Review Request](docs/REVIEW-REQUEST.md) | Published read-only request candidate; counts follow the saved Pack report |
| [Company Pack Review Response](docs/REVIEW-RESPONSE.md) | Published read-only response candidate; saved-request binding and item counts are dynamic |
| [Company Pack Decision Handoff](docs/REVIEW-DECISION-HANDOFF.md) | Published read-only handoff candidate; decision and selected outcome remain null |
| [Template Guide / Starter Walkthrough](docs/TEMPLATE-GUIDE.md) | Published ideal/current usage docs; starter counts are examples, not universal Pack invariants |
| [Company Pack CLI Reference](docs/COMPANY-PACK-CLI-REFERENCE.md) | Fourteen public entrypoints with fixed help boundaries and one candidate-only Smoke command |
| One-command review-chain smoke | Published standard-library-only local smoke; exact thirteen steps in a temporary workspace, no retained artifacts or GO |
| [5-minute tour](docs/FIVE-MINUTE-TOUR.md) | Clone-to-result first-visit path; external-free local smoke and bounded next choices only |
| [Company OS story map](docs/OVERVIEW.md) | Vision-to-Try-it reader map and eight-surface ideal/current boundary, moved from README to docs/OVERVIEW.md on 2026-09-14; documentation only |
| [Owner-confirmed Company AGI direction](docs/OWNER-INTENT-COMPANY-AGI.md) | Redacted owner-directed direction candidate; not signed/independently verified governance approval or rightsholder proof; runtime remains unimplemented, `NO_GO_UNPUBLISHED` |
| Live Compose / Proxmox installation | Not verified |
| Public Beta access | Not open |
| Public Discord invite | Not published |
| Public Voice Bot | Inactive |
| Raw audio or transcript corpus | Not published |
| Final Human GO | Not completed |

## Latest Cloudflare candidate result

The official Cloudflare OS candidate pins the current official starter and the
core gitlink that starter actually uses. The separately observed current core
head differs by 99 files and remains a mandatory independent-review boundary.
The Gatekeeper validator passes six content-free synthetic projections and
keeps provider, execution, Promotion, Current Truth, and Public Beta authority
false.

The saved [local runtime evaluation](docs/CLOUDFLARE-OS-LOCAL-RUNTIME-EVALUATION.md)
adds exact dependency/toolchain integrity, 1060 passing tests with 7 explicit
skips, all 26 workspace package projects covered by build checks, three stable
headers-only HTTP 200 responses in `LOOPBACK_ONLY` mode, and zero remaining
evaluation processes/listeners. The result is `PASS_LOCAL_RUNTIME_WITH_GAPS`.

P0/P1/P2 is 0/6/2. The open P1 set includes the independent drift review, one
high `nanoid` advisory, Windows-only compatibility mitigation, unproven
observability retention/readback, provider E2E, and package-manager attestation
signature. Dynamic Workers, Workers Paid entitlement, KV, R2, Browser Rendering,
Access, provider logs, private Context, backup, restore, Discord integration,
and production remain unproven. The edge Worker was not uploaded or deployed.
`NO_GO_UNPUBLISHED` remains unchanged.

## Owner-confirmed Company AGI direction

The [Owner-confirmed direction](docs/OWNER-INTENT-COMPANY-AGI.md) records the
Company AGI target, bounded autonomy, Voice Requirements Agent, per-Invocation authority, causal ledger, and unresolved design decisions. README, STATUS, and
ROADMAP are projections of that source. Correction themes: one Kotodama product
with BecomeOne as migration donor/control plane; OKF v0.2 as the central
representation for governed curated knowledge, not sole Company truth; and
separate raw/derived Voice evidence with adaptive GrillU. Luna-first routing,
the provider-neutral archive interface/private ZFS v1 target, and a synthetic ZFS test dataset with authenticated restore and 8/8 file-hash restore readback are explicit.
Production dataset/key custody/retention/deletion/replication binding remain pending. Reversible delegation and the bounded Goal Completion
Improvement Loop remain requirements. This documentation does not activate
Voice, Agent Swarm, provider, deployment, Promotion, or Current Truth; runtime
remains unimplemented and Public Beta remains `NO_GO_UNPUBLISHED`. The public
bytes preserve the user's working direction as a redacted owner-directed
candidate, not a signed or independently verifiable governance approval,
rightsholder proof, canonical adoption, launch decision, or Final Human GO; no receipt is fabricated. The root license is MIT (merged via #18 on
2026-09-12; see [License scope](docs/LICENSE-SCOPE.md)); Issue #25 remains open
for the accountable rightsholder, contributor, provenance, and NOTICE record.

## Latest runtime result

最新の private Voice runtime cutover attempt は、read-only reconciliation 後に `BLOCKED_NO_EFFECT` と判定されました。候補ファイルの deploy は 0、外部 provider API の作用も 0 でした。

これは安全に停止したことの証拠であり、Voice runtime が公開稼働していることの証明ではありません。

## Documentation revision history

The R91 to R179 documentation revision narrative that previously lived here is
preserved in [docs/HISTORY.md](docs/HISTORY.md). It is historical and does not
describe the current state of `main`.

## Current boundary

このリポジトリは情報公開面です。Discord や外部 provider の Current Truth、Human Decision、production runtime の代替ではありません。
