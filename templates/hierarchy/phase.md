---
template_kind: phase
id: "{{PHASE_ID}}"
parent_ref: "{{PROJECT_REF}}"
status: draft
owner_role: "{{OWNER_ROLE}}"
created_at: "{{ISO8601}}"
updated_at: "{{ISO8601}}"
---

# {{PHASE_TITLE}}

## Outcome

{{MEASURABLE_PHASE_OUTCOME}}

## Entry criteria

- [ ] {{ENTRY_CRITERION}}

## Exit criteria

- [ ] {{EXIT_CRITERION}}

## Boundary

### In scope

- {{IN_SCOPE_ITEM}}

### Non-goals

- {{NON_GOAL}}

## Requirements and deliverables

| Reference | Kind | Expected result | Status |
|---|---|---|---|
| {{CHILD_REF}} | requirement | {{EXPECTED_RESULT}} | draft |

## Evidence and rollback

- Verification: {{VERIFICATION_REF}}
- Rollback reference: {{ROLLBACK_REF}}
- Stop condition: {{STOP_CONDITION}}

Meeting exit criteria produces a review candidate, not automatic promotion.

Component license: MIT; see `../../LICENSES/MIT.txt`.
