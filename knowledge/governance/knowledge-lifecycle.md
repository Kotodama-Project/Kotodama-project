---
type: Knowledge Lifecycle
title: Knowledge lifecycle and invalidation
description: Define how source-backed concepts move through candidate, confirmation, conflict, staleness, deprecation and revocation without rewriting source history.
tags: [governance, lifecycle, provenance, freshness, conflict]
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
  - id: okf-spec
    resource: https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md
    title: Open Knowledge Format specification v0.2
    author: team:google-cloud-platform
kotodama:
  profile: "0.1"
  id: governance/knowledge-lifecycle
  classification: public_candidate
  authority: projection_only
  knowledge_state: candidate
  owner_role: AI-LIBRARIAN
  reviewer_role: AI-AUDITOR
  context_priority: 10
  goal_refs: [OUT-INTENT, OUT-LOCAL]
  kgi_refs: [KGI-INTENT]
  initiative_refs: [INIT-KNOWLEDGE-FORMAT, INIT-KNOWLEDGE-REFRESH]
  agent_use:
    discoverable: true
    answer_mode: source_required
    decision_authority: false
    runtime_authority: false
---

# Two separate state axes

OKF `status` describes the document lifecycle: `draft`, `stable` or `deprecated`. Kotodama's `knowledge_state` describes epistemic handling:

| Knowledge state | Handling |
|---|---|
| `candidate` | Source-backed proposal awaiting independent verification or owner promotion |
| `confirmed` | Independently verified against cited sources; still a projection |
| `conflicted` | Credible sources or revisions disagree; consumers must surface the conflict |
| `unknown` | Required evidence or relationship is missing; do not infer a value |
| `deprecated` | Retained for links/history but not current |
| `revoked` | Source access, consent or authority was revoked; exclude from generated context |

# Required transition evidence

```text
source observation
  -> candidate concept
  -> independent verification or explicit conflict
  -> owner-controlled promotion outside this bundle, when applicable
  -> refresh, deprecation or revocation when dependencies change
```

Every meaningful content change updates `generated.at`. Verification events are separate and must identify a different actor. `stale_after` is a review trigger: staleness does not prove falsehood, but stale critical knowledge is excluded from decision-ready context until reviewed.

# Invalidation

A source correction, replacement, deletion, access revocation or changed governing decision triggers impact analysis. Affected concepts are marked stale, conflicted, deprecated or revoked before derived indexes/context are rebuilt. Original sources and prior Git history remain available according to their owning retention policy; this bundle does not rewrite history.

# No embedding authority

Embeddings and vector indexes may assist retrieval, but they are replaceable projections. They are not reversible source archives, do not carry permission by themselves, and cannot override ancestor context or explicit constraints. The current slice uses deterministic lexical and graph projections first; any semantic retriever must pass the evaluation in [retrieval quality](../operations/retrieval-quality.md).

See the operational [refresh loop](../operations/refresh-loop.md).
