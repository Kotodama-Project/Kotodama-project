---
name: kotodama-public-review
description: Review a Kotodama candidate for public readiness while keeping local, device, provider, public, and human-go evidence strictly separate.
---

# Kotodama public review

## Intent

Make a public candidate reviewable without mistaking local quality, static
documentation, synthetic fixtures, or HTTP health for public availability or
approval.

## Triggers

Use when preparing a public repository branch, draft pull request, release
candidate, or evidence bundle.

## Non-triggers

Do not use this to merge, push `main`, change repository visibility, deploy a
provider, invite users, send a message, or grant `HUMAN_GO`. Those effects need
their own candidate-bound Work Order.

## Procedure

1. Bind the candidate to repository, branch/ref, exact tree digest, file list,
   license/privacy review, and rollback owner.
2. Run local structural/tests and secret/PII scans; record failures rather
   than filtering them out. Keep private runtime, credentials, raw transcripts,
   and host-specific commands outside the public candidate.
3. Use a draft PR or equivalent review surface. Record provider/public checks
   only when an independent receipt actually observed them.
4. State every missing gate and retain `NO_GO_UNPUBLISHED` until the exact
   candidate has technical evidence and an identified human decision.

## Completion

Return a candidate-bound review receipt with changed/no-op, tree digest,
evidence tier, test logs, privacy result, rollback locator, and explicit
`no_go_reasons`. A draft PR is a review artifact, not Public Beta access.

## Recovery

Close or withdraw only the exact candidate branch/PR on request. Never rewrite
unrelated branches or the default branch as a cleanup shortcut.
