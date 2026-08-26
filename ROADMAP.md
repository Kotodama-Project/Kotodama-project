# Roadmap to Public Beta

Current roadmap checked: 2026-08-21  
Published fixed point: `main@be71f424689648b3ab1b1db15adbaddea374586b`

This roadmap describes the **safe order of work from the current public state**. It is not a release plan or authorization. If published `main` or any active candidate head changes, this dated snapshot is stale and must be refreshed before it is used for integration or merge decisions. The detailed R179-and-earlier revision record is preserved in [the historical roadmap snapshot](docs/history/ROADMAP-R179-AND-EARLIER.md). See [STATUS.md](STATUS.md) for the current-state summary.

## Current public state

| Surface | Exact commit | Current role |
|---|---|---|
| Published `main` | `be71f424689648b3ab1b1db15adbaddea374586b` | Incomplete Public Preview; open PR content is not published |
| PR #18 | `fbb6da377edd2b726a854912eb17c964a1ec01e9` | Publication, license, policy, neutral CI, dependency baseline, and current-tree tracked credential hygiene |
| BecomeOne migration SSOT | [issue #24](https://github.com/Kotodama-Project/Kotodama-project/issues/24) | Allowlist-only, no-history dual-repository migration; every item remains blocked until classified and receipted |
| PR #17 | `704ced6a4b8be6465849646c7d2c1ba95f4fd7af` | Bounded public skill operating contract |
| PR #1 | `83e7b9e0789f941f993fd2c43a938dd872b12581` | Cloudflare edge and official OS integration candidate |

All three pull requests remain Draft, `read-only/candidate-only`, and `NO_GO_UNPUBLISHED`. Issue #24 is coordination evidence only and grants no publication, rename, archive, or deployment authority.

## Safe integration order

1. **Validate PR #18 exactly.** Keep the tracked credential gate, README smoke, three runtime-candidate validators, immutable GitHub Action references, dependency review, full tests, and clean-tree refusal green on `fbb6da377edd2b726a854912eb17c964a1ec01e9`.
2. **Complete issue #19.** Replace the Cloudflare-only generic required-check binding with neutral repository checks, configure review/force-push/deletion controls, inspect security settings, and record a sanitized readback.
3. **Complete human gates for PR #18.** Obtain independent approval of the latest push and an explicit repository-owner decision accepting Apache-2.0. Merge only after all gates pass.
4. **Publish the operational status safely.** Merge the status/roadmap change only after PR #18, rerun exact-head checks, and preserve the historical snapshots byte-for-byte.
5. **Run migration batches under issue #24.** Maintain one canonical ledger; use allowlist-only, no-history public extracts; retain or regenerate everything else; record immutable receipts; and prove zero unclassified items and zero residual consumers before any rename or archive.
6. **Rebase and validate PR #17.** Resolve overlapping review-chain files against the accepted baseline; rerun neutral hosted checks and the public-skill audit; obtain independent review.
7. **Reconcile and validate PR #1.** Retain Cloudflare-specific checks without making them the generic repository gate; resolve dependency, provenance, privacy, billing, provider, and production-boundary issues.
8. **Prove runtime lifecycle.** Bind clean install, migration, health, restart, rollback, backup, and restore evidence to one exact candidate and environment.
9. **Prove Voice and privacy boundaries.** Bind consent, participant notification, speaker attribution, retention/deletion, access control, error handling, and rollback evidence. A private Voice runtime cutover attempt is not public runtime evidence.
10. **Reconcile independently.** Separate builder, verifier, administrator, and human decision roles; resolve drift and contradictions.
11. **Final Human GO.** Record a candidate-bound decision before any limited Public Beta access.
12. **Limited Public Beta.** Only after all earlier gates; publish scope, support boundary, rollback, stop conditions, and durable receipts.

## Evidence required at every stage

| Evidence lane | Minimum requirement |
|---|---|
| Code evidence / Local evidence | Exact commit/tree, deterministic commands, bounded outputs, negative tests, no generated drift, and current-tree credential hygiene |
| Hosted evidence | Checks run on the exact proposed head with least privilege and immutable dependencies |
| Admin evidence | Readback of branch/ruleset, security settings, identities, permissions, provider state, quotas, secret state, and stop controls |
| Human evidence | Independent latest-push review, explicit owner decisions, reconciled evidence, and candidate-bound Final Human GO |

No lane substitutes for another. In particular, a candidate-owned hosted check is not independent review, a current-tree credential scan does not scan Git history or provider stores, and a schema-valid artifact is not proof of live execution.

## Current candidate entry points

- [Public Preview Self-check](docs/PUBLIC-PREVIEW-SELF-CHECK.md): `python -S -B tools/check_company_pack_public_preview.py examples/company-starter --format markdown`
- [Source Binding Verifier Candidate](docs/SOURCE-BINDING-VERIFIER-CANDIDATE.md)
- [Protected Source Binding Receipt Candidate](docs/PROTECTED-SOURCE-BINDING-RECEIPT-CANDIDATE.md)
- [Protected Execution Request Handoff Candidate](docs/PROTECTED-EXECUTION-REQUEST-HANDOFF-CANDIDATE.md)

These remain deterministic, read-only candidate tools. Discoverability is not proof of source authenticity, protected execution, provider state, deployment, or human approval.

## Milestones

### M0 — Published incomplete preview

- [x] Public repository and project direction
- [x] Company Pack schemas, validators, review-chain smoke, and runtime candidate contracts
- [x] Explicit `read-only/candidate-only` and `NO_GO_UNPUBLISHED` boundary
- [ ] No claim of supported production runtime or Public Beta

### M1 — Neutral public governance baseline

- [x] PR #18 candidate contains public policy documents, proposed Apache-2.0 text, neutral validation, dependency review, immutable Action pins, current-tree credential hygiene, and regression coverage
- [x] Repository validation run `32488194816` and Dependency review run `32488194768` passed on exact head `fbb6da377edd2b726a854912eb17c964a1ec01e9`; the public suite ran 529 tests and left no generated drift
- [ ] Issue #19 control-plane changes and readback
- [ ] Independent latest-push approval
- [ ] Explicit Apache-2.0 repository-owner decision
- [ ] Historical/provider-side credential readback and remediation if required
- [ ] Accepted integration into `main`

### M2 — Operational current-state SSOT

- [x] Compact top-level status and roadmap candidate
- [x] Historical R179-and-earlier snapshots preserved byte-for-byte
- [ ] Merge only after M1
- [ ] Exact-head hosted checks after reconciliation
- [ ] Close issue #20 only after the accepted merge and readback

### M3 — Ledger-backed BecomeOne migration

- [ ] One canonical ledger assigns exactly one terminal classification and receipt to every in-scope item
- [ ] Every public extract is allowlist-only and no-history, with license, provenance, secret/history, privacy, and independent-review gates
- [ ] The private control plane consumes an immutable, digest-verified public ref in one direction only
- [ ] Compatibility, bounded canary, and rollback evidence pass for every accepted batch
- [ ] Final source/destination re-inventory proves zero unclassified items and zero residual consumers before any rename, archive, or deprecation
- [ ] `NO_GO_UNPUBLISHED` remains until each separate publication and human gate passes

### M4 — Bounded public agent skills

- [ ] Rebase PR #17 after M1
- [ ] Resolve overlapping review-chain files
- [ ] Run neutral hosted validation and public-skill audit on the exact reconciled head
- [ ] Independent latest-push approval

### M5 — Cloudflare candidate reconciliation

- [ ] Reconcile PR #1 after M1
- [ ] Resolve issues #9–#16 and the remaining provider/billing/privacy gates
- [ ] Run neutral repository checks and Cloudflare-specific checks on one exact head
- [ ] Independent latest-push approval
- [ ] No provider deployment or production traffic implied

### M6 — Runtime and Voice evidence

- [ ] Supported environment and identity boundary
- [ ] Clean-install and migration evidence
- [ ] Health, restart, rollback, backup, and restore evidence
- [ ] Consent, speaker attribution, retention/deletion, access-control, and incident evidence
- [ ] Independent verification and contradiction reconciliation

### M7 — Human decision and limited Beta

- [ ] Final Human GO bound to an exact candidate, evidence set, scope, expiry, rollback, and stop conditions
- [ ] Limited Public Beta plan with support and incident boundaries
- [ ] Publish only the approved surface; preserve private data and private runtime boundaries

## Non-goals before Final Human GO

Do not publish credentials, raw conversations, personal data, private host identifiers, Discord access, Voice access, production routes, billing changes, provider mutations, Promotion, Current Truth, or Public Beta access. Do not rename, archive, or deprecate either repository before issue #24 proves zero unclassified items, zero residual consumers, and a tested rollback. This roadmap creates no authority to merge, deploy, release, or invite users.

## Owner-confirmed Company AGI direction

The [Owner-confirmed direction](docs/OWNER-INTENT-COMPANY-AGI.md) is the canonical product-direction source for Company AGI, bounded autonomy,
Voice Requirements Agent, per-Invocation authority, and one Kotodama product /
Company SSOT. Correction themes: BecomeOne is the migration donor/control plane;
OKF v0.2 is central for governed curated knowledge, not sole Company truth; and
Voice raw/derived evidence plus adaptive GrillU remain explicit. Luna-first
routing, a provider-neutral archive interface with a private ZFS v1 target still
pending exact safe dataset binding, reversible review/revert delegation, and the
bounded Goal Completion Loop remain product requirements. This
documentation milestone does not implement the runtime: Voice-to-Requirement,
Agent Swarm, Context/encoder, provider, storage, and Promotion remain separate
work. The runtime remains unimplemented and Public Beta remains
`NO_GO_UNPUBLISHED`. The public bytes are a redacted owner-directed direction
candidate, not signed or independently verifiable governance approval,
rightsholder proof, canonical adoption, launch decision, or Final Human GO, and
no receipt is fabricated. PR #18 supplies Apache-2.0 candidate bytes; Issue #25's
contributor/provenance/NOTICE/accountable-rightsholder gaps remain open.
