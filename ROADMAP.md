# Roadmap to Public Beta

Current roadmap checked: 2026-08-21  
Published fixed point: `main@be71f424689648b3ab1b1db15adbaddea374586b`

This roadmap describes the **safe order of work from the current public state**. It is not a release plan or authorization. The detailed R179-and-earlier revision record is preserved in [the historical roadmap snapshot](docs/history/ROADMAP-R179-AND-EARLIER.md). See [STATUS.md](STATUS.md) for the current truth summary.

## Exact active candidates

| Candidate | Exact head | Current role |
|---|---|---|
| PR #18 | `ec76f48d2623476e6433ec8673d2586ee51f9aa1` | Publication, license, policy, neutral CI, and dependency baseline |
| PR #17 | `704ced6a4b8be6465849646c7d2c1ba95f4fd7af` | Bounded public skill operating contract |
| PR #1 | `4963801bd17deee30623171199a54c6c8ee9e5c3` | Cloudflare edge and official OS integration candidate |

All three remain Draft, `read-only/candidate-only`, and `NO_GO_UNPUBLISHED`.

## Safe integration order

1. **Validate PR #18 exactly.** Keep the README smoke, three runtime-candidate validators, immutable GitHub Action references, dependency review, full tests, and clean-tree refusal green on `ec76f48d2623476e6433ec8673d2586ee51f9aa1`.
2. **Complete issue #19.** Replace the Cloudflare-only generic required-check binding with neutral repository checks, configure review/force-push/deletion controls, inspect security settings, and record a sanitized readback.
3. **Complete human gates for PR #18.** Obtain independent approval of the latest push and an explicit repository-owner decision accepting Apache-2.0. Merge only after all gates pass.
4. **Rebase and validate PR #17.** Resolve overlapping review-chain files against the accepted baseline; rerun neutral hosted checks and the public-skill audit; obtain independent review.
5. **Reconcile and validate PR #1.** Retain Cloudflare-specific checks without making them the generic repository gate; resolve dependency, provenance, privacy, billing, provider, and production-boundary issues.
6. **Prove runtime lifecycle.** Bind clean install, migration, health, restart, rollback, backup, and restore evidence to one exact candidate and environment.
7. **Prove Voice and privacy boundaries.** Bind consent, participant notification, speaker attribution, retention/deletion, access control, error handling, and rollback evidence. A private Voice runtime cutover attempt is not public runtime evidence.
8. **Reconcile independently.** Separate builder, verifier, administrator, and human decision roles; resolve drift and contradictions.
9. **Final Human GO.** Record a candidate-bound decision before any limited Public Beta access.
10. **Limited Public Beta.** Only after all earlier gates; publish scope, support boundary, rollback, stop conditions, and durable receipts.

## Evidence required at every stage

| Evidence lane | Minimum requirement |
|---|---|
| Code evidence | Exact commit/tree, deterministic commands, bounded outputs, negative tests, and no generated drift |
| Hosted evidence | Checks run on the exact proposed head with least privilege and immutable dependencies |
| Admin evidence | Readback of branch/ruleset, security settings, identities, permissions, provider state, quotas, and stop controls |
| Human evidence | Independent latest-push review, explicit owner decisions, reconciled evidence, and candidate-bound Final Human GO |

No lane substitutes for another. In particular, a candidate-owned hosted check is not independent review, and a schema-valid artifact is not proof of live execution.

## Milestones

### M0 — Published incomplete preview

- [x] Public repository and project direction
- [x] Company Pack schemas, validators, review-chain smoke, and runtime candidate contracts
- [x] Explicit `read-only/candidate-only` and `NO_GO_UNPUBLISHED` boundary
- [ ] No claim of supported production runtime or Public Beta

### M1 — Neutral public governance baseline

- [x] PR #18 candidate contains public policy documents, proposed Apache-2.0 text, neutral validation, dependency review, immutable Action pins, and regression coverage
- [x] Exact-head hosted checks passed on `ec76f48d2623476e6433ec8673d2586ee51f9aa1`
- [ ] Issue #19 control-plane changes and readback
- [ ] Independent latest-push approval
- [ ] Explicit Apache-2.0 repository-owner decision
- [ ] Accepted integration into `main`

### M2 — Bounded public agent skills

- [ ] Rebase PR #17 after M1
- [ ] Resolve overlapping review-chain files
- [ ] Run neutral hosted validation and public-skill audit on the exact reconciled head
- [ ] Independent latest-push approval

### M3 — Cloudflare candidate reconciliation

- [ ] Reconcile PR #1 after M1
- [ ] Resolve issues #9–#16 and the remaining provider/billing/privacy gates
- [ ] Run neutral repository checks and Cloudflare-specific checks on one exact head
- [ ] Independent latest-push approval
- [ ] No provider deployment or production traffic implied

### M4 — Runtime and Voice evidence

- [ ] Supported environment and identity boundary
- [ ] Clean-install and migration evidence
- [ ] Health, restart, rollback, backup, and restore evidence
- [ ] Consent, speaker attribution, retention/deletion, access-control, and incident evidence
- [ ] Independent verification and contradiction reconciliation

### M5 — Human decision and limited Beta

- [ ] Final Human GO bound to an exact candidate, evidence set, scope, expiry, rollback, and stop conditions
- [ ] Limited Public Beta plan with support and incident boundaries
- [ ] Publish only the approved surface; preserve private data and private runtime boundaries

## Non-goals before Final Human GO

Do not publish credentials, raw conversations, personal data, private host identifiers, Discord access, Voice access, production routes, billing changes, provider mutations, Promotion, Current Truth, or Public Beta access. This roadmap creates no authority to merge, deploy, release, or invite users.
