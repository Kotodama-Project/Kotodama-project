---
type: Operational Playbook
title: Source-to-knowledge refresh loop
description: Refresh only affected public-safe concepts and projections after a source, policy, intent, access or dependency change, then independently review and read back the result.
tags: [operations, refresh, ingestion, invalidation, audit]
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
  - id: information-access
    resource: ../../docs/INFORMATION-ACCESS.md
    title: Information classification and reader management
    author: team:kotodama-project
kotodama:
  profile: "0.1"
  id: operations/refresh-loop
  classification: public_candidate
  authority: projection_only
  knowledge_state: candidate
  owner_role: AI-LIBRARIAN
  reviewer_role: AI-AUDITOR
  context_priority: 15
  goal_refs: [OUT-INTENT, OUT-LOCAL]
  kgi_refs: [KGI-INTENT]
  initiative_refs: [INIT-KNOWLEDGE-REFRESH, INIT-CONTEXT-AUDIT, INIT-DYNAMIC-AGENT-CONTEXT]
  agent_use:
    discoverable: true
    answer_mode: source_required
    decision_authority: false
    runtime_authority: false
---

# Trigger

Run impact analysis when a cited source revision changes, intent is corrected or withdrawn, a governing decision changes, access is revoked, a dependency moves, a conflict is detected, or a concept reaches `stale_after`.

# Bounded flow

1. **Resolve authority and access**: identify the owning source, exact revision, classification and permitted reader/reviewer before content is read.
2. **Compute impact**: traverse provenance, concept links, goal/KGI/initiative edges and generated-context dependencies.
3. **Quarantine first**: mark affected projections stale, conflicted, deprecated or revoked before they can be selected as ready context.
4. **Rebuild candidates**: update only affected concepts; retain unchanged files and source history.
5. **Regenerate projections**: build catalog and graph from current files. Embeddings, if later enabled, are rebuilt as non-authoritative indexes.
6. **Independent review**: a runtime actor distinct from the writer checks source fidelity, omitted constraints, classification and proposed lifecycle state.
7. **Readback**: query the updated bundle and assemble representative context to confirm that the changed fact appears and superseded content does not.
8. **Record disposition**: continue, revise, experiment, change approach or stop, with evidence and owner follow-up.

# Commands in this repository slice

```bash
python tools/knowledge_base.py validate --root .
python tools/knowledge_base.py build --root . --check
python tools/knowledge_base.py audit --root . --format markdown
python tools/knowledge_base.py query --root . "更新 失効"
python tools/knowledge_base.py context --root . --initiative INIT-KNOWLEDGE-REFRESH
```

These commands inspect the repository projection only. They do not fetch private sources, change access policy, promote Current Truth or claim that the runtime scheduler exists.

# Rollback

Revert the candidate concept and regenerated projections to the last reviewed Git revision, preserve the failed attempt and audit finding, then repair the source binding or method. A rollback does not restore revoked access or consent.

See [knowledge lifecycle](../governance/knowledge-lifecycle.md) and [agent responsibilities](../governance/agent-responsibilities.md).
