---
id: WORK-ORDER-EXAMPLE
kind: work_order_block
version: 0.1.0
status: example
owner_role: HUMAN_OWNER
expires_at: YYYY-MM-DDTHH:MM:SSZ
---

# Work Order Block

## Purpose

何を達成するための作業かを一文で書く。

## Inputs

- source reference:
- candidate revision or digest:
- decision reference:

## Authorized actions

- exact action:
- exact target:
- allowed data class:

## Denied actions

- credential or permission change
- unbound external write
- destructive deletion without rollback
- self-approval or self-promotion

## Expected outputs

- change candidate:
- verification receipt:
- human-facing summary:

## Verification

- success condition:
- negative test:
- independent check:

## Rollback

- rollback action:
- rollback verification:

## Stop conditions

- source or candidate drift
- authority expiry
- unexpected external effect
- verification mismatch

## Promotion boundary

このBlockの完了は、PromotionまたはCurrent Truth変更を自動的に意味しない。
