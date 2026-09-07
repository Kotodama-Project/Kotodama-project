---
type: Context Contract
title: Agent knowledge-context assembly
description: Assemble a small, inspectable projection from required goal, KGI, initiative and source relationships while preserving unknowns, freshness and authority boundaries.
tags: [operations, agents, context, progressive-disclosure]
status: draft
stale_after: 2026-12-07T00:00:00Z
generated: { by: kotodama-kb/bootstrap-v1, at: 2026-09-07T04:00:00Z }
sources:
  - id: context-policy
    resource: ../../docs/CONTEXT-AND-AGENT-RESPONSIBILITY.md
    title: Intent, position, responsibility and dynamic context
    author: team:kotodama-project
  - id: session-ledger
    resource: ../../docs/SESSION-CONVERSATION-LEDGER.md
    title: Session and conversation ledger
    author: team:kotodama-project
  - id: session-projection
    resource: ../../schemas/session-knowledge-projection.schema.json
    title: Session knowledge projection schema
    author: team:kotodama-project
kotodama:
  profile: "0.1"
  id: operations/agent-context
  classification: public_candidate
  authority: projection_only
  knowledge_state: candidate
  owner_role: AI-LIBRARIAN
  reviewer_role: AI-AUDITOR
  context_priority: 5
  goal_refs: [OUT-INTENT, OUT-LOCAL]
  kgi_refs: [KGI-INTENT]
  initiative_refs: [INIT-CONTEXT-HANDOFF, INIT-DYNAMIC-AGENT-CONTEXT, INIT-CONTEXT-END-TO-END]
  agent_use:
    discoverable: true
    answer_mode: source_required
    decision_authority: false
    runtime_authority: false
---

# Inputs

A context request supplies one or more explicit goal, KGI, initiative or tag filters; the current Task/Session owner and scope remain in their owning ledgers. A production selector must also receive the applicable authorization result from the existing policy owner. This public bundle does not resolve private information.

# Selection

1. Select concepts explicitly connected to the requested references.
2. Add mandatory governance concepts and required ancestor context.
3. Exclude revoked, deprecated, non-discoverable and stale critical concepts from ready context; surface them as unresolved instead of silently substituting another concept.
4. Rank by declared `context_priority`, direct reference match and transparent lexical relevance.
5. Stop at the configured concept budget and expose omitted IDs.

# Output

The generated context contains, for each concept:

* ID, title and concise description;
* lifecycle, knowledge state, trust tier and staleness signal;
* owner and independent reviewer role;
* goal/KGI/initiative links;
* cited source resources that must be opened for consequential use.

It also states that the output is a generated projection, not authority or an execution instruction. Missing required context becomes an explicit `needs_resolution` condition.

# Refresh

Reassemble context at session start, resume, compaction, delegation, source/policy revision change, correction, revocation, detected conflict and work-boundary transition. If inputs and evidence are unchanged, reuse the digest rather than regenerating prose.

# Verification

Assemble a bounded context for `OUT-INTENT` and `INIT-DYNAMIC-AGENT-CONTEXT`, then evaluate the result with [retrieval quality](retrieval-quality.md). A successful repository-level check does not prove runtime activation.
