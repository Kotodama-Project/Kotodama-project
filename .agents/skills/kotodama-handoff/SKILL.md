---
name: kotodama-handoff
description: Use only for the Kotodama public repository when creating or resuming a redacted handoff bound to exact state and evidence.
---

# Kotodama handoff

## Intent

Make interrupted work resumable without treating a stale summary, model
memory, or previous receipt as current truth.

## Triggers

Use when a task is paused, compacted, transferred, or resumed after a context
boundary.

## Non-triggers

Do not use a handoff to approve work, merge a branch, erase an unresolved
blocker, or copy raw private conversation and credentials into a new session.

## Procedure

1. Record task/intent revision, owner, repository/ref, exact target file list,
   baseline/HEAD digests, completed checks, current status, and unknowns.
   Done when: the handoff names one exact restart fixed point.
2. Separate `done`, `partial`, `blocked`, and `not started`; attach paths,
   line ranges, logs, or URLs rather than broad claims.
   Done when: every work item has one explicit lifecycle status and evidence.
3. State the next safe action, its stop conditions, expiry, rollback locator,
   and the evidence tier it can reach.
   Done when: one bounded next action and all stop conditions are recorded.
4. On resume, re-read current bytes and compare digests before continuing; mark
   stale or missing evidence as `UNKNOWN`.
   Done when: current bytes have been compared and all drift is classified.

## Completion

Return a redacted handoff receipt with source/revision digests, owner, current
status, evidence references, and `MODEL_UNVERIFIED` when runtime identity is
not observed. A handoff is continuity evidence, not completion or approval.

## Recovery

If the handoff conflicts with current files, preserve both records, stop at the
conflict, and create a new candidate revision rather than overwriting history.
