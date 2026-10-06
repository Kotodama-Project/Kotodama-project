---
name: kotodama-agent-status
description: Use only for the Kotodama public repository to diagnose agent responsibility indexes and bounded offline observations with private context withheld.
---

# Kotodama agent status

## Intent

Explain the difference between indexed responsibilities, reported activity,
freshness, stop observations and independent verification using the repository's
existing projector. The mode is `plan`: read-only and no mutation controls.

## Triggers

Use for an offline diagnostic of this repository's agent index or an explicitly
selected local observation snapshot. Read the [input and display contract](../../../docs/AGENT-STATUS-PROJECTION.md).

## Non-triggers

Live runtime control, provider queries, new credentials, task dispatch and access
decisions belong to their existing owners. This skill does not establish agent
health or permission to act. A generic status request outside Kotodama is not a trigger.

## Procedure

1. Pin the repository revision, dirty baseline, owner and allowlisted local input
   paths. Reuse existing read authorization; source access is not evaluated by
   the projector. Done when: the target, sensitivity and read boundary are known.
2. Obtain `python -B tools/project_agent_status.py --bundle-sha256` and bind the
   digest to the existing task evidence. It covers code, this skill and the
   consumed integration contract, not runtime identity or authority.
   Done when: the content digest and evaluation timestamp are recorded.
3. Run `python -B tools/project_agent_status.py --expected-bundle-sha256 DIGEST --as-of RFC3339 --format markdown`,
   substituting the recorded digest and evaluation instant. Use `--observations`
   only for the already authorized snapshot. JSON and Markdown withhold names,
   purposes and Work/run identifiers by default; `--include-context` is an
   explicit local display choice, not permission or a public-output flag.
   Done when: every attempt has an exit code and the parsed input digests match
   the selected scope; no missing observation is called offline or healthy.
4. Keep registry, reported state, freshness, execution, stop and verification
   separate. Return the [standard content-free receipt](../../../docs/SKILL-OPERATING-CONTRACT.md#5-receipt-contract)
   with source revision, digests, timestamp, exit code, `mode=plan`, `changed=false`,
   `no_op=true` and its read-only reason, actual evidence tier and remaining gates.
   Done when: the diagnostic explains unknowns without granting authority or
   exposing private input, and file/network-write/external-send counts are zero.

## Completion

`COMPLETED` means the scoped local projection succeeded. Its evidence tier is
`LOCAL`; it does not create `DEVICE`, `PROVIDER`, `PUBLIC` or `HUMAN_GO` evidence.
Use `UNKNOWN` or `FAILED` for unavailable or refused inputs, and report skipped
checks explicitly. Model identity is `MODEL_UNVERIFIED` unless observed; the
deterministic CLI itself uses `NOT_APPLICABLE`.

## Recovery

On bundle mismatch, preserve the prior digest and inspect the changed components
before accepting a new one. Reconcile conflicting observations at their source;
do not choose the last record or rerun unchanged failures. A fresh report remains
unauthenticated; a stop request is not confirmed termination. See the
[diagnostic integration contract](../../../docs/AGENT-DIAGNOSTICS-INTEGRATION.md)
when interpreting input limits, Windows behavior or CI results.
