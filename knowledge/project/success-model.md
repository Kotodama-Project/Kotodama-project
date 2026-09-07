---
type: Success Model
title: Goal, KGI, KPI and knowledge-quality model
description: Preserve the existing outcome and KGI references, then measure whether the knowledge system supplies fresh, source-backed context without treating coverage metrics as the product outcome.
tags: [goal, kgi, kpi, quality, measurement]
status: draft
stale_after: 2026-12-07T00:00:00Z
generated: { by: kotodama-kb/bootstrap-v1, at: 2026-09-07T04:00:00Z }
sources:
  - id: operating-policy
    resource: ../../docs/operating-policy.json
    title: Operating policy projection v1.6.0
    author: team:kotodama-project
  - id: context-policy
    resource: ../../docs/CONTEXT-AND-AGENT-RESPONSIBILITY.md
    title: Intent, position, responsibility and dynamic context
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
  agent_use:
    discoverable: true
    answer_mode: source_required
    decision_authority: false
    runtime_authority: false
---

# Existing references

The current public policy names two outcomes: `OUT-INTENT` for turning authorized conversation into audited work, and `OUT-LOCAL` for a reproducible local-first company runtime. Its current KGI reference, `KGI-INTENT`, counts verified intent-to-artifact vertical slices. `KPI-RECEIPTS` and `KPI-INTENT-ACCEPT` are proxy measures and do not prove the outcome.[^operating-policy]

# Knowledge-quality measurements

The validator reports these measurements without silently adopting targets:

| Measurement | Meaning |
|---|---|
| Source coverage | Concepts with at least one resolvable or explicitly external source |
| Freshness coverage | Concepts not past `stale_after` at the audit instant |
| Independent verification coverage | Concepts checked by an actor other than the generator |
| Human-review coverage | Concepts with a `human:` verification actor |
| Retrieval readiness | Discoverable, source-backed, non-stale concepts with no unresolved conflict |
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

[^operating-policy]: Operating policy projection v1.6.0; it explicitly publishes definitions without current measurements, historical targets or revived deadlines.
