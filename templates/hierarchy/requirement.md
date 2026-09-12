---
template_kind: requirement
id: "{{REQUIREMENT_ID}}"
parent_ref: "{{PHASE_OR_PROJECT_REF}}"
requirement_type: "{{FUNCTIONAL_NONFUNCTIONAL_OR_CONSTRAINT}}"
priority: "{{PRIORITY}}"
status: draft
owner_role: "{{OWNER_ROLE}}"
effort: "{{EFFORT_CLASS}}"
blocking: false
created_at: "{{ISO8601}}"
updated_at: "{{ISO8601}}"
---

# {{REQUIREMENT_TITLE}}

## Need

{{TESTABLE_NEED}}

## Background

{{WHY_THIS_IS_NEEDED}}

## Boundary

### In scope

- {{IN_SCOPE_ITEM}}

### Out of scope

- {{OUT_OF_SCOPE_ITEM}}

## Acceptance criteria

- [ ] {{TESTABLE_ACCEPTANCE_CRITERION}}

## Dependencies

| Reference | Relationship | Reason |
|---|---|---|
| {{REQUIREMENT_REF}} | depends_on | {{REASON}} |

## Verification and evidence

- Verification method: {{VERIFICATION_METHOD}}
- Evidence reference: {{EVIDENCE_REF}}
- Independent reviewer role: {{REVIEWER_ROLE}}

## History and rollback

| Timestamp | Candidate state | Reason | Evidence reference |
|---|---|---|---|
| {{ISO8601}} | draft | initial candidate | {{EVIDENCE_REF}} |

- Rollback reference: {{ROLLBACK_REF}}
- Stop condition: {{STOP_CONDITION}}

Component license: MIT; see `../../LICENSES/MIT.txt`.
