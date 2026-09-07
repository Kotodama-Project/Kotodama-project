---
type: Project Goal
title: Kotodama project goal
description: Connect authorized conversation to reviewed intent, bounded work, evidence, outcomes and organizational learning inside an operator-controlled trust boundary.
tags: [goal, intent, company-os, local-first]
status: draft
stale_after: 2026-12-07T00:00:00Z
generated: { by: kotodama-kb/bootstrap-v1, at: 2026-09-07T04:00:00Z }
sources:
  - id: readme-goal
    resource: ../../README.md
    title: Kotodama README
    author: team:kotodama-project
  - id: owner-intent
    resource: ../../docs/OWNER-INTENT-COMPANY-AGI.md
    title: Company AGI direction
    author: team:kotodama-project
  - id: project-map
    resource: ../../docs/PROJECT-MAP.md
    title: Project map
    author: team:kotodama-project
kotodama:
  profile: "0.1"
  id: project/goal
  classification: public_candidate
  authority: projection_only
  knowledge_state: candidate
  owner_role: AI-CHIEF
  reviewer_role: AI-AUDITOR
  context_priority: 10
  goal_refs: [OUT-INTENT, OUT-LOCAL]
  kgi_refs: [KGI-INTENT]
  initiative_refs: []
  agent_use:
    discoverable: true
    answer_mode: source_required
    decision_authority: false
    runtime_authority: false
---

# Outcome

Kotodama aims to make an authorized conversation traceable through reviewed intent, bounded work, candidate artifacts, evidence, outcomes and learning rather than stopping at a chat summary.[^readme-goal] The intended operating boundary is local-first and controlled by the operator; repository artifacts alone do not prove that runtime is deployed.[^owner-intent]

# Required properties

* Preserve the original requested outcome and its correction chain.
* Keep source, decision, work, evidence, promotion and Current Truth distinct.
* Make the current position, responsible owner, constraints, unknowns and next action recoverable.
* Let humans and agents navigate the same public-safe knowledge without turning generated prose into authority.

# Non-goals of this bundle

This bundle does not create a second Company truth store, grant access, activate agents, approve publication, or prove a live deployment. See [authority boundaries](../governance/authority-boundaries.md) and the freshness-bounded [current state](current-state.md).

[^readme-goal]: Kotodama README and project map.
[^owner-intent]: Company AGI direction.
