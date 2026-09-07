---
type: Project State
title: Knowledge and context current state
description: The branch has source, session, projection, access and logical agent contracts, while cross-project refresh, runtime role binding and live retrieval evaluation remain unproved.
tags: [current-state, baseline, knowledge, context]
status: draft
stale_after: 2026-10-07T00:00:00Z
generated: { by: kotodama-kb/bootstrap-v1, at: 2026-09-07T04:00:00Z }
sources:
  - id: status
    resource: ../../STATUS.md
    title: Repository status
    author: team:kotodama-project
  - id: roadmap
    resource: ../../ROADMAP.md
    title: Repository roadmap
    author: team:kotodama-project
  - id: context-policy
    resource: ../../docs/CONTEXT-AND-AGENT-RESPONSIBILITY.md
    title: Intent, position, responsibility and dynamic context
    author: team:kotodama-project
  - id: project-map
    resource: ../../docs/PROJECT-MAP.md
    title: Project map
    author: team:kotodama-project
kotodama:
  profile: "0.1"
  id: project/current-state
  classification: public_candidate
  authority: projection_only
  knowledge_state: candidate
  owner_role: AI-CHIEF
  reviewer_role: AI-AUDITOR
  context_priority: 20
  goal_refs: [OUT-INTENT, OUT-LOCAL]
  kgi_refs: [KGI-INTENT]
  initiative_refs: [INIT-KNOWLEDGE-FORMAT, INIT-KNOWLEDGE-REFRESH, INIT-DYNAMIC-AGENT-CONTEXT]
  agent_use:
    discoverable: true
    answer_mode: source_required
    decision_authority: false
    runtime_authority: false
---

# Established in repository contracts

* Session and conversation events can be represented separately from a rebuildable session knowledge projection.[^context-policy]
* Logical responsibilities exist for AI-LIBRARIAN, AI-AUDITOR, AI-CHIEF and AI-BUILDER.[^context-policy]
* Information classification, explicit readers/reviewers, expiry and revocation are kept separate from responsibility and execution authority.[^project-map]
* The public surface remains candidate-only and does not itself establish a release decision.[^status]

# Added by this knowledge-base slice

* An OKF v0.2 Markdown bundle for progressive human and agent disclosure.
* A Kotodama producer profile that requires source lineage, public-safe classification, owner/reviewer separation and non-authoritative agent-use flags.
* Deterministic catalog and graph projections.
* Structural validation, freshness/conflict reporting, lexical query and task-scoped context assembly.

# Still unproved or not deployed

* No runtime identity is bound merely because a logical role is named.
* No automatic cross-store invalidation or ACL-revocation propagation is claimed.
* No embedding model, vector database or semantic ranking model is adopted by this slice.
* No retrieval-quality target is met until an authorized evaluation set is run.
* No concept in this bundle is Current Truth without the owning authority's separate promotion path.

The operational path is defined in the [refresh loop](../operations/refresh-loop.md); quality must be measured through [retrieval evaluation](../operations/retrieval-quality.md).

[^context-policy]: Intent, position, responsibility and dynamic-context policy.
[^project-map]: Project map and information-access boundary.
[^status]: Repository status and roadmap.
