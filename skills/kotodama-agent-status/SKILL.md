---
name: kotodama-agent-status
description: Diagnose the existing Kotodama agent registry using bounded offline observations, without execution, authority changes, or live-runtime claims.
---

# Kotodama agent status

Use the repository's `tools/project_agent_status.py`. This skill and implementation
ship together. Read `docs/AGENT-STATUS-PROJECTION.md` for the observation contract.

## Procedure

1. Confirm permission to read the local inputs. This tool does not evaluate access.
   Do not feed private observations into a public report or expose stdout as an API.
2. Read the current skill, then obtain the content identity:
   `python tools/project_agent_status.py --bundle-sha256`.
   Record it with the task's existing evidence; do not create a new authority ledger.
3. Run `python tools/project_agent_status.py --expected-bundle-sha256 DIGEST --as-of RFC3339`.
   Replace `DIGEST` with the recorded digest and `RFC3339` with the explicit evaluation
   instant. With no observation file, every connection is unknown, not offline.
4. Use `--observations PATH` only for an already-authorized, bounded local snapshot.
   Never obtain credentials, query a runtime, restart an agent, or dispatch work as a
   side effect of diagnosis. The default observation expiry is 120 seconds; it is a
   diagnostic policy, not an established service-level objective.
5. Report registry state, reported state, freshness, projected execution state, and
   verification separately. Exit 0 only means projection succeeded. It never means
   a runtime is healthy, a task is independently verified, or an action is permitted.
6. On mismatch, reread the implementation/skill/contract before recording a new
   digest. Do not silently accept a changed bundle. On ambiguous observations,
   reconcile at their existing source; do not choose the last record automatically.

## Boundaries

A fresh report is still unauthenticated. A planned or unbound agent is never projected
as running. A stale/future observation becomes unknown; preserve its reference for
source-side investigation. A stop request is not a stop confirmation. A producer's
`verified_candidate` claim never becomes independent verification here.

The digest covers implementation, this skill, and the consumed integration contract.
It identifies content, not trust, signatures, a Capability Grant, or human approval.
It does not check an arbitrary external copy of this skill unless that copy's recorded
digest is supplied. Output contains no mutation controls. Do not reinterpret it as
permission to operate OpenMaus, Cloudflare, Proxmox, or any agent.

## Version 2 diagnostic output

Read [the integration and v2 contract](../../docs/AGENT-DIAGNOSTICS-INTEGRATION.md).

The output is `agent-status-v2`: each diagnostic code has a fixed read-only
`next_steps` explanation. Fresh/missing/stale/future counts are observation counts,
not healthy-agent counts. No new command, retry, grant, or mutation is authorized.
Consumers of v1 must explicitly accept v2 before using these additional fields.
Input mutation detected across stat/open/read/post-stat is refused. Use immutable,
access-controlled snapshots: these checks are not an atomic directory snapshot.

## Local human-readable view

Markdown keeps names, purposes and Work/run identifiers withheld by default. An
operator who already has access to the input can use `--include-context` for an
explicit local view. This is not an authorization check or a safe-to-publish flag.
Read the evaluation time, freshness, stop state, independent verification and
next steps together. A stop report remains unauthenticated runtime evidence;
`not_evaluated` is never a successful verification. See
`docs/TEST-INTENT-AUDIT.md` for the scope and regression evidence.
