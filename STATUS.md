# Project Status

Updated: 2026-10-13

現在の公開面の状態表です。過去の documentation revision（R91〜R179）の履歴は
[docs/HISTORY.md](docs/HISTORY.md) に移し、この文書は現在地だけを示します。
GitHub の [milestones](https://github.com/Kotodama-Project/Kotodama-project/milestones) が
次に何が来るかの索引です。

Repository entries describe the source in this revision. They do not refresh
or promote the separately scoped runtime/deployment evidence below.

## Current source and open integration work

Source check: 2026-10-13. This revision includes the [README refresh #393](https://github.com/Kotodama-Project/Kotodama-project/pull/393) and the source changes listed below. Refresh main and each linked PR before adoption. Earlier runtime/deployment evidence retains its separately recorded scope.

- Canonical OKF Markdown, typed Goal/KGI/INIT and corrected Source bindings, full-assignment critic evidence, checkpoint recovery and durable cancellation are on main. [#383](https://github.com/Kotodama-Project/Kotodama-project/pull/383) is merged and [#363](https://github.com/Kotodama-Project/Kotodama-project/issues/363) is completed.
- [#384](https://github.com/Kotodama-Project/Kotodama-project/pull/384) is merged and [#365](https://github.com/Kotodama-Project/Kotodama-project/issues/365) is completed: one bounded repair selects leaves from verified gaps, preserves retained work and the original budget, and checks the same proof across normal, recovery and learning readers. The Windows file-identity repair is included.
- The two-leaf A-to-B dependency execution from [#366 / PR #391](https://github.com/Kotodama-Project/Kotodama-project/pull/391) is included in this revision. A separate prerequisite critic gates B's actual input, B-only repair stays within the original six attempts, and cancellation, recovery, old-writer readback and package entrypoints use the same stored proof. Invalid prerequisite responses settle without retry; blocked stages cannot supply receipt replay; initial jobs are exactly the two work jobs and two reviews. Arbitrary DAGs and cross-revision reuse remain outside this scope.
- The bounded local executor from [#375](https://github.com/Kotodama-Project/Kotodama-project/issues/375) is included in this revision. The [knowledge CLI](docs/KNOWLEDGE-TASK-INPUT.md#知識cliから使う) and [installed core CLI](docs/TASK-LOOP-EXECUTOR.md) explicitly select `local_executable_fixture` and run owner-declared child processes with a separate critic. Two document datasets complete in five calls, retain DocA's result and repair only DocB; the original Task and attempt budget remain bound. Saved readers verify the actual input/process evidence and current owner bindings. An anchored replay starts no additional child and preserves a failed receipt's exit status. Hierarchy readers and actual model/user acceptance remain separate work.
- [#390 learning-origin verification reuse](https://github.com/Kotodama-Project/Kotodama-project/issues/390) is included in this revision. A single invocation reuses completed origin semantics, while each guard rereads current proof, policy, Source, owner, actors, relevant execution DB state and the latest learning decision. The final check also detects changes made during policy validation. A new invocation verifies semantics again; this removes repeated deep verification without extending a Task budget or skipping freshness checks. The [learning contract](docs/TASK-LEARNING-REUSE.md) defines the scope; no general speedup or production performance is claimed.
- [#392 learning-origin readback](https://github.com/Kotodama-Project/Kotodama-project/issues/392) is included in this revision. Public `propose_learning` and its CLI read a bounded, validated private copy without creating or repairing the original execution DB/WAL/SHM. Missing/corrupt state and missing required current-schema tables produce typed refusals; matching verified legacy-writer formats remain readable. Current owner, Source, expiry, cancellation and final artifact checks remain required. This changes proposal readback; explicit learning review/decision writes retain their existing contract.
- The Project-centered intent/design from [#386](https://github.com/Kotodama-Project/Kotodama-project/pull/386) and the first [Project view](docs/PROJECT-HUB-VIEW.md) from [#388](https://github.com/Kotodama-Project/Kotodama-project/pull/388) are merged. The CLI resolves operator-selected existing Task owners and inspects correction candidates; it does not persist a Project or dispatch work.
- Ordinary Task admission from [#346](https://github.com/Kotodama-Project/Kotodama-project/pull/346) is adopted: default width 1, finite queue, actor/room fairness, writer barrier and settlement-based slot release. Same-load performance and resource admission remain separate work.

These are bounded source/fixture results. Full eight-layer operation, actual model/user outcomes and production acceptance remain open.

| Candidate / owner | Actual state and remaining gate |
|---|---|
| [#372 / #347](https://github.com/Kotodama-Project/Kotodama-project/issues/372) | Multiple parents and current Plan/Task references need their bounded reader/producer acceptance. A hierarchy preview or opaque reference alone does not prove all current owner bindings, corrected inputs or the whole eight-layer mechanism |
| [PR #389 / #330 / #331](https://github.com/Kotodama-Project/Kotodama-project/pull/389) | Measurement CLI candidate `d2822b0`; the [fixed width 1/2/4 observations](https://github.com/Kotodama-Project/Kotodama-project/blob/c4f1a21830c3f7bccb8cd16420e76179b843d20d/docs/PERFORMANCE-TASK-ADMISSION-2026-10-13.md) and raw samples are published separately. All 72 fixed-fixture trials passed. Waiting overlapped; synchronous CPU work did not become parallel. Full-pipeline memory, sustained memory growth, provider cost and production qualification remain unmeasured; the default width is unchanged |
| [#385](https://github.com/Kotodama-Project/Kotodama-project/issues/385) | Stage 1 read-only Project view is adopted. Next: existing Project-owner persistence/correction events and shared GUI/natural-language operations, then configurable orchestration, live external-agent acceptance and measured optimization |

Remaining hierarchy/executor reader acceptance for #375 belongs with #372/#347. Non-conflicting measured performance work (#330/#331 and retrieval #326/#349) and Project common operations (#385) can progress in parallel. Broader intent and improvement acceptance stays with #327/#328/#350. Use each existing Issue's current evidence and owners; the preview branch is not a second release or Task ledger.

README is the short entrypoint for this status; the owner-intent document retains the product direction.

## Current public surfaces

| Surface | Status |
|---|---|
| Public repository | Published preview |
| Product direction and roadmap | Public |
| Company governance starter | Published and locally validated |
| [Task-bound Company Pack execution](docs/COMPANY-PACK-TASK-EXECUTION.md) | Local CREATE_COMPANY_PACK adapter plus explicit Discord CLI/slash connector, bound to one existing SQLite Task; real Linux HTTP/Python/Docker/result readback tested; disabled by default, Windows/macOS writes and remote owner refused; live Discord/Human acceptance remains unverified |
| [Explicit Discord Task swarm](docs/TASK-SWARM-RUN.md) | Disabled-by-default slash research on the existing local Task owner; fixed 3 workers plus verifier, daily reservations, current Source/grant checks, cancellation and exact-result readback. Linux synthetic end-to-end is tested. Live workers require a dedicated authenticated home and verified root-deny profiles; actual model/Discord acceptance remains unverified |
| [Persistent local review gateway](runtime/local-review-gateway/README.md) | Included local review/restart candidate with operator-selected catalog v3: classification, explicit readers/reviewers, tenant and review purpose, source-bound consent, expiry and revocation; human-kind admission for human review; snapshot policy is not identity authentication. Live Access/Tunnel and automatic Voice-to-Task connection remain unverified |
| [Discord runtime candidate](docs/DISCORD-RUNTIME.md) | Included Node24 template with local ASR, continuous Live conversation and bounded Task workers. Indexed Source/Task context, finite raw HTTP/ASR/notification work, transcript correction delivery and retryable shutdown keep SQLite/host ownership until dispatched work settles. Write workers require Linux isolation and current grants. Real-microphone continuity, two-person 30-minute voice and clean installation in a second setup remain unaccepted; no public Bot |
| [Dots local plugin](runtime/discord-template/dots-plugin/README.md) | Included stdio source for one configured owner and allowed channels, cursor discovery and revision-bound Unicode-safe full-text pages. Synthetic official-SDK tests verify complete text, corrections, revocation, finite authorization waits and zero Task creation; live Dot connection and continuous monitoring remain unaccepted |
| [Long-context agent communication benchmark](docs/LUNA-TASK-SWARM.md) | Required CI exercises three synthetic profiles, retained history, exact evidence/correction/replay, payload bounds and indexed work. Deterministic reference workers are not measurements of model reasoning, live providers or global concurrency |
| [Session / conversation event ledger](docs/SESSION-CONVERSATION-LEDGER.md) | Schema/validator plus local Discord `ledger-export`, encrypted Source/event payload and readback, opaque same-Task correlation, synthetic Python validation; real-data export and operational retention/backup remain unverified |
| Agent swarm and autonomous delegation after a human GO | [Luna Task swarm](docs/LUNA-TASK-SWARM.md) (#67 with the #85 repairs) is on `main` as a bounded local runtime: owner-bound plans, budgets, acknowledged peer messages, and an independent verifier, exercised by the offline fixture on Linux and Windows in the required check; a prior live synthetic fixture pass at `7df1aea` is recorded in [#159](https://github.com/Kotodama-Project/Kotodama-project/issues/159#issuecomment-5852532538); current-revision live acceptance is not established. The swarm and route-binding contract candidates from #34 are on `main` as schemas, read-only validators, and tests that start no agent; the [adoption candidate](docs/AGENT-SWARM-KOTODAMA-ADOPTION-CANDIDATE.md#luna-task-swarm-との対応) maps the swarm contract to this runtime (both have their own rows below). The public migration ledger contract from #35 is included as a schema, read-only verifier, tests, and synthetic fixture, with a mapping to this runtime; the ledger is not populated and migration execution remains unverified. The [agent lifecycle contract](docs/PUBLIC-AGENT-LIFECYCLE-REGISTRY.md) from #36 includes a schema, read-only verifier, negative tests, and a synthetic fixture; the real registry is absent and runtime/continuity remain unverified ([#30](https://github.com/Kotodama-Project/Kotodama-project/issues/30)). The repository's own [improvement loop](docs/IMPROVEMENT-LOOP.md) defines how agents select, verify, merge, and revert one change at a time |
| [Git Steward coordination core](runtime/git-steward/README.md) | Included local candidate from #179: work-cell reservations, lease/epoch fences, independent review and a SQLite journal, covered by the Linux regression launcher and path-scoped Node CI on Linux/Windows; no model call, Git/GitHub/provider write or deployment. [Design](docs/GIT-STEWARD-AND-WORK-CELLS.md) and [business rehearsal](docs/BUSINESS-REHEARSAL.md) cover synthetic corrections and restart with temporary Git/SQLite/processes; live admission, executors and provider integration remain unverified |
| [Public knowledge base (OKF)](docs/KNOWLEDGE-BASE.md) | Canonical OKF Markdown, deterministic catalog/graph, lexical query, bounded context, typed Goal/KGI/INIT and corrected-Source input binding through the existing Task owner. The checked catalog contains 50 Concepts. Stale concepts stay out of delivery candidates and required context takes priority. Owner-bound learning candidates keep current-decision/revocation checks and connect to explicit local execution. Independent concept quality, model/user outcome, large-corpus performance and full hierarchy integration remain separate acceptance; no new grant or Goal/Task owner is issued |
| [Local Task loop execution](docs/TASK-LOOP-EXECUTOR.md) | Included in this revision through the source knowledge CLI and installed core module. Explicit `local_executable_fixture` runs local child processes, an independent critic and bounded partial repair under the existing Task/owner/budget. Saved proof and current owner/learning-decision checks cover normal execution, recovery and replay; learning-origin semantics are reused within one invocation. Hierarchy reader integration, actual models, user outcomes and production remain unaccepted |
| [Project information contract and Task view](docs/PROJECT-HUB-VIEW.md) | Adopted local read-only CLI and correction-proposal checks from #388. Existing owner, revision, context digest, expiry and cancellation are checked. Project persistence, Task mutation/dispatch, GUI/NL shared operations and live external-agent integration remain unimplemented |
| Slack / Teams / Salesforce adapters | [Synthetic Slack/Teams event contract](docs/SURFACE-ENVELOPE.md) with signature-mechanism and same-thread scope checks (#70), plus a [synthetic relationship catalog](docs/RELATIONSHIP-CATALOG.md) with revision/ACL filtering and selected-field Salesforce fixture mapping (#77). Real connectors remain unconnected |
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
Voice, Agent Swarm, provider, deployment, Promotion, or Current Truth. The full Company AGI
runtime remains unimplemented; bounded source components are listed above. Public Beta remains `NO_GO_UNPUBLISHED`. The public
bytes preserve the user's working direction as a redacted owner-directed
candidate, not a signed or independently verifiable governance approval,
rightsholder proof, canonical adoption, launch decision, or Final Human GO; no receipt is fabricated. The root license is MIT (merged via #18 on
2026-09-12). [License scope](docs/LICENSE-SCOPE.md) records Issue #25's owner decision,
admitted batch provenance and notices. Future exports still require their own checks.

## Latest runtime result

最新の private Voice runtime cutover attempt は、read-only reconciliation 後に `BLOCKED_NO_EFFECT` と判定されました。候補ファイルの deploy は 0、外部 provider API の作用も 0 でした。

これは安全に停止したことの証拠であり、Voice runtime が公開稼働していることの証明ではありません。

## Documentation revision history

The R91 to R179 documentation revision narrative that previously lived here is
preserved in [docs/HISTORY.md](docs/HISTORY.md). It is historical and does not
describe the current state of `main`.

## Current boundary

このリポジトリは情報公開面です。Discord や外部 provider の Current Truth、Human Decision、production runtime の代替ではありません。
