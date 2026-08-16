---
name: kotodama-intent
description: Turn a natural-language request into a bounded Kotodama intent candidate with explicit beneficiaries, non-goals, scope, and stop conditions.
---

# Kotodama intent

## Intent

Make the user's desired outcome explicit before selecting tools, agents, files,
or providers. Preserve the user's words as source evidence and label every
inference as a candidate rather than a decision.

## Triggers

Use when a request is broad, ambiguous, spans several skills, or mixes an
outcome with an implementation idea. Ask for an intent candidate before a
state-changing workflow begins.

## Non-triggers

Do not use this to approve a Work Order, infer consent, choose a public
destination, or treat a previous conversation or model summary as current
truth. Do not collect secrets or raw private conversation into the candidate.

## Procedure

1. Capture purpose, beneficiary, desired outcome, constraints, non-goals, and
   the smallest useful scope.
2. Separate `confirmed`, `proposed`, and `unknown` fields. Preserve source
   locators and revision/time instead of quoting private bodies.
3. Write measurable acceptance criteria, stop conditions, rollback intent, and
   the evidence tier that would be sufficient.
4. Identify missing decisions and return one bounded clarification list; do not
   silently expand scope.

## Completion

Return a content-free receipt with `status`, `changed=false`, an input digest,
source references, `evidence_tier=LOCAL`, and `no_go_reasons` for unresolved
authority or scope. `COMPLETED` means the intent candidate is explicit, not
that the work is approved or published.

## Recovery

If the request changes, create a new candidate revision and retain the old
revision as superseded. Never overwrite an approved decision with a later
inference.
