---
name: kotodama-validate
description: Use only for the Kotodama public repository to validate one declared candidate read-only and emit fail-closed receipt fields.
---

# Kotodama validation

## Intent

Determine whether the exact candidate satisfies its declared contract without
repairing it, changing state, contacting a provider, or promoting evidence.

## Triggers

Use after a plan or local change when the target, source revision, acceptance
tests, and validation scope are explicit.

## Non-triggers

Do not use validation as automatic repair, a deployment check, a public smoke
test, or a substitute for human approval. A passing health check is observation
only.

## Procedure

1. Resolve and verify the allowlisted root and target digest; refuse path escape,
   missing ownership, or dirty-baseline ambiguity. Done when: the exact candidate
   and read boundary are fixed.
2. Run only declared read-only checks with bounded bytes, time, recursion, and
   output. Decode text as UTF-8 and report binary or replacement-character
   counts. Done when: every attempted check has an exit or explicit unknown.
3. Record check names, commands or test identifiers, exit codes, timestamps,
   before/after digests, changed/no-op state, and skipped/unknown reasons.
   Done when: the receipt can reproduce the declared validation boundary.
4. Keep evidence at the tier actually observed; do not infer `DEVICE`,
   `PROVIDER`, `PUBLIC`, or `HUMAN_GO` from local output. Done when: every
   missing higher gate is listed in `no_go_reasons`.

## Completion

Return `COMPLETED`, `PARTIAL`, `BLOCKED`, `FAILED`, or `UNKNOWN` with the
standard receipt shape. A successful local validator has
`evidence_tier=LOCAL` and explicit `no_go_reasons` for every higher missing
gate.

## Recovery

If a check mutates files or external state unexpectedly, stop, preserve the
pre-state, classify the result as `UNKNOWN`, and record the boundary failure.
