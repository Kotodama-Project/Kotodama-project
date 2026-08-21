# Project Status

Current state checked: 2026-08-21  
Published fixed point: `main@be71f424689648b3ab1b1db15adbaddea374586b`

This file answers **what is true now** for the public repository. It is not a deployment, Promotion, Current Truth, Final Human GO, or Public Beta receipt. The detailed R179-and-earlier revision record is preserved in [the historical status snapshot](docs/history/STATUS-R179-AND-EARLIER.md).

## Current public state

| Surface | Exact state | Required next gate |
|---|---|---|
| Published `main` | Incomplete Public Preview at `be71f424689648b3ab1b1db15adbaddea374586b`; `read-only/candidate-only` | Do not treat open PR content as published |
| Publication and governance baseline | Draft PR #18 at `ec76f48d2623476e6433ec8673d2586ee51f9aa1`; exact-head README smoke, runtime-candidate checks, immutable-Action validation, dependency review, 513 tests, and clean-tree check passed | Complete issue #19 control-plane readback, obtain independent latest-push review, and record the repository owner's Apache-2.0 decision |
| Public skill operating contract | Draft PR #17 at `704ced6a4b8be6465849646c7d2c1ba95f4fd7af`; based on the old published `main` | Rebase after the accepted governance baseline, rerun neutral checks, and obtain independent review |
| Cloudflare candidate | Draft PR #1 at `4963801bd17deee30623171199a54c6c8ee9e5c3`; scope-specific hosted validation exists | Keep Cloudflare evidence scope-specific; reconcile only after neutral repository gates |
| `main` protection | Protected for everyone, but the sole required context is `Trusted Cloudflare candidate validation` | Rebind generic repository checks and read back the final rule under issue #19 |
| Runtime, Voice, and Discord | No supported public production runtime, public Voice Bot, or public Discord invite is published | Exact scope-matched runtime, privacy, security, rollback, and independent evidence plus Final Human GO |
| Public Beta | `NO_GO_UNPUBLISHED` | Remains blocked |

A private Voice runtime cutover attempt is not public runtime evidence and does not authorize a public Voice surface.

## Evidence lanes

| Lane | What is currently available | What is still missing |
|---|---|---|
| Code evidence | Published preview plus exact candidate commits and deterministic validators | Accepted integration fixed point |
| Hosted evidence | PR #18 neutral validation and dependency review passed on its exact head; PR #1 has Cloudflare-specific validation | Neutral required-check binding on `main`, then exact-head reruns after reconciliation |
| Admin evidence | Public branch readback confirms protection and the current required context | Sanitized readback for final branch/ruleset, CodeQL, vulnerability reporting, dependency alerts, secret scanning, and push protection |
| Human evidence | No independent latest-push approval and no Final Human GO are represented here | Independent review, explicit Apache-2.0 owner decision, provider/runtime decisions, and Final Human GO |

A passing candidate-owned workflow is hosted evidence, not independent human approval.

## Safe integration order

1. Keep PR #18 Draft while its exact-head evidence remains bound to `ec76f48d2623476e6433ec8673d2586ee51f9aa1`.
2. Complete and read back issue #19 controls; obtain independent latest-push review and the explicit Apache-2.0 owner decision.
3. Merge PR #18 only if those gates pass; no merge is authorized by this document.
4. Rebase PR #17 onto the accepted baseline, resolve overlaps, rerun all neutral checks, and obtain independent review.
5. Reconcile PR #1 after the neutral baseline; retain its Cloudflare checks as scope-specific evidence.
6. Produce clean-install, migration, restart, rollback/restore, privacy, and provider evidence for any proposed runtime or Voice surface.
7. Perform independent reconciliation and Final Human GO before any limited Public Beta decision.

## Current entry points

- [README](README.md)
- [Roadmap](ROADMAP.md)
- [Company Pack Catalog](docs/COMPANY-PACK-CATALOG.md)
- [Company Pack Guided Next Steps](docs/COMPANY-PACK-NEXT-STEPS.md)
- [Schema / Validator / Test Matrix](docs/SCHEMA-VALIDATOR-MATRIX.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)
- [Support](SUPPORT.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Governance control-plane issue #19](https://github.com/Kotodama-Project/Kotodama-project/issues/19)
- [Current-state synchronization issue #20](https://github.com/Kotodama-Project/Kotodama-project/issues/20)

## Boundary

This public repository remains an incomplete preview. It does not publish credentials, private host identifiers, raw conversations, personal data, deployment authority, provider authority, billing authority, Promotion, Current Truth, Final Human GO, or Public Beta access. Every candidate remains `read-only/candidate-only` and `NO_GO_UNPUBLISHED` until its own evidence and human gates are satisfied.
