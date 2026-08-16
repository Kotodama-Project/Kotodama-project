---
name: kotodama-implement
description: Apply an approved, bounded Kotodama local change with a clean baseline, atomic writes, focused tests, and a rollback-bound receipt.
---

# Kotodama implementation

## Intent

Make the smallest reversible local change that satisfies an approved plan,
while preserving unrelated user work and leaving a clear verification trail.

## Triggers

Use only when the candidate, owner, target revision, acceptance tests, effect
ceiling, and required approval are already explicit.

## Non-triggers

Do not use for vague requests, direct public/main pushes, provider actions,
credential rotation, deletion, or a dirty target whose ownership cannot be
separated. Do not hide partial work behind “single pass” language.

## Procedure

1. Re-read the plan and compare the target digest and dirty baseline; stop on
   drift.
2. Work only inside the allowlisted scope. Use UTF-8, atomic replacement,
   backup/pre-state digest, and an exclusive lock where concurrent writers are
   possible.
3. Run focused tests and static checks, capture the exact diff and effect count,
   and classify incomplete work as `PARTIAL` or `BLOCKED`.
4. Leave public/provider/promotion actions for their own Work Order and
   evidence gates.

## Completion

Return a receipt with before/after digests, changed/no-op, test exit codes,
rollback locator, and `evidence_tier=LOCAL`. Completion means the declared
local acceptance criteria passed; it does not mean merge, release, or GO.

## Recovery

On failure, stop at the last safe boundary, keep the backup and refusal
receipt, and roll back only the exact candidate if the Work Order permits it.
