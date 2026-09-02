---
name: kotodama-delegate
description: Use only for the Kotodama public repository to decompose independent work into bounded agent lanes with explicit ownership and receipts.
---

# Kotodama delegation

## Intent

Use parallel agents for independent evidence or implementation slices without
turning delegation into an authorization shortcut or a source of hidden work.

## Triggers

Use when the task has independent, reviewable lanes and the parent can define
exact read/write boundaries and acceptance tests for each lane.

## Non-triggers

Do not delegate an unbounded brainstorm, a shared-checkout write race, a
credential/public action, or a task whose target and owner are unknown. Do not
infer a child model from a task name, nickname, or static configuration.

## Procedure

1. Create a stable parent-to-child edge ID and record child owner, target paths,
   read/write mode, maximum depth, cumulative fan-out budget, timeout, and
   retry/cancel policy. Done when: every child edge has all required bounds.
2. Default children to read-only isolated artifacts. Give each writer an
   exclusive lane or worktree; never let two children edit the same file.
   Done when: each writable path has exactly one recorded owner.
3. Confirm the callable runtime schema before spawning. Record observed model
   metadata or `MODEL_UNVERIFIED`; never auto-fallback to an unrequested model.
   Done when: runtime identity is observed or explicitly marked unverified.
4. Require each child to return the same receipt shape, acceptance result, and
   unresolved risks. Aggregate failures as `PARTIAL` or `BLOCKED`.
   Done when: every started child has a receipt or an explicit missing status.

## Completion

The parent receipt includes the edge graph, fan-out/depth usage, child statuses,
retry counts, artifact locators, and acceptance evidence. “All green” is not
valid when a child is missing, timed out, or unknown.

## Recovery

Cancel a child on scope drift or lease expiry. Keep its last artifact and
receipt; do not silently rerun against a changed target.
