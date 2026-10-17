---
name: kotodama-intent
description: Use only for the Kotodama public repository when turning an ambiguous request into a bounded, non-authorizing intent candidate.
---

# Kotodama intent

## Intent

Make the user's desired outcome explicit before selecting tools, agents, files,
or providers. Preserve the user's words as source evidence and label every
inference as a candidate rather than a decision.

## Triggers

Use when a request is broad, ambiguous, spans several skills, or mixes an
outcome with an implementation idea. Form an intent candidate before selecting
work; reuse confirmed scope and still-valid authorization from the session.

## Non-triggers

Do not use this to approve a Work Order, infer consent, choose a public
destination, or treat a previous conversation or model summary as current
truth. Do not collect secrets or raw private conversation into the candidate.

## Procedure

1. Read the current source, relevant project definitions, and existing work
   before asking the user. Capture purpose, beneficiary, desired outcome,
   constraints, non-goals, and smallest useful scope. Resolve facts from those
   sources; leave choices to their owner. Done when: each field is supported or
   unknown and no question asks for an already available fact.
2. Separate `confirmed`, `proposed`, and `unknown` fields. Preserve source
   locators and revision/time instead of quoting private bodies. Done when:
   every statement has one evidence status and a source locator or gap.
3. Write measurable acceptance criteria, stop conditions, rollback intent, and
   the evidence tier that would be sufficient. Link each criterion to its
   planned check and result. Done when: success and refusal can be evaluated
   without inference and unfinished checks cannot become a completion claim.
4. Ask only material unresolved choices whose prerequisites are known. Include
   a recommended answer and its tradeoff; keep questions within the selected
   runtime's clarification budget. Record confirmed terms, constraints, and
   decisions immediately with source/revision references in the existing
   Intent/Decision owner when the invocation's existing apply scope permits
   that write; in plan mode return the candidate and its owner reference.
   Use an existing decision record for consequential
   tradeoffs, not a second Task or approval ledger. Stop questioning when the
   bounded work can proceed. Done when: blockers have an owner or question,
   confirmed agreements are recorded, and the next authorized action is clear.

## Completion

Return a content-free receipt with `status`, the actual `changed` value, mode,
an input digest,
source references, `evidence_tier=LOCAL`, and `no_go_reasons` for unresolved
authority or scope. `COMPLETED` means the intent candidate is explicit, not
that the work is approved or published. A plan has `changed=false`; an
authorized owner update reports its actual changed state and evidence.

## Recovery

If the request changes, create a new candidate revision and retain the old
revision as superseded. Never overwrite an approved decision with a later
inference.
