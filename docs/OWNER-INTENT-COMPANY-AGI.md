# Owner-confirmed Company AGI direction

Status: **Owner-confirmed Human Intent / product direction (redacted public candidate)**
Recorded: 2026-08-27
Canonical role: the owner-intent source for Kotodama's Company AGI product direction
Runtime state: documentation-only candidate / `NO_GO_UNPUBLISHED`

This public byte projection preserves the user's owner-directed working
direction, but it is not a signed or independently verifiable governance
approval, rightsholder proof, canonical adoption record, launch decision, or
Final Human GO. It does not fabricate a receipt. The redacted record is
authoritative only as a candidate input for the product direction. It explicitly
supersedes stale Candidate 1 wording about model routing, fixed question shape,
archive selection, and BecomeOne's migration role. It does not treat a README,
design candidate, runtime flag, or local test as execution authority or Current
Truth.

## Target

The promise remains: **conversation can become governed, reviewable work and
learning without losing its evidence, authority, or human boundary.** Kotodama
may pursue bounded autonomy across conversation ingress, speaker attribution,
intent extraction, Requirement and Plan formation, specialist-agent
construction and invocation, decomposition, Swarm execution, replanning,
verification, and learning.

### One product and migration boundary

- There is one public Kotodama product and one governed Company AGI / Company
  SSOT. BecomeOne is the private donor and experimental kernel during migration.
- After migration, BecomeOne is a consumer/control plane pinned to the public
  Kotodama version and content digest. It is never a second product SSOT or a
  competing public product.
- A candidate, projection, or agent may not promote itself to Human Decision or
  Current Truth. Ambiguous requirements and irreversible, external, or
  high-impact decisions remain behind an explicit Human gate.

Target flow:

```text
Conversation / Voice -> Source Evidence -> Requirement State -> Plan Candidate
-> bounded Work Order -> Agent Swarm -> Verification Receipt -> Promotion
-> reply / learning
```

## Canonical transaction and projection boundary

Kotodama's **canonical transactional SSOT core** is an **append-only causal
ledger**. It preserves correction and supersession, authority and capability
grants, causal history, the current revision, concurrency and idempotency, and
immutable Source Evidence locator/digest bindings. A correction appends a new
event and relationship; it does not erase or silently rewrite the prior event
or source.

Current Truth is derived by evaluating the applicable revision, authority, and
causal history. OKF is a **first-class agent-readable curated knowledge read
model** built from that ledger and provenance-bound sources. A source,
supersession, authority, ACL, or retention change can rebuild or invalidate the
OKF projection. OKF is not the transactional write model, raw archive,
authority/ACL engine, or sole audit record.

This is a **target architecture candidate, not a claim about current donor
runtime**. Git remains authoritative for current code, contracts, schemas,
policies, and already admitted facts until a reviewed migration,
reconciliation, Promotion Decision, and cutover occur.

The first executable proof is a disposable, offline, **single-writer
SQLite/WAL** pilot. Its bounded contract allows at most **64 admitted events**,
**900 seconds**, **10 monitor ticks**, and one `STOP` file checked before every
append, consumer tick, snapshot, and restore boundary. The pilot must verify an
`event_digest` over the **complete immutable event envelope**, its prior-event
digest chain, idempotent replay and divergent-replay rejection, stream-version
conflicts, isolated snapshot/restore, deterministic Forest/OKF rebuild, and one
correction/invalidation path.

Ledger MCP access remains **deny-by-default**: bounded read and proposal scopes
come before protected append, restore, or promotion-request tools; no agent has
ambient credentials, direct table access, or self-approval. **Automatic erasure
remains disabled** until retention, legal-hold, key-custody, replica/backup, and
post-erasure restore rules have separate approval and negative-path evidence.
This bounded documentation direction **does not adopt a runtime**, database,
archive target, cutover, Decision, Promotion, or Current Truth.

## Governed knowledge and OKF

[Google Cloud Open Knowledge Format (OKF)](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md)
is the central human- and agent-readable representation for governed, curated
knowledge, not the sole Company truth. The current official format is **OKF v0.2**; the canonical
repository is
`GoogleCloudPlatform/open-knowledge-format`. The v0.2 trust-signal context is
described by [Google Cloud's OKF v0.2 announcement](https://cloud.google.com/blog/products/data-analytics/okf-v0-2-adds-trust-signals/).

OKF is deliberately a format, not a central control plane. OKF itself has no
central authority, transactional state, raw archive, ACL, storage/serving/query
semantics, audit ledger, deletion semantics, or concurrency semantics. Raw
sources and operational systems retain their own source-of-record role.
Owner-reviewed OKF concepts may be canonical for governed curated interpretation;
generated OKF concepts are rebuildable projections and are never canonical source
authority.

Kotodama therefore needs an extension profile around OKF with:

- a stable logical ID, immutable revision/content digest, and parent revision;
- evidence locators, evidence hashes, and derivation details;
- an authenticated authority/policy/approval receipt;
- supersession, invalidation, and retention state;
- typed, revision-bound links;
- atomic promotion / compare-and-set (CAS);
- Context Pack and attestation binding; and
- an erasure/invalidation index.

The extension profile governs promotion around OKF; it does not silently add
those semantics to the OKF format itself.

## Conversation ingress and evidence

Conversation ingress includes **Discord text and Voice, Codex, Claude, Notion,
GitHub, Google Drive, and n8n**. Every source enters the same evidence boundary
with exact source/session/channel, speaker or individual track, timestamps and
spans, raw ASR text where applicable, consent/retention revision, and a digest.

Raw evidence is retained as a distinct source layer. Derived stages are separate
and never overwrite raw evidence:

```text
raw PCM + ingress event JSON
-> per-speaker ASR
-> optional timestamp/acoustic alignment
-> immutable speaker-attributed transcript
-> deterministic/contextual corrected transcript (separate sidecar/diff)
-> whole-conversation minutes
-> Source Evidence / Intent events
```

Raw PCM and ingress event JSON, together with source provenance, are evidence for
what was captured. An individual speaker track is authoritative only for
attribution within the capture contract; ASR remains derived and fallible.
Phoneme/G2P may help with dictionary lookup, normalization, or alignment, but it
must not be presented as reconstructing unknown words from audio. Corrections,
summaries, and Intent events point back to source spans and revision-bound
evidence; the corrected transcript is a sidecar/diff and never replaces raw
capture or the immutable speaker-attributed transcript.

Meeting input adapters include **Microsoft Teams, Google Meet, and Zoom**. They
ingest speaker-attributed raw JSON and raw transcripts, preserve
diarization/alignment and provenance, keep corrections in corrected sidecars,
and derive minutes before emitting Source Evidence and Intent Candidate
records. No meeting transcript or minutes self-promote to Decision or Current
Truth, and a provider speaker label does not prove identity, consent, or
authority.

Requests explicitly marked as Kotodama-related are captured automatically as
Source Evidence and Intent Candidate records with their source, observation
time, attribution state, policy revision, authority label, and digest. Capture
does not approve, execute, issue a Work Order, promote, or change Current Truth.
Raw utterances and private source locators remain in protected Source Evidence
and are not published in this repository. Public platform names and aliases are
derived terminology, not silent transcript rewrites.

## Sessions, Requirements, and GrillU

Session auto-creation is allowed. Each Session binds, when known, to Task SSOT,
Plan/Requirement references, Agent Invocation and model provenance,
Capability/Knowledge/MCP grants, A2A delegation, dependencies and parallel
status, evidence, and invalidation. Unknown or ambiguous authority remains
explicit rather than being inferred or hidden.

Voice Requirements / GrillU is an adaptive, channel-neutral facilitator.
Natural continuous Voice conversation can form requirements. It asks only when
uncertainty, impact, or authority needs clarification; it does not mandate a
rigid UI or a one-question ritual. The number and shape of prompts follow the
conversation and the remaining uncertainty. Facilitation preserves answers,
corrections, holds, and unknowns in Requirement State, but it does not
self-approve, self-promote, or gain execution authority.

## Bounded execution and agent authority

Agents may auto-execute reversible work in a self-owned disposable clone,
worktree, or container, and later in an isolated VM. Every execution binds the
exact base or image, owner, data/network/tool grants, budget, TTL, kill
condition, export/evidence boundary, and cleanup receipt. There is no ambient
shared, production, public, or credential authority.

Specialists may be shared as an Agent Definition / Card, but every run receives
a new bounded Invocation with its own Capability Grant, Knowledge Scope,
MCP/Tool/Action Grant, model/subscription binding, context scope, budget,
expiry, kill conditions, and Evidence Sink.

## Model and local-component policy

The policy is **Luna-first**, not exclusive. The overwhelming majority of
Context Pack, research, implementation, coordination, and routine review work
uses **GPT-5.6 Luna**. **GPT-5.6 Sol** may be selected for upper-tier
architecture, difficult integration, cross-swarm audit, adversarial synthesis,
and human-facing judgment. **Terra** may be explicitly selected when
appropriate. Routing never falls back invisibly: every Invocation records the
routing rationale, exact runtime model, and provenance/evidence, and a missing
or unverifiable identity is a bounded stop.

Identity-bound Codex subscription access remains a product candidate, not a
pooled credential or ambient capability. A metered API architecture remains
excluded. General-purpose local LLM operation remains deferred. Local and
deterministic support remains allowed for ASR/VAD, speaker support,
encoder/embedding, tiny deterministic specialists, parsers, validators,
redaction, and routing rules.

## Conversation archive boundary

The Archive Target interface remains provider-neutral. The owner-selected
private v1 backend is an ordinary encrypted file package on a dedicated ZFS
archive dataset with snapshot/restore. The exact suitable dataset and mount must
be identified and read back before use; the current inspection found no safe
dedicated existing target, so this direction creates nothing and writes
nothing. Local package/restore tests proceed first. The final retention period
and deletion policy remain OPEN; no automatic deletion is implied. Future
Drive/S3/NAS replication or migration preserves the package manifest and
digests rather than changing canonical raw evidence.

## Standing GitHub delegation

With standing policy and an agent-executable revert path, agents may branch,
commit, open a PR, and merge when independent review and tests pass. The
delegation preserves the exact revision, review evidence, rollback path, and
post-merge monitoring. It does not authorize force-push or history erasure,
repository deletion, visibility/settings/credential changes, or any other
operation that is not a simple, reviewable revert. Provider, runtime, deploy,
credential, and destructive actions remain separately governed.

## Unattended Improvement Loop

The Unattended Improvement Loop is a product requirement, bounded by budget,
cadence, kill conditions, provenance, and explicit authority:

```text
observe evidence / metrics / feedback
-> create hypothesis and automatic Session / Task
-> disposable experiment
-> Luna-first build / review
-> upper-tier Sol audit / integration when warranted
-> reversible Git merge
-> monitor
-> auto-revert regression
-> promote verified learning into OKF / Company SSOT
```

This loop is not unbounded self-modification. Each experiment and promotion
retains its evidence, routing provenance, review, rollback, and authority
boundary.

The canonical primitive is the **Goal Completion Loop**, owned by one
**Completion Owner Agent** per scoped goal. The owner binds acceptance criteria,
current SSOT revision, authority/capability grants, budget/TTL/kill/rollback,
one global N/C/W/V ledger, max depth two, unique active work keys, and
non-overlapping writers. It decomposes only into bounded disposable work,
aggregates typed evidence, verifies the actual target experience and negative
controls, promotes only reviewed/read-back outputs, updates the causal ledger
and rebuildable OKF projection, and re-evaluates the same goal until complete
or genuinely blocked. Attempts, tasks, reviews, and proxy-green metrics are not
completion evidence. Unchanged inputs suppress reruns, repeated identical
blockers escalate only after a bounded threshold, and regressions auto-revert.

A generic manifest-driven Routing Agent may classify and dispatch the scoped
goal, and a separate Metadata/Context Resolution Agent may resolve exact
SSOT/OKF/Session/Knowledge revisions, lineage, ACL and grants into the minimum
provenance-bound Context Pack. Neither role executes effects, promotes truth, or
expands authority. Execution and review agents consume that packet.

Before creating or linking a Session, recall uses exact metadata, Forest level,
identity, ACL and current-revision filters, then lexical and optional small local
encoder similarity across Session plus curated Knowledge/OKF/BecomeOne donor
candidates. Embeddings are rebuildable projections only. Reuse is allowed only
after source-text/digest/provenance readback and current/superseded/authority
validation; false-neighbor and stale-index paths fail closed.

## Current reality

- This branch is a **documentation-only public candidate**. The canonical
  direction, README projection, STATUS, ROADMAP, and regression tests do not
  implement or deploy the product.
- The private Voice/Intent/Swarm path does not yet prove one end-to-end slice of
  continuous capture, rotation, transcription, requirements, delegation,
  execution, and verification. Provider and public-access gates remain
  unproven.
- Public Kotodama currently provides candidate contracts, validators, and
  documentation. Public Voice, an activated Agent Swarm, provider E2E, and
  Public Beta access remain unavailable; `NO_GO_UNPUBLISHED` remains in force.

## Open design decisions

- The OKF extension profile, A2A transport, realtime Context, Context Pack and
  attestation topology, causal-ledger storage/query and projection invalidation
  implementation, RAG, knowledge graph,
  encoder, and invalidation implementation remain under research.
- Exact private ZFS dataset binding, external cold-archive replication, and the
  retention/deletion period remain open. Query-plane, raw-source, and
  operational-system roles must not be conflated with the Conversation Evidence Package.
- Exact deployment, model/subscription capacity, specialist-sharing UX, and
  provider/runtime integration remain unresolved and separately governed.

## Authority and non-effects

This record does not authorize runtime execution.
This record does not create a Capability Grant.
This record does not change Current Truth.
This record does not grant Final Human GO.
Credentials are never pooled or shared.
One personal seat is not unlimited multi-tenant capacity.

PR #18 supplies Apache-2.0 candidate bytes for this public repository. Issue #25 remains open for contributor attribution, complete provenance, NOTICE
handling, and an accountable rightsholder decision; those gaps are not closed
by this redacted direction candidate or by local tests.

The public candidate remains `NO_GO_UNPUBLISHED`.
