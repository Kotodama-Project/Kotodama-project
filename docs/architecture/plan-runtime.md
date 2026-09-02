# Plan lifecycle contract

Status: **candidate only / `NO_GO_UNPUBLISHED`**.

This document defines a deterministic plan lifecycle. “Runtime” here means the
state-transition contract for a plan candidate; it does not assert that a live
service or deployment exists.

## Plan record

A plan record contains:

- `plan_id` and `schema_version`;
- immutable `intent_ref` and authority references;
- `revision` and current `state`;
- ordered step records with stable identifiers;
- explicit dependency edges;
- per-step scope, owner role, capability category, and risk class;
- acceptance checks and evidence requirements;
- attempt, time, and concurrency budgets;
- stop conditions, cancellation policy, and rollback or compensation plan;
- checkpoint and decision references.

Mutable values are updated through versioned events. A prose plan without these
boundaries may be useful for discussion but is not executable under this
contract.

## States

| State | Entry condition | Exit condition |
|---|---|---|
| `DRAFT` | Plan is being authored | Structure and authority are validated |
| `READY` | Preconditions are known and no blocker is open | A runnable step is claimed or plan is cancelled |
| `RUNNING` | At least one authorized step is active | Work blocks, verification begins, or cancellation is accepted |
| `BLOCKED` | A named prerequisite or evidence item is missing | The blocker is resolved or plan is cancelled |
| `VERIFYING` | All required candidate steps stopped mutating | Declared checks produce complete evidence |
| `REVIEW` | Evidence is complete for the exact revision | Independent acceptance, rejection, or rework decision |
| `COMPLETE` | Acceptance is bound to the exact revision | Terminal |
| `CANCELLED` | Cancellation policy completed | Terminal |

Unknown states and transitions are rejected. `COMPLETE` cannot be reached
directly from `RUNNING`.

## Dependency scheduling

Steps form a directed acyclic graph. Validation rejects missing dependencies,
self-dependencies, and cycles. A step becomes runnable only when every required
predecessor has the declared accepted outcome. “Finished” is not equivalent to
“accepted.”

The scheduler chooses from runnable steps subject to explicit concurrency and
resource limits. Selection order is deterministic for equal-priority work, for
example by priority followed by stable step identifier. Scheduling never widens
a step's scope or capability.

## Events and checkpoints

Each transition records an event identifier, plan revision, expected prior
state, actor role, transition type, input references, evidence references, and
timestamp. Applying an event with a previously accepted identifier returns the
prior result. Applying an event against a stale revision fails with a conflict.

A checkpoint contains the plan revision, accepted event sequence, step states,
outstanding blockers, evidence index, and integrity digest. Checkpoints are
recovery aids; they do not replace the event record or authorize promotion.

## Validation and evidence

Every step declares structural checks and, where applicable, behavioral checks.
The plan may enter `REVIEW` only when:

1. every required step is accepted or explicitly waived by authorized policy;
2. every expected evidence reference resolves to the exact candidate;
3. no blocker, expired grant, or uncertain side effect remains;
4. rollback or compensation information is complete;
5. verification identifies checks that did not run as well as checks that ran.

A partial or missing check is a blocked result, not an implied pass.

## Cancellation and recovery

Cancellation stops new claims, requests cooperative cancellation of active
steps, and waits for independent readback of uncertain side effects. It then
executes only the rollback or compensation actions explicitly authorized for
the plan. Completed evidence is retained.

Recovery loads the latest valid checkpoint, replays later accepted events, and
reconciles any in-flight action through read-only inspection before deciding
whether a retry is safe. Re-execution without reconciliation is prohibited.

## Revision and review

Changing plan scope, dependencies, authority, acceptance checks, or candidate
bytes creates a new revision. Reviews and approvals bind to one revision and
become stale after such a change. A newer revision may cite prior evidence only
when the evidence contract declares it reusable and its inputs are unchanged.

This contract contains no provider deployment details, live operational state,
private implementation index, or repository-specific backlog.

Source-derived architecture component: MIT; see
[`../../LICENSES/MIT.txt`](../../LICENSES/MIT.txt).
