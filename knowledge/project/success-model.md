---
type: Metric
title: Goal, KGI, KPI and knowledge-quality model
description: Preserve the existing outcome and KGI references, then measure whether the knowledge system supplies fresh, source-backed context without treating coverage metrics as the product outcome.
tags: [goal, kgi, kpi, quality, measurement]
status: draft
stale_after: 2026-12-07T00:00:00Z
generated: { by: process:strategy-definition, at: 2026-10-06T21:30:01Z }
sources:
  - id: owner-direction
    resource: ../../docs/OWNER-INTENT-COMPANY-AGI.md
    title: Owner-recorded Company AGI direction
    author: team:kotodama-project
  - id: product-direction
    resource: ../../docs/PRODUCT-DIRECTION.md
    title: Product direction and context requirements
    author: team:kotodama-project
kotodama:
  profile: "0.1"
  id: project/success-model
  classification: public_candidate
  authority: projection_only
  knowledge_state: candidate
  owner_role: AI-ANALYST
  reviewer_role: AI-AUDITOR
  context_priority: 30
  goal_refs: [OUT-INTENT, OUT-LOCAL]
  kgi_refs: [KGI-INTENT]
  initiative_refs: [INIT-KNOWLEDGE-FORMAT, INIT-KNOWLEDGE-REFRESH, INIT-CONTEXT-AUDIT]
  strategy:
    id: KGI-INTENT
    adoption_status: candidate
    measurement_role: product_outcome
    baseline: unknown
    target: not_adopted
    deadline: not_adopted
    measurement_window: not_adopted
    exclusion_policy: not_adopted
    relationships: []
  agent_use:
    discoverable: true
    answer_mode: source_required
    decision_authority: false
    runtime_authority: false
---

# Existing references

The [goal concept](goal.md) defines `OUT-INTENT` and `OUT-LOCAL` from the current
public product direction. This concept defines the canonical projection ID
`KGI-INTENT`: requested outcomes accepted by the outcome owner after independent
verification within the existing authorized scope. Artifacts, receipts, PRs, Tasks,
reviews and agent counts cannot substitute for the requested outcome. The owning
intent, Task and decision systems retain acceptance and adoption.[^owner-direction]

The existing initiative IDs resolve to individual candidate Concepts:

| ID | Scope |
|---|---|
| [INIT-KNOWLEDGE-FORMAT](../initiatives/knowledge-format.md) | Maintain the public OKF projection and its separate producer checks |
| [INIT-KNOWLEDGE-REFRESH](../initiatives/knowledge-refresh.md) | Recheck and rebuild only affected source-backed concepts |
| [INIT-AGENT-OWNERSHIP](../initiatives/agent-ownership.md) | Resolve existing responsibilities without creating a Task owner |
| [INIT-CONTEXT-AUDIT](../initiatives/context-audit.md) | Inspect required, forbidden and omitted context against sources |
| [INIT-CONTEXT-HANDOFF](../initiatives/context-handoff.md) | Preserve source and correction references during delegation |
| [INIT-DYNAMIC-AGENT-CONTEXT](../initiatives/dynamic-agent-context.md) | Reassemble context after source, policy or work-boundary changes |
| [INIT-CONTEXT-END-TO-END](../initiatives/context-end-to-end.md) | Evaluate delivered input and actual outcomes separately |
| [INIT-METHOD-RENEWAL](../initiatives/method-renewal.md) | Compare retrieval methods on the same required/forbidden fixtures |

These definitions implement the canonical #48 vocabulary choice. Mapping the
older #49 strategy metrics is follow-up work under #52; its competing
`governance/okf.json` is not imported. No baseline, target or measurement is
fabricated by defining an ID.

# Knowledge-quality measurements

The validator reports these measurements without silently adopting targets:

| Measurement | Meaning |
|---|---|
| Source coverage | Concepts with at least one resolvable or explicitly external source |
| Freshness coverage | Concepts not past `stale_after` at the audit instant |
| Independent verification coverage | Concepts checked by an actor other than the generator |
| Human-review coverage | Concepts with a `human:` verification actor |
| Structural retrieval eligibility | Discoverable, source-backed, non-stale concepts with no unresolved conflict; separate from decision readiness |
| Context coverage | Required goal/KGI/initiative concepts returned within a bounded context set |
| Orphan count | Concepts unreachable through bundle indexes or concept links |
| Conflict count | Concepts explicitly marked `conflicted` and still unresolved |

# Candidate KGI additions

The following are **measurement candidates**, not adopted policy or numerical targets:

1. **Required-knowledge readiness**: the proportion of active work whose required concept set is source-backed, fresh, access-allowed and independently reviewed.
2. **Correction propagation**: the proportion of source corrections or revocations whose affected projections are invalidated and rebuilt within the owning SLA.
3. **Fresh-session recovery**: the proportion of authorized tasks resumed in a fresh session without material correction caused by missing project context.
4. **Grounded retrieval success**: the proportion of evaluation questions for which required source-backed concepts appear within the allowed context budget.

Each candidate needs an owner, denominator, evidence source, baseline, target, deadline and anti-gaming guard before adoption. See [retrieval quality](../operations/retrieval-quality.md) and [agent context assembly](../operations/agent-context.md).

[^owner-direction]: Current owner-recorded direction; projection definitions and measurements remain candidates.
