# Repository Topology

Kotodama separates public contracts, private operational authority, and local execution work so that no repository or workspace silently becomes a competing source of truth.

This document describes roles and allowed information flow. It is a public architecture candidate, not proof that a private runtime exists, is deployed, or has adopted these contracts. The public surface remains `read-only/candidate-only` and `NO_GO_UNPUBLISHED`.

## Three layers

| Layer | Canonical responsibility | May contain | Must not contain or claim |
|---|---|---|---|
| **Public Core** | Public-safe lifecycle contracts, schemas, examples, validators, tests, and documentation after governed Promotion | Provider-neutral interfaces, synthetic fixtures, redacted receipts, public runbooks | Private source bodies, identities, sessions, credentials, endpoints, operational evidence, or a live-runtime claim |
| **Private Control Plane** | Governance, authority policy, private lifecycle events, runtime adapters, protected evidence, and recovery | Private AgentRun records, capability policy, provider/device adapters, pinned public-core dependency | A reverse dependency that forces Public Core to import private implementation or data |
| **Local Operational Workspace** | Bounded implementation, investigation, testing, and operational evidence before governed adoption | Dirty candidates, local receipts, worktrees, host-specific adapters | Canonical status merely because a file is newest, local, or executable |

## Dependency direction

The target dependency direction requires the private control plane to consume an admitted public core pinned by version, commit, and artifact digest. The current public preview does not claim that this cutover is complete. The public core never imports private implementation or data.

```text
Local Operational Workspace --candidate + evidence--> Private Control Plane
Private Control Plane --pinned dependency-----------> Public Core
Public Core --------X private code, data, or runtime dependency
```

Public extraction uses allow-listed, clean-history, independently reviewed material. Public schemas and tests may describe a contract; populated private records and operational receipts remain private.

## Canonical ownership

- Public interface facts are owned by the promoted Public Core revision.
- Private authority, lifecycle, and operational facts are owned by the governed Private Control Plane.
- Local files and host state are candidates or evidence until a bounded review and Promotion identifies a Canonical Owner.
- Discord, dashboards, indexes, status pages, and generated documents are projections unless their fact family explicitly assigns another role.
- Human Decision remains separate from code, tests, and automated verification.

## Lifecycle events and projections

Session Identity and AgentRun lifecycle facts should be append-only and replayable. Mutable status files, handoff documents, indexes, and dashboards are projections derived from those facts. A projection may be regenerated or audience-redacted; editing it does not change Current Truth.

The canonical lifecycle is intentionally narrow:

```text
prepared -> dispatched -> running -> completed | failed | cancelled | expired
```

`completed` requires the evidence declared by the governing contract. Preparing a request, dispatching work, generating an artifact, or receiving an acknowledgement cannot independently produce success.

## Cross-layer handoff

Every cross-layer handoff records:

- exact source revision and digest;
- destination layer and intended Canonical Owner;
- allow-listed content and explicit omissions;
- evidence and validation references;
- authority and gate ceiling;
- rollback and stop conditions.

A handoff does not copy authority. A successor session or adapter receives a bounded context candidate and must obtain its own capability and activation decision.

## Repository lifecycle

Repositories and workspaces should be explicitly classified as one of:

- `ACTIVE_PUBLIC_CORE`
- `ACTIVE_PRIVATE_CONTROL_PLANE`
- `ACTIVE_LOCAL_OPERATIONAL`
- `DONOR_ONLY`
- `HISTORICAL_READONLY`
- `ARCHIVE_CANDIDATE`

Rename, archive, deletion, or visibility changes require dependency readback, recovery evidence, and an exact owner decision. An archive candidate is not disposable by default.

## Migration order

1. Fix exact repository and revision identities.
2. Assign one Canonical Owner per fact family.
3. Introduce append-only lifecycle truth and rebuildable projections.
4. Compare legacy and new views before changing readers.
5. Admit small public batches through license, provenance, history, privacy, and compatibility gates.
6. Pin the private consumer to the admitted public artifact.
7. Reconcile local candidates by exact path/blob/digest without publishing private content.
8. Rename or archive only after canary and rollback evidence pass.

## Claim boundary

This topology document creates no runtime, provider connection, deployment, Human Decision, Promotion, Current Truth, Final Human GO, or Public Beta access. Current access remains `NO_GO_UNPUBLISHED`.

The public migration coordination remains tracked in [Issue #24](https://github.com/Kotodama-Project/Kotodama-project/issues/24). Repository and package names described there are proposals until their exact gates and decisions pass.
