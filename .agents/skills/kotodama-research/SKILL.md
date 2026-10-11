---
name: kotodama-research
description: Use only for the Kotodama public repository when current primary-source research must update a bounded project claim.
---

# Kotodama research

## Intent

Replace remembered or stale guidance with current primary-source evidence while
keeping facts, inferences, proposals, and unknowns separate.

## Triggers

Use when a specification, runtime behavior, model option, security rule, or
provider contract may have changed or when the user requests current evidence.

## Non-triggers

Do not use research to make a provider write, publish a repository, install a
dependency, or turn a health response into a production claim. Do not copy
private source bodies, credentials, or personal identifiers into notes.

## Procedure

1. State the question, date window, allowed sources, and excluded actions.
   Read existing claim/source references first. Reuse evidence whose revision,
   access scope, and freshness still cover the question; recheck changed or
   unsupported claims. Done when: the boundary is answerable and time-bounded,
   and each reused source has a stated freshness basis.
2. Prefer official documentation, source code, standards, and the selected
   repository's current bytes. Record URL/path, revision, accessed time, and
   content digest for each claim. Done when: every factual claim has provenance.
3. Label `FACT`, `INFERENCE`, `PROPOSAL`, and `UNKNOWN`; record contradictions
   and stale-source risk instead of averaging them away. Done when: conflicting
   evidence and freshness gaps remain visible.
4. Return the claim-to-source mapping and recommendation for the existing
   knowledge or work owner, including gaps and superseded claims. Persist it
   only within the invocation's already authorized apply scope; a plan returns
   the candidate and owner reference without writing. End with the
   smallest local next step and the evidence tier it can reach. Done when: a
   later reader can recover the evidence without redoing the investigation,
   and the recommendation cannot imply an unauthorized external effect.

## Completion

Return a claim table and content-free receipt with source references,
`MODEL_UNVERIFIED` when runtime identity is unavailable, and
`evidence_tier=LOCAL`, mode, and the actual `changed` value. Plans report
`changed=false`; permitted owner writes include their evidence reference.
No external mutation is part of completion.

## Recovery

If a source disappears or contradicts the current checkout, mark the claim
`UNKNOWN`, preserve the old citation as historical, and stop promotion.
