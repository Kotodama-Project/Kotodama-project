# Kotodama public Skill Operating Contract

Status: public reference contract, refreshed 2026-08-17.

This document defines the smallest safe contract for the portable skills in
`.agents/skills`. It carries the project intent and evidence boundaries into
the public repository without pretending that a Markdown skill is a runtime,
an approval system, or a deployment credential.

## 1. Intent before mechanics

Every skill must answer four questions before it describes a tool call:

1. **Intent:** what user outcome becomes safer or more repeatable?
2. **Trigger:** which request is a match, and which similar request is not?
3. **Scope:** which repository, files, accounts, data classes, and evidence
   tiers are in scope?
4. **Completion:** which machine-readable receipt proves completion, no-op,
   partial work, blocked work, or an unknown result?

Keep `description` short: action, target, and strongest positive trigger.
Keep non-goals and detailed procedure in the body. A skill that is explanatory
must say so and must not present a nonexistent command as executable.

The recommended body order is:

`preflight -> intent -> plan/dry-run -> approval -> apply -> verify -> receipt -> recovery`

## 2. Public surface ownership

| Surface | Responsibility | Boundary |
| --- | --- | --- |
| `.agents/skills/` | portable public reference skills | declarative, plan/read-only by default |
| `docs/` | project governance and public explanation | does not grant authority |
| `tools/` | deterministic local validators | output is local evidence only |
| private runtime/adapters | project-specific implementation | intentionally not copied into this public pack |

An adapter is not a second source of truth. If a downstream runtime copies a
skill, it must preserve the public revision and state which implementation owns
the executable behavior.

## 3. Manifest and trigger contract

Every public skill starts with exactly the portable minimum unless a runtime
explicitly documents an additional field:

```yaml
---
name: lower-case-hyphen-name
description: One sentence describing the action and when to use it.
---
```

Triggers are positive and bounded. Non-triggers are explicit. Generic words
such as `update`, `research`, or `session` are not sufficient on their own;
use a namespaced skill name and a target-specific description to avoid silent
collisions. Every skill in this pack starts its description with
`Use only for the Kotodama public repository ...`; a generic research,
implementation, validation, planning, delegation, or handoff request outside
that repository is not a trigger.

Every numbered procedure step ends with a checkable `Done when:` condition.
Overall completion cannot substitute for an incomplete intermediate step. The
surface auditor can also compare explicitly declared external catalogs with
repeatable `--external-skill-root <path>` arguments. It reads only bounded
`*/SKILL.md` files and fails on duplicate names or exact descriptions; it does
not discover or widen to undeclared roots.

Model names, task names, nicknames, static TOML, and historical receipts do
not prove which model ran. If runtime metadata is unavailable, record
`MODEL_UNVERIFIED`; do not infer an identity or silently switch to a fallback.
The same rule applies to agent depth, fork mode, ABI/version, and provider
capability.

## 4. Modes and authorization

State-changing work exposes an explicit mode:

- `plan`: inspect and propose; no writes, sends, credentials, or provider calls;
- `dry-run`: calculate exact target, diff, effect count, and rollback locator;
- `apply`: change only the approved candidate.

`plan` or `dry-run` is the public default. `apply` requires a valid session or
work identifier, exact target and revision digest, an owner, an effect ceiling,
and a recorded dirty baseline. Public, provider, credential, delete, or
destructive actions additionally require a candidate-bound human approval
receipt. Stop on target drift, unknown ownership, path escape, lease conflict,
or an effect count above the approved ceiling.

The public skills do not authorize a merge, direct `main` push, release,
external send, provider write, credential change, deletion, or visibility
change. Those are separate Work Order actions.

## 5. Receipt contract

An invocation emits a content-free JSON receipt (stdout or an artifact). Never
include raw conversations, secrets, cookies, tokens, or unredacted PII.

```json
{
  "schema_version": "kotodama.skill-receipt.v1",
  "skill": "<name>",
  "status": "COMPLETED|PARTIAL|BLOCKED|FAILED|UNKNOWN",
  "mode": "plan|dry-run|apply",
  "changed": false,
  "no_op": true,
  "evidence_tier": "LOCAL|DEVICE|PROVIDER|PUBLIC|HUMAN_GO",
  "target": {"identity_digest": "sha256:<hex>"},
  "source_revision": "<git revision or input digest>",
  "before_sha256": "sha256:<hex-or-null>",
  "after_sha256": "sha256:<hex-or-null>",
  "observed_at_utc": "<RFC3339>",
  "exit_code": 0,
  "actor": "<runtime-identity-or-UNKNOWN>",
  "model_verification": "OBSERVED:<id>|MODEL_UNVERIFIED|NOT_APPLICABLE",
  "approval_ref": null,
  "rollback_ref": "<artifact-or-null>",
  "evidence_refs": [],
  "effect_counts": {"files_changed": 0, "network_writes": 0, "external_sends": 0},
  "no_go_reasons": []
}
```

`COMPLETED` means the declared acceptance checks passed at the declared tier;
it does not promote the result to a higher tier. `UNKNOWN` is required when
identity, source, or verification cannot be established. `no_op=true` is a
successful result only when its reason and input digest are recorded.

## 6. Evidence gates

Evidence is monotonic and cannot be promoted by wording:

| Tier | Can prove | Cannot prove |
| --- | --- | --- |
| `LOCAL` | current bytes, schema, deterministic tests | device, provider, public availability, human decision |
| `DEVICE` | named device/host readback with identity and time | provider route, public E2E, Human GO |
| `PROVIDER` | provider/account/route/policy readback | functional public E2E or approval |
| `PUBLIC` | external authenticated functional E2E and origin verification | human decision or production promotion by itself |
| `HUMAN_GO` | identified human approved the exact candidate and time window | any missing technical receipt |

Health, HTTP 200, a static manifest, synthetic data, a local model response,
a tunnel-connected status, or a chat display is never provider/public/Human GO
evidence. Until independent receipts exist, retain `NO_GO_UNPUBLISHED`.

## 7. Bounded delegation

Delegation is work decomposition, not an authorization shortcut. The parent
records an edge ID, child owner, exact read/write scope, maximum depth,
cumulative fan-out budget, timeout, retry/cancel policy, and acceptance test.
Children default to read-only and isolated artifacts. They must return the
receipt shape above and must not merge, commit, publish, delete, or change
credentials unless the parent Work Order explicitly authorizes that exact
effect. A failed child makes the parent `PARTIAL` or `BLOCKED`; a summary must
not hide it with “all green”.

## 8. Privacy and recovery

- Accept repo-relative, allowlisted paths; resolve and check containment before
  opening or writing.
- Bound bytes, records, recursion, time, and network egress. Decode UTF-8
  explicitly; binary skips and replacement characters are receipt fields.
- Redact secrets and PII before logs, artifacts, or messages; retain a digest
  and locator rather than raw content.
- One canonical writer owns each fact family. Projections must not rewrite
  Current Truth. Use a lock/lease/fence and idempotency key for append, sync,
  channel, transcript, and index operations.
- Keep the pre-state on failure and emit a refusal or rollback receipt. Never
  use fail-open policy checks or “skip failures and continue to GO”.

## 9. Current primary sources

The public pack follows these current primary sources; re-check them when a
runtime changes rather than copying an old model or CLI claim:

- [OpenAI Skills](https://developers.openai.com/api/docs/guides/tools-skills#what-is-a-skill)
- [OpenAI skill-creator](https://github.com/openai/skills/blob/main/skills/.system/skill-creator/SKILL.md)
- [OpenAI AGENTS.md discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md#how-codex-discovers-guidance)
- [OpenAI subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Claude Code skills](https://code.claude.com/docs/en/skills)
- [Claude Code sub-agents](https://code.claude.com/docs/en/sub-agents)

These links describe external runtimes. The evidence tiers, public preview
boundary, canonical-writer rule, and `NO_GO_UNPUBLISHED` state are Kotodama
project policy.

## 10. Refresh checklist

- [ ] `name` and `description` parse; triggers and non-triggers are distinct.
- [ ] Description begins with the Kotodama public-repository scope phrase, and
      every procedure step has its own `Done when:` criterion.
- [ ] Declared external skill catalogs have no duplicate public name or exact
      description; undeclared catalogs are explicitly outside the audit claim.
- [ ] Every command, if any, exists in the target checkout and has UTF-8 and
      Windows guidance; otherwise the skill is explicitly explanatory.
- [ ] Scope, mode, owner, approval, effect ceiling, and dirty baseline are
      explicit.
- [ ] Completion includes status, changed/no-op, exit code, digest, timestamp,
      evidence tier, and no-go reasons.
- [ ] Failure, retry, lock, idempotency, and rollback behavior is explicit.
- [ ] Fixed model/version claims are absent unless runtime evidence is attached.
- [ ] Health/static/synthetic results cannot promote provider/public/Human GO.
- [ ] A fresh read-only review can follow the skill without hidden context.
