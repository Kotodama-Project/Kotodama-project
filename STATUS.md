# Project Status

Current state checked: 2026-08-21  
Published fixed point: `main@be71f424689648b3ab1b1db15adbaddea374586b`

This file answers **what is true now** for the public repository. It is not a deployment, Promotion, Current Truth, Final Human GO, or Public Beta receipt. If published `main` or any active candidate head changes, this dated snapshot is stale and must be refreshed before it is used for integration or merge decisions. The detailed R179-and-earlier revision record is preserved in [the historical status snapshot](docs/history/STATUS-R179-AND-EARLIER.md).

## Current public state

| Surface | Exact state | Required next gate |
|---|---|---|
| Published `main` | Incomplete Public Preview at `be71f424689648b3ab1b1db15adbaddea374586b`; `read-only/candidate-only` | Do not treat open PR content as published |
| Publication and governance baseline | Draft PR #18 at `fbb6da377edd2b726a854912eb17c964a1ec01e9`; Repository validation run `32488194816` and Dependency review run `32488194768` passed on that exact head. README smoke, three runtime-candidate validators, immutable-Action validation, tracked credential hygiene over the current Git-tracked tree, 529 tests, and clean-tree refusal succeeded | Complete issue #19 control-plane readback, obtain independent latest-push review, and record the repository owner's Apache-2.0 decision |
| BecomeOne migration SSOT | Public [issue #24](https://github.com/Kotodama-Project/Kotodama-project/issues/24) coordinates an allowlist-only, no-history dual-repository migration; no batch, repository rename, or archive is accepted yet | Classify and receipt every item, prove zero unclassified items and zero residual consumers, then verify pinned one-way dependency, compatibility, canary, and rollback evidence |
| Public skill operating contract | Draft PR #17 at `704ced6a4b8be6465849646c7d2c1ba95f4fd7af`; based on the old published `main` | Rebase after the accepted governance baseline, rerun neutral checks, and obtain independent review |
| Cloudflare candidate | Draft PR #1 at `83e7b9e0789f941f993fd2c43a938dd872b12581`; scope-specific validation run `32488235678` passed | Keep Cloudflare evidence scope-specific; reconcile only after neutral repository gates |
| `main` protection | Protected for everyone, but the sole required context is `Trusted Cloudflare candidate validation` | Rebind generic repository checks and read back the final rule under issue #19 |
| Runtime, Voice, and Discord | No supported public production runtime, public Voice Bot, or public Discord invite is published | Exact scope-matched runtime, privacy, security, rollback, and independent evidence plus Final Human GO |
| Public Beta | `NO_GO_UNPUBLISHED` | Remains blocked |

A private Voice runtime cutover attempt is not public runtime evidence and does not authorize a public Voice surface.

## Evidence lanes

| Lane | What is currently available | What is still missing |
|---|---|---|
| Code evidence / Local evidence | Published preview plus exact candidate commits, deterministic validators, negative tests, and a current-tree tracked credential gate | Accepted integration fixed point; historical and provider-side credential evidence |
| Hosted evidence | PR #18 Repository validation run `32488194816` and Dependency review run `32488194768` passed on exact head `fbb6da377edd2b726a854912eb17c964a1ec01e9`; PR #1 Cloudflare validation run `32488235678` passed on exact head `83e7b9e0789f941f993fd2c43a938dd872b12581` | Neutral required-check binding on `main`, then exact-head reruns after reconciliation |
| Admin evidence | Public branch readback confirms protection and the current required context | Sanitized readback for final branch/ruleset, CodeQL, vulnerability reporting, dependency alerts, secret scanning, push protection, and provider secret state |
| Human evidence | No independent latest-push approval and no Final Human GO are represented here | Independent review, explicit Apache-2.0 owner decision, provider/runtime decisions, and Final Human GO |

A passing candidate-owned workflow is hosted evidence, not independent human approval.

## Credential evidence boundary

`python -S -B tools/check_tracked_secret_hygiene.py` deterministically scans the current Git-tracked tree and does not print detected values. It does not scan Git history, untracked files, forks, GitHub or provider secret stores, or security settings. A pass is current-tree code evidence only. Any credential that may previously have been committed must be revoked or rotated first and handled through separately reviewed history remediation.

## Safe integration order

1. Keep PR #18 Draft while its exact-head evidence remains bound to `fbb6da377edd2b726a854912eb17c964a1ec01e9`.
2. Complete and read back issue #19 controls; obtain independent latest-push review and the explicit Apache-2.0 owner decision.
3. Merge PR #18 only if those gates pass; no merge is authorized by this document.
4. Merge the operational status/roadmap change only after PR #18, rerun its exact-head checks, and preserve the historical snapshots byte-for-byte.
5. Run issue #24 migration batches from one canonical ledger: allowlist-only, no-history public extracts; private retention or regeneration for everything else; immutable receipts; and no rename or archive until zero unclassified items and zero residual consumers are proven.
6. Rebase PR #17 onto the accepted baseline, resolve overlaps, rerun all neutral checks, and obtain independent review.
7. Reconcile PR #1 after the neutral baseline; retain its Cloudflare checks as scope-specific evidence.
8. Produce clean-install, migration, restart, rollback/restore, privacy, and provider evidence for any proposed runtime or Voice surface.
9. Perform independent reconciliation and Final Human GO before any limited Public Beta decision.

## Current entry points

- [README](README.md)
- [Roadmap](ROADMAP.md)
- [Company Pack Catalog](docs/COMPANY-PACK-CATALOG.md)
- [Company Pack Guided Next Steps](docs/COMPANY-PACK-NEXT-STEPS.md)
- [Schema / Validator / Test Matrix](docs/SCHEMA-VALIDATOR-MATRIX.md)
- [Public Preview Self-check](docs/PUBLIC-PREVIEW-SELF-CHECK.md): `python -S -B tools/check_company_pack_public_preview.py examples/company-starter --format markdown`
- [Source Binding Verifier Candidate](docs/SOURCE-BINDING-VERIFIER-CANDIDATE.md)
- [Protected Source Binding Receipt Candidate](docs/PROTECTED-SOURCE-BINDING-RECEIPT-CANDIDATE.md)
- [Protected Execution Request Handoff Candidate](docs/PROTECTED-EXECUTION-REQUEST-HANDOFF-CANDIDATE.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)
- [Support](SUPPORT.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Governance control-plane issue #19](https://github.com/Kotodama-Project/Kotodama-project/issues/19)
- [Current-state synchronization issue #20](https://github.com/Kotodama-Project/Kotodama-project/issues/20)
- [BecomeOne migration SSOT issue #24](https://github.com/Kotodama-Project/Kotodama-project/issues/24)

## Boundary

This public repository remains an incomplete preview. It does not publish credentials, private host identifiers, raw conversations, personal data, deployment authority, provider authority, billing authority, Promotion, Current Truth, Final Human GO, or Public Beta access. Every candidate remains `read-only/candidate-only` and `NO_GO_UNPUBLISHED` until its own evidence and human gates are satisfied.
