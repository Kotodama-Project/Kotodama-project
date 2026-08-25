# Owner-confirmed Company AGI direction

Status: **Owner-confirmed Human Intent / product direction**
Recorded: 2026-08-26
Canonical role: the owner-intent source for Kotodama's Company AGI product direction
Runtime state: documentation only / `NO_GO_UNPUBLISHED`

This record preserves the product direction without treating a README, design
candidate, runtime flag, or local test as execution authority or Current Truth.

## Target

- Improve BecomeOne's organization SSOT, decomposition, Agent Swarm, and Context
  kernel while integrating the useful contracts and implementations into
  Kotodama's conversation, Voice, Intent, and product runtime. The destination
  is one Kotodama product and one governed Company SSOT, not two permanent
  products or competing sources of truth.
- Pursue **bounded autonomous operation** across ingestion, speaker attribution,
  intent extraction, Requirement and Plan generation, specialist-agent
  construction and invocation, task decomposition, Swarm execution, replanning,
  verification, and learning.
- Keep ambiguous requirements and irreversible, external, or high-impact
  decisions behind an explicit Human gate. Autonomous work must not bypass
  consent, authority, review, rollback, or stop conditions.
- In an explicitly designated private Voice channel, allow policy-bound
  auto-join, continuous recording and transcription, and automatic generation
  of Intent Candidate and bounded Work Order Candidate records, followed by a
  same-channel preview. Capture in every other guild or channel remains
  fail-closed, and a candidate never promotes itself to Human Decision or
  Current Truth.
- Use a **Voice Requirements Agent** / GrillU facilitator to hear
  speaker-attributed Source Evidence, ask the most important missing question
  one at a time, preserve answers, corrections, holds, and unknowns in
  Requirement State, and read a Plan Candidate back for Human confirmation.
  Keep it separate from the **Execution Agent**; it cannot self-approve or
  self-execute.
- Share specialists as an **Agent Definition / Card**, but create a new bounded
  Invocation each time with Capability Grant, Knowledge Scope, MCP / Tool /
  Action Grant, VM / CT placement, Model / Subscription, Discord Voice Binding,
  Context Subscription, budget, expiry, kill conditions, and Evidence Sink.
  Sharing a specialist never shares ambient authority.
- Preserve Human speech and source, intent, correction, withdrawal, and
  confirmation in a causal ledger. Conversation, Swarm, and Decision views are
  projections from that ledger, not independent truth stores.
- Exclude a metered LLM API architecture. Bind subscription access to each
  Invocation, and keep general-purpose local LLM operation deferred.

Target flow:

```text
Conversation / Voice -> Source Evidence -> Requirement State -> Plan Candidate
-> bounded Work Order -> Agent Swarm -> Verification Receipt -> Promotion
-> reply / learning
```

## Model lane target

**Codex App Server** with **ChatGPT OAuth / subscription** is an approved design
candidate for the owner's internal Company AGI. It provides identity-bound subscription access.
It is not a pooled credential or ambient capability.

| Lane | Target role |
|---|---|
| Local permitted components | ASR / VAD, speaker diarization and identity support, Encoder / embedding / indexing, tiny specialist classifiers / rankers when justified, and deterministic parsers, validators, redaction, and routing rules |
| GPT-5.6 Luna ONLY | Every Agent Swarm role: coordinator, researcher, worker / builder, reviewer, and verifier, through verified Luna Skills and the selected effort policy |
| GPT-5.6 Sol | Human-facing root integrator outside the swarm: fixes objective, budget, and authority; starts the Luna swarm; verifies provenance; reopens evidence; integrates outputs; and makes the final decision |
| Terra | Optional non-swarm middle-tier experiment; not required and never an automatic fallback |
| Anthropic | Possible non-swarm experiment only under compatible official terms and explicit approval; never an automatic fallback |
| General local LLM | deferred experiment; not adopted as a reasoning layer or fallback |

Sol is outside the swarm. It cannot replace a Luna coordinator, researcher,
worker / builder, reviewer, or verifier.

Every Agent Invocation binds user, workspace, personal seat / subscription,
exact model, effort, role, task, rate-limit state, approvals, context and grants,
budget / TTL, and audit / evidence destination. Luna output is accepted only
after **runtime model / effort / provenance** verification, never by its name or
task label alone. If Luna is unavailable or its runtime identity cannot be
proven, the swarm stops with no automatic fallback to Sol, Terra, Anthropic, a
general local LLM, or another model. Local permitted components are not LLM
swarm roles.

## Current reality

- BecomeOne remains a private kernel and migration source while Kotodama is the
  product destination. Their useful contracts are not yet fully reconciled or
  promoted into one product and one Company SSOT.
- The current private CT200 deployment has Voice bridge, capture, transcript,
  retention, and intent components, but its active desktop-Voice path does not
  yet connect simultaneous recording, rotation, transcription, Intent
  generation, and Swarm execution end to end.
- Public Kotodama provides candidate contracts, validators, and documentation.
  It does not provide the private Voice runtime, an activated Agent Swarm,
  provider E2E, or Public Beta access.
- Encoder Steward's latest package is not eligible for activation; embedding,
  vector, retrieval-quality, durable database, and private-data runtime evidence
  remain unproven. Derived embeddings and indexes remain rebuildable
  projections, not Memory SSOT.

## Open design decisions

- A2A transport, realtime Context, large-context sharing, Context Subscription,
  ledger/projection topology, RAG, knowledge graph, encoder, and invalidation
  contracts remain under research.
- Google Drive and Proxmox storage roles, final hierarchy and graph shape,
  naming, placement, model/subscription selection, and specialist-sharing UX
  remain unresolved.
- The eight-surface product map and Forest Map v2 eight-layer hierarchy are
  different concepts. The current Forest Map is an input to migration and
  validation, not a final architecture decision.

## Authority and non-effects

This record does not authorize runtime execution.
This record does not create a Capability Grant.
This record does not change Current Truth.
This record does not grant Final Human GO.
Credentials are never pooled or shared.
One personal seat is not unlimited multi-tenant capacity.

Implementation, provider, deployment, publication, and Promotion remain
separate candidate-bound work. Public Beta remains `NO_GO_UNPUBLISHED`.
