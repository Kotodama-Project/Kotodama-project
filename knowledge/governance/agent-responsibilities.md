---
type: Agent Contract
title: Knowledge-agent responsibilities
description: Assign source ingestion and maintenance to the librarian, independent verification to the auditor, ownership resolution to the coordinator and bounded implementation to the builder.
tags: [governance, agents, ownership, review]
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
  - id: agents
    resource: ../../AGENTS.md
    title: Contributor and agent entrypoint
    author: team:kotodama-project
kotodama:
  profile: "0.1"
  id: governance/agent-responsibilities
  classification: public_candidate
  authority: projection_only
  knowledge_state: candidate
  owner_role: AI-LIBRARIAN
  reviewer_role: AI-AUDITOR
  context_priority: 10
  goal_refs: [OUT-INTENT, OUT-LOCAL]
  kgi_refs: [KGI-INTENT]
  initiative_refs: [INIT-KNOWLEDGE-REFRESH, INIT-AGENT-OWNERSHIP, INIT-CONTEXT-AUDIT]
  agent_use:
    discoverable: true
    answer_mode: source_required
    decision_authority: false
    runtime_authority: false
---

# Responsibility matrix

| Role | Accountable output | Must not do |
|---|---|---|
| `AI-LIBRARIAN` | Source-to-concept lineage, lifecycle state, affected-view rebuild, retrieval evaluation inputs | Promote unreviewed claims, regenerate revoked data, rewrite history |
| `AI-AUDITOR` | Independent source/content/context review and explicit finding disposition | Execute the reviewed change, approve its own output, alter evidence |
| `AI-CHIEF` | Resolve existing owner, goal/KGI relationship, priority and material notification path | Change human intent, expand grants, collapse review into coordination |
| `AI-BUILDER` | Implement bounded parsers, projections, tests and repair proposals | Publish, write production state or broaden scope without the relevant grant |
| `AI-ANALYST` | Measure retrieval/context quality, uncertainty, proxy-to-outcome relation and side effects | Treat correlation or coverage as proven outcome |

# Work cycle

1. The librarian reads only authorized sources and records revision/provenance.
2. It creates or updates a candidate concept and an impact set.
3. The builder updates deterministic projections or tooling when required.
4. A distinct auditor checks source fidelity, lost constraints, conflicts and the proposed disposition.
5. The librarian applies the reviewed bounded update and performs readback.
6. The analyst measures retrieval and task outcome; the coordinator routes material failures or owner conflicts.

The number of agents is not a success metric. One writer owns each mutable surface, child agents inherit a bounded context and grant, and the parent remains accountable for integration.

# Runtime boundary

These are logical contracts. Naming a role in frontmatter does not instantiate a runtime identity, lease, work order, budget or access grant. See [authority boundaries](authority-boundaries.md).
