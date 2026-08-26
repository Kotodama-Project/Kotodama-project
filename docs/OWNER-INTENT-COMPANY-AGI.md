# Owner-confirmed Company AGI direction

Status: **Owner-confirmed Human Intent / product direction (redacted public candidate)**
Recorded: 2026-08-26
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

The archive backend is **OPEN**. No storage or archive backend is adopted or
preferred by this direction. If useful, Kotodama can define a provider-neutral,
versioned, encrypted Conversation Evidence Package containing a package
version, encryption/key-reference boundary, content manifest and digests,
source/session locators, retention and deletion state, and restore/delete/
retention test receipts. Backend selection follows those restore, delete, and
retention tests; a backend name, availability check, or historical receipt is
not adoption evidence.

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
  attestation topology, ledger/projection topology, RAG, knowledge graph,
  encoder, and invalidation implementation remain under research.
- Archive backend selection remains open until provider-neutral restore/delete/
  retention tests pass. Query-plane, raw-source, and operational-system roles
  must not be conflated with the Conversation Evidence Package.
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
