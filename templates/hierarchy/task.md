---
template_kind: task
id: "{{TASK_ID}}"
parent_ref: "{{PLAN_REF}}"
session_ref: "{{SESSION_REF}}"
intent_ref: "{{INTENT_REF}}"
status: draft
owner_role: "{{OWNER_ROLE}}"
created_at: "{{ISO8601}}"
updated_at: "{{ISO8601}}"
---

# {{TASK_TITLE}}

## Outcome

{{ONE_BOUNDED_TASK_OUTCOME}}

## Authorized scope

### In scope

- {{ALLOWED_TARGET_OR_ACTION}}

### Out of scope

- {{DENIED_TARGET_OR_ACTION}}

## Acceptance criteria

- [ ] {{TASK_ACCEPTANCE_CRITERION}}

## Context references

- Mandatory reference: {{OPAQUE_CONTEXT_REF}}
- Related reference: {{OPAQUE_RELATED_REF}}

References must be opaque locators or digests. Do not embed private source
bodies, transcripts, credentials, endpoints, or operational logs.

## Evidence and validation

- Validation check: {{CHECK_ID}}
- Evidence reference: {{EVIDENCE_REF}}
- Independent reviewer role: {{REVIEWER_ROLE}}

## Work log

| Timestamp | Candidate state | Summary | Evidence reference |
|---|---|---|---|
| {{ISO8601}} | draft | {{SUMMARY}} | {{EVIDENCE_REF}} |

## Stop conditions and rollback

- Stop on: {{STOP_CONDITION}}
- Rollback reference: {{ROLLBACK_REF}}
- Rollback verification: {{ROLLBACK_CHECK}}

## Handoff

- Current status: draft
- Next safe action: {{NEXT_SAFE_ACTION}}
- Unresolved blocker: {{BLOCKER_OR_NONE}}

Task completion does not approve its parent plan, requirement, phase, or
project.

Component license: MIT; see `../../LICENSES/MIT.txt`.
