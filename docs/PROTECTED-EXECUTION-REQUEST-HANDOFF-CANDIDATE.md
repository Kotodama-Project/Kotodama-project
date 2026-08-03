# Protected Execution Request / Handoff Candidate

This document describes the public, schema-only candidate for handing a future
protected execution request to a private runner. It is deliberately narrower
than the [Protected Source Binding Receipt Candidate](PROTECTED-SOURCE-BINDING-RECEIPT-CANDIDATE.md).
It defines what a runner would need to receive and what a later independent
verifier would need to check; it does not run a runner or publish private
evidence.

The current public state is `CANDIDATE_ONLY`, `REQUEST_DEFINED_UNVERIFIED`, and
`NO_GO_UNPUBLISHED`. No populated private request, source record, audio,
transcript, consent evidence, retention evidence, credential, or receipt is
stored in this repository.

## Ideal use

The eventual flow is:

1. A governed Work Order selects an exact runner policy, executable, config,
   environment, clock policy, and rollback policy.
2. A private protected store supplies four opaque, purpose-bound locators:
   `source_record`, `source_content`, `access_consent_evidence`, and
   `retention_policy`.
3. The runner evaluates the request only inside the bounded time window and
   stops on any fixed stop condition.
4. The runner may create a private Protected Source Binding Receipt Candidate
   with all claims still unverified. Its serialized bytes remain private and
   are not embedded in this public handoff.
5. An independent verifier receives a separate handoff and resolves the
   private bindings. A Human Decision, Promotion, Current Truth update, Voice
   runtime claim, or Public Beta decision is a later governed step.

The canonical chain remains:

```text
Source -> Intent Candidate -> Decision -> Work Order -> Change Candidate
       -> Verification Receipt -> Promotion -> Current Truth
```

This candidate is a request/handoff shape between Work Order and a future
private Change Candidate. It cannot skip the chain.

## Contract shape

The machine-readable contract is
[`schemas/company-pack-protected-execution-request-handoff-candidate.schema.json`](../schemas/company-pack-protected-execution-request-handoff-candidate.schema.json).
It uses Draft 2020-12 with closed objects and exact ordered arrays.

| Area | Contracted boundary |
| --- | --- |
| Source contract | Exact public revision and expected R33 receipt kind/state, all `NOT_VERIFIED` |
| Runner request | Opaque policy/executable/config/environment refs and bindings; no credentials or physical paths |
| Private inputs | Exactly four ordered opaque refs; locators are not resolved |
| Evaluation window | `not_before`, `expires_at`, bounded clock skew, and an unverified clock policy |
| Failure / rollback | Fixed stop conditions, no external effects expected, no rollback or execution receipt populated |
| Expected output | R33 receipt-candidate contract only; serialized receipt locator and binding remain `null` |
| Handoff | `independent_verifier` role and policy only; result and Human Decision refs remain `null` |
| Claims | Every execution, authority, authenticity, retention, runtime, Promotion, and GO claim is `false` |

References are intentionally opaque `ref/...` values. A path, URL, token,
cookie, hostname, raw body, audio, transcript, or private locator URI is not a
valid substitute. A binding is only a declared digest/byte-count shape; it is
not proof that the referenced bytes exist or are authentic.

## Time and stop conditions

The schema bounds `max_skew_seconds` to 24 hours and validates timestamp shape.
The future protected runner must additionally enforce that `not_before` is
strictly earlier than the nested `expires_at`, that the request and window are
within their parent expiry, that its clock policy is trusted, and that the
window has not expired. **schema alone does not prove** those cross-field or
trusted-clock conditions.

The stop-condition order is fixed:

1. `locator_unresolved`
2. `consent_or_retention_missing`
3. `runner_binding_drift`
4. `clock_untrusted_or_window_expired`
5. `input_or_output_binding_drift`
6. `external_effect_detected`

Any stop condition yields `NOT_EXECUTED` or `REFUSED_UNVERIFIED`, with
`no_external_effects_expected: true`. A real rollback receipt requires a
separate private execution receipt contract and cannot be filled in this
candidate.

## What is implemented now

The public repository currently contains only:

- the closed Draft 2020-12 schema;
- contract tests using a real Draft 2020-12 validator and hostile instances;
- this documentation and navigation links from the Company starter material.

There is no request builder, protected runner, private-store resolver, trusted
clock adapter, nonce/replay store, deletion worker, signature verifier, or
populated handoff. The R33 receipt schema remains the expected-output contract;
this R35 document does not duplicate or activate it.

## Verification and rollback boundary

Local schema/test PASS proves only that the candidate bytes satisfy the
published shape. It does not prove source authenticity, consent authority,
retention or deletion enforcement, replay prevention, person separation,
independent verification, deployment, Discord/Voice E2E, Promotion, Current
Truth, Final Human GO, or Public Beta GO.

For this documentation-only revision, rollback is a normal revert of the
candidate commit. Do not delete or overwrite private source material as a
rollback action. A future protected Work Order must name the exact target,
revision, effect, rollback, expiry, and stop conditions before any private
runner is invoked.

## Related public contracts

- [Company Pack Catalog](COMPANY-PACK-CATALOG.md)
- [Source Binding Verification Candidate](SOURCE-BINDING-VERIFIER-CANDIDATE.md)
- [Protected Source Binding Receipt Candidate](PROTECTED-SOURCE-BINDING-RECEIPT-CANDIDATE.md)
- [Template Guide](TEMPLATE-GUIDE.md)
- [Starter Walkthrough](STARTER-WALKTHROUGH.md)
