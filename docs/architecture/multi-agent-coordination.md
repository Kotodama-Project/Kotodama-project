# Multi-agent coordination contract

Status: **candidate only / `NO_GO_UNPUBLISHED`**.

This contract defines how a coordinator, bounded workers, and reviewers exchange
work. It is independent of any model vendor, message transport, hosting
provider, or deployment topology.

## Roles

| Role | Responsibility | Must not do |
|---|---|---|
| Coordinator | Decompose accepted work, assign ownership, collect evidence | Invent missing authority or silently widen scope |
| Worker | Produce one bounded candidate and its evidence | Mutate work owned by another lease |
| Reviewer | Evaluate the candidate against declared checks | Treat authorship or execution as independent approval |
| Human authority | Approve sensitive transitions and promotion | Delegate accountability to a successful tool result |

A process may implement more than one role, but every record names the role being
performed. Independent review requires a distinct accountable reviewer.

## Work item envelope

Every delegated unit declares:

- `work_id`: stable identifier;
- `parent_ref`: immutable reference to the accepted parent intent or plan;
- `owner_role`: the role holding the active lease;
- `scope`: exact paths, resources, or records the worker may affect;
- `input_refs`: immutable inputs, never an implicit working set;
- `expected_outputs`: candidate artifacts and their required format;
- `acceptance_checks`: deterministic checks evaluated before handoff;
- `stop_conditions`: conditions that prohibit further mutation;
- `rollback`: reversible action or explicit statement that no mutation occurred;
- `evidence_refs`: immutable receipts added during execution;
- `lease_version` and `expires_at`: concurrency boundary.

The envelope contains references rather than credentials, personal data, live
endpoints, or source bodies.

## Lifecycle

| State | Meaning | Allowed next states |
|---|---|---|
| `PROPOSED` | Work is described but not authorized | `READY`, `CANCELLED` |
| `READY` | Preconditions and authority are recorded | `CLAIMED`, `CANCELLED` |
| `CLAIMED` | One owner holds the current lease | `RUNNING`, `BLOCKED`, `READY` |
| `RUNNING` | Candidate work is in progress | `BLOCKED`, `VERIFYING`, `CANCELLED` |
| `BLOCKED` | A named prerequisite is missing | `READY`, `CANCELLED` |
| `VERIFYING` | Candidate is immutable while checks run | `REVIEW`, `BLOCKED` |
| `REVIEW` | Evidence awaits an independent decision | `COMPLETE`, `BLOCKED`, `CANCELLED` |
| `COMPLETE` | Declared output and evidence are accepted | none |
| `CANCELLED` | Work stopped without promotion | none |

An unknown transition is rejected. Completion of a child does not automatically
complete its parent.

## Ownership and concurrency

1. A writable resource has at most one active lease.
2. Lease acquisition compares the expected version before assigning ownership.
3. A worker renews a lease only while its scope and authority remain unchanged.
4. An expired or conflicting lease stops writes and produces a blocked receipt.
5. Parallel workers use disjoint write sets or an explicitly reviewed merge
   protocol.
6. The coordinator bounds concurrency; an available worker is not itself a
   reason to create more work.

## Messages and idempotency

Messages contain a schema version, message identifier, work identifier, sender
role, expected lease version, event type, immutable payload reference, and
timestamp. Receivers record the message identifier before applying its event.
A repeated identifier returns the prior outcome and must not repeat a side
effect.

Ordering is local to a work item. Cross-item ordering is expressed with explicit
dependency references, not wall-clock assumptions.

## Failure and retry

- A retry repeats only an idempotent transition or creates a new attempt linked
  to the prior failure.
- Backoff is bounded by a declared attempt budget and deadline.
- A permanent validation error moves work to `BLOCKED`; it is not retried as a
  transport failure.
- Partial candidates remain unpromoted until their full acceptance set passes.
- Compensation is a new reviewed action. It does not erase the original event
  or evidence.

## Handoff and review

A worker handoff records the candidate identity, exact input refs, checks run,
checks not run, evidence refs, residual risks, and rollback. The reviewer binds
the decision to that exact candidate. Any later change makes the earlier review
stale.

This contract defines coordination semantics only. It does not create agents,
queues, runtime authority, or a production deployment.

Source-derived architecture component: MIT; see
[`../../LICENSES/MIT.txt`](../../LICENSES/MIT.txt).
