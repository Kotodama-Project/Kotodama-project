---
type: Evaluation Plan
title: Knowledge retrieval quality
description: Evaluate whether bounded retrieval returns the source-backed concepts and ancestor constraints needed for a real task, before adopting embeddings or a new ranking method.
tags: [operations, retrieval, evaluation, search, context]
status: draft
stale_after: 2026-12-07T00:00:00Z
generated: { by: kotodama-kb/bootstrap-v1, at: 2026-09-07T04:00:00Z }
sources:
  - id: context-policy
    resource: ../../docs/CONTEXT-AND-AGENT-RESPONSIBILITY.md
    title: Intent, position, responsibility and dynamic context
    author: team:kotodama-project
  - id: operating-policy
    resource: ../../docs/operating-policy.json
    title: Operating policy projection v1.6.0
    author: team:kotodama-project
kotodama:
  profile: "0.1"
  id: operations/retrieval-quality
  classification: public_candidate
  authority: projection_only
  knowledge_state: candidate
  owner_role: AI-ANALYST
  reviewer_role: AI-AUDITOR
  context_priority: 25
  goal_refs: [OUT-INTENT, OUT-LOCAL]
  kgi_refs: [KGI-INTENT]
  initiative_refs: [INIT-KNOWLEDGE-FORMAT, INIT-KNOWLEDGE-REFRESH, INIT-METHOD-RENEWAL]
  agent_use:
    discoverable: true
    answer_mode: source_required
    decision_authority: false
    runtime_authority: false
---

# Evaluation unit

Each fixture represents an authorized question or task and records:

* the originating goal/KGI/initiative references;
* required concepts and required primary sources;
* forbidden, revoked or superseded concepts;
* material constraints that must survive compression;
* the maximum concept and token budget;
* the expected next action or explicit unknown.

# Measurements

| Measurement | Failure it detects |
|---|---|
| Required-concept recall at `k` | Necessary knowledge omitted from the bounded result |
| Source recall at `k` | Summary found but its authority/source not made reachable |
| Ancestor-constraint retention | Similarity ranking displaced mandatory goal or policy context |
| Superseded/revoked leakage | Invalidated knowledge re-entered context |
| Citation/source fidelity | Answer cites a concept but not the source supporting the claim |
| Material-correction rate | A human must correct missing or distorted intent/context |
| Latency and context size | Retrieval works but is operationally unusable |
| Outcome contribution | Ranking metrics improve without the requested task outcome improving |

# Baseline and method changes

The current implementation intentionally starts with transparent lexical scoring plus explicit graph filters. It is a baseline, not a claim of semantic adequacy. A vector, reranker or encoder is adopted only after comparison on the same fixtures shows a meaningful improvement in required-context recall or task outcome while preserving access, invalidation, latency, cost and rollback behavior.

# Negative fixtures

Tests must include ambiguous queries, stale current-state pages, conflicting sources, missing parent links, revoked information, similarly worded but unrelated concepts, and a KPI that improves while the actual requested outcome does not.

Use [agent context assembly](agent-context.md) for the bounded output contract and the [success model](../project/success-model.md) for measurement interpretation.
