# Supervision and tool-boundary contract

Status: **candidate only / `NO_GO_UNPUBLISHED`**.

A supervisor converts an authorized plan step into a bounded tool request and
records the outcome. It is a control boundary, not an unlimited executor and
not a substitute for human approval.

## Inputs and outputs

The supervisor accepts only:

- an immutable plan and step reference;
- the current state version;
- a capability grant naming permitted actions and resources;
- preconditions and a time or attempt budget;
- the expected result schema and verification checks;
- stop, escalation, and rollback rules.

It emits a decision record, zero or one bounded tool request, the resulting
candidate or failure reference, verification evidence, and the next proposed
state. A tool response alone is never a promotion decision.

## Decision sequence

For every step the supervisor evaluates, in order:

1. **Identity** — the plan, step, and state version are the expected immutable
   objects.
2. **Authority** — the capability grant is present, current, and specific to the
   requested action.
3. **Preconditions** — dependencies and required evidence are satisfied.
4. **Risk class** — read-only, reversible write, sensitive write, or prohibited.
5. **Budget** — the attempt, time, and concurrency limits have capacity.
6. **Invocation** — exactly one typed request is sent to the selected tool.
7. **Validation** — the response matches its schema and declared checks.
8. **Receipt** — success, failure, and omitted work are recorded without secret
   values.

Failure at any stage prevents later stages from running.

## Tool contract

Each registered tool declares:

- a stable tool identifier and version;
- input and output schemas;
- side-effect class;
- required capability categories;
- idempotency behavior;
- timeout and cancellation behavior;
- evidence emitted on success and failure;
- rollback or compensation support.

Dynamic tool discovery may suggest a tool, but it cannot authorize its use. An
unregistered tool or schema mismatch is a blocking error.

## Side-effect policy

| Class | Default policy | Required evidence |
|---|---|---|
| Read-only | Allowed within declared scope | Input ref and bounded result digest |
| Reversible write | Explicit grant and rollback | Before/after identity and rollback receipt |
| Sensitive write | Human approval and least privilege | Exact approval, target, result, and independent readback |
| Prohibited | Never invoke | Blocked decision with policy reason |

Broad targets, unresolved variables, hidden defaults, and missing rollback
information fail closed.

## State transition rules

The supervisor proposes a transition with an expected prior version. The state
store accepts it only when the expected version still matches. A concurrent
change returns a conflict and causes re-evaluation; it must not be overwritten.

A successful invocation may advance a step to `VERIFYING`. Only declared checks
may advance it to `REVIEW`. Independent acceptance may advance it to
`COMPLETE`. Missing or failed evidence advances it to `BLOCKED`, never to a
degraded success state.

## Failure isolation

- Timeouts cancel the bounded request when supported and record uncertainty.
- A response with an unknown completion state is treated as potentially
  side-effecting until independently read back.
- Retry budgets are per step and cannot be borrowed silently from another step.
- Circuit breaking stops a failing tool class without cancelling unrelated
  read-only work.
- Compensation is separately authorized and linked to the original receipt.
- Logs contain categories, object identities, and digests, not credentials,
  personal data, or raw private payloads.

## Human gates

Human approval is required when policy classifies a transition as sensitive,
irreversible, externally visible, financially material, privacy-relevant, or a
promotion. Approval binds to the exact candidate and expires when its inputs,
scope, or bytes change.

This document specifies a provider-neutral contract. It does not document a
live tool registry, account, endpoint, deployment, or operational topology.

Source-derived architecture component: MIT; see
[`../../LICENSES/MIT.txt`](../../LICENSES/MIT.txt).
