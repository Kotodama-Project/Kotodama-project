# Public architecture boundaries

Status: **candidate only / `NO_GO_UNPUBLISHED`**.

These documents describe provider-neutral design contracts. They do not prove
that a runtime exists, grant execution authority, publish an operational
topology, or make a release or admission decision.

## Scope

The public architecture set answers four questions:

1. Which layer owns each decision and record?
2. How do bounded workers coordinate without hidden shared state?
3. How does a supervisor call tools without acquiring implicit authority?
4. How does a plan move through deterministic, reviewable states?

The detailed contracts are:

- [multi-agent coordination](multi-agent-coordination.md);
- [supervision contract](supervision-contract.md);
- [plan lifecycle](plan-runtime.md).

## Architectural invariants

### Separate intent, authority, execution, evidence, and promotion

An intent states the desired outcome. A decision establishes whether work may
proceed. A capability grant bounds what a worker may change. Execution produces
a candidate. Verification produces evidence. Promotion is a separate human or
policy decision. No layer may infer a missing decision from success in another
layer.

### One owner per authoritative record

Each authoritative record has one declared owner and one write boundary.
Projections may summarize or index that record, but a projection cannot become
an alternate source of truth. Cross-layer communication uses immutable
references or versioned messages rather than untracked shared state.

### Dependencies point toward stable contracts

The public dependency direction is:

```text
contracts -> coordination -> adapters -> operational surfaces
```

Contracts must not depend on a provider adapter. Coordination may depend on
contracts but not on a live deployment. Adapters translate an explicit contract
for one environment. Operational surfaces consume evidence; they do not rewrite
the contract that produced it.

### Fail closed at missing boundaries

Unknown authority, missing evidence, conflicting ownership, expired capability,
or an unrecognized state stops the transition. A stop is a valid and reportable
outcome. It must not be converted into success by a retry, default value, or
best-effort continuation.

### Make replay deterministic

State transitions use stable identifiers, explicit inputs, monotonic sequence
numbers, and idempotency keys. Replaying the same accepted event must not create
a second side effect. Human-readable documents may explain a transition, but
the recorded state and evidence references determine its identity.

### Minimize public data

Public contracts define fields and categories, not live values. Credentials,
personal data, provider account details, endpoints, private repository paths,
and operational ledgers stay outside the public architecture set. Evidence
should identify a check and immutable artifact without embedding sensitive
payloads.

## Repository placement rules

- `docs/architecture/` contains stable, provider-neutral contracts.
- Provider adapters belong outside the contract layer and require their own
  security and deployment review.
- Time-bound backlogs and incident state belong in the current tracking system,
  not in normative architecture.
- Generated indexes and implementation trace maps remain implementation
  evidence, not public architectural authority.
- A document may link to an authoritative record but must not duplicate its
  mutable state.

## Candidate and admission boundary

This component remains blocked pending the accountable license/provenance
decision in Issue #25, an applicable private source-history secret/PII receipt
for all A022 paths, independent latest-push review, PR #18 and Issue #19
governance prerequisites, and Dependency Review after retargeting to `main`.
The Apache-2.0 proposal in PR #18 is not relicensing authority for this
source-derived component.

Source-derived architecture component: MIT; see
[`../../LICENSES/MIT.txt`](../../LICENSES/MIT.txt).
