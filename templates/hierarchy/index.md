---
template_kind: hierarchy_index
status: draft
owner_role: "{{OWNER_ROLE}}"
updated_at: "{{ISO8601}}"
---

# {{INDEX_TITLE}}

## Purpose

{{ONE_SENTENCE_PURPOSE}}

## Canonical entries

| Artifact | Canonical reference | Status | Owner role | Evidence reference |
|---|---|---|---|---|
| {{ARTIFACT_NAME}} | {{OPAQUE_REFERENCE}} | draft | {{OWNER_ROLE}} | {{EVIDENCE_REF}} |

## Change boundary

- Allowed without wider effect: {{LOCAL_READ_OR_DRAFT_ACTION}}
- Separate approval required: {{STATE_CHANGING_ACTION}}
- Prohibited: credentials, personal data, private endpoints, or unbound
  external writes.

## Validation and rollback

- Validation: {{VALIDATION_COMMAND_OR_CHECK_ID}}
- Rollback reference: {{ROLLBACK_REF}}
- Stop condition: {{STOP_CONDITION}}

## Projection rule

This index is navigation only. It must be regenerated or updated from the
canonical artifacts and cannot approve, promote, or overwrite them.

Component license: MIT; see `../../LICENSES/MIT.txt`.
