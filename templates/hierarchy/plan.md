---
template_kind: plan
id: "{{PLAN_ID}}"
parent_ref: "{{REQUIREMENT_REF}}"
status: draft
owner_role: "{{OWNER_ROLE}}"
created_at: "{{ISO8601}}"
updated_at: "{{ISO8601}}"
---

# {{PLAN_TITLE}}

## Outcome

{{PLAN_OUTCOME}}

## Preconditions

- [ ] {{PRECONDITION}}

## Ordered steps

| # | Action | Owner role | Effect ceiling | Acceptance check |
|---|---|---|---|---|
| 1 | {{BOUNDED_ACTION}} | {{OWNER_ROLE}} | {{MAX_EFFECT}} | {{CHECK_ID}} |

## Dependencies

- Required reference: {{OPAQUE_REF}}
- Required evidence: {{EVIDENCE_REF}}

## Completion criteria

- [ ] {{PLAN_COMPLETION_CRITERION}}

## Stop conditions and rollback

- Stop on: {{STOP_CONDITION}}
- Rollback action: {{ROLLBACK_ACTION}}
- Rollback verification: {{ROLLBACK_CHECK}}

A plan is not authority to apply its steps. Each state-changing action remains
subject to its own approval and evidence boundary.

Component license: MIT; see `../../LICENSES/MIT.txt`.
