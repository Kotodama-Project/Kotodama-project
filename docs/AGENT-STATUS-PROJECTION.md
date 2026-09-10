# Agent status projection — Olares-informed, read-only candidate

## Scope

This change turns part of the existing #56 common-agent-view contract into executable
Python, rather than adding another registry, scheduler, portal, or authority ledger.
The canonical input stays `governance/agent-registry.json`; the vocabulary and common
fields come from `governance/openmaus-integration.json`.

This is an **offline diagnostic projector and CLI**, not a connected adapter, native
Workforce Console, or complete implementation of #56's P0. It does not replace the
OpenMaus GUI integration direction. It introduces no runtime dependency beyond Python's
standard library, no network call, no subprocess execution, and no canonical write.

## Run

```sh
python tools/project_agent_status.py --as-of 2026-09-10T09:00:00Z
python tools/project_agent_status.py --as-of 2026-09-10T09:00:00Z --format markdown
python tools/project_agent_status.py --bundle-sha256
python -m unittest discover -s tests -p 'test_agent_status_projection.py' -v
```

An omitted observation file means **not observed**, never offline or healthy. To
inspect an already-authorized local snapshot, add `--observations PATH`. `--root`
selects the existing registry and integration contract; it does not substitute the
executing implementation or its skill. Use `--expected-bundle-sha256 DIGEST` to refuse
a skill/implementation/contract mismatch. No install or mutation command is provided.

Exit 0 means the projection was computed, even when every agent is unbound or stale.
Exit 2 means invalid/unavailable input or bundle mismatch; no partial report is emitted.
The CLI only writes its report to stdout and a bounded error to stderr. Shell output
redirection is the caller's responsibility. Use immutable input snapshots for a
consistent cross-file read: no repository-wide transaction is asserted.

## Observation format v1

A snapshot contains exactly `version: 1` and `observations: []`. Each observation
contains exactly the following fields; nullable fields must still be present:

```json
{
  "version": 1,
  "observations": [{
    "kotodama_agent_id": "context-compiler",
    "observation_ref": "fixture:observation-1",
    "adapter_id": "external_agents",
    "observed_at": "2026-09-10T09:00:00Z",
    "connection_state": "running",
    "current_work_ref": "fixture:work-1",
    "run_ref": "fixture:run-1",
    "work_state": "running",
    "stop_requested_at": null,
    "stop_observed_at": null
  }]
}
```

This is a **synthetic example**, not evidence that context-compiler runs. A registry
entry that is planned, candidate-only, disabled, retired, or unbound stays `unknown`
even with this observation. Raw reported state is retained separately for diagnosis.

The adapter ID must exist in the existing integration contract. This checks identity
membership only, not a deployed adapter, authentication, or source access. Work state
uses that contract's vocabulary. A work state requires both Work and run references;
all three must be null for an observation with no work. Identifiers are bounded opaque
references; no referenced path or URL is opened. Transcripts, arbitrary metadata,
credentials, artifact bodies, or extra fields are not accepted.

One observation per registered agent is allowed. Duplicate agent IDs, duplicate
observation references, a Work/run attributed to multiple agents, unknown IDs, and
partial Work/run bindings are rejected. Resolve ordering and multi-run aggregation
at the source before constructing the snapshot; last-write-wins is not implemented.

## Projection rules

| Input | Projected result |
| --- | --- |
| No observation | Connection, execution, and stop state are unknown. |
| Fresh report on an active, promoted, bound registry entry | Reported connection/work state may be projected, but remains unauthenticated and is not authority. |
| Candidate-only registry, inactive entry, or missing implementation binding | Connection/execution remain unknown. Raw reported state is separate. |
| Age at or beyond the expiry, including the exact boundary | Unknown; diagnostic retains source reference and `stale` freshness. |
| Observation later than the evaluation instant | Unknown and `future`; no implicit clock-skew allowance. |
| Execution settled or producer claims verification | Independent verification stays `not_evaluated`. |
| Stop request without stop observation | Never `observed`; an unsupported cancellation claim becomes unknown. |
| Stop observation | Requires the same snapshot's Work/run binding, ordered timestamps, cancelled work, and non-running connection. Still a report, not independently validated stop evidence. |
| Required common-view field changes | Fail rather than fabricate the missing field. |

Freshness defaults to 120 seconds, configurable from 1 to 86,400 seconds. It is not a
production SLA. Registry authority is a **declared value**, not an evaluated grant.
Group/project membership, runtime location, parent Work, artifacts, and cost references
remain empty/null until a real authorized source exists; the projector does not invent
these from names, purposes, or adapter hints. There are no mutation controls, even for
`bounded_execute` agents. All observations get an unauthenticated-report diagnostic.

The read path rejects oversized files (>1 MiB), oversized collections (>1,000 entries),
overdeep JSON, duplicate keys, non-finite values, symlink inputs, and non-regular files
including FIFOs. These are bounded local-input defenses, not a filesystem sandbox or
protection against a concurrent adversarial replacement of parent directories.

## Content identity and trust

`bundle_sha256` covers the executing source file, the co-shipped `SKILL.md`, and the
actual consumed integration-contract bytes. The digest is domain-separated and hashes
sorted paths, path lengths, content lengths, and contents. The report separately binds
the exact parsed registry/contract/observation byte snapshots via `input_sha256`.

A digest is not a signature, attestation, reproducible Python environment, approval,
source authentication, or access decision. Full registry/schema conformance remains
with existing validators; this projector validates only the fields it consumes. The
local skill is checked; an externally installed copy must retain and supply its
recorded expected digest to detect drift. This is not automatic skill installation.

## Integration boundary and next patch

Do not mount this CLI output directly as a public or multi-user endpoint. The report
explicitly says `access_evaluation: not_evaluated_do_not_serve`. A future native adapter
must first resolve the observer and purpose, recheck access to every source and Work,
validate source/run bindings and authenticity, and only then render an escaped view.
Sharing a Gadget or connecting over Access/Tunnel must not grant source access.

Implement that read-only authenticated source adapter against the agreed native OS
integration point from #45–#47. Keep #56's original OpenMaus GUI/native integration
scope: this module is not a separate portal or a replacement GUI. Mutation dispatch,
stop execution, independent verification receipts, Proxmox lifecycle, adoption, and
Current Truth remain outside this patch. Do not add a new scheduler or Task SSOT.

Rollback is removal/revert of the four additive files in this change. No migration,
authority record, resource, secret, data retention setting, or deployment is changed.
Existing CI already discovers the new tests through `unittest discover -s tests -v`.
The focused suite uses synthetic reports to verify deterministic behavior and safety
boundaries; it is not runtime isolation, provider compatibility, or end-to-end testing.

## Design references

- Olares manifest specification: https://www.olares.com/docs/developer/develop/package/manifest
  — reuse a machine-readable contract instead of copying state rules into each UI.
- Olares `cli/skills/digest.go`: https://github.com/beclab/Olares/blob/main/cli/skills/digest.go
  — identify shipped instructions by their contents, not just a version label.
- Kotodama #56: https://github.com/Kotodama-Project/Kotodama-project/pull/56
  — retain common identity, separate execution/verification, and observe stops.

References were inspected on 2026-09-10. This is an independent Python implementation;
no Olares source code, dependencies, or license files are imported. Olares is a design
reference, not an adopted OS or an asserted license compatibility determination.
