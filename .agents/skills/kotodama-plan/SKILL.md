---
name: kotodama-plan
description: Build a bounded Kotodama plan or dry-run from an intent candidate, including ownership, acceptance, rollback, and explicit stop conditions.
---

# Kotodama plan

## Intent

Turn an intent candidate into an ordered, reviewable change plan without
performing the change. Make the target, effect ceiling, and evidence needed
for each step visible.

## Triggers

Use before implementation, public review, multi-agent delegation, or any
operation that could touch files, credentials, providers, or external users.

## Non-triggers

Do not use a plan as an approval, a deployment, a rollback execution, or proof
that a provider or public route works. Do not invent a command for a runtime
that is not present in the selected checkout.

## Procedure

1. Bind the plan to an intent revision, repository/ref, target paths, owner,
   dirty baseline, and source digests.
2. Select `plan` or `dry-run`; enumerate reads, writes, network calls, sends,
   and expected effect counts separately.
3. Define acceptance tests, no-op behavior, timeout, retry/cancel policy,
   backup/pre-state, rollback locator, and terminal states.
4. Mark every promotion boundary (`LOCAL`, `DEVICE`, `PROVIDER`, `PUBLIC`,
   `HUMAN_GO`) and list the receipt required to cross it.

## Completion

Return the ordered plan, ownership map, risk/stop list, and a receipt with
`changed=false`. A plan is `COMPLETED` only when its inputs and acceptance
criteria are bound; apply remains blocked until the required approval exists.

## Recovery

If the target digest or dirty baseline changes, invalidate the plan and create a
new revision. Never apply a stale plan by adjusting its prose in place.
